from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from .dataset import DayDataset, load_round_dataset
from .metadata import get_round_spec
from .platform import write_rows_csv
from .round3 import (
    black_scholes_call_price,
    implied_vol_bisection,
    parse_voucher_symbol,
    tte_years,
)


UNDERLYING = "VELVETFRUIT_EXTRACT"
HYDROGEL = "HYDROGEL_PACK"
CENTRAL_VOUCHERS = ("VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500")
DEEP_ITM_VOUCHERS = ("VEV_4000", "VEV_4500")
FAR_OTM_VOUCHERS = ("VEV_6000", "VEV_6500")
MIN_RECOMMENDATION_COUNT = 30
MIN_NET_EDGE_TICKS = 0.15


@dataclass
class Observation:
    day: int
    timestamp: int
    product: str
    counterparty: str
    side: str
    quantity: int
    price_minus_mid: float
    signed_price_vs_mid: float
    spread: float
    aggressive: bool | None
    markouts: Dict[int, float] = field(default_factory=dict)


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = max(0.0, min(1.0, q)) * (len(ordered) - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return ordered[lo]
    weight = idx - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def _product_group(product: str) -> str:
    if product == HYDROGEL:
        return "hydrogel"
    if product == UNDERLYING:
        return "velvet"
    if product in DEEP_ITM_VOUCHERS:
        return "voucher_deep_itm"
    if product in CENTRAL_VOUCHERS:
        return "voucher_central"
    if product in FAR_OTM_VOUCHERS:
        return "voucher_far_otm"
    return "other"


def _best_bid_ask(snapshot) -> tuple[float | None, float | None]:
    bid = float(snapshot.bids[0][0]) if snapshot and snapshot.bids else None
    ask = float(snapshot.asks[0][0]) if snapshot and snapshot.asks else None
    return bid, ask


def _spread(snapshot) -> float | None:
    bid, ask = _best_bid_ask(snapshot)
    if bid is None or ask is None:
        return None
    return max(1.0, ask - bid)


def _side_observation(
    *,
    day: int,
    timestamp: int,
    product: str,
    counterparty: str,
    side: str,
    quantity: int,
    price: float,
    current_mid: float,
    snapshot,
    horizons: Sequence[int],
    mids_by_timestamp: Mapping[int, float],
    timestamp_step: int,
) -> Observation:
    bid, ask = _best_bid_ask(snapshot)
    price_minus_mid = float(price) - float(current_mid)
    signed_price_vs_mid = price_minus_mid if side == "buy" else -price_minus_mid
    if side == "buy":
        aggressive = None if ask is None else float(price) >= ask
    else:
        aggressive = None if bid is None else float(price) <= bid
    markouts: Dict[int, float] = {}
    for horizon in horizons:
        future_mid = mids_by_timestamp.get(int(timestamp) + int(horizon) * timestamp_step)
        if future_mid is None:
            continue
        move = float(future_mid) - float(current_mid)
        markouts[int(horizon)] = move if side == "buy" else -move
    return Observation(
        day=int(day),
        timestamp=int(timestamp),
        product=product,
        counterparty=counterparty,
        side=side,
        quantity=int(quantity),
        price_minus_mid=price_minus_mid,
        signed_price_vs_mid=signed_price_vs_mid,
        spread=float(_spread(snapshot) or 1.0),
        aggressive=aggressive,
        markouts=markouts,
    )


def _sample_flag(count: int) -> str:
    if count < 12:
        return "small"
    if count < 30:
        return "medium"
    return "ok"


def _summarise_observations(
    key: tuple,
    observations: Sequence[Observation],
    horizons: Sequence[int],
    *,
    pooled: bool,
) -> Dict[str, object]:
    count = len(observations)
    quantities = [obs.quantity for obs in observations]
    timestamp_counts: Dict[int, int] = {}
    for obs in observations:
        timestamp_counts[obs.timestamp] = timestamp_counts.get(obs.timestamp, 0) + 1
    without_clusters = [obs for obs in observations if timestamp_counts.get(obs.timestamp, 0) <= 1]
    without_largest = sorted(observations, key=lambda obs: obs.quantity, reverse=True)[5:] if count > 5 else []
    row = {
        "count": count,
        "buy_count": sum(1 for obs in observations if obs.side == "buy"),
        "sell_count": sum(1 for obs in observations if obs.side == "sell"),
        "average_size": _mean([float(qty) for qty in quantities]),
        "average_trade_price_vs_mid": _mean([obs.price_minus_mid for obs in observations]),
        "average_signed_price_vs_mid": _mean([obs.signed_price_vs_mid for obs in observations]),
        "aggressive_rate": _mean([1.0 if obs.aggressive else 0.0 for obs in observations if obs.aggressive is not None]),
        "average_spread": _mean([obs.spread for obs in observations]),
        "sample_flag": _sample_flag(count),
        "timestamp_cluster_count": sum(1 for value in timestamp_counts.values() if value > 1),
        "pooled": bool(pooled),
    }
    for horizon in horizons:
        values = [obs.markouts[int(horizon)] for obs in observations if int(horizon) in obs.markouts]
        weighted_num = sum(obs.markouts[int(horizon)] * obs.quantity for obs in observations if int(horizon) in obs.markouts)
        weighted_den = sum(obs.quantity for obs in observations if int(horizon) in obs.markouts)
        robust_values = [obs.markouts[int(horizon)] for obs in without_largest if int(horizon) in obs.markouts]
        cluster_values = [obs.markouts[int(horizon)] for obs in without_clusters if int(horizon) in obs.markouts]
        mean_value = _mean(values)
        spread_proxy = float(row["average_spread"] or 1.0) * 0.5 + 0.25
        row[f"markout_{horizon}"] = mean_value
        row[f"markout_{horizon}_weighted"] = None if weighted_den <= 0 else weighted_num / weighted_den
        row[f"markout_{horizon}_p05"] = _quantile(values, 0.05)
        row[f"markout_{horizon}_p95"] = _quantile(values, 0.95)
        row[f"markout_{horizon}_ex_largest5"] = _mean(robust_values)
        row[f"markout_{horizon}_ex_timestamp_clusters"] = _mean(cluster_values)
        row[f"raw_markout_{horizon}"] = mean_value
        row[f"estimated_spread_adverse_cost_{horizon}"] = spread_proxy
        row[f"net_follow_edge_{horizon}"] = None if mean_value is None else mean_value - spread_proxy
        row[f"net_fade_edge_{horizon}"] = None if mean_value is None else -mean_value - spread_proxy
        row[f"edge_after_cost_{horizon}"] = None if mean_value is None else mean_value - spread_proxy
    return row


def _mids_by_product(day_dataset: DayDataset) -> Dict[str, Dict[int, float]]:
    output: Dict[str, Dict[int, float]] = {product: {} for product in day_dataset.products}
    for timestamp in day_dataset.timestamps:
        for product, snapshot in day_dataset.books_by_timestamp.get(timestamp, {}).items():
            if snapshot.mid is not None:
                output.setdefault(product, {})[timestamp] = float(snapshot.mid)
    return output


def _bs_residual_cache(day_dataset: DayDataset, *, tte_days: int) -> Dict[tuple[int, str], float]:
    residuals: Dict[tuple[int, str], float] = {}
    t_years = tte_years(tte_days)
    for timestamp in day_dataset.timestamps:
        snapshots = day_dataset.books_by_timestamp.get(timestamp, {})
        underlying = snapshots.get(UNDERLYING)
        if underlying is None or underlying.mid is None:
            continue
        spot = float(underlying.mid)
        ivs: List[float] = []
        for symbol in CENTRAL_VOUCHERS:
            snapshot = snapshots.get(symbol)
            if snapshot is None or snapshot.mid is None:
                continue
            iv = implied_vol_bisection(float(snapshot.mid), spot, parse_voucher_symbol(symbol), t_years)
            if iv is not None and iv > 0.0:
                ivs.append(float(iv))
        if not ivs:
            continue
        centre_iv = statistics.median(ivs)
        for symbol in (*DEEP_ITM_VOUCHERS, *CENTRAL_VOUCHERS, *FAR_OTM_VOUCHERS):
            snapshot = snapshots.get(symbol)
            if snapshot is None or snapshot.mid is None:
                continue
            strike = parse_voucher_symbol(symbol)
            fair = black_scholes_call_price(spot, strike, t_years, centre_iv)
            residuals[(timestamp, symbol)] = float(snapshot.mid) - fair
    return residuals


def _build_product_side_rows(
    market_days: Sequence[DayDataset],
    horizons: Sequence[int],
) -> tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]]]:
    spec = get_round_spec(4)
    by_day: Dict[tuple[str, str, str, int], List[Observation]] = {}
    cross_by_day: Dict[tuple[str, str, str, str, str, str, int], List[Observation]] = {}
    for day_dataset in market_days:
        mids = _mids_by_product(day_dataset)
        residuals = _bs_residual_cache(
            day_dataset,
            tte_days=int(spec.tte_days_by_historical_day.get(day_dataset.day, spec.final_tte_days or 4)),
        )
        for timestamp in day_dataset.timestamps:
            trades_by_product = day_dataset.trades_by_timestamp.get(timestamp, {})
            for product, trades in trades_by_product.items():
                snapshot = day_dataset.books_by_timestamp.get(timestamp, {}).get(product)
                current_mid = mids.get(product, {}).get(timestamp)
                if snapshot is None or current_mid is None:
                    continue
                for trade in trades:
                    participants = (("buy", trade.buyer), ("sell", trade.seller))
                    for side, counterparty in participants:
                        if not counterparty:
                            continue
                        obs = _side_observation(
                            day=day_dataset.day,
                            timestamp=timestamp,
                            product=product,
                            counterparty=str(counterparty),
                            side=side,
                            quantity=trade.quantity,
                            price=trade.price,
                            current_mid=current_mid,
                            snapshot=snapshot,
                            horizons=horizons,
                            mids_by_timestamp=mids.get(product, {}),
                            timestamp_step=spec.timestamp_step,
                        )
                        by_day.setdefault((product, str(counterparty), side, day_dataset.day), []).append(obs)

                        target_products = [UNDERLYING] if product != HYDROGEL else [HYDROGEL]
                        if product == UNDERLYING or product.startswith("VEV_"):
                            target_products.extend([*DEEP_ITM_VOUCHERS, *CENTRAL_VOUCHERS, *FAR_OTM_VOUCHERS])
                        for target in target_products:
                            current_target = mids.get(target, {}).get(timestamp)
                            if current_target is None:
                                continue
                            target_snapshot = day_dataset.books_by_timestamp.get(timestamp, {}).get(target)
                            target_obs = _side_observation(
                                day=day_dataset.day,
                                timestamp=timestamp,
                                product=target,
                                counterparty=str(counterparty),
                                side=side,
                                quantity=trade.quantity,
                                price=current_target,
                                current_mid=current_target,
                                snapshot=target_snapshot,
                                horizons=horizons,
                                mids_by_timestamp=mids.get(target, {}),
                                timestamp_step=spec.timestamp_step,
                            )
                            cross_by_day.setdefault(
                                (_product_group(product), product, _product_group(target), target, "mid", str(counterparty), side, day_dataset.day),
                                [],
                            ).append(target_obs)

                            if target.startswith("VEV_") and (timestamp, target) in residuals:
                                residual_obs = Observation(
                                    day=day_dataset.day,
                                    timestamp=timestamp,
                                    product=target,
                                    counterparty=str(counterparty),
                                    side=side,
                                    quantity=trade.quantity,
                                    price_minus_mid=0.0,
                                    signed_price_vs_mid=0.0,
                                    spread=float(_spread(target_snapshot) or 1.0),
                                    aggressive=None,
                                )
                                current_residual = residuals[(timestamp, target)]
                                for horizon in horizons:
                                    future_ts = timestamp + int(horizon) * spec.timestamp_step
                                    future_residual = residuals.get((future_ts, target))
                                    if future_residual is None:
                                        continue
                                    move = future_residual - current_residual
                                    residual_obs.markouts[int(horizon)] = move if side == "buy" else -move
                                cross_by_day.setdefault(
                                    (_product_group(product), product, _product_group(target), target, "bs_residual", str(counterparty), side, day_dataset.day),
                                    [],
                                ).append(residual_obs)

    day_rows: List[Dict[str, object]] = []
    pooled_groups: Dict[tuple[str, str, str], List[Observation]] = {}
    for (product, counterparty, side, day), observations in sorted(by_day.items()):
        row = {
            "day": day,
            "product": product,
            "product_group": _product_group(product),
            "counterparty": counterparty,
            "side": side,
        }
        row.update(_summarise_observations((product, counterparty, side, day), observations, horizons, pooled=False))
        day_rows.append(row)
        pooled_groups.setdefault((product, counterparty, side), []).extend(observations)

    pooled_rows: List[Dict[str, object]] = []
    for (product, counterparty, side), observations in sorted(pooled_groups.items()):
        row = {
            "day": "pooled",
            "product": product,
            "product_group": _product_group(product),
            "counterparty": counterparty,
            "side": side,
        }
        row.update(_summarise_observations((product, counterparty, side), observations, horizons, pooled=True))
        row.update(_stability_fields(day_rows, product=product, counterparty=counterparty, side=side, horizon=20))
        pooled_rows.append(row)

    cross_rows: List[Dict[str, object]] = []
    cross_pooled: Dict[tuple[str, str, str, str, str, str, str], List[Observation]] = {}
    for key, observations in sorted(cross_by_day.items()):
        source_group, source_product, target_group, target_product, target_metric, counterparty, side, day = key
        row = {
            "day": day,
            "source_product_group": source_group,
            "source_product": source_product,
            "target_product_group": target_group,
            "target_product": target_product,
            "target_metric": target_metric,
            "counterparty": counterparty,
            "side": side,
        }
        row.update(_summarise_observations(key, observations, horizons, pooled=False))
        cross_rows.append(row)
        cross_pooled.setdefault(key[:-1], []).extend(observations)
    for key, observations in sorted(cross_pooled.items()):
        source_group, source_product, target_group, target_product, target_metric, counterparty, side = key
        row = {
            "day": "pooled",
            "source_product_group": source_group,
            "source_product": source_product,
            "target_product_group": target_group,
            "target_product": target_product,
            "target_metric": target_metric,
            "counterparty": counterparty,
            "side": side,
        }
        row.update(_summarise_observations(key, observations, horizons, pooled=True))
        cross_rows.append(row)
    return day_rows, pooled_rows, cross_rows


def _stability_fields(
    day_rows: Sequence[Mapping[str, object]],
    *,
    product: str,
    counterparty: str,
    side: str,
    horizon: int,
) -> Dict[str, object]:
    values: Dict[int, float | None] = {}
    for row in day_rows:
        if row.get("product") == product and row.get("counterparty") == counterparty and row.get("side") == side:
            day_value = row.get("day")
            if isinstance(day_value, int):
                values[day_value] = row.get(f"markout_{horizon}") if row.get(f"markout_{horizon}") is not None else None
    signs = [1 if value and value > 0 else -1 if value and value < 0 else 0 for value in values.values()]
    non_zero = [sign for sign in signs if sign != 0]
    if len(non_zero) >= 2 and all(sign == non_zero[0] for sign in non_zero):
        stability = "stable"
    elif len(non_zero) >= 2 and sum(1 for sign in non_zero if sign > 0) in (0, len(non_zero)):
        stability = "stable"
    elif len(non_zero) >= 2:
        stability = "mixed"
    else:
        stability = "insufficient"
    return {
        "day_1_markout": values.get(1),
        "day_2_markout": values.get(2),
        "day_3_markout": values.get(3),
        "stability": stability,
    }


def _recommendation_rows(pooled_rows: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for row in pooled_rows:
        count = int(row.get("count") or 0)
        raw_value = float(row.get("raw_markout_20") or row.get("markout_20") or 0.0)
        cost_value = float(row.get("estimated_spread_adverse_cost_20") or 0.0)
        follow_edge = raw_value - cost_value
        fade_edge = -raw_value - cost_value
        product_group = str(row.get("product_group"))
        stability = str(row.get("stability") or "insufficient")
        reason = ""
        confidence_flag = "low"
        stability_flag = stability
        if count < MIN_RECOMMENDATION_COUNT:
            decision = "ignore"
            reason = f"count_below_minimum_{MIN_RECOMMENDATION_COUNT}"
        elif stability == "mixed":
            decision = "ignore"
            reason = "day_signs_conflict"
        elif raw_value > 0.0:
            if follow_edge > MIN_NET_EDGE_TICKS and stability == "stable":
                decision = "follow"
                reason = "positive_raw_markout_net_of_cost_and_day_stable"
                confidence_flag = "medium"
            else:
                decision = "ignore"
                reason = "positive_raw_markout_below_cost_or_not_stable"
        elif raw_value < 0.0:
            if fade_edge > MIN_NET_EDGE_TICKS and stability == "stable":
                decision = "fade"
                reason = "negative_raw_markout_supports_cost_adjusted_fade"
                confidence_flag = "medium"
            else:
                decision = "ignore"
                reason = "negative_raw_markout_below_fade_cost_or_not_stable"
        else:
            decision = "ignore"
            reason = "zero_raw_markout"
        if decision == "ignore":
            recommended_use = "ignore"
            suggested_clip = 0.0
        else:
            recommended_use = decision
            net_edge = follow_edge if decision == "follow" else fade_edge
            if product_group == "velvet":
                suggested_clip = min(1.0, max(0.25, abs(net_edge)))
            elif product_group.startswith("voucher"):
                suggested_clip = min(0.5, max(0.1, abs(net_edge) * 0.5))
            elif product_group == "hydrogel":
                suggested_clip = min(0.5, max(0.1, abs(net_edge) * 0.5))
            else:
                suggested_clip = 0.0
        rows.append({
            "counterparty": row.get("counterparty"),
            "product": row.get("product"),
            "product_group": product_group,
            "side": row.get("side"),
            "follow_fade_ignore": decision,
            "recommended_use": recommended_use,
            "reason": reason,
            "raw_signed_markout_20": raw_value,
            "estimated_spread_adverse_cost_20": cost_value,
            "net_follow_edge_20": follow_edge,
            "net_fade_edge_20": fade_edge,
            "edge_ticks_after_cost": follow_edge if decision != "fade" else fade_edge,
            "count": count,
            "minimum_count_threshold": MIN_RECOMMENDATION_COUNT,
            "day_1_markout": row.get("day_1_markout"),
            "day_2_markout": row.get("day_2_markout"),
            "day_3_markout": row.get("day_3_markout"),
            "stability": stability,
            "stability_flag": stability_flag,
            "confidence_flag": confidence_flag,
            "markout_interpretation": "participant_side_not_aggressor_inference",
            "suggested_clip": round(float(suggested_clip), 4),
        })
    rows.sort(key=lambda item: (item["follow_fade_ignore"] == "ignore", -abs(float(item["edge_ticks_after_cost"])), -int(item["count"])))
    return rows


def run_round4_counterparty_research(
    *,
    data_dir: Path,
    output_dir: Path,
    days: Iterable[int] = (1, 2, 3),
    horizons: Sequence[int] = (1, 5, 10, 20, 50, 100, 300),
) -> Dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    spec = get_round_spec(4)
    dataset = load_round_dataset(data_dir, days, round_number=4, round_spec=spec)
    market_days = [dataset[int(day)] for day in days]
    horizons = tuple(int(horizon) for horizon in horizons)
    day_rows, pooled_rows, cross_rows = _build_product_side_rows(market_days, horizons)
    recommendation_rows = _recommendation_rows(pooled_rows)

    write_rows_csv(output_dir / "counterparty_product_side_day.csv", day_rows)
    write_rows_csv(output_dir / "counterparty_product_side_pooled.csv", pooled_rows)
    write_rows_csv(output_dir / "cross_product_markouts.csv", cross_rows)
    write_rows_csv(output_dir / "counterparty_recommendations.csv", recommendation_rows)
    summary = {
        "round": 4,
        "data_dir": str(data_dir),
        "output_dir": str(output_dir),
        "days": [int(day) for day in days],
        "horizons": list(horizons),
        "product_side_rows": len(day_rows) + len(pooled_rows),
        "cross_product_rows": len(cross_rows),
        "recommendation_rows": len(recommendation_rows),
        "top_recommendations": recommendation_rows[:20],
        "validation": [day.validation for day in market_days],
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
