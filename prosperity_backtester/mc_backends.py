from __future__ import annotations

import contextlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Sequence

from .datamodel import Listing, Observation, Trade, TradingState
from .dataset import BookSnapshot, DayDataset, TradePrint
from .fill_models import FillModel, ProductFillConfig
from .metadata import CURRENCY, PRODUCTS, TIMESTAMP_STEP, RoundSpec, get_round_spec
from .platform import (
    OrderSchedule,
    PerturbationConfig,
    ProductLedger,
    SessionArtefacts,
    _NullWriter,
    _StreamingPathMetricCollector,
    _execute_order_batch,
    _finalize_slippage_accumulator,
    _new_slippage_accumulator,
    _position_limit_for,
    _record_slippage_fill,
    _scaled_snapshot,
    snapshot_to_order_depth,
)
from .round2 import AccessScenario, NO_ACCESS_SCENARIO
from .simulate import (
    TICKS_PER_DAY,
    build_samplers,
    load_calibration,
    make_book,
    sample_trade_counts,
    sample_trade_quantity,
    simulate_latent_fair,
)

MONTE_CARLO_BACKENDS = ("classic", "streaming", "rust")
DEFAULT_MONTE_CARLO_BACKEND = "streaming"
AUTO_MONTE_CARLO_BACKEND = "auto"
RUST_MONTE_CARLO_BACKEND = "rust"

_PROFILE_KEYS = (
    "market_generation_seconds",
    "state_build_seconds",
    "trader_seconds",
    "execution_seconds",
    "path_metrics_seconds",
    "postprocess_seconds",
    "session_total_seconds",
)


@dataclass(frozen=True)
class StreamingSimulationContext:
    calibration: Dict[str, Dict[str, object]]
    samplers: Dict[str, object]
    tick_count: int


@dataclass(frozen=True)
class RustBackendRun:
    sessions: list[SessionArtefacts]
    path_bands: Dict[str, Dict[str, list[Dict[str, object]]]]
    profile: Dict[str, object]


_RUST_BINARY_CACHE: tuple[Path, Path] | None = None


def normalise_monte_carlo_backend(value: str | None) -> str:
    text = str(value or AUTO_MONTE_CARLO_BACKEND).strip().lower().replace("-", "_")
    if text in {"", AUTO_MONTE_CARLO_BACKEND}:
        return DEFAULT_MONTE_CARLO_BACKEND
    if text in MONTE_CARLO_BACKENDS:
        return text
    valid = ", ".join((AUTO_MONTE_CARLO_BACKEND, *MONTE_CARLO_BACKENDS))
    raise ValueError(f"unknown Monte Carlo backend {value!r}. Choose one of: {valid}")


def new_profile(backend: str) -> Dict[str, object]:
    return {
        "monte_carlo_backend": backend,
        "session_count": 0,
        "sampled_session_count": 0,
        "classic_session_count": 0,
        "streaming_session_count": 0,
        "rust_session_count": 0,
        **{key: 0.0 for key in _PROFILE_KEYS},
    }


def merge_profile(profile: Dict[str, object], update: Mapping[str, object], *, sampled: bool, execution_backend: str) -> None:
    profile["session_count"] = int(profile.get("session_count", 0)) + int(update.get("session_count", 1) or 1)
    if sampled:
        profile["sampled_session_count"] = int(profile.get("sampled_session_count", 0)) + 1
    profile[f"{execution_backend}_session_count"] = int(profile.get(f"{execution_backend}_session_count", 0)) + 1
    for key in _PROFILE_KEYS:
        profile[key] = float(profile.get(key, 0.0) or 0.0) + float(update.get(key, 0.0) or 0.0)


def finalise_profile(profile: Mapping[str, object]) -> Dict[str, object]:
    rounded = {key: round(float(profile.get(key, 0.0) or 0.0), 6) for key in _PROFILE_KEYS}
    known = sum(rounded[key] for key in _PROFILE_KEYS if key != "session_total_seconds")
    total = rounded["session_total_seconds"]
    rounded["python_overhead_seconds"] = round(max(0.0, total - known), 6)
    return {
        "monte_carlo_backend": profile.get("monte_carlo_backend"),
        "session_count": int(profile.get("session_count", 0) or 0),
        "sampled_session_count": int(profile.get("sampled_session_count", 0) or 0),
        "classic_session_count": int(profile.get("classic_session_count", 0) or 0),
        "streaming_session_count": int(profile.get("streaming_session_count", 0) or 0),
        "rust_session_count": int(profile.get("rust_session_count", 0) or 0),
        **rounded,
    }


def prepare_streaming_simulation_context(perturb: PerturbationConfig) -> StreamingSimulationContext:
    calibration = deepcopy(load_calibration())
    if "INTARIAN_PEPPER_ROOT" in calibration:
        drift = float(calibration["INTARIAN_PEPPER_ROOT"]["drift_per_tick"])
        calibration["INTARIAN_PEPPER_ROOT"]["drift_per_tick"] = drift * float(perturb.pepper_slope_scale)
    for product in PRODUCTS:
        latent_noise = perturb.latent_noise_for(product)
        if latent_noise > 0:
            calibration[product]["simulation_noise_std"] = latent_noise
    tick_count = TICKS_PER_DAY if perturb.synthetic_tick_limit in (None, 0) else max(1, int(perturb.synthetic_tick_limit))
    return StreamingSimulationContext(
        calibration=calibration,
        samplers=build_samplers(calibration),
        tick_count=tick_count,
    )


def rust_backend_supported(
    *,
    access_scenario: AccessScenario | None = None,
    print_trader_output: bool = False,
) -> bool:
    access_scenario = access_scenario or NO_ACCESS_SCENARIO
    return not access_scenario.enabled and not print_trader_output


def resolve_monte_carlo_backend(
    requested_backend: str | None,
    *,
    access_scenario: AccessScenario | None = None,
    print_trader_output: bool = False,
) -> str:
    """Resolve the backend to use for Monte Carlo simulation.

    The ``auto`` sentinel (default when nothing is requested) always resolves
    to the ``streaming`` backend. The ``rust`` backend must be requested
    explicitly via ``--mc-backend rust``; it is NOT auto-selected because the
    tracked 2026-04-22 benchmark pass kept ``streaming`` or ``classic`` ahead
    on realistic cases, while the Rust path still pays build and per-tick IPC
    cost.
    """
    text = str(requested_backend or AUTO_MONTE_CARLO_BACKEND).strip().lower().replace("-", "_")
    if text not in {"", AUTO_MONTE_CARLO_BACKEND}:
        backend = normalise_monte_carlo_backend(text)
        if backend == RUST_MONTE_CARLO_BACKEND:
            if not rust_backend_supported(access_scenario=access_scenario, print_trader_output=print_trader_output):
                raise ValueError(
                    "The rust Monte Carlo backend is not supported for this configuration "
                    "(access scenarios and print_trader_output are incompatible with it)."
                )
        return backend
    return DEFAULT_MONTE_CARLO_BACKEND


def ensure_rust_backend_binary() -> tuple[Path, Path] | None:
    global _RUST_BINARY_CACHE
    if _RUST_BINARY_CACHE is not None:
        binary_path, rust_bin_dir = _RUST_BINARY_CACHE
        if binary_path.is_file():
            return _RUST_BINARY_CACHE
        _RUST_BINARY_CACHE = None

    cargo_exe = _find_cargo_executable()
    if cargo_exe is None:
        return None
    rust_bin_dir = cargo_exe.parent
    project_root = Path(__file__).resolve().parent.parent
    manifest_path = project_root / "rust_mc_engine" / "Cargo.toml"
    binary_name = "prosperity-rust-mc.exe" if os.name == "nt" else "prosperity-rust-mc"
    binary_path = project_root / "rust_mc_engine" / "target" / "release" / binary_name
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(rust_bin_dir), env.get("PATH", "")])
    try:
        print("[prosperity-backtester] Building Rust MC engine (one-time, ~30-90s)...", flush=True)
        subprocess.run(
            [str(cargo_exe), "build", "--release", "--manifest-path", str(manifest_path)],
            cwd=project_root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        print("[prosperity-backtester] Rust MC engine built.", flush=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    if not binary_path.is_file():
        return None
    _RUST_BINARY_CACHE = (binary_path, rust_bin_dir)
    return _RUST_BINARY_CACHE


def _find_cargo_executable() -> Path | None:
    direct = shutil.which("cargo")
    if direct:
        return Path(direct).resolve()
    user_home = Path.home()
    candidates = [
        user_home / ".cargo" / "bin" / ("cargo.exe" if os.name == "nt" else "cargo"),
    ]
    if os.name == "nt":
        for rust_dir in Path("C:/Program Files").glob("Rust*"):
            candidates.append(rust_dir / "bin" / "cargo.exe")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _serialise_histogram(values: Mapping[object, object]) -> Dict[str, object]:
    ordered = sorted(
        ((int(key) if not isinstance(key, float) or float(key).is_integer() else float(key), int(weight)) for key, weight in values.items()),
        key=lambda item: item[0],
    )
    return {
        "values": [int(value) for value, _weight in ordered],
        "weights": [int(weight) for _value, weight in ordered],
    }


def _product_fill_payload(config: ProductFillConfig) -> Dict[str, object]:
    return {
        "passive_fill_rate": float(config.passive_fill_rate),
        "same_price_queue_share": float(config.same_price_queue_share),
        "queue_pressure": float(config.queue_pressure),
        "missed_fill_probability": float(config.missed_fill_probability),
        "passive_adverse_selection_ticks": float(config.passive_adverse_selection_ticks),
        "aggressive_slippage_ticks": float(config.aggressive_slippage_ticks),
        "aggressive_adverse_selection_ticks": float(config.aggressive_adverse_selection_ticks),
        "size_slippage_threshold": int(config.size_slippage_threshold),
        "size_slippage_rate": float(config.size_slippage_rate),
        "size_slippage_power": float(config.size_slippage_power),
        "max_size_slippage_ticks": float(config.max_size_slippage_ticks),
        "wide_spread_threshold": int(config.wide_spread_threshold) if config.wide_spread_threshold is not None else None,
        "thin_depth_threshold": int(config.thin_depth_threshold),
    }


def _serialise_fill_model(fill_model: FillModel) -> Dict[str, object]:
    products_payload: Dict[str, object] = {}
    for product in PRODUCTS:
        base_config = fill_model.product_overrides.get(product, fill_model.base_product_config())
        products_payload[product] = {
            "normal": _product_fill_payload(base_config.with_regime("normal")),
            "thin_depth": _product_fill_payload(base_config.with_regime("thin_depth")),
            "wide_spread": _product_fill_payload(base_config.with_regime("wide_spread")),
            "one_sided": _product_fill_payload(base_config.with_regime("one_sided")),
        }
    return {
        "fill_rate_multiplier": float(fill_model.fill_rate_multiplier),
        "missed_fill_additive": float(fill_model.missed_fill_additive),
        "slippage_multiplier": float(fill_model.slippage_multiplier),
        "products": products_payload,
    }


def _serialise_simulation_context(context: StreamingSimulationContext) -> Dict[str, object]:
    products_payload: Dict[str, object] = {}
    for product in PRODUCTS:
        calibration = context.calibration[product]
        products_payload[product] = {
            "start_candidates": [float(value) for value in calibration.get("start_candidates", [])],
            "drift_per_tick": float(calibration.get("drift_per_tick", 0.0)),
            "simulation_noise_std": float(calibration.get("simulation_noise_std", 0.0)),
            "trade_active_prob": float(calibration.get("trade_active_prob", 0.0)),
            "second_trade_prob": float(calibration.get("second_trade_prob", 0.0)),
            "trade_buy_prob": float(calibration.get("trade_buy_prob", 0.0)),
            "bot3_bid_rate": float(calibration.get("bot3_bid_rate", 0.0)),
            "bot3_ask_rate": float(calibration.get("bot3_ask_rate", 0.0)),
            "outer_spread": _serialise_histogram(calibration["outer_spread_counts"]),
            "inner_spread": _serialise_histogram(calibration["inner_spread_counts"]),
            "outer_bid_vol": _serialise_histogram(calibration["outer_bid_vol_counts"]),
            "inner_bid_vol": _serialise_histogram(calibration["inner_bid_vol_counts"]),
            "trade_qty": _serialise_histogram(calibration["trade_qty_counts"]),
        }
    return {"products": products_payload}


def _serialise_perturbation(perturb: PerturbationConfig) -> Dict[str, object]:
    return {
        "passive_fill_scale": float(perturb.passive_fill_scale),
        "missed_fill_additive": float(perturb.missed_fill_additive),
        "spread_shift_ticks": int(perturb.spread_shift_ticks),
        "order_book_volume_scale": float(perturb.order_book_volume_scale),
        "price_noise_std": float(perturb.price_noise_std),
        "latency_ticks": max(0, int(perturb.latency_ticks)),
        "adverse_selection_ticks": float(perturb.adverse_selection_ticks),
        "slippage_multiplier": float(perturb.slippage_multiplier),
        "reentry_probability": float(perturb.reentry_probability),
        "trade_matching_mode": str(perturb.trade_matching_mode),
        "position_limits": {
            product: max(1, int(_position_limit_for(product, perturb)))
            for product in PRODUCTS
        },
        "shock_tick": None if perturb.shock_tick is None else max(0, int(perturb.shock_tick)),
        "shock_by_product": {
            product: float(perturb.shock_for(product))
            for product in PRODUCTS
            if float(perturb.shock_for(product)) != 0.0
        },
    }


def run_rust_backend(
    *,
    trader_name: str,
    trader_path: Path,
    trader_overrides: Dict[str, object] | None,
    fill_model: FillModel,
    perturb: PerturbationConfig,
    days: Sequence[int],
    session_indices: Sequence[int],
    run_name: str,
    path_bucket_count: int,
    workers: int,
    access_scenario: AccessScenario | None = None,
    print_trader_output: bool = False,
    base_seed: int,
) -> RustBackendRun:
    access_scenario = access_scenario or NO_ACCESS_SCENARIO
    if not rust_backend_supported(access_scenario=access_scenario, print_trader_output=print_trader_output):
        raise RuntimeError("Rust Monte Carlo backend is not supported for this configuration")
    binary = ensure_rust_backend_binary()
    if binary is None:
        raise RuntimeError("Rust Monte Carlo backend is unavailable on this machine")
    binary_path, rust_bin_dir = binary
    context = prepare_streaming_simulation_context(perturb)
    worker_script = Path(__file__).resolve().with_name("rust_strategy_worker.py")
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(binary_path.parent), str(rust_bin_dir), env.get("PATH", "")])
    with tempfile.TemporaryDirectory(prefix="prosperity_rust_mc_") as temp_dir_text:
        temp_dir = Path(temp_dir_text)
        overrides_path: Path | None = None
        if trader_overrides:
            overrides_path = temp_dir / "trader_overrides.json"
            overrides_path.write_text(json.dumps(trader_overrides, sort_keys=True), encoding="utf-8")
        config_path = temp_dir / "config.json"
        output_path = temp_dir / "output.json"
        payload = {
            "run_name": run_name,
            "trader_path": str(Path(trader_path).resolve()),
            "trader_overrides_path": None if overrides_path is None else str(overrides_path.resolve()),
            "python_bin": sys.executable,
            "worker_script": str(worker_script.resolve()),
            "base_seed": int(base_seed),
            "days": [int(day) for day in days],
            "session_indices": [int(index) for index in session_indices],
            "worker_count": max(1, int(workers)),
            "tick_count": int(context.tick_count),
            "path_bucket_count": max(0, int(path_bucket_count)),
            "print_trader_output": bool(print_trader_output),
            "fill_model": _serialise_fill_model(fill_model),
            "perturbation": _serialise_perturbation(perturb),
            "simulation": _serialise_simulation_context(context),
        }
        config_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        subprocess.run(
            [str(binary_path), str(config_path), str(output_path)],
            cwd=Path(__file__).resolve().parent.parent,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        run_payload = json.loads(output_path.read_text(encoding="utf-8"))
    profile = dict(run_payload.get("profile") or {})
    sessions: list[SessionArtefacts] = []
    for row in run_payload.get("sessions", []):
        summary = dict(row["summary"])
        access_payload = summary.get("access_scenario")
        if not isinstance(access_payload, dict) or not access_payload:
            access_payload = access_scenario.to_dict()
        sessions.append(
            SessionArtefacts(
                run_name=str(row["run_name"]),
                trader_name=trader_name,
                mode="monte_carlo",
                fill_model=fill_model.to_dict(),
                perturbations=perturb.to_dict(),
                summary=summary,
                session_rows=list(row.get("session_rows") or []),
                orders=[],
                fills=[],
                inventory_series=[],
                pnl_series=[],
                validation={},
                fair_value_series=[],
                fair_value_summary={},
                behaviour={"summary": {}, "per_product": {}, "series": []},
                behaviour_series=[],
                access_scenario=access_payload,
                path_metrics=[],
            )
        )
    return RustBackendRun(
        sessions=sessions,
        path_bands=dict(run_payload.get("path_bands") or {}),
        profile=profile,
    )


def run_streaming_synthetic_session(
    *,
    trader,
    trader_name: str,
    fill_model: FillModel,
    perturb: PerturbationConfig,
    days: Sequence[int],
    market_seed: int,
    execution_seed: int,
    run_name: str,
    path_bucket_count: int,
    access_scenario: AccessScenario | None = None,
    print_trader_output: bool = False,
    simulation_context: StreamingSimulationContext | None = None,
    round_spec: RoundSpec | None = None,
) -> tuple[SessionArtefacts, Dict[str, object]]:
    access_scenario = access_scenario or NO_ACCESS_SCENARIO
    round_spec = round_spec or get_round_spec(1)
    products = tuple(round_spec.products)
    context = simulation_context or prepare_streaming_simulation_context(perturb)
    market_rng = random.Random(int(market_seed))
    execution_rng = random.Random(int(execution_seed))
    session_started = time.perf_counter()
    timings = new_profile("streaming")
    stdout_sink = _NullWriter()

    ledgers = {product: ProductLedger() for product in products}
    trader_data = ""
    prev_own_trades = {product: [] for product in products}
    prev_market_trades = {product: [] for product in products}
    listings = {product: Listing(product, product, round_spec.currency) for product in products}
    schedule = OrderSchedule(products)
    session_rows: list[Dict[str, object]] = []
    total_limit_breaches = 0
    total_order_count = 0
    total_fill_count = 0
    global_step = 0
    running_peak = float("-inf")
    max_drawdown = 0.0
    slippage_accumulator = _new_slippage_accumulator(products)
    tick_timestamps = [tick * TIMESTAMP_STEP for tick in range(context.tick_count)]
    collector_days = [
        DayDataset(day=int(day), timestamps=tick_timestamps, books_by_timestamp={}, trades_by_timestamp={})
        for day in days
    ]
    path_metric_collector = _StreamingPathMetricCollector(collector_days, max(0, int(path_bucket_count)), products)
    final_marks: Dict[str, float | None] = {product: None for product in products}
    last_latent: Dict[str, float | None] = {product: None for product in products}

    for session_day_index, day in enumerate(days):
        generation_started = time.perf_counter()
        latent_paths = {
            product: simulate_latent_fair(
                product,
                context.calibration,
                session_day_index,
                market_rng,
                continue_from=last_latent[product],
                tick_count=context.tick_count,
            )
            for product in products
        }
        if perturb.shock_tick is not None:
            shock_tick = max(0, int(perturb.shock_tick))
            for product, path in latent_paths.items():
                shock = perturb.shock_for(product)
                if shock == 0.0 or shock_tick >= len(path):
                    continue
                for tick in range(shock_tick, len(path)):
                    path[tick] += shock
        trade_counts = {
            product: sample_trade_counts(product, context.calibration, market_rng, tick_count=context.tick_count)
            for product in products
        }
        timings["market_generation_seconds"] = float(timings["market_generation_seconds"]) + (time.perf_counter() - generation_started)

        day_marks: Dict[str, float | None] = {product: None for product in products}
        for tick, ts in enumerate(tick_timestamps):
            generation_started = time.perf_counter()
            tick_snapshots: Dict[str, BookSnapshot] = {}
            tick_access_fractions: Dict[str, float] = {}
            tick_trades: Dict[str, list[TradePrint]] = {}
            for product in products:
                access_extra_fraction = access_scenario.active_extra_fraction(execution_rng)
                tick_access_fractions[product] = access_extra_fraction
                latent = float(latent_paths[product][tick])
                book = make_book(product, latent, context.samplers, context.calibration, market_rng)
                bids = list(book.bids)
                asks = list(book.asks)
                mid = (bids[0][0] + asks[0][0]) / 2.0 if bids and asks else None
                raw_snapshot = BookSnapshot(
                    timestamp=ts,
                    product=product,
                    bids=bids,
                    asks=asks,
                    mid=mid,
                    reference_fair=latent,
                    source_day=int(day),
                )
                tick_snapshots[product] = _scaled_snapshot(
                    raw_snapshot,
                    execution_rng,
                    perturb,
                    access_scenario.book_volume_multiplier(access_extra_fraction),
                )
                trades: list[TradePrint] = []
                for _ in range(int(trade_counts[product][tick])):
                    market_buy = market_rng.random() < float(context.calibration[product]["trade_buy_prob"])
                    levels = asks if market_buy else bids
                    if not levels:
                        continue
                    trade_price = levels[0][0]
                    volume_limit = sum(level[1] for level in levels)
                    quantity = sample_trade_quantity(product, context.samplers, volume_limit, market_rng)
                    trades.append(
                        TradePrint(
                            timestamp=ts,
                            buyer="BOT_TAKER" if market_buy else "",
                            seller="" if market_buy else "BOT_TAKER",
                            symbol=product,
                            price=int(trade_price),
                            quantity=int(quantity),
                            synthetic=True,
                        )
                    )
                tick_trades[product] = trades
                day_marks[product] = latent
            timings["market_generation_seconds"] = float(timings["market_generation_seconds"]) + (time.perf_counter() - generation_started)

            state_build_started = time.perf_counter()
            state = TradingState(
                traderData=trader_data,
                timestamp=ts,
                listings=listings,
                order_depths={
                    product: snapshot_to_order_depth(tick_snapshots[product])
                    for product in products
                },
                own_trades=prev_own_trades,
                market_trades=prev_market_trades,
                position={product: ledgers[product].position for product in products},
                observations=Observation({}, {}),
            )
            timings["state_build_seconds"] = float(timings["state_build_seconds"]) + (time.perf_counter() - state_build_started)

            trader_started = time.perf_counter()
            if print_trader_output:
                result = trader.run(state)
            else:
                with contextlib.redirect_stdout(stdout_sink):
                    result = trader.run(state)
            timings["trader_seconds"] = float(timings["trader_seconds"]) + (time.perf_counter() - trader_started)

            if not isinstance(result, tuple) or len(result) != 3:
                raise RuntimeError(f"Trader returned unexpected result at {ts}: {result!r}")
            submitted_orders_raw, _conversions, trader_data = result
            submitted_orders = {
                product: list(submitted_orders_raw.get(product, [])) if submitted_orders_raw else []
                for product in products
            }
            due_step = global_step + max(0, int(perturb.latency_ticks))
            schedule.add(due_step, submitted_orders)
            due_orders = schedule.pop(global_step)

            execution_started = time.perf_counter()
            own_trades_tick = {product: [] for product in products}
            market_trades_tick = {product: [] for product in products}
            total_mtm_for_tick = 0.0

            for product in products:
                snapshot = tick_snapshots[product]
                product_orders = due_orders.get(product, [])
                total_order_count += len(product_orders)
                product_fills, residual_trades, limit_breach = _execute_order_batch(
                    timestamp=ts,
                    product=product,
                    snapshot=snapshot,
                    trades=tick_trades[product],
                    ledger=ledgers[product],
                    orders=product_orders,
                    fill_model=fill_model,
                    perturb=perturb,
                    round_spec=round_spec,
                    access_scenario=access_scenario,
                    access_extra_fraction=tick_access_fractions[product],
                    rng=execution_rng,
                )
                total_limit_breaches += limit_breach
                total_fill_count += len(product_fills)
                for fill in product_fills:
                    _record_slippage_fill(slippage_accumulator, fill)
                    if fill["side"] == "buy":
                        own_trades_tick[product].append(Trade(product, fill["price"], fill["quantity"], "SUBMISSION", "BOT", ts))
                    else:
                        own_trades_tick[product].append(Trade(product, fill["price"], fill["quantity"], "BOT", "SUBMISSION", ts))
                for residual in residual_trades:
                    market_trades_tick[product].append(
                        Trade(residual.symbol, residual.price, residual.quantity, residual.buyer, residual.seller, residual.timestamp)
                    )
                mark = snapshot.reference_fair if snapshot.reference_fair is not None else snapshot.mid
                product_mtm = ledgers[product].mtm(mark)
                total_mtm_for_tick += float(product_mtm)
                path_started = time.perf_counter()
                path_metric_collector.add(
                    day=int(day),
                    product=product,
                    timestamp=ts,
                    analysis_fair=snapshot.reference_fair,
                    mid=snapshot.mid,
                    inventory=ledgers[product].position,
                    pnl=product_mtm,
                )
                timings["path_metrics_seconds"] = float(timings["path_metrics_seconds"]) + (time.perf_counter() - path_started)

            timings["execution_seconds"] = float(timings["execution_seconds"]) + (time.perf_counter() - execution_started)

            prev_own_trades = own_trades_tick
            prev_market_trades = market_trades_tick
            global_step += 1
            running_peak = max(running_peak, total_mtm_for_tick)
            max_drawdown = max(max_drawdown, running_peak - total_mtm_for_tick)

        for product in products:
            last_latent[product] = day_marks[product]
            final_marks[product] = day_marks[product]
        gross_day_pnl = sum(ledgers[product].mtm(day_marks[product]) for product in products)
        maf_cost_for_row = access_scenario.maf_cost if int(day) == int(days[-1]) else 0.0
        day_row = {
            "day": int(day),
            "final_pnl": gross_day_pnl - maf_cost_for_row,
            "gross_pnl_before_maf": gross_day_pnl,
            "maf_cost": maf_cost_for_row,
            "access_scenario": access_scenario.name,
            "per_product_pnl": {product: ledgers[product].mtm(day_marks[product]) for product in products},
            "per_product_position": {product: ledgers[product].position for product in products},
        }
        if "ASH_COATED_OSMIUM" in products:
            day_row["osmium_pnl"] = day_row["per_product_pnl"]["ASH_COATED_OSMIUM"]
            day_row["osmium_position"] = day_row["per_product_position"]["ASH_COATED_OSMIUM"]
        if "INTARIAN_PEPPER_ROOT" in products:
            day_row["pepper_pnl"] = day_row["per_product_pnl"]["INTARIAN_PEPPER_ROOT"]
            day_row["pepper_position"] = day_row["per_product_position"]["INTARIAN_PEPPER_ROOT"]
        session_rows.append(day_row)

    postprocess_started = time.perf_counter()
    slippage_summary = _finalize_slippage_accumulator(slippage_accumulator)
    per_product_summary = {
        product: {
            "cash": ledgers[product].cash,
            "realised": ledgers[product].realised,
            "unrealised": ledgers[product].unrealised(final_marks[product]),
            "final_mtm": ledgers[product].mtm(final_marks[product]),
            "final_position": ledgers[product].position,
            "avg_entry_price": ledgers[product].avg_entry_price,
            "slippage_cost": slippage_summary["per_product"][product]["slippage_cost"],
            "average_slippage_ticks": slippage_summary["per_product"][product]["average_slippage_ticks"],
        }
        for product in products
    }
    path_metrics = path_metric_collector.rows()
    timings["postprocess_seconds"] = float(timings["postprocess_seconds"]) + (time.perf_counter() - postprocess_started)
    gross_final_pnl = sum(item["final_mtm"] for item in per_product_summary.values())
    maf_cost = access_scenario.maf_cost
    summary = {
        "final_pnl": gross_final_pnl - maf_cost,
        "gross_pnl_before_maf": gross_final_pnl,
        "maf_cost": maf_cost,
        "access_scenario": access_scenario.to_dict(),
        "fill_count": total_fill_count,
        "order_count": total_order_count,
        "limit_breaches": total_limit_breaches,
        "max_drawdown": max_drawdown,
        "final_positions": {product: per_product_summary[product]["final_position"] for product in products},
        "per_product": per_product_summary,
        "slippage": slippage_summary,
        "fair_value": {},
        "behaviour": {},
    }
    timings["session_total_seconds"] = float(timings["session_total_seconds"]) + (time.perf_counter() - session_started)
    timings["session_count"] = 1
    return (
        SessionArtefacts(
            run_name=run_name,
            trader_name=trader_name,
            mode="monte_carlo",
            round_number=round_spec.round_number,
            round_name=round_spec.name,
            products=products,
            product_metadata={
                symbol: meta.to_dict()
                for symbol, meta in round_spec.product_metadata.items()
            },
            fill_model=fill_model.to_dict(),
            perturbations=perturb.to_dict(),
            summary=summary,
            session_rows=session_rows,
            orders=[],
            fills=[],
            inventory_series=[],
            pnl_series=[],
            validation={},
            fair_value_series=[],
            fair_value_summary={},
            behaviour={"summary": {}, "per_product": {}, "series": []},
            behaviour_series=[],
            access_scenario=access_scenario.to_dict(),
            path_metrics=path_metrics,
        ),
        finalise_profile(timings),
    )
