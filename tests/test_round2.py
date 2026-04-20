from __future__ import annotations

import json
import random
from pathlib import Path

from prosperity_backtester.dataset import load_round2_dataset
from prosperity_backtester.experiments import TraderSpec, run_replay, run_round2_scenario_compare_from_config
from prosperity_backtester.platform import PerturbationConfig
from prosperity_backtester.round2 import AccessScenario


ROOT = Path(__file__).resolve().parent.parent
STARTER = ROOT / "strategies" / "starter.py"


def _write_round2_tiny_dataset(data_dir: Path) -> None:
    data_dir.mkdir(parents=True)
    header = (
        "day;timestamp;product;"
        "bid_price_1;bid_volume_1;bid_price_2;bid_volume_2;bid_price_3;bid_volume_3;"
        "ask_price_1;ask_volume_1;ask_price_2;ask_volume_2;ask_price_3;ask_volume_3;"
        "mid_price;profit_and_loss\n"
    )
    rows = [
        "0;0;ASH_COATED_OSMIUM;9998;10;;;;;9999;10;;;;;10000;0\n",
        "0;0;INTARIAN_PEPPER_ROOT;11498;10;;;;;11499;10;;;;;11500;0\n",
    ]
    (data_dir / "prices_round_2_day_0.csv").write_text(header + "".join(rows), encoding="utf-8")
    (data_dir / "trades_round_2_day_0.csv").write_text(
        "timestamp;buyer;seller;symbol;currency;price;quantity\n",
        encoding="utf-8",
    )


def test_round2_dataset_loader_uses_round2_file_names(tmp_path):
    data_dir = tmp_path / "round2"
    _write_round2_tiny_dataset(data_dir)

    dataset = load_round2_dataset(data_dir, days=(0,))

    assert dataset[0].metadata["source"] == "round2_csv"
    assert dataset[0].validation["products_seen"] == ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]
    assert dataset[0].validation["timestamps"] == 1


def test_access_scenario_cost_and_stochastic_activation():
    scenario = AccessScenario(
        name="stochastic_test",
        enabled=True,
        contract_won=True,
        mode="stochastic",
        maf_bid=123.0,
        access_probability=1.0,
        access_quality=0.5,
    )

    assert scenario.maf_cost == 123.0
    assert scenario.expected_extra_quote_fraction == 0.125
    assert scenario.active_extra_fraction(random.Random(1)) == 0.125


def test_round2_replay_deducts_maf_without_hiding_gross_pnl(tmp_path):
    data_dir = tmp_path / "round2"
    _write_round2_tiny_dataset(data_dir)
    scenario = AccessScenario(
        name="won_access",
        enabled=True,
        contract_won=True,
        mode="deterministic",
        maf_bid=5.0,
        access_quality=1.0,
    )

    artefact = run_replay(
        trader_spec=TraderSpec(name="starter", path=STARTER),
        days=(0,),
        data_dir=data_dir,
        fill_model_name="base",
        perturbation=PerturbationConfig(),
        output_dir=tmp_path / "replay",
        run_name="round2_replay",
        round_number=2,
        access_scenario=scenario,
    )

    assert artefact.summary["maf_cost"] == 5.0
    assert artefact.summary["final_pnl"] == artefact.summary["gross_pnl_before_maf"] - 5.0
    assert artefact.access_scenario["name"] == "won_access"
    dashboard = json.loads((tmp_path / "replay" / "dashboard.json").read_text(encoding="utf-8"))
    assert dashboard["meta"]["round"] == 2
    assert dashboard["meta"]["accessScenario"]["name"] == "won_access"
    assert "round2" in dashboard["assumptions"]


def test_round2_scenario_compare_bundle(tmp_path):
    data_dir = tmp_path / "round2"
    _write_round2_tiny_dataset(data_dir)
    config = {
        "name": "tiny_round2",
        "round": 2,
        "data_dir": str(data_dir),
        "days": [0],
        "trader": str(STARTER),
        "variants": [{"name": "starter"}],
        "scenarios": [
            {"name": "no_access", "enabled": False, "contract_won": False, "mode": "none"},
            {
                "name": "access_base",
                "enabled": True,
                "contract_won": True,
                "mode": "deterministic",
                "maf_bid": 5,
                "access_quality": 1.0,
            },
        ],
        "mc_sessions": 2,
        "mc_sample_sessions": 0,
    }
    config_path = tmp_path / "round2_config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    result = run_round2_scenario_compare_from_config(config_path, tmp_path / "round2_out")

    assert len(result["scenario_rows"]) == 2
    assert result["winner_rows"]
    access_row = next(row for row in result["scenario_rows"] if row["scenario"] == "access_base")
    assert access_row["maf_cost"] == 5.0
    assert access_row["marginal_access_pnl_before_maf"] is not None
    assert (tmp_path / "round2_out" / "dashboard.json").is_file()
    assert (tmp_path / "round2_out" / "round2_scenarios.csv").is_file()
