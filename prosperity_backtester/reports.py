from __future__ import annotations

import json
import math
import platform as py_platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence

from .fair_value import fair_path_bands
from .metadata import PRODUCTS
from .platform import SessionArtefacts, describe_series, summarise_monte_carlo_sessions, write_rows_csv
from .round2 import ASSUMPTION_REGISTRY
from .storage import OutputOptions


DASHBOARD_SCHEMA_VERSION = 3
DEFAULT_OUTPUT_OPTIONS = OutputOptions()
_KEY_FIELDS = {"run_name", "day", "timestamp", "product"}
_SERIES_PRIORITY_METRICS = (
    "position",
    "mtm",
    "realised",
    "unrealised",
    "cash",
    "analysis_fair",
    "mid",
    "fair",
    "fair_minus_mid",
    "position_ratio",
    "abs_position_ratio",
    "order_count",
    "fill_count",
)


def _normalise_run_type(run_type: str | None) -> str:
    text = str(run_type or "").strip().lower().replace("-", "_")
    if text in {"mc", "montecarlo"}:
        return "monte_carlo"
    if text in {"compare"}:
        return "comparison"
    if text in {"optimize", "optimise"}:
        return "optimization"
    if text in {"round2", "round_2", "round2_scenario"}:
        return "round2_scenarios"
    return text


def _data_contract(run_type: str | None, options: OutputOptions) -> List[Dict[str, object]]:
    kind = _normalise_run_type(run_type)
    light_replay_paths = {
        "key": "replay_paths",
        "label": "Replay paths",
        "fidelity": "compact",
        "location": "dashboard.json",
        "notes": (
            "Event-aware retained replay rows with bucket min/max envelopes. "
            "Retained points are faithful, while omitted intra-bucket chronology is compacted."
        ),
    }
    full_replay_paths = {
        "key": "replay_paths",
        "label": "Replay paths",
        "fidelity": "raw",
        "location": "dashboard.json and *_series.csv sidecars",
        "notes": "Full-resolution replay rows are retained for forensic debugging.",
    }
    light_orders = {
        "key": "order_submission",
        "label": "Order submission evidence",
        "fidelity": "compact",
        "location": "dashboard.json orderIntent",
        "notes": "Compact submitted quote intent per timestamp and product. Raw order rows are omitted.",
    }
    raw_orders = {
        "key": "order_submission",
        "label": "Order submission evidence",
        "fidelity": "raw",
        "location": "dashboard.json orders and orders.csv",
        "notes": "Raw submitted order rows are retained.",
    }

    if kind == "replay":
        return [
            {
                "key": "replay_summary",
                "label": "Replay summary",
                "fidelity": "exact",
                "location": "dashboard.json and run_summary.csv",
                "notes": "Exact scalar replay metrics and per-product end-state values for this local run.",
            },
            {
                "key": "fills",
                "label": "Fills",
                "fidelity": "exact",
                "location": "dashboard.json and fills.csv",
                "notes": "Exact fill rows produced by the local replay engine.",
            },
            raw_orders if options.include_orders else light_orders,
            full_replay_paths if int(options.max_series_rows_per_product) <= 0 else light_replay_paths,
        ]

    if kind == "monte_carlo":
        return [
            {
                "key": "final_distribution",
                "label": "Final distribution metrics",
                "fidelity": "exact",
                "location": "dashboard.json monteCarlo.summary and session_summary.csv",
                "notes": "Exact cross-session summary metrics across every Monte Carlo session in the run.",
            },
            {
                "key": "path_bands",
                "label": "Monte Carlo path bands",
                "fidelity": "bucketed" if int(options.max_mc_path_rows_per_product) > 0 else "exact",
                "location": "dashboard.json monteCarlo.pathBands",
                "notes": (
                    "Exact cross-session quantiles at retained bucket endpoints. "
                    "If bucketed, omitted ticks contribute min/max envelopes before the cross-session bands are written."
                    if int(options.max_mc_path_rows_per_product) > 0
                    else "Exact cross-session quantiles across every retained Monte Carlo timestamp."
                ),
            },
            {
                "key": "sample_runs",
                "label": "Sample session paths",
                "fidelity": "qualitative",
                "location": "dashboard.json monteCarlo.sampleRuns",
                "notes": (
                    "Sample sessions are for behaviour inspection only. "
                    "They are not the population used for the final distribution or path bands."
                ),
            },
        ]

    if kind in {"comparison", "scenario_compare", "optimization", "round2_scenarios"}:
        return [
            {
                "key": "aggregate_rows",
                "label": "Aggregate rows",
                "fidelity": "exact",
                "location": "dashboard.json and CSV sidecars",
                "notes": "Exact aggregate rows for this configured local run.",
            },
            {
                "key": "derived_rankings",
                "label": "Rankings and scores",
                "fidelity": "derived",
                "location": "dashboard.json diagnostics and ranking CSVs",
                "notes": "Derived local rankings and diagnostics built from the recorded aggregate rows.",
            },
        ]

    if kind == "calibration":
        return [
            {
                "key": "calibration_grid",
                "label": "Calibration grid",
                "fidelity": "exact",
                "location": "dashboard.json calibration.grid and calibration_grid.csv",
                "notes": "Exact local replay-vs-live comparison rows for the tested calibration grid.",
            },
            {
                "key": "best_candidate",
                "label": "Best calibration candidate",
                "fidelity": "derived",
                "location": "dashboard.json calibration.best",
                "notes": "Best candidate under the local score function, not proof of exact website reconstruction.",
            },
        ]

    return []


def _json_text(payload: object, options: OutputOptions) -> str:
    if options.json_indent is None:
        return json.dumps(payload, separators=(",", ":"))
    return json.dumps(payload, indent=options.json_indent)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    return None


def _row_sort_key(row: Dict[str, object]) -> tuple[int, int]:
    return int(row.get("day", 0)), int(row.get("timestamp", 0))


def _metric_names(rows: Sequence[Dict[str, object]]) -> List[str]:
    present = {
        key
        for row in rows[: min(len(rows), 200)]
        for key, value in row.items()
        if key not in _KEY_FIELDS and _number(value) is not None
    }
    priority = [key for key in _SERIES_PRIORITY_METRICS if key in present]
    if priority:
        return priority[:6]
    return sorted(present)[:6]


def _fill_context(fills: Sequence[Dict[str, object]]) -> Dict[tuple[object, object], set[tuple[int, int]]]:
    by_group: Dict[tuple[object, object], set[tuple[int, int]]] = {}
    for fill in fills:
        by_group.setdefault((fill.get("run_name"), fill.get("product", "all")), set()).add(
            (int(fill.get("day", 0)), int(fill.get("timestamp", 0)))
        )
    return by_group


def _day_boundary_indices(rows: Sequence[Dict[str, object]]) -> set[int]:
    if not rows:
        return set()
    indices = {0, len(rows) - 1}
    previous_day = rows[0].get("day")
    for idx, row in enumerate(rows[1:], start=1):
        current_day = row.get("day")
        if current_day != previous_day:
            indices.add(idx - 1)
            indices.add(idx)
        previous_day = current_day
    return indices


def _fill_neighbour_indices(rows: Sequence[Dict[str, object]], fill_times: set[tuple[int, int]]) -> set[int]:
    if not fill_times:
        return set()
    indices: set[int] = set()
    by_time = {
        (int(row.get("day", 0)), int(row.get("timestamp", 0))): idx
        for idx, row in enumerate(rows)
    }
    for key in fill_times:
        idx = by_time.get(key)
        if idx is None:
            continue
        indices.update(i for i in (idx - 1, idx, idx + 1) if 0 <= i < len(rows))
    return indices


def _drawdown_indices(rows: Sequence[Dict[str, object]]) -> set[int]:
    if not rows or not any("mtm" in row for row in rows):
        return set()
    peak_value = float("-inf")
    peak_idx = 0
    worst_peak_idx = 0
    worst_trough_idx = 0
    worst_drawdown = 0.0
    for idx, row in enumerate(rows):
        value = _number(row.get("mtm"))
        if value is None:
            continue
        if value > peak_value:
            peak_value = value
            peak_idx = idx
        drawdown = peak_value - value
        if drawdown > worst_drawdown:
            worst_drawdown = drawdown
            worst_peak_idx = peak_idx
            worst_trough_idx = idx
    return {worst_peak_idx, worst_trough_idx} if worst_drawdown > 0 else set()


def _regime(value: object) -> str:
    number = _number(value)
    if number is None:
        return "unknown"
    if number > 0.0005:
        return "up"
    if number < -0.0005:
        return "down"
    return "flat"


def _regime_change_indices(rows: Sequence[Dict[str, object]]) -> set[int]:
    if not rows or not any("trend_slope_per_tick" in row for row in rows):
        return set()
    indices: set[int] = set()
    previous = _regime(rows[0].get("trend_slope_per_tick"))
    for idx, row in enumerate(rows[1:], start=1):
        current = _regime(row.get("trend_slope_per_tick"))
        if current != previous:
            indices.add(idx - 1)
            indices.add(idx)
        previous = current
    return indices


def _bucket_ranges(length: int, bucket_count: int) -> List[tuple[int, int]]:
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


def _bucket_extrema_indices(rows: Sequence[Dict[str, object]], metrics: Sequence[str], bucket_count: int) -> tuple[set[int], Dict[int, tuple[int, int]]]:
    selected: set[int] = set()
    ranges_by_index: Dict[int, tuple[int, int]] = {}
    for start, end in _bucket_ranges(len(rows), bucket_count):
        bucket_rows = rows[start:end]
        selected.add(end - 1)
        for metric in metrics:
            values = [(idx, _number(row.get(metric))) for idx, row in enumerate(bucket_rows, start=start)]
            clean = [(idx, value) for idx, value in values if value is not None]
            if not clean:
                continue
            selected.add(min(clean, key=lambda item: item[1])[0])
            selected.add(max(clean, key=lambda item: item[1])[0])
        for idx in range(start, end):
            ranges_by_index[idx] = (start, end)
    return selected, ranges_by_index


def _with_bucket_envelope(row: Dict[str, object], bucket_rows: Sequence[Dict[str, object]], metrics: Sequence[str]) -> Dict[str, object]:
    output = dict(row)
    if len(bucket_rows) <= 1:
        return output
    first = bucket_rows[0]
    last = bucket_rows[-1]
    output["bucket_start_day"] = first.get("day")
    output["bucket_start_timestamp"] = first.get("timestamp")
    output["bucket_end_day"] = last.get("day")
    output["bucket_end_timestamp"] = last.get("timestamp")
    output["bucket_count"] = len(bucket_rows)
    for metric in metrics:
        values = [_number(item.get(metric)) for item in bucket_rows]
        clean = [value for value in values if value is not None]
        if not clean:
            continue
        last_value = next((value for value in reversed(values) if value is not None), None)
        output[f"{metric}_bucket_min"] = min(clean)
        output[f"{metric}_bucket_max"] = max(clean)
        output[f"{metric}_bucket_last"] = last_value
    return output


def _compact_event_aware(
    rows: Sequence[Dict[str, object]],
    limit: int,
    fill_times: set[tuple[int, int]] | None = None,
) -> List[Dict[str, object]]:
    ordered = sorted((dict(row) for row in rows), key=_row_sort_key)
    if limit <= 0 or len(ordered) <= limit:
        return ordered

    metrics = _metric_names(ordered)
    required = (
        _day_boundary_indices(ordered)
        | _fill_neighbour_indices(ordered, fill_times or set())
        | _drawdown_indices(ordered)
        | _regime_change_indices(ordered)
    )
    budget = max(1, limit - len(required))
    slots_per_bucket = max(1, 1 + 2 * max(1, len(metrics)))
    bucket_count = max(1, budget // slots_per_bucket)
    bucket_indices, bucket_ranges = _bucket_extrema_indices(ordered, metrics, bucket_count)
    selected = required | bucket_indices
    output: List[Dict[str, object]] = []
    for idx in sorted(selected):
        if idx < 0 or idx >= len(ordered):
            continue
        start, end = bucket_ranges.get(idx, (idx, idx + 1))
        output.append(_with_bucket_envelope(ordered[idx], ordered[start:end], metrics))
    return output


def _compact_series(
    rows: Sequence[Dict[str, object]],
    options: OutputOptions,
    fills: Sequence[Dict[str, object]] | None = None,
) -> List[Dict[str, object]]:
    limit = int(options.max_series_rows_per_product)
    if limit <= 0:
        return [dict(row) for row in rows]
    fill_context = _fill_context(fills or [])
    grouped: Dict[tuple[object, object], List[Dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault((row.get("run_name"), row.get("product", "all")), []).append(row)
    output: List[Dict[str, object]] = []
    for key in sorted(grouped, key=lambda item: (str(item[0]), str(item[1]))):
        output.extend(_compact_event_aware(grouped[key], limit, fill_context.get(key, set())))
    return output


def _compact_order_intent(orders: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    grouped: Dict[tuple[object, object, int, int], List[Dict[str, object]]] = {}
    for row in orders:
        grouped.setdefault(
            (row.get("run_name"), row.get("product", "all"), int(row.get("day", 0)), int(row.get("timestamp", 0))),
            [],
        ).append(row)

    rows: List[Dict[str, object]] = []
    previous_quote: Dict[tuple[object, object], tuple[object, object]] = {}
    for key in sorted(grouped, key=lambda item: (str(item[0]), str(item[1]), item[2], item[3])):
        run_name, product, day, timestamp = key
        bucket = grouped[key]
        buys = [row for row in bucket if int(row.get("submitted_quantity", 0)) > 0]
        sells = [row for row in bucket if int(row.get("submitted_quantity", 0)) < 0]
        best_bid = max((int(row["submitted_price"]) for row in buys), default=None)
        best_ask = min((int(row["submitted_price"]) for row in sells), default=None)
        signed_qty = sum(int(row.get("submitted_quantity", 0)) for row in bucket)
        aggressive_qty = sum(abs(int(row.get("submitted_quantity", 0))) for row in bucket if row.get("order_role") == "aggressive")
        passive_qty = sum(abs(int(row.get("submitted_quantity", 0))) for row in bucket if row.get("order_role") != "aggressive")
        edges = [_number(row.get("signed_edge_to_analysis_fair")) for row in bucket]
        clean_edges = [edge for edge in edges if edge is not None]
        quote = (best_bid, best_ask)
        previous = previous_quote.get((run_name, product))
        quote_update_count = 1 if previous is not None and quote != previous else 0
        previous_quote[(run_name, product)] = quote
        first = bucket[0]
        rows.append({
            "run_name": run_name,
            "day": day,
            "timestamp": timestamp,
            "product": product,
            "best_submitted_bid": best_bid,
            "best_submitted_ask": best_ask,
            "signed_submitted_quantity": signed_qty,
            "aggressive_submitted_quantity": aggressive_qty,
            "passive_submitted_quantity": passive_qty,
            "quote_width": None if best_bid is None or best_ask is None else best_ask - best_bid,
            "order_row_count": len(bucket),
            "quote_update_count": quote_update_count,
            "buy_order_count": len(buys),
            "sell_order_count": len(sells),
            "one_sided": bool((best_bid is None) ^ (best_ask is None)),
            "market_best_bid": first.get("best_bid"),
            "market_best_ask": first.get("best_ask"),
            "mid": first.get("mid"),
            "reference_fair": first.get("reference_fair"),
            "analysis_fair": first.get("analysis_fair"),
            "mean_signed_edge_to_analysis_fair": None if not clean_edges else sum(clean_edges) / len(clean_edges),
            "min_signed_edge_to_analysis_fair": None if not clean_edges else min(clean_edges),
            "max_signed_edge_to_analysis_fair": None if not clean_edges else max(clean_edges),
            "fill_regime": first.get("fill_regime"),
            "access_scenario": first.get("access_scenario"),
            "access_active": first.get("access_active"),
            "access_extra_fraction": first.get("access_extra_fraction"),
        })
    return rows


def _compact_replay_rows(artefact: SessionArtefacts, options: OutputOptions) -> Dict[str, List[Dict[str, object]]]:
    return {
        "orders": [dict(row) for row in artefact.orders] if options.include_orders else [],
        "fills": [dict(row) for row in artefact.fills],
        "orderIntent": _compact_order_intent(artefact.orders),
        "inventorySeries": _compact_series(artefact.inventory_series, options, artefact.fills),
        "pnlSeries": _compact_series(artefact.pnl_series, options, artefact.fills),
        "fairValueSeries": _compact_series(artefact.fair_value_series, options, artefact.fills),
        "behaviourSeries": _compact_series(artefact.behaviour_series, options, artefact.fills),
    }


def _compact_behaviour(behaviour: Dict[str, object]) -> Dict[str, object]:
    return {key: value for key, value in behaviour.items() if key != "series"}


def _sample_run_payload(result: SessionArtefacts, options: OutputOptions) -> Dict[str, object]:
    rows = _compact_replay_rows(result, options)
    return {
        "runName": result.run_name,
        "summary": result.summary,
        "inventorySeries": rows["inventorySeries"],
        "pnlSeries": rows["pnlSeries"],
        "fills": rows["fills"],
        "orderIntent": rows["orderIntent"],
        "fairValueSeries": rows["fairValueSeries"],
        "behaviour": _compact_behaviour(result.behaviour),
        "behaviourSeries": rows["behaviourSeries"],
    }


def _quantile(clean: Sequence[float], q: float) -> float:
    values = sorted(clean)
    if len(values) == 1:
        return values[0]
    idx = q * (len(values) - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return values[lo]
    weight = idx - lo
    return values[lo] * (1.0 - weight) + values[hi] * weight


def _aggregate_mc_path_bands(results: Sequence[SessionArtefacts]) -> Dict[str, Dict[str, List[Dict[str, object]]]]:
    metric_map = {
        "analysisFair": "analysis_fair",
        "mid": "mid",
        "inventory": "inventory",
        "pnl": "pnl",
    }
    output: Dict[str, Dict[str, List[Dict[str, object]]]] = {
        metric_name: {product: [] for product in PRODUCTS}
        for metric_name in metric_map
    }
    grouped: Dict[tuple[str, str, int], List[Dict[str, object]]] = {}
    for result in results:
        for row in result.path_metrics:
            product = str(row.get("product"))
            if product not in PRODUCTS:
                continue
            bucket_index = int(row.get("bucket_index", 0))
            for metric_name, row_key in metric_map.items():
                if _number(row.get(row_key)) is None:
                    continue
                grouped.setdefault((metric_name, product, bucket_index), []).append(row)

    for (metric_name, product, bucket_index), rows in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])):
        row_key = metric_map[metric_name]
        values = [float(row[row_key]) for row in rows if _number(row.get(row_key)) is not None]
        if not values:
            continue
        envelope_min_values = [
            float(row.get(f"{row_key}_bucket_min", row[row_key]))
            for row in rows
            if _number(row.get(f"{row_key}_bucket_min", row.get(row_key))) is not None
        ]
        envelope_max_values = [
            float(row.get(f"{row_key}_bucket_max", row[row_key]))
            for row in rows
            if _number(row.get(f"{row_key}_bucket_max", row.get(row_key))) is not None
        ]
        first = rows[0]
        output[metric_name][product].append({
            "day": first.get("day"),
            "timestamp": first.get("timestamp"),
            "bucketIndex": bucket_index,
            "bucketStartTimestamp": first.get("bucket_start_timestamp"),
            "bucketEndTimestamp": first.get("bucket_end_timestamp"),
            "bucketCount": first.get("bucket_count"),
            "sessionCount": len(values),
            "p05": _quantile(values, 0.05),
            "p10": _quantile(values, 0.10),
            "p25": _quantile(values, 0.25),
            "p50": _quantile(values, 0.50),
            "p75": _quantile(values, 0.75),
            "p90": _quantile(values, 0.90),
            "p95": _quantile(values, 0.95),
            "min": min(values),
            "max": max(values),
            "envelopeMin": min(envelope_min_values) if envelope_min_values else min(values),
            "envelopeMax": max(envelope_max_values) if envelope_max_values else max(values),
        })
    return output


def _path_band_method(results: Sequence[SessionArtefacts], options: OutputOptions) -> Dict[str, object]:
    session_count = len(results)
    bucketed_sessions = sum(1 for result in results if result.path_metrics)
    return {
        "source": "all_sessions",
        "session_count": session_count,
        "sessions_with_path_metrics": bucketed_sessions,
        "metrics": ["analysisFair", "mid", "inventory", "pnl"],
        "quantiles": "Exact across sessions at retained bucket endpoints.",
        "envelopes": "Min/max envelopes are retained across omitted ticks inside each bucket.",
        "time_compaction": (
            "No timestamp compaction for full profile."
            if int(options.max_mc_path_rows_per_product) <= 0
            else f"At most {int(options.max_mc_path_rows_per_product)} retained buckets per product."
        ),
    }


def _mean(values: Sequence[float]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return sum(clean) / len(clean) if clean else None


def _bias_label(value: object, tolerance: float = 1e-9) -> str:
    if value is None:
        return "unknown"
    number = float(value)
    if number > tolerance:
        return "optimistic"
    if number < -tolerance:
        return "pessimistic"
    return "neutral"


def _calibration_diagnostics(
    rows: Sequence[Dict[str, object]],
    best: Dict[str, object] | None,
) -> Dict[str, object]:
    if not rows:
        return {"candidate_count": 0}

    by_fill_model: Dict[str, Dict[str, object]] = {}
    for fill_model in sorted({str(row.get("fill_model", "unknown")) for row in rows}):
        subset = [row for row in rows if str(row.get("fill_model", "unknown")) == fill_model]
        scores = [float(row["score"]) for row in subset if row.get("score") is not None]
        by_fill_model[fill_model] = {
            "candidate_count": len(subset),
            "best_score": min(scores) if scores else None,
            "mean_score": _mean(scores),
            "mean_profit_error": _mean([float(row["profit_error"]) for row in subset if row.get("profit_error") is not None]),
            "mean_path_rmse": _mean([float(row["path_rmse"]) for row in subset if row.get("path_rmse") is not None]),
        }

    product_fields = {
        "ASH_COATED_OSMIUM": ("osmium_pnl_error", "osmium_path_rmse"),
        "INTARIAN_PEPPER_ROOT": ("pepper_pnl_error", "pepper_path_rmse"),
    }
    per_product: Dict[str, Dict[str, object]] = {}
    for product, (pnl_key, rmse_key) in product_fields.items():
        pnl_errors = [float(row[pnl_key]) for row in rows if row.get(pnl_key) is not None]
        path_errors = [float(row[rmse_key]) for row in rows if row.get(rmse_key) is not None]
        best_row = min(
            (row for row in rows if row.get(rmse_key) is not None),
            key=lambda row: float(row[rmse_key]),
            default=None,
        )
        per_product[product] = {
            "mean_abs_pnl_error": _mean([abs(value) for value in pnl_errors]),
            "mean_path_rmse": _mean(path_errors),
            "best_path_rmse": None if best_row is None else best_row.get(rmse_key),
            "best_path_candidate": None if best_row is None else {
                "fill_model": best_row.get("fill_model"),
                "passive_fill_scale": best_row.get("passive_fill_scale"),
                "adverse_selection_ticks": best_row.get("adverse_selection_ticks"),
                "latency_ticks": best_row.get("latency_ticks"),
                "missed_fill_additive": best_row.get("missed_fill_additive"),
                "score": best_row.get("score"),
            },
        }

    profit_bias_counts = {"optimistic": 0, "pessimistic": 0, "neutral": 0, "unknown": 0}
    fill_bias_counts = {"overfilled": 0, "underfilled": 0, "neutral": 0, "unknown": 0}
    for row in rows:
        profit_bias_counts[_bias_label(row.get("profit_error"))] += 1
        fill_error = row.get("fill_count_error")
        if fill_error is None:
            fill_bias_counts["unknown"] += 1
        elif float(fill_error) > 0:
            fill_bias_counts["overfilled"] += 1
        elif float(fill_error) < 0:
            fill_bias_counts["underfilled"] += 1
        else:
            fill_bias_counts["neutral"] += 1

    return {
        "candidate_count": len(rows),
        "by_fill_model": by_fill_model,
        "profit_bias_counts": profit_bias_counts,
        "fill_bias_counts": fill_bias_counts,
        "best_attribution": {
            "profit_bias": _bias_label((best or {}).get("profit_error")),
            "fill_bias": (best or {}).get("fill_bias", "unknown"),
            "dominant_error_source": (best or {}).get("dominant_error_source", "unknown"),
        },
        "per_product": per_product,
    }


def _optimization_diagnostics(rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    if not rows:
        return {"variant_count": 0}
    best_score = rows[0]
    best_replay = max(rows, key=lambda row: float(row.get("replay_final_pnl") or 0.0))
    best_downside = max(rows, key=lambda row: float(row.get("mc_p05") or 0.0))
    most_stable = min(rows, key=lambda row: float(row.get("mc_std") or 0.0))
    return {
        "variant_count": len(rows),
        "best_score_variant": best_score.get("variant"),
        "best_replay_variant": best_replay.get("variant"),
        "best_downside_variant": best_downside.get("variant"),
        "most_stable_variant": most_stable.get("variant"),
        "score_gap_to_second": None if len(rows) < 2 else float(rows[0].get("score") or 0.0) - float(rows[1].get("score") or 0.0),
        "frontier": [
            {
                "variant": row.get("variant"),
                "score": row.get("score"),
                "replay_final_pnl": row.get("replay_final_pnl"),
                "mc_p05": row.get("mc_p05"),
                "mc_expected_shortfall_05": row.get("mc_expected_shortfall_05"),
                "mc_std": row.get("mc_std"),
            }
            for row in rows[:8]
        ],
    }


def _comparison_diagnostics(rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    if not rows:
        return {"row_count": 0}
    winner = rows[0]
    runner_up = rows[1] if len(rows) > 1 else None
    return {
        "row_count": len(rows),
        "winner": winner.get("trader"),
        "winner_final_pnl": winner.get("final_pnl"),
        "gap_to_second": None if runner_up is None else float(winner.get("final_pnl") or 0.0) - float(runner_up.get("final_pnl") or 0.0),
        "limit_breach_count": sum(int(row.get("limit_breaches") or 0) for row in rows),
        "scenario_count": len({str(row.get("scenario", "default")) for row in rows}),
        "maf_sensitive_rows": sum(1 for row in rows if row.get("maf_cost") not in (None, 0, 0.0)),
    }


def _write_registry_entry(output_dir: Path, dashboard_payload: Dict[str, object]) -> None:
    output_dir = output_dir.resolve()
    meta = dashboard_payload.get("meta", {})
    summary = dashboard_payload.get("summary", {})
    monte_carlo_summary = dashboard_payload.get("monteCarlo", {}).get("summary", {})
    calibration_best = dashboard_payload.get("calibration", {}).get("best", {})
    optimization_rows = dashboard_payload.get("optimization", {}).get("rows", [])
    best_optimization = optimization_rows[0] if optimization_rows else {}
    row = {
        "created_at": meta.get("createdAt") or datetime.now(timezone.utc).isoformat(),
        "schema_version": DASHBOARD_SCHEMA_VERSION,
        "run_name": meta.get("runName"),
        "run_type": dashboard_payload.get("type"),
        "trader_name": meta.get("traderName"),
        "mode": meta.get("mode"),
        "round": meta.get("round"),
        "output_profile": (meta.get("outputProfile") or {}).get("profile") if isinstance(meta.get("outputProfile"), dict) else None,
        "access_scenario": (meta.get("accessScenario") or {}).get("name") if isinstance(meta.get("accessScenario"), dict) else None,
        "output_dir": str(output_dir),
        "dashboard_json": str(output_dir / "dashboard.json"),
        "final_pnl": summary.get("final_pnl"),
        "max_drawdown": summary.get("max_drawdown"),
        "fill_count": summary.get("fill_count"),
        "limit_breaches": summary.get("limit_breaches"),
        "mc_mean": monte_carlo_summary.get("mean"),
        "mc_p05": monte_carlo_summary.get("p05"),
        "calibration_best_score": calibration_best.get("score"),
        "optimization_best_variant": best_optimization.get("variant"),
        "optimization_best_score": best_optimization.get("score"),
    }
    registry_path = output_dir.parent / "run_registry.jsonl"
    with registry_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def build_dashboard_payload(
    *,
    run_type: str,
    run_name: str,
    trader_name: str,
    mode: str,
    fill_model: Dict[str, object],
    perturbations: Dict[str, object],
    round_number: int = 1,
    access_scenario: Dict[str, object] | None = None,
    replay_result: SessionArtefacts | None = None,
    monte_carlo_results: Sequence[SessionArtefacts] | None = None,
    comparison_rows: List[Dict[str, object]] | None = None,
    dataset_reports: List[Dict[str, object]] | None = None,
    validation: Dict[str, object] | None = None,
    calibration_grid: List[Dict[str, object]] | None = None,
    calibration_best: Dict[str, object] | None = None,
    optimization_rows: List[Dict[str, object]] | None = None,
    round2: Dict[str, object] | None = None,
    scenario_analysis: Dict[str, object] | None = None,
    output_options: OutputOptions | None = None,
) -> Dict[str, object]:
    output_options = output_options or DEFAULT_OUTPUT_OPTIONS
    access_scenario = access_scenario or {}
    assumptions: Dict[str, object] = {
        "exact": [
            "CSV and live-export parsing",
            "visible-book aggressive fills",
            "cash, realised, unrealised and MTM accounting",
            "traderData and own-trade state hand-off",
            "synthetic latent fair inside Monte Carlo sessions",
        ],
        "approximate": [
            "passive queue position",
            "same-price queue share",
            "adverse selection penalties",
            "size-dependent slippage",
            "empirical fill profiles inferred from realised live fills",
            "historical analysis fair",
            "synthetic market generation",
            "calibration and optimisation scores",
        ],
        "scenario": [
            "Stress, crash, fill-quality and slippage scenarios are decision tools.",
            "Scenario outputs should be used for ranking stability and fragility checks, not exact website forecasts.",
        ],
    }
    if int(round_number) == 2 or access_scenario:
        assumptions["round2"] = ASSUMPTION_REGISTRY

    payload: Dict[str, object] = {
        "type": run_type,
        "meta": {
            "schemaVersion": DASHBOARD_SCHEMA_VERSION,
            "runName": run_name,
            "traderName": trader_name,
            "mode": mode,
            "round": round_number,
            "fillModel": fill_model,
            "perturbations": perturbations,
            "accessScenario": access_scenario,
            "outputProfile": output_options.to_manifest(),
            "createdAt": datetime.now(timezone.utc).isoformat(),
        },
        "products": list(PRODUCTS),
        "assumptions": assumptions,
        "dataContract": _data_contract(run_type, output_options),
        "datasetReports": dataset_reports or [],
        "validation": validation or {},
    }
    if replay_result is not None:
        rows = _compact_replay_rows(replay_result, output_options)
        payload["summary"] = replay_result.summary
        payload["sessionRows"] = replay_result.session_rows
        if output_options.include_orders:
            payload["orders"] = rows["orders"]
        payload["orderIntent"] = rows["orderIntent"]
        payload["fills"] = rows["fills"]
        payload["inventorySeries"] = rows["inventorySeries"]
        payload["pnlSeries"] = rows["pnlSeries"]
        payload["fairValueSeries"] = rows["fairValueSeries"]
        payload["fairValueSummary"] = replay_result.fair_value_summary
        payload["behaviour"] = _compact_behaviour(replay_result.behaviour)
        payload["behaviourSeries"] = rows["behaviourSeries"]
    if monte_carlo_results is not None:
        sample_runs = [
            _sample_run_payload(result, output_options)
            for result in monte_carlo_results
            if result.inventory_series
        ]
        path_bands = _aggregate_mc_path_bands(monte_carlo_results)
        has_all_session_bands = any(
            rows
            for metric_bands in path_bands.values()
            for rows in metric_bands.values()
        )
        if has_all_session_bands:
            fair_value_bands = {
                "analysisFair": path_bands["analysisFair"],
                "mid": path_bands["mid"],
            }
            path_band_method = _path_band_method(monte_carlo_results, output_options)
        else:
            fair_value_bands = {
                "analysisFair": fair_path_bands(sample_runs, "analysis_fair"),
                "mid": fair_path_bands(sample_runs, "mid"),
            }
            path_band_method = {
                "source": "sample_runs",
                "session_count": len(sample_runs),
                "metrics": ["analysisFair", "mid"],
                "quantiles": "Fallback only; current Monte Carlo runs normally write all-session path metrics.",
            }
        payload["monteCarlo"] = {
            "summary": summarise_monte_carlo_sessions(list(monte_carlo_results)),
            "sessions": [describe_series(result) for result in monte_carlo_results],
            "sampleRuns": sample_runs,
            "pathBands": path_bands,
            "fairValueBands": fair_value_bands,
            "pathBandMethod": path_band_method,
        }
    if comparison_rows is not None:
        payload["comparison"] = comparison_rows
        payload["comparisonDiagnostics"] = _comparison_diagnostics(comparison_rows)
    if calibration_grid is not None:
        payload["calibration"] = {
            "grid": calibration_grid,
            "best": calibration_best or {},
            "diagnostics": _calibration_diagnostics(calibration_grid, calibration_best),
        }
    if optimization_rows is not None:
        payload["optimization"] = {
            "rows": optimization_rows,
            "diagnostics": _optimization_diagnostics(optimization_rows),
        }
    if round2 is not None:
        registry_extra = round2.get("assumptionRegistry", {})
        if not isinstance(registry_extra, dict):
            registry_extra = {}
        payload["round2"] = {
            **round2,
            "assumptionRegistry": {
                **ASSUMPTION_REGISTRY,
                **registry_extra,
            },
        }
    if scenario_analysis is not None:
        payload["scenarioAnalysis"] = scenario_analysis
    return payload


def write_run_bundle(
    output_dir: Path,
    dashboard_payload: Dict[str, object],
    extra_csvs: Dict[str, List[Dict[str, object]]] | None = None,
    register: bool = True,
    output_options: OutputOptions | None = None,
) -> None:
    output_options = output_options or DEFAULT_OUTPUT_OPTIONS
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "dashboard.json").write_text(_json_text(dashboard_payload, output_options), encoding="utf-8")
    if extra_csvs:
        for filename, rows in extra_csvs.items():
            if rows or filename in {"run_summary.csv", "session_summary.csv", "comparison.csv", "optimization.csv", "calibration_grid.csv"}:
                write_rows_csv(output_dir / filename, rows)
    if register:
        _write_registry_entry(output_dir, dashboard_payload)


def _bundle_file_category(relative_path: str) -> str:
    if relative_path in {"dashboard.json", "manifest.json"}:
        return "metadata"
    if relative_path == "orders.csv" or relative_path.startswith("sample_paths/") or relative_path.startswith("sessions/"):
        return "debug"
    if relative_path.endswith("_series.csv") or relative_path == "order_intent.csv":
        return "sidecar"
    return "canonical"


def _bundle_file_rows(output_dir: Path) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for path in sorted(p for p in output_dir.rglob("*") if p.is_file()):
        relative_path = str(path.relative_to(output_dir)).replace("\\", "/")
        rows.append({
            "path": relative_path,
            "size_bytes": path.stat().st_size,
            "category": _bundle_file_category(relative_path),
        })
    return rows


def _bundle_stats(rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    total_size = sum(int(row.get("size_bytes", 0) or 0) for row in rows)
    return {
        "file_count": len(rows),
        "total_size_bytes": total_size,
        "debug_file_count": sum(1 for row in rows if row.get("category") == "debug"),
        "sidecar_file_count": sum(1 for row in rows if row.get("category") == "sidecar"),
    }


def write_manifest(output_dir: Path, manifest: Dict[str, object], output_options: OutputOptions | None = None) -> None:
    output_options = output_options or DEFAULT_OUTPUT_OPTIONS
    output_dir.mkdir(parents=True, exist_ok=True)
    run_type = manifest.get("run_type") or manifest.get("mode")
    payload = {
        "run_name": manifest.get("run_name") or output_dir.name,
        "schema_version": manifest.get("schema_version", DASHBOARD_SCHEMA_VERSION),
        "created_at": manifest.get("created_at") or datetime.now(timezone.utc).isoformat(),
        **manifest,
        "output_profile": output_options.to_manifest(),
    }
    if run_type and "data_contract" not in payload:
        payload["data_contract"] = _data_contract(str(run_type), output_options)

    manifest_path = output_dir / "manifest.json"
    previous_text: str | None = None
    for _ in range(5):
        text = _json_text(payload, output_options)
        if text == previous_text:
            break
        manifest_path.write_text(text, encoding="utf-8")
        previous_text = text
        rows = _bundle_file_rows(output_dir)
        payload["bundle_stats"] = _bundle_stats(rows)
        payload["canonical_files"] = [row["path"] for row in rows if row.get("category") in {"metadata", "canonical"}]
        payload["sidecar_files"] = [row["path"] for row in rows if row.get("category") == "sidecar"]
        payload["debug_files"] = [row["path"] for row in rows if row.get("category") == "debug"]
        payload["bundle_files"] = rows


def _manifest_base(artefact: SessionArtefacts) -> Dict[str, object]:
    return {
        "run_type": artefact.mode,
        "run_name": artefact.run_name,
        "trader_name": artefact.trader_name,
        "mode": artefact.mode,
        "fill_model": artefact.fill_model,
        "perturbations": artefact.perturbations,
        "access_scenario": artefact.access_scenario,
        "summary": artefact.summary,
        "fair_value_summary": artefact.fair_value_summary,
        "behaviour_summary": artefact.behaviour.get("summary", {}),
        "schema_version": DASHBOARD_SCHEMA_VERSION,
        "assumptions": {
            "aggressive_fills": "exact against visible book",
            "passive_fills": "empirical or configured approximate queue model",
            "slippage": "configured size-dependent and adverse-selection penalty",
            "noise": "configured or fitted Monte Carlo latent noise profile",
            "historical_fair": "diagnostic inference",
            "synthetic_fair": "exact latent path",
            "round2_access": "configurable local assumption, not official reconstruction",
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version,
        "platform": py_platform.platform(),
    }


def write_replay_bundle(
    output_dir: Path,
    artefact: SessionArtefacts,
    dashboard_payload: Dict[str, object],
    register: bool = True,
    output_options: OutputOptions | None = None,
) -> None:
    output_options = output_options or DEFAULT_OUTPUT_OPTIONS
    rows = _compact_replay_rows(artefact, output_options)
    extra_csvs = {
        "run_summary.csv": [{
            "run_name": artefact.run_name,
            "trader_name": artefact.trader_name,
            "mode": artefact.mode,
            "final_pnl": artefact.summary["final_pnl"],
            "gross_pnl_before_maf": artefact.summary.get("gross_pnl_before_maf"),
            "maf_cost": artefact.summary.get("maf_cost"),
            "access_scenario": artefact.access_scenario.get("name"),
            "fill_count": artefact.summary["fill_count"],
            "order_count": artefact.summary.get("order_count"),
            "limit_breaches": artefact.summary["limit_breaches"],
            "max_drawdown": artefact.summary.get("max_drawdown"),
        }],
        "session_summary.csv": artefact.session_rows,
        "fills.csv": rows["fills"],
        "behaviour_summary.csv": [
            {"product": product, **row}
            for product, row in artefact.behaviour.get("per_product", {}).items()
        ],
    }
    if output_options.write_series_csvs:
        extra_csvs.update({
            "inventory_series.csv": rows["inventorySeries"],
            "pnl_series.csv": rows["pnlSeries"],
            "fair_value_series.csv": rows["fairValueSeries"],
            "behaviour_series.csv": rows["behaviourSeries"],
            "order_intent.csv": rows["orderIntent"],
        })
    if output_options.include_orders:
        extra_csvs["orders.csv"] = rows["orders"]
    write_run_bundle(
        output_dir,
        dashboard_payload,
        extra_csvs=extra_csvs,
        register=register,
        output_options=output_options,
    )
    write_manifest(output_dir, _manifest_base(artefact), output_options)


def write_mc_bundle(
    output_dir: Path,
    results: Sequence[SessionArtefacts],
    dashboard_payload: Dict[str, object],
    register: bool = True,
    output_options: OutputOptions | None = None,
) -> None:
    output_options = output_options or DEFAULT_OUTPUT_OPTIONS
    output_dir.mkdir(parents=True, exist_ok=True)
    run_rows = [
        {
            "run_name": result.run_name,
            "trader_name": result.trader_name,
            "mode": result.mode,
            "final_pnl": result.summary["final_pnl"],
            "gross_pnl_before_maf": result.summary.get("gross_pnl_before_maf"),
            "maf_cost": result.summary.get("maf_cost"),
            "access_scenario": result.access_scenario.get("name"),
            "fill_count": result.summary["fill_count"],
            "order_count": result.summary.get("order_count"),
            "limit_breaches": result.summary["limit_breaches"],
            "max_drawdown": result.summary.get("max_drawdown"),
        }
        for result in results
    ]
    session_rows: List[Dict[str, object]] = []
    fill_rows: List[Dict[str, object]] = []
    order_rows: List[Dict[str, object]] = []
    order_intent_rows: List[Dict[str, object]] = []
    inventory_rows: List[Dict[str, object]] = []
    pnl_rows: List[Dict[str, object]] = []
    fair_rows: List[Dict[str, object]] = []
    behaviour_rows: List[Dict[str, object]] = []
    behaviour_series_rows: List[Dict[str, object]] = []
    sample_dir = output_dir / "sample_paths"
    sessions_dir = output_dir / "sessions"
    if output_options.write_sample_path_files:
        sample_dir.mkdir(exist_ok=True)
    if output_options.write_session_manifests:
        sessions_dir.mkdir(exist_ok=True)
    for result in results:
        rows = _compact_replay_rows(result, output_options)
        if output_options.write_session_manifests:
            (sessions_dir / f"{result.run_name}.json").write_text(_json_text(_manifest_base(result), output_options), encoding="utf-8")
        if result.inventory_series:
            if output_options.write_sample_path_files:
                (sample_dir / f"{result.run_name}.json").write_text(_json_text(_sample_run_payload(result, output_options), output_options), encoding="utf-8")
        for row in result.session_rows:
            session_rows.append({"run_name": result.run_name, **dict(row)})
        for row in rows["fills"]:
            fill_rows.append({"run_name": result.run_name, **dict(row)})
        for row in rows["orderIntent"]:
            order_intent_rows.append({**dict(row), "run_name": result.run_name})
        if output_options.include_orders:
            for row in rows["orders"]:
                order_rows.append({"run_name": result.run_name, **dict(row)})
        if output_options.write_series_csvs:
            for row in rows["inventorySeries"]:
                inventory_rows.append({"run_name": result.run_name, **dict(row)})
            for row in rows["pnlSeries"]:
                pnl_rows.append({"run_name": result.run_name, **dict(row)})
            for row in rows["fairValueSeries"]:
                fair_rows.append({"run_name": result.run_name, **dict(row)})
        for product, row in result.behaviour.get("per_product", {}).items():
            behaviour_rows.append({"run_name": result.run_name, "product": product, **row})
        if output_options.write_series_csvs:
            for row in rows["behaviourSeries"]:
                behaviour_series_rows.append({"run_name": result.run_name, **dict(row)})
    extra_csvs = {
        "run_summary.csv": run_rows,
        "session_summary.csv": session_rows,
        "fills.csv": fill_rows,
        "behaviour_summary.csv": behaviour_rows,
    }
    if output_options.write_series_csvs:
        extra_csvs.update({
            "inventory_series.csv": inventory_rows,
            "pnl_series.csv": pnl_rows,
            "fair_value_series.csv": fair_rows,
            "behaviour_series.csv": behaviour_series_rows,
            "order_intent.csv": order_intent_rows,
        })
    if output_options.include_orders:
        extra_csvs["orders.csv"] = order_rows
    write_run_bundle(
        output_dir,
        dashboard_payload,
        extra_csvs=extra_csvs,
        register=register,
        output_options=output_options,
    )
    write_manifest(output_dir, {
        "run_type": "monte_carlo",
        "run_count": len(results),
        "sample_run_count": sum(1 for result in results if result.inventory_series),
        "saved_sample_path_count": sum(1 for result in results if result.inventory_series) if output_options.write_sample_path_files else 0,
        "schema_version": DASHBOARD_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version,
        "platform": py_platform.platform(),
    }, output_options)
