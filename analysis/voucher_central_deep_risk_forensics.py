"""Round 4 voucher central/deep cap-exposure forensic risk pass.

Builds on top of voucher_m0_risk_forensics. Reuses run_replay_result so the
active candidate (strategies/r4_voucher_risk_hardened_candidate.py, default
mode M3_upper_long_cap_200) is the only baseline.

Adds analyses that are NOT in m0/m3 artefacts:
  P1. Multi-delta net-delta diagnostics (BS, empirical proxy, conservative
      bucket proxy). Reports model-stability of net-delta conclusions.
  P2. Cap-entry lifecycle forward-move analysis per central/deep strike.
      For each entry into |pos| >= 290, measure forward VELVET mid move at
      +10/+50/+100/+500 ticks plus voucher mid move and a directional sign.
  P3. Marginal-add attribution. Counts fills made while |pos| >= 250 and the
      sign of the marginal exposure they create. Reports which strikes do
      most of their adding past 250 (i.e. live in the tail).
  P4. Extended terminal stress matrix - VELVET shocks +/-50/100/150,
      IV shocks +/-3/5/8 vol pts, combined adverse (+100/+5, -100/-5),
      lower-TTE proxy.
  P5. Day attribution stability - per-day per-strike PnL / cap-time / ratio.

This script does NOT modify any strategy file. It only writes artefacts to
backtests/r4_voucher_central_deep_risk_forensics/.

Run:  python -m analysis.voucher_central_deep_risk_forensics
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

from analysis.voucher_m0_risk_forensics import (
    ANALYSED_VOUCHERS,
    BUCKETS,
    CANDIDATE,
    CENTRAL_STRIKES,
    STRIKES,
    VOUCHERS,
    _bs_call_delta,
    _bs_call_price,
    _implied_vol_call,
    _quantile,
    _tte_days,
    _write_csv,
    _write_json,
    compute_delta_ledger,
    run_replay_result,
)

DATA = ROOT / "data" / "round4"
OUT = ROOT / "backtests" / "r4_voucher_central_deep_risk_forensics"

CENTRAL_DEEP_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300]
CENTRAL_DEEP_VOUCHERS = [f"VEV_{k}" for k in CENTRAL_DEEP_STRIKES]
UPPER_VOUCHERS = ["VEV_5400", "VEV_5500"]
UNDERLYING = "VELVETFRUIT_EXTRACT"

# Conservative bucket proxy. Deep strikes are not delta 1.0 even when the call
# is far ITM in the public sample because (i) the BS smile is flat-ish at IV
# ~0.24 with TTE 5-7 days and (ii) realised hedge-PnL evidence in earlier
# voucher_bs research suggested an effective proxy of ~0.73 for deep ITM.
# Central is left to BS, upper is left to BS (already small).
CONSERVATIVE_DEEP_DELTA = 0.73


# -----------------------------------------------------------------------------
# Phase P1. Multi-delta net-delta.
def _empirical_delta_per_strike_day(
    *,
    days: Sequence[int] = (1, 2, 3),
    horizon: int = 50,
    spread_max: float = 8.0,
    velvet_min_move: float = 1.0,
) -> Dict[int, Dict[int, Dict[str, float]]]:
    """Robust empirical delta: for each (day, strike), regress (voucher mid
    move) on (VELVET mid move) over a fixed lookahead horizon, using a clipped
    median ratio to be robust to outliers. Returns slope and confidence stats.

    We use median of (dC / dS) across windows where |dS| > velvet_min_move and
    voucher spread <= spread_max. The median is more robust than OLS for the
    voucher tape (lots of zero or 1-tick voucher noise around larger VELVET
    moves).
    """
    results: Dict[int, Dict[int, Dict[str, float]]] = {}
    for day in days:
        path = DATA / f"prices_round_4_day_{day}.csv"
        if not path.exists():
            continue
        # Load tick frames per timestamp.
        snaps_by_ts: Dict[int, Dict[str, Tuple[Optional[float], Optional[float], Optional[float]]]] = {}
        with path.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter=";")
            for row in reader:
                try:
                    ts = int(row["timestamp"])
                except (ValueError, KeyError, TypeError):
                    continue
                product = row.get("product", "")
                try:
                    bid = float(row["bid_price_1"]) if row.get("bid_price_1") else None
                except (ValueError, TypeError):
                    bid = None
                try:
                    ask = float(row["ask_price_1"]) if row.get("ask_price_1") else None
                except (ValueError, TypeError):
                    ask = None
                try:
                    mid = float(row["mid_price"]) if row.get("mid_price") else None
                except (ValueError, TypeError):
                    mid = None
                if mid is None and bid is not None and ask is not None:
                    mid = 0.5 * (bid + ask)
                snaps_by_ts.setdefault(ts, {})[product] = (bid, ask, mid)
        ordered_ts = sorted(snaps_by_ts.keys())
        # Build VELVET mid path.
        velvet_path: List[Tuple[int, float]] = []
        for ts in ordered_ts:
            entry = snaps_by_ts[ts].get(UNDERLYING)
            if entry and entry[2] is not None:
                velvet_path.append((ts, float(entry[2])))
        velvet_idx = {ts: i for i, (ts, _) in enumerate(velvet_path)}
        per_strike: Dict[int, Dict[str, float]] = {}
        for K in CENTRAL_DEEP_STRIKES + [5400, 5500]:
            voucher_key = f"VEV_{K}"
            slopes: List[float] = []
            n_used = 0
            for ts_now, mid_now in velvet_path:
                # Build voucher mid at ts_now and ts_future.
                v_now = snaps_by_ts[ts_now].get(voucher_key)
                if v_now is None or v_now[2] is None:
                    continue
                if v_now[0] is not None and v_now[1] is not None and (v_now[1] - v_now[0]) > spread_max:
                    continue
                # Future tick by index
                idx = velvet_idx.get(ts_now, -1)
                if idx < 0 or (idx + horizon) >= len(velvet_path):
                    continue
                ts_fut, mid_fut = velvet_path[idx + horizon]
                v_fut = snaps_by_ts[ts_fut].get(voucher_key)
                if v_fut is None or v_fut[2] is None:
                    continue
                dS = mid_fut - mid_now
                if abs(dS) < velvet_min_move:
                    continue
                dC = v_fut[2] - v_now[2]
                slopes.append(dC / dS)
                n_used += 1
            if not slopes:
                per_strike[K] = {"n": 0, "median_slope": float("nan"), "p25": float("nan"), "p75": float("nan")}
                continue
            slopes_clipped = [max(-2.0, min(2.0, s)) for s in slopes]
            slopes_sorted = sorted(slopes_clipped)
            per_strike[K] = {
                "n": n_used,
                "median_slope": _quantile(slopes_sorted, 0.5),
                "p25": _quantile(slopes_sorted, 0.25),
                "p75": _quantile(slopes_sorted, 0.75),
                "mean_slope": statistics.fmean(slopes_clipped),
            }
        results[day] = per_strike
    return results


def _model_aggregate_empirical(empirical: Mapping[int, Mapping[int, Mapping[str, float]]]) -> Dict[int, float]:
    """Pool empirical slopes per strike across days into one effective delta."""
    pooled: Dict[int, float] = {}
    for K in CENTRAL_DEEP_STRIKES + [5400, 5500]:
        vals = []
        for day in empirical:
            entry = empirical[day].get(K, {})
            slope = entry.get("median_slope")
            if slope is not None and not (isinstance(slope, float) and math.isnan(slope)):
                vals.append(float(slope))
        if not vals:
            pooled[K] = 0.0
        else:
            pooled[K] = statistics.fmean(vals)
    return pooled


def compute_multi_delta_ledger(
    artefact,
    empirical_pooled: Mapping[int, float],
) -> Dict[str, object]:
    """Compute net delta under three models and return summaries + per-tick rows.

    Returns:
        {
          "BS": {summary},
          "EMPIRICAL": {summary},
          "CONSERVATIVE": {summary},
          "rows": [...],
        }
    """
    summary_BS, rows_BS = compute_delta_ledger(artefact)
    # Build positions+spot lookup keyed by (day, ts).
    fair_by_tick: Dict[Tuple[int, int], Dict[str, dict]] = {}
    for row in getattr(artefact, "fair_value_series", []) or []:
        product = str(row["product"])
        if product == UNDERLYING or product in ANALYSED_VOUCHERS:
            key = (int(row["day"]), int(row["timestamp"]))
            fair_by_tick.setdefault(key, {})[product] = row
    pos_by_tick: Dict[Tuple[int, int], Dict[str, int]] = {}
    for row in getattr(artefact, "inventory_series", []) or []:
        product = str(row["product"])
        if product == UNDERLYING or product in ANALYSED_VOUCHERS:
            key = (int(row["day"]), int(row["timestamp"]))
            pos_by_tick.setdefault(key, {})[product] = int(row.get("position", 0) or 0)

    rows_emp: List[float] = []
    rows_cons: List[float] = []
    rows_per_tick: List[Dict[str, object]] = []
    bs_lookup = {(int(r["day"]), int(r["timestamp"])): r for r in rows_BS}
    for key in sorted(fair_by_tick.keys()):
        day, ts = key
        bs_row = bs_lookup.get(key)
        if not bs_row:
            continue
        velvet_pos = float(bs_row.get("velvet_delta", 0.0))
        # Empirical net delta = velvet + sum(pos[k] * empirical_pooled[k])
        emp_net = velvet_pos
        cons_net = velvet_pos
        positions = pos_by_tick.get(key, {})
        for product in ANALYSED_VOUCHERS:
            K = STRIKES[product]
            pos = int(positions.get(product, 0))
            emp_delta = empirical_pooled.get(K, 0.0) or 0.0
            emp_net += pos * emp_delta
            if product in BUCKETS["deep"]:
                cons_net += pos * CONSERVATIVE_DEEP_DELTA
            else:
                cons_net += float(bs_row.get(f"{product}_delta", 0.0))
        rows_emp.append(emp_net)
        rows_cons.append(cons_net)
        rows_per_tick.append({
            "day": day,
            "timestamp": ts,
            "BS_net": float(bs_row.get("net_delta", 0.0)),
            "EMPIRICAL_net": emp_net,
            "CONSERVATIVE_net": cons_net,
            "deep_delta_bs": float(bs_row.get("deep_delta", 0.0)),
            "central_delta_bs": float(bs_row.get("central_delta", 0.0)),
            "upper_delta_bs": float(bs_row.get("upper_delta", 0.0)),
            "velvet_delta": velvet_pos,
        })

    def summarise(values: Sequence[float]) -> Dict[str, Optional[float]]:
        if not values:
            return {"p05": None, "p50": None, "p95": None, "p99": None, "max_abs": None}
        return {
            "p05": _quantile(values, 0.05),
            "p50": _quantile(values, 0.50),
            "p95": _quantile(values, 0.95),
            "p99": _quantile(values, 0.99),
            "max_abs": max(abs(v) for v in values),
        }

    return {
        "BS": summary_BS["overall"],
        "EMPIRICAL": summarise(rows_emp),
        "CONSERVATIVE": summarise(rows_cons),
        "BS_buckets": {
            "deep": summary_BS.get("deep_delta"),
            "central": summary_BS.get("central_delta"),
            "upper": summary_BS.get("upper_delta"),
            "velvet": summary_BS.get("velvet_delta"),
        },
        "rows": rows_per_tick,
    }


# -----------------------------------------------------------------------------
# Phase P2. Cap-entry forward-move analysis.
def cap_entry_forward_moves(
    artefact,
    *,
    cap_threshold: int = 290,
    horizons: Sequence[int] = (10, 50, 100, 500),
) -> List[Dict[str, object]]:
    """For each cap-entry in central/deep+upper strikes, record forward
    VELVET mid move and forward voucher mid move at given horizons.

    A cap-entry event is a tick where |pos| crossed from < threshold to >=
    threshold. Position direction sign is captured. Forward windows skip if
    they would cross day boundary (we restrict to within-day forward).
    """
    inv_by_product: Dict[str, List[Tuple[int, int, int]]] = {p: [] for p in ANALYSED_VOUCHERS}
    fair_by_product_day: Dict[Tuple[str, int], List[Tuple[int, float]]] = {}
    velvet_by_day: Dict[int, List[Tuple[int, float]]] = {}
    for row in getattr(artefact, "inventory_series", []) or []:
        product = str(row["product"])
        if product in inv_by_product:
            inv_by_product[product].append((int(row["day"]), int(row["timestamp"]), int(row.get("position", 0) or 0)))
    for row in getattr(artefact, "fair_value_series", []) or []:
        product = str(row["product"])
        day = int(row["day"])
        ts = int(row["timestamp"])
        mid = row.get("mid")
        if mid is None:
            continue
        try:
            mid_f = float(mid)
        except (ValueError, TypeError):
            continue
        if product == UNDERLYING:
            velvet_by_day.setdefault(day, []).append((ts, mid_f))
        elif product in ANALYSED_VOUCHERS:
            fair_by_product_day.setdefault((product, day), []).append((ts, mid_f))

    # Build sorted index per series for binary search.
    velvet_idx = {day: {ts: i for i, (ts, _) in enumerate(sorted(seq))} for day, seq in velvet_by_day.items()}
    velvet_sorted = {day: sorted(seq) for day, seq in velvet_by_day.items()}
    fair_idx: Dict[Tuple[str, int], Dict[int, int]] = {}
    fair_sorted: Dict[Tuple[str, int], List[Tuple[int, float]]] = {}
    for key, seq in fair_by_product_day.items():
        seq_sorted = sorted(seq)
        fair_sorted[key] = seq_sorted
        fair_idx[key] = {ts: i for i, (ts, _) in enumerate(seq_sorted)}

    rows: List[Dict[str, object]] = []
    for product in ANALYSED_VOUCHERS:
        path = sorted(inv_by_product[product])
        prev_pos = 0
        prev_day = None
        for day, ts, pos in path:
            if prev_day is not None and prev_day != day:
                prev_pos = 0
            entered_long = (abs(pos) >= cap_threshold) and (abs(prev_pos) < cap_threshold) and pos > 0
            entered_short = (abs(pos) >= cap_threshold) and (abs(prev_pos) < cap_threshold) and pos < 0
            if entered_long or entered_short:
                side = "long" if entered_long else "short"
                v_now = None
                v_seq = velvet_sorted.get(day, [])
                v_idx_map = velvet_idx.get(day, {})
                v_now_i = v_idx_map.get(ts)
                if v_now_i is not None:
                    v_now = v_seq[v_now_i][1]
                voucher_seq = fair_sorted.get((product, day), [])
                voucher_idx_map = fair_idx.get((product, day), {})
                vc_now_i = voucher_idx_map.get(ts)
                vc_now = voucher_seq[vc_now_i][1] if vc_now_i is not None else None
                row: Dict[str, object] = {
                    "product": product,
                    "bucket": next((b for b, names in BUCKETS.items() if product in names), "unknown"),
                    "day": day,
                    "timestamp": ts,
                    "side": side,
                    "position": pos,
                    "velvet_at_entry": v_now,
                    "voucher_at_entry": vc_now,
                }
                for h in horizons:
                    fwd_v = None
                    fwd_vc = None
                    if v_now_i is not None and (v_now_i + h) < len(v_seq):
                        fwd_v_pair = v_seq[v_now_i + h]
                        fwd_v = fwd_v_pair[1]
                    if vc_now_i is not None and (vc_now_i + h) < len(voucher_seq):
                        fwd_vc_pair = voucher_seq[vc_now_i + h]
                        fwd_vc = fwd_vc_pair[1]
                    if v_now is not None and fwd_v is not None:
                        row[f"velvet_move_{h}"] = fwd_v - v_now
                        # Sign-aware: positive value = move that was UNFAVOURABLE
                        # for the held position (i.e. for short call, +VELVET hurts).
                        unfav = (fwd_v - v_now) if pos < 0 else -(fwd_v - v_now)
                        row[f"unfavourable_move_{h}"] = unfav
                    else:
                        row[f"velvet_move_{h}"] = None
                        row[f"unfavourable_move_{h}"] = None
                    if vc_now is not None and fwd_vc is not None:
                        row[f"voucher_move_{h}"] = fwd_vc - vc_now
                    else:
                        row[f"voucher_move_{h}"] = None
                rows.append(row)
            prev_pos = pos
            prev_day = day
    return rows


def cap_entry_forward_summary(rows: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    """Aggregate cap-entry forward moves by (product, side)."""
    grouped: Dict[Tuple[str, str], List[Mapping[str, object]]] = {}
    for r in rows:
        grouped.setdefault((str(r["product"]), str(r["side"])), []).append(r)
    out: List[Dict[str, object]] = []
    for (product, side), records in grouped.items():
        n = len(records)
        summary: Dict[str, object] = {
            "product": product,
            "bucket": next((b for b, names in BUCKETS.items() if product in names), "unknown"),
            "side": side,
            "n_events": n,
        }
        for h in (10, 50, 100, 500):
            unfav = [float(r.get(f"unfavourable_move_{h}", 0.0) or 0.0) for r in records if r.get(f"unfavourable_move_{h}") is not None]
            voucher_mv = [float(r.get(f"voucher_move_{h}", 0.0) or 0.0) for r in records if r.get(f"voucher_move_{h}") is not None]
            if unfav:
                summary[f"mean_unfav_move_{h}"] = statistics.fmean(unfav)
                summary[f"median_unfav_move_{h}"] = _quantile(unfav, 0.5)
                summary[f"p75_unfav_move_{h}"] = _quantile(unfav, 0.75)
            else:
                summary[f"mean_unfav_move_{h}"] = None
                summary[f"median_unfav_move_{h}"] = None
                summary[f"p75_unfav_move_{h}"] = None
            if voucher_mv:
                summary[f"mean_voucher_move_{h}"] = statistics.fmean(voucher_mv)
            else:
                summary[f"mean_voucher_move_{h}"] = None
        out.append(summary)
    return sorted(out, key=lambda r: (r["product"], r["side"]))


# -----------------------------------------------------------------------------
# Phase P3. Marginal-add attribution.
def marginal_add_attribution(
    artefact,
    *,
    near_cap_threshold: int = 250,
) -> Dict[str, object]:
    """Walk inventory_series + fills jointly. For each fill, classify whether
    pos right BEFORE the fill was already |pos| >= near_cap_threshold and
    whether the fill increased or reduced |pos|. Report counts and lot sums.
    """
    inv_by_product_day: Dict[Tuple[str, int], List[Tuple[int, int]]] = {}
    for row in getattr(artefact, "inventory_series", []) or []:
        product = str(row["product"])
        if product not in ANALYSED_VOUCHERS:
            continue
        key = (product, int(row["day"]))
        inv_by_product_day.setdefault(key, []).append((int(row["timestamp"]), int(row.get("position", 0) or 0)))
    fills_by_product: Dict[str, List[dict]] = {p: [] for p in ANALYSED_VOUCHERS}
    for fill in getattr(artefact, "fills", []) or []:
        product = str(fill.get("product", ""))
        if product in fills_by_product:
            fills_by_product[product].append(fill)

    rows: List[Dict[str, object]] = []
    for product in CENTRAL_DEEP_VOUCHERS + UPPER_VOUCHERS:
        # Build sorted inventory map per day.
        day_paths = {day: sorted(seq) for (p, day), seq in inv_by_product_day.items() if p == product}
        # Helper to find pos right before timestamp.
        def pos_at(day: int, ts: int) -> int:
            seq = day_paths.get(day, [])
            if not seq:
                return 0
            lo, hi = 0, len(seq) - 1
            best = 0
            while lo <= hi:
                mid = (lo + hi) // 2
                if seq[mid][0] < ts:
                    best = seq[mid][1]
                    lo = mid + 1
                elif seq[mid][0] == ts:
                    if mid - 1 >= 0:
                        best = seq[mid - 1][1]
                    return int(best)
                else:
                    hi = mid - 1
            return int(best)

        adds_in_tail = 0  # fills that increased |pos| while already in tail
        reduces_in_tail = 0  # fills that reduced |pos| while in tail
        adds_in_body = 0
        reduces_in_body = 0
        adds_tail_qty = 0
        reduces_tail_qty = 0
        adds_body_qty = 0
        reduces_body_qty = 0
        adds_extreme_lots_long = 0
        adds_extreme_lots_short = 0
        for f in fills_by_product[product]:
            try:
                day = int(f.get("day", 0))
                ts = int(f.get("timestamp", 0))
                qty = int(f.get("quantity", 0))
                side = str(f.get("side"))
            except (ValueError, TypeError):
                continue
            if qty <= 0:
                continue
            signed = qty if side == "buy" else -qty
            pos_before = pos_at(day, ts)
            pos_after = pos_before + signed
            in_tail = abs(pos_before) >= near_cap_threshold
            inc = abs(pos_after) > abs(pos_before)
            if in_tail and inc:
                adds_in_tail += 1
                adds_tail_qty += qty
                if signed > 0:
                    adds_extreme_lots_long += qty
                else:
                    adds_extreme_lots_short += qty
            elif in_tail and not inc:
                reduces_in_tail += 1
                reduces_tail_qty += qty
            elif (not in_tail) and inc:
                adds_in_body += 1
                adds_body_qty += qty
            else:
                reduces_in_body += 1
                reduces_body_qty += qty
        total = adds_in_tail + reduces_in_tail + adds_in_body + reduces_in_body
        rows.append({
            "product": product,
            "bucket": next((b for b, names in BUCKETS.items() if product in names), "unknown"),
            "fills_total": total,
            "adds_in_tail": adds_in_tail,
            "reduces_in_tail": reduces_in_tail,
            "adds_in_body": adds_in_body,
            "reduces_in_body": reduces_in_body,
            "adds_tail_lots": adds_tail_qty,
            "reduces_tail_lots": reduces_tail_qty,
            "adds_body_lots": adds_body_qty,
            "reduces_body_lots": reduces_body_qty,
            "adds_tail_long_lots": adds_extreme_lots_long,
            "adds_tail_short_lots": adds_extreme_lots_short,
            "tail_add_share_by_count": (adds_in_tail / total) if total else 0.0,
            "tail_add_share_by_lots": (adds_tail_qty / max(1, adds_tail_qty + adds_body_qty)),
        })
    return {"rows": rows, "near_cap_threshold": near_cap_threshold}


# -----------------------------------------------------------------------------
# Phase P4. Extended terminal stress matrix.
def extended_stress_matrix(artefact) -> Dict[str, object]:
    """Compute terminal-state stresses across a wider grid than M0 forensics:
    VELVET +/- 50/100/150, IV +/- 0.03/0.05/0.08, combined +/- shocks,
    lower-TTE proxy.
    """
    products = set(ANALYSED_VOUCHERS + [UNDERLYING])
    fair_by_tick: Dict[Tuple[int, int], Dict[str, dict]] = {}
    for row in getattr(artefact, "fair_value_series", []) or []:
        product = str(row["product"])
        if product in products:
            key = (int(row["day"]), int(row["timestamp"]))
            fair_by_tick.setdefault(key, {})[product] = row
    if not fair_by_tick:
        return {}
    final_key = max(fair_by_tick.keys())
    final_rows = fair_by_tick[final_key]
    positions = {
        product: int(row.get("final_position", 0))
        for product, row in artefact.summary.get("per_product", {}).items()
    }
    spot = float(final_rows[UNDERLYING].get("mid") or 0.0)
    day, ts = final_key
    tte_years = max(1e-6, _tte_days(day, ts) / 365.0)
    sigma_inputs = []
    for K in CENTRAL_STRIKES:
        row = final_rows.get(f"VEV_{K}")
        if not row:
            continue
        iv = _implied_vol_call(float(row.get("mid") or 0.0), spot, float(K), tte_years)
        if iv is not None:
            sigma_inputs.append(iv)
    sigma = sum(sigma_inputs) / len(sigma_inputs) if sigma_inputs else 0.24

    def voucher_value(sigma_value: float, spot_value: float, tte_value: float) -> float:
        total = 0.0
        for product in ANALYSED_VOUCHERS:
            total += positions.get(product, 0) * _bs_call_price(
                spot_value, float(STRIKES[product]), tte_value, sigma_value
            )
        return total

    base = voucher_value(sigma, spot, tte_years)
    velvet_shifts: Dict[str, float] = {}
    for shift in (-150.0, -100.0, -50.0, 50.0, 100.0, 150.0):
        v_change = voucher_value(sigma, spot + shift, tte_years) - base
        velvet_change = positions.get(UNDERLYING, 0) * shift
        velvet_shifts[f"{shift:+.0f}"] = v_change + velvet_change

    iv_shifts: Dict[str, float] = {}
    for vol_pts in (-0.08, -0.05, -0.03, 0.03, 0.05, 0.08):
        shifted_sigma = max(0.01, sigma + vol_pts)
        iv_shifts[f"{vol_pts:+.2f}"] = voucher_value(shifted_sigma, spot, tte_years) - base

    combined: Dict[str, float] = {}
    for spot_d, vol_d in ((100, 0.05), (-100, -0.05), (50, 0.03), (-50, -0.03)):
        shifted_sigma = max(0.01, sigma + vol_d)
        v_change = voucher_value(shifted_sigma, spot + spot_d, tte_years) - base
        velvet_change = positions.get(UNDERLYING, 0) * spot_d
        combined[f"VELVET{spot_d:+d}_IV{vol_d:+.2f}"] = v_change + velvet_change

    # Lower-TTE proxy: simulate final-sim shorter TTE (4 days vs ~5 day-3
    # public terminal). We treat final-sim as 4 calendar days at terminal.
    lower_tte: Dict[str, float] = {}
    for tte_days_alt in (3.0, 2.0, 1.0):
        tte_alt_years = tte_days_alt / 365.0
        diff = voucher_value(sigma, spot, tte_alt_years) - base
        lower_tte[f"tte_{tte_days_alt:.1f}d"] = diff

    # Per-strike contribution to underlying +100 shock (worst case).
    per_strike_shock_up100: Dict[str, float] = {}
    per_strike_shock_dn100: Dict[str, float] = {}
    for product in ANALYSED_VOUCHERS:
        K = float(STRIKES[product])
        base_v = positions.get(product, 0) * _bs_call_price(spot, K, tte_years, sigma)
        up_v = positions.get(product, 0) * _bs_call_price(spot + 100.0, K, tte_years, sigma)
        dn_v = positions.get(product, 0) * _bs_call_price(spot - 100.0, K, tte_years, sigma)
        per_strike_shock_up100[product] = up_v - base_v
        per_strike_shock_dn100[product] = dn_v - base_v
    # Add VELVET leg.
    per_strike_shock_up100[UNDERLYING] = float(positions.get(UNDERLYING, 0) * 100.0)
    per_strike_shock_dn100[UNDERLYING] = float(positions.get(UNDERLYING, 0) * -100.0)

    return {
        "method": "terminal inventory proxy",
        "final_day": day,
        "final_timestamp": ts,
        "final_spot": spot,
        "final_sigma": sigma,
        "final_tte_days": _tte_days(day, ts),
        "velvet_shifts_pnl": velvet_shifts,
        "iv_shifts_pnl": iv_shifts,
        "combined_shifts_pnl": combined,
        "lower_tte_proxy_pnl": lower_tte,
        "per_strike_underlying_up100": per_strike_shock_up100,
        "per_strike_underlying_dn100": per_strike_shock_dn100,
        "final_positions": positions,
    }


# -----------------------------------------------------------------------------
# Phase P5. Day attribution stability.
def day_attribution_stability() -> Dict[str, object]:
    """Run M3 day-by-day and report per-strike contribution and ratio of
    central/deep PnL to other days. We do NOT re-run pooled (already in M3
    artefacts) - just the three day-isolated runs.
    """
    out: Dict[str, Dict[str, float]] = {}
    for day in (1, 2, 3):
        _art, result = run_replay_result(label=f"M3_day{day}", mode="M3_upper_long_cap_200", days=(day,), full_metrics=False)
        out[f"day_{day}"] = {
            "total": result.total,
            "voucher_total": result.voucher_total,
            "deep_total": result.deep_total,
            "central_total": result.central_total,
            "upper_total": result.upper_total,
        }
        for product in ANALYSED_VOUCHERS:
            out[f"day_{day}"][f"pnl_{product}"] = result.per_product.get(product, 0.0)
    return out


# -----------------------------------------------------------------------------
# Top-level driver.
def run_central_deep_forensics() -> Dict[str, object]:
    OUT.mkdir(parents=True, exist_ok=True)
    print("[P0] Running M3 base replay")
    artefact, result = run_replay_result(label="M3_central_deep_forensics", mode="M3_upper_long_cap_200")
    print(f"  total={result.total:,.0f} voucher={result.voucher_total:,.0f} breaches={result.breaches}")

    print("[P1] Computing empirical delta proxy from CSVs")
    empirical = _empirical_delta_per_strike_day()
    pooled = _model_aggregate_empirical(empirical)
    multi_delta = compute_multi_delta_ledger(artefact, pooled)
    rows_per_tick = multi_delta.pop("rows", [])

    print("[P2] Cap-entry forward-move analysis")
    entry_rows = cap_entry_forward_moves(artefact)
    entry_summary = cap_entry_forward_summary(entry_rows)

    print("[P3] Marginal-add attribution")
    add_attr = marginal_add_attribution(artefact, near_cap_threshold=250)
    add_attr_275 = marginal_add_attribution(artefact, near_cap_threshold=275)

    print("[P4] Extended terminal stress matrix")
    stress = extended_stress_matrix(artefact)

    print("[P5] Day attribution stability")
    day_stability = day_attribution_stability()

    # Persist artefacts.
    _write_csv(OUT / "multi_delta_per_tick.csv", rows_per_tick)
    _write_json(OUT / "multi_delta_summary.json", multi_delta)
    _write_json(OUT / "empirical_delta_per_strike_day.json", empirical)
    _write_json(OUT / "empirical_delta_pooled.json", pooled)
    _write_csv(OUT / "cap_entry_events.csv", entry_rows)
    _write_csv(OUT / "cap_entry_summary.csv", entry_summary)
    _write_csv(OUT / "marginal_add_attribution_250.csv", add_attr["rows"])
    _write_csv(OUT / "marginal_add_attribution_275.csv", add_attr_275["rows"])
    _write_json(OUT / "extended_stress_matrix.json", stress)
    _write_json(OUT / "day_attribution_stability.json", day_stability)
    _write_json(OUT / "summary.json", {
        "label": result.label,
        "mode": result.mode,
        "total": result.total,
        "voucher_total": result.voucher_total,
        "deep_total": result.deep_total,
        "central_total": result.central_total,
        "upper_total": result.upper_total,
        "breaches": result.breaches,
        "final_positions": result.final_pos,
        "per_product_pnl": result.per_product,
        "multi_delta": multi_delta,
        "stress_top_lines": {
            "underlying_+100": stress.get("velvet_shifts_pnl", {}).get("+100"),
            "underlying_-100": stress.get("velvet_shifts_pnl", {}).get("-100"),
            "iv_+0.05": stress.get("iv_shifts_pnl", {}).get("+0.05"),
            "iv_-0.05": stress.get("iv_shifts_pnl", {}).get("-0.05"),
            "VELVET+100_IV+0.05": stress.get("combined_shifts_pnl", {}).get("VELVET+100_IV+0.05"),
            "VELVET-100_IV-0.05": stress.get("combined_shifts_pnl", {}).get("VELVET-100_IV-0.05"),
        },
    })
    print(f"Artefacts written to {OUT}")
    return {
        "summary": result,
        "multi_delta": multi_delta,
        "stress": stress,
        "day_stability": day_stability,
        "marginal_add_250": add_attr,
        "marginal_add_275": add_attr_275,
        "entry_summary": entry_summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="Quick smoke test: empirical delta only.")
    args = parser.parse_args()
    if args.smoke:
        empirical = _empirical_delta_per_strike_day()
        pooled = _model_aggregate_empirical(empirical)
        OUT.mkdir(parents=True, exist_ok=True)
        _write_json(OUT / "empirical_delta_per_strike_day.json", empirical)
        _write_json(OUT / "empirical_delta_pooled.json", pooled)
        print(json.dumps(pooled, indent=2))
        return
    run_central_deep_forensics()


if __name__ == "__main__":
    main()
