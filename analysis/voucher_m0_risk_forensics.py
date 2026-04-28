"""Round 4 voucher M0 risk forensics and hardening matrix.

The default action runs the M0 forensic audit against the copied risk
candidate and writes compact artefacts under backtests/r4_voucher_m0_forensics.
Use --mode-matrix after the candidate has risk modes wired.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from prosperity_backtester.experiments import TraderSpec, run_replay
from prosperity_backtester.platform import PerturbationConfig
from prosperity_backtester.storage import OutputOptions


CANDIDATE = ROOT / "strategies" / "r4_voucher_risk_hardened_candidate.py"
ACTIVE = ROOT / "strategies" / "r4_hydro_velvet_m4_candidate.py"
DATA = ROOT / "data" / "round4"
OUT = ROOT / "backtests" / "r4_voucher_m0_forensics"

VOUCHERS = [
    "VEV_4000",
    "VEV_4500",
    "VEV_5000",
    "VEV_5100",
    "VEV_5200",
    "VEV_5300",
    "VEV_5400",
    "VEV_5500",
    "VEV_6000",
    "VEV_6500",
]
ANALYSED_VOUCHERS = VOUCHERS[:8]
STRIKES = {product: int(product.split("_")[1]) for product in VOUCHERS}
BUCKETS = {
    "deep": ["VEV_4000", "VEV_4500"],
    "central": ["VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300"],
    "upper": ["VEV_5400", "VEV_5500"],
    "far": ["VEV_6000", "VEV_6500"],
}
CENTRAL_STRIKES = [5000, 5100, 5200, 5300]


@dataclass
class RunResult:
    label: str
    mode: str
    fill_mode: str
    days: Tuple[int, ...]
    extras: Dict[str, object]
    total: float
    per_product: Dict[str, float]
    realised: Dict[str, float]
    final_pos: Dict[str, int]
    order_count: Dict[str, int]
    fill_count: Dict[str, int]
    markout5: Dict[str, Optional[float]]
    mean_abs_pos: Dict[str, float]
    time_near_cap: Dict[str, float]
    breaches: int
    day_splits: Dict[int, float]
    voucher_total: float
    central_total: float
    upper_total: float
    deep_total: float
    delta_summary: Dict[str, object]
    stress: Dict[str, object]


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_call_price(spot: float, strike: float, tte_years: float, sigma: float) -> float:
    if tte_years <= 0.0 or sigma <= 0.0:
        return max(0.0, spot - strike)
    vol_sqrt = sigma * math.sqrt(tte_years)
    if vol_sqrt <= 0.0:
        return max(0.0, spot - strike)
    d1 = (math.log(max(1e-12, spot / strike)) + 0.5 * sigma * sigma * tte_years) / vol_sqrt
    d2 = d1 - vol_sqrt
    return spot * _normal_cdf(d1) - strike * _normal_cdf(d2)


def _bs_call_delta(spot: float, strike: float, tte_years: float, sigma: float) -> float:
    if tte_years <= 0.0 or sigma <= 0.0:
        return 1.0 if spot > strike else 0.0
    vol_sqrt = sigma * math.sqrt(tte_years)
    if vol_sqrt <= 0.0:
        return 1.0 if spot > strike else 0.0
    d1 = (math.log(max(1e-12, spot / strike)) + 0.5 * sigma * sigma * tte_years) / vol_sqrt
    return _normal_cdf(d1)


def _implied_vol_call(price: float, spot: float, strike: float, tte_years: float) -> Optional[float]:
    intrinsic = max(0.0, spot - strike)
    if price < intrinsic - 1e-9 or price <= 0.0 or spot <= 0.0 or tte_years <= 0.0:
        return None
    lo, hi = 0.05, 1.0
    plo = _bs_call_price(spot, strike, tte_years, lo)
    phi = _bs_call_price(spot, strike, tte_years, hi)
    if price < plo - 1e-9 or price > phi + 1e-9:
        return None
    for _ in range(50):
        mid = (lo + hi) / 2.0
        pmid = _bs_call_price(spot, strike, tte_years, mid)
        if pmid < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _tte_days(day: int, timestamp: int) -> float:
    return max(0.5, (8.0 - float(day)) - float(timestamp) / 1_000_000.0)


def _quantile(values: Sequence[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    idx = (len(ordered) - 1) * q
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return ordered[int(idx)]
    weight = idx - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def _mean(values: Iterable[float]) -> Optional[float]:
    vals = list(values)
    return None if not vals else sum(vals) / len(vals)


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _perturbation(name: str) -> Tuple[str, PerturbationConfig]:
    if name == "base":
        return "base", PerturbationConfig()
    if name == "no_passive":
        return "base", PerturbationConfig(trade_matching_mode="none")
    if name == "worse":
        return "base", PerturbationConfig(trade_matching_mode="worse")
    if name == "adverse":
        return "low_fill_quality", PerturbationConfig(
            passive_fill_scale=0.7,
            missed_fill_additive=0.08,
            adverse_selection_ticks=1,
            slippage_multiplier=1.25,
        )
    if name == "harsh":
        return "low_fill_quality", PerturbationConfig(
            passive_fill_scale=0.5,
            missed_fill_additive=0.14,
            adverse_selection_ticks=1,
            slippage_multiplier=1.5,
            spread_shift_ticks=1,
        )
    raise ValueError(f"unknown fill mode: {name}")


def run_replay_result(
    *,
    label: str,
    mode: str = "M0_control",
    fill_mode: str = "base",
    days: Sequence[int] = (1, 2, 3),
    extras: Optional[Dict[str, object]] = None,
    trader_path: Path = CANDIDATE,
    full_metrics: bool = True,
) -> Tuple[object, RunResult]:
    fill_model, perturb = _perturbation(fill_mode)
    overrides: Dict[str, object] = {
        "VOUCHER_BS.initial_day_index": int(days[0]),
    }
    # M0_control is the default path. Avoid requiring VOUCHER_RISK to exist so
    # phase-1 forensics can run before any strategy-code edits.
    if mode and mode != "M0_control":
        overrides["VOUCHER_RISK.mode"] = mode
    if extras:
        overrides.update(extras)
    artefact = run_replay(
        trader_spec=TraderSpec(label, trader_path, overrides=overrides),
        days=list(days),
        data_dir=DATA,
        fill_model_name=fill_model,
        perturbation=perturb,
        output_dir=OUT / "_tmp",
        run_name=label,
        round_number=4,
        register=False,
        write_bundle=False,
        output_options=OutputOptions(),
    )
    summary = artefact.summary
    per_raw = summary.get("per_product", {})
    behaviour = (getattr(artefact, "behaviour", {}) or {}).get("per_product", {})
    per_product = {p: float(row.get("final_mtm", 0.0)) for p, row in per_raw.items()}
    realised = {p: float(row.get("realised", 0.0)) for p, row in per_raw.items()}
    final_pos = {p: int(row.get("final_position", 0)) for p, row in per_raw.items()}
    order_count = {p: int(behaviour.get(p, {}).get("order_count", 0) or 0) for p in per_raw}
    fill_count = {p: int(behaviour.get(p, {}).get("fill_count", 0) or 0) for p in per_raw}
    markout5 = {
        p: (
            None
            if behaviour.get(p, {}).get("average_fill_markout_5") is None
            else float(behaviour.get(p, {}).get("average_fill_markout_5"))
        )
        for p in per_raw
    }
    mean_abs_pos = {
        p: float(behaviour.get(p, {}).get("mean_abs_position_ratio", 0.0) or 0.0)
        * float(artefact.summary.get("position_limits", {}).get(p, 300) or 300)
        for p in per_raw
    }
    # Position limits are not included in summary on older bundles.
    for p in per_raw:
        limit = 200 if p in {"HYDROGEL_PACK", "VELVETFRUIT_EXTRACT"} else 300
        mean_abs_pos[p] = float(behaviour.get(p, {}).get("mean_abs_position_ratio", 0.0) or 0.0) * limit
    time_near_cap = {
        p: float(behaviour.get(p, {}).get("time_near_cap_ratio", 0.0) or 0.0)
        for p in per_raw
    }
    day_splits = {}
    for row in getattr(artefact, "session_rows", []) or []:
        day_splits[int(row["day"])] = float(row.get("final_pnl", 0.0) or 0.0)
    delta_summary = compute_delta_ledger(artefact)[0] if full_metrics else {}
    stress = compute_stress_summary(artefact) if full_metrics else {}
    result = RunResult(
        label=label,
        mode=mode,
        fill_mode=fill_mode,
        days=tuple(int(d) for d in days),
        extras=extras or {},
        total=float(summary.get("final_pnl", 0.0)),
        per_product=per_product,
        realised=realised,
        final_pos=final_pos,
        order_count=order_count,
        fill_count=fill_count,
        markout5=markout5,
        mean_abs_pos=mean_abs_pos,
        time_near_cap=time_near_cap,
        breaches=int(summary.get("limit_breaches", 0) or 0),
        day_splits=day_splits,
        voucher_total=sum(per_product.get(p, 0.0) for p in VOUCHERS),
        central_total=sum(per_product.get(p, 0.0) for p in BUCKETS["central"]),
        upper_total=sum(per_product.get(p, 0.0) for p in BUCKETS["upper"]),
        deep_total=sum(per_product.get(p, 0.0) for p in BUCKETS["deep"]),
        delta_summary=delta_summary,
        stress=stress,
    )
    return artefact, result


def _series_by_tick(artefact, products: Optional[set[str]] = None) -> Dict[Tuple[int, int], Dict[str, dict]]:
    grouped: Dict[Tuple[int, int], Dict[str, dict]] = {}
    for row in getattr(artefact, "fair_value_series", []) or []:
        product = str(row["product"])
        if products is not None and product not in products:
            continue
        key = (int(row["day"]), int(row["timestamp"]))
        grouped.setdefault(key, {})[product] = row
    return grouped


def _positions_by_tick(artefact, products: Optional[set[str]] = None) -> Dict[Tuple[int, int], Dict[str, int]]:
    grouped: Dict[Tuple[int, int], Dict[str, int]] = {}
    for row in getattr(artefact, "inventory_series", []) or []:
        product = str(row["product"])
        if products is not None and product not in products:
            continue
        key = (int(row["day"]), int(row["timestamp"]))
        grouped.setdefault(key, {})[product] = int(row.get("position", 0) or 0)
    return grouped


def compute_delta_ledger(artefact) -> Tuple[Dict[str, object], List[Dict[str, object]]]:
    products = set(ANALYSED_VOUCHERS + ["VELVETFRUIT_EXTRACT"])
    fair_by_tick = _series_by_tick(artefact, products)
    pos_by_tick = _positions_by_tick(artefact, products)
    rows: List[Dict[str, object]] = []
    sigma = 0.24
    tick_count = 0

    for key in sorted(fair_by_tick.keys()):
        day, ts = key
        fair_rows = fair_by_tick[key]
        spot_row = fair_rows.get("VELVETFRUIT_EXTRACT")
        if not spot_row:
            continue
        spot = float(spot_row.get("mid") or 0.0)
        if spot <= 0.0:
            continue
        tte_years = max(1e-6, _tte_days(day, ts) / 365.0)
        ivs: List[float] = []
        for strike in CENTRAL_STRIKES:
            row = fair_rows.get(f"VEV_{strike}")
            if not row:
                continue
            spread = row.get("spread")
            if spread is not None and float(spread) > 8.0:
                continue
            mid = float(row.get("mid") or 0.0)
            iv = _implied_vol_call(mid, spot, float(strike), tte_years)
            if iv is not None:
                ivs.append(iv)
        if len(ivs) >= 2:
            raw_sigma = sum(ivs) / len(ivs)
            alpha = 1.0 / float(tick_count + 1) if tick_count < 200 else 0.02
            sigma = (1.0 - alpha) * sigma + alpha * raw_sigma
        tick_count += 1

        positions = pos_by_tick.get(key, {})
        velvet_delta = float(positions.get("VELVETFRUIT_EXTRACT", 0))
        bucket_delta = {"deep": 0.0, "central": 0.0, "upper": 0.0}
        deltas_by_product: Dict[str, float] = {}
        for product in ANALYSED_VOUCHERS:
            strike = STRIKES[product]
            delta = _bs_call_delta(spot, float(strike), tte_years, sigma)
            pos = int(positions.get(product, 0))
            contribution = pos * delta
            deltas_by_product[product] = contribution
            for bucket, names in BUCKETS.items():
                if product in names and bucket in bucket_delta:
                    bucket_delta[bucket] += contribution
        net = velvet_delta + sum(bucket_delta.values())
        row = {
            "day": day,
            "timestamp": ts,
            "spot": spot,
            "sigma": sigma,
            "velvet_delta": velvet_delta,
            "deep_delta": bucket_delta["deep"],
            "central_delta": bucket_delta["central"],
            "upper_delta": bucket_delta["upper"],
            "net_delta": net,
        }
        for product, contribution in deltas_by_product.items():
            row[f"{product}_delta"] = contribution
        rows.append(row)

    def summarise(values: List[float]) -> Dict[str, Optional[float]]:
        return {
            "p05": _quantile(values, 0.05),
            "p50": _quantile(values, 0.50),
            "p95": _quantile(values, 0.95),
            "max_abs": max((abs(v) for v in values), default=None),
        }

    net_values = [float(row["net_delta"]) for row in rows]
    summary: Dict[str, object] = {"overall": summarise(net_values)}
    for day in sorted({int(row["day"]) for row in rows}):
        vals = [float(row["net_delta"]) for row in rows if int(row["day"]) == day]
        summary[f"day_{day}"] = summarise(vals)
    for bucket_key in ("deep_delta", "central_delta", "upper_delta", "velvet_delta"):
        vals = [float(row[bucket_key]) for row in rows]
        summary[bucket_key] = summarise(vals)
    return summary, rows


def compute_stress_summary(artefact) -> Dict[str, object]:
    products = set(ANALYSED_VOUCHERS + ["VELVETFRUIT_EXTRACT"])
    fair_by_tick = _series_by_tick(artefact, products)
    final_key = max(fair_by_tick.keys())
    final_rows = fair_by_tick[final_key]
    positions = {
        product: int(row.get("final_position", 0))
        for product, row in artefact.summary.get("per_product", {}).items()
    }
    spot = float(final_rows["VELVETFRUIT_EXTRACT"].get("mid") or 0.0)
    day, ts = final_key
    tte_years = max(1e-6, _tte_days(day, ts) / 365.0)

    sigma_inputs = []
    for strike in CENTRAL_STRIKES:
        row = final_rows.get(f"VEV_{strike}")
        if not row:
            continue
        iv = _implied_vol_call(float(row.get("mid") or 0.0), spot, float(strike), tte_years)
        if iv is not None:
            sigma_inputs.append(iv)
    sigma = sum(sigma_inputs) / len(sigma_inputs) if sigma_inputs else 0.24

    def voucher_value(sigma_value: float, spot_value: float = spot) -> float:
        total = 0.0
        for product in ANALYSED_VOUCHERS:
            total += positions.get(product, 0) * _bs_call_price(
                spot_value, float(STRIKES[product]), tte_years, sigma_value
            )
        return total

    base_voucher_value = voucher_value(sigma)
    iv_shift = {}
    for vol_pts in (-0.05, -0.02, 0.0, 0.02, 0.05):
        shifted_sigma = max(0.01, sigma + vol_pts)
        iv_shift[f"{vol_pts:+.2f}"] = voucher_value(shifted_sigma) - base_voucher_value

    underlying_shift = {}
    for shift in (-100.0, -50.0, 50.0, 100.0):
        voucher_change = voucher_value(sigma, spot + shift) - base_voucher_value
        velvet_change = positions.get("VELVETFRUIT_EXTRACT", 0) * shift
        underlying_shift[f"{shift:+.0f}"] = velvet_change + voucher_change

    adverse = {}
    for bucket, names in (("upper", BUCKETS["upper"]), ("deep", BUCKETS["deep"])):
        for shock in (1, 2, 5):
            adverse[f"{bucket}_{shock}"] = -sum(abs(positions.get(product, 0)) for product in names) * shock

    liquidation_half = 0.0
    liquidation_full = 0.0
    per_product_liq = {}
    for product in ANALYSED_VOUCHERS:
        row = final_rows.get(product)
        if not row:
            continue
        spread = float(row.get("spread") or 0.0)
        pos_abs = abs(positions.get(product, 0))
        half_cost = pos_abs * spread / 2.0
        full_cost = pos_abs * spread
        liquidation_half += half_cost
        liquidation_full += full_cost
        per_product_liq[product] = {"half_spread": half_cost, "full_spread": full_cost, "spread": spread}

    return {
        "method": "terminal inventory proxy, not a replay stress",
        "final_day": day,
        "final_timestamp": ts,
        "final_spot": spot,
        "final_sigma": sigma,
        "iv_shift_pnl": iv_shift,
        "underlying_shift_pnl": underlying_shift,
        "adverse_tick_pnl": adverse,
        "terminal_liquidation": {
            "voucher_half_spread_cost": liquidation_half,
            "voucher_full_spread_cost": liquidation_full,
            "per_product": per_product_liq,
        },
    }


def independent_day_attribution(mode: str = "M0_control") -> Dict[int, Dict[str, float]]:
    day_results: Dict[int, Dict[str, float]] = {}
    for day in (1, 2, 3):
        _artefact, result = run_replay_result(label=f"{mode}_day{day}", mode=mode, days=(day,))
        day_results[day] = dict(result.per_product)
    return day_results


def per_strike_attribution(artefact, result: RunResult, day_attr: Mapping[int, Mapping[str, float]]) -> List[Dict[str, object]]:
    _delta_summary, delta_rows = compute_delta_ledger(artefact)
    rows = []
    positions_by_product: Dict[str, List[Tuple[int, int, int]]] = {p: [] for p in VOUCHERS}
    for inv in getattr(artefact, "inventory_series", []) or []:
        product = str(inv["product"])
        if product in positions_by_product:
            positions_by_product[product].append((int(inv["day"]), int(inv["timestamp"]), int(inv.get("position", 0) or 0)))
    for product in VOUCHERS:
        pos_path = positions_by_product.get(product, [])
        total_ticks = max(1, len(pos_path))
        near_long = sum(1 for _d, _t, pos in pos_path if pos >= 290)
        near_short = sum(1 for _d, _t, pos in pos_path if pos <= -290)
        cap_ticks = near_long + near_short
        delta_vals = [float(row.get(f"{product}_delta", 0.0)) for row in delta_rows]
        rows.append({
            "product": product,
            "bucket": next((bucket for bucket, names in BUCKETS.items() if product in names), "unknown"),
            "total_pnl": result.per_product.get(product, 0.0),
            "realised_pnl": result.realised.get(product, 0.0),
            "mtm_pnl": result.per_product.get(product, 0.0) - result.realised.get(product, 0.0),
            "final_position": result.final_pos.get(product, 0),
            "mean_abs_position": result.mean_abs_pos.get(product, 0.0),
            "time_near_plus_300": near_long / total_ticks,
            "time_near_minus_300": near_short / total_ticks,
            "time_near_cap": cap_ticks / total_ticks,
            "order_count": result.order_count.get(product, 0),
            "fill_count": result.fill_count.get(product, 0),
            "markout5": result.markout5.get(product),
            "day1_independent_pnl": day_attr.get(1, {}).get(product, 0.0),
            "day2_independent_pnl": day_attr.get(2, {}).get(product, 0.0),
            "day3_independent_pnl": day_attr.get(3, {}).get(product, 0.0),
            "delta_p05": _quantile(delta_vals, 0.05),
            "delta_p50": _quantile(delta_vals, 0.50),
            "delta_p95": _quantile(delta_vals, 0.95),
            "delta_max_abs": max((abs(v) for v in delta_vals), default=0.0),
            "pnl_per_cap_time": None if cap_ticks == 0 else result.per_product.get(product, 0.0) / cap_ticks,
        })
    return rows


def lifecycle_rows(artefact, result: RunResult) -> List[Dict[str, object]]:
    rows = []
    fills_by_product: Dict[str, List[dict]] = {p: [] for p in VOUCHERS}
    for fill in getattr(artefact, "fills", []) or []:
        product = str(fill["product"])
        if product in fills_by_product:
            fills_by_product[product].append(fill)
    positions_by_product: Dict[str, List[Tuple[int, int, int]]] = {p: [] for p in VOUCHERS}
    for inv in getattr(artefact, "inventory_series", []) or []:
        product = str(inv["product"])
        if product in positions_by_product:
            positions_by_product[product].append((int(inv["day"]), int(inv["timestamp"]), int(inv.get("position", 0) or 0)))

    for product, path in positions_by_product.items():
        first_plus = next(((d, ts) for d, ts, pos in path if pos >= 290), None)
        first_minus = next(((d, ts) for d, ts, pos in path if pos <= -290), None)
        near_flags = [abs(pos) >= 290 for _d, _ts, pos in path]
        exits = sum(1 for prev, cur in zip(near_flags, near_flags[1:]) if prev and not cur)
        entries = sum(1 for prev, cur in zip(near_flags, near_flags[1:]) if not prev and cur)
        last_window = path[int(len(path) * 0.9):] if path else []
        terminal_near_share = (
            sum(1 for _d, _ts, pos in last_window if abs(pos) >= 290) / len(last_window)
            if last_window
            else 0.0
        )
        exit_fill_count = 0
        fill_qty = {"buy": 0, "sell": 0}
        for fill in fills_by_product.get(product, []):
            side = str(fill.get("side"))
            qty = int(fill.get("quantity", 0) or 0)
            fill_qty[side] = fill_qty.get(side, 0) + qty
            if side == "buy" and result.final_pos.get(product, 0) < 0:
                exit_fill_count += 1
            if side == "sell" and result.final_pos.get(product, 0) > 0:
                exit_fill_count += 1
        rows.append({
            "product": product,
            "first_plus_cap": None if first_plus is None else f"day{first_plus[0]}:{first_plus[1]}",
            "first_minus_cap": None if first_minus is None else f"day{first_minus[0]}:{first_minus[1]}",
            "near_cap_entries": entries,
            "near_cap_exits": exits,
            "near_cap_last_10pct": terminal_near_share,
            "final_position": result.final_pos.get(product, 0),
            "realised_pnl": result.realised.get(product, 0.0),
            "terminal_mtm_component": result.per_product.get(product, 0.0) - result.realised.get(product, 0.0),
            "buy_fill_qty": fill_qty.get("buy", 0),
            "sell_fill_qty": fill_qty.get("sell", 0),
            "exit_side_fill_count": exit_fill_count,
            "interpretation": (
                "terminal cap holding dominates"
                if terminal_near_share >= 0.8 and exits <= 3
                else "active inventory recycling present"
            ),
        })
    return rows


def fragility_rows(attr_rows: Sequence[Mapping[str, object]], stress: Mapping[str, object]) -> List[Dict[str, object]]:
    liquidation = stress.get("terminal_liquidation", {}).get("per_product", {})
    adverse = stress.get("adverse_tick_pnl", {})
    rows = []
    for row in attr_rows:
        product = str(row["product"])
        bucket = str(row["bucket"])
        if product in BUCKETS["upper"]:
            harsh = abs(float(adverse.get("upper_5", 0.0))) / max(1, len(BUCKETS["upper"]))
        elif product in BUCKETS["deep"]:
            harsh = abs(float(adverse.get("deep_5", 0.0))) / max(1, len(BUCKETS["deep"]))
        else:
            harsh = 0.0
        liq = float(liquidation.get(product, {}).get("full_spread", 0.0)) if isinstance(liquidation, dict) else 0.0
        pnl = float(row.get("total_pnl", 0.0) or 0.0)
        cap = float(row.get("time_near_cap", 0.0) or 0.0)
        stress_risk = harsh + liq
        rows.append({
            "product": product,
            "bucket": bucket,
            "public_pnl": pnl,
            "stress_risk_proxy": stress_risk,
            "time_near_cap": cap,
            "pnl_per_cap_time": row.get("pnl_per_cap_time"),
            "control_priority": (
                "test hardening"
                if bucket == "upper" and cap > 0.2
                else "do not shrink without stronger evidence"
            ),
        })
    return sorted(rows, key=lambda r: (float(r["stress_risk_proxy"]), float(r["time_near_cap"])), reverse=True)


def result_row(result: RunResult) -> Dict[str, object]:
    row: Dict[str, object] = {
        "label": result.label,
        "mode": result.mode,
        "fill_mode": result.fill_mode,
        "days": " ".join(str(d) for d in result.days),
        "extras": json.dumps(result.extras, sort_keys=True),
        "total": result.total,
        "voucher_total": result.voucher_total,
        "deep_total": result.deep_total,
        "central_total": result.central_total,
        "upper_total": result.upper_total,
        "HYDROGEL_PACK": result.per_product.get("HYDROGEL_PACK", 0.0),
        "VELVETFRUIT_EXTRACT": result.per_product.get("VELVETFRUIT_EXTRACT", 0.0),
        "breaches": result.breaches,
        "net_delta_p50": result.delta_summary.get("overall", {}).get("p50"),
        "net_delta_p95": result.delta_summary.get("overall", {}).get("p95"),
        "net_delta_max_abs": result.delta_summary.get("overall", {}).get("max_abs"),
        "terminal_liq_full": result.stress.get("terminal_liquidation", {}).get("voucher_full_spread_cost"),
    }
    for product in VOUCHERS:
        row[f"pnl_{product}"] = result.per_product.get(product, 0.0)
        row[f"pos_{product}"] = result.final_pos.get(product, 0)
        row[f"near_cap_{product}"] = result.time_near_cap.get(product, 0.0)
    for day, pnl in result.day_splits.items():
        row[f"cumulative_day{day}"] = pnl
    return row


def run_m0_forensics() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    artefact, result = run_replay_result(label="M0_control", mode="M0_control")
    day_attr = independent_day_attribution("M0_control")
    attr = per_strike_attribution(artefact, result, day_attr)
    lifecycle = lifecycle_rows(artefact, result)
    delta_summary, delta_rows = compute_delta_ledger(artefact)
    stress = compute_stress_summary(artefact)
    fragility = fragility_rows(attr, stress)

    _write_csv(OUT / "m0_per_strike_attribution.csv", attr)
    _write_csv(OUT / "m0_position_lifecycle.csv", lifecycle)
    _write_csv(OUT / "m0_delta_ledger.csv", delta_rows)
    _write_csv(OUT / "m0_fragility_ranking.csv", fragility)
    _write_json(OUT / "m0_delta_summary.json", delta_summary)
    _write_json(OUT / "m0_stress_summary.json", stress)
    _write_json(OUT / "m0_independent_day_attribution.json", day_attr)
    _write_json(OUT / "m0_summary.json", {
        "total": result.total,
        "voucher_total": result.voucher_total,
        "deep_total": result.deep_total,
        "central_total": result.central_total,
        "upper_total": result.upper_total,
        "breaches": result.breaches,
        "final_positions": result.final_pos,
        "delta_summary": delta_summary,
        "stress": stress,
    })

    lines = [
        "# Voucher M0 Risk Forensics",
        "",
        f"- Total PnL: {result.total:,.0f}",
        f"- Voucher PnL: {result.voucher_total:,.0f}",
        f"- Deep / central / upper: {result.deep_total:,.0f} / {result.central_total:,.0f} / {result.upper_total:,.0f}",
        f"- Breaches: {result.breaches}",
        f"- Net delta p05/p50/p95/max_abs: "
        f"{delta_summary['overall']['p05']:.1f} / {delta_summary['overall']['p50']:.1f} / "
        f"{delta_summary['overall']['p95']:.1f} / {delta_summary['overall']['max_abs']:.1f}",
        "",
        "Stress figures are terminal inventory proxies, not replay stresses.",
        "",
        "Top fragility rows:",
    ]
    for row in fragility[:5]:
        lines.append(
            f"- {row['product']}: pnl={float(row['public_pnl']):,.0f}, "
            f"risk_proxy={float(row['stress_risk_proxy']):,.0f}, cap_time={float(row['time_near_cap']):.2f}, "
            f"{row['control_priority']}"
        )
    (OUT / "m0_forensics.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"M0 forensics written to {OUT}")
    print(f"total={result.total:.2f} voucher={result.voucher_total:.2f} breaches={result.breaches}")


def mode_specs() -> List[Tuple[str, str, Dict[str, object]]]:
    return [
        ("M0_control", "M0_control", {}),
        ("M1_diagnostics_only", "M1_diagnostics_only", {}),
        ("M2_upper_long_cap_250", "M2_upper_long_cap_250", {}),
        ("M3_upper_long_cap_200", "M3_upper_long_cap_200", {}),
        ("M4_5400_only_cap_250", "M4_5400_only_cap", {"VOUCHER_RISK.upper_long_cap": 250}),
        ("M4_5400_only_cap_200", "M4_5400_only_cap", {"VOUCHER_RISK.upper_long_cap": 200}),
        ("M5_5500_only_cap_250", "M5_5500_only_cap", {"VOUCHER_RISK.upper_long_cap": 250}),
        ("M5_5500_only_cap_200", "M5_5500_only_cap", {"VOUCHER_RISK.upper_long_cap": 200}),
        ("M6_terminal_upper_reduction_075", "M6_terminal_upper_reduction", {"VOUCHER_RISK.terminal_fraction": 0.75}),
        ("M6_terminal_upper_reduction_085", "M6_terminal_upper_reduction", {"VOUCHER_RISK.terminal_fraction": 0.85}),
        ("M6_terminal_upper_reduction_090", "M6_terminal_upper_reduction", {"VOUCHER_RISK.terminal_fraction": 0.90}),
        ("M7_extreme_BS_veto_upper_4", "M7_extreme_BS_veto_upper", {"VOUCHER_RISK.bs_veto_edge": 4.0}),
        ("M7_extreme_BS_veto_upper_8", "M7_extreme_BS_veto_upper", {"VOUCHER_RISK.bs_veto_edge": 8.0}),
        ("M7_extreme_BS_veto_upper_12", "M7_extreme_BS_veto_upper", {"VOUCHER_RISK.bs_veto_edge": 12.0}),
        ("M8_extreme_BS_veto_all_8", "M8_extreme_BS_veto_all", {"VOUCHER_RISK.bs_veto_edge": 8.0}),
        ("M9_net_delta_soft_cap_700", "M9_net_delta_soft_cap", {"VOUCHER_RISK.net_delta_cap": 700}),
        ("M9_net_delta_soft_cap_900", "M9_net_delta_soft_cap", {"VOUCHER_RISK.net_delta_cap": 900}),
        ("M9_net_delta_soft_cap_1100", "M9_net_delta_soft_cap", {"VOUCHER_RISK.net_delta_cap": 1100}),
        ("M9_net_delta_soft_cap_1300", "M9_net_delta_soft_cap", {"VOUCHER_RISK.net_delta_cap": 1300}),
    ]


def run_mode_matrix() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    results: List[RunResult] = []
    print("Running pooled base mode matrix")
    for label, mode, extras in mode_specs():
        _artefact, result = run_replay_result(label=label, mode=mode, extras=extras)
        results.append(result)
        print(f"{label:36s} total={result.total:,.0f} vouchers={result.voucher_total:,.0f} upper={result.upper_total:,.0f}")

    _write_csv(OUT / "mode_matrix_base.csv", [result_row(result) for result in results])

    serious_labels = [
        "M0_control",
        "M1_diagnostics_only",
        "M2_upper_long_cap_250",
        "M3_upper_long_cap_200",
        "M7_extreme_BS_veto_upper_8",
        "M9_net_delta_soft_cap_1300",
    ]
    serious_specs = [spec for spec in mode_specs() if spec[0] in serious_labels]

    split_results: List[RunResult] = []
    print("Running independent day splits")
    for label, mode, extras in serious_specs:
        for day in (1, 2, 3):
            _artefact, result = run_replay_result(
                label=f"{label}_day{day}",
                mode=mode,
                days=(day,),
                extras=extras,
            )
            split_results.append(result)
            print(f"{label:36s} day={day} total={result.total:,.0f}")
    _write_csv(OUT / "mode_matrix_day_splits.csv", [result_row(result) for result in split_results])

    fill_results: List[RunResult] = []
    print("Running fill stress")
    for label, mode, extras in serious_specs:
        for fill_mode in ("base", "no_passive", "worse", "adverse", "harsh"):
            _artefact, result = run_replay_result(
                label=f"{label}_{fill_mode}",
                mode=mode,
                fill_mode=fill_mode,
                extras=extras,
            )
            fill_results.append(result)
            print(f"{label:36s} fill={fill_mode:10s} total={result.total:,.0f} vouchers={result.voucher_total:,.0f}")
    _write_csv(OUT / "mode_matrix_fill_stress.csv", [result_row(result) for result in fill_results])

    _write_json(OUT / "mode_matrix_summary.json", {
        "base": [result_row(result) for result in results],
        "day_splits": [result_row(result) for result in split_results],
        "fill_stress": [result_row(result) for result in fill_results],
    })


def run_focused_validation() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    focused_specs = [
        ("M0_control", "M0_control", {}),
        ("M2_upper_long_cap_250", "M2_upper_long_cap_250", {}),
        ("M3_upper_long_cap_200", "M3_upper_long_cap_200", {}),
        ("M4_5400_only_cap_250", "M4_5400_only_cap", {"VOUCHER_RISK.upper_long_cap": 250}),
        ("M5_5500_only_cap_250", "M5_5500_only_cap", {"VOUCHER_RISK.upper_long_cap": 250}),
    ]

    split_results: List[RunResult] = []
    print("Running focused day splits")
    for label, mode, extras in focused_specs:
        for day in (1, 2, 3):
            _artefact, result = run_replay_result(
                label=f"{label}_day{day}",
                mode=mode,
                days=(day,),
                extras=extras,
                full_metrics=False,
            )
            split_results.append(result)
            print(f"{label:30s} day={day} total={result.total:,.0f} vouchers={result.voucher_total:,.0f}")
    _write_csv(OUT / "focused_day_splits.csv", [result_row(result) for result in split_results])

    fill_results: List[RunResult] = []
    print("Running focused fill stress")
    for label, mode, extras in focused_specs:
        for fill_mode in ("base", "no_passive", "worse", "adverse", "harsh"):
            _artefact, result = run_replay_result(
                label=f"{label}_{fill_mode}",
                mode=mode,
                fill_mode=fill_mode,
                extras=extras,
                full_metrics=False,
            )
            fill_results.append(result)
            print(f"{label:30s} fill={fill_mode:10s} total={result.total:,.0f} vouchers={result.voucher_total:,.0f}")
    _write_csv(OUT / "focused_fill_stress.csv", [result_row(result) for result in fill_results])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode-matrix", action="store_true", help="Run hardening mode matrix after modes are implemented")
    parser.add_argument("--focused-validation", action="store_true", help="Run quick day/fill validation for plausible hardening modes")
    parser.add_argument("--forensics-only", action="store_true", help="Only run M0 forensics")
    args = parser.parse_args()
    if args.focused_validation:
        run_focused_validation()
    elif args.mode_matrix:
        run_mode_matrix()
    else:
        run_m0_forensics()


if __name__ == "__main__":
    main()
