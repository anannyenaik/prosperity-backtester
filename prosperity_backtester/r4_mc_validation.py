from __future__ import annotations

import hashlib
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence

from .dataset import DayDataset, load_round_dataset
from .experiments import TraderSpec, run_monte_carlo
from .metadata import get_round_spec
from .platform import PerturbationConfig, generate_synthetic_market_days, summarise_monte_carlo_sessions
from .provenance import capture_provenance
from .r4_manifest import build_round4_manifest
from .round3 import black_scholes_call_price, implied_vol_bisection, parse_voucher_symbol, tte_years


UNDERLYING = "VELVETFRUIT_EXTRACT"
HYDROGEL = "HYDROGEL_PACK"
CENTRAL_VOUCHERS = ("VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500")
ALL_VOUCHERS = ("VEV_4000", "VEV_4500", *CENTRAL_VOUCHERS, "VEV_6000", "VEV_6500")


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
    return {
        "noop_summary": summarise_monte_carlo_sessions(noop_a),
        "noop_pnl_values": noop_pnl,
        "noop_zero_pnl": all(abs(value) <= 1e-9 for value in noop_pnl),
        "seed_determinism": [session.summary for session in noop_a] == [session.summary for session in noop_b],
        "simple_inventory_summary": summarise_monte_carlo_sessions(simple_runs),
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
    lines = [
        "# Round 4 MC Validation",
        "",
        f"- Generated at: `{report.get('generated_at')}`",
        f"- Preset: `{report.get('preset')}`",
        f"- Status: **{report.get('status')}**",
        f"- Seed: `{report.get('seed')}`",
        f"- Synthetic tick limit: `{report.get('synthetic_tick_limit')}`",
        "",
        "| Gate | Status |",
        "| --- | --- |",
    ]
    for gate in report.get("gates", []):
        lines.append(f"| {gate.get('name')} | {gate.get('status')} |")
    lines.extend(
        [
            "",
            "Known limitation: this is a resemblance and reproducibility check, not proof that the MC distribution is the official simulator.",
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
    output_dir.mkdir(parents=True, exist_ok=True)
    day_tuple = tuple(int(day) for day in days)
    fast = preset == "fast"
    tick_limit = 300 if fast else 1500
    sessions = 2 if fast else 8
    sample_sessions = 1 if fast else 2
    generated_at = datetime.now(timezone.utc).isoformat()
    spec = get_round_spec(4)
    manifest = build_round4_manifest(data_dir=data_dir, output_dir=output_dir / "manifest", days=day_tuple)
    dataset_map = load_round_dataset(data_dir, day_tuple, round_number=4, round_spec=spec)
    public_days = [dataset_map[day] for day in day_tuple]
    synthetic_days = generate_synthetic_market_days(
        days=day_tuple,
        seed=seed,
        perturb=PerturbationConfig(synthetic_tick_limit=tick_limit, counterparty_edge_strength=0.0),
        round_spec=spec,
        historical_market_days=public_days,
    )
    synthetic_repeat = generate_synthetic_market_days(
        days=day_tuple,
        seed=seed,
        perturb=PerturbationConfig(synthetic_tick_limit=tick_limit, counterparty_edge_strength=0.0),
        round_spec=spec,
        historical_market_days=public_days,
    )
    synthetic_other = generate_synthetic_market_days(
        days=day_tuple,
        seed=seed + 1,
        perturb=PerturbationConfig(synthetic_tick_limit=tick_limit, counterparty_edge_strength=0.0),
        round_spec=spec,
        historical_market_days=public_days,
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
    gates = [
        {"name": "manifest", "status": "pass" if manifest.get("status") == "pass" else "fail"},
        {"name": "path_seed_determinism", "status": "pass" if _path_hash(synthetic_days) == _path_hash(synthetic_repeat) else "fail"},
        {"name": "different_seed_changes_path", "status": "pass" if _path_hash(synthetic_days) != _path_hash(synthetic_other) else "fail"},
        {"name": "noop_zero_pnl", "status": "pass" if mc_checks["noop_zero_pnl"] else "fail"},
        {"name": "mc_seed_determinism", "status": "pass" if mc_checks["seed_determinism"] else "fail"},
    ]
    resemblance = _basic_resemblance_checks(public_metrics, synthetic_metrics)
    if any(row["status"] == "warn" for row in resemblance):
        gates.append({"name": "basic_resemblance", "status": "warn"})
    else:
        gates.append({"name": "basic_resemblance", "status": "pass"})
    status = "fail" if any(gate["status"] == "fail" for gate in gates) else ("warn" if any(gate["status"] == "warn" for gate in gates) else "pass")
    report = {
        "generated_at": generated_at,
        "status": status,
        "preset": preset,
        "seed": seed,
        "round": 4,
        "data_dir": str(data_dir),
        "output_dir": str(output_dir),
        "days": list(day_tuple),
        "synthetic_tick_limit": tick_limit,
        "sessions": sessions,
        "sample_sessions": sample_sessions,
        "data_hash": manifest.get("data_hash"),
        "provenance": capture_provenance(start=Path(__file__).resolve().parent.parent),
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
        },
        "gates": gates,
        "decision_grade": False,
        "decision_grade_reason": "MC validation is reproducible and checks resemblance, but official queue priority and full distributional equivalence remain unproven.",
        "candidate_promoted": False,
        "artefacts": {
            "json": "mc_validation_report.json",
            "markdown": "mc_validation_report.md",
            "manifest": "manifest/manifest_report.json",
            **mc_checks.get("artefacts", {}),
        },
    }
    (output_dir / "mc_validation_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (output_dir / "mc_validation_report.md").write_text(render_mc_validation_markdown(report), encoding="utf-8")
    return report
