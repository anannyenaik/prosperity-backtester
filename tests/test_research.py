from __future__ import annotations

import json
import statistics
import subprocess
import sys
from pathlib import Path

import prosperity_backtester.experiments as experiments_module
import prosperity_backtester.reports as reports_module
from prosperity_backtester.__main__ import _days_from_args, build_parser
from prosperity_backtester.experiments import TraderSpec, _mc_runtime_context, run_monte_carlo
from prosperity_backtester.mc_backends import (
    ensure_rust_backend_binary,
    finalise_profile,
    merge_profile,
    new_profile,
    resolve_monte_carlo_backend,
    run_streaming_synthetic_session,
)
from prosperity_backtester.platform import PerturbationConfig
from prosperity_backtester.research import (
    get_research_pack_preset,
    profile_replay_suite,
    run_research_pack,
)
from prosperity_backtester.storage import OutputOptions
from prosperity_backtester.trader_adapter import install_datamodel_aliases, load_trader_module


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


def test_cli_defaults_follow_round_specs_for_routine_replay_and_compare():
    parser = build_parser()

    replay_args = parser.parse_args(["replay", "strategies/archive/legacy/trader.py"])
    compare_args = parser.parse_args(["compare", "strategies/archive/legacy/trader.py", "strategies/archive/legacy/starter.py"])
    round3_replay_args = parser.parse_args(["replay", "tests/fixtures/noop_round3_trader.py", "--round", "3"])

    assert replay_args.days is None
    assert compare_args.days == ["0"]
    assert _days_from_args(replay_args) == (-2, -1, 0)
    assert _days_from_args(compare_args) == (0,)
    assert _days_from_args(round3_replay_args) == (0, 1, 2)


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


def test_rust_backend_stays_close_to_classic_distribution_on_small_fixture(tmp_path):
    if ensure_rust_backend_binary() is None:
        return
    trader = _write_aggressive_trader(tmp_path / "aggressive_trader.py")
    common = {
        "trader_spec": TraderSpec(name="main", path=trader),
        "sessions": 12,
        "sample_sessions": 0,
        "days": (0,),
        "fill_model_name": "base",
        "perturbation": PerturbationConfig(synthetic_tick_limit=20),
        "base_seed": 20260418,
        "run_name": "mc_rust_backend_parity",
        "write_bundle": False,
    }

    classic = run_monte_carlo(
        **common,
        output_dir=tmp_path / "classic",
        monte_carlo_backend="classic",
    )
    rust = run_monte_carlo(
        **common,
        output_dir=tmp_path / "rust",
        monte_carlo_backend="rust",
    )

    classic_pnl = [session.summary["final_pnl"] for session in classic]
    rust_pnl = [session.summary["final_pnl"] for session in rust]
    classic_mean = statistics.fmean(classic_pnl)
    rust_mean = statistics.fmean(rust_pnl)

    assert len(classic) == len(rust) == 12
    assert {session.summary["fill_count"] for session in classic} == {session.summary["fill_count"] for session in rust}
    assert {session.summary["order_count"] for session in classic} == {session.summary["order_count"] for session in rust}
    assert classic[0].session_rows[0]["day"] == rust[0].session_rows[0]["day"]
    assert abs(rust_mean - classic_mean) / max(1.0, abs(classic_mean)) < 0.08


# ---------------------------------------------------------------------------
# MC profile accounting
# ---------------------------------------------------------------------------

def test_mc_profile_merge_and_finalise_accounting():
    profile = new_profile("streaming")
    update = {
        "market_generation_seconds": 0.5,
        "state_build_seconds": 0.1,
        "trader_seconds": 0.8,
        "execution_seconds": 0.2,
        "path_metrics_seconds": 0.05,
        "postprocess_seconds": 0.02,
        "session_total_seconds": 1.7,
        "session_count": 1,
    }
    merge_profile(profile, update, sampled=False, execution_backend="streaming")
    assert profile["session_count"] == 1
    assert profile["streaming_session_count"] == 1
    assert profile["sampled_session_count"] == 0
    assert profile["classic_session_count"] == 0

    merge_profile(profile, update, sampled=True, execution_backend="classic")
    assert profile["session_count"] == 2
    assert profile["streaming_session_count"] == 1
    assert profile["classic_session_count"] == 1
    assert profile["sampled_session_count"] == 1

    finalised = finalise_profile(profile)
    assert finalised["session_count"] == 2
    assert abs(finalised["trader_seconds"] - 1.6) < 1e-9
    assert abs(finalised["session_total_seconds"] - 3.4) < 1e-9
    assert "python_overhead_seconds" in finalised
    assert finalised["python_overhead_seconds"] >= 0.0


def test_mc_profile_python_overhead_clamps_to_zero():
    profile = new_profile("classic")
    # session_total_seconds less than component sum tests clamping to >= 0
    update = {
        "market_generation_seconds": 1.0,
        "state_build_seconds": 0.5,
        "trader_seconds": 2.0,
        "execution_seconds": 0.5,
        "path_metrics_seconds": 0.1,
        "postprocess_seconds": 0.1,
        "session_total_seconds": 1.0,
    }
    merge_profile(profile, update, sampled=False, execution_backend="classic")
    finalised = finalise_profile(profile)
    assert finalised["python_overhead_seconds"] >= 0.0


def test_mc_profile_rust_session_counter():
    profile = new_profile("rust")
    update = {
        "market_generation_seconds": 0.3,
        "state_build_seconds": 0.05,
        "trader_seconds": 0.6,
        "execution_seconds": 0.15,
        "path_metrics_seconds": 0.02,
        "postprocess_seconds": 0.01,
        "session_total_seconds": 1.1,
    }
    merge_profile(profile, update, sampled=False, execution_backend="rust")
    assert profile["rust_session_count"] == 1
    assert profile["classic_session_count"] == 0
    assert profile["streaming_session_count"] == 0


# ---------------------------------------------------------------------------
# Backend selection and resolution
# ---------------------------------------------------------------------------

def test_resolve_mc_backend_auto_always_returns_streaming():
    # auto must resolve to streaming regardless of Rust binary availability.
    # The Rust backend is slower at low worker counts due to per-tick IPC
    # overhead, so it must be requested explicitly with --mc-backend rust.
    backend = resolve_monte_carlo_backend("auto")
    assert backend == "streaming"


def test_resolve_mc_backend_auto_returns_streaming_even_when_rust_binary_present(monkeypatch):
    fake_binary = (Path(__file__).parent, Path(__file__).parent)
    monkeypatch.setattr(
        "prosperity_backtester.mc_backends.ensure_rust_backend_binary",
        lambda: fake_binary,
    )
    backend = resolve_monte_carlo_backend("auto")
    assert backend == "streaming", "auto must never silently select rust"


def test_resolve_mc_backend_falls_back_when_rust_unavailable(monkeypatch):
    monkeypatch.setattr(
        "prosperity_backtester.mc_backends.ensure_rust_backend_binary",
        lambda: None,
    )
    backend = resolve_monte_carlo_backend("auto")
    assert backend in {"streaming", "classic"}


def test_resolve_mc_backend_explicit_streaming_ignores_rust_availability(monkeypatch):
    monkeypatch.setattr(
        "prosperity_backtester.mc_backends.ensure_rust_backend_binary",
        lambda: None,
    )
    assert resolve_monte_carlo_backend("streaming") == "streaming"


def test_resolve_mc_backend_explicit_classic_ignores_rust_availability():
    assert resolve_monte_carlo_backend("classic") == "classic"


def test_resolve_mc_backend_rust_with_access_scenario_raises():
    import pytest
    from prosperity_backtester.round2 import AccessScenario
    access = AccessScenario(name="with_access", enabled=True, contract_won=True)
    with pytest.raises(ValueError, match="rust"):
        resolve_monte_carlo_backend("rust", access_scenario=access)


def test_mc_runtime_context_rust_sets_engine_and_parallelism():
    ctx = _mc_runtime_context(workers=4, sessions=100, sample_sessions=10, monte_carlo_backend="rust")
    assert ctx["engine_backend"] == "rust"
    assert ctx["parallelism"] == "rayon"
    assert ctx["monte_carlo_backend"] == "rust"


def test_mc_runtime_context_rust_single_worker_uses_single_thread():
    ctx = _mc_runtime_context(workers=1, sessions=50, sample_sessions=5, monte_carlo_backend="rust")
    assert ctx["engine_backend"] == "rust"
    assert ctx["parallelism"] == "single_thread"


def test_mc_runtime_context_streaming_sets_python_engine():
    ctx = _mc_runtime_context(workers=1, sessions=50, sample_sessions=5, monte_carlo_backend="streaming")
    assert ctx["engine_backend"] == "python"
    assert ctx["monte_carlo_backend"] == "streaming"


def test_mc_runtime_context_classic_multi_worker_uses_process_pool():
    ctx = _mc_runtime_context(workers=4, sessions=50, sample_sessions=5, monte_carlo_backend="classic")
    assert ctx["engine_backend"] == "python"
    assert ctx["parallelism"] == "process_pool"


def test_mc_runtime_context_no_sessions_clamps_workers():
    ctx = _mc_runtime_context(workers=8, sessions=0, sample_sessions=0, monte_carlo_backend="streaming")
    assert ctx["worker_count"] == 1
    assert ctx["parallelism"] == "single_process"


# ---------------------------------------------------------------------------
# Streaming backend reproducibility
# ---------------------------------------------------------------------------

def _make_live_trader(tmp_path: Path) -> object:
    path = tmp_path / "trader.py"
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
    install_datamodel_aliases()
    module = load_trader_module(path)
    return module.Trader()


def test_streaming_backend_same_seed_is_deterministic(tmp_path):
    from prosperity_backtester.fill_models import resolve_fill_model
    fill_model = resolve_fill_model("base")
    trader = _make_live_trader(tmp_path)
    kwargs = dict(
        trader=trader,
        trader_name="aggressive",
        fill_model=fill_model,
        perturb=PerturbationConfig(synthetic_tick_limit=50),
        days=(0,),
        market_seed=99991,
        execution_seed=88882,
        run_name="repro_test",
        path_bucket_count=0,
    )
    result1, _ = run_streaming_synthetic_session(**kwargs)
    result2, _ = run_streaming_synthetic_session(**kwargs)
    assert result1.summary == result2.summary
    assert result1.session_rows == result2.session_rows


def test_streaming_backend_profile_keys_complete_and_non_negative(tmp_path):
    from prosperity_backtester.fill_models import resolve_fill_model
    fill_model = resolve_fill_model("base")
    trader = _make_live_trader(tmp_path)
    _, profile = run_streaming_synthetic_session(
        trader=trader,
        trader_name="aggressive",
        fill_model=fill_model,
        perturb=PerturbationConfig(synthetic_tick_limit=30),
        days=(0,),
        market_seed=12345,
        execution_seed=67890,
        run_name="profile_test",
        path_bucket_count=0,
    )
    for key in (
        "market_generation_seconds",
        "state_build_seconds",
        "trader_seconds",
        "execution_seconds",
        "path_metrics_seconds",
        "postprocess_seconds",
        "session_total_seconds",
    ):
        assert key in profile, f"missing profile key: {key}"
        assert float(profile[key]) >= 0.0, f"negative timing for {key}: {profile[key]}"
    assert float(profile["session_total_seconds"]) > 0.0
    assert int(profile.get("session_count", 0)) == 1


def test_streaming_backend_multi_day_session_produces_one_row_per_day(tmp_path):
    from prosperity_backtester.fill_models import resolve_fill_model
    fill_model = resolve_fill_model("base")
    trader = _make_live_trader(tmp_path)
    result, _ = run_streaming_synthetic_session(
        trader=trader,
        trader_name="aggressive",
        fill_model=fill_model,
        perturb=PerturbationConfig(synthetic_tick_limit=20),
        days=(-2, -1, 0),
        market_seed=11111,
        execution_seed=22222,
        run_name="multi_day",
        path_bucket_count=0,
    )
    assert len(result.session_rows) == 3
    assert [row["day"] for row in result.session_rows] == [-2, -1, 0]


# ---------------------------------------------------------------------------
# rust_strategy_worker.py subprocess protocol
# ---------------------------------------------------------------------------

_WORKER_SCRIPT = Path(__file__).resolve().parent.parent / "prosperity_backtester" / "rust_strategy_worker.py"


def _write_pass_trader(path: Path) -> Path:
    path.write_text(
        """
class Trader:
    def run(self, state):
        return {}, 0, state.traderData
""".strip(),
        encoding="utf-8",
    )
    return path


def _make_run_request(*, timestamp: int = 0, trader_data: str = "") -> dict:
    return {
        "type": "run",
        "timestamp": timestamp,
        "trader_data": trader_data,
        "order_depths": {
            "ASH_COATED_OSMIUM": {"buy_orders": {"9998": 10}, "sell_orders": {"10002": -10}},
            "INTARIAN_PEPPER_ROOT": {"buy_orders": {"11998": 10}, "sell_orders": {"12002": -10}},
        },
        "own_trades": {"ASH_COATED_OSMIUM": [], "INTARIAN_PEPPER_ROOT": []},
        "market_trades": {"ASH_COATED_OSMIUM": [], "INTARIAN_PEPPER_ROOT": []},
        "position": {"ASH_COATED_OSMIUM": 0, "INTARIAN_PEPPER_ROOT": 0},
    }


def _exchange(proc: subprocess.Popen, msg: dict) -> dict:
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline().strip())


def test_rust_strategy_worker_handles_run_request(tmp_path):
    trader = _write_pass_trader(tmp_path / "pass_trader.py")
    proc = subprocess.Popen(
        [sys.executable, str(_WORKER_SCRIPT), str(trader)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        resp = _exchange(proc, _make_run_request())
        assert resp.get("error") is None
        assert "orders" in resp
        assert "trader_data" in resp
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


def test_rust_strategy_worker_reset_reinitialises_trader(tmp_path):
    trader = _write_pass_trader(tmp_path / "pass_trader.py")
    proc = subprocess.Popen(
        [sys.executable, str(_WORKER_SCRIPT), str(trader)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        reset_resp = _exchange(proc, {"type": "reset"})
        assert reset_resp.get("ok") is True
        run_resp = _exchange(proc, _make_run_request(timestamp=100))
        assert run_resp.get("error") is None
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


def test_rust_strategy_worker_propagates_trader_data(tmp_path):
    path = tmp_path / "stateful.py"
    path.write_text(
        """
class Trader:
    def run(self, state):
        count = int(state.traderData or "0") + 1
        return {}, 0, str(count)
""".strip(),
        encoding="utf-8",
    )
    proc = subprocess.Popen(
        [sys.executable, str(_WORKER_SCRIPT), str(path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        r1 = _exchange(proc, _make_run_request(timestamp=0))
        assert r1.get("trader_data") == "1"
        r2 = _exchange(proc, _make_run_request(timestamp=100, trader_data=r1["trader_data"]))
        assert r2.get("trader_data") == "2"
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


def test_rust_strategy_worker_reports_trader_exception(tmp_path):
    path = tmp_path / "crash_trader.py"
    path.write_text(
        """
class Trader:
    def run(self, state):
        raise RuntimeError("intentional crash")
""".strip(),
        encoding="utf-8",
    )
    proc = subprocess.Popen(
        [sys.executable, str(_WORKER_SCRIPT), str(path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        resp = _exchange(proc, _make_run_request())
        assert resp.get("error") is not None
        assert "intentional crash" in resp["error"]
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


def test_rust_strategy_worker_handles_unknown_request_type(tmp_path):
    trader = _write_pass_trader(tmp_path / "pass_trader.py")
    proc = subprocess.Popen(
        [sys.executable, str(_WORKER_SCRIPT), str(trader)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        resp = _exchange(proc, {"type": "unknown_type"})
        assert resp.get("error") is not None
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)
