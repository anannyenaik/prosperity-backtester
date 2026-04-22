from __future__ import annotations

from pathlib import Path

from prosperity_backtester.benchmark import run_output_benchmark
from prosperity_backtester.experiments import TraderSpec
from prosperity_backtester.platform import PerturbationConfig


def _write_tiny_dataset(data_dir: Path, *, ticks: int = 4) -> None:
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


def test_output_benchmark_reports_light_vs_full_bundle_shapes(tmp_path):
    data_dir = tmp_path / "data"
    trader = _write_aggressive_trader(tmp_path / "aggressive_trader.py")
    _write_tiny_dataset(data_dir)

    report = run_output_benchmark(
        output_root=tmp_path / "benchmark",
        trader_spec=TraderSpec(name="tiny", path=trader),
        data_dir=data_dir,
        days=(0,),
        round_number=1,
        fill_model_name="base",
        perturbation=PerturbationConfig(),
        mc_sessions=2,
        mc_sample_sessions=1,
        fixture_timestamp_limit=4,
    )

    by_case = {case["case"]: case for case in report["cases"]}
    assert set(by_case) == {"replay_light", "replay_full", "mc_light", "mc_full"}
    assert by_case["replay_light"]["bundle_size_bytes"] < by_case["replay_full"]["bundle_size_bytes"]
    assert by_case["mc_light"]["bundle_size_bytes"] < by_case["mc_full"]["bundle_size_bytes"]
    assert "orders.csv" not in by_case["replay_light"]["debug_files"]
    assert "orders.csv" in by_case["replay_full"]["debug_files"]
    assert by_case["mc_light"]["debug_files"] == []
    assert any(path.startswith("sample_paths/") for path in by_case["mc_full"]["debug_files"])
    assert any(path.startswith("sessions/") for path in by_case["mc_full"]["debug_files"])
    assert report["repo_root"]
    assert report["python_executable"]
    assert isinstance(report["git_dirty"], bool)
    assert report["mc_workers"] == 1
    assert report["caveats"]
    assert (tmp_path / "benchmark" / "benchmark_report.json").is_file()
    assert (tmp_path / "benchmark" / "benchmark_report.md").is_file()
