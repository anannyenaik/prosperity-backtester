from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[1]
    repo_root_text = str(repo_root)
    if repo_root_text not in sys.path:
        sys.path.insert(0, repo_root_text)

from prosperity_backtester.experiments import DEFAULT_DATA_DIR, TraderSpec, calibrate_against_live_export


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate replay fill assumptions against a live export")
    parser.add_argument("trader", help="Trader python file")
    parser.add_argument("--name", default=None)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--days", nargs="*", default=["0"])
    parser.add_argument("--live-export", required=True)
    parser.add_argument("--output-dir", default="backtests/calibration_report")
    args = parser.parse_args()

    best = calibrate_against_live_export(
        trader_spec=TraderSpec(name=args.name or Path(args.trader).stem, path=Path(args.trader).resolve()),
        days=tuple(int(day) for day in args.days),
        data_dir=Path(args.data_dir),
        live_export_path=Path(args.live_export).resolve(),
        output_dir=Path(args.output_dir).resolve(),
    )
    print(best)


if __name__ == "__main__":
    main()
