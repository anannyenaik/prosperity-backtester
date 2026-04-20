from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .dataset import BookSnapshot, DayDataset, TradePrint
from .metadata import PRODUCTS


@dataclass
class LiveExport:
    submission_id: Optional[str]
    status: Optional[str]
    profit: Optional[float]
    day_dataset: DayDataset
    trade_history: List[TradePrint]
    own_trade_history: List[TradePrint]
    raw_path: str
    graph_points: List[Dict[str, float]]
    final_positions: Dict[str, int]
    activities_profit_path: List[Dict[str, float]]
    per_product_profit_path: Dict[str, List[Dict[str, float]]]


def _parse_activities_log(text: str) -> tuple[DayDataset, List[Dict[str, float]], Dict[str, List[Dict[str, float]]]]:
    books_by_timestamp: Dict[int, Dict[str, BookSnapshot]] = {}
    timestamps: List[int] = []
    reader = csv.reader(io.StringIO(text), delimiter=";")
    header = next(reader)
    expected = [
        "day", "timestamp", "product",
        "bid_price_1", "bid_volume_1", "bid_price_2", "bid_volume_2", "bid_price_3", "bid_volume_3",
        "ask_price_1", "ask_volume_1", "ask_price_2", "ask_volume_2", "ask_price_3", "ask_volume_3",
        "mid_price", "profit_and_loss",
    ]
    if header != expected:
        raise ValueError("Live export activitiesLog schema does not match round 1 prices schema")
    current_day = 0
    profit_path: Dict[int, float] = {}
    per_product_profit: Dict[str, List[Dict[str, float]]] = {product: [] for product in PRODUCTS}
    for row in reader:
        current_day = int(row[0])
        ts = int(row[1])
        product = row[2]
        if ts not in books_by_timestamp:
            books_by_timestamp[ts] = {}
            timestamps.append(ts)
        bids = []
        asks = []
        for p_idx, v_idx in ((3, 4), (5, 6), (7, 8)):
            if row[p_idx] != "" and row[v_idx] != "":
                bids.append((int(float(row[p_idx])), abs(int(float(row[v_idx])))))
        for p_idx, v_idx in ((9, 10), (11, 12), (13, 14)):
            if row[p_idx] != "" and row[v_idx] != "":
                asks.append((int(float(row[p_idx])), abs(int(float(row[v_idx])))))
        books_by_timestamp[ts][product] = BookSnapshot(
            timestamp=ts,
            product=product,
            bids=bids,
            asks=asks,
            mid=float(row[15]) if row[15] else None,
            reference_fair=float(row[15]) if row[15] else None,
            source_day=current_day,
        )
        if row[16] != "":
            profit_value = float(row[16])
            profit_path[ts] = profit_value
            if product in per_product_profit:
                per_product_profit[product].append({"timestamp": ts, "pnl": profit_value})
    timestamps.sort()
    dataset = DayDataset(
        day=current_day,
        timestamps=timestamps,
        books_by_timestamp=books_by_timestamp,
        trades_by_timestamp={},
        metadata={"source": "live_export_activities"},
        validation={
            "price_rows": sum(len(v) for v in books_by_timestamp.values()),
            "trade_rows": 0,
            "timestamps": len(timestamps),
            "missing_products": {
                ts: [p for p in PRODUCTS if p not in books_by_timestamp[ts]]
                for ts in timestamps
                if any(p not in books_by_timestamp[ts] for p in PRODUCTS)
            },
            "timestamp_step_ok": all((b - a) == 100 for a, b in zip(timestamps, timestamps[1:])),
            "products_seen": sorted({p for by_p in books_by_timestamp.values() for p in by_p}),
        },
    )
    profit_series = [{"timestamp": ts, "pnl": profit_path[ts]} for ts in sorted(profit_path)]
    return dataset, profit_series, per_product_profit


def _parse_graph_log(text: str) -> List[Dict[str, float]]:
    if not text.strip():
        return []
    reader = csv.reader(io.StringIO(text), delimiter=";")
    header = next(reader, None)
    if header != ["timestamp", "value"]:
        return []
    out = []
    for row in reader:
        if len(row) < 2 or row[0] == "" or row[1] == "":
            continue
        out.append({"timestamp": int(row[0]), "pnl": float(row[1])})
    return out


def load_live_export(path: Path) -> LiveExport:
    path = path.resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    sibling_json = path.with_suffix(".json")
    sibling_log = path.with_suffix(".log")
    sibling_payload = None
    if path.suffix == ".log" and sibling_json.is_file():
        sibling_payload = json.loads(sibling_json.read_text(encoding="utf-8"))
    elif path.suffix == ".json" and sibling_log.is_file():
        sibling_payload = json.loads(sibling_log.read_text(encoding="utf-8"))

    activities_log = payload.get("activitiesLog", "") or (sibling_payload or {}).get("activitiesLog", "")
    if not activities_log:
        raise ValueError(f"Could not find activitiesLog in live export: {path}")
    day_dataset, activities_profit_path, per_product_profit_path = _parse_activities_log(activities_log)

    trade_history_raw = payload.get("tradeHistory", []) or (sibling_payload or {}).get("tradeHistory", [])
    trade_history = [
        TradePrint(
            timestamp=int(item["timestamp"]),
            buyer=item.get("buyer", "") or "",
            seller=item.get("seller", "") or "",
            symbol=item["symbol"],
            price=int(float(item["price"])),
            quantity=int(item["quantity"]),
            synthetic=False,
        )
        for item in trade_history_raw
    ]
    own_trade_history = [
        trade for trade in trade_history
        if trade.buyer == "SUBMISSION" or trade.seller == "SUBMISSION"
    ]
    for trade in trade_history:
        if trade.buyer == "SUBMISSION" or trade.seller == "SUBMISSION":
            continue
        day_dataset.trades_by_timestamp.setdefault(trade.timestamp, {}).setdefault(trade.symbol, []).append(trade)

    other = sibling_payload or {}
    graph_points = _parse_graph_log(str(payload.get("graphLog") or other.get("graphLog") or ""))
    final_positions = {
        item["symbol"]: int(item["quantity"])
        for item in (payload.get("positions") or other.get("positions") or [])
        if item.get("symbol") in PRODUCTS
    }
    return LiveExport(
        submission_id=payload.get("submissionId") or other.get("submissionId"),
        status=payload.get("status") or other.get("status"),
        profit=payload.get("profit") if payload.get("profit") is not None else other.get("profit"),
        day_dataset=day_dataset,
        trade_history=trade_history,
        own_trade_history=own_trade_history,
        raw_path=str(path),
        graph_points=graph_points,
        final_positions=final_positions,
        activities_profit_path=activities_profit_path,
        per_product_profit_path=per_product_profit_path,
    )


def _path_rmse(a: List[Dict[str, float]], b_lookup: Dict[int, float]) -> float | None:
    common = [(float(point["pnl"]), b_lookup[int(point["timestamp"])]) for point in a if int(point["timestamp"]) in b_lookup]
    if not common:
        return None
    return math.sqrt(sum((sim - live) ** 2 for live, sim in common) / len(common))


def _own_trade_side(trade: TradePrint) -> str | None:
    if trade.buyer == "SUBMISSION":
        return "buy"
    if trade.seller == "SUBMISSION":
        return "sell"
    return None


def _classify_live_role(trade: TradePrint, dataset: DayDataset) -> str:
    side = _own_trade_side(trade)
    snapshot = dataset.books_by_timestamp.get(int(trade.timestamp), {}).get(trade.symbol)
    if side is None or snapshot is None:
        return "unknown"
    if side == "buy" and snapshot.asks and int(trade.price) >= int(snapshot.asks[0][0]):
        return "aggressive"
    if side == "sell" and snapshot.bids and int(trade.price) <= int(snapshot.bids[0][0]):
        return "aggressive"
    return "passive"


def _live_fill_summary(live_export: LiveExport) -> Dict[str, object]:
    own_trades = live_export.own_trade_history
    role_counts = {"passive": 0, "aggressive": 0, "unknown": 0}
    side_counts = {"buy": 0, "sell": 0, "unknown": 0}
    per_product: Dict[str, Dict[str, object]] = {}
    for product in PRODUCTS:
        per_product[product] = {
            "fill_count": 0,
            "fill_qty": 0,
            "passive_count": 0,
            "aggressive_count": 0,
            "buy_qty": 0,
            "sell_qty": 0,
            "active_tick_count": 0,
        }
    active_ticks_by_product: Dict[str, set[int]] = {product: set() for product in PRODUCTS}
    for trade in own_trades:
        side = _own_trade_side(trade) or "unknown"
        role = _classify_live_role(trade, live_export.day_dataset)
        side_counts[side] = side_counts.get(side, 0) + 1
        role_counts[role] = role_counts.get(role, 0) + 1
        product_row = per_product.setdefault(trade.symbol, {
            "fill_count": 0,
            "fill_qty": 0,
            "passive_count": 0,
            "aggressive_count": 0,
            "buy_qty": 0,
            "sell_qty": 0,
            "active_tick_count": 0,
        })
        product_row["fill_count"] = int(product_row["fill_count"]) + 1
        product_row["fill_qty"] = int(product_row["fill_qty"]) + int(trade.quantity)
        if role in {"passive", "aggressive"}:
            product_row[f"{role}_count"] = int(product_row[f"{role}_count"]) + 1
        if side == "buy":
            product_row["buy_qty"] = int(product_row["buy_qty"]) + int(trade.quantity)
        elif side == "sell":
            product_row["sell_qty"] = int(product_row["sell_qty"]) + int(trade.quantity)
        active_ticks_by_product.setdefault(trade.symbol, set()).add(int(trade.timestamp))
    for product, ticks in active_ticks_by_product.items():
        per_product.setdefault(product, {})["active_tick_count"] = len(ticks)
    return {
        "fill_count": len(own_trades),
        "fill_qty": sum(int(trade.quantity) for trade in own_trades),
        "role_counts": role_counts,
        "side_counts": side_counts,
        "per_product": per_product,
    }


def _sim_fill_summary(artefact) -> Dict[str, object]:
    fills = artefact.fills
    role_counts = {"passive": 0, "aggressive": 0, "unknown": 0}
    side_counts = {"buy": 0, "sell": 0, "unknown": 0}
    per_product: Dict[str, Dict[str, object]] = {}
    active_ticks_by_product: Dict[str, set[int]] = {product: set() for product in PRODUCTS}
    for product in PRODUCTS:
        per_product[product] = {
            "fill_count": 0,
            "fill_qty": 0,
            "passive_count": 0,
            "aggressive_count": 0,
            "buy_qty": 0,
            "sell_qty": 0,
            "active_tick_count": 0,
        }
    for row in fills:
        product = str(row.get("product"))
        kind = str(row.get("kind", ""))
        role = "aggressive" if kind.startswith("aggressive") else "passive" if kind.startswith("passive") else "unknown"
        side = str(row.get("side", "unknown"))
        qty = int(row.get("quantity", 0))
        role_counts[role] = role_counts.get(role, 0) + 1
        side_counts[side] = side_counts.get(side, 0) + 1
        product_row = per_product.setdefault(product, {
            "fill_count": 0,
            "fill_qty": 0,
            "passive_count": 0,
            "aggressive_count": 0,
            "buy_qty": 0,
            "sell_qty": 0,
            "active_tick_count": 0,
        })
        product_row["fill_count"] = int(product_row["fill_count"]) + 1
        product_row["fill_qty"] = int(product_row["fill_qty"]) + qty
        if role in {"passive", "aggressive"}:
            product_row[f"{role}_count"] = int(product_row[f"{role}_count"]) + 1
        if side == "buy":
            product_row["buy_qty"] = int(product_row["buy_qty"]) + qty
        elif side == "sell":
            product_row["sell_qty"] = int(product_row["sell_qty"]) + qty
        active_ticks_by_product.setdefault(product, set()).add(int(row.get("timestamp", 0)))
    for product, ticks in active_ticks_by_product.items():
        per_product.setdefault(product, {})["active_tick_count"] = len(ticks)
    return {
        "fill_count": len(fills),
        "fill_qty": sum(int(row.get("quantity", 0)) for row in fills),
        "role_counts": role_counts,
        "side_counts": side_counts,
        "per_product": per_product,
    }


def _position_path_from_live(live_export: LiveExport) -> Dict[str, Dict[int, int]]:
    positions = {product: 0 for product in PRODUCTS}
    path: Dict[str, Dict[int, int]] = {product: {} for product in PRODUCTS}
    for trade in sorted(live_export.own_trade_history, key=lambda item: int(item.timestamp)):
        if trade.symbol not in PRODUCTS:
            continue
        side = _own_trade_side(trade)
        if side == "buy":
            positions[trade.symbol] += int(trade.quantity)
        elif side == "sell":
            positions[trade.symbol] -= int(trade.quantity)
        for product in PRODUCTS:
            path[product][int(trade.timestamp)] = positions[product]
    return path


def _position_path_errors(live_export: LiveExport, artefact) -> Dict[str, object]:
    live_paths = _position_path_from_live(live_export)
    sim_paths: Dict[str, Dict[int, int]] = {product: {} for product in PRODUCTS}
    for row in artefact.inventory_series:
        product = str(row["product"])
        if product in sim_paths:
            sim_paths[product][int(row["timestamp"])] = int(row["position"])
    per_product: Dict[str, object] = {}
    total_common = 0
    total_abs_error = 0.0
    total_sq_error = 0.0
    for product in PRODUCTS:
        live_path = live_paths.get(product, {})
        sim_path = sim_paths.get(product, {})
        common = sorted(set(live_path) & set(sim_path))
        abs_errors = [abs(sim_path[ts] - live_path[ts]) for ts in common]
        sq_errors = [(sim_path[ts] - live_path[ts]) ** 2 for ts in common]
        total_common += len(common)
        total_abs_error += sum(abs_errors)
        total_sq_error += sum(sq_errors)
        per_product[product] = {
            "common_points": len(common),
            "mean_abs_error": None if not common else sum(abs_errors) / len(common),
            "rmse": None if not common else math.sqrt(sum(sq_errors) / len(common)),
        }
    return {
        "common_points": total_common,
        "mean_abs_error": None if total_common == 0 else total_abs_error / total_common,
        "rmse": None if total_common == 0 else math.sqrt(total_sq_error / total_common),
        "per_product": per_product,
    }


def _activity_timing_summary(live_export: LiveExport, artefact) -> Dict[str, object]:
    live_ticks = {product: set() for product in PRODUCTS}
    sim_ticks = {product: set() for product in PRODUCTS}
    for trade in live_export.own_trade_history:
        if trade.symbol in live_ticks:
            live_ticks[trade.symbol].add(int(trade.timestamp))
    for row in artefact.fills:
        product = str(row.get("product"))
        if product in sim_ticks:
            sim_ticks[product].add(int(row.get("timestamp", 0)))
    per_product: Dict[str, object] = {}
    for product in PRODUCTS:
        union = live_ticks[product] | sim_ticks[product]
        overlap = live_ticks[product] & sim_ticks[product]
        per_product[product] = {
            "live_active_ticks": len(live_ticks[product]),
            "simulated_active_ticks": len(sim_ticks[product]),
            "overlap_ticks": len(overlap),
            "jaccard": None if not union else len(overlap) / len(union),
            "first_live_tick": min(live_ticks[product]) if live_ticks[product] else None,
            "first_simulated_tick": min(sim_ticks[product]) if sim_ticks[product] else None,
            "last_live_tick": max(live_ticks[product]) if live_ticks[product] else None,
            "last_simulated_tick": max(sim_ticks[product]) if sim_ticks[product] else None,
        }
    return {"per_product": per_product}


def _ranking_usefulness(profit_error: float | None, path_rmse: float | None) -> str:
    if profit_error is None:
        return "unknown_live_profit"
    abs_profit_error = abs(float(profit_error))
    if abs_profit_error <= 2_000:
        return "usable_for_relative_ranking_with_caution"
    if abs_profit_error <= 5_000 or (path_rmse is not None and float(path_rmse) <= 2_500):
        return "calibration_needed_before_trusting_small_edges"
    return "large_mismatch_use_only_for_coarse_stress_tests"


def compare_live_export_summary(live_export: LiveExport, artefact) -> Dict[str, object]:
    run_summary = artefact.summary
    live_positions = dict(live_export.final_positions)
    if not live_positions and live_export.own_trade_history:
        for trade in live_export.own_trade_history:
            live_positions.setdefault(trade.symbol, 0)
            if trade.buyer == "SUBMISSION":
                live_positions[trade.symbol] += trade.quantity
            if trade.seller == "SUBMISSION":
                live_positions[trade.symbol] -= trade.quantity

    sim_totals: Dict[int, float] = {}
    sim_totals_by_product: Dict[str, Dict[int, float]] = {product: {} for product in PRODUCTS}
    for row in artefact.pnl_series:
        ts = int(row["timestamp"])
        mtm = float(row.get("mtm", 0.0))
        sim_totals.setdefault(ts, 0.0)
        sim_totals[ts] += mtm
        product = str(row["product"])
        sim_totals_by_product.setdefault(product, {})[ts] = mtm

    sim_pnl_points = [{"timestamp": ts, "pnl": pnl} for ts, pnl in sorted(sim_totals.items())]
    live_path = live_export.graph_points or live_export.activities_profit_path
    sim_lookup = {int(row["timestamp"]): float(row["pnl"]) for row in sim_pnl_points}
    path_rmse = _path_rmse(live_path, sim_lookup)

    per_product_pnl = {}
    for product in PRODUCTS:
        live_rows = live_export.per_product_profit_path.get(product, [])
        sim_lookup_product = sim_totals_by_product.get(product, {})
        live_final = live_rows[-1]["pnl"] if live_rows else None
        sim_final = None
        if sim_lookup_product:
            last_ts = max(sim_lookup_product)
            sim_final = sim_lookup_product[last_ts]
        per_product_pnl[product] = {
            "live_final_pnl": live_final,
            "simulated_final_pnl": sim_final,
            "pnl_error": None if live_final is None or sim_final is None else float(sim_final) - float(live_final),
            "path_rmse": _path_rmse(live_rows, sim_lookup_product),
        }

    position_l1_error = sum(abs(int(run_summary.get("final_positions", {}).get(product, 0)) - int(live_positions.get(product, 0))) for product in PRODUCTS)
    live_fill_summary = _live_fill_summary(live_export)
    sim_fill_summary = _sim_fill_summary(artefact)
    fill_count_error = int(run_summary.get("fill_count", 0)) - int(live_fill_summary["fill_count"])
    position_path_error = _position_path_errors(live_export, artefact)
    timing = _activity_timing_summary(live_export, artefact)
    profit_error = None if live_export.profit is None else float(run_summary.get("final_pnl", 0.0)) - float(live_export.profit)

    return {
        "live_profit": live_export.profit,
        "simulated_profit": run_summary.get("final_pnl"),
        "profit_error": profit_error,
        "live_positions": live_positions,
        "simulated_positions": run_summary.get("final_positions", {}),
        "position_l1_error": position_l1_error,
        "fill_count_live": live_fill_summary["fill_count"],
        "fill_count_simulated": run_summary.get("fill_count", 0),
        "fill_count_error": fill_count_error,
        "fill_qty_live": live_fill_summary["fill_qty"],
        "fill_qty_simulated": sim_fill_summary["fill_qty"],
        "fill_qty_error": int(sim_fill_summary["fill_qty"]) - int(live_fill_summary["fill_qty"]),
        "path_rmse": path_rmse,
        "graph_points_live": live_path,
        "graph_points_simulated": sim_pnl_points,
        "per_product_pnl": per_product_pnl,
        "live_fill_summary": live_fill_summary,
        "simulated_fill_summary": sim_fill_summary,
        "fill_role_error": {
            "passive_count_error": int(sim_fill_summary["role_counts"].get("passive", 0)) - int(live_fill_summary["role_counts"].get("passive", 0)),
            "aggressive_count_error": int(sim_fill_summary["role_counts"].get("aggressive", 0)) - int(live_fill_summary["role_counts"].get("aggressive", 0)),
        },
        "inventory_path_error": position_path_error,
        "activity_timing": timing,
        "ranking_usefulness": _ranking_usefulness(profit_error, path_rmse),
        "diagnostic_notes": [
            "Live fill counts use only tradeHistory rows where SUBMISSION is buyer or seller.",
            "Passive/aggressive live labels are inferred from visible touch prices at fill time.",
            "A 1k to 2k daily profit mismatch can still be useful for relative ranking if scenario ordering is stable.",
        ],
    }
