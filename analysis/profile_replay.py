from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from prosperity_backtester.experiments import TraderSpec, default_data_dir_for_round
from prosperity_backtester.research import default_fill_mode_for_round, profile_replay_suite
from prosperity_backtester.platform import PerturbationConfig
from prosperity_backtester.storage import OutputOptions, prune_old_auto_runs, validate_keep_count


def _timestamped_dir(root: Path, label: str) -> Path:
    return root / f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{label}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Profile replay slowdown by day with step timings")
    parser.add_argument("trader", nargs="?", default="strategies/trader.py", help="Trader python file")
    parser.add_argument("--compare-trader", default="strategies/starter.py", help="Optional comparison trader for the slowest day")
    parser.add_argument("--days", nargs="*", default=["-2", "-1", "0"], help="Day list to profile, default -2 -1 0")
    parser.add_argument("--round", type=int, default=1, choices=[1, 2], help="Competition round mode")
    parser.add_argument("--data-dir", default=None, help="Directory containing CSVs")
    parser.add_argument("--fill-mode", default=None, help="Fill model override")
    parser.add_argument("--output-dir", default=None, help="Output directory. Default is backtests/<timestamp>_profile_replay_<trader>")
    parser.add_argument("--keep-runs", type=int, default=30, help="When using the default backtests/ output root, keep this many timestamped profile roots")
    parser.add_argument("--no-write-bundles", action="store_true", help="Measure the replay steps without writing output bundles")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    keep_runs = validate_keep_count(args.keep_runs)
    trader_path = Path(args.trader).resolve()
    trader_name = trader_path.stem
    if args.output_dir:
        output_dir = Path(args.output_dir).resolve()
        auto_output = False
    else:
        output_dir = _timestamped_dir(Path.cwd() / "backtests", f"profile_replay_{trader_name}")
        auto_output = True
    report = profile_replay_suite(
        trader_spec=TraderSpec(name=trader_name, path=trader_path),
        compare_trader_spec=(
            None
            if not args.compare_trader
            else TraderSpec(name=Path(args.compare_trader).stem, path=Path(args.compare_trader).resolve())
        ),
        days=tuple(int(day) for day in args.days),
        data_dir=Path(args.data_dir).resolve() if args.data_dir else default_data_dir_for_round(args.round),
        fill_model_name=args.fill_mode or default_fill_mode_for_round(args.round),
        perturbation=PerturbationConfig(),
        round_number=args.round,
        output_root=output_dir,
        output_options=OutputOptions.from_profile("light"),
        write_bundle=not args.no_write_bundles,
    )
    if auto_output:
        prune_old_auto_runs(output_dir.parent, keep_runs)
    print(f"Slowest day: {report['slowest_day']}")
    print(json.dumps(report["diagnosis"], indent=2))
    if report["comparison_case"] is not None:
        compare = report["comparison_case"]
        print(
            f"Slowest-day comparison trader {compare['trader']}: "
            f"{compare['timings']['total_seconds']:.3f}s total, "
            f"{compare['timings']['run_market_session_seconds']:.3f}s market session"
        )
    print(f"Profile report: {output_dir / 'profile_report.json'}")


if __name__ == "__main__":
    main()
