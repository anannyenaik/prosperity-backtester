from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from prosperity_backtester.benchmark import render_benchmark_markdown, run_output_benchmark
from prosperity_backtester.experiments import TraderSpec, default_data_dir_for_round
from prosperity_backtester.noise import resolve_noise_profile
from prosperity_backtester.platform import PerturbationConfig


def _days_arg(values: list[str]) -> tuple[int, ...]:
    return tuple(int(value) for value in values)


def _default_output_dir() -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return Path.cwd() / "backtests" / f"{timestamp}_output_benchmark"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure representative replay and Monte Carlo bundle sizes")
    parser.add_argument("--trader", default=str(Path("examples") / "benchmark_trader.py"), help="Trader file to benchmark")
    parser.add_argument("--name", default="benchmark_trader", help="Display name for the trader")
    parser.add_argument("--round", type=int, default=1, choices=[1, 2], help="Competition round mode")
    parser.add_argument("--data-dir", default=None, help="Directory containing CSV inputs")
    parser.add_argument("--days", nargs="*", default=["0"], help="Day list, default 0")
    parser.add_argument("--fill-mode", default="base", help="Fill assumption preset")
    parser.add_argument("--noise-profile", default="fitted", choices=["none", "fitted", "baseline", "stress", "crash"], help="Latent Monte Carlo noise profile")
    parser.add_argument("--noise-scale", type=float, default=1.0, help="Multiplier around the selected latent noise profile")
    parser.add_argument("--sessions", type=int, default=4, help="Monte Carlo sessions per measured case")
    parser.add_argument("--sample-sessions", type=int, default=2, help="Saved sample sessions per measured Monte Carlo case")
    parser.add_argument("--fixture-timestamps", type=int, default=250, help="Retain this many timestamps per selected day in the temporary benchmark fixture")
    parser.add_argument("--workers", type=int, default=1, help="Monte Carlo worker processes")
    parser.add_argument("--seed", type=int, default=20260418, help="Base seed for Monte Carlo cases")
    parser.add_argument("--output-dir", default=None, help="Empty directory to write the measured bundles and reports")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir).resolve() if args.output_dir else _default_output_dir().resolve()
    data_dir = Path(args.data_dir).resolve() if args.data_dir else default_data_dir_for_round(args.round).resolve()
    trader_path = Path(args.trader).resolve()

    perturbation = PerturbationConfig(
        latent_price_noise_by_product=resolve_noise_profile(args.noise_profile, args.noise_scale),
        synthetic_tick_limit=args.fixture_timestamps,
        scenario_name="output_benchmark",
    )
    report = run_output_benchmark(
        output_root=output_dir,
        trader_spec=TraderSpec(name=args.name, path=trader_path),
        data_dir=data_dir,
        days=_days_arg(args.days),
        round_number=args.round,
        fill_model_name=args.fill_mode,
        perturbation=perturbation,
        mc_sessions=args.sessions,
        mc_sample_sessions=args.sample_sessions,
        mc_seed=args.seed,
        mc_workers=args.workers,
        fixture_timestamp_limit=args.fixture_timestamps,
    )

    print(f"Output benchmark: {output_dir}")
    print(render_benchmark_markdown(report))


if __name__ == "__main__":
    main()
