from __future__ import annotations

import concurrent.futures
import ctypes
import json
import multiprocessing
import os
import pickle
import random
import statistics
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence

from .dataset import DayDataset, load_round_dataset
from .fill_models import FillModel, derive_empirical_fill_profile, resolve_fill_model
from .live_export import compare_live_export_summary, load_live_export
from .mc_backends import (
    finalise_profile as finalise_mc_profile,
    merge_profile as merge_mc_profile,
    new_profile as new_mc_profile,
    normalise_monte_carlo_backend,
    prepare_streaming_simulation_context,
    resolve_monte_carlo_backend,
    run_rust_backend,
    run_streaming_synthetic_session,
)
from .platform import PerturbationConfig, SessionArtefacts, generate_synthetic_market_days, run_market_session
from .provenance import capture_provenance
from .reports import (
    all_session_path_band_method,
    accumulate_path_band_rows,
    build_dashboard_payload,
    compact_replay_rows,
    finalize_path_band_accumulator,
    merge_path_band_accumulators,
    new_path_band_accumulator,
    write_manifest,
    write_mc_bundle,
    write_replay_bundle,
    write_run_bundle,
)
from .round2 import AccessScenario, NO_ACCESS_SCENARIO, access_scenario_from_dict, expand_scenarios
from .round3 import prepare_round3_synthetic_context
from .metadata import RoundSpec, get_round_spec
from .scenarios import ResearchScenario, scenario_manifest, scenarios_from_config
from .storage import OutputOptions
from .trader_adapter import TraderLoadError, describe_overrides, load_trader_module, make_trader


@dataclass
class TraderSpec:
    name: str
    path: Path
    overrides: Dict[str, object] | None = None


DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data" / "round1"
DEFAULT_ROUND2_DATA_DIR = Path(__file__).parent.parent / "data" / "round2"
DEFAULT_ROUND3_DATA_DIR = Path(__file__).parent.parent / "data" / "round3"
DEFAULT_EXPORT_DIR = Path(__file__).parent.parent / "live_exports"

_MC_DIAGNOSTICS_PATH_ENV = "PROSPERITY_MC_DIAGNOSTICS_PATH"
_MC_PROFILE_INT_KEYS = (
    "session_count",
    "sampled_session_count",
    "classic_session_count",
    "streaming_session_count",
    "rust_session_count",
)
_MC_PROFILE_FLOAT_KEYS = (
    "market_generation_seconds",
    "state_build_seconds",
    "trader_seconds",
    "execution_seconds",
    "path_metrics_seconds",
    "postprocess_seconds",
    "session_total_seconds",
)


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


if os.name == "nt":
    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _PSAPI = ctypes.WinDLL("psapi")
    _GET_CURRENT_PROCESS = _KERNEL32.GetCurrentProcess
    _GET_CURRENT_PROCESS.restype = ctypes.c_void_p
    _GET_PROCESS_MEMORY_INFO = _PSAPI.GetProcessMemoryInfo
    _GET_PROCESS_MEMORY_INFO.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ProcessMemoryCounters),
        ctypes.c_ulong,
    ]
    _GET_PROCESS_MEMORY_INFO.restype = ctypes.c_int
else:
    _GET_CURRENT_PROCESS = None
    _GET_PROCESS_MEMORY_INFO = None


def default_data_dir_for_round(round_number: int) -> Path:
    spec = get_round_spec(round_number)
    return (Path(__file__).parent.parent / spec.default_data_dir).resolve()


def _validate_access_usage(round_spec: RoundSpec, access_scenario: AccessScenario) -> None:
    if round_spec.has_round2_access:
        return
    if access_scenario.enabled or access_scenario.contract_won or access_scenario.maf_bid:
        raise ValueError(
            f"Round {round_spec.round_number} does not support Round 2 access or MAF assumptions"
        )


def _current_process_rss_bytes() -> int | None:
    if os.name == "nt":
        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if _GET_CURRENT_PROCESS is None or _GET_PROCESS_MEMORY_INFO is None:
            return None
        if not _GET_PROCESS_MEMORY_INFO(
            _GET_CURRENT_PROCESS(),
            ctypes.byref(counters),
            counters.cb,
        ):
            return None
        return int(counters.WorkingSetSize)
    statm = Path("/proc/self/statm")
    if statm.is_file():
        try:
            parts = statm.read_text(encoding="utf-8").split()
            if len(parts) >= 2:
                return int(parts[1]) * int(os.sysconf("SC_PAGE_SIZE"))
        except (OSError, ValueError):
            return None
    return None


def _measure_phase_rss(run) -> tuple[object, Dict[str, object]]:
    rss_before = _current_process_rss_bytes()
    rss_peak = rss_before
    stop = threading.Event()

    def sampler() -> None:
        nonlocal rss_peak
        while not stop.wait(0.005):
            sample = _current_process_rss_bytes()
            if sample is None:
                continue
            rss_peak = sample if rss_peak is None else max(int(rss_peak), int(sample))

    worker = threading.Thread(target=sampler, daemon=True)
    worker.start()
    started = time.perf_counter()
    try:
        result = run()
    finally:
        elapsed = time.perf_counter() - started
        stop.set()
        worker.join(timeout=0.1)
    rss_after = _current_process_rss_bytes()
    if rss_after is not None:
        rss_peak = rss_after if rss_peak is None else max(int(rss_peak), int(rss_after))
    return result, {
        "elapsed_seconds": round(elapsed, 6),
        "rss_before_bytes": rss_before,
        "rss_after_bytes": rss_after,
        "rss_delta_bytes": None if rss_before is None or rss_after is None else int(rss_after) - int(rss_before),
        "rss_peak_bytes": rss_peak,
    }


def _mc_diagnostics_path() -> Path | None:
    path_text = os.environ.get(_MC_DIAGNOSTICS_PATH_ENV)
    if not path_text:
        return None
    if multiprocessing.current_process().name != "MainProcess":
        return None
    return Path(path_text)


def _mc_diagnostics_enabled() -> bool:
    return bool(os.environ.get(_MC_DIAGNOSTICS_PATH_ENV))


def _diagnostic_pickle_size_bytes(value: object) -> int | None:
    if not _mc_diagnostics_enabled():
        return None
    try:
        return len(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))
    except Exception:
        return None


def _record_mc_diagnostic(event: str, **payload: object) -> None:
    path = _mc_diagnostics_path()
    if path is None:
        return
    row = {
        "event": event,
        "perf_counter_seconds": round(time.perf_counter(), 6),
        "pid": os.getpid(),
        **payload,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def _merge_mc_chunk_profile(profile: Dict[str, object], chunk_profile: Mapping[str, object]) -> None:
    for key in _MC_PROFILE_INT_KEYS:
        profile[key] = int(profile.get(key, 0) or 0) + int(chunk_profile.get(key, 0) or 0)
    for key in _MC_PROFILE_FLOAT_KEYS:
        profile[key] = float(profile.get(key, 0.0) or 0.0) + float(chunk_profile.get(key, 0.0) or 0.0)


def _sampled_result_count(results: Sequence[SessionArtefacts]) -> int:
    return sum(1 for result in results if result.inventory_series)


def _record_chunk_output_diagnostic(
    chunk_output: Mapping[str, object],
    *,
    chunk_index: int,
    accumulated_result_count: int,
) -> None:
    diagnostics = chunk_output.get("diagnostics")
    diagnostics_payload = diagnostics if isinstance(diagnostics, Mapping) else {}
    chunk_results_raw = chunk_output.get("results")
    chunk_results = list(chunk_results_raw) if isinstance(chunk_results_raw, list) else []
    _record_mc_diagnostic(
        "chunk_output_received",
        chunk_index=int(chunk_index),
        chunk_result_count=len(chunk_results),
        chunk_sampled_result_count=_sampled_result_count(chunk_results),
        accumulated_result_count=int(accumulated_result_count),
        chunk_payload_pickle_bytes=diagnostics_payload.get("chunk_payload_pickle_bytes"),
        chunk_path_band_accumulator_pickle_bytes=diagnostics_payload.get("path_band_accumulator_pickle_bytes"),
    )


def _load_json_config(config_path: Path) -> Dict[str, object]:
    config_path = config_path.resolve()
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON config {config_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Config must be a JSON object: {config_path}")
    return payload


def _resolve_config_path(config_path: Path, value: object) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    cwd_candidate = (Path.cwd() / path).resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    return (config_path.resolve().parent / path).resolve()


def _optional_config_path(config: Mapping[str, object], config_path: Path, key: str) -> Path | None:
    value = config.get(key)
    if value in (None, ""):
        return None
    return _resolve_config_path(config_path, value)


def _config_data_dir(config: Mapping[str, object], config_path: Path, round_number: int) -> Path:
    value = config.get("data_dir")
    if value in (None, ""):
        return default_data_dir_for_round(round_number)
    return _resolve_config_path(config_path, value)


def _config_days(config: Mapping[str, object]) -> tuple[int, ...]:
    raw_days = config.get("days", [-2, -1, 0])
    if not isinstance(raw_days, list) or not raw_days:
        raise ValueError("Config field 'days' must be a non-empty list of integers")
    return tuple(int(day) for day in raw_days)


def _config_variants(config: Mapping[str, object], config_path: Path) -> List[Mapping[str, object]]:
    variants = config.get("variants")
    if not isinstance(variants, list) or not variants:
        raise ValueError(f"{config_path}: expected a non-empty 'variants' list")
    if not all(isinstance(variant, Mapping) for variant in variants):
        raise ValueError(f"{config_path}: every variant must be an object")
    return list(variants)


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


def _data_scope_context(
    *,
    round_number: int,
    days: Sequence[int],
    source: str,
    data_dir: Path | None = None,
) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "round": int(round_number),
        "days": [int(day) for day in days],
        "source": str(source),
    }
    if data_dir is not None:
        payload["data_dir"] = str(data_dir)
    return payload


def _mc_runtime_context(
    *,
    workers: int,
    sessions: int,
    sample_sessions: int,
    monte_carlo_backend: str | None = None,
    data_scope: Dict[str, object] | None = None,
) -> Dict[str, object]:
    resolved = normalise_monte_carlo_backend(monte_carlo_backend) if monte_carlo_backend else None
    rust_active = resolved == "rust" and int(sessions) > 0
    if rust_active:
        engine_backend = "rust"
        parallelism = "rayon" if int(workers) > 1 else "single_thread"
    else:
        engine_backend = "python"
        parallelism = "process_pool" if int(workers) > 1 and int(sessions) > 0 else "single_process"
    runtime_context: Dict[str, object] = {
        "engine_backend": engine_backend,
        "parallelism": parallelism,
        "worker_count": int(workers) if int(sessions) > 0 else 1,
        "session_count": int(sessions),
        "sample_session_count": int(sample_sessions),
    }
    if resolved is not None and int(sessions) > 0:
        runtime_context["monte_carlo_backend"] = resolved
    if data_scope is not None:
        runtime_context["data_scope"] = data_scope
    return runtime_context


def run_replay(
    *,
    trader_spec: TraderSpec,
    days: Sequence[int],
    data_dir: Path,
    fill_model_name: str,
    perturbation: PerturbationConfig,
    fill_model_config_path: Path | None = None,
    output_dir: Path,
    run_name: str,
    live_export_path: Path | None = None,
    round_number: int = 1,
    access_scenario: AccessScenario | None = None,
    register: bool = True,
    write_bundle: bool = True,
    output_options: OutputOptions | None = None,
    print_trader_output: bool = False,
) -> SessionArtefacts:
    output_options = output_options or OutputOptions()
    access_scenario = access_scenario or NO_ACCESS_SCENARIO
    round_spec = get_round_spec(round_number)
    _validate_access_usage(round_spec, access_scenario)
    datasets_map = load_round_dataset(data_dir, days, round_number=round_number, round_spec=round_spec)
    datasets = [datasets_map[day] for day in days]
    live_export = load_live_export(live_export_path) if live_export_path is not None else None
    if live_export is not None:
        datasets = [live_export.day_dataset]
    trader, _module = make_trader(trader_spec.path, trader_spec.overrides)
    fill_model = resolve_fill_model(fill_model_name, fill_model_config_path)
    artefact = run_market_session(
        trader=trader,
        trader_name=trader_spec.name,
        market_days=datasets,
        fill_model=fill_model,
        perturb=perturbation,
        rng=random.Random(20260418),
        run_name=run_name,
        mode="replay",
        round_spec=round_spec,
        capture_full_output=True,
        access_scenario=access_scenario,
        print_trader_output=print_trader_output,
        include_option_diagnostics=bool(write_bundle),
    )
    validation = {}
    if live_export is not None:
        validation = compare_live_export_summary(live_export, artefact)
        artefact.validation = validation
    if write_bundle:
        runtime_context = {
            "engine_backend": "python",
            "parallelism": "single_process",
            "worker_count": 1,
            "data_scope": _data_scope_context(
                round_number=round_number,
                days=days,
                data_dir=data_dir,
                source="live_export" if live_export is not None else "historical",
            ),
        }
        if live_export_path is not None:
            runtime_context["live_export_path"] = str(live_export_path)
        replay_rows = compact_replay_rows(artefact, output_options)
        dashboard = build_dashboard_payload(
            run_type="replay",
            run_name=run_name,
            trader_name=trader_spec.name,
            mode="replay",
            fill_model=fill_model.to_dict(),
            perturbations=perturbation.to_dict(),
            round_number=round_number,
            access_scenario=access_scenario.to_dict(),
            replay_result=artefact,
            dataset_reports=_dataset_reports(datasets),
            validation=validation,
            replay_rows=replay_rows,
            output_options=output_options,
            runtime_context=runtime_context,
        )
        write_replay_bundle(
            output_dir,
            artefact,
            dashboard,
            register=register,
            replay_rows=replay_rows,
            output_options=output_options,
            runtime_context=runtime_context,
        )
    return artefact


def _instantiate_worker_trader(module, trader_path: Path):
    try:
        trader = module.Trader()
    except Exception as exc:  # pragma: no cover - exercised through workers
        raise TraderLoadError(f"Trader() construction failed for {trader_path}: {exc}") from exc
    if not callable(getattr(trader, "run", None)):
        raise TraderLoadError(f"Trader instance does not define callable run(state): {trader_path}")
    return trader


def _run_monte_carlo_chunk(task: Dict[str, object]) -> Dict[str, object]:
    session_indices = [int(session_idx) for session_idx in task["session_indices"]]
    sample_sessions = int(task["sample_sessions"])
    base_seed = int(task["base_seed"])
    run_name = str(task["run_name"])
    backend = normalise_monte_carlo_backend(str(task.get("monte_carlo_backend", "auto")))
    trader_spec = task["trader_spec"]
    assert isinstance(trader_spec, TraderSpec)
    perturbation = task["perturbation"]
    assert isinstance(perturbation, PerturbationConfig)
    access_scenario = task.get("access_scenario") or NO_ACCESS_SCENARIO
    assert isinstance(access_scenario, AccessScenario)
    round_number = int(task.get("round_number", 1) or 1)
    round_spec = get_round_spec(round_number)
    _validate_access_usage(round_spec, access_scenario)
    fill_model = task["fill_model"]
    assert isinstance(fill_model, FillModel)
    days = tuple(int(day) for day in task["days"])
    module = load_trader_module(trader_spec.path, trader_spec.overrides)
    if backend == "rust":
        raise RuntimeError("Rust Monte Carlo backend is orchestrated outside the Python chunk runner")
    streaming_context = (
        prepare_streaming_simulation_context(perturbation)
        if backend == "streaming" and round_spec.round_number != 3
        else None
    )
    round3_context = task.get("round3_context")
    results: List[SessionArtefacts] = []
    profile = new_mc_profile(backend)
    path_band_accumulator = new_path_band_accumulator() if bool(task.get("aggregate_path_bands", False)) else None
    for session_idx in session_indices:
        trader = _instantiate_worker_trader(module, trader_spec.path)
        capture_full_output = session_idx < sample_sessions
        if backend == "streaming" and round_spec.round_number != 3 and not capture_full_output:
            result, session_profile = run_streaming_synthetic_session(
                trader=trader,
                trader_name=trader_spec.name,
                fill_model=fill_model,
                perturb=perturbation,
                days=days,
                market_seed=base_seed + session_idx * 17,
                execution_seed=base_seed + session_idx * 31,
                run_name=f"{run_name}_session_{session_idx:04d}",
                path_bucket_count=int(task.get("path_bucket_count", 800)),
                access_scenario=access_scenario,
                print_trader_output=bool(task.get("print_trader_output", False)),
                simulation_context=streaming_context,
                round_spec=round_spec,
            )
            if path_band_accumulator is not None and result.path_metrics:
                accumulate_path_band_rows(path_band_accumulator, result.path_metrics)
                result.path_metrics = []
            results.append(result)
            merge_mc_profile(profile, session_profile, sampled=False, execution_backend="streaming")
            continue

        generation_started = time.perf_counter()
        market_days = generate_synthetic_market_days(
            days=days,
            seed=base_seed + session_idx * 17,
            perturb=perturbation,
            round_spec=round_spec,
            round3_context=round3_context,
        )
        generation_seconds = time.perf_counter() - generation_started
        session_profile: Dict[str, object] = {}
        result = run_market_session(
            trader=trader,
            trader_name=trader_spec.name,
            market_days=market_days,
            fill_model=fill_model,
            perturb=perturbation,
            rng=random.Random(base_seed + session_idx * 31),
            run_name=f"{run_name}_session_{session_idx:04d}",
            mode="monte_carlo",
            round_spec=round_spec,
            capture_full_output=capture_full_output,
            capture_path_metrics=bool(task.get("capture_path_metrics", False)),
            path_bucket_count=int(task.get("path_bucket_count", 800)),
            access_scenario=access_scenario,
            print_trader_output=bool(task.get("print_trader_output", False)),
            timing_profile=session_profile,
            include_option_diagnostics=False,
        )
        session_profile["market_generation_seconds"] = round(generation_seconds, 6)
        if path_band_accumulator is not None and result.path_metrics:
            accumulate_path_band_rows(path_band_accumulator, result.path_metrics)
            result.path_metrics = []
        results.append(result)
        merge_mc_profile(profile, session_profile, sampled=capture_full_output, execution_backend="classic")
    payload = {
        "results": results,
        "profile": finalise_mc_profile(profile),
        "path_band_accumulator": path_band_accumulator,
    }
    if _mc_diagnostics_enabled():
        payload["diagnostics"] = {
            "chunk_payload_pickle_bytes": _diagnostic_pickle_size_bytes(payload),
            "path_band_accumulator_pickle_bytes": _diagnostic_pickle_size_bytes(path_band_accumulator),
        }
    return payload


def _group_session_indices(session_indices: Sequence[int], worker_count: int) -> List[List[int]]:
    indices = [int(session_idx) for session_idx in session_indices]
    if not indices:
        return []
    if worker_count <= 1:
        return [indices]
    chunk_count = min(len(indices), max(worker_count, worker_count * 2))
    groups: List[List[int]] = [[] for _ in range(chunk_count)]
    for offset, session_idx in enumerate(indices):
        groups[offset % chunk_count].append(session_idx)
    return [group for group in groups if group]


def _session_chunks(sessions: int, worker_count: int) -> List[List[int]]:
    return _group_session_indices(range(sessions), worker_count)


def _run_monte_carlo_profiled(
    *,
    trader_spec: TraderSpec,
    sessions: int,
    sample_sessions: int,
    days: Sequence[int],
    data_dir: Path | None,
    fill_model_name: str,
    perturbation: PerturbationConfig,
    output_dir: Path,
    base_seed: int,
    run_name: str,
    workers: int = 1,
    round_number: int = 1,
    access_scenario: AccessScenario | None = None,
    fill_model_config_path: Path | None = None,
    register: bool = True,
    write_bundle: bool = True,
    output_options: OutputOptions | None = None,
    print_trader_output: bool = False,
    monte_carlo_backend: str = "auto",
) -> tuple[List[SessionArtefacts], Dict[str, object]]:
    output_options = output_options or OutputOptions()
    if sessions < 1:
        raise ValueError("Monte Carlo sessions must be at least 1")
    sample_sessions = max(0, min(int(sample_sessions), int(sessions)))
    access_scenario = access_scenario or NO_ACCESS_SCENARIO
    round_spec = get_round_spec(round_number)
    _validate_access_usage(round_spec, access_scenario)
    fill_model = resolve_fill_model(fill_model_name, fill_model_config_path)
    resolved_backend = resolve_monte_carlo_backend(
        monte_carlo_backend,
        access_scenario=access_scenario,
        print_trader_output=print_trader_output,
    )
    if round_spec.round_number == 3 and resolved_backend == "streaming":
        resolved_backend = "classic"
    if round_spec.round_number == 3 and resolved_backend == "rust":
        raise ValueError("Rust Monte Carlo backend does not support Round 3")
    worker_count = max(1, int(workers))
    if worker_count > 1:
        worker_count = min(worker_count, sessions, os.cpu_count() or worker_count)
    profile = new_mc_profile(resolved_backend)
    precomputed_path_bands: Dict[str, Dict[str, List[Dict[str, object]]]] | None = None
    path_band_method: Dict[str, object] | None = None
    results: List[SessionArtefacts]
    round3_context = None
    if round_spec.round_number == 3:
        calibration_data_dir = data_dir or default_data_dir_for_round(round_number)
        historical_map = load_round_dataset(
            calibration_data_dir,
            round_spec.default_days,
            round_number=round_spec.round_number,
            round_spec=round_spec,
        )
        historical_days = [historical_map[day] for day in round_spec.default_days]
        tick_limit = None if perturbation.synthetic_tick_limit in (None, 0) else max(1, int(perturbation.synthetic_tick_limit))
        round3_context = prepare_round3_synthetic_context(
            historical_days,
            round_spec=round_spec,
            tick_count=tick_limit,
        )
    base_task = {
        "sample_sessions": sample_sessions,
        "base_seed": base_seed,
        "run_name": run_name,
        "trader_spec": trader_spec,
        "perturbation": perturbation,
        "access_scenario": access_scenario,
        "days": tuple(days),
        "fill_model": fill_model,
        "capture_path_metrics": True,
        "path_bucket_count": output_options.max_mc_path_rows_per_product,
        "print_trader_output": print_trader_output,
        "monte_carlo_backend": resolved_backend,
        "aggregate_path_bands": bool(write_bundle),
        "round_number": round_number,
        "round3_context": round3_context,
    }
    execution_started = time.perf_counter()
    diagnostics_enabled = _mc_diagnostics_enabled()
    _record_mc_diagnostic(
        "execution_started",
        backend=resolved_backend,
        worker_count=worker_count,
        session_count=sessions,
        sample_session_count=sample_sessions,
        write_bundle=bool(write_bundle),
    )
    if resolved_backend == "rust":
        rust_run = run_rust_backend(
            trader_name=trader_spec.name,
            trader_path=trader_spec.path,
            trader_overrides=trader_spec.overrides,
            fill_model=fill_model,
            perturb=perturbation,
            days=days,
            session_indices=tuple(range(sessions)),
            run_name=run_name,
            path_bucket_count=output_options.max_mc_path_rows_per_product,
            workers=worker_count,
            access_scenario=access_scenario,
            print_trader_output=print_trader_output,
            base_seed=base_seed,
        )
        results = list(rust_run.sessions)
        precomputed_path_bands = rust_run.path_bands
        for key in (
            "session_count",
            "sampled_session_count",
            "classic_session_count",
            "streaming_session_count",
            "rust_session_count",
        ):
            profile[key] = int(rust_run.profile.get(key, profile.get(key, 0)) or 0)
        for key in (
            "market_generation_seconds",
            "state_build_seconds",
            "trader_seconds",
            "execution_seconds",
            "path_metrics_seconds",
            "postprocess_seconds",
            "session_total_seconds",
        ):
            profile[key] = float(rust_run.profile.get(key, profile.get(key, 0.0)) or 0.0)
        rust_internal_wall = rust_run.profile.get("session_execution_wall_seconds")
        if rust_internal_wall is not None:
            profile["rust_internal_wall_seconds"] = float(rust_internal_wall)
        if sample_sessions > 0:
            sample_worker_count = min(worker_count, sample_sessions)
            sample_task = dict(base_task)
            sample_task["sample_sessions"] = sample_sessions
            sample_task["monte_carlo_backend"] = "classic"
            sample_task["aggregate_path_bands"] = False
            sample_chunk_tasks = [
                sample_task | {"session_indices": chunk}
                for chunk in _session_chunks(sample_sessions, sample_worker_count)
            ]
            sample_chunk_outputs: List[Dict[str, object]] = []
            if sample_worker_count == 1:
                for chunk_index, task in enumerate(sample_chunk_tasks):
                    chunk_output = _run_monte_carlo_chunk(task)
                    sample_chunk_outputs.append(chunk_output)
                    if diagnostics_enabled:
                        accumulated = sum(len(output.get("results") or []) for output in sample_chunk_outputs)
                        _record_chunk_output_diagnostic(chunk_output, chunk_index=chunk_index, accumulated_result_count=accumulated)
            else:
                with concurrent.futures.ProcessPoolExecutor(max_workers=sample_worker_count) as executor:
                    for chunk_index, chunk_output in enumerate(executor.map(_run_monte_carlo_chunk, sample_chunk_tasks)):
                        sample_chunk_outputs.append(chunk_output)
                        if diagnostics_enabled:
                            accumulated = sum(len(output.get("results") or []) for output in sample_chunk_outputs)
                            _record_chunk_output_diagnostic(chunk_output, chunk_index=chunk_index, accumulated_result_count=accumulated)
            sampled_results = [
                result
                for chunk_output in sample_chunk_outputs
                for result in chunk_output.get("results", [])
            ]
            for chunk_output in sample_chunk_outputs:
                chunk_profile = chunk_output.get("profile")
                if isinstance(chunk_profile, Mapping):
                    profile["classic_session_count"] = int(profile.get("classic_session_count", 0) or 0) + int(chunk_profile.get("classic_session_count", 0) or 0)
                    for key in _MC_PROFILE_FLOAT_KEYS:
                        profile[key] = float(profile.get(key, 0.0) or 0.0) + float(chunk_profile.get(key, 0.0) or 0.0)
            profile["sampled_session_count"] = sample_sessions
            by_name = {result.run_name: result for result in results}
            for result in sampled_results:
                by_name[result.run_name] = result
            results = list(by_name.values())
    else:
        combined_path_bands = new_path_band_accumulator() if write_bundle else None
        chunk_tasks = [
            base_task | {"session_indices": chunk}
            for chunk in _session_chunks(sessions, worker_count)
        ]
        if worker_count == 1:
            chunk_outputs = []
            for chunk_index, task in enumerate(chunk_tasks):
                chunk_output = _run_monte_carlo_chunk(task)
                chunk_outputs.append(chunk_output)
                if diagnostics_enabled:
                    accumulated = sum(len(output.get("results") or []) for output in chunk_outputs)
                    _record_chunk_output_diagnostic(chunk_output, chunk_index=chunk_index, accumulated_result_count=accumulated)
        else:
            with concurrent.futures.ProcessPoolExecutor(max_workers=worker_count) as executor:
                chunk_outputs = []
                for chunk_index, chunk_output in enumerate(executor.map(_run_monte_carlo_chunk, chunk_tasks)):
                    chunk_outputs.append(chunk_output)
                    if diagnostics_enabled:
                        accumulated = sum(len(output.get("results") or []) for output in chunk_outputs)
                        _record_chunk_output_diagnostic(chunk_output, chunk_index=chunk_index, accumulated_result_count=accumulated)
        results = [
            result
            for chunk_output in chunk_outputs
            for result in chunk_output.get("results", [])
        ]
        for chunk_output in chunk_outputs:
            chunk_profile = chunk_output.get("profile")
            if isinstance(chunk_profile, Mapping):
                _merge_mc_chunk_profile(profile, chunk_profile)
            chunk_accumulator = chunk_output.get("path_band_accumulator")
            if combined_path_bands is not None and isinstance(chunk_accumulator, dict):
                merge_path_band_accumulators(combined_path_bands, chunk_accumulator)
        if write_bundle:
            if combined_path_bands:
                precomputed_path_bands = finalize_path_band_accumulator(combined_path_bands)
                path_band_method = all_session_path_band_method(
                    session_count=sessions,
                    sessions_with_path_metrics=sessions,
                    options=output_options,
                )
    execution_seconds = time.perf_counter() - execution_started
    results.sort(key=lambda artefact: artefact.run_name)
    _record_mc_diagnostic(
        "execution_finished",
        result_count=len(results),
        sampled_result_count=_sampled_result_count(results),
    )
    sort_seconds = time.perf_counter() - execution_started - execution_seconds
    compact_seconds = 0.0
    dashboard_seconds = 0.0
    write_seconds = 0.0
    provenance_seconds = 0.0
    data_scope = _data_scope_context(
        round_number=round_number,
        days=days,
        source="synthetic",
        data_dir=data_dir if data_dir is not None else None,
    )
    runtime_context = _mc_runtime_context(
        workers=worker_count,
        sessions=sessions,
        sample_sessions=sample_sessions,
        monte_carlo_backend=resolved_backend,
        data_scope=data_scope,
    )
    if write_bundle:
        phase_rss: Dict[str, object] = {
            "before_reporting_rss_bytes": _current_process_rss_bytes(),
        }
        _record_mc_diagnostic(
            "reporting_started",
            before_reporting_rss_bytes=phase_rss["before_reporting_rss_bytes"],
            result_count=len(results),
            sampled_result_count=_sampled_result_count(results),
        )

        def build_compact_rows() -> Dict[str, Dict[str, List[Dict[str, object]]]]:
            return {
                result.run_name: compact_replay_rows(result, output_options)
                for result in results
                if result.inventory_series
            }

        _record_mc_diagnostic("sample_row_compaction_started")
        monte_carlo_rows_raw, compact_rss = _measure_phase_rss(build_compact_rows)
        assert isinstance(monte_carlo_rows_raw, dict)
        monte_carlo_rows = monte_carlo_rows_raw
        compact_seconds = float(compact_rss["elapsed_seconds"])
        phase_rss["sample_row_compaction"] = compact_rss
        _record_mc_diagnostic(
            "sample_row_compaction_finished",
            rss_peak_bytes=compact_rss.get("rss_peak_bytes"),
        )
        phase_timings = finalise_mc_profile(profile)
        phase_timings["result_sort_seconds"] = round(sort_seconds, 6)
        phase_timings["sample_row_compaction_seconds"] = round(compact_seconds, 6)
        phase_timings["dashboard_build_seconds"] = 0.0
        phase_timings["bundle_write_seconds"] = 0.0
        phase_timings["provenance_capture_seconds"] = 0.0
        phase_timings["session_execution_wall_seconds"] = round(execution_seconds, 6)
        if "rust_internal_wall_seconds" in profile:
            phase_timings["rust_internal_wall_seconds"] = round(float(profile["rust_internal_wall_seconds"]), 6)
        runtime_context["phase_timings_seconds"] = phase_timings
        runtime_context["phase_rss_bytes"] = phase_rss
        dashboard_provenance_started = time.perf_counter()
        dashboard_provenance = capture_provenance(runtime_context=runtime_context)
        provenance_seconds += time.perf_counter() - dashboard_provenance_started
        runtime_context["phase_timings_seconds"]["provenance_capture_seconds"] = round(provenance_seconds, 6)

        def build_dashboard() -> Dict[str, object]:
            dashboard = build_dashboard_payload(
                run_type="monte_carlo",
                run_name=run_name,
                trader_name=trader_spec.name,
                mode="monte_carlo",
                fill_model=fill_model.to_dict(),
                perturbations=perturbation.to_dict(),
                round_number=round_number,
                access_scenario=access_scenario.to_dict(),
                monte_carlo_results=results,
                monte_carlo_rows=monte_carlo_rows,
                monte_carlo_path_bands=precomputed_path_bands,
                monte_carlo_path_band_method=path_band_method,
                dataset_reports=[],
                output_options=output_options,
                runtime_context=runtime_context,
                provenance=dashboard_provenance,
            )
            if round3_context is not None:
                dashboard["optionDiagnostics"] = round3_context.option_diagnostics
            return dashboard

        _record_mc_diagnostic("dashboard_build_started")
        dashboard_raw, dashboard_rss = _measure_phase_rss(build_dashboard)
        assert isinstance(dashboard_raw, dict)
        dashboard = dashboard_raw
        dashboard_seconds = float(dashboard_rss["elapsed_seconds"])
        phase_rss["dashboard_build"] = dashboard_rss
        runtime_context["phase_timings_seconds"]["dashboard_build_seconds"] = round(dashboard_seconds, 6)
        _record_mc_diagnostic(
            "dashboard_build_finished",
            rss_peak_bytes=dashboard_rss.get("rss_peak_bytes"),
        )

        def write_bundle() -> None:
            write_mc_bundle(
                output_dir,
                results,
                dashboard,
                register=register,
                replay_rows_by_run=monte_carlo_rows,
                output_options=output_options,
                runtime_context=runtime_context,
            )

        _record_mc_diagnostic("bundle_write_started")
        _unused_write_result, write_rss = _measure_phase_rss(write_bundle)
        write_seconds = float(write_rss["elapsed_seconds"])
        phase_rss["bundle_write"] = write_rss
        runtime_context["phase_timings_seconds"]["bundle_write_seconds"] = round(write_seconds, 6)
        _record_mc_diagnostic(
            "bundle_write_finished",
            rss_peak_bytes=write_rss.get("rss_peak_bytes"),
        )
        manifest_path = output_dir / "manifest.json"
        if manifest_path.is_file():
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(manifest_payload, dict):
                manifest_provenance_started = time.perf_counter()
                manifest_provenance = capture_provenance(runtime_context=runtime_context, start=output_dir)
                provenance_seconds += time.perf_counter() - manifest_provenance_started
                runtime_context["phase_timings_seconds"]["provenance_capture_seconds"] = round(provenance_seconds, 6)

                def refresh_manifest() -> None:
                    write_manifest(
                        output_dir,
                        manifest_payload,
                        output_options,
                        runtime_context=runtime_context,
                        provenance=manifest_provenance,
                    )

                _record_mc_diagnostic("manifest_refresh_started")
                _unused_manifest_result, manifest_rss = _measure_phase_rss(refresh_manifest)
                phase_rss["manifest_refresh"] = manifest_rss
                _record_mc_diagnostic(
                    "manifest_refresh_finished",
                    rss_peak_bytes=manifest_rss.get("rss_peak_bytes"),
                )
        phase_rss["after_reporting_rss_bytes"] = _current_process_rss_bytes()
        _record_mc_diagnostic(
            "reporting_finished",
            after_reporting_rss_bytes=phase_rss["after_reporting_rss_bytes"],
        )
    final_profile = dict(runtime_context.get("phase_timings_seconds") or finalise_mc_profile(profile))
    final_profile["result_sort_seconds"] = round(sort_seconds, 6)
    final_profile["sample_row_compaction_seconds"] = round(compact_seconds, 6)
    final_profile["dashboard_build_seconds"] = round(dashboard_seconds, 6)
    final_profile["bundle_write_seconds"] = round(write_seconds, 6)
    final_profile["provenance_capture_seconds"] = round(provenance_seconds, 6)
    final_profile["session_execution_wall_seconds"] = round(execution_seconds, 6)
    if "rust_internal_wall_seconds" in profile:
        final_profile["rust_internal_wall_seconds"] = round(float(profile["rust_internal_wall_seconds"]), 6)
    return results, final_profile


def run_monte_carlo(
    *,
    trader_spec: TraderSpec,
    sessions: int,
    sample_sessions: int,
    days: Sequence[int],
    data_dir: Path | None = None,
    fill_model_name: str,
    perturbation: PerturbationConfig,
    output_dir: Path,
    base_seed: int,
    run_name: str,
    workers: int = 1,
    round_number: int = 1,
    access_scenario: AccessScenario | None = None,
    fill_model_config_path: Path | None = None,
    register: bool = True,
    write_bundle: bool = True,
    output_options: OutputOptions | None = None,
    print_trader_output: bool = False,
    monte_carlo_backend: str = "auto",
) -> List[SessionArtefacts]:
    results, _profile = _run_monte_carlo_profiled(
        trader_spec=trader_spec,
        sessions=sessions,
        sample_sessions=sample_sessions,
        days=days,
        data_dir=data_dir,
        fill_model_name=fill_model_name,
        perturbation=perturbation,
        output_dir=output_dir,
        base_seed=base_seed,
        run_name=run_name,
        workers=workers,
        round_number=round_number,
        access_scenario=access_scenario,
        fill_model_config_path=fill_model_config_path,
        register=register,
        write_bundle=write_bundle,
        output_options=output_options,
        print_trader_output=print_trader_output,
        monte_carlo_backend=monte_carlo_backend,
    )
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
    round_number: int = 1,
    access_scenario: AccessScenario | None = None,
    fill_model_config_path: Path | None = None,
    output_options: OutputOptions | None = None,
    print_trader_output: bool = False,
) -> List[Dict[str, object]]:
    output_options = output_options or OutputOptions()
    access_scenario = access_scenario or NO_ACCESS_SCENARIO
    round_spec = get_round_spec(round_number)
    _validate_access_usage(round_spec, access_scenario)
    fill_model = resolve_fill_model(fill_model_name, fill_model_config_path)
    runtime_context = {
        "engine_backend": "python",
        "parallelism": "single_process",
        "worker_count": 1,
        "data_scope": _data_scope_context(
            round_number=round_number,
            days=days,
            data_dir=data_dir,
            source="historical",
        ),
    }
    comparison_rows: List[Dict[str, object]] = []
    for trader_spec in trader_specs:
        run_dir = output_dir / trader_spec.name
        artefact = run_replay(
            trader_spec=trader_spec,
            days=days,
            data_dir=data_dir,
            fill_model_name=fill_model_name,
            perturbation=perturbation,
            fill_model_config_path=fill_model_config_path,
            output_dir=run_dir,
            run_name=f"{run_name}_{trader_spec.name}",
            round_number=round_number,
            access_scenario=access_scenario,
            register=False,
            write_bundle=output_options.write_child_bundles,
            output_options=output_options,
            print_trader_output=print_trader_output,
        )
        comparison_rows.append({
            "trader": trader_spec.name,
            "overrides": describe_overrides(trader_spec.overrides),
            "final_pnl": artefact.summary["final_pnl"],
            "gross_pnl_before_maf": artefact.summary.get("gross_pnl_before_maf"),
            "maf_cost": artefact.summary.get("maf_cost"),
            "access_scenario": access_scenario.name,
            "contract_won": access_scenario.contract_won,
            "extra_access_enabled": access_scenario.enabled,
            "expected_extra_quote_fraction": access_scenario.expected_extra_quote_fraction,
            "max_drawdown": artefact.summary.get("max_drawdown"),
            "fill_count": artefact.summary["fill_count"],
            "order_count": artefact.summary.get("order_count"),
            "limit_breaches": artefact.summary["limit_breaches"],
            "per_product_pnl": {
                product: metrics.get("final_mtm")
                for product, metrics in artefact.summary.get("per_product", {}).items()
            },
            "per_product_positions": dict(artefact.summary.get("final_positions", {})),
            "per_product_fill_count": {
                product: metrics.get("total_fills")
                for product, metrics in artefact.behaviour.get("per_product", {}).items()
            },
            "per_product_cap_usage": {
                product: metrics.get("cap_usage_ratio")
                for product, metrics in artefact.behaviour.get("per_product", {}).items()
            },
            "osmium_pnl": artefact.summary.get("per_product", {}).get("ASH_COATED_OSMIUM", {}).get("final_mtm"),
            "pepper_pnl": artefact.summary.get("per_product", {}).get("INTARIAN_PEPPER_ROOT", {}).get("final_mtm"),
            "osmium_realised": artefact.summary.get("per_product", {}).get("ASH_COATED_OSMIUM", {}).get("realised"),
            "pepper_realised": artefact.summary.get("per_product", {}).get("INTARIAN_PEPPER_ROOT", {}).get("realised"),
            "osmium_position": artefact.summary.get("per_product", {}).get("ASH_COATED_OSMIUM", {}).get("final_position"),
            "pepper_position": artefact.summary.get("per_product", {}).get("INTARIAN_PEPPER_ROOT", {}).get("final_position"),
            "osmium_cap_usage": artefact.behaviour.get("per_product", {}).get("ASH_COATED_OSMIUM", {}).get("cap_usage_ratio"),
            "pepper_cap_usage": artefact.behaviour.get("per_product", {}).get("INTARIAN_PEPPER_ROOT", {}).get("cap_usage_ratio"),
            "osmium_fill_count": artefact.behaviour.get("per_product", {}).get("ASH_COATED_OSMIUM", {}).get("total_fills"),
            "pepper_fill_count": artefact.behaviour.get("per_product", {}).get("INTARIAN_PEPPER_ROOT", {}).get("total_fills"),
            "osmium_max_drawdown": artefact.behaviour.get("per_product", {}).get("ASH_COATED_OSMIUM", {}).get("max_drawdown"),
            "pepper_max_drawdown": artefact.behaviour.get("per_product", {}).get("INTARIAN_PEPPER_ROOT", {}).get("max_drawdown"),
            "pepper_markout_5": artefact.behaviour.get("per_product", {}).get("INTARIAN_PEPPER_ROOT", {}).get("average_fill_markout_5"),
            "osmium_markout_5": artefact.behaviour.get("per_product", {}).get("ASH_COATED_OSMIUM", {}).get("average_fill_markout_5"),
        })
    comparison_rows.sort(key=lambda row: float(row["final_pnl"]), reverse=True)
    dashboard = build_dashboard_payload(
        run_type="comparison",
        run_name=run_name,
        trader_name="multiple",
        mode="replay",
        fill_model=fill_model.to_dict(),
        perturbations=perturbation.to_dict(),
        round_number=round_number,
        access_scenario=access_scenario.to_dict(),
        comparison_rows=comparison_rows,
        output_options=output_options,
        runtime_context=runtime_context,
    )
    write_run_bundle(output_dir, dashboard, extra_csvs={"comparison.csv": comparison_rows}, output_options=output_options)
    write_manifest(
        output_dir,
        {"run_type": "comparison", "run_name": run_name, "row_count": len(comparison_rows), "round": round_number, "access_scenario": access_scenario.to_dict()},
        output_options,
        runtime_context=runtime_context,
    )
    return comparison_rows


def run_sweep_from_config(config_path: Path, output_dir: Path, output_options: OutputOptions | None = None) -> List[Dict[str, object]]:
    config_path = config_path.resolve()
    config = _load_json_config(config_path)
    if "trader" not in config:
        raise ValueError(f"{config_path}: expected 'trader'")
    trader_path = _resolve_config_path(config_path, config["trader"])
    base_name = config.get("name", config_path.stem)
    round_number = int(config.get("round", 1))
    days = _config_days(config)
    fill_model_name = config.get("fill_model", "base")
    fill_model_config_path = _optional_config_path(config, config_path, "fill_config")
    perturbation = PerturbationConfig(**config.get("perturbation", {}))
    access_scenario = access_scenario_from_dict(config.get("access_scenario"))
    output_options = output_options or OutputOptions.from_config(config)
    trader_specs = [
        TraderSpec(
            name=str(variant.get("name") or f"variant_{idx}"),
            path=trader_path,
            overrides=variant.get("overrides"),
        )
        for idx, variant in enumerate(_config_variants(config, config_path))
    ]
    return run_compare(
        trader_specs=trader_specs,
        days=days,
        data_dir=_config_data_dir(config, config_path, round_number),
        fill_model_name=fill_model_name,
        perturbation=perturbation,
        fill_model_config_path=fill_model_config_path,
        output_dir=output_dir,
        run_name=base_name,
        round_number=round_number,
        access_scenario=access_scenario,
        output_options=output_options,
    )


def _trader_specs_from_config(config: Dict[str, object], config_path: Path) -> List[TraderSpec]:
    trader_items = config.get("traders")
    if isinstance(trader_items, list):
        if not trader_items:
            raise ValueError(f"{config_path}: 'traders' must not be empty")
        specs = []
        for item in trader_items:
            if not isinstance(item, Mapping):
                raise ValueError(f"{config_path}: every trader entry must be an object")
            if "path" not in item:
                raise ValueError(f"{config_path}: every trader entry must include 'path'")
            path = _resolve_config_path(config_path, item["path"])
            specs.append(TraderSpec(
                name=str(item.get("name") or path.stem),
                path=path,
                overrides=item.get("overrides") if isinstance(item, dict) else None,
            ))
        return specs

    if "trader" not in config:
        raise ValueError(f"{config_path}: expected 'trader' or 'traders'")
    trader_path = _resolve_config_path(config_path, config["trader"])
    variants = config.get("variants")
    if isinstance(variants, list):
        return [
            TraderSpec(
                name=str(variant.get("name") or f"variant_{idx}"),
                path=_resolve_config_path(config_path, variant.get("path", trader_path)),
                overrides=variant.get("overrides") if isinstance(variant, dict) else None,
            )
            for idx, variant in enumerate(_config_variants(config, config_path))
        ]

    return [TraderSpec(name=str(config.get("name", config_path.stem)), path=trader_path)]


def _scenario_winner_rows(rows: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    grouped: Dict[str, List[Dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row["scenario"]), []).append(row)

    baseline_name = None
    for scenario, scenario_rows in grouped.items():
        if any(not bool(row.get("extra_access_enabled")) for row in scenario_rows):
            baseline_name = scenario
            break
    baseline_winner = None
    if baseline_name:
        baseline_winner = max(grouped[baseline_name], key=lambda row: float(row.get("final_pnl") or 0.0)).get("trader")

    winner_rows = []
    for scenario, scenario_rows in sorted(grouped.items()):
        replay_winner = max(scenario_rows, key=lambda row: float(row.get("final_pnl") or 0.0))
        mc_candidates = [row for row in scenario_rows if row.get("mc_mean") is not None]
        mc_winner = max(mc_candidates, key=lambda row: float(row.get("mc_mean") or 0.0)) if mc_candidates else None
        second = sorted(scenario_rows, key=lambda row: float(row.get("final_pnl") or 0.0), reverse=True)[1:2]
        winner_rows.append({
            "scenario": scenario,
            "winner": replay_winner.get("trader"),
            "winner_final_pnl": replay_winner.get("final_pnl"),
            "gap_to_second": None if not second else float(replay_winner.get("final_pnl") or 0.0) - float(second[0].get("final_pnl") or 0.0),
            "mc_winner": None if mc_winner is None else mc_winner.get("trader"),
            "mc_winner_mean": None if mc_winner is None else mc_winner.get("mc_mean"),
            "ranking_changed_vs_no_access": None if baseline_winner is None else replay_winner.get("trader") != baseline_winner,
        })
    return winner_rows


def _pairwise_mc_rows(mc_results: Dict[tuple[str, str], List[SessionArtefacts]], replay_rows: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    replay_lookup = {(str(row["scenario"]), str(row["trader"])): row for row in replay_rows}
    rows: List[Dict[str, object]] = []
    scenarios = sorted({key[0] for key in mc_results})
    for scenario in scenarios:
        traders = sorted(trader for sc, trader in mc_results if sc == scenario)
        for idx, trader_a in enumerate(traders):
            for trader_b in traders[idx + 1:]:
                sessions_a = mc_results[(scenario, trader_a)]
                sessions_b = mc_results[(scenario, trader_b)]
                n = min(len(sessions_a), len(sessions_b))
                if n == 0:
                    continue
                diffs = [float(sessions_a[i].summary["final_pnl"]) - float(sessions_b[i].summary["final_pnl"]) for i in range(n)]
                mean_diff = statistics.fmean(diffs)
                std_diff = statistics.pstdev(diffs) if len(diffs) > 1 else 0.0
                replay_diff = float(replay_lookup[(scenario, trader_a)].get("final_pnl") or 0.0) - float(replay_lookup[(scenario, trader_b)].get("final_pnl") or 0.0)
                rows.append({
                    "scenario": scenario,
                    "trader_a": trader_a,
                    "trader_b": trader_b,
                    "sessions": n,
                    "replay_diff_a_minus_b": replay_diff,
                    "mc_mean_diff_a_minus_b": mean_diff,
                    "mc_std_diff": std_diff,
                    "mc_p05_diff": _quantile(diffs, 0.05),
                    "mc_p50_diff": _quantile(diffs, 0.50),
                    "mc_p95_diff": _quantile(diffs, 0.95),
                    "a_win_rate": sum(1 for value in diffs if value > 0) / n,
                    "likely_winner": trader_a if mean_diff > 0 else trader_b if mean_diff < 0 else "tie",
                })
    return rows


def run_round2_scenario_compare_from_config(config_path: Path, output_dir: Path, output_options: OutputOptions | None = None) -> Dict[str, List[Dict[str, object]]]:
    config_path = config_path.resolve()
    config = _load_json_config(config_path)
    run_name = str(config.get("name", config_path.stem))
    round_number = int(config.get("round", 2))
    data_dir = _config_data_dir(config, config_path, round_number)
    days = _config_days(config)
    fill_model_name = str(config.get("fill_model", "base"))
    fill_model_config_path = _optional_config_path(config, config_path, "fill_config")
    perturbation = PerturbationConfig(**config.get("perturbation", {}))
    scenarios = expand_scenarios(config.get("scenarios"), config.get("maf_values"))
    trader_specs = _trader_specs_from_config(config, config_path)
    if not scenarios:
        raise ValueError(f"{config_path}: no Round 2 scenarios configured")
    mc_sessions = int(config.get("mc_sessions", 0))
    mc_sample_sessions = int(config.get("mc_sample_sessions", min(4, mc_sessions)))
    mc_seed = int(config.get("mc_seed", 20260418))
    mc_workers = int(config.get("mc_workers", 1))
    mc_backend = str(config.get("mc_backend", "auto"))
    output_options = output_options or OutputOptions.from_config(config)
    aggregate_runtime_context = _mc_runtime_context(
        workers=mc_workers,
        sessions=mc_sessions,
        sample_sessions=mc_sample_sessions,
        monte_carlo_backend=mc_backend if mc_sessions > 0 else None,
        data_scope=_data_scope_context(
            round_number=round_number,
            days=days,
            data_dir=data_dir,
            source="historical",
        ),
    )

    scenario_rows: List[Dict[str, object]] = []
    mc_results: Dict[tuple[str, str], List[SessionArtefacts]] = {}
    baseline_gross_by_trader: Dict[str, float] = {}

    for scenario_idx, scenario in enumerate(scenarios):
        for trader_idx, trader_spec in enumerate(trader_specs):
            replay = run_replay(
                trader_spec=trader_spec,
                days=days,
                data_dir=data_dir,
                fill_model_name=fill_model_name,
                perturbation=perturbation,
                fill_model_config_path=fill_model_config_path,
                output_dir=output_dir / scenario.name / trader_spec.name / "replay",
                run_name=f"{run_name}_{scenario.name}_{trader_spec.name}_replay",
                round_number=round_number,
                access_scenario=scenario,
                register=False,
                write_bundle=output_options.write_child_bundles,
                output_options=output_options,
            )
            gross = float(replay.summary.get("gross_pnl_before_maf", replay.summary["final_pnl"]))
            if not scenario.enabled and trader_spec.name not in baseline_gross_by_trader:
                baseline_gross_by_trader[trader_spec.name] = gross
            baseline_gross = baseline_gross_by_trader.get(trader_spec.name)
            row = {
                "scenario": scenario.name,
                "trader": trader_spec.name,
                "overrides": describe_overrides(trader_spec.overrides),
                "round": round_number,
                "final_pnl": replay.summary["final_pnl"],
                "gross_pnl_before_maf": gross,
                "maf_cost": replay.summary.get("maf_cost"),
                "maf_bid": scenario.maf_bid,
                "contract_won": scenario.contract_won,
                "extra_access_enabled": scenario.enabled,
                "expected_extra_quote_fraction": scenario.expected_extra_quote_fraction,
                "marginal_access_pnl_before_maf": None if baseline_gross is None else gross - baseline_gross,
                "break_even_maf_vs_no_access": None if baseline_gross is None else gross - baseline_gross,
                "max_drawdown": replay.summary.get("max_drawdown"),
                "fill_count": replay.summary["fill_count"],
                "order_count": replay.summary.get("order_count"),
                "limit_breaches": replay.summary["limit_breaches"],
                "per_product_pnl": {
                    product: metrics.get("final_mtm")
                    for product, metrics in replay.summary.get("per_product", {}).items()
                },
                "per_product_fill_count": {
                    product: metrics.get("total_fills")
                    for product, metrics in replay.behaviour.get("per_product", {}).items()
                },
                "per_product_cap_usage": {
                    product: metrics.get("cap_usage_ratio")
                    for product, metrics in replay.behaviour.get("per_product", {}).items()
                },
                "osmium_pnl": replay.summary.get("per_product", {}).get("ASH_COATED_OSMIUM", {}).get("final_mtm"),
                "pepper_pnl": replay.summary.get("per_product", {}).get("INTARIAN_PEPPER_ROOT", {}).get("final_mtm"),
                "osmium_fill_count": replay.behaviour.get("per_product", {}).get("ASH_COATED_OSMIUM", {}).get("total_fills"),
                "pepper_fill_count": replay.behaviour.get("per_product", {}).get("INTARIAN_PEPPER_ROOT", {}).get("total_fills"),
                "osmium_cap_usage": replay.behaviour.get("per_product", {}).get("ASH_COATED_OSMIUM", {}).get("cap_usage_ratio"),
                "pepper_cap_usage": replay.behaviour.get("per_product", {}).get("INTARIAN_PEPPER_ROOT", {}).get("cap_usage_ratio"),
                "osmium_markout_5": replay.behaviour.get("per_product", {}).get("ASH_COATED_OSMIUM", {}).get("average_fill_markout_5"),
                "pepper_markout_5": replay.behaviour.get("per_product", {}).get("INTARIAN_PEPPER_ROOT", {}).get("average_fill_markout_5"),
            }

            if mc_sessions > 0:
                mc = run_monte_carlo(
                    trader_spec=trader_spec,
                    sessions=mc_sessions,
                    sample_sessions=mc_sample_sessions,
                    days=days,
                    data_dir=data_dir,
                    fill_model_name=fill_model_name,
                    perturbation=perturbation,
                    fill_model_config_path=fill_model_config_path,
                    output_dir=output_dir / scenario.name / trader_spec.name / "monte_carlo",
                    base_seed=mc_seed + scenario_idx * 10_000,
                    run_name=f"{run_name}_{scenario.name}_{trader_spec.name}_mc",
                    workers=mc_workers,
                    monte_carlo_backend=mc_backend,
                    round_number=round_number,
                    access_scenario=scenario,
                    register=False,
                    write_bundle=output_options.write_child_bundles,
                    output_options=output_options,
                )
                mc_summary = _mc_summary_for_rows(mc)
                row.update(mc_summary)
                mc_results[(scenario.name, trader_spec.name)] = mc

            scenario_rows.append(row)

    winner_rows = _scenario_winner_rows(scenario_rows)
    pairwise_rows = _pairwise_mc_rows(mc_results, scenario_rows) if mc_results else []
    maf_sensitivity_rows = [
        row for row in scenario_rows
        if row.get("maf_bid") is not None and (bool(row.get("extra_access_enabled")) or float(row.get("maf_bid") or 0.0) != 0.0)
    ]
    scenario_rows.sort(key=lambda row: (str(row["scenario"]), -float(row.get("final_pnl") or 0.0)))

    dashboard = build_dashboard_payload(
        run_type="round2_scenarios",
        run_name=run_name,
        trader_name="multiple" if len(trader_specs) > 1 else trader_specs[0].name,
        mode="replay" if mc_sessions <= 0 else "replay+monte_carlo",
        fill_model=resolve_fill_model(fill_model_name, fill_model_config_path).to_dict(),
        perturbations=perturbation.to_dict(),
        round_number=round_number,
        access_scenario={"name": "scenario_sweep", "scenario_count": len(scenarios)},
        round2={
            "scenarioRows": scenario_rows,
            "winnerRows": winner_rows,
            "pairwiseRows": pairwise_rows,
            "mafSensitivityRows": maf_sensitivity_rows,
            "assumptionRegistry": {
                "note": "Rows are local decision scenarios, not official website reconstruction.",
            },
        },
        comparison_rows=scenario_rows,
        output_options=output_options,
        runtime_context=aggregate_runtime_context,
    )
    write_run_bundle(
        output_dir,
        dashboard,
        extra_csvs={
            "round2_scenarios.csv": scenario_rows,
            "round2_winners.csv": winner_rows,
            "round2_pairwise_mc.csv": pairwise_rows,
            "round2_maf_sensitivity.csv": maf_sensitivity_rows,
        },
        output_options=output_options,
    )
    write_manifest(
        output_dir,
        {
            "run_type": "round2_scenarios",
            "run_name": run_name,
            "round": round_number,
            "scenario_count": len(scenarios),
            "trader_count": len(trader_specs),
            "mc_sessions": mc_sessions,
        },
        output_options,
        runtime_context=aggregate_runtime_context,
    )
    return {
        "scenario_rows": scenario_rows,
        "winner_rows": winner_rows,
        "pairwise_rows": pairwise_rows,
        "maf_sensitivity_rows": maf_sensitivity_rows,
    }


def _mc_summary_for_rows(results: Sequence[SessionArtefacts]) -> Dict[str, object]:
    finals = [float(session.summary["final_pnl"]) for session in results]
    if not finals:
        return {}
    p05 = _quantile(finals, 0.05)
    tail = [value for value in finals if value <= p05]
    return {
        "mc_sessions": len(finals),
        "mc_mean": statistics.fmean(finals),
        "mc_std": statistics.pstdev(finals) if len(finals) > 1 else 0.0,
        "mc_p05": p05,
        "mc_p50": _quantile(finals, 0.50),
        "mc_p95": _quantile(finals, 0.95),
        "mc_expected_shortfall_05": statistics.fmean(tail) if tail else p05,
        "mc_positive_rate": sum(1 for value in finals if value > 0) / len(finals),
        "mc_mean_drawdown": statistics.fmean(float(session.summary.get("max_drawdown", 0.0)) for session in results),
    }


def _robustness_rows(rows: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    by_trader: Dict[str, List[Dict[str, object]]] = {}
    for row in rows:
        by_trader.setdefault(str(row["trader"]), []).append(row)
    baseline_rows = {
        str(row["trader"]): row
        for row in rows
        if str(row.get("scenario")) == "baseline"
    }
    winners = {
        str(row.get("trader"))
        for row in _scenario_winner_rows(rows)
        if row.get("winner") is not None
    }
    output: List[Dict[str, object]] = []
    for trader, trader_rows in sorted(by_trader.items()):
        pnls = [float(row.get("final_pnl") or 0.0) for row in trader_rows]
        mc_means = [float(row.get("mc_mean")) for row in trader_rows if row.get("mc_mean") is not None]
        baseline = baseline_rows.get(trader, trader_rows[0])
        baseline_pnl = float(baseline.get("final_pnl") or 0.0)
        worst = min(pnls) if pnls else 0.0
        p10 = _quantile(pnls, 0.10) if pnls else 0.0
        stress_drop = baseline_pnl - worst
        output.append({
            "trader": trader,
            "scenario_count": len(trader_rows),
            "baseline_pnl": baseline_pnl,
            "mean_pnl": statistics.fmean(pnls) if pnls else 0.0,
            "median_pnl": statistics.median(pnls) if pnls else 0.0,
            "p10_pnl": p10,
            "worst_pnl": worst,
            "best_pnl": max(pnls) if pnls else 0.0,
            "stress_drop_from_baseline": stress_drop,
            "fragility_score": max(0.0, stress_drop) + max(0.0, baseline_pnl - float(p10 or baseline_pnl)),
            "scenario_win_count": sum(1 for row in _scenario_winner_rows(rows) if row.get("winner") == trader),
            "wins_any_scenario": trader in winners,
            "mean_mc_pnl": statistics.fmean(mc_means) if mc_means else None,
        })
    output.sort(key=lambda row: (float(row["fragility_score"]), -float(row["median_pnl"])))
    for idx, row in enumerate(output, start=1):
        row["robust_rank"] = idx
    return output


def run_scenario_compare_from_config(config_path: Path, output_dir: Path, output_options: OutputOptions | None = None) -> Dict[str, List[Dict[str, object]]]:
    config_path = config_path.resolve()
    config = _load_json_config(config_path)
    run_name = str(config.get("name", config_path.stem))
    round_number = int(config.get("round", 1))
    data_dir = _config_data_dir(config, config_path, round_number)
    days = _config_days(config)
    fill_model_config_path = _optional_config_path(config, config_path, "fill_config")
    default_fill_model = str(config.get("fill_model", "empirical_baseline"))
    scenarios = scenarios_from_config(config.get("scenarios"))
    trader_specs = _trader_specs_from_config(config, config_path)
    if not scenarios:
        raise ValueError(f"{config_path}: no research scenarios configured")
    mc_sessions = int(config.get("mc_sessions", 0))
    mc_sample_sessions = int(config.get("mc_sample_sessions", min(4, mc_sessions)))
    mc_seed = int(config.get("mc_seed", 20260418))
    mc_workers = int(config.get("mc_workers", 1))
    mc_backend = str(config.get("mc_backend", "auto"))
    output_options = output_options or OutputOptions.from_config(config)
    aggregate_runtime_context = _mc_runtime_context(
        workers=mc_workers,
        sessions=mc_sessions,
        sample_sessions=mc_sample_sessions,
        monte_carlo_backend=mc_backend if mc_sessions > 0 else None,
        data_scope=_data_scope_context(
            round_number=round_number,
            days=days,
            data_dir=data_dir,
            source="historical",
        ),
    )

    scenario_rows: List[Dict[str, object]] = []
    mc_results: Dict[tuple[str, str], List[SessionArtefacts]] = {}
    for scenario_idx, scenario in enumerate(scenarios):
        fill_model_name = scenario.fill_model or default_fill_model
        for trader_spec in trader_specs:
            replay = run_replay(
                trader_spec=trader_spec,
                days=days,
                data_dir=data_dir,
                fill_model_name=fill_model_name,
                fill_model_config_path=fill_model_config_path,
                perturbation=scenario.perturbation,
                output_dir=output_dir / scenario.name / trader_spec.name / "replay",
                run_name=f"{run_name}_{scenario.name}_{trader_spec.name}_replay",
                round_number=round_number,
                register=False,
                write_bundle=output_options.write_child_bundles,
                output_options=output_options,
            )
            row = {
                "scenario": scenario.name,
                "scenario_description": scenario.description,
                "scenario_tags": ",".join(scenario.tags),
                "trader": trader_spec.name,
                "overrides": describe_overrides(trader_spec.overrides),
                "round": round_number,
                "fill_model": fill_model_name,
                "final_pnl": replay.summary["final_pnl"],
                "gross_pnl_before_maf": replay.summary.get("gross_pnl_before_maf"),
                "max_drawdown": replay.summary.get("max_drawdown"),
                "fill_count": replay.summary["fill_count"],
                "order_count": replay.summary.get("order_count"),
                "limit_breaches": replay.summary["limit_breaches"],
                "slippage_cost": replay.summary.get("slippage", {}).get("total_slippage_cost"),
                "average_slippage_ticks": replay.summary.get("slippage", {}).get("average_slippage_ticks"),
                "per_product_pnl": {
                    product: metrics.get("final_mtm")
                    for product, metrics in replay.summary.get("per_product", {}).items()
                },
                "per_product_slippage_cost": {
                    product: metrics.get("slippage_cost")
                    for product, metrics in replay.summary.get("per_product", {}).items()
                },
                "per_product_fill_count": {
                    product: metrics.get("total_fills")
                    for product, metrics in replay.behaviour.get("per_product", {}).items()
                },
                "per_product_cap_usage": {
                    product: metrics.get("cap_usage_ratio")
                    for product, metrics in replay.behaviour.get("per_product", {}).items()
                },
                "osmium_pnl": replay.summary.get("per_product", {}).get("ASH_COATED_OSMIUM", {}).get("final_mtm"),
                "pepper_pnl": replay.summary.get("per_product", {}).get("INTARIAN_PEPPER_ROOT", {}).get("final_mtm"),
                "osmium_slippage_cost": replay.summary.get("per_product", {}).get("ASH_COATED_OSMIUM", {}).get("slippage_cost"),
                "pepper_slippage_cost": replay.summary.get("per_product", {}).get("INTARIAN_PEPPER_ROOT", {}).get("slippage_cost"),
                "osmium_fill_count": replay.behaviour.get("per_product", {}).get("ASH_COATED_OSMIUM", {}).get("total_fills"),
                "pepper_fill_count": replay.behaviour.get("per_product", {}).get("INTARIAN_PEPPER_ROOT", {}).get("total_fills"),
                "osmium_cap_usage": replay.behaviour.get("per_product", {}).get("ASH_COATED_OSMIUM", {}).get("cap_usage_ratio"),
                "pepper_cap_usage": replay.behaviour.get("per_product", {}).get("INTARIAN_PEPPER_ROOT", {}).get("cap_usage_ratio"),
                "latent_noise": scenario.perturbation.latent_price_noise_by_product,
                "spread_shift_ticks": scenario.perturbation.spread_shift_ticks,
                "order_book_volume_scale": scenario.perturbation.order_book_volume_scale,
                "slippage_multiplier": scenario.perturbation.slippage_multiplier,
                "shock_tick": scenario.perturbation.shock_tick,
                "shock_by_product": scenario.perturbation.shock_by_product,
            }
            if mc_sessions > 0:
                mc = run_monte_carlo(
                    trader_spec=trader_spec,
                    sessions=mc_sessions,
                    sample_sessions=mc_sample_sessions,
                    days=days,
                    data_dir=data_dir,
                    fill_model_name=fill_model_name,
                    fill_model_config_path=fill_model_config_path,
                    perturbation=scenario.perturbation,
                    output_dir=output_dir / scenario.name / trader_spec.name / "monte_carlo",
                    base_seed=mc_seed + scenario_idx * 10_000,
                    run_name=f"{run_name}_{scenario.name}_{trader_spec.name}_mc",
                    workers=mc_workers,
                    monte_carlo_backend=mc_backend,
                    round_number=round_number,
                    register=False,
                    write_bundle=output_options.write_child_bundles,
                    output_options=output_options,
                )
                row.update(_mc_summary_for_rows(mc))
                mc_results[(scenario.name, trader_spec.name)] = mc
            scenario_rows.append(row)

    scenario_rows.sort(key=lambda row: (str(row["scenario"]), -float(row.get("final_pnl") or 0.0)))
    winner_rows = _scenario_winner_rows(scenario_rows)
    robustness_rows = _robustness_rows(scenario_rows)
    pairwise_rows = _pairwise_mc_rows(mc_results, scenario_rows) if mc_results else []
    dashboard = build_dashboard_payload(
        run_type="scenario_compare",
        run_name=run_name,
        trader_name="multiple" if len(trader_specs) > 1 else trader_specs[0].name,
        mode="replay" if mc_sessions <= 0 else "replay+monte_carlo",
        fill_model=resolve_fill_model(default_fill_model, fill_model_config_path).to_dict(),
        perturbations={"scenario_count": len(scenarios)},
        round_number=round_number,
        comparison_rows=scenario_rows,
        scenario_analysis={
            "scenarios": scenario_manifest(scenarios),
            "rows": scenario_rows,
            "winners": winner_rows,
            "robustness": robustness_rows,
            "pairwiseMc": pairwise_rows,
            "assumptions": {
                "empirical": "Fill, noise and slippage scenarios are calibrated decision assumptions.",
                "unknown": "Website queue priority, hidden matching and other teams' behaviour are not reconstructed.",
            },
        },
        output_options=output_options,
        runtime_context=aggregate_runtime_context,
    )
    write_run_bundle(
        output_dir,
        dashboard,
        extra_csvs={
            "scenario_results.csv": scenario_rows,
            "scenario_winners.csv": winner_rows,
            "robustness_ranking.csv": robustness_rows,
            "scenario_pairwise_mc.csv": pairwise_rows,
        },
        output_options=output_options,
    )
    write_manifest(
        output_dir,
        {
            "run_type": "scenario_compare",
            "run_name": run_name,
            "round": round_number,
            "scenario_count": len(scenarios),
            "trader_count": len(trader_specs),
            "mc_sessions": mc_sessions,
            "scenarios": scenario_manifest(scenarios),
            "fill_config": str(fill_model_config_path) if fill_model_config_path else None,
        },
        output_options,
        runtime_context=aggregate_runtime_context,
    )
    return {
        "scenario_rows": scenario_rows,
        "winner_rows": winner_rows,
        "robustness_rows": robustness_rows,
        "pairwise_rows": pairwise_rows,
    }


def calibrate_against_live_export(
    *,
    trader_spec: TraderSpec,
    days: Sequence[int],
    data_dir: Path,
    live_export_path: Path,
    output_dir: Path,
    quick: bool = False,
    round_number: int = 1,
    access_scenario: AccessScenario | None = None,
    output_options: OutputOptions | None = None,
) -> Dict[str, object]:
    output_options = output_options or OutputOptions()
    access_scenario = access_scenario or NO_ACCESS_SCENARIO
    runtime_context = {
        "engine_backend": "python",
        "parallelism": "single_process",
        "worker_count": 1,
        "data_scope": _data_scope_context(
            round_number=round_number,
            days=days,
            data_dir=data_dir,
            source="historical",
        ),
    }
    empirical_profile = derive_empirical_fill_profile([live_export_path], output_dir / "empirical_profile", profile_name="live_empirical")
    if quick:
        candidate_fill_models = ["empirical_baseline", "empirical_conservative", "base"]
        candidate_scales = [0.70, 1.00]
        candidate_adverse = [0, 1]
        candidate_latency = [0]
        candidate_missed = [0.0, 0.05]
    else:
        candidate_fill_models = ["empirical_optimistic", "empirical_baseline", "empirical_conservative", "base", "conservative"]
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
                            round_number=round_number,
                            access_scenario=access_scenario,
                            register=False,
                            write_bundle=output_options.write_child_bundles,
                            output_options=output_options,
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
        round_number=round_number,
        access_scenario=access_scenario.to_dict(),
        calibration_grid=rows,
        calibration_best=best_row,
        output_options=output_options,
        runtime_context=runtime_context,
    )
    write_run_bundle(output_dir, dashboard, extra_csvs={"calibration_grid.csv": rows}, output_options=output_options)
    write_manifest(
        output_dir,
        {
            "run_type": "calibration",
            "grid_size": len(rows),
            "best": best_row,
            "quick": quick,
            "empirical_profile": empirical_profile,
            "validation_note": "Best score is a local calibration choice, not proof of exact website reconstruction.",
        },
        output_options,
        runtime_context=runtime_context,
    )
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


def run_optimize_from_config(config_path: Path, output_dir: Path, output_options: OutputOptions | None = None) -> List[Dict[str, object]]:
    config_path = config_path.resolve()
    config = _load_json_config(config_path)
    if "trader" not in config:
        raise ValueError(f"{config_path}: expected 'trader'")
    trader_path = _resolve_config_path(config_path, config["trader"])
    run_name = config.get("name", config_path.stem)
    round_number = int(config.get("round", 1))
    data_dir = _config_data_dir(config, config_path, round_number)
    days = _config_days(config)
    fill_model_name = config.get("fill_model", "base")
    fill_model_config_path = _optional_config_path(config, config_path, "fill_config")
    perturbation = PerturbationConfig(**config.get("perturbation", {}))
    access_scenario = access_scenario_from_dict(config.get("access_scenario"))
    mc_sessions = int(config.get("mc_sessions", 24))
    mc_sample_sessions = int(config.get("mc_sample_sessions", min(6, mc_sessions)))
    mc_seed = int(config.get("mc_seed", 20260418))
    mc_workers = int(config.get("mc_workers", 1))
    mc_backend = str(config.get("mc_backend", "auto"))
    output_options = output_options or OutputOptions.from_config(config)
    aggregate_runtime_context = _mc_runtime_context(
        workers=mc_workers,
        sessions=mc_sessions,
        sample_sessions=mc_sample_sessions,
        monte_carlo_backend=mc_backend if mc_sessions > 0 else None,
        data_scope=_data_scope_context(
            round_number=round_number,
            days=days,
            data_dir=data_dir,
            source="historical",
        ),
    )
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
    for idx, variant in enumerate(_config_variants(config, config_path)):
        variant_name = str(variant.get("name") or f"variant_{idx}")
        spec = TraderSpec(name=variant_name, path=trader_path, overrides=variant.get("overrides"))
        variant_dir = output_dir / variant_name
        replay = run_replay(
            trader_spec=spec,
            days=days,
            data_dir=data_dir,
            fill_model_name=fill_model_name,
            perturbation=perturbation,
            fill_model_config_path=fill_model_config_path,
            output_dir=variant_dir / "replay",
            run_name=f"{run_name}_{variant_name}_replay",
            round_number=round_number,
            access_scenario=access_scenario,
            register=False,
            write_bundle=output_options.write_child_bundles,
            output_options=output_options,
        )
        mc = run_monte_carlo(
            trader_spec=spec,
            sessions=mc_sessions,
            sample_sessions=mc_sample_sessions,
            days=days,
            data_dir=data_dir,
            fill_model_name=fill_model_name,
            perturbation=perturbation,
            fill_model_config_path=fill_model_config_path,
            output_dir=variant_dir / "monte_carlo",
            base_seed=mc_seed + idx * 1000,
            run_name=f"{run_name}_{variant_name}_mc",
            workers=mc_workers,
            monte_carlo_backend=mc_backend,
            round_number=round_number,
            access_scenario=access_scenario,
            register=False,
            write_bundle=output_options.write_child_bundles,
            output_options=output_options,
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
            "variant": variant_name,
            "overrides": describe_overrides(spec.overrides),
            "replay_final_pnl": replay.summary["final_pnl"],
            "replay_gross_pnl_before_maf": replay.summary.get("gross_pnl_before_maf"),
            "maf_cost": replay.summary.get("maf_cost"),
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
        fill_model=resolve_fill_model(fill_model_name, fill_model_config_path).to_dict(),
        perturbations=perturbation.to_dict(),
        round_number=round_number,
        access_scenario=access_scenario.to_dict(),
        optimization_rows=rows,
        output_options=output_options,
        runtime_context=aggregate_runtime_context,
    )
    write_run_bundle(output_dir, dashboard, extra_csvs={"optimization.csv": rows}, output_options=output_options)
    write_manifest(
        output_dir,
        {"run_type": "optimization", "run_name": run_name, "row_count": len(rows), "best_variant": rows[0] if rows else None},
        output_options,
        runtime_context=aggregate_runtime_context,
    )
    return rows
