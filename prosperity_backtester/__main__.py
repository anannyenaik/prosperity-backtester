from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import List, Sequence

from .experiments import (
    DEFAULT_DATA_DIR,
    DEFAULT_ROUND2_DATA_DIR,
    TraderSpec,
    calibrate_against_live_export,
    default_data_dir_for_round,
    run_compare,
    run_monte_carlo,
    run_optimize_from_config,
    run_replay,
    run_round2_scenario_compare_from_config,
    run_scenario_compare_from_config,
    run_sweep_from_config,
)
from .fill_models import FILL_MODELS, derive_empirical_fill_profile
from .noise import resolve_noise_profile
from .platform import PerturbationConfig
from .round2 import AccessScenario
from .server import serve_directory
from .storage import OutputOptions, prune_old_auto_runs, validate_keep_count

SUBCOMMANDS = {
    "replay",
    "monte-carlo",
    "compare",
    "sweep",
    "optimize",
    "calibrate",
    "inspect",
    "serve",
    "round2-scenarios",
    "scenario-compare",
    "derive-fill-profile",
    "workspace-bundle",
    "clean",
}

RUN_TYPE_ALIASES = {
    "replay": "replay",
    "mc": "monte_carlo",
    "montecarlo": "monte_carlo",
    "monte-carlo": "monte_carlo",
    "monte_carlo": "monte_carlo",
    "compare": "comparison",
    "comparison": "comparison",
    "calibrate": "calibration",
    "calibration": "calibration",
    "optimize": "optimization",
    "optimise": "optimization",
    "optimization": "optimization",
    "optimisation": "optimization",
    "round2": "round2_scenarios",
    "round2-scenarios": "round2_scenarios",
    "round2_scenarios": "round2_scenarios",
    "scenario-compare": "scenario_compare",
    "scenario_compare": "scenario_compare",
    "workspace": "workspace",
    "workspace-bundle": "workspace",
    "all-in-one": "workspace",
    "all_in_one": "workspace",
}


class _CliFormatter(argparse.RawDescriptionHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
    pass


def _timestamped_dir(root: Path, label: str) -> Path:
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return root / f"{ts}_{label}"


def _slug(text: str, *, max_length: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    if not slug:
        return "run"
    return slug[:max_length].rstrip("_") or "run"


def _output_options_from_args(args) -> OutputOptions:
    config = {"output_profile": getattr(args, "output_profile", None) or "light"}
    save_child_bundles = getattr(args, "save_child_bundles", None)
    if save_child_bundles is not None:
        config["save_child_bundles"] = bool(save_child_bundles)
    if getattr(args, "series_sidecars", None) is not None:
        config["write_series_csvs"] = bool(args.series_sidecars)
    if getattr(args, "orders", None) is not None:
        config["include_orders"] = bool(args.orders)
    if getattr(args, "sample_path_files", None) is not None:
        config["write_sample_path_files"] = bool(args.sample_path_files)
    if getattr(args, "session_manifests", None) is not None:
        config["write_session_manifests"] = bool(args.session_manifests)
    if getattr(args, "pretty_json", None) is not None:
        config["pretty_json"] = bool(args.pretty_json)
    return OutputOptions.from_config(config)


def _has_output_policy_override(args) -> bool:
    return any(
        getattr(args, name, None) is not None
        for name in (
            "output_profile",
            "save_child_bundles",
            "series_sidecars",
            "orders",
            "sample_path_files",
            "session_manifests",
            "pretty_json",
        )
    )


def _default_auto_label(args, label: str) -> str:
    if args.command in {"replay", "monte-carlo", "calibrate"}:
        trader_name = getattr(args, "name", None) or Path(str(getattr(args, "trader", "run"))).stem
        return f"{label}_{_slug(str(trader_name))}"
    if args.command == "compare":
        traders = [Path(path).stem for path in getattr(args, "traders", [])]
        names = list(getattr(args, "names", None) or [])
        display = names[:2] if names else traders[:2]
        joined = "_vs_".join(_slug(name) for name in display if name)
        return f"{label}_{joined or 'comparison'}"
    if args.command in {"sweep", "optimize", "round2-scenarios", "scenario-compare"}:
        return f"{label}_{_slug(Path(str(getattr(args, 'config', label))).stem)}"
    if args.command == "derive-fill-profile":
        return f"{label}_{_slug(str(getattr(args, 'profile_name', 'empirical')))}"
    return label


def _auto_output_dir(args, label: str) -> tuple[Path, bool]:
    explicit = getattr(args, "output_dir", None)
    if explicit:
        return Path(explicit).resolve(), False
    return _timestamped_dir(Path.cwd() / "backtests", _default_auto_label(args, label)), True


def _prune_after_auto_run(output_dir: Path, was_auto: bool, keep_runs: int) -> None:
    if not was_auto:
        return
    removed = prune_old_auto_runs(output_dir.parent, validate_keep_count(keep_runs))
    if removed:
        print(f"Pruned old auto backtest runs: {len(removed)}")


def _days_arg(values: Sequence[str]) -> Sequence[int]:
    return tuple(int(v) for v in values)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
        return validate_keep_count(parsed)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _limit_override(value: str) -> tuple[str, int]:
    product, separator, limit_text = str(value).partition(":")
    if not separator or not product.strip() or not limit_text.strip():
        raise argparse.ArgumentTypeError("limit overrides must look like PRODUCT:LIMIT")
    try:
        limit = int(limit_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid limit override {value!r}: {exc}") from exc
    if limit < 1:
        raise argparse.ArgumentTypeError("limit overrides must be at least 1")
    return product.strip(), limit


def _normalise_run_type(value: str | None) -> str | None:
    if value is None:
        return None
    key = str(value).strip().lower()
    if not key:
        return None
    normalised = RUN_TYPE_ALIASES.get(key)
    if normalised is None:
        choices = ", ".join(sorted(set(RUN_TYPE_ALIASES)))
        raise argparse.ArgumentTypeError(f"unknown run type {value!r}. Choose one of: {choices}")
    return normalised


def _perturb_from_args(args) -> PerturbationConfig:
    noise_profile = getattr(args, "noise_profile", "none")
    noise_scale = float(getattr(args, "noise_scale", 1.0))
    limit_overrides = {
        product: limit
        for product, limit in getattr(args, "limit_overrides", []) or []
    }
    return PerturbationConfig(
        passive_fill_scale=args.passive_fill_scale,
        missed_fill_additive=args.missed_fill_additive,
        spread_shift_ticks=args.spread_shift_ticks,
        order_book_volume_scale=args.order_book_volume_scale,
        price_noise_std=args.price_noise_std,
        latent_price_noise_by_product=resolve_noise_profile(noise_profile, noise_scale),
        latent_noise_scale=float(getattr(args, "latent_noise_scale", 1.0)),
        pepper_slope_scale=args.pepper_slope_scale,
        latency_ticks=args.latency_ticks,
        adverse_selection_ticks=args.adverse_selection_ticks,
        slippage_multiplier=args.slippage_multiplier,
        reentry_probability=args.reentry_probability,
        trade_matching_mode=str(getattr(args, "match_trades", "all")),
        inventory_limit_scale=args.inventory_limit_scale,
        position_limits_by_product=limit_overrides,
        synthetic_tick_limit=getattr(args, "synthetic_tick_limit", None),
        scenario_name=str(getattr(args, "scenario_name", "cli")),
    )


def _data_dir_from_args(args) -> Path:
    explicit = getattr(args, "data_dir", None)
    return Path(explicit) if explicit else default_data_dir_for_round(int(getattr(args, "round", 1)))


def _open_bundle(output_dir: Path) -> None:
    output_dir = output_dir.resolve()
    root = output_dir.parent
    dashboard_path = output_dir / "dashboard.json"
    query = urllib.parse.urlencode({"run": str(dashboard_path.relative_to(root)).replace("\\", "/")})
    serve_directory(root, open_browser=True, query=query)


def _open_latest(directory: Path, run_type: str | None, *, host: str, port: int) -> None:
    params = {"latest": "1"}
    if run_type:
        params["latestType"] = run_type
    query = urllib.parse.urlencode(params)
    serve_directory(directory, host=host, port=port, open_browser=True, query=query)


def _access_from_args(args) -> AccessScenario:
    enabled = bool(getattr(args, "with_extra_access", False)) or str(getattr(args, "access_mode", "none")) != "none"
    contract_won = bool(getattr(args, "contract_won", False)) or enabled
    mode = str(getattr(args, "access_mode", "deterministic" if enabled else "none"))
    if not enabled:
        mode = "none"
        contract_won = False
    return AccessScenario(
        name=str(getattr(args, "access_name", None) or ("extra_access" if enabled else "no_access")),
        enabled=enabled,
        contract_won=contract_won,
        mode=mode,
        maf_bid=float(getattr(args, "maf_bid", 0.0)),
        extra_quote_fraction=float(getattr(args, "extra_quote_fraction", 0.25)),
        access_quality=float(getattr(args, "access_quality", 1.0)),
        access_probability=float(getattr(args, "access_probability", 1.0)),
        book_volume_share=float(getattr(args, "access_book_volume_share", 1.0)),
        passive_fill_rate_multiplier=float(getattr(args, "access_passive_multiplier", 1.0)),
        passive_fill_rate_bonus=float(getattr(args, "access_passive_bonus", 0.0)),
        missed_fill_reduction=float(getattr(args, "access_missed_reduction", 0.0)),
        trade_volume_share=float(getattr(args, "access_trade_volume_share", 1.0)),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prosperity replay, Monte Carlo and Round 2 research platform",
        formatter_class=_CliFormatter,
        epilog=(
            "Examples:\n"
            "  python -m prosperity_backtester replay strategies/r2_algo_v2_optimised.py --round 2 --data-dir data/round2 --days -1 0 1 --fill-mode base\n"
            "  python -m prosperity_backtester compare strategies/r2_algo_v2_optimised.py strategies/r2_algo_v2.py --names optimised submitted --round 2 --data-dir data/round2 --days -1 0 1 --fill-mode base --merge-pnl\n"
            "  python -m prosperity_backtester monte-carlo strategies/r2_algo_v2_optimised.py --round 2 --data-dir data/round2 --days 0 --quick --noise-profile fitted\n"
            "  python -m prosperity_backtester serve --latest-type replay\n"
        ),
    )
    sub = parser.add_subparsers(dest="command")

    def add_round_and_access(subparser):
        subparser.add_argument("--round", type=int, default=1, choices=[1, 2], help="Competition round mode")
        subparser.add_argument("--with-extra-access", action="store_true", help="Enable the local Round 2 extra-quote access assumption")
        subparser.add_argument("--contract-won", action="store_true", help="Assume the MAF contract is won and the fee is paid")
        subparser.add_argument("--access-name", default=None, help="Display name for the local access scenario")
        subparser.add_argument("--access-mode", default="none", choices=["none", "deterministic", "stochastic"])
        subparser.add_argument("--maf-bid", type=float, default=0.0)
        subparser.add_argument("--extra-quote-fraction", type=float, default=0.25)
        subparser.add_argument("--access-quality", type=float, default=1.0)
        subparser.add_argument("--access-probability", type=float, default=1.0)
        subparser.add_argument("--access-book-volume-share", type=float, default=1.0)
        subparser.add_argument("--access-passive-multiplier", type=float, default=1.0)
        subparser.add_argument("--access-passive-bonus", type=float, default=0.0)
        subparser.add_argument("--access-missed-reduction", type=float, default=0.0)
        subparser.add_argument("--access-trade-volume-share", type=float, default=1.0)

    def add_output_controls(subparser, *, child_bundles: bool = False):
        subparser.add_argument("--output-profile", choices=["light", "full"], default=None, help="Bundle detail level. Default is light unless a config sets output_profile.")
        if child_bundles:
            subparser.add_argument("--save-child-bundles", action=argparse.BooleanOptionalAction, default=None, help="Write per-variant/per-scenario child replay and Monte Carlo bundles")
        subparser.add_argument("--series-sidecars", action=argparse.BooleanOptionalAction, default=None, help="Write chart-series CSV sidecars. Full profile enables this by default.")
        subparser.add_argument("--orders", action=argparse.BooleanOptionalAction, default=None, help="Write raw submitted order rows. Full profile enables this by default.")
        subparser.add_argument("--sample-path-files", action=argparse.BooleanOptionalAction, default=None, help="Write duplicate Monte Carlo sample_paths/ files. Full profile enables this by default.")
        subparser.add_argument("--session-manifests", action=argparse.BooleanOptionalAction, default=None, help="Write one Monte Carlo session manifest per sampled session. Full profile enables this by default.")
        subparser.add_argument("--pretty-json", action=argparse.BooleanOptionalAction, default=None, help="Write indented dashboard and manifest JSON for debugging")
        subparser.add_argument("--keep-runs", type=_positive_int, default=30, help="When using the default backtests/ output root, keep this many timestamped runs")
        subparser.add_argument("--open", "--vis", dest="open", action="store_true", help="Serve the written bundle locally and open it in the dashboard")

    def add_shared(subparser):
        subparser.add_argument("trader", help="Trader python file")
        subparser.add_argument("--name", default=None, help="Display name for the trader")
        subparser.add_argument("--data-dir", "--data", dest="data_dir", default=None, help=f"Directory containing CSVs. Defaults: round 1 {DEFAULT_DATA_DIR}, round 2 {DEFAULT_ROUND2_DATA_DIR}")
        subparser.add_argument("--days", nargs="*", default=["0"], help="Day list, default 0")
        subparser.add_argument("--fill-mode", default="base", help=f"Fill assumption preset. Built-ins: {', '.join(sorted(FILL_MODELS))}")
        subparser.add_argument("--fill-config", default=None, help="Optional JSON fill-profile config produced by derive-fill-profile")
        subparser.add_argument("--output-dir", default=None, help="Output directory. Default is backtests/<timestamp>_<label>")
        subparser.add_argument("--passive-fill-scale", type=float, default=1.0)
        subparser.add_argument("--missed-fill-additive", type=float, default=0.0)
        subparser.add_argument("--spread-shift-ticks", type=int, default=0)
        subparser.add_argument("--order-book-volume-scale", type=float, default=1.0)
        subparser.add_argument("--price-noise-std", type=float, default=0.0)
        subparser.add_argument("--noise-profile", default="none", choices=["none", "fitted", "baseline", "stress", "crash"], help="Latent Monte Carlo noise profile")
        subparser.add_argument("--noise-scale", type=float, default=1.0, help="Multiplier around the selected latent noise profile")
        subparser.add_argument("--latent-noise-scale", type=float, default=1.0, help="Extra multiplier applied inside perturbation configs")
        subparser.add_argument("--pepper-slope-scale", type=float, default=1.0)
        subparser.add_argument("--latency-ticks", type=int, default=0)
        subparser.add_argument("--adverse-selection-ticks", type=int, default=0)
        subparser.add_argument("--slippage-multiplier", type=float, default=1.0, help="Set to 0 for a no-slippage comparison")
        subparser.add_argument("--reentry-probability", type=float, default=1.0)
        subparser.add_argument("--match-trades", default="all", choices=["all", "worse", "none"], help="How passive trade-print matching should work. 'worse' excludes same-price prints and 'none' disables passive trade matching.")
        subparser.add_argument("--inventory-limit-scale", type=float, default=1.0)
        subparser.add_argument("--limit", dest="limit_overrides", action="append", type=_limit_override, default=None, metavar="PRODUCT:LIMIT", help="Override the position limit for one product. Repeat as needed.")
        subparser.add_argument("--synthetic-tick-limit", type=int, default=None, help="Cap synthetic Monte Carlo ticks per day for quick smoke or benchmark runs")
        subparser.add_argument("--scenario-name", default="cli")
        subparser.add_argument("--print-trader-output", "--print", dest="print_trader_output", action="store_true", help="Forward trader stdout directly instead of suppressing it")
        add_output_controls(subparser)
        add_round_and_access(subparser)

    replay = sub.add_parser(
        "replay",
        help="Replay one trader on historical data",
        formatter_class=_CliFormatter,
        description="Replay one trader with short daily defaults and optional local debug controls.",
        epilog=(
            "Examples:\n"
            "  python -m prosperity_backtester replay strategies/r2_algo_v2_optimised.py --round 2 --data-dir data/round2 --days -1 0 1 --fill-mode base\n"
            "  python -m prosperity_backtester replay strategies/r2_algo_v2_optimised.py --round 2 --data-dir data/round2 --days 0 --with-extra-access --access-mode deterministic --maf-bid 1000 --access-quality 0.75 --access-passive-multiplier 1.12 --access-missed-reduction 0.02 --vis\n"
            "  python -m prosperity_backtester replay strategies/r2_algo_v2_optimised.py --round 2 --data-dir data/round2 --days 0 --limit INTARIAN_PEPPER_ROOT:40 --print\n"
        ),
    )
    add_shared(replay)
    replay.add_argument("--live-export", default=None, help="Optional website export .log/.json to validate against")

    mc = sub.add_parser(
        "monte-carlo",
        help="Run Monte Carlo robustness sessions",
        formatter_class=_CliFormatter,
        description="Run Monte Carlo robustness sessions with optional worker parallelism and saved sample paths.",
        epilog=(
            "Examples:\n"
            "  python -m prosperity_backtester monte-carlo strategies/r2_algo_v2_optimised.py --round 2 --data-dir data/round2 --days 0 --quick --noise-profile fitted\n"
            "  python -m prosperity_backtester monte-carlo strategies/r2_algo_v2_optimised.py --round 2 --data-dir data/round2 --days 0 --sessions 256 --sample-sessions 16 --workers 4\n"
            "  python -m prosperity_backtester monte-carlo strategies/r2_algo_v2_optimised.py --round 2 --data-dir data/round2 --days 0 --sessions 256 --workers 4 --mc-backend rust\n"
        ),
    )
    add_shared(mc)
    mc.add_argument("--sessions", type=int, default=100)
    mc.add_argument("--sample-sessions", type=int, default=10)
    mc.add_argument("--seed", type=int, default=20260418)
    mc.add_argument("--workers", type=int, default=1, help="Parallel worker processes for Monte Carlo sessions")
    mc.add_argument("--mc-backend", default="auto", choices=["auto", "classic", "streaming", "rust"], help="Monte Carlo execution backend. 'auto' always resolves to 'streaming' (recommended default). 'classic' materialises full synthetic market days per session and remains the parity option. 'streaming' runs the hot loop directly in Python with no IPC overhead; it is still the best default overall, but realistic-trader rankings are strategy-sensitive and some measured 8-worker cells slightly favour classic. 'rust' offloads market generation and order execution to a compiled Rayon engine via a Python subprocess per worker; it remains available for explicit experiments, but is not auto-selected and stayed slower on the tracked 2026-04-22 benchmark cases. The Rust binary is built with cargo the first time (~60s, cached after that).")
    mc.add_argument("--quick", action="store_true", help="Use quick preset: 64 sessions, 8 sampled runs")
    mc.add_argument("--heavy", action="store_true", help="Use heavy preset: 512 sessions, 32 sampled runs")

    compare = sub.add_parser(
        "compare",
        help="Compare multiple traders side by side on replay",
        formatter_class=_CliFormatter,
        description="Compare traders on the same replay settings, with optional merged PnL output.",
        epilog=(
            "Examples:\n"
            "  python -m prosperity_backtester compare strategies/r2_algo_v2_optimised.py strategies/r2_algo_v2.py --names optimised submitted --round 2 --data-dir data/round2 --days -1 0 1 --fill-mode base\n"
            "  python -m prosperity_backtester compare strategies/r2_algo_v2_optimised.py strategies/r2_algo_v2.py --names optimised submitted --round 2 --data-dir data/round2 --days -1 0 1 --with-extra-access --access-mode stochastic --access-quality 0.8 --access-probability 0.65 --maf-bid 1000 --merge-pnl --vis\n"
        ),
    )
    compare.add_argument("traders", nargs="+", help="Trader python files")
    compare.add_argument("--names", nargs="*", default=None, help="Optional display names")
    compare.add_argument("--data-dir", "--data", dest="data_dir", default=None)
    compare.add_argument("--days", nargs="*", default=["0"])
    compare.add_argument("--fill-mode", default="base", help=f"Fill assumption preset. Built-ins: {', '.join(sorted(FILL_MODELS))}")
    compare.add_argument("--fill-config", default=None)
    compare.add_argument("--output-dir", default=None)
    compare.add_argument("--passive-fill-scale", type=float, default=1.0)
    compare.add_argument("--missed-fill-additive", type=float, default=0.0)
    compare.add_argument("--spread-shift-ticks", type=int, default=0)
    compare.add_argument("--order-book-volume-scale", type=float, default=1.0)
    compare.add_argument("--price-noise-std", type=float, default=0.0)
    compare.add_argument("--noise-profile", default="none", choices=["none", "fitted", "baseline", "stress", "crash"])
    compare.add_argument("--noise-scale", type=float, default=1.0)
    compare.add_argument("--latent-noise-scale", type=float, default=1.0)
    compare.add_argument("--pepper-slope-scale", type=float, default=1.0)
    compare.add_argument("--latency-ticks", type=int, default=0)
    compare.add_argument("--adverse-selection-ticks", type=int, default=0)
    compare.add_argument("--slippage-multiplier", type=float, default=1.0)
    compare.add_argument("--reentry-probability", type=float, default=1.0)
    compare.add_argument("--match-trades", default="all", choices=["all", "worse", "none"], help="How passive trade-print matching should work. 'worse' excludes same-price prints and 'none' disables passive trade matching.")
    compare.add_argument("--inventory-limit-scale", type=float, default=1.0)
    compare.add_argument("--limit", dest="limit_overrides", action="append", type=_limit_override, default=None, metavar="PRODUCT:LIMIT", help="Override the position limit for one product. Repeat as needed.")
    compare.add_argument("--scenario-name", default="cli")
    compare.add_argument("--merge-pnl", action="store_true", help="Print a compact merged PnL summary by trader after the compare run")
    compare.add_argument("--print-trader-output", "--print", dest="print_trader_output", action="store_true", help="Forward trader stdout directly instead of suppressing it")
    add_output_controls(compare, child_bundles=True)
    add_round_and_access(compare)

    sweep = sub.add_parser("sweep", help="Run a named parameter sweep from JSON config")
    sweep.add_argument("config", help="Path to sweep JSON config")
    sweep.add_argument("--output-dir", default=None)
    add_output_controls(sweep)

    optimize = sub.add_parser("optimize", help="Run replay + Monte Carlo parameter optimisation from JSON config")
    optimize.add_argument("config", help="Path to optimization JSON config")
    optimize.add_argument("--output-dir", default=None)
    add_output_controls(optimize, child_bundles=True)

    round2 = sub.add_parser("round2-scenarios", help="Run a Round 2 MAF/access scenario comparison config")
    round2.add_argument("config", help="Path to Round 2 scenario JSON config")
    round2.add_argument("--output-dir", default=None)
    add_output_controls(round2, child_bundles=True)

    scenario_compare = sub.add_parser("scenario-compare", help="Run calibrated baseline/stress/crash scenario comparisons")
    scenario_compare.add_argument("config", help="Path to research scenario JSON config")
    scenario_compare.add_argument("--output-dir", default=None)
    add_output_controls(scenario_compare, child_bundles=True)

    derive_fill = sub.add_parser("derive-fill-profile", help="Derive an empirical fill profile from live export files")
    derive_fill.add_argument("live_exports", nargs="+", help="One or more Prosperity live export .log/.json files")
    derive_fill.add_argument("--profile-name", default="empirical_live")
    derive_fill.add_argument("--output-dir", default=None)
    derive_fill.add_argument("--keep-runs", type=_positive_int, default=30)

    calibrate = sub.add_parser("calibrate", help="Grid-search fill assumptions against a live export", formatter_class=_CliFormatter)
    calibrate.add_argument("trader", help="Trader python file")
    calibrate.add_argument("--name", default=None)
    calibrate.add_argument("--data-dir", "--data", dest="data_dir", default=None)
    calibrate.add_argument("--days", nargs="*", default=["0"])
    calibrate.add_argument("--live-export", required=True)
    calibrate.add_argument("--output-dir", default=None)
    calibrate.add_argument("--quick", action="store_true", help="Use a smaller calibration grid for fast local iteration")
    add_output_controls(calibrate, child_bundles=True)
    add_round_and_access(calibrate)

    inspect = sub.add_parser("inspect", help="Print a concise dataset inspection report", formatter_class=_CliFormatter)
    inspect.add_argument("--data-dir", "--data", dest="data_dir", default=None)
    inspect.add_argument("--days", nargs="*", default=["-2", "-1", "0"])
    inspect.add_argument("--round", type=int, default=1, choices=[1, 2])
    inspect.add_argument("--json", action="store_true")

    serve = sub.add_parser(
        "serve",
        help="Serve the local dashboard frontend",
        formatter_class=_CliFormatter,
        epilog=(
            "Examples:\n"
            "  python -m prosperity_backtester serve\n"
            "  python -m prosperity_backtester serve --latest\n"
            "  python -m prosperity_backtester serve --latest-type monte-carlo\n"
        ),
    )
    serve.add_argument("--dir", default=str(Path(__file__).resolve().parent.parent))
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=5555)
    serve.add_argument("--open-browser", action="store_true", help="Open the dashboard in a browser when the server starts")
    serve.add_argument("--latest", action="store_true", help="Open the latest discovered bundle automatically")
    serve.add_argument("--latest-type", type=_normalise_run_type, default=None, help="Open the latest run of one type: workspace, replay, monte-carlo, compare, calibration, optimization, round2-scenarios or scenario-compare")

    workspace = sub.add_parser(
        "workspace-bundle",
        help="Assemble a research workspace dashboard bundle from single-purpose child bundles",
        formatter_class=_CliFormatter,
        description=(
            "Build an all-in-one workspace dashboard.json from existing child bundles. The workspace "
            "bundle keeps per-section provenance so it remains reproducible and auditable."
        ),
        epilog=(
            "Examples:\n"
            "  python -m prosperity_backtester workspace-bundle --from-dir backtests/final_round2_study_pack --name r2_final\n"
            "  python -m prosperity_backtester workspace-bundle path/to/replay/dashboard.json path/to/mc/dashboard.json --name focus_study --open\n"
        ),
    )
    workspace.add_argument("sources", nargs="*", default=[], help="Child dashboard.json files or bundle directories to include")
    workspace.add_argument("--from-dir", dest="from_dir", default=None, help="Discover child dashboard.json files recursively under this directory")
    workspace.add_argument("--name", default=None, help="Workspace name (defaults to a timestamped label)")
    workspace.add_argument("--notes", default=None, help="Optional one-line description stored on the workspace")
    workspace.add_argument("--output-dir", default=None, help="Output directory for the workspace bundle")
    workspace.add_argument("--open", "--vis", dest="open", action="store_true", help="Serve the written bundle locally and open it in the dashboard")
    workspace.add_argument("--keep-runs", type=_positive_int, default=30, help="When using the default backtests/ output root, keep this many timestamped runs")

    clean = sub.add_parser("clean", help="Prune old timestamped backtest run directories")
    clean.add_argument("--dir", default=str(Path.cwd() / "backtests"))
    clean.add_argument("--keep", type=_positive_int, default=30)

    return parser


def _trader_spec(path: str, name: str | None) -> TraderSpec:
    trader_path = Path(path).resolve()
    return TraderSpec(name=name or trader_path.stem, path=trader_path)


def _print_replay_result(artefact) -> None:
    print(f"Run: {artefact.run_name}")
    print(f"Trader: {artefact.trader_name}")
    print(f"Final PnL: {artefact.summary['final_pnl']:,.2f}")
    if artefact.summary.get("maf_cost"):
        print(f"Gross before MAF: {artefact.summary.get('gross_pnl_before_maf', 0.0):,.2f}")
        print(f"MAF cost: {artefact.summary.get('maf_cost', 0.0):,.2f}")
    if artefact.access_scenario:
        print(f"Access scenario: {artefact.access_scenario.get('name', 'no_access')}")
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


def _print_day_breakdown(artefact) -> None:
    if len(getattr(artefact, "session_rows", [])) <= 1:
        return
    print("Per-day PnL:")
    for row in artefact.session_rows:
        print(
            f"  day {row['day']}: pnl={row['final_pnl']:,.2f} "
            f"gross={row.get('gross_pnl_before_maf', 0.0):,.2f} "
            f"osmium={row.get('osmium_pnl', 0.0):,.2f} "
            f"pepper={row.get('pepper_pnl', 0.0):,.2f}"
        )


def _print_compare_rows(rows: Sequence[dict[str, object]], *, merge_pnl: bool = False) -> None:
    print(f"Compared {len(rows)} traders")
    for row in rows:
        print(f"  {row['trader']}: pnl={row['final_pnl']:,.2f} drawdown={row['max_drawdown']:,.2f}")
    if not merge_pnl:
        return
    print("Merged PnL:")
    for row in rows:
        gross = row.get("gross_pnl_before_maf")
        maf_cost = row.get("maf_cost")
        gross_text = "n/a" if gross is None else f"{float(gross):,.2f}"
        maf_text = "n/a" if maf_cost is None else f"{float(maf_cost):,.2f}"
        print(
            f"  {row['trader']}: total={float(row['final_pnl']):,.2f} "
            f"osmium={float(row.get('osmium_pnl') or 0.0):,.2f} "
            f"pepper={float(row.get('pepper_pnl') or 0.0):,.2f} "
            f"gross={gross_text} maf={maf_text}"
        )


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
        output_options=OutputOptions(),
    )
    finals = [result.summary["final_pnl"] for result in results]
    print(f"Legacy Monte Carlo mean PnL: {sum(finals)/len(finals):,.2f}")
    print(f"Output bundle: {output_dir}")
    _prune_after_auto_run(output_dir, True, 30)


def main(argv: List[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and not argv[0].startswith("-") and argv[0] not in SUBCOMMANDS:
        _handle_legacy(argv[0])
        return

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "replay":
        output_dir, auto_output = _auto_output_dir(args, "replay")
        output_options = _output_options_from_args(args)
        artefact = run_replay(
            trader_spec=_trader_spec(args.trader, args.name),
            days=_days_arg(args.days),
            data_dir=_data_dir_from_args(args),
            fill_model_name=args.fill_mode,
            perturbation=_perturb_from_args(args),
            fill_model_config_path=Path(args.fill_config).resolve() if args.fill_config else None,
            output_dir=output_dir,
            run_name=output_dir.name,
            live_export_path=Path(args.live_export).resolve() if args.live_export else None,
            round_number=args.round,
            access_scenario=_access_from_args(args),
            output_options=output_options,
            print_trader_output=args.print_trader_output,
        )
        _print_replay_result(artefact)
        _print_day_breakdown(artefact)
        print(f"Output bundle: {output_dir}")
        _prune_after_auto_run(output_dir, auto_output, args.keep_runs)
        if artefact.validation:
            print(f"Validation: {json.dumps(artefact.validation, indent=2)}")
        if args.open:
            _open_bundle(output_dir)
        return

    if args.command == "monte-carlo":
        output_dir, auto_output = _auto_output_dir(args, "mc")
        output_options = _output_options_from_args(args)
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
            fill_model_config_path=Path(args.fill_config).resolve() if args.fill_config else None,
            output_dir=output_dir,
            base_seed=args.seed,
            run_name=output_dir.name,
            workers=args.workers,
            round_number=args.round,
            access_scenario=_access_from_args(args),
            output_options=output_options,
            print_trader_output=args.print_trader_output,
            monte_carlo_backend=args.mc_backend,
        )
        finals = [result.summary["final_pnl"] for result in results]
        print(f"Sessions: {len(finals)}")
        print(f"Mean PnL: {sum(finals)/len(finals):,.2f}")
        print(f"Min / Max: {min(finals):,.2f} / {max(finals):,.2f}")
        print(f"Output bundle: {output_dir}")
        _prune_after_auto_run(output_dir, auto_output, args.keep_runs)
        if args.open:
            _open_bundle(output_dir)
        return

    if args.command == "compare":
        output_dir, auto_output = _auto_output_dir(args, "compare")
        output_options = _output_options_from_args(args)
        names = args.names or []
        trader_specs = [
            _trader_spec(path, names[idx] if idx < len(names) else None)
            for idx, path in enumerate(args.traders)
        ]
        rows = run_compare(
            trader_specs=trader_specs,
            days=_days_arg(args.days),
            data_dir=_data_dir_from_args(args),
            fill_model_name=args.fill_mode,
            perturbation=_perturb_from_args(args),
            fill_model_config_path=Path(args.fill_config).resolve() if args.fill_config else None,
            output_dir=output_dir,
            run_name=output_dir.name,
            round_number=args.round,
            access_scenario=_access_from_args(args),
            output_options=output_options,
            print_trader_output=args.print_trader_output,
        )
        _print_compare_rows(rows, merge_pnl=args.merge_pnl)
        print(f"Output bundle: {output_dir}")
        _prune_after_auto_run(output_dir, auto_output, args.keep_runs)
        if args.open:
            _open_bundle(output_dir)
        return

    if args.command == "sweep":
        output_dir, auto_output = _auto_output_dir(args, "sweep")
        cli_options = _output_options_from_args(args) if _has_output_policy_override(args) else None
        rows = run_sweep_from_config(Path(args.config).resolve(), output_dir, output_options=cli_options)
        print(f"Sweep variants: {len(rows)}")
        for row in rows:
            print(f"  {row['trader']}: {row['final_pnl']:,.2f}")
        print(f"Output bundle: {output_dir}")
        _prune_after_auto_run(output_dir, auto_output, args.keep_runs)
        if args.open:
            _open_bundle(output_dir)
        return

    if args.command == "optimize":
        output_dir, auto_output = _auto_output_dir(args, "optimize")
        cli_options = _output_options_from_args(args) if _has_output_policy_override(args) else None
        rows = run_optimize_from_config(Path(args.config).resolve(), output_dir, output_options=cli_options)
        print(f"Optimized variants: {len(rows)}")
        for row in rows[:5]:
            print(f"  {row['variant']}: score={row['score']:,.2f} replay={row['replay_final_pnl']:,.2f} mc_p05={row['mc_p05']:,.2f}")
        print(f"Output bundle: {output_dir}")
        _prune_after_auto_run(output_dir, auto_output, args.keep_runs)
        if args.open:
            _open_bundle(output_dir)
        return

    if args.command == "round2-scenarios":
        output_dir, auto_output = _auto_output_dir(args, "round2_scenarios")
        cli_options = _output_options_from_args(args) if _has_output_policy_override(args) else None
        result = run_round2_scenario_compare_from_config(Path(args.config).resolve(), output_dir, output_options=cli_options)
        rows = result["scenario_rows"]
        winners = result["winner_rows"]
        print(f"Round 2 scenario rows: {len(rows)}")
        for row in winners:
            gap = row.get("gap_to_second")
            gap_text = "n/a" if gap is None else f"{gap:,.2f}"
            print(f"  {row['scenario']}: winner={row['winner']} pnl={row['winner_final_pnl']:,.2f} gap={gap_text}")
        print(f"Output bundle: {output_dir}")
        _prune_after_auto_run(output_dir, auto_output, args.keep_runs)
        if args.open:
            _open_bundle(output_dir)
        return

    if args.command == "scenario-compare":
        output_dir, auto_output = _auto_output_dir(args, "scenario_compare")
        cli_options = _output_options_from_args(args) if _has_output_policy_override(args) else None
        result = run_scenario_compare_from_config(Path(args.config).resolve(), output_dir, output_options=cli_options)
        rows = result["scenario_rows"]
        robustness = result["robustness_rows"]
        print(f"Scenario rows: {len(rows)}")
        for row in robustness[:8]:
            print(
                f"  rank={row['robust_rank']} trader={row['trader']} "
                f"median={row['median_pnl']:,.2f} worst={row['worst_pnl']:,.2f} "
                f"fragility={row['fragility_score']:,.2f}"
            )
        print(f"Output bundle: {output_dir}")
        _prune_after_auto_run(output_dir, auto_output, args.keep_runs)
        if args.open:
            _open_bundle(output_dir)
        return

    if args.command == "derive-fill-profile":
        output_dir, auto_output = _auto_output_dir(args, "fill_profile")
        artefact = derive_empirical_fill_profile(
            [Path(path).resolve() for path in args.live_exports],
            output_dir,
            profile_name=args.profile_name,
        )
        print(f"Empirical fill rows: {artefact['row_count']}")
        print(f"Profile: {args.profile_name}")
        print(f"Output bundle: {output_dir}")
        _prune_after_auto_run(output_dir, auto_output, args.keep_runs)
        return

    if args.command == "calibrate":
        output_dir, auto_output = _auto_output_dir(args, "calibrate")
        output_options = _output_options_from_args(args)
        best = calibrate_against_live_export(
            trader_spec=_trader_spec(args.trader, args.name),
            days=_days_arg(args.days),
            data_dir=_data_dir_from_args(args),
            live_export_path=Path(args.live_export).resolve(),
            output_dir=output_dir,
            quick=args.quick,
            round_number=args.round,
            access_scenario=_access_from_args(args),
            output_options=output_options,
        )
        print(f"Best calibration: {json.dumps(best, indent=2)}")
        print(f"Output bundle: {output_dir}")
        _prune_after_auto_run(output_dir, auto_output, args.keep_runs)
        if args.open:
            _open_bundle(output_dir)
        return

    if args.command == "inspect":
        from .dataset import load_round_dataset
        dataset = load_round_dataset(_data_dir_from_args(args), _days_arg(args.days), round_number=args.round)
        payload = {day: day_dataset.validation for day, day_dataset in dataset.items()}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            for day, validation in payload.items():
                print(f"Day {day}: {validation}")
        return

    if args.command == "workspace-bundle":
        from .workspace import resolve_sources, write_workspace_bundle

        from_dir = Path(args.from_dir).resolve() if args.from_dir else None
        source_paths = [Path(p) for p in args.sources]
        try:
            sources = resolve_sources(source_paths, from_dir=from_dir)
        except RuntimeError as exc:
            parser.error(str(exc))
            return
        if not sources:
            parser.error("no child dashboard.json bundles were found. Pass paths or use --from-dir.")
            return

        label = args.name or (from_dir.name if from_dir is not None else "research")
        # Normalise the workspace slug so timestamped directories stay readable.
        workspace_slug = _slug(label)
        if args.output_dir:
            output_dir = Path(args.output_dir).resolve()
            auto_output = False
        else:
            output_dir = _timestamped_dir(Path.cwd() / "backtests", f"workspace_{workspace_slug}")
            auto_output = True

        dashboard_path, assembly = write_workspace_bundle(
            sources,
            output_dir,
            name=label,
            notes=args.notes,
        )
        print(f"Workspace bundle: {dashboard_path}")
        print(f"  sources: {len(sources)}")
        for record in assembly.source_records:
            contributed = ", ".join(sorted(set(record.get("sections") or []))) or "no sections"
            print(f"    - {record['path']} ({record['type']}): {contributed}")
        print(f"  present sections: {', '.join(assembly.present_sections)}")
        if assembly.missing_sections:
            print(f"  missing sections: {', '.join(assembly.missing_sections)}")
        integrity = ((assembly.payload.get("workspace") or {}).get("integrity") or {}) if isinstance(assembly.payload.get("workspace"), dict) else {}
        warnings = integrity.get("warnings") if isinstance(integrity, dict) else None
        if isinstance(warnings, list) and warnings:
            print("  integrity notes:")
            for warning in warnings:
                print(f"    - {warning}")
        _prune_after_auto_run(output_dir, auto_output, args.keep_runs)
        if args.open:
            _open_bundle(output_dir)
        return

    if args.command == "serve":
        if args.latest or args.latest_type:
            _open_latest(Path(args.dir), args.latest_type, host=args.host, port=args.port)
            return
        serve_directory(Path(args.dir), host=args.host, port=args.port, open_browser=args.open_browser)
        return

    if args.command == "clean":
        removed = prune_old_auto_runs(Path(args.dir), validate_keep_count(args.keep))
        print(f"Pruned old auto backtest runs: {len(removed)}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
