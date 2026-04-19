from __future__ import annotations

import concurrent.futures
import json
import os
import random
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence

from .dataset import DayDataset, load_round1_dataset
from .fill_models import resolve_fill_model
from .live_export import compare_live_export_summary, load_live_export
from .platform import PerturbationConfig, SessionArtefacts, generate_synthetic_market_days, run_market_session
from .reports import build_dashboard_payload, write_manifest, write_mc_bundle, write_replay_bundle, write_run_bundle
from .trader_adapter import describe_overrides, make_trader


@dataclass
class TraderSpec:
    name: str
    path: Path
    overrides: Dict[str, object] | None = None


DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data" / "round1"
DEFAULT_EXPORT_DIR = Path(__file__).parent.parent / "live_exports"


def _dataset_reports(datasets: Sequence[DayDataset]) -> List[Dict[str, object]]:
    reports = []
    for dataset in datasets:
        validation = dict(dataset.validation)
        validation["issue_score"] = (
            int(validation.get("duplicate_book_rows", 0))
            + int(validation.get("crossed_book_rows", 0)) * 5
            + int(validation.get("trade_rows_unknown_symbol", 0)) * 5
            + int(validation.get("trade_rows_unknown_timestamp", 0)) * 3
            + len(validation.get("missing_products", {})) * 10
        )
        reports.append({
            "day": dataset.day,
            "metadata": dataset.metadata,
            "validation": validation,
        })
    return reports


def run_replay(
    *,
    trader_spec: TraderSpec,
    days: Sequence[int],
    data_dir: Path,
    fill_model_name: str,
    perturbation: PerturbationConfig,
    output_dir: Path,
    run_name: str,
    live_export_path: Path | None = None,
    register: bool = True,
) -> SessionArtefacts:
    datasets_map = load_round1_dataset(data_dir, days)
    datasets = [datasets_map[day] for day in days]
    live_export = load_live_export(live_export_path) if live_export_path is not None else None
    if live_export is not None:
        datasets = [live_export.day_dataset]
    trader, _module = make_trader(trader_spec.path, trader_spec.overrides)
    fill_model = resolve_fill_model(fill_model_name)
    artefact = run_market_session(
        trader=trader,
        trader_name=trader_spec.name,
        market_days=datasets,
        fill_model=fill_model,
        perturb=perturbation,
        rng=random.Random(20260418),
        run_name=run_name,
        mode="replay",
        capture_full_output=True,
    )
    validation = {}
    if live_export is not None:
        validation = compare_live_export_summary(live_export, artefact)
        artefact.validation = validation
    dashboard = build_dashboard_payload(
        run_type="replay",
        run_name=run_name,
        trader_name=trader_spec.name,
        mode="replay",
        fill_model=fill_model.to_dict(),
        perturbations=perturbation.to_dict(),
        replay_result=artefact,
        dataset_reports=_dataset_reports(datasets),
        validation=validation,
    )
    write_replay_bundle(output_dir, artefact, dashboard, register=register)
    return artefact


def _run_monte_carlo_session(task: Dict[str, object]) -> SessionArtefacts:
    session_idx = int(task["session_idx"])
    sample_sessions = int(task["sample_sessions"])
    base_seed = int(task["base_seed"])
    run_name = str(task["run_name"])
    trader_spec = task["trader_spec"]
    assert isinstance(trader_spec, TraderSpec)
    perturbation = task["perturbation"]
    assert isinstance(perturbation, PerturbationConfig)
    days = tuple(int(day) for day in task["days"])
    fill_model = resolve_fill_model(str(task["fill_model_name"]))
    market_days = generate_synthetic_market_days(days=days, seed=base_seed + session_idx * 17, perturb=perturbation)
    trader, _module = make_trader(trader_spec.path, trader_spec.overrides)
    return run_market_session(
        trader=trader,
        trader_name=trader_spec.name,
        market_days=market_days,
        fill_model=fill_model,
        perturb=perturbation,
        rng=random.Random(base_seed + session_idx * 31),
        run_name=f"{run_name}_session_{session_idx:04d}",
        mode="monte_carlo",
        capture_full_output=session_idx < sample_sessions,
    )


def run_monte_carlo(
    *,
    trader_spec: TraderSpec,
    sessions: int,
    sample_sessions: int,
    days: Sequence[int],
    fill_model_name: str,
    perturbation: PerturbationConfig,
    output_dir: Path,
    base_seed: int,
    run_name: str,
    workers: int = 1,
    register: bool = True,
) -> List[SessionArtefacts]:
    if sessions < 1:
        raise ValueError("Monte Carlo sessions must be at least 1")
    sample_sessions = max(0, min(int(sample_sessions), int(sessions)))
    fill_model = resolve_fill_model(fill_model_name)
    worker_count = max(1, int(workers))
    if worker_count > 1:
        worker_count = min(worker_count, sessions, os.cpu_count() or worker_count)
    tasks = [
        {
            "session_idx": session_idx,
            "sample_sessions": sample_sessions,
            "base_seed": base_seed,
            "run_name": run_name,
            "trader_spec": trader_spec,
            "perturbation": perturbation,
            "days": tuple(days),
            "fill_model_name": fill_model_name,
        }
        for session_idx in range(sessions)
    ]
    if worker_count == 1:
        results = [_run_monte_carlo_session(task) for task in tasks]
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=worker_count) as executor:
            results = list(executor.map(_run_monte_carlo_session, tasks))
    dashboard = build_dashboard_payload(
        run_type="monte_carlo",
        run_name=run_name,
        trader_name=trader_spec.name,
        mode="monte_carlo",
        fill_model=fill_model.to_dict(),
        perturbations=perturbation.to_dict(),
        monte_carlo_results=results,
        dataset_reports=[],
    )
    write_mc_bundle(output_dir, results, dashboard, register=register)
    return results


def run_compare(
    *,
    trader_specs: Sequence[TraderSpec],
    days: Sequence[int],
    data_dir: Path,
    fill_model_name: str,
    perturbation: PerturbationConfig,
    output_dir: Path,
    run_name: str,
) -> List[Dict[str, object]]:
    comparison_rows: List[Dict[str, object]] = []
    for trader_spec in trader_specs:
        run_dir = output_dir / trader_spec.name
        artefact = run_replay(
            trader_spec=trader_spec,
            days=days,
            data_dir=data_dir,
            fill_model_name=fill_model_name,
            perturbation=perturbation,
            output_dir=run_dir,
            run_name=f"{run_name}_{trader_spec.name}",
            register=False,
        )
        comparison_rows.append({
            "trader": trader_spec.name,
            "overrides": describe_overrides(trader_spec.overrides),
            "final_pnl": artefact.summary["final_pnl"],
            "max_drawdown": artefact.summary.get("max_drawdown"),
            "fill_count": artefact.summary["fill_count"],
            "order_count": artefact.summary.get("order_count"),
            "limit_breaches": artefact.summary["limit_breaches"],
            "osmium_pnl": artefact.summary["per_product"]["ASH_COATED_OSMIUM"]["final_mtm"],
            "pepper_pnl": artefact.summary["per_product"]["INTARIAN_PEPPER_ROOT"]["final_mtm"],
            "osmium_position": artefact.summary["per_product"]["ASH_COATED_OSMIUM"]["final_position"],
            "pepper_position": artefact.summary["per_product"]["INTARIAN_PEPPER_ROOT"]["final_position"],
            "osmium_cap_usage": artefact.behaviour.get("per_product", {}).get("ASH_COATED_OSMIUM", {}).get("cap_usage_ratio"),
            "pepper_cap_usage": artefact.behaviour.get("per_product", {}).get("INTARIAN_PEPPER_ROOT", {}).get("cap_usage_ratio"),
            "pepper_markout_5": artefact.behaviour.get("per_product", {}).get("INTARIAN_PEPPER_ROOT", {}).get("average_fill_markout_5"),
        })
    comparison_rows.sort(key=lambda row: float(row["final_pnl"]), reverse=True)
    dashboard = build_dashboard_payload(
        run_type="comparison",
        run_name=run_name,
        trader_name="multiple",
        mode="replay",
        fill_model=resolve_fill_model(fill_model_name).to_dict(),
        perturbations=perturbation.to_dict(),
        comparison_rows=comparison_rows,
    )
    write_run_bundle(output_dir, dashboard, extra_csvs={"comparison.csv": comparison_rows})
    write_manifest(output_dir, {"run_type": "comparison", "run_name": run_name, "row_count": len(comparison_rows)})
    return comparison_rows


def run_sweep_from_config(config_path: Path, output_dir: Path) -> List[Dict[str, object]]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    trader_path = Path(config["trader"])
    base_name = config.get("name", config_path.stem)
    days = tuple(config.get("days", [-2, -1, 0]))
    fill_model_name = config.get("fill_model", "base")
    perturbation = PerturbationConfig(**config.get("perturbation", {}))
    trader_specs = [
        TraderSpec(
            name=variant["name"],
            path=trader_path,
            overrides=variant.get("overrides"),
        )
        for variant in config["variants"]
    ]
    return run_compare(
        trader_specs=trader_specs,
        days=days,
        data_dir=Path(config.get("data_dir", DEFAULT_DATA_DIR)),
        fill_model_name=fill_model_name,
        perturbation=perturbation,
        output_dir=output_dir,
        run_name=base_name,
    )


def calibrate_against_live_export(
    *,
    trader_spec: TraderSpec,
    days: Sequence[int],
    data_dir: Path,
    live_export_path: Path,
    output_dir: Path,
    quick: bool = False,
) -> Dict[str, object]:
    if quick:
        candidate_fill_models = ["base", "conservative"]
        candidate_scales = [0.70, 1.00]
        candidate_adverse = [0, 1]
        candidate_latency = [0]
        candidate_missed = [0.0, 0.05]
    else:
        candidate_fill_models = ["optimistic", "base", "conservative"]
        candidate_scales = [0.50, 0.70, 0.85, 1.00]
        candidate_adverse = [0, 1, 2]
        candidate_latency = [0, 1]
        candidate_missed = [0.0, 0.05]
    rows: List[Dict[str, object]] = []
    best_row: Dict[str, object] | None = None
    for fill_model_name in candidate_fill_models:
        for passive_fill_scale in candidate_scales:
            for adverse_ticks in candidate_adverse:
                for latency_ticks in candidate_latency:
                    for missed_fill_additive in candidate_missed:
                        perturbation = PerturbationConfig(
                            passive_fill_scale=passive_fill_scale,
                            adverse_selection_ticks=adverse_ticks,
                            latency_ticks=latency_ticks,
                            missed_fill_additive=missed_fill_additive,
                        )
                        artefact = run_replay(
                            trader_spec=trader_spec,
                            days=days,
                            data_dir=data_dir,
                            fill_model_name=fill_model_name,
                            perturbation=perturbation,
                            output_dir=output_dir / f"{fill_model_name}_{passive_fill_scale:.2f}_{adverse_ticks}_{latency_ticks}_{missed_fill_additive:.2f}",
                            run_name=f"calibration_{fill_model_name}_{passive_fill_scale:.2f}_{adverse_ticks}_{latency_ticks}_{missed_fill_additive:.2f}",
                            live_export_path=live_export_path,
                            register=False,
                        )
                        validation = dict(artefact.validation)
                        per_product = validation.get("per_product_pnl", {})
                        row = {
                            "fill_model": fill_model_name,
                            "passive_fill_scale": passive_fill_scale,
                            "adverse_selection_ticks": adverse_ticks,
                            "latency_ticks": latency_ticks,
                            "missed_fill_additive": missed_fill_additive,
                            **validation,
                            "osmium_path_rmse": (per_product.get("ASH_COATED_OSMIUM") or {}).get("path_rmse"),
                            "pepper_path_rmse": (per_product.get("INTARIAN_PEPPER_ROOT") or {}).get("path_rmse"),
                            "osmium_pnl_error": (per_product.get("ASH_COATED_OSMIUM") or {}).get("pnl_error"),
                            "pepper_pnl_error": (per_product.get("INTARIAN_PEPPER_ROOT") or {}).get("pnl_error"),
                        }
                        row["score"] = (
                            abs(float(row.get("profit_error") or 0.0)) * 0.18
                            + abs(float(row.get("fill_count_error") or 0.0)) * 8.0
                            + abs(float(row.get("position_l1_error") or 0.0)) * 32.0
                            + abs(float(row.get("path_rmse") or 0.0)) * 1.0
                            + abs(float(row.get("osmium_path_rmse") or 0.0)) * 0.45
                            + abs(float(row.get("pepper_path_rmse") or 0.0)) * 0.45
                        )
                        row["profit_bias"] = _profit_bias(row.get("profit_error"))
                        row["fill_bias"] = _fill_bias(row.get("fill_count_error"))
                        row["dominant_error_source"] = _dominant_calibration_error(row)
                        rows.append(row)
                        if best_row is None or row["score"] < best_row["score"]:
                            best_row = row
    rows.sort(key=lambda row: row["score"])
    dashboard = build_dashboard_payload(
        run_type="calibration",
        run_name=output_dir.name,
        trader_name=trader_spec.name,
        mode="replay",
        fill_model={"name": "grid"},
        perturbations={},
        calibration_grid=rows,
        calibration_best=best_row,
    )
    write_run_bundle(output_dir, dashboard, extra_csvs={"calibration_grid.csv": rows})
    write_manifest(output_dir, {"run_type": "calibration", "grid_size": len(rows), "best": best_row, "quick": quick})
    assert best_row is not None
    return best_row


def _quantile(values: List[float], q: float) -> float:
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    idx = q * (len(s) - 1)
    lo = int(idx)
    hi = min(len(s) - 1, lo + 1)
    w = idx - lo
    return s[lo] * (1.0 - w) + s[hi] * w


def _profit_bias(value: object) -> str:
    if value is None:
        return "unknown"
    number = float(value)
    if number > 0:
        return "optimistic"
    if number < 0:
        return "pessimistic"
    return "neutral"


def _fill_bias(value: object) -> str:
    if value is None:
        return "unknown"
    number = float(value)
    if number > 0:
        return "overfilled"
    if number < 0:
        return "underfilled"
    return "neutral"


def _dominant_calibration_error(row: Dict[str, object]) -> str:
    components = {
        "profit": abs(float(row.get("profit_error") or 0.0)) * 0.18,
        "fill_count": abs(float(row.get("fill_count_error") or 0.0)) * 8.0,
        "position": abs(float(row.get("position_l1_error") or 0.0)) * 32.0,
        "total_path": abs(float(row.get("path_rmse") or 0.0)),
        "osmium_path": abs(float(row.get("osmium_path_rmse") or 0.0)) * 0.45,
        "pepper_path": abs(float(row.get("pepper_path_rmse") or 0.0)) * 0.45,
    }
    return max(components, key=components.get)


def run_optimize_from_config(config_path: Path, output_dir: Path) -> List[Dict[str, object]]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    trader_path = Path(config["trader"])
    run_name = config.get("name", config_path.stem)
    data_dir = Path(config.get("data_dir", DEFAULT_DATA_DIR))
    days = tuple(config.get("days", [-2, -1, 0]))
    fill_model_name = config.get("fill_model", "base")
    perturbation = PerturbationConfig(**config.get("perturbation", {}))
    mc_sessions = int(config.get("mc_sessions", 24))
    mc_sample_sessions = int(config.get("mc_sample_sessions", min(6, mc_sessions)))
    mc_seed = int(config.get("mc_seed", 20260418))
    mc_workers = int(config.get("mc_workers", 1))
    weights = {
        "replay": 1.0,
        "mc_mean": 0.35,
        "mc_p05": 0.50,
        "mc_expected_shortfall": 0.45,
        "mc_std": -0.25,
        "mc_drawdown": -0.20,
        "limit_breaches": -100.0,
    }
    weights.update(config.get("score_weights", {}))

    rows: List[Dict[str, object]] = []
    for idx, variant in enumerate(config["variants"]):
        spec = TraderSpec(name=variant["name"], path=trader_path, overrides=variant.get("overrides"))
        variant_dir = output_dir / variant["name"]
        replay = run_replay(
            trader_spec=spec,
            days=days,
            data_dir=data_dir,
            fill_model_name=fill_model_name,
            perturbation=perturbation,
            output_dir=variant_dir / "replay",
            run_name=f"{run_name}_{variant['name']}_replay",
            register=False,
        )
        mc = run_monte_carlo(
            trader_spec=spec,
            sessions=mc_sessions,
            sample_sessions=mc_sample_sessions,
            days=days,
            fill_model_name=fill_model_name,
            perturbation=perturbation,
            output_dir=variant_dir / "monte_carlo",
            base_seed=mc_seed + idx * 1000,
            run_name=f"{run_name}_{variant['name']}_mc",
            workers=mc_workers,
            register=False,
        )
        mc_final = [float(session.summary["final_pnl"]) for session in mc]
        p05 = _quantile(mc_final, 0.05)
        mean = statistics.fmean(mc_final)
        std = statistics.pstdev(mc_final) if len(mc_final) > 1 else 0.0
        tail = [value for value in mc_final if value <= p05]
        expected_shortfall = statistics.fmean(tail) if tail else p05
        limit_breaches = sum(int(session.summary["limit_breaches"]) for session in mc)
        mc_drawdown = statistics.fmean(float(session.summary.get("max_drawdown", 0.0)) for session in mc)
        score = (
            weights["replay"] * float(replay.summary["final_pnl"])
            + weights["mc_mean"] * float(mean)
            + weights["mc_p05"] * float(p05)
            + weights.get("mc_expected_shortfall", 0.0) * float(expected_shortfall)
            + weights["mc_std"] * float(std)
            + weights.get("mc_drawdown", 0.0) * float(mc_drawdown)
            + weights["limit_breaches"] * float(limit_breaches)
        )
        rows.append({
            "variant": variant["name"],
            "overrides": describe_overrides(spec.overrides),
            "replay_final_pnl": replay.summary["final_pnl"],
            "replay_max_drawdown": replay.summary.get("max_drawdown"),
            "replay_fill_count": replay.summary["fill_count"],
            "mc_mean": mean,
            "mc_p05": p05,
            "mc_expected_shortfall_05": expected_shortfall,
            "mc_std": std,
            "mc_positive_rate": sum(1 for value in mc_final if value > 0) / len(mc_final),
            "mc_mean_drawdown": mc_drawdown,
            "mc_limit_breaches": limit_breaches,
            "score": score,
        })
    rows.sort(key=lambda row: row["score"], reverse=True)
    dashboard = build_dashboard_payload(
        run_type="optimization",
        run_name=run_name,
        trader_name=trader_path.stem,
        mode="replay+monte_carlo",
        fill_model=resolve_fill_model(fill_model_name).to_dict(),
        perturbations=perturbation.to_dict(),
        optimization_rows=rows,
    )
    write_run_bundle(output_dir, dashboard, extra_csvs={"optimization.csv": rows})
    write_manifest(output_dir, {"run_type": "optimization", "run_name": run_name, "row_count": len(rows), "best_variant": rows[0] if rows else None})
    return rows
