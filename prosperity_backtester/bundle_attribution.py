from __future__ import annotations

import json
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Dict, List

from .dashboard_payload import is_row_table


def json_size_bytes(value: object) -> int:
    return len(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def estimate_object_size_bytes(value: object) -> int:
    return _estimate_object_size_bytes(value, set())


def build_bundle_attribution(
    payload: Mapping[str, object],
    bundle_files: Sequence[Mapping[str, object]],
    *,
    include_object_sizes: bool = False,
) -> Dict[str, object]:
    return {
        "dashboard_sections": dashboard_section_rows(payload, include_object_sizes=include_object_sizes),
        "file_components": file_component_rows(bundle_files),
    }


def dashboard_section_rows(
    payload: Mapping[str, object],
    *,
    include_object_sizes: bool = False,
) -> List[Dict[str, object]]:
    rows = [
        _section_row(
            component=key,
            value=value,
            schema_path=f"$.{key}",
            writer_path="prosperity_backtester.reports.build_dashboard_payload",
            include_object_sizes=include_object_sizes,
        )
        for key, value in payload.items()
    ]
    monte_carlo = payload.get("monteCarlo")
    if isinstance(monte_carlo, Mapping):
        rows.extend([
            _section_row(
                component=f"monteCarlo.{key}",
                value=monte_carlo.get(key),
                schema_path=f"$.monteCarlo.{key}",
                writer_path=_monte_carlo_writer_path(key),
                include_object_sizes=include_object_sizes,
            )
            for key in ("summary", "sessions", "sampleRuns", "pathBands", "fairValueBands", "pathBandMethod")
            if key in monte_carlo
        ])
        sample_runs = monte_carlo.get("sampleRuns")
        if isinstance(sample_runs, list):
            rows.extend(_sample_run_section_rows(sample_runs, include_object_sizes=include_object_sizes))
        path_bands = monte_carlo.get("pathBands")
        if isinstance(path_bands, Mapping):
            rows.extend(_path_band_metric_rows(path_bands, base_path="$.monteCarlo.pathBands", include_object_sizes=include_object_sizes))
        fair_value_bands = monte_carlo.get("fairValueBands")
        if isinstance(fair_value_bands, Mapping):
            rows.extend(_path_band_metric_rows(fair_value_bands, base_path="$.monteCarlo.fairValueBands", include_object_sizes=include_object_sizes))
    return sorted(rows, key=lambda row: int(row.get("json_bytes") or 0), reverse=True)


def file_component_rows(bundle_files: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    totals: dict[str, dict[str, object]] = {}
    for row in bundle_files:
        relative_path = str(row.get("path") or "")
        if not relative_path:
            continue
        component = _file_component(relative_path)
        state = totals.setdefault(component, {
            "component": component,
            "writer_path": _file_writer_path(component),
            "size_bytes": 0,
            "file_count": 0,
            "paths": [],
        })
        state["size_bytes"] = int(state["size_bytes"]) + int(row.get("size_bytes") or 0)
        state["file_count"] = int(state["file_count"]) + 1
        state["paths"].append(relative_path)
    return sorted(totals.values(), key=lambda row: int(row.get("size_bytes") or 0), reverse=True)


def _sample_run_section_rows(
    sample_runs: Sequence[object],
    *,
    include_object_sizes: bool = False,
) -> List[Dict[str, object]]:
    component_values: dict[str, list[object]] = defaultdict(list)
    for sample in sample_runs:
        if not isinstance(sample, Mapping):
            continue
        for key, value in sample.items():
            component_values[key].append(value)
    rows: List[Dict[str, object]] = []
    for key, values in component_values.items():
        aggregate_value = values if key == "summary" else _aggregate_section_values(values)
        rows.append(_section_row(
            component=f"monteCarlo.sampleRuns.{key}",
            value=aggregate_value,
            schema_path=f"$.monteCarlo.sampleRuns[*].{key}",
            writer_path="prosperity_backtester.reports._sample_run_payload",
            include_object_sizes=include_object_sizes,
        ))
    return rows


def _path_band_metric_rows(
    band_payload: Mapping[str, object],
    *,
    base_path: str,
    include_object_sizes: bool = False,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for metric, metric_rows in band_payload.items():
        rows.append(_section_row(
            component=f"{base_path[2:]}.{metric}",
            value=metric_rows,
            schema_path=f"{base_path}.{metric}",
            writer_path="prosperity_backtester.reports.finalize_path_band_accumulator",
            include_object_sizes=include_object_sizes,
        ))
    return rows


def _aggregate_section_values(values: Sequence[object]) -> object:
    if not values:
        return []
    if all(is_row_table(value) for value in values):
        return {
            "encoding": str(values[0].get("encoding")),
            "columns": list(values[0].get("columns") or []),
            "rows": [
                row
                for value in values
                for row in (value.get("rows") or [])
            ],
        }
    flattened: List[object] = []
    for value in values:
        if isinstance(value, list):
            flattened.extend(value)
        else:
            flattened.append(value)
    return flattened


def _section_row(
    *,
    component: str,
    value: object,
    schema_path: str,
    writer_path: str,
    include_object_sizes: bool,
) -> Dict[str, object]:
    row: Dict[str, object] = {
        "component": component,
        "schema_path": schema_path,
        "writer_path": writer_path,
        "json_bytes": json_size_bytes(value),
    }
    if include_object_sizes:
        row["estimated_object_size_bytes"] = estimate_object_size_bytes(value)
    if isinstance(value, list):
        row["row_count"] = len(value)
    elif is_row_table(value):
        row["storage_encoding"] = str(value.get("encoding"))
        row["row_count"] = len(value.get("rows") or [])
        row["column_count"] = len(value.get("columns") or [])
    elif isinstance(value, Mapping):
        row["entry_count"] = len(value)
    return row


def _file_component(relative_path: str) -> str:
    if relative_path == "dashboard.json":
        return "dashboard_payload"
    if relative_path == "manifest.json":
        return "manifest"
    if relative_path == "run_summary.csv":
        return "run_summary_csv"
    if relative_path == "session_summary.csv":
        return "session_summary_csv"
    if relative_path == "fills.csv":
        return "fills_csv"
    if relative_path == "behaviour_summary.csv":
        return "behaviour_summary_csv"
    if relative_path == "comparison.csv":
        return "comparison_csv"
    if relative_path == "optimization.csv":
        return "optimization_csv"
    if relative_path == "calibration_grid.csv":
        return "calibration_grid_csv"
    if relative_path.startswith("round2_"):
        return "round2_csvs"
    if relative_path.startswith("scenario_") or relative_path == "robustness_ranking.csv":
        return "scenario_csvs"
    if relative_path.endswith("_series.csv"):
        return "series_sidecars"
    if relative_path == "order_intent.csv":
        return "order_intent_sidecar"
    if relative_path == "orders.csv":
        return "orders_debug"
    if relative_path.startswith("sample_paths/"):
        return "sample_path_debug"
    if relative_path.startswith("sessions/"):
        return "session_manifest_debug"
    if relative_path.startswith("empirical_profile/"):
        return "empirical_profile"
    return "other_files"


def _file_writer_path(component: str) -> str:
    if component == "dashboard_payload":
        return "prosperity_backtester.reports.write_run_bundle"
    if component == "manifest":
        return "prosperity_backtester.reports.write_manifest"
    if component in {"run_summary_csv", "session_summary_csv", "fills_csv", "behaviour_summary_csv", "series_sidecars", "order_intent_sidecar", "orders_debug", "sample_path_debug", "session_manifest_debug"}:
        return "prosperity_backtester.reports.write_mc_bundle / prosperity_backtester.reports.write_replay_bundle"
    if component in {"comparison_csv", "round2_csvs", "scenario_csvs", "optimization_csv", "calibration_grid_csv", "empirical_profile"}:
        return "prosperity_backtester.reports.write_run_bundle"
    return "prosperity_backtester.reports.write_run_bundle"


def _monte_carlo_writer_path(key: str) -> str:
    if key == "sessions":
        return "prosperity_backtester.dashboard_payload.compact_dashboard_payload_for_storage"
    if key == "sampleRuns":
        return "prosperity_backtester.reports._sample_run_payload"
    if key in {"pathBands", "fairValueBands", "pathBandMethod"}:
        return "prosperity_backtester.reports.finalize_path_band_accumulator"
    return "prosperity_backtester.reports.build_dashboard_payload"


def _estimate_object_size_bytes(value: object, seen: set[int]) -> int:
    object_id = id(value)
    if object_id in seen:
        return 0
    seen.add(object_id)
    size = sys.getsizeof(value)
    if isinstance(value, Mapping):
        return size + sum(
            _estimate_object_size_bytes(key, seen) + _estimate_object_size_bytes(child, seen)
            for key, child in value.items()
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return size + sum(_estimate_object_size_bytes(child, seen) for child in value)
    return size
