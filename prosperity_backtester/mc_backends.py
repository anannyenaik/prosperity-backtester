from __future__ import annotations

import contextlib
import random
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Dict, Mapping, Sequence

from .datamodel import Listing, Observation, Trade, TradingState
from .dataset import BookSnapshot, DayDataset, TradePrint
from .fill_models import FillModel
from .metadata import CURRENCY, PRODUCTS, TIMESTAMP_STEP
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

MONTE_CARLO_BACKENDS = ("classic", "streaming")
DEFAULT_MONTE_CARLO_BACKEND = "streaming"
AUTO_MONTE_CARLO_BACKEND = "auto"

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
) -> tuple[SessionArtefacts, Dict[str, object]]:
    access_scenario = access_scenario or NO_ACCESS_SCENARIO
    context = simulation_context or prepare_streaming_simulation_context(perturb)
    market_rng = random.Random(int(market_seed))
    execution_rng = random.Random(int(execution_seed))
    session_started = time.perf_counter()
    timings = new_profile("streaming")
    stdout_sink = _NullWriter()

    ledgers = {product: ProductLedger() for product in PRODUCTS}
    trader_data = ""
    prev_own_trades = {product: [] for product in PRODUCTS}
    prev_market_trades = {product: [] for product in PRODUCTS}
    listings = {product: Listing(product, product, CURRENCY) for product in PRODUCTS}
    schedule = OrderSchedule()
    session_rows: list[Dict[str, object]] = []
    total_limit_breaches = 0
    total_order_count = 0
    total_fill_count = 0
    global_step = 0
    running_peak = float("-inf")
    max_drawdown = 0.0
    slippage_accumulator = _new_slippage_accumulator()
    tick_timestamps = [tick * TIMESTAMP_STEP for tick in range(context.tick_count)]
    collector_days = [
        DayDataset(day=int(day), timestamps=tick_timestamps, books_by_timestamp={}, trades_by_timestamp={})
        for day in days
    ]
    path_metric_collector = _StreamingPathMetricCollector(collector_days, max(0, int(path_bucket_count)))
    final_marks: Dict[str, float | None] = {product: None for product in PRODUCTS}
    last_latent: Dict[str, float | None] = {product: None for product in PRODUCTS}

    for session_day_index, day in enumerate(days):
        generation_started = time.perf_counter()
        latent_paths = {
            product: simulate_latent_fair(
                product,
                context.calibration,
                session_day_index,
                market_rng,
                continue_from=last_latent[product],
            )[: context.tick_count]
            for product in PRODUCTS
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
            product: sample_trade_counts(product, context.calibration, market_rng)[: context.tick_count]
            for product in PRODUCTS
        }
        timings["market_generation_seconds"] = float(timings["market_generation_seconds"]) + (time.perf_counter() - generation_started)

        day_marks: Dict[str, float | None] = {product: None for product in PRODUCTS}
        for tick, ts in enumerate(tick_timestamps):
            generation_started = time.perf_counter()
            tick_snapshots: Dict[str, BookSnapshot] = {}
            tick_access_fractions: Dict[str, float] = {}
            tick_trades: Dict[str, list[TradePrint]] = {}
            for product in PRODUCTS:
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
                    for product in PRODUCTS
                },
                own_trades=prev_own_trades,
                market_trades=prev_market_trades,
                position={product: ledgers[product].position for product in PRODUCTS},
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
                for product in PRODUCTS
            }
            due_step = global_step + max(0, int(perturb.latency_ticks))
            schedule.add(due_step, submitted_orders)
            due_orders = schedule.pop(global_step)

            execution_started = time.perf_counter()
            own_trades_tick = {product: [] for product in PRODUCTS}
            market_trades_tick = {product: [] for product in PRODUCTS}
            total_mtm_for_tick = 0.0

            for product in PRODUCTS:
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

        for product in PRODUCTS:
            last_latent[product] = day_marks[product]
            final_marks[product] = day_marks[product]
        gross_day_pnl = sum(ledgers[product].mtm(day_marks[product]) for product in PRODUCTS)
        maf_cost_for_row = access_scenario.maf_cost if int(day) == int(days[-1]) else 0.0
        session_rows.append(
            {
                "day": int(day),
                "final_pnl": gross_day_pnl - maf_cost_for_row,
                "gross_pnl_before_maf": gross_day_pnl,
                "maf_cost": maf_cost_for_row,
                "access_scenario": access_scenario.name,
                "osmium_pnl": ledgers["ASH_COATED_OSMIUM"].mtm(day_marks["ASH_COATED_OSMIUM"]),
                "pepper_pnl": ledgers["INTARIAN_PEPPER_ROOT"].mtm(day_marks["INTARIAN_PEPPER_ROOT"]),
                "osmium_position": ledgers["ASH_COATED_OSMIUM"].position,
                "pepper_position": ledgers["INTARIAN_PEPPER_ROOT"].position,
            }
        )

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
        for product in PRODUCTS
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
        "final_positions": {product: per_product_summary[product]["final_position"] for product in PRODUCTS},
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
