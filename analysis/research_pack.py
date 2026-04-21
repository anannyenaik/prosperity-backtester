from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from prosperity_backtester.experiments import TraderSpec, default_data_dir_for_round
from prosperity_backtester.research import default_fill_mode_for_round, run_research_pack
from prosperity_backtester.storage import prune_old_auto_runs, validate_keep_count


def _timestamped_dir(root: Path, label: str) -> Path:
    return root / f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{label}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the fast, validation or forensic research pack")
    parser.add_argument("preset", choices=["fast", "validation", "forensic"])
    parser.add_argument("--trader", default="strategies/trader.py", help="Trader python file")
    parser.add_argument("--baseline", default="strategies/starter.py", help="Baseline trader for the compare bundle")
    parser.add_argument("--round", type=int, default=1, choices=[1, 2], help="Competition round mode")
    parser.add_argument("--data-dir", default=None, help="Directory containing CSVs")
    parser.add_argument("--fill-mode", default=None, help="Fill model override")
    parser.add_argument("--mc-workers", type=int, default=1, help="Parallel worker processes for Monte Carlo sessions")
    parser.add_argument("--output-dir", default=None, help="Output directory. Default is backtests/<timestamp>_<preset>_pack_<trader>")
    parser.add_argument("--keep-runs", type=int, default=30, help="When using the default backtests/ output root, keep this many timestamped pack roots")
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
        output_dir = _timestamped_dir(Path.cwd() / "backtests", f"{args.preset}_pack_{trader_name}")
        auto_output = True
    summary = run_research_pack(
        preset_name=args.preset,
        trader_spec=TraderSpec(name=trader_name, path=trader_path),
        baseline_spec=TraderSpec(name=Path(args.baseline).stem, path=Path(args.baseline).resolve()),
        output_root=output_dir,
        round_number=args.round,
        data_dir=Path(args.data_dir).resolve() if args.data_dir else default_data_dir_for_round(args.round),
        fill_model_name=args.fill_mode or default_fill_mode_for_round(args.round),
        mc_workers=args.mc_workers,
    )
    if auto_output:
        prune_old_auto_runs(output_dir.parent, keep_runs)
    print(f"Pack: {args.preset}")
    print(f"Output root: {output_dir}")
    print(f"Replay final PnL: {summary['replay']['final_pnl']:,.2f}")
    print(f"Compare winner: {summary['comparison']['best_trader']}")
    print(f"Monte Carlo mean: {summary['monte_carlo']['summary'].get('mean', 0.0):,.2f}")
    print(json.dumps(summary["preset"], indent=2))


if __name__ == "__main__":
    main()
