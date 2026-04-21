from __future__ import annotations

import json
import random
import statistics
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Dict, Sequence

from .dataset import load_round_dataset
from .experiments import TraderSpec, _dataset_reports, default_data_dir_for_round, run_compare, run_monte_carlo, run_replay
from .fill_models import resolve_fill_model
from .platform import PerturbationConfig, run_market_session, summarise_monte_carlo_sessions
from .reports import build_dashboard_payload, compact_replay_rows, write_replay_bundle
from .round2 import AccessScenario, NO_ACCESS_SCENARIO
from .storage import OutputOptions
from .trader_adapter import make_trader


@dataclass(frozen=True)
class ResearchPackPreset:
    name: str
    replay_days: tuple[int, ...]
    compare_days: tuple[int, ...]
    mc_days: tuple[int, ...]
    mc_sessions: int
    mc_sample_sessions: int
    mc_synthetic_tick_limit: int | None
    replay_output_profile: str = "light"
    mc_output_profile: str = "light"
    description: str = ""


RESEARCH_PACK_PRESETS: Dict[str, ResearchPackPreset] = {
    "fast": ResearchPackPreset(
        name="fast",
        replay_days=(0,),
        compare_days=(0,),
        mc_days=(0,),
        mc_sessions=8,
        mc_sample_sessions=2,
        mc_synthetic_tick_limit=250,
        description="Routine branch loop: one-day replay, one-day compare and a tiny smoke Monte Carlo run.",
    ),
    "validation": ResearchPackPreset(
        name="validation",
        replay_days=(-2, -1, 0),
        compare_days=(-2, -1, 0),
        mc_days=(0,),
        mc_sessions=24,
        mc_sample_sessions=4,
        mc_synthetic_tick_limit=1000,
        description="Promising branch loop: three-day replay and compare, with a stronger but still deliberate Monte Carlo check.",
    ),
    "forensic": ResearchPackPreset(
        name="forensic",
        replay_days=(-2, -1, 0),
        compare_days=(-2, -1, 0),
        mc_days=(-2, -1, 0),
        mc_sessions=64,
        mc_sample_sessions=8,
        mc_synthetic_tick_limit=None,
        replay_output_profile="full",
        mc_output_profile="full",
        description="Finalist or suspicious-case loop: full-fidelity replay plus heavier Monte Carlo evidence.",
    ),
}


def default_fill_mode_for_round(round_number: int) -> str:
    return "base" if int(round_number) == 2 else "empirical_baseline"


def get_research_pack_preset(name: str) -> ResearchPackPreset:
    try:
        return RESEARCH_PACK_PRESETS[str(name).strip().lower()]
    except KeyError as exc:
        valid = ", ".join(sorted(RESEARCH_PACK_PRESETS))
        raise ValueError(f"Unknown research pack preset {name!r}. Expected one of: {valid}") from exc


def _profile_day_output_dir(output_root: Path | None, trader_name: str, day: int) -> Path | None:
    if output_root is None:
        return None
    return output_root / f"day_{day}_{trader_name}"


def _mc_perturbation(perturbation: PerturbationConfig, tick_limit: int | None) -> PerturbationConfig:
    if tick_limit is None:
        return perturbation
    return replace(perturbation, synthetic_tick_limit=int(tick_limit))


def _write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def profile_replay_case(
    *,
    trader_spec: TraderSpec,
    day: int,
    data_dir: Path,
    fill_model_name: str,
    perturbation: PerturbationConfig,
    round_number: int = 1,
    access_scenario: AccessScenario | None = None,
    output_dir: Path | None = None,
    output_options: OutputOptions | None = None,
    write_bundle: bool = True,
) -> Dict[str, object]:
    output_options = output_options or OutputOptions()
    access_scenario = access_scenario or NO_ACCESS_SCENARIO
    fill_model = resolve_fill_model(fill_model_name, None)

    started = time.perf_counter()
    datasets_map = load_round_dataset(data_dir, (day,), round_number=round_number)
    datasets = [datasets_map[day]]
    after_dataset = time.perf_counter()
    trader, _module = make_trader(trader_spec.path, trader_spec.overrides)
    after_trader = time.perf_counter()
    artefact = run_market_session(
        trader=trader,
        trader_name=trader_spec.name,
        market_days=datasets,
        fill_model=fill_model,
        perturb=perturbation,
        rng=random.Random(20260418),
        run_name=f"profile_day_{day}_{trader_spec.name}",
        mode="replay",
        capture_full_output=True,
        access_scenario=access_scenario,
    )
    after_session = time.perf_counter()
    replay_rows = compact_replay_rows(artefact, output_options)
    after_compaction = time.perf_counter()
    dashboard = build_dashboard_payload(
        run_type="replay",
        run_name=artefact.run_name,
        trader_name=trader_spec.name,
        mode="replay",
        fill_model=fill_model.to_dict(),
        perturbations=perturbation.to_dict(),
        round_number=round_number,
        access_scenario=access_scenario.to_dict(),
        replay_result=artefact,
        dataset_reports=_dataset_reports(datasets),
        validation={},
        replay_rows=replay_rows,
        output_options=output_options,
    )
    after_dashboard = time.perf_counter()
    if write_bundle:
        if output_dir is None:
            raise ValueError("output_dir is required when write_bundle=True")
        write_replay_bundle(
            output_dir,
            artefact,
            dashboard,
            register=False,
            replay_rows=replay_rows,
            output_options=output_options,
        )
    after_write = time.perf_counter()

    return {
        "trader": trader_spec.name,
        "trader_path": str(trader_spec.path),
        "day": int(day),
        "round": int(round_number),
        "fill_model": fill_model_name,
        "output_profile": output_options.profile,
        "timings": {
            "load_dataset_seconds": round(after_dataset - started, 3),
            "make_trader_seconds": round(after_trader - after_dataset, 3),
            "run_market_session_seconds": round(after_session - after_trader, 3),
            "compact_rows_seconds": round(after_compaction - after_session, 3),
            "build_dashboard_seconds": round(after_dashboard - after_compaction, 3),
            "write_bundle_seconds": round(after_write - after_dashboard, 3),
            "total_seconds": round(after_write - started, 3),
        },
        "row_counts": {
            "orders": len(artefact.orders),
            "fills": len(artefact.fills),
            "inventory_series": len(artefact.inventory_series),
            "pnl_series": len(artefact.pnl_series),
            "fair_value_series": len(artefact.fair_value_series),
            "behaviour_series": len(artefact.behaviour_series),
        },
        "per_product": {
            product: {
                "order_count": sum(1 for row in artefact.orders if row.get("product") == product),
                "fill_count": sum(1 for row in artefact.fills if row.get("product") == product),
            }
            for product in artefact.summary["per_product"]
        },
        "summary": {
            "final_pnl": artefact.summary["final_pnl"],
            "max_drawdown": artefact.summary.get("max_drawdown"),
            "fill_count": artefact.summary.get("fill_count"),
            "order_count": artefact.summary.get("order_count"),
            "limit_breaches": artefact.summary.get("limit_breaches"),
        },
        "output_dir": None if output_dir is None else str(output_dir),
    }


def profile_replay_suite(
    *,
    trader_spec: TraderSpec,
    days: Sequence[int],
    data_dir: Path,
    fill_model_name: str,
    perturbation: PerturbationConfig,
    round_number: int = 1,
    access_scenario: AccessScenario | None = None,
    output_root: Path | None = None,
    compare_trader_spec: TraderSpec | None = None,
    output_options: OutputOptions | None = None,
    write_bundle: bool = True,
) -> Dict[str, object]:
    output_options = output_options or OutputOptions()
    access_scenario = access_scenario or NO_ACCESS_SCENARIO
    rows = [
        profile_replay_case(
            trader_spec=trader_spec,
            day=int(day),
            data_dir=data_dir,
            fill_model_name=fill_model_name,
            perturbation=perturbation,
            round_number=round_number,
            access_scenario=access_scenario,
            output_dir=_profile_day_output_dir(output_root, trader_spec.name, int(day)),
            output_options=output_options,
            write_bundle=write_bundle,
        )
        for day in days
    ]
    slowest = max(rows, key=lambda row: float(row["timings"]["total_seconds"]))
    comparison = None
    if compare_trader_spec is not None:
        slowest_day = int(slowest["day"])
        comparison = profile_replay_case(
            trader_spec=compare_trader_spec,
            day=slowest_day,
            data_dir=data_dir,
            fill_model_name=fill_model_name,
            perturbation=perturbation,
            round_number=round_number,
            access_scenario=access_scenario,
            output_dir=_profile_day_output_dir(output_root, compare_trader_spec.name, slowest_day),
            output_options=output_options,
            write_bundle=write_bundle,
        )
    report = {
        "trader": trader_spec.name,
        "days": [int(day) for day in days],
        "fill_model": fill_model_name,
        "round": int(round_number),
        "slowest_day": int(slowest["day"]),
        "rows": rows,
        "comparison_case": comparison,
        "diagnosis": {
            "dominant_day": int(slowest["day"]),
            "slowest_total_seconds": slowest["timings"]["total_seconds"],
            "slowest_market_session_seconds": slowest["timings"]["run_market_session_seconds"],
            "slowest_compaction_seconds": slowest["timings"]["compact_rows_seconds"],
            "slowest_bundle_write_seconds": round(
                float(slowest["timings"]["build_dashboard_seconds"]) + float(slowest["timings"]["write_bundle_seconds"]),
                3,
            ),
        },
    }
    if output_root is not None:
        _write_json(output_root / "profile_report.json", report)
    return report


def run_research_pack(
    *,
    preset_name: str,
    trader_spec: TraderSpec,
    baseline_spec: TraderSpec,
    output_root: Path,
    round_number: int = 1,
    data_dir: Path | None = None,
    fill_model_name: str | None = None,
    perturbation: PerturbationConfig | None = None,
    access_scenario: AccessScenario | None = None,
    mc_workers: int = 1,
) -> Dict[str, object]:
    preset = get_research_pack_preset(preset_name)
    data_dir = data_dir or default_data_dir_for_round(round_number)
    fill_model_name = fill_model_name or default_fill_mode_for_round(round_number)
    perturbation = perturbation or PerturbationConfig()
    access_scenario = access_scenario or NO_ACCESS_SCENARIO
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    replay_dir = output_root / "replay"
    compare_dir = output_root / "compare"
    monte_carlo_dir = output_root / "monte_carlo"

    replay = run_replay(
        trader_spec=trader_spec,
        days=preset.replay_days,
        data_dir=data_dir,
        fill_model_name=fill_model_name,
        perturbation=perturbation,
        output_dir=replay_dir,
        run_name=f"{output_root.name}_replay",
        round_number=round_number,
        access_scenario=access_scenario,
        output_options=OutputOptions.from_profile(preset.replay_output_profile),
    )
    comparison_rows = run_compare(
        trader_specs=[trader_spec, baseline_spec],
        days=preset.compare_days,
        data_dir=data_dir,
        fill_model_name=fill_model_name,
        perturbation=perturbation,
        output_dir=compare_dir,
        run_name=f"{output_root.name}_compare",
        round_number=round_number,
        access_scenario=access_scenario,
        output_options=OutputOptions.from_profile("light"),
    )
    mc_results = run_monte_carlo(
        trader_spec=trader_spec,
        sessions=preset.mc_sessions,
        sample_sessions=preset.mc_sample_sessions,
        days=preset.mc_days,
        fill_model_name=fill_model_name,
        perturbation=_mc_perturbation(perturbation, preset.mc_synthetic_tick_limit),
        output_dir=monte_carlo_dir,
        base_seed=20260418,
        run_name=f"{output_root.name}_mc",
        workers=mc_workers,
        round_number=round_number,
        access_scenario=access_scenario,
        output_options=OutputOptions.from_profile(preset.mc_output_profile),
    )
    mc_summary = summarise_monte_carlo_sessions(list(mc_results))
    finals = [float(result.summary["final_pnl"]) for result in mc_results]
    comparison_best = comparison_rows[0] if comparison_rows else {}
    summary = {
        "preset": asdict(preset),
        "round": int(round_number),
        "data_dir": str(data_dir),
        "fill_model": fill_model_name,
        "trader": {"name": trader_spec.name, "path": str(trader_spec.path)},
        "baseline": {"name": baseline_spec.name, "path": str(baseline_spec.path)},
        "outputs": {
            "root": str(output_root),
            "replay": str(replay_dir),
            "compare": str(compare_dir),
            "monte_carlo": str(monte_carlo_dir),
        },
        "replay": {
            "final_pnl": replay.summary["final_pnl"],
            "max_drawdown": replay.summary.get("max_drawdown"),
            "fill_count": replay.summary.get("fill_count"),
            "order_count": replay.summary.get("order_count"),
        },
        "comparison": {
            "best_trader": comparison_best.get("trader"),
            "best_final_pnl": comparison_best.get("final_pnl"),
            "rows": comparison_rows,
        },
        "monte_carlo": {
            "sessions": len(mc_results),
            "sample_sessions": preset.mc_sample_sessions,
            "synthetic_tick_limit": preset.mc_synthetic_tick_limit,
            "summary": mc_summary,
            "mean_final_pnl": None if not finals else statistics.fmean(finals),
        },
        "notes": [
            "Fast and validation packs stay in light mode so the dashboard remains small and quick to load.",
            "Calibration is not part of the default pack. Run it deliberately when live-export evidence matters.",
            "Comparison stays aggregate-only by default. Use standalone replay or compare in full mode when raw orders are required.",
        ],
    }
    _write_json(output_root / "pack_summary.json", summary)
    return summary
