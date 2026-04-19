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


DASHBOARD_SCHEMA_VERSION = 2


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
    replay_result: SessionArtefacts | None = None,
    monte_carlo_results: Sequence[SessionArtefacts] | None = None,
    comparison_rows: List[Dict[str, object]] | None = None,
    dataset_reports: List[Dict[str, object]] | None = None,
    validation: Dict[str, object] | None = None,
    calibration_grid: List[Dict[str, object]] | None = None,
    calibration_best: Dict[str, object] | None = None,
    optimization_rows: List[Dict[str, object]] | None = None,
) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "type": run_type,
        "meta": {
            "schemaVersion": DASHBOARD_SCHEMA_VERSION,
            "runName": run_name,
            "traderName": trader_name,
            "mode": mode,
            "fillModel": fill_model,
            "perturbations": perturbations,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        },
        "products": list(PRODUCTS),
        "assumptions": {
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
                "historical analysis fair",
                "synthetic market generation",
                "calibration and optimisation scores",
            ],
        },
        "datasetReports": dataset_reports or [],
        "validation": validation or {},
    }
    if replay_result is not None:
        payload["summary"] = replay_result.summary
        payload["sessionRows"] = replay_result.session_rows
        payload["orders"] = replay_result.orders
        payload["fills"] = replay_result.fills
        payload["inventorySeries"] = replay_result.inventory_series
        payload["pnlSeries"] = replay_result.pnl_series
        payload["fairValueSeries"] = replay_result.fair_value_series
        payload["fairValueSummary"] = replay_result.fair_value_summary
        payload["behaviour"] = replay_result.behaviour
        payload["behaviourSeries"] = replay_result.behaviour_series
    if monte_carlo_results is not None:
        sample_runs = [
            {
                "runName": result.run_name,
                "summary": result.summary,
                "inventorySeries": result.inventory_series,
                "pnlSeries": result.pnl_series,
                "fills": result.fills,
                "fairValueSeries": result.fair_value_series,
                "behaviour": result.behaviour,
                "behaviourSeries": result.behaviour_series,
            }
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
    return payload


def write_run_bundle(
    output_dir: Path,
    dashboard_payload: Dict[str, object],
    extra_csvs: Dict[str, List[Dict[str, object]]] | None = None,
    register: bool = True,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "dashboard.json").write_text(json.dumps(dashboard_payload, indent=2), encoding="utf-8")
    if extra_csvs:
        for filename, rows in extra_csvs.items():
            write_rows_csv(output_dir / filename, rows)
    if register:
        _write_registry_entry(output_dir, dashboard_payload)


def write_manifest(output_dir: Path, manifest: Dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _manifest_base(artefact: SessionArtefacts) -> Dict[str, object]:
    return {
        "run_name": artefact.run_name,
        "trader_name": artefact.trader_name,
        "mode": artefact.mode,
        "fill_model": artefact.fill_model,
        "perturbations": artefact.perturbations,
        "summary": artefact.summary,
        "fair_value_summary": artefact.fair_value_summary,
        "behaviour_summary": artefact.behaviour.get("summary", {}),
        "schema_version": DASHBOARD_SCHEMA_VERSION,
        "assumptions": {
            "aggressive_fills": "exact against visible book",
            "passive_fills": "approximate queue model",
            "historical_fair": "diagnostic inference",
            "synthetic_fair": "exact latent path",
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
) -> None:
    write_run_bundle(
        output_dir,
        dashboard_payload,
        extra_csvs={
            "run_summary.csv": [{
                "run_name": artefact.run_name,
                "trader_name": artefact.trader_name,
                "mode": artefact.mode,
                "final_pnl": artefact.summary["final_pnl"],
                "fill_count": artefact.summary["fill_count"],
                "order_count": artefact.summary.get("order_count"),
                "limit_breaches": artefact.summary["limit_breaches"],
                "max_drawdown": artefact.summary.get("max_drawdown"),
            }],
            "session_summary.csv": artefact.session_rows,
            "orders.csv": artefact.orders,
            "fills.csv": artefact.fills,
            "inventory_series.csv": artefact.inventory_series,
            "pnl_series.csv": artefact.pnl_series,
            "fair_value_series.csv": artefact.fair_value_series,
            "behaviour_summary.csv": [
                {"product": product, **row}
                for product, row in artefact.behaviour.get("per_product", {}).items()
            ],
            "behaviour_series.csv": artefact.behaviour_series,
        },
        register=register,
    )
    (output_dir / "manifest.json").write_text(json.dumps(_manifest_base(artefact), indent=2), encoding="utf-8")


def write_mc_bundle(
    output_dir: Path,
    results: Sequence[SessionArtefacts],
    dashboard_payload: Dict[str, object],
    register: bool = True,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_rows = [
        {
            "run_name": result.run_name,
            "trader_name": result.trader_name,
            "mode": result.mode,
            "final_pnl": result.summary["final_pnl"],
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
    sample_dir.mkdir(exist_ok=True)
    sessions_dir.mkdir(exist_ok=True)
    for result in results:
        (sessions_dir / f"{result.run_name}.json").write_text(json.dumps(_manifest_base(result), indent=2), encoding="utf-8")
        if result.inventory_series:
            sample_payload = {
                "runName": result.run_name,
                "summary": result.summary,
                "inventorySeries": result.inventory_series,
                "pnlSeries": result.pnl_series,
                "fairValueSeries": result.fair_value_series,
                "fills": result.fills,
                "behaviour": result.behaviour,
                "behaviourSeries": result.behaviour_series,
            }
            (sample_dir / f"{result.run_name}.json").write_text(json.dumps(sample_payload, indent=2), encoding="utf-8")
        for row in result.session_rows:
            session_rows.append({"run_name": result.run_name, **dict(row)})
        for row in result.fills:
            fill_rows.append({"run_name": result.run_name, **dict(row)})
        for row in result.orders:
            order_rows.append({"run_name": result.run_name, **dict(row)})
        for row in result.inventory_series:
            inventory_rows.append({"run_name": result.run_name, **dict(row)})
        for row in result.pnl_series:
            pnl_rows.append({"run_name": result.run_name, **dict(row)})
        for row in result.fair_value_series:
            fair_rows.append({"run_name": result.run_name, **dict(row)})
        for product, row in result.behaviour.get("per_product", {}).items():
            behaviour_rows.append({"run_name": result.run_name, "product": product, **row})
        for row in result.behaviour_series:
            behaviour_series_rows.append({"run_name": result.run_name, **dict(row)})
    write_run_bundle(
        output_dir,
        dashboard_payload,
        extra_csvs={
            "run_summary.csv": run_rows,
            "session_summary.csv": session_rows,
            "fills.csv": fill_rows,
            "orders.csv": order_rows,
            "inventory_series.csv": inventory_rows,
            "pnl_series.csv": pnl_rows,
            "fair_value_series.csv": fair_rows,
            "behaviour_summary.csv": behaviour_rows,
            "behaviour_series.csv": behaviour_series_rows,
        },
        register=register,
    )
    (output_dir / "manifest.json").write_text(json.dumps({
        "run_type": "monte_carlo",
        "run_count": len(results),
        "sample_path_count": sum(1 for result in results if result.inventory_series),
        "schema_version": DASHBOARD_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version,
        "platform": py_platform.platform(),
    }, indent=2), encoding="utf-8")
