from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Dict, List


ROW_TABLE_ENCODING = "row_table_v1"

_TOP_LEVEL_SERIES_KEYS = (
    "orders",
    "orderIntent",
    "fills",
    "inventorySeries",
    "pnlSeries",
    "fairValueSeries",
    "behaviourSeries",
)
_SAMPLE_RUN_SERIES_KEYS = (
    "inventorySeries",
    "pnlSeries",
    "fills",
    "orderIntent",
    "fairValueSeries",
    "behaviourSeries",
)


def is_row_table(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("encoding") == ROW_TABLE_ENCODING
        and isinstance(value.get("columns"), list)
        and isinstance(value.get("rows"), list)
    )


def compact_row_table(rows: object) -> object:
    if not isinstance(rows, list) or not rows:
        return rows
    if not all(isinstance(row, Mapping) for row in rows):
        return rows
    columns: List[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            text = str(key)
            if text not in seen:
                seen.add(text)
                columns.append(text)
    if not columns:
        return []
    return {
        "encoding": ROW_TABLE_ENCODING,
        "columns": columns,
        "rows": [[row.get(column) for column in columns] for row in rows],
    }


def expand_row_table(value: object) -> object:
    if not is_row_table(value):
        return value
    columns = [str(column) for column in value.get("columns", [])]
    expanded: List[Dict[str, object]] = []
    for raw_row in value.get("rows", []):
        if isinstance(raw_row, Mapping):
            expanded.append({column: raw_row.get(column) for column in columns})
            continue
        if isinstance(raw_row, Sequence) and not isinstance(raw_row, (str, bytes, bytearray)):
            expanded.append({
                column: raw_row[index] if index < len(raw_row) else None
                for index, column in enumerate(columns)
            })
    return expanded


def compact_dashboard_payload_for_storage(payload: Dict[str, object]) -> Dict[str, object]:
    stored = dict(payload)
    monte_carlo = stored.get("monteCarlo")
    if not isinstance(monte_carlo, Mapping):
        return stored
    compacted = dict(monte_carlo)
    sessions = compacted.get("sessions")
    if isinstance(sessions, list):
        compacted["sessions"] = compact_row_table(_slim_monte_carlo_sessions(sessions))
    sample_runs = compacted.get("sampleRuns")
    if isinstance(sample_runs, list):
        compacted["sampleRuns"] = [
            _compact_sample_run_payload(sample)
            if isinstance(sample, Mapping)
            else sample
            for sample in sample_runs
        ]
    path_bands = compacted.get("pathBands")
    if isinstance(path_bands, Mapping):
        compacted["pathBands"] = _compact_table_leaves(path_bands)
        if _path_bands_include_fair_value(path_bands):
            compacted.pop("fairValueBands", None)
        elif isinstance(compacted.get("fairValueBands"), Mapping):
            compacted["fairValueBands"] = _compact_table_leaves(compacted["fairValueBands"])
    elif isinstance(compacted.get("fairValueBands"), Mapping):
        compacted["fairValueBands"] = _compact_table_leaves(compacted["fairValueBands"])
    stored["monteCarlo"] = compacted
    return stored


def normalise_dashboard_payload(payload: Dict[str, object]) -> Dict[str, object]:
    normalised = dict(payload)
    for key in _TOP_LEVEL_SERIES_KEYS:
        normalised[key] = expand_row_table(normalised.get(key))
    monte_carlo = normalised.get("monteCarlo")
    if not isinstance(monte_carlo, Mapping):
        return normalised
    expanded = dict(monte_carlo)
    expanded["sessions"] = expand_row_table(expanded.get("sessions"))
    sample_runs = expanded.get("sampleRuns")
    if isinstance(sample_runs, list):
        expanded["sampleRuns"] = [
            _expand_sample_run_payload(sample)
            if isinstance(sample, Mapping)
            else sample
            for sample in sample_runs
        ]
    if isinstance(expanded.get("pathBands"), Mapping):
        expanded["pathBands"] = _expand_table_leaves(expanded["pathBands"])
    if isinstance(expanded.get("fairValueBands"), Mapping):
        expanded["fairValueBands"] = _expand_table_leaves(expanded["fairValueBands"])
    normalised["monteCarlo"] = expanded
    return normalised


def _slim_monte_carlo_sessions(rows: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    return [
        {
            "run_name": row.get("run_name"),
            "final_pnl": row.get("final_pnl"),
            "gross_pnl_before_maf": row.get("gross_pnl_before_maf"),
            "maf_cost": row.get("maf_cost"),
            "fill_count": row.get("fill_count"),
            "limit_breaches": row.get("limit_breaches"),
            "max_drawdown": row.get("max_drawdown"),
        }
        for row in rows
    ]


def _compact_sample_run_payload(sample: Mapping[str, object]) -> Dict[str, object]:
    compacted = dict(sample)
    for key in _SAMPLE_RUN_SERIES_KEYS:
        compacted[key] = compact_row_table(compacted.get(key))
    return compacted


def _expand_sample_run_payload(sample: Mapping[str, object]) -> Dict[str, object]:
    expanded = dict(sample)
    for key in _SAMPLE_RUN_SERIES_KEYS:
        expanded[key] = expand_row_table(expanded.get(key))
    return expanded


def _compact_table_leaves(value: object) -> object:
    if isinstance(value, list):
        return compact_row_table(value)
    if isinstance(value, Mapping):
        return {str(key): _compact_table_leaves(child) for key, child in value.items()}
    return value


def _expand_table_leaves(value: object) -> object:
    if is_row_table(value):
        return expand_row_table(value)
    if isinstance(value, Mapping):
        return {str(key): _expand_table_leaves(child) for key, child in value.items()}
    return value


def _path_bands_include_fair_value(path_bands: Mapping[str, object]) -> bool:
    for metric in ("analysisFair", "mid"):
        metric_rows = path_bands.get(metric)
        if not isinstance(metric_rows, Mapping):
            continue
        if any(isinstance(rows, list) and rows for rows in metric_rows.values()):
            return True
    return False
