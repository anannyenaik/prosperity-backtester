from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from prosperity_backtester.dataset import load_round_dataset
from prosperity_backtester.experiments import TraderSpec, run_monte_carlo
from prosperity_backtester.metadata import get_round_spec, products_for_round
from prosperity_backtester.platform import PerturbationConfig, generate_synthetic_market_days


ROOT = Path(__file__).resolve().parent.parent
ROUND4_DATA = ROOT / "data" / "round4"
R4_TRADER = ROOT / "strategies" / "r4_algo_v1_candidate.py"


def test_round4_registry_and_loader_preserve_counterparties():
    spec = get_round_spec(4)
    assert spec.default_days == (1, 2, 3)
    assert spec.final_tte_days == 4
    assert spec.tte_days_by_historical_day == {1: 7, 2: 6, 3: 5}
    assert products_for_round(4) == products_for_round(3)

    dataset = load_round_dataset(ROUND4_DATA, (1, 2, 3), round_number=4)
    expected_trade_rows = {1: 1407, 2: 1333, 3: 1541}
    names = set()
    for day, day_dataset in dataset.items():
        validation = day_dataset.validation
        assert validation["price_rows"] == 120000
        assert validation["timestamps"] == 10000
        assert validation["timestamp_min"] == 0
        assert validation["timestamp_max"] == 999900
        assert validation["timestamp_step_ok"] is True
        assert validation["products_seen"] == list(products_for_round(4))
        assert validation["trade_rows"] == expected_trade_rows[day]
        assert validation["trade_rows_invalid_currency"] == 0
        assert validation["trade_rows_invalid_quantity"] == 0
        for by_product in day_dataset.trades_by_timestamp.values():
            for trades in by_product.values():
                for trade in trades:
                    assert trade.buyer
                    assert trade.seller
                    names.add(trade.buyer)
                    names.add(trade.seller)
    assert {"Mark 01", "Mark 14", "Mark 22", "Mark 49", "Mark 55", "Mark 67"} <= names


def test_round4_cli_inspect_and_counterparty_research(tmp_path):
    inspect = subprocess.run(
        [
            sys.executable,
            "-m",
            "prosperity_backtester",
            "inspect",
            "--round",
            "4",
            "--data-dir",
            str(ROUND4_DATA),
            "--days",
            "1",
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(inspect.stdout)
    assert payload["round"] == 4
    assert payload["option_diagnostics"]["round"] == 4

    output_dir = tmp_path / "research"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "prosperity_backtester",
            "r4-counterparty-research",
            "--data-dir",
            str(ROUND4_DATA),
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert (output_dir / "counterparty_recommendations.csv").is_file()
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["recommendation_rows"] > 0


def test_round4_synthetic_mc_has_named_flow_and_is_deterministic(tmp_path):
    spec = get_round_spec(4)
    dataset = load_round_dataset(ROUND4_DATA, spec.default_days, round_number=4)
    historical_days = [dataset[day] for day in spec.default_days]
    perturb = PerturbationConfig(synthetic_tick_limit=80, counterparty_edge_strength=0.25)
    synthetic = generate_synthetic_market_days(
        days=(1,),
        seed=20260426,
        perturb=perturb,
        round_spec=spec,
        historical_market_days=historical_days,
    )[0]
    names = {
        name
        for by_product in synthetic.trades_by_timestamp.values()
        for trades in by_product.values()
        for trade in trades
        for name in (trade.buyer, trade.seller)
        if name
    }
    assert names

    common = {
        "trader_spec": TraderSpec(name="r4", path=R4_TRADER),
        "sessions": 2,
        "sample_sessions": 0,
        "days": (1,),
        "data_dir": ROUND4_DATA,
        "fill_model_name": "base",
        "perturbation": perturb,
        "base_seed": 20260426,
        "run_name": "r4_determinism",
        "round_number": 4,
        "write_bundle": False,
    }
    first = run_monte_carlo(**common, output_dir=tmp_path / "first")
    second = run_monte_carlo(**common, output_dir=tmp_path / "second")
    assert [session.summary for session in first] == [session.summary for session in second]
