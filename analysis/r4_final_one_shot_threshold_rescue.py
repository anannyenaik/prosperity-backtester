"""Final bounded Round 4 threshold-rescue pass.

Runs only the explicit V0-V5 variants requested for the final one-shot review.
Writes compact JSON/CSV artefacts under backtests/r4_final_one_shot_threshold_rescue.
"""
from __future__ import annotations

import csv
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from prosperity_backtester.dataset import load_round_dataset
from prosperity_backtester.fill_models import resolve_fill_model
from prosperity_backtester.metadata import get_round_spec
from prosperity_backtester.platform import PerturbationConfig, run_market_session
from prosperity_backtester.trader_adapter import make_trader

from analysis.voucher_m0_risk_forensics import compute_delta_ledger


DATA = ROOT / "data" / "round4"
OUT = ROOT / "backtests" / "r4_final_one_shot_threshold_rescue"
ACTIVE = ROOT / "strategies" / "r4_trader.py"
REJECTED = ROOT / "strategies" / "r4_execution_mm_candidate.py"
ONE_SHOT = ROOT / "strategies" / "r4_final_one_shot_candidate.py"

VOUCHERS = [
    "VEV_4000",
    "VEV_4500",
    "VEV_5000",
    "VEV_5100",
    "VEV_5200",
    "VEV_5300",
    "VEV_5400",
    "VEV_5500",
]


@dataclass(frozen=True)
class Variant:
    label: str
    path: Path
    overrides: Mapping[str, object]


VARIANTS = [
    Variant("V0_ACTIVE_M3", ACTIVE, {}),
    Variant("V1_REJECTED_REFERENCE", REJECTED, {}),
    Variant("V2_CAP_SAFE_THRESHOLD", ONE_SHOT, {"THRESHOLD_RESCUE.mode": "cap_safe"}),
    Variant("V3_DELTA_ADD_GATED_THRESHOLD", ONE_SHOT, {"THRESHOLD_RESCUE.mode": "delta_add_gated"}),
    Variant("V4_COMBINED_CAP_AND_DELTA_SAFE", ONE_SHOT, {"THRESHOLD_RESCUE.mode": "combined"}),
    Variant(
        "V5_SELECTIVE_STRIKE_THRESHOLD",
        ONE_SHOT,
        {
            "THRESHOLD_RESCUE.mode": "combined",
            "THRESHOLD_RESCUE.thresholds.VEV_4000": 1.5,
            "THRESHOLD_RESCUE.thresholds.VEV_4500": 1.5,
            "THRESHOLD_RESCUE.thresholds.VEV_5100": 1.0,
        },
    ),
]


def _dataset(days: Sequence[int]):
    round_spec = get_round_spec(4)
    loaded = load_round_dataset(DATA, days, round_number=4, round_spec=round_spec)
    return [loaded[int(day)] for day in days]


def _perturbation(name: str) -> Tuple[str, PerturbationConfig]:
    if name == "base":
        return "base", PerturbationConfig()
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
    raise ValueError(f"unknown fill mode {name!r}")


def _overrides(variant: Variant, days: Sequence[int]) -> Dict[str, object]:
    merged: Dict[str, object] = {"VOUCHER_BS.initial_day_index": int(days[0])}
    merged.update(dict(variant.overrides))
    return merged


def _run(variant: Variant, *, days: Sequence[int] = (1, 2, 3),
         fill_mode: str = "base", full: bool = False):
    fill_model_name, perturb = _perturbation(fill_mode)
    trader, _module = make_trader(variant.path, _overrides(variant, days))
    return run_market_session(
        trader=trader,
        trader_name=variant.label,
        market_days=_dataset(days),
        fill_model=resolve_fill_model(fill_model_name),
        perturb=perturb,
        rng=random.Random(20260418),
        run_name=f"{variant.label}_{fill_mode}_{'_'.join(str(day) for day in days)}",
        mode="replay",
        round_spec=get_round_spec(4),
        capture_full_output=full,
        include_option_diagnostics=False,
    )


def _voucher_pnl(artefact) -> float:
    per_product = artefact.summary.get("per_product", {})
    return float(sum(float(per_product.get(product, {}).get("final_mtm", 0.0)) for product in VOUCHERS))


def _per_product_pnl(artefact) -> Dict[str, float]:
    per_product = artefact.summary.get("per_product", {})
    return {product: float(per_product.get(product, {}).get("final_mtm", 0.0)) for product in VOUCHERS}


def _cap_side_dwell(artefact, product: str) -> Dict[str, float]:
    rows = [
        row for row in getattr(artefact, "inventory_series", []) or []
        if str(row.get("product")) == product
    ]
    if not rows:
        return {"long": 0.0, "short": 0.0}
    long_count = sum(1 for row in rows if int(row.get("position", 0) or 0) >= 270)
    short_count = sum(1 for row in rows if int(row.get("position", 0) or 0) <= -270)
    total = float(len(rows))
    return {"long": long_count / total, "short": short_count / total}


def _base_metrics(variant: Variant) -> Tuple[dict, object]:
    artefact = _run(variant, full=True)
    delta_summary, _delta_rows = compute_delta_ledger(artefact)
    overall_delta = delta_summary.get("overall", {})
    behaviour = (getattr(artefact, "behaviour", {}) or {}).get("per_product", {})
    row = {
        "variant": variant.label,
        "base_total": float(artefact.summary.get("final_pnl", 0.0)),
        "voucher_pnl": _voucher_pnl(artefact),
        "breaches": int(artefact.summary.get("limit_breaches", 0) or 0),
        "net_delta_p95": float(overall_delta.get("p95", 0.0) or 0.0),
        "net_delta_max": float(overall_delta.get("max_abs", 0.0) or 0.0),
        "per_product_pnl": _per_product_pnl(artefact),
    }
    for product in VOUCHERS:
        cap_dwell = float(behaviour.get(product, {}).get("time_near_cap_ratio", 0.0) or 0.0)
        row[f"{product}_cap_dwell"] = cap_dwell
        side = _cap_side_dwell(artefact, product)
        row[f"{product}_long_cap_dwell"] = side["long"]
        row[f"{product}_short_cap_dwell"] = side["short"]
    return row, artefact


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows: Dict[str, dict] = {}
    base_artefacts = {}

    for variant in VARIANTS:
        print(f"base {variant.label}")
        row, artefact = _base_metrics(variant)
        rows[variant.label] = row
        base_artefacts[variant.label] = artefact

    for variant in VARIANTS:
        for day in (1, 2, 3):
            print(f"day {day} {variant.label}")
            artefact = _run(variant, days=(day,), full=False)
            rows[variant.label][f"day_{day}"] = float(artefact.summary.get("final_pnl", 0.0))
            rows[variant.label][f"day_{day}_voucher"] = _voucher_pnl(artefact)
            rows[variant.label][f"day_{day}_breaches"] = int(artefact.summary.get("limit_breaches", 0) or 0)
        for fill_mode in ("adverse", "harsh"):
            print(f"{fill_mode} {variant.label}")
            artefact = _run(variant, fill_mode=fill_mode, full=False)
            rows[variant.label][f"{fill_mode}_total"] = float(artefact.summary.get("final_pnl", 0.0))
            rows[variant.label][f"{fill_mode}_voucher"] = _voucher_pnl(artefact)
            rows[variant.label][f"{fill_mode}_breaches"] = int(artefact.summary.get("limit_breaches", 0) or 0)

    ordered_rows = [rows[variant.label] for variant in VARIANTS]
    active = rows["V0_ACTIVE_M3"]
    rejected = rows["V1_REJECTED_REFERENCE"]
    contribution_rows = []
    for product in VOUCHERS:
        contribution_rows.append({
            "product": product,
            "active_pnl": active["per_product_pnl"].get(product, 0.0),
            "rejected_pnl": rejected["per_product_pnl"].get(product, 0.0),
            "diff": rejected["per_product_pnl"].get(product, 0.0) - active["per_product_pnl"].get(product, 0.0),
            "active_cap_dwell": active.get(f"{product}_cap_dwell", 0.0),
            "rejected_cap_dwell": rejected.get(f"{product}_cap_dwell", 0.0),
            "active_short_cap_dwell": active.get(f"{product}_short_cap_dwell", 0.0),
            "rejected_short_cap_dwell": rejected.get(f"{product}_short_cap_dwell", 0.0),
            "active_long_cap_dwell": active.get(f"{product}_long_cap_dwell", 0.0),
            "rejected_long_cap_dwell": rejected.get(f"{product}_long_cap_dwell", 0.0),
        })

    payload = {
        "variants": ordered_rows,
        "rejected_contribution_by_strike": contribution_rows,
    }
    (OUT / "summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    fieldnames = [
        "variant",
        "base_total",
        "voucher_pnl",
        "day_1",
        "day_2",
        "day_3",
        "adverse_voucher",
        "harsh_voucher",
        "breaches",
        "net_delta_p95",
        "net_delta_max",
        "VEV_4000_cap_dwell",
        "VEV_4500_cap_dwell",
        "VEV_5000_cap_dwell",
        "VEV_5100_cap_dwell",
        "VEV_5200_cap_dwell",
        "VEV_5300_cap_dwell",
        "VEV_5400_cap_dwell",
        "VEV_5500_cap_dwell",
    ]
    with (OUT / "variant_table.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in ordered_rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})

    with (OUT / "rejected_contribution_by_strike.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(contribution_rows[0]))
        writer.writeheader()
        writer.writerows(contribution_rows)

    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
