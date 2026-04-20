from __future__ import annotations

import json
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


def _json_text(payload: object, options: OutputOptions) -> str:
    if options.json_indent is None:
        return json.dumps(payload, separators=(",", ":"))
    return json.dumps(payload, indent=options.json_indent)


def _sample_evenly(rows: Sequence[Dict[str, object]], limit: int) -> List[Dict[str, object]]:
    if limit <= 0 or len(rows) <= limit:
        return [dict(row) for row in rows]
    if limit == 1:
        return [dict(rows[-1])]
    indexes = {
        min(len(rows) - 1, round(idx * (len(rows) - 1) / (limit - 1)))
        for idx in range(limit)
    }
    return [dict(rows[idx]) for idx in sorted(indexes)]


def _compact_series(rows: Sequence[Dict[str, object]], options: OutputOptions) -> List[Dict[str, object]]:
    limit = int(options.max_series_rows_per_product)
    if limit <= 0:
        return [dict(row) for row in rows]
    grouped: Dict[tuple[object, object], List[Dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault((row.get("run_name"), row.get("product", "all")), []).append(row)
    output: List[Dict[str, object]] = []
    for key in sorted(grouped, key=lambda item: (str(item[0]), str(item[1]))):
        output.extend(_sample_evenly(grouped[key], limit))
    return output


def _compact_replay_rows(artefact: SessionArtefacts, options: OutputOptions) -> Dict[str, List[Dict[str, object]]]:
    return {
        "orders": [dict(row) for row in artefact.orders] if options.include_orders else [],
        "fills": [dict(row) for row in artefact.fills],
        "inventorySeries": _compact_series(artefact.inventory_series, options),
        "pnlSeries": _compact_series(artefact.pnl_series, options),
        "fairValueSeries": _compact_series(artefact.fair_value_series, options),
        "behaviourSeries": _compact_series(artefact.behaviour_series, options),
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
        "fairValueSeries": rows["fairValueSeries"],
        "behaviour": _compact_behaviour(result.behaviour),
        "behaviourSeries": rows["behaviourSeries"],
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
        "datasetReports": dataset_reports or [],
        "validation": validation or {},
    }
    if replay_result is not None:
        rows = _compact_replay_rows(replay_result, output_options)
        payload["summary"] = replay_result.summary
        payload["sessionRows"] = replay_result.session_rows
        if output_options.include_orders:
            payload["orders"] = rows["orders"]
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
        payload["monteCarlo"] = {
            "summary": summarise_monte_carlo_sessions(list(monte_carlo_results)),
            "sessions": [describe_series(result) for result in monte_carlo_results],
            "sampleRuns": sample_runs,
            "fairValueBands": {
                "analysisFair": fair_path_bands(sample_runs, "analysis_fair"),
                "mid": fair_path_bands(sample_runs, "mid"),
            },
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


def write_manifest(output_dir: Path, manifest: Dict[str, object], output_options: OutputOptions | None = None) -> None:
    output_options = output_options or DEFAULT_OUTPUT_OPTIONS
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {**manifest, "output_profile": output_options.to_manifest()}
    (output_dir / "manifest.json").write_text(_json_text(payload, output_options), encoding="utf-8")


def _manifest_base(artefact: SessionArtefacts) -> Dict[str, object]:
    return {
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
        "inventory_series.csv": rows["inventorySeries"],
        "pnl_series.csv": rows["pnlSeries"],
        "fair_value_series.csv": rows["fairValueSeries"],
        "behaviour_summary.csv": [
            {"product": product, **row}
            for product, row in artefact.behaviour.get("per_product", {}).items()
        ],
        "behaviour_series.csv": rows["behaviourSeries"],
    }
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
        if output_options.include_orders:
            for row in rows["orders"]:
                order_rows.append({"run_name": result.run_name, **dict(row)})
        for row in rows["inventorySeries"]:
            inventory_rows.append({"run_name": result.run_name, **dict(row)})
        for row in rows["pnlSeries"]:
            pnl_rows.append({"run_name": result.run_name, **dict(row)})
        for row in rows["fairValueSeries"]:
            fair_rows.append({"run_name": result.run_name, **dict(row)})
        for product, row in result.behaviour.get("per_product", {}).items():
            behaviour_rows.append({"run_name": result.run_name, "product": product, **row})
        for row in rows["behaviourSeries"]:
            behaviour_series_rows.append({"run_name": result.run_name, **dict(row)})
    extra_csvs = {
        "run_summary.csv": run_rows,
        "session_summary.csv": session_rows,
        "fills.csv": fill_rows,
        "inventory_series.csv": inventory_rows,
        "pnl_series.csv": pnl_rows,
        "fair_value_series.csv": fair_rows,
        "behaviour_summary.csv": behaviour_rows,
        "behaviour_series.csv": behaviour_series_rows,
    }
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
