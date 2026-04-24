from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from prosperity_backtester.__main__ import build_parser, _days_from_args
from prosperity_backtester.dataset import load_round3_dataset, load_round_dataset
from prosperity_backtester.experiments import TraderSpec, default_data_dir_for_round, run_replay
from prosperity_backtester.fill_models import resolve_fill_model
from prosperity_backtester.metadata import get_round_spec, position_limit_for, products_for_round
from prosperity_backtester.platform import PerturbationConfig, generate_synthetic_market_days
from prosperity_backtester.round3 import (
    ROUND3_VOUCHERS,
    ROUND3_UNDERLYING,
    black_scholes_call_price,
    call_delta,
    implied_vol_bisection,
    intrinsic_value,
    parse_voucher_symbol,
    time_value,
)


ROOT = Path(__file__).resolve().parent.parent
ROUND3_DATA = ROOT / "data" / "round3"
NOOP_ROUND3 = ROOT / "tests" / "fixtures" / "noop_round3_trader.py"


def _write_round3_tiny_dataset(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    header = (
        "day;timestamp;product;"
        "bid_price_1;bid_volume_1;bid_price_2;bid_volume_2;bid_price_3;bid_volume_3;"
        "ask_price_1;ask_volume_1;ask_price_2;ask_volume_2;ask_price_3;ask_volume_3;"
        "mid_price;profit_and_loss\n"
    )
    product_rows = {
        "HYDROGEL_PACK": "0;0;HYDROGEL_PACK;99;10;;;;;100;10;;;;;99.5;0\n",
        "VELVETFRUIT_EXTRACT": "0;0;VELVETFRUIT_EXTRACT;5249;20;;;;;5251;20;;;;;5250.0;0\n",
        "VEV_4000": "0;0;VEV_4000;1250;5;;;;;1252;5;;;;;1251.0;0\n",
        "VEV_4500": "0;0;VEV_4500;760;5;;;;;762;5;;;;;761.0;0\n",
        "VEV_5000": "0;0;VEV_5000;9;5;8;5;;;10;1;11;2;;;10.5;0\n",
        "VEV_5100": "0;0;VEV_5100;6;5;;;;;7;5;;;;;6.5;0\n",
        "VEV_5200": "0;0;VEV_5200;4;5;;;;;5;5;;;;;4.5;0\n",
        "VEV_5300": "0;0;VEV_5300;3;5;;;;;4;5;;;;;3.5;0\n",
        "VEV_5400": "0;0;VEV_5400;2;5;;;;;3;5;;;;;2.5;0\n",
        "VEV_5500": "0;0;VEV_5500;1;5;;;;;2;5;;;;;1.5;0\n",
        "VEV_6000": "0;0;VEV_6000;0;5;;;;;1;5;;;;;0.5;0\n",
        "VEV_6500": "0;0;VEV_6500;0;5;;;;;1;5;;;;;0.5;0\n",
    }
    ordered_rows = [product_rows[product] for product in products_for_round(3)]
    (data_dir / "prices_round_3_day_0.csv").write_text(header + "".join(ordered_rows), encoding="utf-8")
    (data_dir / "trades_round_3_day_0.csv").write_text(
        "".join([
            "timestamp;buyer;seller;symbol;currency;price;quantity\n",
            "0;;BOT_SELLER;HYDROGEL_PACK;XIRECS;99.0;1\n",
        ]),
        encoding="utf-8",
    )


def _write_trader(path: Path, body: str) -> Path:
    path.write_text(body.strip(), encoding="utf-8")
    return path


def test_round3_registry_and_metadata():
    spec = get_round_spec(3)

    assert spec.round_number == 3
    assert spec.default_days == (0, 1, 2)
    assert spec.tte_days_by_historical_day == {0: 8, 1: 7, 2: 6}
    assert spec.final_tte_days == 5
    assert len(spec.products) == 12
    assert position_limit_for("HYDROGEL_PACK", 3) == 200
    assert position_limit_for("VELVETFRUIT_EXTRACT", 3) == 200
    assert position_limit_for("VEV_5000", 3) == 300
    assert parse_voucher_symbol("VEV_6500") == 6500
    assert all(spec.product_metadata[symbol].underlying == "VELVETFRUIT_EXTRACT" for symbol in ROUND3_VOUCHERS)
    assert get_round_spec(1).products
    assert get_round_spec(2).products


def test_round3_dataset_loader_reads_real_capsule_files():
    dataset = load_round3_dataset(ROUND3_DATA, days=(0, 1, 2))

    assert set(dataset) == {0, 1, 2}
    expected_products = list(products_for_round(3))
    expected_trade_rows = {0: 1308, 1: 1407, 2: 1333}
    zero_price_rows = 0
    for day, day_dataset in dataset.items():
        validation = day_dataset.validation
        assert validation["price_rows"] == 120000
        assert validation["timestamps"] == 10000
        assert validation["timestamp_step_ok"] is True
        assert validation["timestamp_min"] == 0
        assert validation["timestamp_max"] == 999900
        assert validation["products_seen"] == expected_products
        assert validation["exact_product_match"] is True
        assert validation["duplicate_book_rows"] == 0
        assert validation["trade_rows"] == expected_trade_rows[day]
        assert validation["trade_rows_unknown_symbol"] == 0
        assert validation["trade_rows_invalid_currency"] == 0
        zero_price_rows += sum(
            1
            for by_product in day_dataset.trades_by_timestamp.values()
            for trades in by_product.values()
            for trade in trades
            if trade.price == 0.0 and trade.symbol in {"VEV_6000", "VEV_6500"}
        )
    assert zero_price_rows > 0


def test_round3_cli_accepts_round3_and_uses_round_defaults(tmp_path):
    parser = build_parser()
    replay_args = parser.parse_args(["replay", "tests/fixtures/noop_round3_trader.py", "--round", "3"])
    inspect_args = parser.parse_args(["inspect", "--round", "3"])

    assert replay_args.round == 3
    assert default_data_dir_for_round(3).name == "round3"
    assert _days_from_args(replay_args) == (0, 1, 2)
    assert _days_from_args(inspect_args) == (0, 1, 2)

    command = [
        sys.executable,
        "-m",
        "prosperity_backtester",
        "inspect",
        "--round",
        "3",
        "--data-dir",
        str(ROUND3_DATA),
        "--days",
        "0",
        "1",
        "2",
        "--json",
    ]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout)
    assert payload["round"] == 3
    assert payload["days"][0]["validation"]["price_rows"] == 120000
    assert "option_diagnostics" in payload

    invalid = subprocess.run(
        [sys.executable, "-m", "prosperity_backtester", "inspect", "--round", "4"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert invalid.returncode != 0
    assert "invalid choice" in invalid.stderr.lower()


def test_round3_replay_noop_smoke(tmp_path):
    artefact = run_replay(
        trader_spec=TraderSpec(name="noop_round3", path=NOOP_ROUND3),
        days=(0, 1, 2),
        data_dir=ROUND3_DATA,
        fill_model_name="base",
        perturbation=PerturbationConfig(),
        output_dir=tmp_path / "replay",
        run_name="round3_noop",
        round_number=3,
    )

    assert artefact.summary["fill_count"] == 0
    assert artefact.summary["final_pnl"] == 0
    assert artefact.summary["limit_breaches"] == 0
    assert all(position == 0 for position in artefact.summary["final_positions"].values())
    assert artefact.products == products_for_round(3)
    assert (tmp_path / "replay" / "dashboard.json").is_file()


def test_round3_aggressive_execution_and_fractional_mark(tmp_path):
    data_dir = tmp_path / "round3_tiny"
    _write_round3_tiny_dataset(data_dir)
    trader = _write_trader(
        tmp_path / "aggressive_round3.py",
        """
from datamodel import Order


class Trader:
    def run(self, state):
        return {"VEV_5000": [Order("VEV_5000", 11, 2)]}, 0, state.traderData
""",
    )

    artefact = run_replay(
        trader_spec=TraderSpec(name="aggressive_round3", path=trader),
        days=(0,),
        data_dir=data_dir,
        fill_model_name="optimistic",
        perturbation=PerturbationConfig(),
        output_dir=tmp_path / "aggressive_out",
        run_name="aggressive_out",
        round_number=3,
    )

    assert artefact.summary["fill_count"] == 2
    assert artefact.summary["per_product"]["VEV_5000"]["cash"] == -21.0
    assert artefact.summary["per_product"]["VEV_5000"]["final_position"] == 2
    assert [fill["price"] for fill in artefact.fills if fill["product"] == "VEV_5000"] == [10, 11]
    assert [fill["quantity"] for fill in artefact.fills if fill["product"] == "VEV_5000"] == [1, 1]
    pnl_row = next(row for row in artefact.pnl_series if row["product"] == "VEV_5000")
    assert pnl_row["mark"] == 10.5
    assert pnl_row["mid"] == 10.5


def test_round3_limit_enforcement_is_atomic_per_product(tmp_path):
    data_dir = tmp_path / "round3_tiny"
    _write_round3_tiny_dataset(data_dir)
    trader = _write_trader(
        tmp_path / "limit_round3.py",
        """
from datamodel import Order


class Trader:
    def run(self, state):
        return {
            "HYDROGEL_PACK": [Order("HYDROGEL_PACK", 100, 201)],
            "VEV_5000": [Order("VEV_5000", 10, 1)],
        }, 0, state.traderData
""",
    )

    artefact = run_replay(
        trader_spec=TraderSpec(name="limit_round3", path=trader),
        days=(0,),
        data_dir=data_dir,
        fill_model_name="optimistic",
        perturbation=PerturbationConfig(),
        output_dir=tmp_path / "limit_out",
        run_name="limit_out",
        round_number=3,
    )

    assert artefact.summary["limit_breaches"] == 1
    assert artefact.summary["per_product"]["HYDROGEL_PACK"]["final_position"] == 0
    assert artefact.summary["per_product"]["VEV_5000"]["final_position"] == 1
    assert any(fill["product"] == "VEV_5000" for fill in artefact.fills)


def test_round3_passive_fill_attribution_and_trade_matching_modes(tmp_path):
    data_dir = tmp_path / "round3_tiny"
    _write_round3_tiny_dataset(data_dir)
    trader = _write_trader(
        tmp_path / "passive_round3.py",
        """
from datamodel import Order


class Trader:
    def run(self, state):
        return {
            "HYDROGEL_PACK": [Order("HYDROGEL_PACK", 99, 1)],
            "VEV_5000": [Order("VEV_5000", 10, 1)],
        }, 0, state.traderData
""",
    )

    forced = PerturbationConfig(passive_fill_scale=10.0, missed_fill_additive=-1.0, trade_matching_mode="all")
    all_mode = run_replay(
        trader_spec=TraderSpec(name="passive_round3", path=trader),
        days=(0,),
        data_dir=data_dir,
        fill_model_name="optimistic",
        perturbation=forced,
        output_dir=tmp_path / "passive_all",
        run_name="passive_all",
        round_number=3,
    )
    none_mode = run_replay(
        trader_spec=TraderSpec(name="passive_round3", path=trader),
        days=(0,),
        data_dir=data_dir,
        fill_model_name="optimistic",
        perturbation=PerturbationConfig(passive_fill_scale=10.0, missed_fill_additive=-1.0, trade_matching_mode="none"),
        output_dir=tmp_path / "passive_none",
        run_name="passive_none",
        round_number=3,
    )
    worse_mode = run_replay(
        trader_spec=TraderSpec(name="passive_round3", path=trader),
        days=(0,),
        data_dir=data_dir,
        fill_model_name="optimistic",
        perturbation=PerturbationConfig(passive_fill_scale=10.0, missed_fill_additive=-1.0, trade_matching_mode="worse"),
        output_dir=tmp_path / "passive_worse",
        run_name="passive_worse",
        round_number=3,
    )

    aggressive_fill = next(fill for fill in all_mode.fills if fill["product"] == "VEV_5000")
    passive_fill = next(fill for fill in all_mode.fills if fill["product"] == "HYDROGEL_PACK")
    assert aggressive_fill["exact"] is True
    assert aggressive_fill["kind"] == "aggressive_visible"
    assert passive_fill["exact"] is False
    assert passive_fill["kind"] == "passive_approx"
    assert all(fill["product"] != "HYDROGEL_PACK" for fill in none_mode.fills)
    assert all(fill["product"] != "HYDROGEL_PACK" for fill in worse_mode.fills)


def test_round3_option_helpers_behave_robustly():
    assert intrinsic_value(5250, 5000) == 250
    assert time_value(270.0, 5250.0, 5000) == 20.0
    low = black_scholes_call_price(5250, 5000, 5 / 365.0, 0.2)
    high = black_scholes_call_price(5250, 5000, 5 / 365.0, 0.4)
    assert high > low > intrinsic_value(5250, 5000)
    implied = implied_vol_bisection(high, 5250, 5000, 5 / 365.0)
    assert implied is not None
    assert abs(implied - 0.4) < 1e-3
    assert implied_vol_bisection(0.0, 5250, 6500, 5 / 365.0) == 0.0
    assert implied_vol_bisection(10.0, 5250, 5000, 0.0) is None
    delta = call_delta(5250, 5000, 5 / 365.0, 0.3)
    assert delta is not None and 0.0 < delta < 1.0


def test_round3_synthetic_market_keeps_chain_coherent():
    historical = load_round_dataset(ROUND3_DATA, (0, 1, 2), round_number=3)
    perturbation = PerturbationConfig(
        synthetic_tick_limit=20,
        shock_tick=10,
        underlying_shock=120.0,
        option_residual_noise_scale=0.0,
        vol_shift=0.0,
        vol_scale=1.0,
    )
    market_days = generate_synthetic_market_days(
        days=(0,),
        seed=20260424,
        perturb=perturbation,
        round_spec=get_round_spec(3),
        historical_market_days=[historical[0], historical[1], historical[2]],
    )

    day = market_days[0]
    assert set(day.books_by_timestamp[0]) == set(products_for_round(3))
    pre_underlying = day.books_by_timestamp[0][ROUND3_UNDERLYING].mid
    post_underlying = day.books_by_timestamp[1000][ROUND3_UNDERLYING].mid
    pre_voucher = day.books_by_timestamp[0]["VEV_5000"].mid
    post_voucher = day.books_by_timestamp[1000]["VEV_5000"].mid
    assert post_underlying is not None and pre_underlying is not None and post_underlying > pre_underlying
    assert post_voucher is not None and pre_voucher is not None and post_voucher >= pre_voucher
    for snapshots in day.books_by_timestamp.values():
        for snapshot in snapshots.values():
            if snapshot.bids:
                assert snapshot.bids[0][0] >= 0
            if snapshot.asks:
                assert snapshot.asks[0][0] >= 0
            if snapshot.bids and snapshot.asks:
                assert snapshot.bids[0][0] < snapshot.asks[0][0]
