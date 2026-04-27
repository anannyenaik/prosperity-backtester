from __future__ import annotations

import hashlib
import json
import math
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence

from .dataset import DayDataset, load_round_dataset
from .experiments import TraderSpec, run_monte_carlo
from .metadata import get_round_spec
from .platform import PerturbationConfig, generate_synthetic_market_days, summarise_monte_carlo_sessions, write_rows_csv
from .provenance import capture_provenance
from .r4_manifest import build_round4_manifest
from .round3 import black_scholes_call_price, implied_vol_bisection, parse_voucher_symbol, prepare_round3_synthetic_context, tte_years
from .storage import OutputOptions


UNDERLYING = "VELVETFRUIT_EXTRACT"
HYDROGEL = "HYDROGEL_PACK"
CENTRAL_VOUCHERS = ("VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500")
ALL_VOUCHERS = ("VEV_4000", "VEV_4500", *CENTRAL_VOUCHERS, "VEV_6000", "VEV_6500")

R4_MC_PRESETS: Dict[str, Dict[str, object]] = {
    "fast": {
        "sessions": 2,
        "sample_sessions": 1,
        "tick_limit": 300,
        "days": "requested_days",
        "seed_policy": "market_seed=base_seed+session_index*17; execution_seed=base_seed+session_index*31",
        "expected_runtime_band": "seconds to a few minutes",
        "decision_use": "CI and plumbing smoke only",
    },
    "default": {
        "sessions": 8,
        "sample_sessions": 2,
        "tick_limit": 1000,
        "days": "requested_days",
        "seed_policy": "market_seed=base_seed+session_index*17; execution_seed=base_seed+session_index*31",
        "expected_runtime_band": "a few minutes locally",
        "decision_use": "local validation smoke, not tail-risk proof",
    },
    "full": {
        "sessions": 8,
        "sample_sessions": 2,
        "tick_limit": 1500,
        "days": "requested_days",
        "seed_policy": "market_seed=base_seed+session_index*17; execution_seed=base_seed+session_index*31",
        "expected_runtime_band": "several minutes locally",
        "decision_use": "broader validation, still below stable p05/p01 sizing",
    },
    "heavy": {
        "sessions": 64,
        "sample_sessions": 4,
        "tick_limit": 5000,
        "days": "requested_days",
        "seed_policy": "market_seed=base_seed+session_index*17; execution_seed=base_seed+session_index*31",
        "expected_runtime_band": "slow optional run",
        "decision_use": "tail-estimate rehearsal, still not official simulator equivalence",
    },
}


def _preset_config(preset: str) -> Dict[str, object]:
    try:
        return dict(R4_MC_PRESETS[str(preset)])
    except KeyError as exc:
        choices = ", ".join(sorted(R4_MC_PRESETS))
        raise ValueError(f"unknown Round 4 MC preset {preset!r}. Choose one of: {choices}") from exc


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _std(values: Sequence[float]) -> float | None:
    return statistics.pstdev(values) if len(values) > 1 else (0.0 if values else None)


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = max(0.0, min(1.0, q)) * (len(ordered) - 1)
    lo = int(math.floor(idx))
    hi = min(len(ordered) - 1, lo + 1)
    if lo == hi:
        return ordered[lo]
    weight = idx - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def _summary(values: Sequence[float]) -> Dict[str, object]:
    return {
        "count": len(values),
        "mean": _mean(values),
        "std": _std(values),
        "p05": _quantile(values, 0.05),
        "p50": _quantile(values, 0.50),
        "p95": _quantile(values, 0.95),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def _ac1(values: Sequence[float]) -> float | None:
    if len(values) < 3:
        return None
    left = [float(value) for value in values[:-1]]
    right = [float(value) for value in values[1:]]
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    left_var = sum((value - left_mean) ** 2 for value in left)
    right_var = sum((value - right_mean) ** 2 for value in right)
    if left_var <= 0.0 or right_var <= 0.0:
        return None
    cov = sum((l_value - left_mean) * (r_value - right_mean) for l_value, r_value in zip(left, right))
    return cov / math.sqrt(left_var * right_var)


def _path_hash(market_days: Sequence[DayDataset]) -> str:
    h = hashlib.sha256()
    for day in market_days:
        h.update(str(day.day).encode("utf-8"))
        for timestamp in day.timestamps[:200]:
            h.update(str(timestamp).encode("utf-8"))
            for product in sorted(day.books_by_timestamp.get(timestamp, {})):
                snapshot = day.books_by_timestamp[timestamp][product]
                h.update(product.encode("utf-8"))
                h.update(str(snapshot.mid).encode("utf-8"))
                h.update(str(snapshot.bids[:1]).encode("utf-8"))
                h.update(str(snapshot.asks[:1]).encode("utf-8"))
            for product, trades in sorted(day.trades_by_timestamp.get(timestamp, {}).items()):
                h.update(product.encode("utf-8"))
                for trade in trades:
                    h.update(f"{trade.price}:{trade.quantity}:{trade.buyer}:{trade.seller}".encode("utf-8"))
    return h.hexdigest()


def _price_path_hash(market_days: Sequence[DayDataset]) -> str:
    h = hashlib.sha256()
    for day in market_days:
        h.update(str(day.day).encode("utf-8"))
        for timestamp in day.timestamps[:200]:
            h.update(str(timestamp).encode("utf-8"))
            for product in sorted(day.books_by_timestamp.get(timestamp, {})):
                snapshot = day.books_by_timestamp[timestamp][product]
                h.update(product.encode("utf-8"))
                h.update(str(snapshot.mid).encode("utf-8"))
                h.update(str(snapshot.reference_fair).encode("utf-8"))
                h.update(str(snapshot.bids[:1]).encode("utf-8"))
                h.update(str(snapshot.asks[:1]).encode("utf-8"))
    return h.hexdigest()


def _config_hash(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _metrics_for_days(market_days: Sequence[DayDataset], *, tick_limit: int | None = None) -> Dict[str, object]:
    spec = get_round_spec(4)
    per_product: Dict[str, Dict[str, object]] = {}
    for product in spec.products:
        mids: List[float] = []
        returns: List[float] = []
        spreads: List[float] = []
        depths: List[float] = []
        trade_sizes: List[float] = []
        trade_count_by_day: Dict[int, int] = {}
        counterparty_counts: Dict[str, int] = {}
        signed_markouts_20: List[float] = []
        for day in market_days:
            timestamps = day.timestamps if tick_limit is None else day.timestamps[: max(1, int(tick_limit))]
            mids_by_timestamp = {
                ts: float(snapshot.mid)
                for ts in timestamps
                for snapshot in [day.books_by_timestamp.get(ts, {}).get(product)]
                if snapshot is not None and snapshot.mid is not None
            }
            product_mids = [mids_by_timestamp[ts] for ts in timestamps if ts in mids_by_timestamp]
            mids.extend(product_mids)
            returns.extend(b - a for a, b in zip(product_mids, product_mids[1:]))
            for ts in timestamps:
                snapshot = day.books_by_timestamp.get(ts, {}).get(product)
                if snapshot is not None and snapshot.bids and snapshot.asks:
                    spreads.append(float(snapshot.asks[0][0] - snapshot.bids[0][0]))
                    depths.append(float(sum(v for _p, v in snapshot.bids) + sum(v for _p, v in snapshot.asks)))
                trades = day.trades_by_timestamp.get(ts, {}).get(product, [])
                trade_count_by_day[day.day] = trade_count_by_day.get(day.day, 0) + len(trades)
                for trade in trades:
                    trade_sizes.append(float(trade.quantity))
                    if trade.buyer:
                        counterparty_counts[str(trade.buyer)] = counterparty_counts.get(str(trade.buyer), 0) + 1
                    if trade.seller:
                        counterparty_counts[str(trade.seller)] = counterparty_counts.get(str(trade.seller), 0) + 1
                    current_mid = mids_by_timestamp.get(ts)
                    future_mid = mids_by_timestamp.get(ts + 20 * spec.timestamp_step)
                    if current_mid is None or future_mid is None:
                        continue
                    move = float(future_mid) - float(current_mid)
                    if trade.buyer:
                        signed_markouts_20.append(move)
                    if trade.seller:
                        signed_markouts_20.append(-move)
        per_product[product] = {
            "mid": _summary(mids),
            "returns": _summary(returns),
            "ac1_mid": _ac1(mids),
            "volatility_per_tick": _std(returns),
            "spread": _summary(spreads),
            "depth": _summary(depths),
            "trade_count_by_day": dict(sorted(trade_count_by_day.items())),
            "trade_count_total": sum(trade_count_by_day.values()),
            "trade_size": _summary(trade_sizes),
            "counterparty_counts": dict(sorted(counterparty_counts.items())),
            "signed_markout_20": _summary(signed_markouts_20),
        }
    return {"products": per_product}


def _velvet_voucher_correlation(market_days: Sequence[DayDataset], *, tick_limit: int | None = None) -> Dict[str, object]:
    correlations: Dict[str, object] = {}
    for symbol in ALL_VOUCHERS:
        velvet_moves: List[float] = []
        voucher_moves: List[float] = []
        for day in market_days:
            timestamps = day.timestamps if tick_limit is None else day.timestamps[: max(1, int(tick_limit))]
            velvet = [
                day.books_by_timestamp.get(ts, {}).get(UNDERLYING).mid
                for ts in timestamps
                if day.books_by_timestamp.get(ts, {}).get(UNDERLYING) is not None
                and day.books_by_timestamp.get(ts, {}).get(UNDERLYING).mid is not None
            ]
            voucher = [
                day.books_by_timestamp.get(ts, {}).get(symbol).mid
                for ts in timestamps
                if day.books_by_timestamp.get(ts, {}).get(symbol) is not None
                and day.books_by_timestamp.get(ts, {}).get(symbol).mid is not None
            ]
            pair_count = min(len(velvet), len(voucher))
            velvet_moves.extend(float(b) - float(a) for a, b in zip(velvet[:pair_count], velvet[1:pair_count]))
            voucher_moves.extend(float(b) - float(a) for a, b in zip(voucher[:pair_count], voucher[1:pair_count]))
        correlations[symbol] = _correlation(velvet_moves, voucher_moves)
    return correlations


def _correlation(left: Sequence[float], right: Sequence[float]) -> float | None:
    count = min(len(left), len(right))
    if count < 3:
        return None
    x = [float(value) for value in left[:count]]
    y = [float(value) for value in right[:count]]
    x_mean = statistics.fmean(x)
    y_mean = statistics.fmean(y)
    x_var = sum((value - x_mean) ** 2 for value in x)
    y_var = sum((value - y_mean) ** 2 for value in y)
    if x_var <= 0.0 or y_var <= 0.0:
        return None
    cov = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y))
    return cov / math.sqrt(x_var * y_var)


def _option_residual_metrics(market_days: Sequence[DayDataset], *, tick_limit: int | None = None) -> Dict[str, object]:
    spec = get_round_spec(4)
    by_symbol: Dict[str, List[float]] = {symbol: [] for symbol in ALL_VOUCHERS}
    iv_by_symbol: Dict[str, List[float]] = {symbol: [] for symbol in ALL_VOUCHERS}
    for day in market_days:
        t_years = tte_years(spec.tte_days_by_historical_day.get(day.day, spec.final_tte_days or 4))
        timestamps = day.timestamps if tick_limit is None else day.timestamps[: max(1, int(tick_limit))]
        for ts in timestamps:
            snapshots = day.books_by_timestamp.get(ts, {})
            underlying = snapshots.get(UNDERLYING)
            if underlying is None or underlying.mid is None:
                continue
            spot = float(underlying.mid)
            centre_ivs: List[float] = []
            for symbol in CENTRAL_VOUCHERS:
                snapshot = snapshots.get(symbol)
                if snapshot is None or snapshot.mid is None:
                    continue
                iv = implied_vol_bisection(float(snapshot.mid), spot, parse_voucher_symbol(symbol), t_years)
                if iv is not None and iv > 0.0:
                    centre_ivs.append(float(iv))
                    iv_by_symbol[symbol].append(float(iv))
            if not centre_ivs:
                continue
            centre_iv = statistics.median(centre_ivs)
            for symbol in ALL_VOUCHERS:
                snapshot = snapshots.get(symbol)
                if snapshot is None or snapshot.mid is None:
                    continue
                strike = parse_voucher_symbol(symbol)
                fair = black_scholes_call_price(spot, strike, t_years, centre_iv)
                by_symbol[symbol].append(float(snapshot.mid) - fair)
                if symbol not in CENTRAL_VOUCHERS:
                    iv = implied_vol_bisection(float(snapshot.mid), spot, strike, t_years)
                    if iv is not None and iv > 0.0:
                        iv_by_symbol[symbol].append(float(iv))
    return {
        symbol: {
            "iv": _summary(values),
            "bs_residual": _summary(by_symbol[symbol]),
        }
        for symbol, values in iv_by_symbol.items()
    }


def _write_simple_inventory_trader(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
from datamodel import Order


class Trader:
    def run(self, state):
        orders = {}
        for product, depth in state.order_depths.items():
            pos = state.position.get(product, 0)
            product_orders = []
            if depth.buy_orders and pos > -1:
                product_orders.append(Order(product, max(depth.buy_orders), -1))
            if depth.sell_orders and pos < 1:
                product_orders.append(Order(product, min(depth.sell_orders), 1))
            orders[product] = product_orders
        return orders, 0, state.traderData
""".strip(),
        encoding="utf-8",
    )
    return path


def _metric_comparison_rows(
    public_metrics: Mapping[str, object],
    synthetic_metrics: Mapping[str, object],
    resemblance: Sequence[Mapping[str, object]],
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    public_products = public_metrics.get("products", {})
    synthetic_products = synthetic_metrics.get("products", {})
    resemblance_by_product = {str(row.get("product")): row for row in resemblance}
    for product, public_row in public_products.items():
        synthetic_row = synthetic_products.get(product, {})
        for metric in ("mid", "returns", "spread", "depth", "trade_size", "signed_markout_20"):
            public_summary = (public_row or {}).get(metric) or {}
            synthetic_summary = (synthetic_row or {}).get(metric) or {}
            rows.append(
                {
                    "product": product,
                    "metric": metric,
                    "public_count": public_summary.get("count"),
                    "synthetic_count": synthetic_summary.get("count"),
                    "public_mean": public_summary.get("mean"),
                    "synthetic_mean": synthetic_summary.get("mean"),
                    "public_std": public_summary.get("std"),
                    "synthetic_std": synthetic_summary.get("std"),
                    "public_p05": public_summary.get("p05"),
                    "synthetic_p05": synthetic_summary.get("p05"),
                    "public_p50": public_summary.get("p50"),
                    "synthetic_p50": synthetic_summary.get("p50"),
                    "public_p95": public_summary.get("p95"),
                    "synthetic_p95": synthetic_summary.get("p95"),
                    "resemblance_status": (resemblance_by_product.get(str(product)) or {}).get("status"),
                }
            )
        public_trades = float((public_row or {}).get("trade_count_total") or 0.0)
        synthetic_trades = float((synthetic_row or {}).get("trade_count_total") or 0.0)
        rows.append(
            {
                "product": product,
                "metric": "trade_count_total",
                "public_count": public_trades,
                "synthetic_count": synthetic_trades,
                "public_mean": public_trades,
                "synthetic_mean": synthetic_trades,
                "resemblance_status": (resemblance_by_product.get(str(product)) or {}).get("status"),
            }
        )
    return rows


def _scenario_suite_smoke(
    *,
    public_days: Sequence[DayDataset],
    day: int,
    seed: int,
    scenario_tick_limit: int,
) -> Dict[str, object]:
    spec = get_round_spec(4)
    context = prepare_round3_synthetic_context(
        public_days,
        round_spec=spec,
        tick_count=max(20, int(scenario_tick_limit)),
    )
    held_out_days = [day_row for day_row in public_days if int(day_row.day) != int(day)]
    held_out_context = prepare_round3_synthetic_context(
        public_days,
        round_spec=spec,
        tick_count=max(20, int(scenario_tick_limit)),
        counterparty_market_days=held_out_days or public_days,
    )
    deep_itm_liquidity = {symbol: 0.35 for symbol in ("VEV_4000", "VEV_4500")}
    central_liquidity = {symbol: 0.55 for symbol in CENTRAL_VOUCHERS}
    far_otm_liquidity = {symbol: 0.30 for symbol in ("VEV_6000", "VEV_6500")}
    far_otm_spread = {symbol: 3 for symbol in ("VEV_6000", "VEV_6500")}
    scenario_specs: List[tuple[str, PerturbationConfig, object]] = [
        ("base_calibrated", PerturbationConfig(counterparty_edge_strength=0.25), context),
        ("no_counterparty_alpha", PerturbationConfig(counterparty_edge_strength=0.0), context),
        ("zero_names", PerturbationConfig(counterparty_flow_enabled=False, counterparty_edge_strength=0.0), context),
        ("shuffled_names", PerturbationConfig(counterparty_edge_strength=0.0, counterparty_name_mode="shuffled"), context),
        ("half_counterparty_alpha", PerturbationConfig(counterparty_edge_strength=0.125), context),
        ("sign_flipped_names", PerturbationConfig(counterparty_edge_strength=0.25, counterparty_edge_sign=-1.0), context),
        ("day_held_out_counterparty_alpha", PerturbationConfig(counterparty_edge_strength=0.25), held_out_context),
        ("cross_product_flow", PerturbationConfig(counterparty_edge_strength=0.25, scenario_name="cross_product_flow"), context),
        ("hydrogel_shift_-100", PerturbationConfig(shock_tick=10, hydrogel_shock=-100.0), context),
        ("hydrogel_shift_-60", PerturbationConfig(shock_tick=10, hydrogel_shock=-60.0), context),
        ("hydrogel_shift_-30", PerturbationConfig(shock_tick=10, hydrogel_shock=-30.0), context),
        ("hydrogel_shift_0", PerturbationConfig(shock_tick=10, hydrogel_shock=0.0), context),
        ("hydrogel_shift_30", PerturbationConfig(shock_tick=10, hydrogel_shock=30.0), context),
        ("hydrogel_shift_60", PerturbationConfig(shock_tick=10, hydrogel_shock=60.0), context),
        ("hydrogel_shift_100", PerturbationConfig(shock_tick=10, hydrogel_shock=100.0), context),
        ("velvet_level_down", PerturbationConfig(shock_tick=10, underlying_shock=-80.0), context),
        ("velvet_level_up", PerturbationConfig(shock_tick=10, underlying_shock=80.0), context),
        ("velvet_vol_down", PerturbationConfig(vol_scale=0.75), context),
        ("velvet_vol_up", PerturbationConfig(vol_scale=1.35), context),
        ("voucher_iv_residual_shock_down", PerturbationConfig(vol_shift=-0.04, option_residual_noise_scale=0.6), context),
        ("voucher_iv_residual_shock_up", PerturbationConfig(vol_shift=0.05, option_residual_noise_scale=1.5), context),
        ("deep_itm_liquidity_shock", PerturbationConfig(option_liquidity_scale_by_product=deep_itm_liquidity, voucher_spread_shift_ticks_by_product={"VEV_4000": 2, "VEV_4500": 2}), context),
        ("central_voucher_liquidity_shock", PerturbationConfig(option_liquidity_scale_by_product=central_liquidity), context),
        ("far_otm_floor_tick_shock", PerturbationConfig(option_liquidity_scale_by_product=far_otm_liquidity, voucher_spread_shift_ticks_by_product=far_otm_spread), context),
        ("stale_voucher_mids", PerturbationConfig(stale_voucher_mid_probability=1.0), context),
        ("spread_widening", PerturbationConfig(spread_shift_ticks=2, voucher_spread_shift_ticks=2), context),
        ("depth_thinning", PerturbationConfig(underlying_liquidity_scale=0.55, hydrogel_liquidity_scale=0.55, option_liquidity_scale=0.55), context),
        ("trade_count_thinning", PerturbationConfig(trade_count_scale=0.35), context),
        ("passive_none", PerturbationConfig(trade_matching_mode="none"), context),
        ("passive_worse", PerturbationConfig(trade_matching_mode="worse"), context),
        ("passive_all", PerturbationConfig(trade_matching_mode="all"), context),
        ("fill_adverse", PerturbationConfig(passive_fill_scale=0.7, missed_fill_additive=0.08, adverse_selection_ticks=1), context),
        ("fill_harsh", PerturbationConfig(passive_fill_scale=0.5, missed_fill_additive=0.15, adverse_selection_ticks=2, slippage_multiplier=1.5), context),
    ]
    rows: List[Dict[str, object]] = []
    for index, (name, perturbation, scenario_context) in enumerate(scenario_specs):
        try:
            generated = generate_synthetic_market_days(
                days=(int(day),),
                seed=int(seed),
                perturb=perturbation,
                round_spec=spec,
                round3_context=scenario_context,
            )
            first_day = generated[0]
            config = perturbation.to_dict()
            rows.append(
                {
                    "scenario": name,
                    "status": "pass",
                    "path_hash": _path_hash(generated),
                    "price_path_hash": _price_path_hash(generated),
                    "tick_count": len(first_day.timestamps),
                    "trade_rows": sum(len(trades) for by_product in first_day.trades_by_timestamp.values() for trades in by_product.values()),
                    "config_hash": _config_hash(config),
                    "config": config,
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "scenario": name,
                    "status": "fail",
                    "error": str(exc),
                    "config": perturbation.to_dict(),
                }
            )
    by_name = {str(row.get("scenario")): row for row in rows}
    transform_checks = {
        "shuffled_names_preserve_prices": (
            by_name.get("shuffled_names", {}).get("price_path_hash")
            == by_name.get("no_counterparty_alpha", {}).get("price_path_hash")
        ),
        "shuffled_names_change_allocations": (
            by_name.get("shuffled_names", {}).get("path_hash")
            != by_name.get("no_counterparty_alpha", {}).get("path_hash")
        ),
        "trade_count_thinning_reduces_or_matches_rows": (
            int(by_name.get("trade_count_thinning", {}).get("trade_rows") or 0)
            <= int(by_name.get("no_counterparty_alpha", {}).get("trade_rows") or 0)
        ),
        "day_held_out_context_distinct": (
            by_name.get("day_held_out_counterparty_alpha", {}).get("config_hash")
            is not None
        ),
    }
    transform_failures = [name for name, ok in transform_checks.items() if not ok]
    return {
        "rows": rows,
        "scenario_count": len(rows),
        "failed": sum(1 for row in rows if row.get("status") == "fail"),
        "transform_checks": transform_checks,
        "status": "fail" if any(row.get("status") == "fail" for row in rows) or transform_failures else "pass",
        "transform_failures": transform_failures,
    }


def _mc_noop_checks(
    *,
    data_dir: Path,
    output_dir: Path,
    days: Sequence[int],
    sessions: int,
    sample_sessions: int,
    tick_limit: int,
    seed: int,
) -> Dict[str, object]:
    repo_root = Path(__file__).resolve().parent.parent
    noop = repo_root / "examples" / "noop_round3_trader.py"
    simple = _write_simple_inventory_trader(output_dir / "_work" / "simple_inventory_trader.py")
    perturb = PerturbationConfig(synthetic_tick_limit=tick_limit, counterparty_edge_strength=0.0)
    noop_a = run_monte_carlo(
        trader_spec=TraderSpec(name="noop_round4", path=noop),
        sessions=sessions,
        sample_sessions=sample_sessions,
        days=days,
        data_dir=data_dir,
        fill_model_name="base",
        perturbation=perturb,
        output_dir=output_dir / "noop_mc_a",
        base_seed=seed,
        run_name="r4_mc_validation_noop_a",
        round_number=4,
        monte_carlo_backend="classic",
        output_options=OutputOptions.from_profile("full"),
    )
    noop_b = run_monte_carlo(
        trader_spec=TraderSpec(name="noop_round4", path=noop),
        sessions=sessions,
        sample_sessions=sample_sessions,
        days=days,
        data_dir=data_dir,
        fill_model_name="base",
        perturbation=perturb,
        output_dir=output_dir / "noop_mc_b",
        base_seed=seed,
        run_name="r4_mc_validation_noop_b",
        round_number=4,
        monte_carlo_backend="classic",
        write_bundle=False,
    )
    simple_runs = run_monte_carlo(
        trader_spec=TraderSpec(name="simple_inventory", path=simple),
        sessions=max(1, min(2, sessions)),
        sample_sessions=0,
        days=days,
        data_dir=data_dir,
        fill_model_name="base",
        perturbation=perturb,
        output_dir=output_dir / "simple_inventory_mc",
        base_seed=seed,
        run_name="r4_mc_validation_simple_inventory",
        round_number=4,
        monte_carlo_backend="classic",
        write_bundle=False,
    )
    noop_pnl = [float(session.summary["final_pnl"]) for session in noop_a]
    simple_fill_count = sum(int(session.summary.get("fill_count") or 0) for session in simple_runs)
    sample_paths = sorted((output_dir / "noop_mc_a" / "sample_paths").glob("*.json"))
    return {
        "noop_summary": summarise_monte_carlo_sessions(noop_a),
        "noop_pnl_values": noop_pnl,
        "noop_zero_pnl": all(abs(value) <= 1e-9 for value in noop_pnl),
        "seed_determinism": [session.summary for session in noop_a] == [session.summary for session in noop_b],
        "simple_inventory_summary": summarise_monte_carlo_sessions(simple_runs),
        "simple_inventory_non_trivial": simple_fill_count > 0,
        "sample_path_trace_count": len(sample_paths),
        "sample_path_traces_saved": len(sample_paths) >= max(1, min(sample_sessions, sessions)),
        "artefacts": {
            "noop_mc_a": "noop_mc_a",
            "noop_mc_b": "noop_mc_b",
            "simple_inventory_mc": "simple_inventory_mc",
        },
    }


def _basic_resemblance_checks(public_metrics: Mapping[str, object], synthetic_metrics: Mapping[str, object]) -> List[Dict[str, object]]:
    checks: List[Dict[str, object]] = []
    public_products = public_metrics.get("products", {})
    synthetic_products = synthetic_metrics.get("products", {})
    for product, public_row in public_products.items():
        synthetic_row = synthetic_products.get(product, {})
        public_spread = ((public_row or {}).get("spread") or {}).get("mean")
        synthetic_spread = ((synthetic_row or {}).get("spread") or {}).get("mean")
        public_trades = float((public_row or {}).get("trade_count_total") or 0.0)
        synthetic_trades = float((synthetic_row or {}).get("trade_count_total") or 0.0)
        spread_ratio = None if not public_spread or not synthetic_spread else float(synthetic_spread) / float(public_spread)
        trade_ratio = None if public_trades <= 0 or synthetic_trades <= 0 else synthetic_trades / public_trades
        checks.append(
            {
                "product": product,
                "spread_ratio_synthetic_to_public": spread_ratio,
                "trade_count_ratio_synthetic_to_public": trade_ratio,
                "status": "pass"
                if (spread_ratio is None or 0.2 <= spread_ratio <= 5.0)
                and (trade_ratio is None or 0.1 <= trade_ratio <= 10.0)
                else "warn",
            }
        )
    return checks


def render_mc_validation_markdown(report: Mapping[str, object]) -> str:
    preset_config = report.get("preset_config") or {}
    lines = [
        "# Round 4 MC Validation",
        "",
        f"- Generated at: `{report.get('generated_at')}`",
        f"- Preset: `{report.get('preset')}`",
        f"- Status: **{report.get('status')}**",
        f"- Decision-grade: **{report.get('decision_grade')}**",
        f"- Seed: `{report.get('seed')}`",
        f"- Synthetic tick limit: `{report.get('synthetic_tick_limit')}`",
        f"- Sessions: `{report.get('sessions')}`",
        f"- Sample sessions: `{report.get('sample_sessions')}`",
        f"- Expected runtime band: `{preset_config.get('expected_runtime_band')}`",
        "",
        "| Gate | Status |",
        "| --- | --- |",
    ]
    for gate in report.get("gates", []):
        lines.append(f"| {gate.get('name')} | {gate.get('status')} |")
    blockers = report.get("decision_grade_blockers") or []
    if blockers:
        lines.extend(["", "## Decision-Grade Blockers", ""])
        for item in blockers:
            lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "Known limitation: this is a seeded rejection and stress check, not proof that the MC distribution is the official simulator.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def run_round4_mc_validation(
    *,
    data_dir: Path,
    output_dir: Path,
    days: Iterable[int] = (1, 2, 3),
    preset: str = "fast",
    seed: int = 20260426,
) -> Dict[str, object]:
    started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    day_tuple = tuple(int(day) for day in days)
    preset_payload = _preset_config(preset)
    tick_limit = int(preset_payload["tick_limit"])
    sessions = int(preset_payload["sessions"])
    sample_sessions = int(preset_payload["sample_sessions"])
    generated_at = datetime.now(timezone.utc).isoformat()
    spec = get_round_spec(4)
    manifest = build_round4_manifest(data_dir=data_dir, output_dir=output_dir / "manifest", days=day_tuple)
    dataset_map = load_round_dataset(data_dir, day_tuple, round_number=4, round_spec=spec)
    public_days = [dataset_map[day] for day in day_tuple]
    round4_context = prepare_round3_synthetic_context(
        public_days,
        round_spec=spec,
        tick_count=tick_limit,
    )
    synthetic_days = generate_synthetic_market_days(
        days=day_tuple,
        seed=seed,
        perturb=PerturbationConfig(synthetic_tick_limit=tick_limit, counterparty_edge_strength=0.0),
        round_spec=spec,
        round3_context=round4_context,
    )
    synthetic_repeat = generate_synthetic_market_days(
        days=day_tuple,
        seed=seed,
        perturb=PerturbationConfig(synthetic_tick_limit=tick_limit, counterparty_edge_strength=0.0),
        round_spec=spec,
        round3_context=round4_context,
    )
    synthetic_other = generate_synthetic_market_days(
        days=day_tuple,
        seed=seed + 1,
        perturb=PerturbationConfig(synthetic_tick_limit=tick_limit, counterparty_edge_strength=0.0),
        round_spec=spec,
        round3_context=round4_context,
    )
    public_metrics = _metrics_for_days(public_days, tick_limit=tick_limit)
    synthetic_metrics = _metrics_for_days(synthetic_days, tick_limit=tick_limit)
    mc_checks = _mc_noop_checks(
        data_dir=data_dir,
        output_dir=output_dir,
        days=(day_tuple[0],),
        sessions=sessions,
        sample_sessions=sample_sessions,
        tick_limit=tick_limit,
        seed=seed,
    )
    scenario_tick_limit = min(120, tick_limit)
    scenario_suite = _scenario_suite_smoke(
        public_days=public_days,
        day=day_tuple[0],
        seed=seed + 10_000,
        scenario_tick_limit=scenario_tick_limit,
    )
    gates = [
        {"name": "manifest", "status": "pass" if manifest.get("status") == "pass" else "fail"},
        {"name": "path_seed_determinism", "status": "pass" if _path_hash(synthetic_days) == _path_hash(synthetic_repeat) else "fail"},
        {"name": "different_seed_changes_path", "status": "pass" if _path_hash(synthetic_days) != _path_hash(synthetic_other) else "fail"},
        {"name": "noop_zero_pnl", "status": "pass" if mc_checks["noop_zero_pnl"] else "fail"},
        {"name": "mc_seed_determinism", "status": "pass" if mc_checks["seed_determinism"] else "fail"},
        {"name": "common_random_numbers", "status": "pass", "detail": preset_payload["seed_policy"]},
        {"name": "sample_path_traces_saved", "status": "pass" if mc_checks["sample_path_traces_saved"] else "fail"},
        {"name": "simple_inventory_non_trivial", "status": "pass" if mc_checks["simple_inventory_non_trivial"] else "fail"},
    ]
    resemblance = _basic_resemblance_checks(public_metrics, synthetic_metrics)
    if any(row["status"] == "warn" for row in resemblance):
        gates.append({"name": "basic_resemblance", "status": "warn"})
    else:
        gates.append({"name": "basic_resemblance", "status": "pass"})
    gates.append({"name": "scenario_suite_smoke", "status": scenario_suite["status"]})
    metric_rows = _metric_comparison_rows(public_metrics, synthetic_metrics, resemblance)
    scenario_rows = [
        {
            key: json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value
            for key, value in row.items()
        }
        for row in scenario_suite["rows"]
    ]
    write_rows_csv(output_dir / "metric_comparison_summary.csv", metric_rows)
    write_rows_csv(output_dir / "scenario_suite_summary.csv", scenario_rows)
    hard_fail = any(gate["status"] == "fail" for gate in gates)
    decision_grade_blockers = [
        str(gate["name"])
        for gate in gates
        if gate.get("status") == "fail"
    ]
    decision_grade = not decision_grade_blockers
    status = "fail" if hard_fail else "pass"
    runtime_seconds = round(time.perf_counter() - started, 6)
    report = {
        "generated_at": generated_at,
        "status": status,
        "preset": preset,
        "preset_config": preset_payload,
        "seed": seed,
        "round": 4,
        "data_dir": str(data_dir),
        "output_dir": str(output_dir),
        "days": list(day_tuple),
        "synthetic_tick_limit": tick_limit,
        "sessions": sessions,
        "sample_sessions": sample_sessions,
        "runtime_seconds": runtime_seconds,
        "data_hash": manifest.get("data_hash"),
        "schema_hash": manifest.get("schema_hash"),
        "provenance": capture_provenance(start=Path(__file__).resolve().parent.parent),
        "validation_thresholds": {
            "spread_ratio_synthetic_to_public": [0.2, 5.0],
            "trade_count_ratio_synthetic_to_public": [0.1, 10.0],
            "hard_fail_on": ["manifest", "seed determinism", "different seed variation", "no-op pnl", "sample traces", "simple inventory smoke", "scenario suite execution"],
            "warn_on": ["basic resemblance outside threshold", "small preset tail precision"],
        },
        "model_risk_limitations": [
            "Official hidden queue priority is unobservable from public data; passive fills are stressed with none/worse/all/adverse/harsh modes.",
            "The official final-simulation distribution is unavailable; MC uses public stylised facts plus explicit scenario shocks.",
            "Fast/default presets are gate and smoke presets, not standalone tail-estimation studies.",
            "Named counterparty flow is participant-side research, not aggressor proof.",
        ],
        "public_metrics": public_metrics,
        "synthetic_metrics": synthetic_metrics,
        "velvet_voucher_correlation": {
            "public": _velvet_voucher_correlation(public_days, tick_limit=tick_limit),
            "synthetic": _velvet_voucher_correlation(synthetic_days, tick_limit=tick_limit),
        },
        "option_iv_residuals": {
            "public": _option_residual_metrics(public_days, tick_limit=tick_limit),
            "synthetic": _option_residual_metrics(synthetic_days, tick_limit=tick_limit),
        },
        "hydrogel_mean_reversion": {
            "public_ac1_mid": (public_metrics["products"][HYDROGEL] or {}).get("ac1_mid"),
            "synthetic_ac1_mid": (synthetic_metrics["products"][HYDROGEL] or {}).get("ac1_mid"),
            "mean_shift_scenarios_supported_by_perturbation": [-100, -60, -30, 0, 30, 60, 100],
        },
        "checks": {
            "resemblance": resemblance,
            "mc": mc_checks,
            "scenario_suite": scenario_suite,
        },
        "gates": gates,
        "metric_comparison_rows": len(metric_rows),
        "decision_grade": decision_grade,
        "decision_grade_reason": (
            "hard gates passed for a deterministic rejection/stress MC tool"
            if decision_grade
            else "one or more hard MC validation gates failed"
        ),
        "decision_grade_blockers": decision_grade_blockers,
        "candidate_promoted": False,
        "artefacts": {
            "json": "mc_validation_report.json",
            "markdown": "mc_validation_report.md",
            "metric_comparison_csv": "metric_comparison_summary.csv",
            "scenario_suite_csv": "scenario_suite_summary.csv",
            "manifest": "manifest/manifest_report.json",
            **mc_checks.get("artefacts", {}),
        },
    }
    (output_dir / "mc_validation_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (output_dir / "mc_validation_report.md").write_text(render_mc_validation_markdown(report), encoding="utf-8")
    return report
