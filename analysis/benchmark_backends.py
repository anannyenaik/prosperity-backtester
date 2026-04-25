from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[1]
    repo_root_text = str(repo_root)
    if repo_root_text not in sys.path:
        sys.path.insert(0, repo_root_text)

from analysis.benchmark_runtime import (  # noqa: E402
    _dir_file_count,
    _dir_size,
    _format_memory,
    _git_text,
    _run_command_with_monitoring,
)


DEFAULT_CASES = {
    "live_v9_default_w1": {
        "trader": "examples/trader_round1_v9.py",
        "sessions": 100,
        "sample_sessions": 10,
        "workers": 1,
    },
    "live_v9_default_w8": {
        "trader": "examples/trader_round1_v9.py",
        "sessions": 100,
        "sample_sessions": 10,
        "workers": 8,
    },
    "live_v9_heavy_w8": {
        "trader": "examples/trader_round1_v9.py",
        "sessions": 192,
        "sample_sessions": 16,
        "workers": 8,
    },
    "submitted_default_w8": {
        "trader": "strategies/archive/round2/r2_algo_v2.py",
        "sessions": 100,
        "sample_sessions": 10,
        "workers": 8,
    },
    "submitted_heavy_w8": {
        "trader": "strategies/archive/round2/r2_algo_v2.py",
        "sessions": 192,
        "sample_sessions": 16,
        "workers": 8,
    },
    "optimised_default_w8": {
        "trader": "strategies/archive/round2/r2_algo_v2_optimised.py",
        "sessions": 100,
        "sample_sessions": 10,
        "workers": 8,
    },
    "optimised_heavy_w8": {
        "trader": "strategies/archive/round2/r2_algo_v2_optimised.py",
        "sessions": 192,
        "sample_sessions": 16,
        "workers": 8,
    },
}

BACKENDS = ("streaming", "classic", "rust")


def _default_output_dir(repo_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return repo_root / "backtests" / f"{timestamp}_backend_benchmark"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark Monte Carlo backends across realistic traders")
    parser.add_argument("--repo-root", default=".", help="Repo root to benchmark")
    parser.add_argument("--python", default=sys.executable, help="Python executable to use")
    parser.add_argument("--output-dir", default=None, help="Directory for reports and measured case outputs")
    parser.add_argument("--cases", nargs="*", default=list(DEFAULT_CASES), choices=list(DEFAULT_CASES), help="Named backend benchmark cases to run")
    parser.add_argument("--warmup", type=int, default=0, help="Warm-up runs before measured repeats")
    parser.add_argument("--measured-repeats", type=int, default=1, help="Measured repeats per case/backend")
    parser.add_argument("--mc-fill-mode", default="base", help="Monte Carlo fill mode")
    parser.add_argument("--mc-synthetic-tick-limit", type=int, default=250, help="Synthetic tick cap for benchmark cases")
    return parser


def _python_command(python_executable: str, *args: str) -> list[str]:
    return [python_executable, *args]


def _timed_runs(
    *,
    command: list[str],
    repo_root: Path,
    warmup: int,
    measured_repeats: int,
) -> tuple[list[float], dict[str, int | None], subprocess.CompletedProcess[str]]:
    timings: list[float] = []
    peak_memory = {
        "peak_process_rss_bytes": None,
        "peak_tree_rss_bytes": None,
        "peak_child_process_count": None,
    }
    completed: subprocess.CompletedProcess[str] | None = None
    total_runs = max(0, int(warmup)) + max(1, int(measured_repeats))
    for run_index in range(total_runs):
        completed, elapsed, current_peak = _run_command_with_monitoring(command=command, repo_root=repo_root)
        if run_index >= warmup:
            timings.append(elapsed)
        for key, value in current_peak.items():
            if value is None:
                continue
            existing = peak_memory.get(key)
            peak_memory[key] = int(value) if existing is None else max(int(existing), int(value))
    assert completed is not None
    return timings, peak_memory, completed


def _case_markdown_row(case: dict[str, object]) -> str:
    return (
        f"| `{case['case']}` | `{case['backend']}` | {case['best_elapsed_seconds']:.3f}s | "
        f"{case['mean_elapsed_seconds']:.3f}s | {_format_memory(case.get('peak_tree_rss_bytes'))} | "
        f"{int(case.get('output_size_bytes') or 0):,} | {int(case.get('file_count') or 0):,} |"
    )


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# Backend Benchmark",
        "",
        "Fixture",
        f"- Repo root: `{report['repo_root']}`",
        f"- Git commit: `{report['git_commit']}`",
        f"- Git dirty: `{report['git_dirty']}`",
        f"- Python: `{report['python_executable']}`",
        f"- Platform: `{report['platform']}`",
        f"- MC fill mode: `{report['mc_fill_mode']}`",
        f"- Synthetic tick limit: `{report['mc_synthetic_tick_limit']}`",
        f"- Warm-up runs: `{report['warmup']}`",
        f"- Measured repeats: `{report['measured_repeats']}`",
        f"- Command: `{report['command']['display']}`",
        "",
        "| Case | Backend | Best | Mean | Peak RSS | Output bytes | Files |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in report["cases"]:
        lines.append(_case_markdown_row(case))
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> None:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(effective_argv)

    repo_root = Path(args.repo_root).resolve()
    output_root = Path(args.output_dir).resolve() if args.output_dir else _default_output_dir(repo_root)
    output_root.mkdir(parents=True, exist_ok=True)
    if any(output_root.iterdir()):
        raise ValueError(f"Backend benchmark output directory must be empty: {output_root}")

    python_executable = str(Path(args.python).resolve())
    selected_cases = [DEFAULT_CASES[name] | {"case": name} for name in args.cases]
    results: list[dict[str, object]] = []

    for case in selected_cases:
        for backend in BACKENDS:
            case_output = output_root / "cases" / f"{case['case']}__{backend}"
            command = _python_command(
                python_executable,
                "-m",
                "prosperity_backtester",
                "monte-carlo",
                str(Path(case["trader"])),
                "--name",
                str(case["case"]),
                "--days",
                "0",
                "--fill-mode",
                args.mc_fill_mode,
                "--noise-profile",
                "fitted",
                "--sessions",
                str(case["sessions"]),
                "--sample-sessions",
                str(case["sample_sessions"]),
                "--workers",
                str(case["workers"]),
                "--mc-backend",
                backend,
                "--synthetic-tick-limit",
                str(args.mc_synthetic_tick_limit),
                "--output-dir",
                str(case_output),
            )
            timings, peak_memory, completed = _timed_runs(
                command=command,
                repo_root=repo_root,
                warmup=args.warmup,
                measured_repeats=args.measured_repeats,
            )
            results.append({
                "case": case["case"],
                "backend": backend,
                "trader": str(case["trader"]),
                "sessions": int(case["sessions"]),
                "sample_sessions": int(case["sample_sessions"]),
                "workers": int(case["workers"]),
                "command": command,
                "best_elapsed_seconds": round(min(timings), 3),
                "mean_elapsed_seconds": round(sum(timings) / len(timings), 3),
                "all_elapsed_seconds": [round(value, 3) for value in timings],
                "peak_process_rss_bytes": peak_memory.get("peak_process_rss_bytes"),
                "peak_tree_rss_bytes": peak_memory.get("peak_tree_rss_bytes"),
                "peak_child_process_count": peak_memory.get("peak_child_process_count"),
                "output_size_bytes": _dir_size(case_output),
                "file_count": _dir_file_count(case_output),
                "stdout_tail": completed.stdout.splitlines()[-6:],
                "stderr_tail": completed.stderr.splitlines()[-6:],
            })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "git_commit": _git_text(repo_root, "rev-parse", "HEAD"),
        "git_dirty": bool(_git_text(repo_root, "status", "--porcelain", "--untracked-files=no")),
        "python_executable": python_executable,
        "platform": platform.platform(),
        "mc_fill_mode": args.mc_fill_mode,
        "mc_synthetic_tick_limit": int(args.mc_synthetic_tick_limit),
        "warmup": int(args.warmup),
        "measured_repeats": int(args.measured_repeats),
        "command": {
            "argv": [python_executable, str(Path(__file__).resolve()), *effective_argv],
            "display": subprocess.list2cmdline([python_executable, str(Path(__file__).resolve()), *effective_argv]),
            "cwd": str(Path.cwd().resolve()),
        },
        "cases": results,
    }

    (output_root / "backend_benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown = render_markdown(report)
    (output_root / "backend_benchmark.md").write_text(markdown, encoding="utf-8")

    print(f"Backend benchmark: {output_root}")
    print(markdown)


if __name__ == "__main__":
    main()
