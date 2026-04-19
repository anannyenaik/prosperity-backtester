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
    for trade in trade_history:
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


def compare_live_export_summary(live_export: LiveExport, artefact) -> Dict[str, object]:
    run_summary = artefact.summary
    live_positions = dict(live_export.final_positions)
    if not live_positions and live_export.trade_history:
        for trade in live_export.trade_history:
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
    fill_count_error = int(run_summary.get("fill_count", 0)) - len(live_export.trade_history)

    return {
        "live_profit": live_export.profit,
        "simulated_profit": run_summary.get("final_pnl"),
        "profit_error": None if live_export.profit is None else float(run_summary.get("final_pnl", 0.0)) - float(live_export.profit),
        "live_positions": live_positions,
        "simulated_positions": run_summary.get("final_positions", {}),
        "position_l1_error": position_l1_error,
        "fill_count_live": len(live_export.trade_history),
        "fill_count_simulated": run_summary.get("fill_count", 0),
        "fill_count_error": fill_count_error,
        "path_rmse": path_rmse,
        "graph_points_live": live_path,
        "graph_points_simulated": sim_pnl_points,
        "per_product_pnl": per_product_pnl,
    }
