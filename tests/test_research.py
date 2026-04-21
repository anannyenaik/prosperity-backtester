from __future__ import annotations

import json
from pathlib import Path

import prosperity_backtester.experiments as experiments_module
import prosperity_backtester.reports as reports_module
from prosperity_backtester.__main__ import build_parser
from prosperity_backtester.experiments import TraderSpec, run_monte_carlo
from prosperity_backtester.platform import PerturbationConfig
from prosperity_backtester.research import (
    get_research_pack_preset,
    profile_replay_suite,
    run_research_pack,
)
from prosperity_backtester.storage import OutputOptions


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


def test_research_pack_fast_writes_only_core_bundles(tmp_path):
    data_dir = tmp_path / "data"
    trader = _write_aggressive_trader(tmp_path / "aggressive_trader.py")
    baseline = _write_aggressive_trader(tmp_path / "baseline_trader.py")
    _write_tiny_dataset(data_dir)

    summary = run_research_pack(
        preset_name="fast",
        trader_spec=TraderSpec(name="main", path=trader),
        baseline_spec=TraderSpec(name="baseline", path=baseline),
        output_root=tmp_path / "fast_pack",
        round_number=1,
        data_dir=data_dir,
        fill_model_name="base",
        perturbation=PerturbationConfig(),
    )

    assert (tmp_path / "fast_pack" / "replay" / "dashboard.json").is_file()
    assert (tmp_path / "fast_pack" / "compare" / "dashboard.json").is_file()
    assert (tmp_path / "fast_pack" / "monte_carlo" / "dashboard.json").is_file()
    assert (tmp_path / "fast_pack" / "pack_summary.json").is_file()
    assert summary["preset"]["name"] == "fast"
    assert tuple(summary["preset"]["replay_days"]) == (0,)
    assert summary["preset"]["mc_synthetic_tick_limit"] == 250
    assert not (tmp_path / "fast_pack" / "calibration").exists()


def test_profile_replay_suite_writes_day_breakdown_report(tmp_path):
    data_dir = tmp_path / "data"
    trader = _write_aggressive_trader(tmp_path / "aggressive_trader.py")
    baseline = _write_aggressive_trader(tmp_path / "baseline_trader.py")
    _write_tiny_dataset(data_dir)

    report = profile_replay_suite(
        trader_spec=TraderSpec(name="main", path=trader),
        compare_trader_spec=TraderSpec(name="baseline", path=baseline),
        days=(0,),
        data_dir=data_dir,
        fill_model_name="base",
        perturbation=PerturbationConfig(),
        output_root=tmp_path / "profile",
    )

    assert report["slowest_day"] == 0
    assert report["rows"][0]["timings"]["run_market_session_seconds"] >= 0.0
    assert report["rows"][0]["timings"]["total_seconds"] >= report["rows"][0]["timings"]["run_market_session_seconds"]
    assert report["comparison_case"]["day"] == 0
    saved = json.loads((tmp_path / "profile" / "profile_report.json").read_text(encoding="utf-8"))
    assert saved["diagnosis"]["dominant_day"] == 0


def test_cli_defaults_favour_day_zero_for_routine_replay_and_compare():
    parser = build_parser()

    replay_args = parser.parse_args(["replay", "strategies/trader.py"])
    compare_args = parser.parse_args(["compare", "strategies/trader.py", "strategies/starter.py"])

    assert replay_args.days == ["0"]
    assert compare_args.days == ["0"]


def test_fast_and_forensic_presets_stay_separate():
    fast = get_research_pack_preset("fast")
    forensic = get_research_pack_preset("forensic")

    assert fast.replay_output_profile == "light"
    assert fast.mc_output_profile == "light"
    assert fast.mc_synthetic_tick_limit == 250
    assert forensic.replay_output_profile == "full"
    assert forensic.mc_output_profile == "full"
    assert forensic.mc_synthetic_tick_limit is None


def test_monte_carlo_reuses_sample_session_compaction(tmp_path, monkeypatch):
    trader = _write_aggressive_trader(tmp_path / "aggressive_trader.py")
    call_count = 0
    original = reports_module.compact_replay_rows

    def counted_compaction(artefact, options):
        nonlocal call_count
        call_count += 1
        return original(artefact, options)

    monkeypatch.setattr(reports_module, "compact_replay_rows", counted_compaction)
    monkeypatch.setattr(experiments_module, "compact_replay_rows", counted_compaction)

    run_monte_carlo(
        trader_spec=TraderSpec(name="main", path=trader),
        sessions=2,
        sample_sessions=1,
        days=(0,),
        fill_model_name="base",
        perturbation=PerturbationConfig(synthetic_tick_limit=20),
        output_dir=tmp_path / "mc",
        base_seed=20260418,
        run_name="mc_compaction_cache",
        output_options=OutputOptions.from_profile("light"),
    )

    assert call_count == 1


def test_streaming_backend_matches_classic_backend_for_unsampled_sessions(tmp_path):
    trader = _write_aggressive_trader(tmp_path / "aggressive_trader.py")
    common = {
        "trader_spec": TraderSpec(name="main", path=trader),
        "sessions": 3,
        "sample_sessions": 0,
        "days": (0,),
        "fill_model_name": "base",
        "perturbation": PerturbationConfig(synthetic_tick_limit=20),
        "base_seed": 20260418,
        "run_name": "mc_backend_parity",
        "write_bundle": False,
    }

    classic = run_monte_carlo(
        **common,
        output_dir=tmp_path / "classic",
        monte_carlo_backend="classic",
    )
    streaming = run_monte_carlo(
        **common,
        output_dir=tmp_path / "streaming",
        monte_carlo_backend="streaming",
    )

    assert [session.summary for session in classic] == [session.summary for session in streaming]
    assert [session.session_rows for session in classic] == [session.session_rows for session in streaming]
    assert [session.path_metrics for session in classic] == [session.path_metrics for session in streaming]
