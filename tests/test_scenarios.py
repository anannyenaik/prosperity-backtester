from __future__ import annotations

import json
from pathlib import Path

import pytest

from prosperity_backtester.noise import resolve_noise_profile
from prosperity_backtester.scenarios import default_research_scenarios
from prosperity_backtester.experiments import run_round3_hydrogel_meanshift_from_config, run_scenario_compare_from_config


ROOT = Path(__file__).resolve().parent.parent
STARTER = ROOT / "strategies" / "archive" / "legacy" / "starter.py"
NOOP_ROUND3 = ROOT / "tests" / "fixtures" / "noop_round3_trader.py"


def _write_tiny_round1_dataset(data_dir: Path) -> None:
    data_dir.mkdir(parents=True)
    header = (
        "day;timestamp;product;"
        "bid_price_1;bid_volume_1;bid_price_2;bid_volume_2;bid_price_3;bid_volume_3;"
        "ask_price_1;ask_volume_1;ask_price_2;ask_volume_2;ask_price_3;ask_volume_3;"
        "mid_price;profit_and_loss\n"
    )
    rows = [
        "0;0;ASH_COATED_OSMIUM;9998;10;;;;;10002;10;;;;;10000;0\n",
        "0;0;INTARIAN_PEPPER_ROOT;11998;10;;;;;12002;10;;;;;12000;0\n",
        "0;100;ASH_COATED_OSMIUM;9998;10;;;;;10002;10;;;;;10000;0\n",
        "0;100;INTARIAN_PEPPER_ROOT;11999;10;;;;;12003;10;;;;;12001;0\n",
    ]
    (data_dir / "prices_round_1_day_0.csv").write_text(header + "".join(rows), encoding="utf-8")
    (data_dir / "trades_round_1_day_0.csv").write_text(
        "timestamp;buyer;seller;symbol;currency;price;quantity\n",
        encoding="utf-8",
    )


def test_noise_profiles_expose_fitted_values():
    fitted = resolve_noise_profile("fitted")
    stress = resolve_noise_profile("stress")

    assert fitted["ASH_COATED_OSMIUM"] == 3.70
    assert fitted["INTARIAN_PEPPER_ROOT"] == 3.22
    assert stress["ASH_COATED_OSMIUM"] > fitted["ASH_COATED_OSMIUM"]


def test_default_research_scenarios_include_core_stresses():
    names = {scenario.name for scenario in default_research_scenarios()}

    assert {"baseline", "crash_shock", "wide_spread_thin_depth", "harsher_slippage", "lower_fill_quality"}.issubset(names)


def test_scenario_compare_bundle(tmp_path):
    data_dir = tmp_path / "round1"
    _write_tiny_round1_dataset(data_dir)
    config = {
        "name": "tiny_scenario_grid",
        "round": 1,
        "data_dir": str(data_dir),
        "days": [0],
        "trader": str(STARTER),
        "variants": [{"name": "starter"}],
        "scenarios": [
            {"name": "baseline", "fill_model": "empirical_baseline", "noise_profile": "fitted"},
            {
                "name": "lower_fill_quality",
                "fill_model": "low_fill_quality",
                "noise_profile": "fitted",
                "perturbation": {"passive_fill_scale": 0.75, "missed_fill_additive": 0.05},
            },
        ],
        "mc_sessions": 0,
    }
    config_path = tmp_path / "scenario_config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8-sig")

    result = run_scenario_compare_from_config(config_path, tmp_path / "scenario_out")

    assert len(result["scenario_rows"]) == 2
    assert result["robustness_rows"][0]["trader"] == "starter"
    assert (tmp_path / "scenario_out" / "dashboard.json").is_file()
    assert (tmp_path / "scenario_out" / "robustness_ranking.csv").is_file()


def test_round3_hydrogel_meanshift_bundle_is_synthetic_only(tmp_path):
    config = {
        "name": "tiny_hydrogel_meanshift",
        "round": 3,
        "data_dir": str(ROOT / "data" / "round3"),
        "days": [0],
        "traders": [{"name": "noop", "path": str(NOOP_ROUND3)}],
        "scenarios": [
            {
                "name": "shift_neutral",
                "fill_model": "base",
                "perturbation": {"synthetic_tick_limit": 4, "shock_tick": 1},
            },
            {
                "name": "shift_plus_25",
                "fill_model": "base",
                "perturbation": {"synthetic_tick_limit": 4, "shock_tick": 1, "hydrogel_shock": 25.0},
            },
        ],
        "mc_sessions": 2,
        "mc_sample_sessions": 0,
    }
    config_path = tmp_path / "r3_meanshift.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    result = run_round3_hydrogel_meanshift_from_config(config_path, tmp_path / "r3_meanshift")

    rows = result["summary_rows"]
    assert len(rows) == 2
    assert {row["source"] for row in rows} == {"synthetic_round3_mc"}
    assert {float(row["hydrogel_shift"]) for row in rows} == {0.0, 25.0}
    assert all("final_pnl" not in row for row in rows)
    assert all(row["mc_min"] is not None and row["mc_max"] is not None for row in rows)
    assert (tmp_path / "r3_meanshift" / "r3_hydrogel_meanshift.csv").is_file()
    assert (tmp_path / "r3_meanshift" / "r3_hydrogel_meanshift_products.csv").is_file()


def test_scenario_config_reports_missing_trader(tmp_path):
    config_path = tmp_path / "bad_scenario_config.json"
    config_path.write_text(json.dumps({"name": "bad", "days": [0], "scenarios": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="trader"):
        run_scenario_compare_from_config(config_path, tmp_path / "out")
