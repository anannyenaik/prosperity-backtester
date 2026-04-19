from __future__ import annotations

import argparse
from pathlib import Path

from r1bt.experiments import DEFAULT_DATA_DIR, TraderSpec, run_replay
from r1bt.platform import PerturbationConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a trader against round 1 replay or a live export")
    parser.add_argument("trader", help="Trader python file")
    parser.add_argument("--name", default=None)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--days", nargs="*", default=["-2", "-1", "0"])
    parser.add_argument("--live-export", default=None)
    parser.add_argument("--output-dir", default="backtests/validation_report")
    parser.add_argument("--fill-mode", default="base")
    args = parser.parse_args()

    artefact = run_replay(
        trader_spec=TraderSpec(name=args.name or Path(args.trader).stem, path=Path(args.trader).resolve()),
        days=tuple(int(day) for day in args.days),
        data_dir=Path(args.data_dir),
        fill_model_name=args.fill_mode,
        perturbation=PerturbationConfig(),
        output_dir=Path(args.output_dir).resolve(),
        run_name="validation_report",
        live_export_path=Path(args.live_export).resolve() if args.live_export else None,
    )
    print(artefact.summary)
    if artefact.validation:
        print(artefact.validation)


if __name__ == "__main__":
    main()
