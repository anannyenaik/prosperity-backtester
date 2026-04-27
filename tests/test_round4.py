from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

from prosperity_backtester.dataset import load_round_dataset
from prosperity_backtester.datamodel import Order
from prosperity_backtester.dataset import BookSnapshot, TradePrint
from prosperity_backtester.counterparty_research import _recommendation_rows
from prosperity_backtester.fill_models import resolve_fill_model
from prosperity_backtester.metadata import get_round_spec, products_for_round
from prosperity_backtester.platform import PerturbationConfig, ProductLedger, _execute_order_batch, generate_synthetic_market_days
from prosperity_backtester.round2 import NO_ACCESS_SCENARIO


ROOT = Path(__file__).resolve().parent.parent
ROUND4_DATA = ROOT / "data" / "round4"


def _run_single_order(
    *,
    order: Order,
    trades: list[TradePrint],
    snapshot: BookSnapshot | None = None,
    trade_matching_mode: str = "all",
    start_position: int = 0,
):
    spec = get_round_spec(4)
    ledger = ProductLedger(position=start_position)
    snapshot = snapshot or BookSnapshot(
        timestamp=0,
        product=order.symbol,
        bids=[(100, 20)],
        asks=[(102, 20)],
        mid=101.0,
        reference_fair=101.0,
        source_day=1,
    )
    fills, residual, limit_breach = _execute_order_batch(
        timestamp=0,
        product=order.symbol,
        snapshot=snapshot,
        trades=trades,
        ledger=ledger,
        orders=[order],
        fill_model=resolve_fill_model("optimistic"),
        perturb=PerturbationConfig(trade_matching_mode=trade_matching_mode),
        round_spec=spec,
        access_scenario=NO_ACCESS_SCENARIO,
        access_extra_fraction=0.0,
        rng=random.Random(7),
    )
    return fills, residual, limit_breach, ledger


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


def test_round4_named_trade_passive_buy_uses_book_direction_not_empty_names():
    fills, _residual, limit_breach, ledger = _run_single_order(
        order=Order("HYDROGEL_PACK", 100, 3),
        trades=[TradePrint(0, "Mark 01", "Mark 22", "HYDROGEL_PACK", 100.0, 5)],
    )

    assert limit_breach == 0
    assert ledger.position == 3
    assert fills[0]["side"] == "buy"
    assert fills[0]["kind"] == "passive_approx"
    assert fills[0]["market_trade_direction"] == "sell"
    assert fills[0]["market_trade_buyer"] == "Mark 01"
    assert fills[0]["market_trade_seller"] == "Mark 22"


def test_round4_named_trade_passive_sell_uses_book_direction_not_empty_names():
    fills, _residual, _limit_breach, ledger = _run_single_order(
        order=Order("HYDROGEL_PACK", 102, -4),
        trades=[TradePrint(0, "Mark 14", "Mark 38", "HYDROGEL_PACK", 102.0, 6)],
    )

    assert ledger.position == -4
    assert fills[0]["side"] == "sell"
    assert fills[0]["market_trade_direction"] == "buy"


def test_round4_passive_equal_price_modes_are_explicit():
    equal_trade = [TradePrint(0, "Mark 01", "Mark 22", "HYDROGEL_PACK", 100.0, 5)]
    all_fills, _residual, _limit_breach, _ledger = _run_single_order(
        order=Order("HYDROGEL_PACK", 100, 3),
        trades=equal_trade,
        trade_matching_mode="all",
    )
    worse_fills, _residual, _limit_breach, _ledger = _run_single_order(
        order=Order("HYDROGEL_PACK", 100, 3),
        trades=[TradePrint(0, "Mark 01", "Mark 22", "HYDROGEL_PACK", 100.0, 5)],
        trade_matching_mode="worse",
    )
    worse_price_fills, _residual, _limit_breach, _ledger = _run_single_order(
        order=Order("HYDROGEL_PACK", 100, 3),
        trades=[TradePrint(0, "Mark 01", "Mark 22", "HYDROGEL_PACK", 99.0, 5)],
        trade_matching_mode="worse",
    )

    assert len(all_fills) == 1
    assert worse_fills == []
    assert len(worse_price_fills) == 1


def test_round4_ambiguous_named_trade_inside_spread_does_not_fill():
    fills, residual, _limit_breach, ledger = _run_single_order(
        order=Order("HYDROGEL_PACK", 101, 3),
        trades=[TradePrint(0, "Mark 01", "Mark 22", "HYDROGEL_PACK", 101.0, 5)],
    )

    assert fills == []
    assert ledger.position == 0
    assert residual[0].quantity == 5


def test_round4_visible_cross_and_limit_cancellation():
    visible_fills, _residual, visible_breach, visible_ledger = _run_single_order(
        order=Order("HYDROGEL_PACK", 102, 7),
        trades=[],
    )
    cancelled_fills, _residual, cancel_breach, cancel_ledger = _run_single_order(
        order=Order("HYDROGEL_PACK", 102, 2),
        trades=[],
        start_position=199,
    )

    assert visible_breach == 0
    assert visible_ledger.position == 7
    assert visible_fills[0]["kind"] == "aggressive_visible"
    assert visible_fills[0]["price"] == 102
    assert cancel_breach == 1
    assert cancelled_fills == []
    assert cancel_ledger.position == 199


def test_round4_counterparty_recommendation_does_not_turn_below_cost_follow_into_fade():
    rows = _recommendation_rows(
        [
            {
                "counterparty": "Mark 01",
                "product": "VELVETFRUIT_EXTRACT",
                "product_group": "velvet",
                "side": "buy",
                "count": 40,
                "raw_markout_20": 0.10,
                "estimated_spread_adverse_cost_20": 0.25,
                "stability": "stable",
            },
            {
                "counterparty": "Mark 22",
                "product": "VELVETFRUIT_EXTRACT",
                "product_group": "velvet",
                "side": "sell",
                "count": 40,
                "raw_markout_20": -0.60,
                "estimated_spread_adverse_cost_20": 0.20,
                "stability": "stable",
            },
        ]
    )
    by_name = {row["counterparty"]: row for row in rows}

    assert by_name["Mark 01"]["follow_fade_ignore"] == "ignore"
    assert by_name["Mark 01"]["reason"] == "positive_raw_markout_below_cost_or_not_stable"
    assert by_name["Mark 22"]["follow_fade_ignore"] == "fade"


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

    manifest_dir = tmp_path / "manifest"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "prosperity_backtester",
            "r4-manifest",
            "--data-dir",
            str(ROUND4_DATA),
            "--output-dir",
            str(manifest_dir),
            "--days",
            "1",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    manifest = json.loads((manifest_dir / "manifest_report.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "pass"
    assert manifest["days"][0]["trade_rows"] == 1407
    assert (manifest_dir / "spread_depth_summary.csv").is_file()


def test_round4_verify_skip_mc_writes_report(tmp_path):
    output_dir = tmp_path / "verify"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "prosperity_backtester",
            "verify-round4",
            "--data-dir",
            str(ROUND4_DATA),
            "--output-dir",
            str(output_dir),
            "--days",
            "1",
            "--trader",
            str(tmp_path / "missing_trader.py"),
            "--skip-mc",
            "--fast",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads((output_dir / "verification_report.json").read_text(encoding="utf-8"))
    assert report["final_decision"]["candidate_promoted"] is False
    assert report["summary"]["overall_status"] == "pass"
    assert report["replay_scope"]["historical_tick_limit"] == 1200
    assert report["replay_scope"]["truncated"] is True
    assert (output_dir / "manifest" / "manifest_report.json").is_file()


def test_round4_synthetic_mc_has_named_flow_and_is_deterministic(tmp_path):
    spec = get_round_spec(4)
    dataset = load_round_dataset(ROUND4_DATA, (1,), round_number=4)
    historical_days = [dataset[1]]
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

    synthetic_again = generate_synthetic_market_days(
        days=(1,),
        seed=20260426,
        perturb=perturb,
        round_spec=spec,
        historical_market_days=historical_days,
    )[0]
    first_signature = [
        (
            ts,
            product,
            snapshot.mid,
            snapshot.bids[:1],
            snapshot.asks[:1],
            [
                (trade.price, trade.quantity, trade.buyer, trade.seller)
                for trade in synthetic.trades_by_timestamp.get(ts, {}).get(product, [])
            ],
        )
        for ts in synthetic.timestamps
        for product, snapshot in sorted(synthetic.books_by_timestamp.get(ts, {}).items())
    ]
    second_signature = [
        (
            ts,
            product,
            snapshot.mid,
            snapshot.bids[:1],
            snapshot.asks[:1],
            [
                (trade.price, trade.quantity, trade.buyer, trade.seller)
                for trade in synthetic_again.trades_by_timestamp.get(ts, {}).get(product, [])
            ],
        )
        for ts in synthetic_again.timestamps
        for product, snapshot in sorted(synthetic_again.books_by_timestamp.get(ts, {}).items())
    ]
    assert first_signature == second_signature
