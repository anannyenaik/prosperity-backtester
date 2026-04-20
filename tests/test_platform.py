from __future__ import annotations

import json
from pathlib import Path

from r1bt.dataset import load_round1_dataset
from r1bt.experiments import TraderSpec, run_compare, run_monte_carlo, run_optimize_from_config, run_replay
from r1bt.platform import PerturbationConfig
from r1bt.trader_adapter import make_trader


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "round1"
LIVE_EXPORT = ROOT / "live_exports" / "259168" / "259168.log"
TRADER_V9 = ROOT / "examples" / "trader_round1_v9.py"
STARTER = ROOT / "strategies" / "starter.py"
MAIN_TRADER = ROOT / "strategies" / "trader.py"

def test_dataset_validation():
    dataset = load_round1_dataset(DATA_DIR, days=(0,))
    assert 0 in dataset
    assert dataset[0].validation["timestamps"] == 10000
    assert dataset[0].validation["timestamp_step_ok"] is True
    assert dataset[0].validation["crossed_book_rows"] == 0


def test_trader_adapter_supports_plain_datamodel_import():
    trader, module = make_trader(TRADER_V9)
    assert trader is not None
    assert hasattr(module, "Trader")


def test_replay_with_live_export_bundle(tmp_path):
    artefact = run_replay(
        trader_spec=TraderSpec(name="live_v9", path=TRADER_V9),
        days=(0,),
        data_dir=DATA_DIR,
        fill_model_name="base",
        perturbation=PerturbationConfig(),
        output_dir=tmp_path / "replay",
        run_name="replay_test",
        live_export_path=LIVE_EXPORT,
    )
    assert artefact.summary["fill_count"] > 0
    assert artefact.fair_value_series
    assert artefact.behaviour["per_product"]["INTARIAN_PEPPER_ROOT"]["cap_usage_ratio"] >= 0.0
    assert "total_fills" in artefact.behaviour["per_product"]["INTARIAN_PEPPER_ROOT"]
    assert "passive_fill_count" in artefact.behaviour["per_product"]["INTARIAN_PEPPER_ROOT"]
    assert artefact.behaviour_series
    assert "per_product_pnl" in artefact.validation
    assert (tmp_path / "replay" / "dashboard.json").is_file()
    dashboard = json.loads((tmp_path / "replay" / "dashboard.json").read_text(encoding="utf-8"))
    assert dashboard["meta"]["schemaVersion"] == 3
    assert dashboard["assumptions"]["exact"]
    assert (tmp_path / "run_registry.jsonl").is_file()
    assert (tmp_path / "replay" / "fills.csv").is_file()
    assert (tmp_path / "replay" / "fair_value_series.csv").is_file()
    assert (tmp_path / "replay" / "behaviour_summary.csv").is_file()
    assert (tmp_path / "replay" / "behaviour_series.csv").is_file()


def test_compare_and_monte_carlo(tmp_path):
    compare_rows = run_compare(
        trader_specs=[
            TraderSpec(name="starter", path=STARTER),
            TraderSpec(name="main", path=MAIN_TRADER),
        ],
        days=(0,),
        data_dir=DATA_DIR,
        fill_model_name="base",
        perturbation=PerturbationConfig(),
        output_dir=tmp_path / "compare",
        run_name="compare_test",
    )
    assert len(compare_rows) == 2
    mc = run_monte_carlo(
        trader_spec=TraderSpec(name="main", path=MAIN_TRADER),
        sessions=2,
        sample_sessions=1,
        days=(-2,),
        fill_model_name="base",
        perturbation=PerturbationConfig(),
        output_dir=tmp_path / "mc",
        base_seed=20260418,
        run_name="mc_test",
    )
    assert len(mc) == 2
    assert (tmp_path / "mc" / "dashboard.json").is_file()
    mc_dashboard = json.loads((tmp_path / "mc" / "dashboard.json").read_text(encoding="utf-8"))
    pepper_bands = mc_dashboard["monteCarlo"]["fairValueBands"]["analysisFair"]["INTARIAN_PEPPER_ROOT"]
    assert not pepper_bands or {"p10", "p25", "p50", "p75", "p90"}.issubset(pepper_bands[0])
    assert (tmp_path / "mc" / "sample_paths").is_dir()
    assert (tmp_path / "mc" / "behaviour_series.csv").is_file()


def test_optimize_config(tmp_path):
    config = {
        "name": "tiny_opt",
        "trader": str(TRADER_V9),
        "days": [0],
        "fill_model": "base",
        "mc_sessions": 2,
        "mc_sample_sessions": 1,
        "variants": [
            {"name": "trend_1", "overrides": {"PARAMS.INTARIAN_PEPPER_ROOT.trend_slope": 0.001}},
            {"name": "trend_2", "overrides": {"PARAMS.INTARIAN_PEPPER_ROOT.trend_slope": 0.002}},
        ],
    }
    config_path = tmp_path / "opt_config.json"
    config_path.write_text(__import__("json").dumps(config), encoding="utf-8")
    rows = run_optimize_from_config(config_path, tmp_path / "opt")
    assert rows
    assert rows[0]["score"] >= rows[-1]["score"]
    assert (tmp_path / "opt" / "dashboard.json").is_file()
    dashboard = json.loads((tmp_path / "opt" / "dashboard.json").read_text(encoding="utf-8"))
    assert dashboard["optimization"]["diagnostics"]["variant_count"] == 2
    assert (tmp_path / "opt" / "optimization.csv").is_file()
    assert (tmp_path / "opt" / "manifest.json").is_file()
