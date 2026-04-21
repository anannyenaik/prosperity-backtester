from __future__ import annotations

import json
from pathlib import Path

from prosperity_backtester.dataset import load_round1_dataset
from prosperity_backtester.experiments import TraderSpec, run_compare, run_monte_carlo, run_optimize_from_config, run_replay
from prosperity_backtester.platform import PerturbationConfig
from prosperity_backtester.storage import OutputOptions
from prosperity_backtester.trader_adapter import make_trader


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "round1"
LIVE_EXPORT = ROOT / "live_exports" / "259168" / "259168.json"
TRADER_V9 = ROOT / "examples" / "trader_round1_v9.py"
STARTER = ROOT / "strategies" / "starter.py"
MAIN_TRADER = ROOT / "strategies" / "trader.py"


def _write_trade_matching_dataset(data_dir: Path) -> None:
    data_dir.mkdir(parents=True)
    prices_header = (
        "day;timestamp;product;"
        "bid_price_1;bid_volume_1;bid_price_2;bid_volume_2;bid_price_3;bid_volume_3;"
        "ask_price_1;ask_volume_1;ask_price_2;ask_volume_2;ask_price_3;ask_volume_3;"
        "mid_price;profit_and_loss\n"
    )
    price_rows = [
        "0;0;ASH_COATED_OSMIUM;9998;10;;;;;10002;10;;;;;10000;0\n",
        "0;0;INTARIAN_PEPPER_ROOT;11998;10;;;;;12002;10;;;;;12000;0\n",
    ]
    (data_dir / "prices_round_1_day_0.csv").write_text(prices_header + "".join(price_rows), encoding="utf-8")
    trade_rows = [
        "timestamp;buyer;seller;symbol;currency;price;quantity\n",
        "0;;BOT_SELLER;ASH_COATED_OSMIUM;SEASHELLS;9999;1\n",
    ]
    (data_dir / "trades_round_1_day_0.csv").write_text("".join(trade_rows), encoding="utf-8")


def _write_passive_buy_trader(path: Path) -> Path:
    path.write_text(
        """
from datamodel import Order


class Trader:
    def run(self, state):
        return {"ASH_COATED_OSMIUM": [Order("ASH_COATED_OSMIUM", 9999, 1)]}, 0, state.traderData
""".strip(),
        encoding="utf-8",
    )
    return path

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
    assert dashboard["meta"]["outputProfile"]["profile"] == "light"
    assert "orders" not in dashboard
    assert dashboard["orderIntent"]
    assert dashboard["assumptions"]["exact"]
    assert any(item["key"] == "fills" and item["fidelity"] == "exact" for item in dashboard["dataContract"])
    assert (tmp_path / "run_registry.jsonl").is_file()
    assert not (tmp_path / "replay" / "orders.csv").exists()
    assert (tmp_path / "replay" / "fills.csv").is_file()
    assert not (tmp_path / "replay" / "fair_value_series.csv").exists()
    assert (tmp_path / "replay" / "behaviour_summary.csv").is_file()
    assert not (tmp_path / "replay" / "behaviour_series.csv").exists()
    manifest = json.loads((tmp_path / "replay" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["created_at"]
    assert manifest["bundle_stats"]["total_size_bytes"] > 0
    assert "dashboard.json" in manifest["canonical_files"]
    assert any(item["key"] == "replay_summary" for item in manifest["data_contract"])
    assert manifest["provenance"]["command"]["argv"]
    assert manifest["provenance"]["runtime"]["engine_backend"] == "python"
    assert manifest["provenance"]["runtime"]["parallelism"] == "single_process"
    assert manifest["provenance"]["runtime"]["worker_count"] == 1


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
    assert not (tmp_path / "compare" / "starter").exists()
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
    assert mc_dashboard["monteCarlo"]["pathBandMethod"]["source"] == "all_sessions"
    assert mc_dashboard["meta"]["outputProfile"]["profile"] == "light"
    assert mc_dashboard["monteCarlo"]["sampleRuns"]
    assert any(item["key"] == "path_bands" and item["fidelity"] == "bucketed" for item in mc_dashboard["dataContract"])
    assert mc_dashboard["meta"]["provenance"]["runtime"]["engine_backend"] == "python"
    assert mc_dashboard["meta"]["provenance"]["runtime"]["monte_carlo_backend"] == "streaming"
    assert mc_dashboard["meta"]["provenance"]["runtime"]["session_count"] == 2
    assert mc_dashboard["meta"]["provenance"]["runtime"]["sample_session_count"] == 1
    assert mc_dashboard["meta"]["provenance"]["runtime"]["phase_timings_seconds"]["bundle_write_seconds"] >= 0.0
    assert not (tmp_path / "mc" / "sample_paths").exists()
    assert not (tmp_path / "mc" / "behaviour_series.csv").exists()


def test_full_output_profile_writes_debug_artifacts(tmp_path):
    options = OutputOptions.from_profile("full")
    run_replay(
        trader_spec=TraderSpec(name="live_v9", path=TRADER_V9),
        days=(0,),
        data_dir=DATA_DIR,
        fill_model_name="base",
        perturbation=PerturbationConfig(),
        output_dir=tmp_path / "full_replay",
        run_name="full_replay_test",
        output_options=options,
    )

    dashboard = json.loads((tmp_path / "full_replay" / "dashboard.json").read_text(encoding="utf-8"))
    assert dashboard["meta"]["outputProfile"]["profile"] == "full"
    assert dashboard["orders"]
    assert (tmp_path / "full_replay" / "orders.csv").is_file()


def test_trade_matching_mode_controls_passive_trade_matching(tmp_path):
    data_dir = tmp_path / "matching_data"
    trader = _write_passive_buy_trader(tmp_path / "passive_buy_trader.py")
    _write_trade_matching_dataset(data_dir)

    common = {
        "trader_spec": TraderSpec(name="passive_buy", path=trader),
        "days": (0,),
        "data_dir": data_dir,
        "fill_model_name": "base",
        "run_name": "trade_matching_mode",
    }
    aggressive_fill_settings = {
        "passive_fill_scale": 10.0,
        "missed_fill_additive": -1.0,
    }

    all_mode = run_replay(
        **common,
        perturbation=PerturbationConfig(trade_matching_mode="all", **aggressive_fill_settings),
        output_dir=tmp_path / "matching_all",
    )
    worse_mode = run_replay(
        **common,
        perturbation=PerturbationConfig(trade_matching_mode="worse", **aggressive_fill_settings),
        output_dir=tmp_path / "matching_worse",
    )
    none_mode = run_replay(
        **common,
        perturbation=PerturbationConfig(trade_matching_mode="none", **aggressive_fill_settings),
        output_dir=tmp_path / "matching_none",
    )

    assert all_mode.summary["fill_count"] == 1
    assert all_mode.fills[0]["kind"] == "passive_approx"
    assert worse_mode.summary["fill_count"] == 0
    assert none_mode.summary["fill_count"] == 0


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
