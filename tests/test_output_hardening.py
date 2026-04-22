from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest

from prosperity_backtester.__main__ import _output_options_from_args, _perturb_from_args, build_parser
from prosperity_backtester.bundle_attribution import build_bundle_attribution
from prosperity_backtester.dashboard_payload import normalise_dashboard_payload
from prosperity_backtester.experiments import TraderSpec, run_compare, run_monte_carlo, run_replay, run_sweep_from_config
from prosperity_backtester.metadata import PRODUCTS
from prosperity_backtester.platform import PerturbationConfig, SessionArtefacts
from prosperity_backtester.reports import (
    build_dashboard_payload,
    accumulate_path_band_rows,
    finalize_path_band_accumulator,
    new_path_band_accumulator,
)
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


def test_monte_carlo_sample_runs_are_explicit_preview_caps_in_light_mode():
    options = OutputOptions.from_profile("light")
    per_product = {
        product: {
            "final_mtm": float(product_idx),
            "final_position": 0,
        }
        for product_idx, product in enumerate(PRODUCTS)
    }
    rows_per_product = 180
    inventory_rows = []
    pnl_rows = []
    fair_rows = []
    fill_rows = []
    behaviour_rows = []
    for product_idx, product in enumerate(PRODUCTS):
        for idx in range(rows_per_product):
            timestamp = idx * 100
            inventory_rows.append({
                "day": 0,
                "timestamp": timestamp,
                "product": product,
                "position": idx,
                "avg_entry_price": 10_000 + product_idx,
                "mid": 10_000 + product_idx,
                "fair": 10_000 + product_idx,
            })
            pnl_rows.append({
                "day": 0,
                "timestamp": timestamp,
                "product": product,
                "cash": float(idx),
                "realised": float(idx),
                "unrealised": float(idx) / 2,
                "mtm": float(idx),
                "mark": 10_000 + product_idx,
                "mid": 10_000 + product_idx,
                "fair": 10_000 + product_idx,
                "spread": 2.0,
                "position": idx,
            })
            fair_rows.append({
                "day": 0,
                "timestamp": timestamp,
                "product": product,
                "analysis_fair": 10_000 + product_idx,
                "mid": 10_000 + product_idx,
            })
            fill_rows.append({
                "day": 0,
                "timestamp": timestamp,
                "product": product,
                "side": "buy" if idx % 2 == 0 else "sell",
                "price": 10_000 + product_idx,
                "quantity": 1,
                "kind": "aggressive_visible",
                "exact": True,
                "source_trade_price": 10_000 + product_idx,
                "mid": 10_000 + product_idx,
                "reference_fair": 10_000 + product_idx,
                "best_bid": 9_999 + product_idx,
                "best_ask": 10_001 + product_idx,
                "markout_1": 0.0,
                "markout_5": 0.0,
                "analysis_fair": 10_000 + product_idx,
                "signed_edge_to_analysis_fair": 0.0,
            })
            behaviour_rows.append({
                "day": 0,
                "timestamp": timestamp,
                "product": product,
                "order_count": 1,
                "fill_count": 1,
                "net_fill_qty": 1,
                "aggressive_fill_count": 1,
                "passive_fill_count": 0,
                "abs_position_ratio": 0.1,
                "buy_order_qty": 1,
                "sell_order_qty": 0,
                "buy_fill_qty": 1,
                "sell_fill_qty": 0,
            })
    result = SessionArtefacts(
        run_name="mc_session_preview",
        trader_name="starter",
        mode="monte_carlo",
        fill_model={"name": "base"},
        perturbations={},
        summary={
                "final_pnl": 1.0,
                "gross_pnl_before_maf": 1.0,
                "maf_cost": 0.0,
                "fill_count": len(fill_rows),
                "order_count": 0,
                "limit_breaches": 0,
                "max_drawdown": 0.0,
                "per_product": per_product,
        },
        session_rows=[{"day": 0}],
        inventory_series=inventory_rows,
        pnl_series=pnl_rows,
        fair_value_series=fair_rows,
        fills=fill_rows,
        orders=[],
        behaviour={"summary": {}, "per_product": {}, "series": behaviour_rows},
        behaviour_series=behaviour_rows,
    )
    dashboard = build_dashboard_payload(
        run_type="monte_carlo",
        run_name="mc",
        trader_name="starter",
        mode="monte_carlo",
        fill_model={"name": "base"},
        perturbations={},
        monte_carlo_results=[result],
        output_options=options,
    )

    sample = dashboard["monteCarlo"]["sampleRuns"][0]
    assert sample["pnlSeriesPreviewTruncated"] is True
    assert sample["pnlSeriesTotalCount"] == len(pnl_rows)
    assert len(sample["pnlSeries"]) == options.max_sample_preview_rows_per_series
    assert sample["fairValueSeriesPreviewTruncated"] is True
    assert sample["fillsPreviewTruncated"] is True
    assert sample["behaviourSeriesPreviewTruncated"] is True


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


def test_precomputed_path_bands_keep_all_session_method_even_when_rows_are_cleared():
    results = [_fake_mc_session(idx, sampled=idx < 2) for idx in range(3)]
    accumulator = new_path_band_accumulator()
    for result in results:
        accumulate_path_band_rows(accumulator, result.path_metrics)
        result.path_metrics = []
    dashboard = build_dashboard_payload(
        run_type="monte_carlo",
        run_name="mc",
        trader_name="starter",
        mode="monte_carlo",
        fill_model={"name": "base"},
        perturbations={},
        monte_carlo_results=results,
        monte_carlo_path_bands=finalize_path_band_accumulator(accumulator),
        output_options=OutputOptions.from_profile("light"),
    )

    assert dashboard["monteCarlo"]["pathBandMethod"]["source"] == "all_sessions"
    pepper_bands = dashboard["monteCarlo"]["pathBands"]["analysisFair"]["INTARIAN_PEPPER_ROOT"]
    assert pepper_bands[0]["sessionCount"] == 3


def test_written_mc_dashboard_uses_compact_storage_and_manifest_attribution(tmp_path):
    data_dir = tmp_path / "data"
    trader = _write_aggressive_trader(tmp_path / "aggressive_trader.py")
    _write_tiny_dataset(data_dir, ticks=6)

    run_monte_carlo(
        trader_spec=TraderSpec(name="tiny", path=trader),
        sessions=2,
        sample_sessions=1,
        days=(0,),
        fill_model_name="base",
        perturbation=PerturbationConfig(synthetic_tick_limit=6),
        output_dir=tmp_path / "mc",
        base_seed=20260418,
        run_name="mc",
    )

    raw_dashboard = json.loads((tmp_path / "mc" / "dashboard.json").read_text(encoding="utf-8"))
    assert raw_dashboard["monteCarlo"]["sessions"]["encoding"] == "row_table_v1"
    assert raw_dashboard["monteCarlo"]["sampleRuns"][0]["pnlSeries"]["encoding"] == "row_table_v1"
    assert "fairValueBands" not in raw_dashboard["monteCarlo"]

    dashboard = normalise_dashboard_payload(raw_dashboard)
    assert isinstance(dashboard["monteCarlo"]["sessions"], list)
    assert isinstance(dashboard["monteCarlo"]["sampleRuns"][0]["pnlSeries"], list)

    manifest = json.loads((tmp_path / "mc" / "manifest.json").read_text(encoding="utf-8"))
    attribution = build_bundle_attribution(raw_dashboard, manifest["bundle_files"])
    assert any(row["component"] == "monteCarlo.sampleRuns" for row in attribution["dashboard_sections"])
    assert any(row["component"] == "dashboard_payload" for row in attribution["file_components"])


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


def test_cli_limit_overrides_and_print_flag_are_parsed():
    parser = build_parser()
    args = parser.parse_args([
        'replay',
        'strategies/trader.py',
        '--limit',
        'ASH_COATED_OSMIUM:60',
        '--limit',
        'INTARIAN_PEPPER_ROOT:40',
        '--print-trader-output',
    ])

    perturbation = _perturb_from_args(args)

    assert perturbation.position_limits_by_product == {
        'ASH_COATED_OSMIUM': 60,
        'INTARIAN_PEPPER_ROOT': 40,
    }
    assert args.print_trader_output is True


def test_cli_aliases_and_mc_backend_are_parsed():
    parser = build_parser()

    replay_args = parser.parse_args([
        'replay',
        'strategies/trader.py',
        '--vis',
        '--print',
    ])
    mc_args = parser.parse_args([
        'monte-carlo',
        'strategies/trader.py',
        '--mc-backend',
        'classic',
    ])

    assert replay_args.open is True
    assert replay_args.print_trader_output is True
    assert mc_args.mc_backend == 'classic'


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
