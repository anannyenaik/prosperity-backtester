from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest

from prosperity_backtester.__main__ import _output_options_from_args, build_parser
from prosperity_backtester.experiments import TraderSpec, run_compare, run_replay, run_sweep_from_config
from prosperity_backtester.metadata import PRODUCTS
from prosperity_backtester.platform import PerturbationConfig, SessionArtefacts
from prosperity_backtester.reports import build_dashboard_payload
from prosperity_backtester.storage import OutputOptions, prune_old_auto_runs


def _write_tiny_dataset(data_dir: Path, *, ticks: int = 6) -> None:
    data_dir.mkdir(parents=True)
    header = (
        "day;timestamp;product;"
        "bid_price_1;bid_volume_1;bid_price_2;bid_volume_2;bid_price_3;bid_volume_3;"
        "ask_price_1;ask_volume_1;ask_price_2;ask_volume_2;ask_price_3;ask_volume_3;"
        "mid_price;profit_and_loss\n"
    )
    rows = []
    for tick in range(ticks):
        ts = tick * 100
        rows.extend([
            f"0;{ts};ASH_COATED_OSMIUM;9998;10;;;;;10002;10;;;;;10000;0\n",
            f"0;{ts};INTARIAN_PEPPER_ROOT;11998;10;;;;;12002;10;;;;;12000;0\n",
        ])
    (data_dir / "prices_round_1_day_0.csv").write_text(header + "".join(rows), encoding="utf-8")
    (data_dir / "trades_round_1_day_0.csv").write_text(
        "timestamp;buyer;seller;symbol;currency;price;quantity\n",
        encoding="utf-8",
    )


def _write_aggressive_trader(path: Path) -> Path:
    path.write_text(
        """
from datamodel import Order


class Trader:
    def run(self, state):
        orders = {}
        for product, depth in state.order_depths.items():
            asks = depth.sell_orders
            orders[product] = [Order(product, min(asks), 1)] if asks else []
        return orders, 0, state.traderData
""".strip(),
        encoding="utf-8",
    )
    return path


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_replay_light_and_full_keep_exact_summaries_and_fills(tmp_path):
    data_dir = tmp_path / "data"
    trader = _write_aggressive_trader(tmp_path / "aggressive_trader.py")
    _write_tiny_dataset(data_dir)

    light = run_replay(
        trader_spec=TraderSpec(name="tiny", path=trader),
        days=(0,),
        data_dir=data_dir,
        fill_model_name="base",
        perturbation=PerturbationConfig(),
        output_dir=tmp_path / "light",
        run_name="light",
        output_options=OutputOptions.from_profile("light"),
    )
    full = run_replay(
        trader_spec=TraderSpec(name="tiny", path=trader),
        days=(0,),
        data_dir=data_dir,
        fill_model_name="base",
        perturbation=PerturbationConfig(),
        output_dir=tmp_path / "full",
        run_name="full",
        output_options=OutputOptions.from_profile("full"),
    )

    assert light.summary == full.summary
    assert _read_csv(tmp_path / "light" / "fills.csv") == _read_csv(tmp_path / "full" / "fills.csv")
    assert not (tmp_path / "light" / "orders.csv").exists()
    assert not (tmp_path / "light" / "pnl_series.csv").exists()
    assert (tmp_path / "full" / "orders.csv").is_file()
    assert (tmp_path / "full" / "pnl_series.csv").is_file()


def test_light_bundle_contains_compact_order_intent(tmp_path):
    data_dir = tmp_path / "data"
    trader = _write_aggressive_trader(tmp_path / "aggressive_trader.py")
    _write_tiny_dataset(data_dir, ticks=3)

    run_replay(
        trader_spec=TraderSpec(name="tiny", path=trader),
        days=(0,),
        data_dir=data_dir,
        fill_model_name="base",
        perturbation=PerturbationConfig(),
        output_dir=tmp_path / "light",
        run_name="light",
        output_options=OutputOptions.from_profile("light"),
    )
    dashboard = json.loads((tmp_path / "light" / "dashboard.json").read_text(encoding="utf-8"))

    assert "orders" not in dashboard
    assert dashboard["orderIntent"]
    first = dashboard["orderIntent"][0]
    assert first["best_submitted_bid"] is not None
    assert first["signed_submitted_quantity"] > 0
    assert first["aggressive_submitted_quantity"] > 0
    assert first["order_row_count"] >= 1


def _fake_mc_session(idx: int, *, sampled: bool) -> SessionArtefacts:
    per_product = {
        product: {
            "final_mtm": float(idx * 10 + product_idx),
            "final_position": idx,
        }
        for product_idx, product in enumerate(PRODUCTS)
    }
    path_metrics = []
    for product_idx, product in enumerate(PRODUCTS):
        value = 100.0 + idx * 10 + product_idx
        path_metrics.append({
            "day": 0,
            "timestamp": 100,
            "product": product,
            "bucket_index": 0,
            "bucket_start_timestamp": 0,
            "bucket_end_timestamp": 100,
            "bucket_count": 2,
            "analysis_fair": value,
            "analysis_fair_bucket_min": value - 1,
            "analysis_fair_bucket_max": value + 1,
            "mid": value + 0.5,
            "mid_bucket_min": value - 0.5,
            "mid_bucket_max": value + 1.5,
            "inventory": idx,
            "inventory_bucket_min": idx - 1,
            "inventory_bucket_max": idx,
            "pnl": idx * 100.0,
            "pnl_bucket_min": idx * 100.0 - 5,
            "pnl_bucket_max": idx * 100.0 + 5,
        })
    return SessionArtefacts(
        run_name=f"mc_session_{idx}",
        trader_name="starter",
        mode="monte_carlo",
        fill_model={"name": "base"},
        perturbations={},
        summary={
            "final_pnl": float(idx * 100),
            "gross_pnl_before_maf": float(idx * 100),
            "maf_cost": 0.0,
            "fill_count": idx,
            "order_count": idx,
            "limit_breaches": 0,
            "max_drawdown": float(idx),
            "per_product": per_product,
        },
        session_rows=[{"day": 0}],
        inventory_series=[{"day": 0, "timestamp": 100, "product": PRODUCTS[0], "position": idx}] if sampled else [],
        pnl_series=[{"day": 0, "timestamp": 100, "product": PRODUCTS[0], "mtm": idx * 100.0}] if sampled else [],
        fair_value_series=[{"day": 0, "timestamp": 100, "product": PRODUCTS[0], "analysis_fair": 100.0 + idx, "mid": 101.0 + idx}] if sampled else [],
        fair_value_summary={},
        behaviour={"summary": {}, "per_product": {}, "series": []},
        path_metrics=path_metrics,
    )


def _mc_dashboard(results: list[SessionArtefacts]) -> dict[str, object]:
    return build_dashboard_payload(
        run_type="monte_carlo",
        run_name="mc",
        trader_name="starter",
        mode="monte_carlo",
        fill_model={"name": "base"},
        perturbations={},
        monte_carlo_results=results,
        output_options=OutputOptions.from_profile("light"),
    )


def test_monte_carlo_summary_and_path_bands_ignore_sample_count():
    sample_0 = _mc_dashboard([_fake_mc_session(idx, sampled=False) for idx in range(3)])
    sample_2 = _mc_dashboard([_fake_mc_session(idx, sampled=idx < 2) for idx in range(3)])

    assert sample_0["monteCarlo"]["summary"] == sample_2["monteCarlo"]["summary"]
    assert sample_0["monteCarlo"]["pathBands"] == sample_2["monteCarlo"]["pathBands"]
    assert sample_2["monteCarlo"]["pathBandMethod"]["source"] == "all_sessions"
    pepper_bands = sample_2["monteCarlo"]["pathBands"]["analysisFair"]["INTARIAN_PEPPER_ROOT"]
    assert pepper_bands
    assert pepper_bands[0]["sessionCount"] == 3
    assert sample_2["monteCarlo"]["fairValueBands"]["analysisFair"] == sample_2["monteCarlo"]["pathBands"]["analysisFair"]


def test_full_profile_child_bundles_require_explicit_request(tmp_path):
    data_dir = tmp_path / "data"
    trader = _write_aggressive_trader(tmp_path / "aggressive_trader.py")
    _write_tiny_dataset(data_dir, ticks=2)

    run_compare(
        trader_specs=[TraderSpec(name="a", path=trader), TraderSpec(name="b", path=trader)],
        days=(0,),
        data_dir=data_dir,
        fill_model_name="base",
        perturbation=PerturbationConfig(),
        output_dir=tmp_path / "full_default",
        run_name="compare",
        output_options=OutputOptions.from_profile("full"),
    )
    assert not (tmp_path / "full_default" / "a").exists()

    run_compare(
        trader_specs=[TraderSpec(name="a", path=trader), TraderSpec(name="b", path=trader)],
        days=(0,),
        data_dir=data_dir,
        fill_model_name="base",
        perturbation=PerturbationConfig(),
        output_dir=tmp_path / "full_child",
        run_name="compare",
        output_options=OutputOptions.from_profile("full", write_child_bundles=True),
    )
    assert (tmp_path / "full_child" / "a" / "dashboard.json").is_file()


def test_config_output_policy_overrides_are_applied(tmp_path):
    data_dir = tmp_path / "data"
    trader = _write_aggressive_trader(tmp_path / "aggressive_trader.py")
    _write_tiny_dataset(data_dir, ticks=2)
    config = {
        "name": "tiny_sweep",
        "trader": str(trader),
        "data_dir": str(data_dir),
        "days": [0],
        "fill_model": "base",
        "output_profile": "full",
        "save_child_bundles": False,
        "write_series_csvs": False,
        "pretty_json": True,
        "variants": [{"name": "a"}, {"name": "b"}],
    }
    config_path = tmp_path / "sweep.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    run_sweep_from_config(config_path, tmp_path / "sweep_out")
    dashboard = json.loads((tmp_path / "sweep_out" / "dashboard.json").read_text(encoding="utf-8"))

    assert dashboard["meta"]["outputProfile"]["profile"] == "full"
    assert dashboard["meta"]["outputProfile"]["write_child_bundles"] is False
    assert dashboard["meta"]["outputProfile"]["write_series_csvs"] is False
    assert not (tmp_path / "sweep_out" / "a").exists()
    assert "\n  " in (tmp_path / "sweep_out" / "dashboard.json").read_text(encoding="utf-8")


def test_cli_output_policy_flags_can_disable_full_debug_extras():
    parser = build_parser()
    args = parser.parse_args([
        "monte-carlo",
        "strategies/trader.py",
        "--output-profile",
        "full",
        "--no-series-sidecars",
        "--no-orders",
        "--no-sample-path-files",
        "--no-session-manifests",
    ])

    options = _output_options_from_args(args)

    assert options.profile == "full"
    assert options.write_series_csvs is False
    assert options.include_orders is False
    assert options.write_sample_path_files is False
    assert options.write_session_manifests is False


def test_prune_uses_folder_timestamp_not_mtime_and_validates_keep(tmp_path):
    older = tmp_path / "2026-04-18_00-00-00_replay"
    newer = tmp_path / "2026-04-19_00-00-00_replay"
    manual = tmp_path / "round2_all_in_one_research_bundle"
    for path in (older, newer, manual):
        path.mkdir()
        (path / "dashboard.json").write_text("{}", encoding="utf-8")
    os.utime(older, (20, 20))
    os.utime(newer, (10, 10))

    removed = prune_old_auto_runs(tmp_path, keep=1)

    assert removed == [older.resolve()]
    assert newer.exists()
    assert manual.exists()
    with pytest.raises(ValueError, match="at least 1"):
        prune_old_auto_runs(tmp_path, keep=0)


def test_prune_uses_manifest_created_at_when_name_timestamp_is_invalid(tmp_path):
    invalid_newer = tmp_path / "2026-99-99_00-00-00_replay"
    valid_older = tmp_path / "2026-04-18_00-00-00_replay"
    for path in (invalid_newer, valid_older):
        path.mkdir()
        (path / "dashboard.json").write_text("{}", encoding="utf-8")
    (invalid_newer / "manifest.json").write_text(
        json.dumps({"created_at": "2026-04-20T00:00:00+00:00"}),
        encoding="utf-8",
    )

    removed = prune_old_auto_runs(tmp_path, keep=1)

    assert removed == [valid_older.resolve()]
    assert invalid_newer.exists()
