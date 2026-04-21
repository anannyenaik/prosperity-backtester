from __future__ import annotations

import csv
import json
import math
import random
import statistics
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .datamodel import Listing, Observation, Order, OrderDepth, Trade, TradingState
from .dataset import BookSnapshot, DayDataset, TradePrint
from .behavior import analyse_behaviour
from .fair_value import infer_market_fair_rows, summarize_fair_rows
from .fill_models import FillModel, resolve_fill_model
from .metadata import CURRENCY, DEFAULT_POSITION_LIMIT, PRODUCTS, PRODUCT_METADATA
from .round2 import AccessScenario, NO_ACCESS_SCENARIO
from .simulate import build_samplers, load_calibration, make_book, sample_trade_counts, sample_trade_quantity, simulate_latent_fair


@dataclass
class PerturbationConfig:
    passive_fill_scale: float = 1.0
    missed_fill_additive: float = 0.0
    spread_shift_ticks: int = 0
    order_book_volume_scale: float = 1.0
    price_noise_std: float = 0.0
    latent_price_noise_by_product: Dict[str, float] = field(default_factory=dict)
    latent_noise_scale: float = 1.0
    pepper_slope_scale: float = 1.0
    latency_ticks: int = 0
    adverse_selection_ticks: int = 0
    slippage_multiplier: float = 1.0
    reentry_probability: float = 1.0
    trade_matching_mode: str = "all"
    inventory_limit_scale: float = 1.0
    synthetic_tick_limit: Optional[int] = None
    shock_tick: Optional[int] = None
    shock_by_product: Dict[str, float] = field(default_factory=dict)
    scenario_name: str = "custom"

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    def book_noise_for(self, product: str) -> float:
        return max(0.0, float(self.price_noise_std))

    def latent_noise_for(self, product: str) -> float:
        value = float(self.latent_price_noise_by_product.get(product, 0.0))
        return max(0.0, value * max(0.0, float(self.latent_noise_scale)))

    def shock_for(self, product: str) -> float:
        return float(self.shock_by_product.get(product, 0.0))

    def passive_trade_matching_mode(self) -> str:
        mode = str(self.trade_matching_mode or "all").strip().lower()
        if mode not in {"all", "worse", "none"}:
            raise ValueError("trade_matching_mode must be one of: all, worse, none")
        return mode


@dataclass
class ProductLedger:
    position: int = 0
    cash: float = 0.0
    realised: float = 0.0
    avg_entry_price: float = 0.0

    def apply_buy(self, price: int, qty: int) -> None:
        self.cash -= price * qty
        if qty <= 0:
            return
        if self.position >= 0:
            total_cost = self.avg_entry_price * self.position + price * qty
            self.position += qty
            self.avg_entry_price = total_cost / self.position if self.position else 0.0
            return
        cover = min(qty, -self.position)
        self.realised += (self.avg_entry_price - price) * cover
        self.position += cover
        remaining = qty - cover
        if self.position == 0:
            self.avg_entry_price = 0.0
        if remaining > 0:
            self.position = remaining
            self.avg_entry_price = float(price)

    def apply_sell(self, price: int, qty: int) -> None:
        self.cash += price * qty
        if qty <= 0:
            return
        if self.position <= 0:
            total_abs = abs(self.position)
            total_proceeds_like_price = self.avg_entry_price * total_abs + price * qty
            self.position -= qty
            self.avg_entry_price = total_proceeds_like_price / abs(self.position) if self.position else 0.0
            return
        close = min(qty, self.position)
        self.realised += (price - self.avg_entry_price) * close
        self.position -= close
        remaining = qty - close
        if self.position == 0:
            self.avg_entry_price = 0.0
        if remaining > 0:
            self.position = -remaining
            self.avg_entry_price = float(price)

    def unrealised(self, mark: Optional[float]) -> float:
        if mark is None or self.position == 0:
            return 0.0
        if self.position > 0:
            return (mark - self.avg_entry_price) * self.position
        return (self.avg_entry_price - mark) * abs(self.position)

    def mtm(self, mark: Optional[float]) -> float:
        if mark is None:
            return self.realised
        return self.cash + self.position * mark


@dataclass
class SessionArtefacts:
    run_name: str
    trader_name: str
    mode: str
    fill_model: Dict[str, object]
    perturbations: Dict[str, object]
    summary: Dict[str, object]
    session_rows: List[Dict[str, object]]
    orders: List[Dict[str, object]] = field(default_factory=list)
    fills: List[Dict[str, object]] = field(default_factory=list)
    inventory_series: List[Dict[str, object]] = field(default_factory=list)
    pnl_series: List[Dict[str, object]] = field(default_factory=list)
    validation: Dict[str, object] = field(default_factory=dict)
    fair_value_series: List[Dict[str, object]] = field(default_factory=list)
    fair_value_summary: Dict[str, object] = field(default_factory=dict)
    behaviour: Dict[str, object] = field(default_factory=dict)
    behaviour_series: List[Dict[str, object]] = field(default_factory=list)
    access_scenario: Dict[str, object] = field(default_factory=dict)
    path_metrics: List[Dict[str, object]] = field(default_factory=list)


class OrderSchedule:
    def __init__(self):
        self._pending: Dict[int, Dict[str, List[Order]]] = {}

    def add(self, due_step: int, orders_by_product: Dict[str, List[Order]]) -> None:
        cloned: Dict[str, List[Order]] = {}
        for product, orders in orders_by_product.items():
            cloned[product] = [Order(order.symbol, int(order.price), int(order.quantity)) for order in orders]
        if due_step not in self._pending:
            self._pending[due_step] = cloned
            return
        for product, orders in cloned.items():
            self._pending[due_step].setdefault(product, []).extend(orders)

    def pop(self, step: int) -> Dict[str, List[Order]]:
        return self._pending.pop(step, {p: [] for p in PRODUCTS})


def snapshot_to_order_depth(snapshot: BookSnapshot) -> OrderDepth:
    depth = OrderDepth()
    for price, volume in snapshot.bids:
        depth.buy_orders[int(price)] = int(volume)
    for price, volume in snapshot.asks:
        depth.sell_orders[int(price)] = -int(volume)
    return depth


def _scaled_snapshot(
    snapshot: BookSnapshot,
    rng: random.Random,
    perturb: PerturbationConfig,
    access_volume_multiplier: float = 1.0,
) -> BookSnapshot:
    book_noise_std = perturb.book_noise_for(snapshot.product)

    def scale_levels(levels: Sequence[Tuple[int, int]], is_bid: bool) -> List[Tuple[int, int]]:
        out: List[Tuple[int, int]] = []
        for price, volume in levels:
            shifted = price - perturb.spread_shift_ticks if is_bid else price + perturb.spread_shift_ticks
            noisy = shifted + int(round(rng.gauss(0.0, book_noise_std))) if book_noise_std > 0 else shifted
            scaled_volume = max(0, int(round(volume * perturb.order_book_volume_scale * access_volume_multiplier)))
            if scaled_volume > 0:
                out.append((noisy, scaled_volume))
        out.sort(key=lambda item: -item[0] if is_bid else item[0])
        return out

    bids = scale_levels(snapshot.bids, True)
    asks = scale_levels(snapshot.asks, False)
    mid = snapshot.mid
    if bids and asks:
        mid = (bids[0][0] + asks[0][0]) / 2.0
    ref = snapshot.reference_fair
    if ref is not None and book_noise_std > 0:
        ref = ref + rng.gauss(0.0, book_noise_std)
    return BookSnapshot(
        timestamp=snapshot.timestamp,
        product=snapshot.product,
        bids=bids,
        asks=asks,
        mid=mid,
        reference_fair=ref,
        source_day=snapshot.source_day,
    )


def _position_limit_for(product: str, perturb: PerturbationConfig) -> int:
    base = PRODUCT_METADATA[product].position_limit
    return max(1, int(round(base * perturb.inventory_limit_scale)))


def _market_sell_trade(trade: TradePrint) -> bool:
    return bool(trade.seller) and not bool(trade.buyer)


def _market_buy_trade(trade: TradePrint) -> bool:
    return bool(trade.buyer) and not bool(trade.seller)


def _consume_passive_trades(
    product: str,
    timestamp: int,
    order: Order,
    side: str,
    remaining_qty: int,
    snapshot: BookSnapshot,
    available_trades: List[TradePrint],
    ledger: ProductLedger,
    fill_model: FillModel,
    perturb: PerturbationConfig,
    access_scenario: AccessScenario,
    access_extra_fraction: float,
    rng: random.Random,
    fills_out: List[Dict[str, object]],
) -> int:
    if remaining_qty <= 0:
        return 0
    trade_matching_mode = perturb.passive_trade_matching_mode()
    if trade_matching_mode == "none":
        return 0
    product_config, fill_regime = fill_model.config_for(product, snapshot.bids, snapshot.asks)
    effective_fill_rate = max(
        0.0,
        product_config.passive_fill_rate
        * fill_model.fill_rate_multiplier
        * perturb.passive_fill_scale
        * access_scenario.passive_rate_multiplier(access_extra_fraction)
        + access_scenario.passive_rate_bonus(access_extra_fraction),
    )
    effective_miss_prob = min(
        1.0,
        max(
            0.0,
            product_config.missed_fill_probability
            + fill_model.missed_fill_additive
            + perturb.missed_fill_additive
            - access_scenario.effective_missed_fill_reduction(access_extra_fraction),
        ),
    )
    if effective_fill_rate <= 0 or rng.random() < effective_miss_prob:
        return 0

    if side == "buy":
        better_depth = sum(v for p, v in snapshot.bids if p > order.price)
        same_depth = sum(v for p, v in snapshot.bids if p == order.price)
        eligible = [
            trade
            for trade in available_trades
            if _market_sell_trade(trade)
            and trade.quantity > 0
            and (trade.price <= order.price if trade_matching_mode == "all" else trade.price < order.price)
        ]
        same_side_depth = better_depth + product_config.same_price_queue_share * same_depth
        adverse_ticks = product_config.passive_adverse_selection_ticks + perturb.adverse_selection_ticks
        execution_price = int(round(order.price + adverse_ticks))
    else:
        better_depth = sum(v for p, v in snapshot.asks if p < order.price)
        same_depth = sum(v for p, v in snapshot.asks if p == order.price)
        eligible = [
            trade
            for trade in available_trades
            if _market_buy_trade(trade)
            and trade.quantity > 0
            and (trade.price >= order.price if trade_matching_mode == "all" else trade.price > order.price)
        ]
        same_side_depth = better_depth + product_config.same_price_queue_share * same_depth
        adverse_ticks = product_config.passive_adverse_selection_ticks + perturb.adverse_selection_ticks
        execution_price = int(round(order.price - adverse_ticks))

    eligible_volume = sum(trade.quantity for trade in eligible)
    if eligible_volume <= 0:
        return 0

    queue_factor = remaining_qty / max(1.0, remaining_qty + product_config.queue_pressure * same_side_depth)
    target = min(remaining_qty, int(round(eligible_volume * effective_fill_rate * queue_factor)))
    if target <= 0:
        return 0

    filled = 0
    for trade in eligible:
        if filled >= target:
            break
        take = min(target - filled, trade.quantity)
        if take <= 0:
            continue
        trade.quantity -= take
        filled += take
        if side == "buy":
            ledger.apply_buy(execution_price, take)
            fills_out.append({
                "timestamp": timestamp,
                "product": product,
                "side": "buy",
                "price": execution_price,
                "quantity": take,
                "kind": "passive_approx",
                "exact": False,
                "reference_price": order.price,
                "source_trade_price": trade.price,
                "slippage_ticks": execution_price - int(order.price),
                "size_slippage_ticks": 0.0,
                "adverse_selection_ticks": adverse_ticks,
                "fill_regime": fill_regime,
                "access_scenario": access_scenario.name,
                "access_active": access_extra_fraction > 0,
                "access_extra_fraction": access_extra_fraction,
            })
        else:
            ledger.apply_sell(execution_price, take)
            fills_out.append({
                "timestamp": timestamp,
                "product": product,
                "side": "sell",
                "price": execution_price,
                "quantity": take,
                "kind": "passive_approx",
                "exact": False,
                "reference_price": order.price,
                "source_trade_price": trade.price,
                "slippage_ticks": int(order.price) - execution_price,
                "size_slippage_ticks": 0.0,
                "adverse_selection_ticks": adverse_ticks,
                "fill_regime": fill_regime,
                "access_scenario": access_scenario.name,
                "access_active": access_extra_fraction > 0,
                "access_extra_fraction": access_extra_fraction,
            })
    return filled


def _execute_order_batch(
    timestamp: int,
    product: str,
    snapshot: BookSnapshot,
    trades: List[TradePrint],
    ledger: ProductLedger,
    orders: List[Order],
    fill_model: FillModel,
    perturb: PerturbationConfig,
    access_scenario: AccessScenario,
    access_extra_fraction: float,
    rng: random.Random,
) -> Tuple[List[Dict[str, object]], List[TradePrint], int]:
    bids = [[price, volume] for price, volume in snapshot.bids]
    asks = [[price, volume] for price, volume in snapshot.asks]
    fills: List[Dict[str, object]] = []
    limit_breaches = 0
    position_limit = _position_limit_for(product, perturb)
    total_buy = sum(max(0, int(order.quantity)) for order in orders)
    total_sell = sum(max(0, -int(order.quantity)) for order in orders)
    if ledger.position + total_buy > position_limit or ledger.position - total_sell < -position_limit:
        return fills, trades, 1

    passive_candidates: List[Tuple[str, Order, int]] = []
    exact_visible_fill = not access_scenario.has_access_effect(access_extra_fraction)
    product_config, fill_regime = fill_model.config_for(product, snapshot.bids, snapshot.asks)
    for order in orders:
        qty = int(order.quantity)
        if qty == 0:
            continue
        if qty > 0:
            remaining = qty
            while remaining > 0 and asks and asks[0][0] <= order.price:
                ask_price, ask_qty = asks[0]
                fill_qty = min(remaining, ask_qty)
                size_slippage = product_config.size_slippage_ticks(fill_qty)
                flat_slippage = product_config.aggressive_slippage_ticks + product_config.aggressive_adverse_selection_ticks
                total_slippage = int(round((flat_slippage + size_slippage) * fill_model.slippage_multiplier * perturb.slippage_multiplier))
                exec_price = ask_price + total_slippage
                ledger.apply_buy(exec_price, fill_qty)
                fills.append({
                    "timestamp": timestamp,
                    "product": product,
                    "side": "buy",
                    "price": exec_price,
                    "quantity": fill_qty,
                    "kind": "aggressive_visible" if exact_visible_fill else "aggressive_access_assumption",
                    "exact": exact_visible_fill,
                    "reference_price": ask_price,
                    "source_trade_price": ask_price,
                    "slippage_ticks": total_slippage,
                    "size_slippage_ticks": size_slippage,
                    "adverse_selection_ticks": product_config.aggressive_adverse_selection_ticks,
                    "fill_regime": fill_regime,
                    "access_scenario": access_scenario.name,
                    "access_active": access_extra_fraction > 0,
                    "access_extra_fraction": access_extra_fraction,
                })
                remaining -= fill_qty
                ask_qty -= fill_qty
                if ask_qty == 0:
                    asks.pop(0)
                else:
                    asks[0][1] = ask_qty
            if remaining > 0 and rng.random() <= perturb.reentry_probability:
                passive_candidates.append(("buy", Order(product, int(order.price), remaining), remaining))
        else:
            remaining = -qty
            while remaining > 0 and bids and bids[0][0] >= order.price:
                bid_price, bid_qty = bids[0]
                fill_qty = min(remaining, bid_qty)
                size_slippage = product_config.size_slippage_ticks(fill_qty)
                flat_slippage = product_config.aggressive_slippage_ticks + product_config.aggressive_adverse_selection_ticks
                total_slippage = int(round((flat_slippage + size_slippage) * fill_model.slippage_multiplier * perturb.slippage_multiplier))
                exec_price = bid_price - total_slippage
                ledger.apply_sell(exec_price, fill_qty)
                fills.append({
                    "timestamp": timestamp,
                    "product": product,
                    "side": "sell",
                    "price": exec_price,
                    "quantity": fill_qty,
                    "kind": "aggressive_visible" if exact_visible_fill else "aggressive_access_assumption",
                    "exact": exact_visible_fill,
                    "reference_price": bid_price,
                    "source_trade_price": bid_price,
                    "slippage_ticks": total_slippage,
                    "size_slippage_ticks": size_slippage,
                    "adverse_selection_ticks": product_config.aggressive_adverse_selection_ticks,
                    "fill_regime": fill_regime,
                    "access_scenario": access_scenario.name,
                    "access_active": access_extra_fraction > 0,
                    "access_extra_fraction": access_extra_fraction,
                })
                remaining -= fill_qty
                bid_qty -= fill_qty
                if bid_qty == 0:
                    bids.pop(0)
                else:
                    bids[0][1] = bid_qty
            if remaining > 0 and rng.random() <= perturb.reentry_probability:
                passive_candidates.append(("sell", Order(product, int(order.price), -remaining), remaining))

    passive_candidates.sort(key=lambda item: (-item[1].price if item[0] == "buy" else item[1].price, -item[2]))
    trade_volume_multiplier = access_scenario.trade_volume_multiplier(access_extra_fraction)
    working_trades = [TradePrint(**asdict(trade)) for trade in trades]
    if trade_volume_multiplier != 1.0:
        for trade in working_trades:
            trade.quantity = max(1, int(round(trade.quantity * trade_volume_multiplier)))
    passive_snapshot = BookSnapshot(
        timestamp=snapshot.timestamp,
        product=snapshot.product,
        bids=[(p, q) for p, q in bids],
        asks=[(p, q) for p, q in asks],
        mid=snapshot.mid,
        reference_fair=snapshot.reference_fair,
        source_day=snapshot.source_day,
    )
    for side, order, remaining in passive_candidates:
        _consume_passive_trades(
            product=product,
            timestamp=timestamp,
            order=order,
            side=side,
            remaining_qty=remaining,
            snapshot=passive_snapshot,
            available_trades=working_trades,
            ledger=ledger,
            fill_model=fill_model,
            perturb=perturb,
            access_scenario=access_scenario,
            access_extra_fraction=access_extra_fraction,
            rng=rng,
            fills_out=fills,
        )

    residual_trades = [trade for trade in working_trades if trade.quantity > 0]
    return fills, residual_trades, limit_breaches


def _record_series_row(timestamp: int, product: str, ledger: ProductLedger, snapshot: BookSnapshot) -> Tuple[Dict[str, object], Dict[str, object]]:
    mark = snapshot.reference_fair if snapshot.reference_fair is not None else snapshot.mid
    spread = None
    if snapshot.bids and snapshot.asks:
        spread = snapshot.asks[0][0] - snapshot.bids[0][0]
    pnl_row = {
        "timestamp": timestamp,
        "product": product,
        "cash": ledger.cash,
        "realised": ledger.realised,
        "unrealised": ledger.unrealised(mark),
        "mtm": ledger.mtm(mark),
        "mark": mark,
        "mid": snapshot.mid,
        "fair": snapshot.reference_fair,
        "spread": spread,
        "position": ledger.position,
    }
    inventory_row = {
        "timestamp": timestamp,
        "product": product,
        "position": ledger.position,
        "avg_entry_price": ledger.avg_entry_price,
        "mid": snapshot.mid,
        "fair": snapshot.reference_fair,
    }
    return pnl_row, inventory_row


def _path_bucket_ranges(length: int, bucket_count: int) -> List[tuple[int, int]]:
    if length <= 0:
        return []
    bucket_count = max(1, min(bucket_count, length))
    ranges = []
    start = 0
    for bucket in range(bucket_count):
        end = round((bucket + 1) * length / bucket_count)
        end = max(start + 1, min(length, end))
        ranges.append((start, end))
        start = end
    return ranges


def _path_metric_rows(
    *,
    inventory_series: Sequence[Dict[str, object]],
    pnl_series: Sequence[Dict[str, object]],
    fair_rows: Sequence[Dict[str, object]],
    max_rows_per_product: int,
) -> List[Dict[str, object]]:
    pnl_lookup = {(int(row["day"]), str(row["product"]), int(row["timestamp"])): row for row in pnl_series}
    fair_lookup = {(int(row["day"]), str(row["product"]), int(row["timestamp"])): row for row in fair_rows}
    by_product_day: Dict[tuple[str, int], List[Dict[str, object]]] = {}
    for inv in inventory_series:
        product = str(inv["product"])
        day = int(inv["day"])
        timestamp = int(inv["timestamp"])
        pnl = pnl_lookup.get((day, product, timestamp), {})
        fair = fair_lookup.get((day, product, timestamp), {})
        by_product_day.setdefault((product, day), []).append({
            "day": day,
            "timestamp": timestamp,
            "product": product,
            "analysis_fair": fair.get("analysis_fair"),
            "mid": fair.get("mid", inv.get("mid")),
            "inventory": inv.get("position"),
            "pnl": pnl.get("mtm"),
        })

    output: List[Dict[str, object]] = []
    bucket_index_by_product = {product: 0 for product in PRODUCTS}
    days_by_product: Dict[str, List[int]] = {}
    for product, day in by_product_day:
        days_by_product.setdefault(product, []).append(day)

    for product in PRODUCTS:
        days = sorted(set(days_by_product.get(product, [])))
        if not days:
            continue
        per_day_limit = 0 if max_rows_per_product <= 0 else max(1, max_rows_per_product // len(days))
        for day in days:
            rows = sorted(by_product_day[(product, day)], key=lambda row: int(row["timestamp"]))
            ranges = (
                [(idx, idx + 1) for idx in range(len(rows))]
                if per_day_limit <= 0 or len(rows) <= per_day_limit
                else _path_bucket_ranges(len(rows), per_day_limit)
            )
            for start, end in ranges:
                bucket_rows = rows[start:end]
                last = dict(bucket_rows[-1])
                last["bucket_index"] = bucket_index_by_product[product]
                last["bucket_start_timestamp"] = bucket_rows[0]["timestamp"]
                last["bucket_end_timestamp"] = bucket_rows[-1]["timestamp"]
                last["bucket_count"] = len(bucket_rows)
                for metric in ("analysis_fair", "mid", "inventory", "pnl"):
                    values = [
                        float(row[metric])
                        for row in bucket_rows
                        if row.get(metric) is not None
                    ]
                    if not values:
                        continue
                    last[f"{metric}_bucket_min"] = min(values)
                    last[f"{metric}_bucket_max"] = max(values)
                    last[f"{metric}_bucket_last"] = values[-1]
                output.append(last)
                bucket_index_by_product[product] += 1
    return output

def _apply_fill_markouts(
    fills_log: List[Dict[str, object]],
    fair_rows: Sequence[Dict[str, object]],
) -> None:
    by_product_day: Dict[tuple[int, str], List[Dict[str, object]]] = {}
    for row in fair_rows:
        by_product_day.setdefault((int(row["day"]), str(row["product"])), []).append(row)
    lookup: Dict[tuple[int, str, int], tuple[int, List[Dict[str, object]]]] = {}
    for key, rows in by_product_day.items():
        rows.sort(key=lambda item: int(item["timestamp"]))
        index_by_ts = {int(row["timestamp"]): idx for idx, row in enumerate(rows)}
        for ts, idx in index_by_ts.items():
            lookup[(key[0], key[1], ts)] = (idx, rows)

    for row in fills_log:
        key = (int(row["day"]), str(row["product"]), int(row["timestamp"]))
        entry = lookup.get(key)
        row["markout_1"] = None
        row["markout_5"] = None
        if entry is None:
            continue
        idx, rows = entry
        base = rows[idx].get("analysis_fair")
        if base is None:
            continue
        for horizon in (1, 5):
            target_idx = min(len(rows) - 1, idx + horizon)
            future = rows[target_idx].get("analysis_fair")
            if future is None:
                continue
            if row.get("side") == "buy":
                value = float(future) - float(row["price"])
            else:
                value = float(row["price"]) - float(future)
            row[f"markout_{horizon}"] = value


def _summarise_slippage(fills_log: Sequence[Dict[str, object]]) -> Dict[str, object]:
    per_product: Dict[str, Dict[str, object]] = {
        product: {
            "slippage_cost": 0.0,
            "slippage_qty": 0,
            "slippage_fill_count": 0,
            "average_slippage_ticks": 0.0,
            "average_size_slippage_ticks": 0.0,
            "size_slippage_tick_qty": 0.0,
            "aggressive_slippage_cost": 0.0,
            "passive_adverse_cost": 0.0,
        }
        for product in PRODUCTS
    }
    total_cost = 0.0
    total_qty = 0
    total_size_ticks = 0.0
    total_slip_ticks = 0.0
    for row in fills_log:
        product = str(row.get("product"))
        if product not in per_product:
            continue
        qty = abs(int(row.get("quantity", 0)))
        slip_ticks = float(row.get("slippage_ticks") or 0.0)
        size_ticks = float(row.get("size_slippage_ticks") or 0.0)
        cost = slip_ticks * qty
        bucket = per_product[product]
        bucket["slippage_cost"] = float(bucket["slippage_cost"]) + cost
        bucket["slippage_qty"] = int(bucket["slippage_qty"]) + qty
        bucket["slippage_fill_count"] = int(bucket["slippage_fill_count"]) + 1
        bucket["size_slippage_tick_qty"] = float(bucket["size_slippage_tick_qty"]) + size_ticks * qty
        if str(row.get("kind", "")).startswith("aggressive"):
            bucket["aggressive_slippage_cost"] = float(bucket["aggressive_slippage_cost"]) + cost
        else:
            bucket["passive_adverse_cost"] = float(bucket["passive_adverse_cost"]) + cost
        total_cost += cost
        total_qty += qty
        total_slip_ticks += slip_ticks * qty
        total_size_ticks += size_ticks * qty
    for bucket in per_product.values():
        qty = int(bucket["slippage_qty"])
        if qty > 0:
            bucket["average_slippage_ticks"] = float(bucket["slippage_cost"]) / qty
            bucket["average_size_slippage_ticks"] = float(bucket["size_slippage_tick_qty"]) / qty
    return {
        "total_slippage_cost": total_cost,
        "total_slippage_qty": total_qty,
        "average_slippage_ticks": 0.0 if total_qty == 0 else total_slip_ticks / total_qty,
        "average_size_slippage_ticks": 0.0 if total_qty == 0 else total_size_ticks / total_qty,
        "per_product": per_product,
    }




def run_market_session(
    trader,
    trader_name: str,
    market_days: Sequence[DayDataset],
    fill_model: FillModel,
    perturb: PerturbationConfig,
    rng: random.Random,
    run_name: str,
    mode: str,
    capture_full_output: bool = True,
    capture_path_metrics: bool = False,
    path_bucket_count: int = 800,
    access_scenario: AccessScenario | None = None,
) -> SessionArtefacts:
    access_scenario = access_scenario or NO_ACCESS_SCENARIO
    ledgers = {product: ProductLedger() for product in PRODUCTS}
    trader_data = ""
    prev_own_trades = {product: [] for product in PRODUCTS}
    prev_market_trades = {product: [] for product in PRODUCTS}
    schedule = OrderSchedule()
    orders_log: List[Dict[str, object]] = []
    fills_log: List[Dict[str, object]] = []
    inventory_series: List[Dict[str, object]] = []
    pnl_series: List[Dict[str, object]] = []
    session_rows: List[Dict[str, object]] = []
    total_limit_breaches = 0
    global_step = 0

    for day_dataset in market_days:
        for ts in day_dataset.timestamps:
            tick_snapshots: Dict[str, BookSnapshot] = {}
            tick_access_fractions: Dict[str, float] = {}
            for product in PRODUCTS:
                original_snapshot = day_dataset.books_by_timestamp.get(ts, {}).get(product)
                access_extra_fraction = access_scenario.active_extra_fraction(rng)
                tick_access_fractions[product] = access_extra_fraction
                access_volume_multiplier = access_scenario.book_volume_multiplier(access_extra_fraction)
                tick_snapshots[product] = (
                    _scaled_snapshot(original_snapshot, rng, perturb, access_volume_multiplier)
                    if original_snapshot
                    else BookSnapshot(ts, product, [], [], None)
                )
            state = TradingState(
                traderData=trader_data,
                timestamp=ts,
                listings={product: Listing(product, product, CURRENCY) for product in PRODUCTS},
                order_depths={
                    product: snapshot_to_order_depth(tick_snapshots[product])
                    for product in PRODUCTS
                },
                own_trades=prev_own_trades,
                market_trades=prev_market_trades,
                position={product: ledgers[product].position for product in PRODUCTS},
                observations=Observation({}, {}),
            )
            result = trader.run(state)
            if not isinstance(result, tuple) or len(result) != 3:
                raise RuntimeError(f"Trader returned unexpected result at {ts}: {result!r}")
            submitted_orders_raw, conversions, trader_data = result
            submitted_orders = {product: list(submitted_orders_raw.get(product, [])) if submitted_orders_raw else [] for product in PRODUCTS}
            due_step = global_step + max(0, int(perturb.latency_ticks))
            schedule.add(due_step, submitted_orders)
            due_orders = schedule.pop(global_step)

            own_trades_tick = {product: [] for product in PRODUCTS}
            market_trades_tick = {product: [] for product in PRODUCTS}

            for product in PRODUCTS:
                snapshot = tick_snapshots[product]
                access_extra_fraction = tick_access_fractions[product]
                trades = deepcopy(day_dataset.trades_by_timestamp.get(ts, {}).get(product, []))
                product_fills, residual_trades, limit_breach = _execute_order_batch(
                    timestamp=ts,
                    product=product,
                    snapshot=snapshot,
                    trades=trades,
                    ledger=ledgers[product],
                    orders=due_orders.get(product, []),
                    fill_model=fill_model,
                    perturb=perturb,
                    access_scenario=access_scenario,
                    access_extra_fraction=access_extra_fraction,
                    rng=rng,
                )
                total_limit_breaches += limit_breach

                best_bid = snapshot.bids[0][0] if snapshot.bids else None
                best_ask = snapshot.asks[0][0] if snapshot.asks else None
                _product_config, fill_regime = fill_model.config_for(product, snapshot.bids, snapshot.asks)
                for order in due_orders.get(product, []):
                    qty = int(order.quantity)
                    order_role = "passive"
                    distance_to_touch = None
                    if qty > 0 and best_ask is not None:
                        order_role = "aggressive" if int(order.price) >= int(best_ask) else "passive"
                        distance_to_touch = int(best_ask) - int(order.price)
                    elif qty < 0 and best_bid is not None:
                        order_role = "aggressive" if int(order.price) <= int(best_bid) else "passive"
                        distance_to_touch = int(order.price) - int(best_bid)
                    orders_log.append({
                        "timestamp": ts,
                        "product": product,
                        "submitted_price": int(order.price),
                        "submitted_quantity": qty,
                        "position_before": state.position.get(product, 0),
                        "fill_model": fill_model.name,
                        "latency_ticks": perturb.latency_ticks,
                        "day": day_dataset.day,
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "mid": snapshot.mid,
                        "reference_fair": snapshot.reference_fair,
                        "order_role": order_role,
                        "distance_to_touch": distance_to_touch,
                        "fill_regime": fill_regime,
                        "access_scenario": access_scenario.name,
                        "access_active": access_extra_fraction > 0,
                        "access_extra_fraction": access_extra_fraction,
                    })
                for fill in product_fills:
                    fill["day"] = day_dataset.day
                    fill["mid"] = snapshot.mid
                    fill["reference_fair"] = snapshot.reference_fair
                    fill["best_bid"] = best_bid
                    fill["best_ask"] = best_ask
                    fills_log.append(fill)
                    if fill["side"] == "buy":
                        own_trades_tick[product].append(Trade(product, fill["price"], fill["quantity"], "SUBMISSION", "BOT", ts))
                    else:
                        own_trades_tick[product].append(Trade(product, fill["price"], fill["quantity"], "BOT", "SUBMISSION", ts))

                for residual in residual_trades:
                    market_trades_tick[product].append(
                        Trade(residual.symbol, residual.price, residual.quantity, residual.buyer, residual.seller, residual.timestamp)
                    )

                pnl_row, inventory_row = _record_series_row(ts, product, ledgers[product], snapshot)
                pnl_row["day"] = day_dataset.day
                inventory_row["day"] = day_dataset.day
                pnl_series.append(pnl_row)
                inventory_series.append(inventory_row)

            prev_own_trades = own_trades_tick
            prev_market_trades = market_trades_tick
            global_step += 1

        maf_cost_for_row = access_scenario.maf_cost if day_dataset is market_days[-1] else 0.0
        gross_day_pnl = sum(ledgers[p].mtm(day_dataset.books_by_timestamp[day_dataset.timestamps[-1]].get(p).reference_fair if day_dataset.books_by_timestamp[day_dataset.timestamps[-1]].get(p) else None) for p in PRODUCTS)
        session_rows.append({
            "day": day_dataset.day,
            "final_pnl": gross_day_pnl - maf_cost_for_row,
            "gross_pnl_before_maf": gross_day_pnl,
            "maf_cost": maf_cost_for_row,
            "access_scenario": access_scenario.name,
            "osmium_pnl": ledgers["ASH_COATED_OSMIUM"].mtm(day_dataset.books_by_timestamp[day_dataset.timestamps[-1]].get("ASH_COATED_OSMIUM").reference_fair if day_dataset.books_by_timestamp[day_dataset.timestamps[-1]].get("ASH_COATED_OSMIUM") else None),
            "pepper_pnl": ledgers["INTARIAN_PEPPER_ROOT"].mtm(day_dataset.books_by_timestamp[day_dataset.timestamps[-1]].get("INTARIAN_PEPPER_ROOT").reference_fair if day_dataset.books_by_timestamp[day_dataset.timestamps[-1]].get("INTARIAN_PEPPER_ROOT") else None),
            "osmium_position": ledgers["ASH_COATED_OSMIUM"].position,
            "pepper_position": ledgers["INTARIAN_PEPPER_ROOT"].position,
        })

    final_marks: Dict[str, Optional[float]] = {}
    final_day = market_days[-1]
    final_ts = final_day.timestamps[-1]
    for product in PRODUCTS:
        snap = final_day.books_by_timestamp[final_ts].get(product)
        final_marks[product] = None if snap is None else (snap.reference_fair if snap.reference_fair is not None else snap.mid)
    slippage_summary = _summarise_slippage(fills_log)
    per_product_summary = {
        product: {
            "cash": ledgers[product].cash,
            "realised": ledgers[product].realised,
            "unrealised": ledgers[product].unrealised(final_marks[product]),
            "final_mtm": ledgers[product].mtm(final_marks[product]),
            "final_position": ledgers[product].position,
            "avg_entry_price": ledgers[product].avg_entry_price,
            "slippage_cost": slippage_summary["per_product"][product]["slippage_cost"],
            "average_slippage_ticks": slippage_summary["per_product"][product]["average_slippage_ticks"],
        }
        for product in PRODUCTS
    }
    fair_rows = infer_market_fair_rows(market_days)
    _apply_fill_markouts(fills_log, fair_rows)
    fair_lookup = {(int(row["day"]), str(row["product"]), int(row["timestamp"])): row for row in fair_rows}
    for row in orders_log:
        fair_row = fair_lookup.get((int(row["day"]), str(row["product"]), int(row["timestamp"])))
        analysis_fair = None if fair_row is None else fair_row.get("analysis_fair")
        row["analysis_fair"] = analysis_fair
        if analysis_fair is None:
            row["signed_edge_to_analysis_fair"] = None
        elif int(row["submitted_quantity"]) > 0:
            row["signed_edge_to_analysis_fair"] = float(analysis_fair) - float(row["submitted_price"])
        elif int(row["submitted_quantity"]) < 0:
            row["signed_edge_to_analysis_fair"] = float(row["submitted_price"]) - float(analysis_fair)
        else:
            row["signed_edge_to_analysis_fair"] = None
    for row in fills_log:
        fair_row = fair_lookup.get((int(row["day"]), str(row["product"]), int(row["timestamp"])))
        analysis_fair = None if fair_row is None else fair_row.get("analysis_fair")
        row["analysis_fair"] = analysis_fair
        if analysis_fair is None:
            row["signed_edge_to_analysis_fair"] = None
        elif row.get("side") == "buy":
            row["signed_edge_to_analysis_fair"] = float(analysis_fair) - float(row["price"])
        else:
            row["signed_edge_to_analysis_fair"] = float(row["price"]) - float(analysis_fair)

    fair_summary = summarize_fair_rows(fair_rows)
    behaviour = analyse_behaviour(
        orders=orders_log,
        fills=fills_log,
        inventory_series=inventory_series,
        pnl_series=pnl_series,
        fair_value_series=fair_rows,
        include_series=capture_full_output,
    )
    path_metrics = (
        _path_metric_rows(
            inventory_series=inventory_series,
            pnl_series=pnl_series,
            fair_rows=fair_rows,
            max_rows_per_product=max(0, int(path_bucket_count)),
        )
        if capture_path_metrics
        else []
    )
    total_series = {}
    for row in pnl_series:
        total_series.setdefault((int(row["day"]), int(row["timestamp"])), 0.0)
        total_series[(int(row["day"]), int(row["timestamp"]))] += float(row.get("mtm", 0.0))
    total_path = [value for _, value in sorted(total_series.items())]
    running_peak = float("-inf")
    max_drawdown = 0.0
    for value in total_path:
        running_peak = max(running_peak, value)
        max_drawdown = max(max_drawdown, running_peak - value)
    gross_final_pnl = sum(item["final_mtm"] for item in per_product_summary.values())
    maf_cost = access_scenario.maf_cost
    summary = {
        "final_pnl": gross_final_pnl - maf_cost,
        "gross_pnl_before_maf": gross_final_pnl,
        "maf_cost": maf_cost,
        "access_scenario": access_scenario.to_dict(),
        "fill_count": len(fills_log),
        "order_count": len(orders_log),
        "limit_breaches": total_limit_breaches,
        "max_drawdown": max_drawdown,
        "final_positions": {product: per_product_summary[product]["final_position"] for product in PRODUCTS},
        "per_product": per_product_summary,
        "slippage": slippage_summary,
        "fair_value": fair_summary,
        "behaviour": behaviour.get("summary", {}),
    }
    return SessionArtefacts(
        run_name=run_name,
        trader_name=trader_name,
        mode=mode,
        fill_model=fill_model.to_dict(),
        perturbations=perturb.to_dict(),
        summary=summary,
        session_rows=session_rows,
        orders=orders_log if capture_full_output else [],
        fills=fills_log if capture_full_output else [],
        inventory_series=inventory_series if capture_full_output else [],
        pnl_series=pnl_series if capture_full_output else [],
        validation={},
        fair_value_series=fair_rows if capture_full_output else [],
        fair_value_summary=fair_summary,
        behaviour=behaviour,
        behaviour_series=behaviour.get("series", []) if capture_full_output else [],
        access_scenario=access_scenario.to_dict(),
        path_metrics=path_metrics,
    )


def generate_synthetic_market_days(
    days: Sequence[int],
    seed: int,
    perturb: PerturbationConfig,
) -> List[DayDataset]:
    rng = random.Random(seed)
    calib = deepcopy(load_calibration())
    if "INTARIAN_PEPPER_ROOT" in calib:
        calib["INTARIAN_PEPPER_ROOT"]["drift_per_tick"] = calib["INTARIAN_PEPPER_ROOT"]["drift_per_tick"] * perturb.pepper_slope_scale
    for product in PRODUCTS:
        latent_noise = perturb.latent_noise_for(product)
        if latent_noise > 0:
            calib[product]["simulation_noise_std"] = latent_noise
    samplers = build_samplers(calib)
    market_days: List[DayDataset] = []
    last_latent: Dict[str, Optional[float]] = {product: None for product in PRODUCTS}
    tick_limit = None if perturb.synthetic_tick_limit in (None, 0) else max(1, int(perturb.synthetic_tick_limit))

    for session_day_index, day in enumerate(days):
        latent_paths = {
            product: simulate_latent_fair(product, calib, session_day_index, rng, continue_from=last_latent[product])
            for product in PRODUCTS
        }
        if tick_limit is not None:
            latent_paths = {
                product: path[:tick_limit]
                for product, path in latent_paths.items()
            }
        if perturb.shock_tick is not None:
            shock_tick = max(0, int(perturb.shock_tick))
            for product, path in latent_paths.items():
                shock = perturb.shock_for(product)
                if shock == 0.0 or shock_tick >= len(path):
                    continue
                for tick in range(shock_tick, len(path)):
                    path[tick] += shock
        trade_counts = {product: sample_trade_counts(product, calib, rng) for product in PRODUCTS}
        if tick_limit is not None:
            trade_counts = {
                product: counts[:tick_limit]
                for product, counts in trade_counts.items()
            }
        timestamps = [tick * 100 for tick in range(len(next(iter(latent_paths.values()))))]
        books_by_timestamp: Dict[int, Dict[str, BookSnapshot]] = {}
        trades_by_timestamp: Dict[int, Dict[str, List[TradePrint]]] = {}
        for tick, ts in enumerate(timestamps):
            books_by_timestamp[ts] = {}
            for product in PRODUCTS:
                book = make_book(product, latent_paths[product][tick], samplers, calib, rng)
                bids = list(book.bids)
                asks = list(book.asks)
                mid = (bids[0][0] + asks[0][0]) / 2.0 if bids and asks else None
                books_by_timestamp[ts][product] = BookSnapshot(
                    timestamp=ts,
                    product=product,
                    bids=bids,
                    asks=asks,
                    mid=mid,
                    reference_fair=latent_paths[product][tick],
                    source_day=day,
                )
                count = trade_counts[product][tick]
                for _ in range(count):
                    market_buy = rng.random() < calib[product]["trade_buy_prob"]
                    levels = asks if market_buy else bids
                    if not levels:
                        continue
                    trade_price = levels[0][0]
                    volume_limit = sum(level[1] for level in levels)
                    quantity = sample_trade_quantity(product, samplers, volume_limit, rng)
                    trade = TradePrint(
                        timestamp=ts,
                        buyer="BOT_TAKER" if market_buy else "",
                        seller="" if market_buy else "BOT_TAKER",
                        symbol=product,
                        price=int(trade_price),
                        quantity=int(quantity),
                        synthetic=True,
                    )
                    trades_by_timestamp.setdefault(ts, {}).setdefault(product, []).append(trade)
        for product in PRODUCTS:
            last_latent[product] = latent_paths[product][-1]
        market_days.append(
            DayDataset(
                day=day,
                timestamps=timestamps,
                books_by_timestamp=books_by_timestamp,
                trades_by_timestamp=trades_by_timestamp,
                validation={"timestamps": len(timestamps), "source": "synthetic", "price_rows": len(timestamps) * len(PRODUCTS), "trade_rows": sum(len(v) for by_p in trades_by_timestamp.values() for v in by_p.values())},
                metadata={"source": "synthetic", "seed": seed, "day": day},
            )
        )
    return market_days


def write_rows_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        with path.open("w", encoding="utf-8") as handle:
            handle.write("")
        return
    headers = []
    for row in rows:
        for key in row.keys():
            if key not in headers:
                headers.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def describe_series(artefact: SessionArtefacts) -> Dict[str, object]:
    return {
        "run_name": artefact.run_name,
        "trader_name": artefact.trader_name,
        "mode": artefact.mode,
        "final_pnl": artefact.summary["final_pnl"],
        "fill_count": artefact.summary["fill_count"],
        "limit_breaches": artefact.summary["limit_breaches"],
        "days": [row["day"] for row in artefact.session_rows],
        "per_product": artefact.summary["per_product"],
        "fill_model": artefact.fill_model,
        "perturbations": artefact.perturbations,
        "access_scenario": artefact.access_scenario,
        "gross_pnl_before_maf": artefact.summary.get("gross_pnl_before_maf"),
        "maf_cost": artefact.summary.get("maf_cost"),
        "fair_value_summary": artefact.fair_value_summary,
        "behaviour_summary": artefact.behaviour.get("summary", {}),
    }


def summarise_monte_carlo_sessions(session_artefacts: List[SessionArtefacts]) -> Dict[str, object]:
    pnl_values = [session.summary["final_pnl"] for session in session_artefacts]
    if not pnl_values:
        return {"session_count": 0}
    pnl_values_sorted = sorted(pnl_values)

    def quantile(q: float) -> float:
        if len(pnl_values_sorted) == 1:
            return pnl_values_sorted[0]
        idx = q * (len(pnl_values_sorted) - 1)
        lo = int(math.floor(idx))
        hi = int(math.ceil(idx))
        if lo == hi:
            return pnl_values_sorted[lo]
        w = idx - lo
        return pnl_values_sorted[lo] * (1 - w) + pnl_values_sorted[hi] * w

    per_product = {}
    for product in PRODUCTS:
        vals = [session.summary["per_product"][product]["final_mtm"] for session in session_artefacts]
        per_product[product] = {
            "mean": statistics.fmean(vals),
            "min": min(vals),
            "max": max(vals),
        }
    p05 = quantile(0.05)
    p25 = quantile(0.25)
    p75 = quantile(0.75)
    tail = [value for value in pnl_values if value <= p05]
    drawdowns = [float(session.summary.get("max_drawdown", 0.0)) for session in session_artefacts]
    gross_values = [float(session.summary.get("gross_pnl_before_maf", session.summary["final_pnl"])) for session in session_artefacts]
    maf_costs = [float(session.summary.get("maf_cost", 0.0)) for session in session_artefacts]
    return {
        "session_count": len(session_artefacts),
        "mean": statistics.fmean(pnl_values),
        "std": statistics.pstdev(pnl_values) if len(pnl_values) > 1 else 0.0,
        "p05": p05,
        "p25": p25,
        "p50": quantile(0.50),
        "p75": p75,
        "p95": quantile(0.95),
        "expected_shortfall_05": statistics.fmean(tail) if tail else p05,
        "min": min(pnl_values),
        "max": max(pnl_values),
        "gross_mean_before_maf": statistics.fmean(gross_values),
        "mean_maf_cost": statistics.fmean(maf_costs),
        "positive_rate": sum(1 for value in pnl_values if value > 0) / len(pnl_values),
        "mean_max_drawdown": statistics.fmean(drawdowns) if drawdowns else 0.0,
        "max_limit_breaches": max(int(session.summary.get("limit_breaches", 0)) for session in session_artefacts),
        "per_product": per_product,
    }
