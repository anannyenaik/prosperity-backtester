from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Sequence

from .experiments import (
    DEFAULT_DATA_DIR,
    TraderSpec,
    calibrate_against_live_export,
    run_compare,
    run_monte_carlo,
    run_optimize_from_config,
    run_replay,
    run_sweep_from_config,
)
from .fill_models import FILL_MODELS
from .platform import PerturbationConfig
from .server import serve_directory

SUBCOMMANDS = {"replay", "monte-carlo", "compare", "sweep", "optimize", "calibrate", "inspect", "serve"}


def _timestamped_dir(root: Path, label: str) -> Path:
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return root / f"{ts}_{label}"


def _days_arg(values: Sequence[str]) -> Sequence[int]:
    return tuple(int(v) for v in values)


def _perturb_from_args(args) -> PerturbationConfig:
    return PerturbationConfig(
        passive_fill_scale=args.passive_fill_scale,
        missed_fill_additive=args.missed_fill_additive,
        spread_shift_ticks=args.spread_shift_ticks,
        order_book_volume_scale=args.order_book_volume_scale,
        price_noise_std=args.price_noise_std,
        pepper_slope_scale=args.pepper_slope_scale,
        latency_ticks=args.latency_ticks,
        adverse_selection_ticks=args.adverse_selection_ticks,
        reentry_probability=args.reentry_probability,
        inventory_limit_scale=args.inventory_limit_scale,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Round 1 team-grade backtesting and Monte Carlo platform")
    sub = parser.add_subparsers(dest="command")

    def add_shared(subparser):
        subparser.add_argument("trader", help="Trader python file")
        subparser.add_argument("--name", default=None, help="Display name for the trader")
        subparser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="Directory containing round 1 CSVs")
        subparser.add_argument("--days", nargs="*", default=["-2", "-1", "0"], help="Day list, default -2 -1 0")
        subparser.add_argument("--fill-mode", default="base", choices=sorted(FILL_MODELS), help="Passive fill assumption preset")
        subparser.add_argument("--output-dir", default=None, help="Output directory. Default is backtests/<timestamp>_<label>")
        subparser.add_argument("--passive-fill-scale", type=float, default=1.0)
        subparser.add_argument("--missed-fill-additive", type=float, default=0.0)
        subparser.add_argument("--spread-shift-ticks", type=int, default=0)
        subparser.add_argument("--order-book-volume-scale", type=float, default=1.0)
        subparser.add_argument("--price-noise-std", type=float, default=0.0)
        subparser.add_argument("--pepper-slope-scale", type=float, default=1.0)
        subparser.add_argument("--latency-ticks", type=int, default=0)
        subparser.add_argument("--adverse-selection-ticks", type=int, default=0)
        subparser.add_argument("--reentry-probability", type=float, default=1.0)
        subparser.add_argument("--inventory-limit-scale", type=float, default=1.0)

    replay = sub.add_parser("replay", help="Replay one trader on historical round 1 days")
    add_shared(replay)
    replay.add_argument("--live-export", default=None, help="Optional website export .log/.json to validate against")

    mc = sub.add_parser("monte-carlo", help="Run Monte Carlo robustness sessions")
    add_shared(mc)
    mc.add_argument("--sessions", type=int, default=100)
    mc.add_argument("--sample-sessions", type=int, default=10)
    mc.add_argument("--seed", type=int, default=20260418)
    mc.add_argument("--workers", type=int, default=1, help="Parallel worker processes for Monte Carlo sessions")
    mc.add_argument("--quick", action="store_true", help="Use team quick preset: 64 sessions, 8 saved samples")
    mc.add_argument("--heavy", action="store_true", help="Use team heavy preset: 512 sessions, 32 saved samples")

    compare = sub.add_parser("compare", help="Compare multiple traders side by side on replay")
    compare.add_argument("traders", nargs="+", help="Trader python files")
    compare.add_argument("--names", nargs="*", default=None, help="Optional display names")
    compare.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    compare.add_argument("--days", nargs="*", default=["-2", "-1", "0"])
    compare.add_argument("--fill-mode", default="base", choices=sorted(FILL_MODELS))
    compare.add_argument("--output-dir", default=None)
    compare.add_argument("--passive-fill-scale", type=float, default=1.0)
    compare.add_argument("--missed-fill-additive", type=float, default=0.0)
    compare.add_argument("--spread-shift-ticks", type=int, default=0)
    compare.add_argument("--order-book-volume-scale", type=float, default=1.0)
    compare.add_argument("--price-noise-std", type=float, default=0.0)
    compare.add_argument("--pepper-slope-scale", type=float, default=1.0)
    compare.add_argument("--latency-ticks", type=int, default=0)
    compare.add_argument("--adverse-selection-ticks", type=int, default=0)
    compare.add_argument("--reentry-probability", type=float, default=1.0)
    compare.add_argument("--inventory-limit-scale", type=float, default=1.0)

    sweep = sub.add_parser("sweep", help="Run a named parameter sweep from JSON config")
    sweep.add_argument("config", help="Path to sweep JSON config")
    sweep.add_argument("--output-dir", default=None)

    optimize = sub.add_parser("optimize", help="Run replay + Monte Carlo parameter optimisation from JSON config")
    optimize.add_argument("config", help="Path to optimization JSON config")
    optimize.add_argument("--output-dir", default=None)

    calibrate = sub.add_parser("calibrate", help="Grid-search fill assumptions against a live export")
    calibrate.add_argument("trader", help="Trader python file")
    calibrate.add_argument("--name", default=None)
    calibrate.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    calibrate.add_argument("--days", nargs="*", default=["0"])
    calibrate.add_argument("--live-export", required=True)
    calibrate.add_argument("--output-dir", default=None)
    calibrate.add_argument("--quick", action="store_true", help="Use a smaller calibration grid for fast local iteration")

    inspect = sub.add_parser("inspect", help="Print a concise dataset inspection report")
    inspect.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    inspect.add_argument("--days", nargs="*", default=["-2", "-1", "0"])
    inspect.add_argument("--json", action="store_true")

    serve = sub.add_parser("serve", help="Serve the local dashboard frontend")
    serve.add_argument("--dir", default=str(Path(__file__).resolve().parent.parent))
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=5555)

    return parser


def _trader_spec(path: str, name: str | None) -> TraderSpec:
    trader_path = Path(path).resolve()
    return TraderSpec(name=name or trader_path.stem, path=trader_path)


def _print_replay_result(artefact) -> None:
    print(f"Run: {artefact.run_name}")
    print(f"Trader: {artefact.trader_name}")
    print(f"Final PnL: {artefact.summary['final_pnl']:,.2f}")
    print(f"Max drawdown: {artefact.summary.get('max_drawdown', 0.0):,.2f}")
    for product, product_summary in artefact.summary["per_product"].items():
        behaviour = artefact.behaviour.get("per_product", {}).get(product, {})
        print(
            f"  {product}: mtm={product_summary['final_mtm']:,.2f} realised={product_summary['realised']:,.2f} "
            f"pos={product_summary['final_position']} fills={sum(1 for fill in artefact.fills if fill['product'] == product)} "
            f"cap_usage={behaviour.get('cap_usage_ratio', 0.0):.2f} markout5={behaviour.get('average_fill_markout_5')}"
        )
    print(f"Order count: {artefact.summary.get('order_count', 0)}")
    print(f"Fill count: {artefact.summary['fill_count']}")
    print(f"Limit breaches: {artefact.summary['limit_breaches']}")


def _handle_legacy(trader_path: str) -> None:
    output_dir = _timestamped_dir(Path.cwd() / "backtests", "legacy_mc")
    results = run_monte_carlo(
        trader_spec=_trader_spec(trader_path, None),
        sessions=64,
        sample_sessions=8,
        days=_days_arg(["-2", "-1", "0"]),
        fill_model_name="base",
        perturbation=PerturbationConfig(),
        output_dir=output_dir,
        base_seed=20260418,
        run_name="legacy_mc",
        workers=1,
    )
    finals = [result.summary["final_pnl"] for result in results]
    print(f"Legacy Monte Carlo mean PnL: {sum(finals)/len(finals):,.2f}")
    print(f"Output bundle: {output_dir}")


def main(argv: List[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and not argv[0].startswith("-") and argv[0] not in SUBCOMMANDS:
        _handle_legacy(argv[0])
        return

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "replay":
        output_dir = Path(args.output_dir).resolve() if args.output_dir else _timestamped_dir(Path.cwd() / "backtests", "replay")
        artefact = run_replay(
            trader_spec=_trader_spec(args.trader, args.name),
            days=_days_arg(args.days),
            data_dir=Path(args.data_dir),
            fill_model_name=args.fill_mode,
            perturbation=_perturb_from_args(args),
            output_dir=output_dir,
            run_name=output_dir.name,
            live_export_path=Path(args.live_export).resolve() if args.live_export else None,
        )
        _print_replay_result(artefact)
        print(f"Output bundle: {output_dir}")
        if artefact.validation:
            print(f"Validation: {json.dumps(artefact.validation, indent=2)}")
        return

    if args.command == "monte-carlo":
        output_dir = Path(args.output_dir).resolve() if args.output_dir else _timestamped_dir(Path.cwd() / "backtests", "mc")
        sessions = args.sessions
        sample_sessions = args.sample_sessions
        if args.quick:
            sessions, sample_sessions = 64, 8
        if args.heavy:
            sessions, sample_sessions = 512, 32
        results = run_monte_carlo(
            trader_spec=_trader_spec(args.trader, args.name),
            sessions=sessions,
            sample_sessions=sample_sessions,
            days=_days_arg(args.days),
            fill_model_name=args.fill_mode,
            perturbation=_perturb_from_args(args),
            output_dir=output_dir,
            base_seed=args.seed,
            run_name=output_dir.name,
            workers=args.workers,
        )
        finals = [result.summary["final_pnl"] for result in results]
        print(f"Sessions: {len(finals)}")
        print(f"Mean PnL: {sum(finals)/len(finals):,.2f}")
        print(f"Min / Max: {min(finals):,.2f} / {max(finals):,.2f}")
        print(f"Output bundle: {output_dir}")
        return

    if args.command == "compare":
        output_dir = Path(args.output_dir).resolve() if args.output_dir else _timestamped_dir(Path.cwd() / "backtests", "compare")
        names = args.names or []
        trader_specs = [
            _trader_spec(path, names[idx] if idx < len(names) else None)
            for idx, path in enumerate(args.traders)
        ]
        rows = run_compare(
            trader_specs=trader_specs,
            days=_days_arg(args.days),
            data_dir=Path(args.data_dir),
            fill_model_name=args.fill_mode,
            perturbation=_perturb_from_args(args),
            output_dir=output_dir,
            run_name=output_dir.name,
        )
        print(f"Compared {len(rows)} traders")
        for row in rows:
            print(f"  {row['trader']}: pnl={row['final_pnl']:,.2f} drawdown={row['max_drawdown']:,.2f}")
        print(f"Output bundle: {output_dir}")
        return

    if args.command == "sweep":
        output_dir = Path(args.output_dir).resolve() if args.output_dir else _timestamped_dir(Path.cwd() / "backtests", "sweep")
        rows = run_sweep_from_config(Path(args.config).resolve(), output_dir)
        print(f"Sweep variants: {len(rows)}")
        for row in rows:
            print(f"  {row['trader']}: {row['final_pnl']:,.2f}")
        print(f"Output bundle: {output_dir}")
        return

    if args.command == "optimize":
        output_dir = Path(args.output_dir).resolve() if args.output_dir else _timestamped_dir(Path.cwd() / "backtests", "optimize")
        rows = run_optimize_from_config(Path(args.config).resolve(), output_dir)
        print(f"Optimized variants: {len(rows)}")
        for row in rows[:5]:
            print(f"  {row['variant']}: score={row['score']:,.2f} replay={row['replay_final_pnl']:,.2f} mc_p05={row['mc_p05']:,.2f}")
        print(f"Output bundle: {output_dir}")
        return

    if args.command == "calibrate":
        output_dir = Path(args.output_dir).resolve() if args.output_dir else _timestamped_dir(Path.cwd() / "backtests", "calibrate")
        best = calibrate_against_live_export(
            trader_spec=_trader_spec(args.trader, args.name),
            days=_days_arg(args.days),
            data_dir=Path(args.data_dir),
            live_export_path=Path(args.live_export).resolve(),
            output_dir=output_dir,
            quick=args.quick,
        )
        print(f"Best calibration: {json.dumps(best, indent=2)}")
        print(f"Output bundle: {output_dir}")
        return

    if args.command == "inspect":
        from .dataset import load_round1_dataset
        dataset = load_round1_dataset(Path(args.data_dir), _days_arg(args.days))
        payload = {day: day_dataset.validation for day, day_dataset in dataset.items()}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            for day, validation in payload.items():
                print(f"Day {day}: {validation}")
        return

    if args.command == "serve":
        serve_directory(Path(args.dir), host=args.host, port=args.port)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
