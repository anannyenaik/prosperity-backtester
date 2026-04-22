from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
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
)


CASES = (
    ("default_100_10", 100, 10),
    ("ceiling_1000_100", 1000, 100),
)


def _default_output_dir(repo_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return repo_root / "backtests" / f"{timestamp}_chris_reference"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare this repo against the local Chris Roberts Monte Carlo repo")
    parser.add_argument("--repo-root", default=".", help="Current repo root")
    parser.add_argument("--python", default=sys.executable, help="Python executable for the current repo")
    parser.add_argument("--reference-root", required=True, help="Path to Chris Roberts' backtester/ directory")
    parser.add_argument("--reference-python", default=None, help="Python executable inside the reference repo")
    parser.add_argument("--output-dir", default=None, help="Directory for reports and measured outputs")
    parser.add_argument("--workers", nargs="*", type=int, default=[1, 2, 4, 8], help="Worker and thread counts to compare")
    parser.add_argument("--ticks-per-day", type=int, default=250, help="Matched synthetic tick budget for both repos")
    parser.add_argument("--warmup", action=argparse.BooleanOptionalAction, default=True, help="Run one warm-up pass per repo before measuring")
    return parser


def _python_command(python_executable: str, *args: str) -> list[str]:
    return [python_executable, *args]


def _worker_values(values: list[int]) -> list[int]:
    deduped = sorted({max(1, int(value)) for value in values})
    return deduped or [1]


def _write_shared_trader(path: Path) -> Path:
    path.write_text(
        "class Trader:\n"
        "    def run(self, state):\n"
        '        return {}, 0, getattr(state, "traderData", "")\n',
        encoding="utf-8",
    )
    return path


def _run_with_env(command: list[str], cwd: Path, env: dict[str, str]) -> dict[str, object]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    from analysis.benchmark_runtime import _sample_process_tree_memory  # noqa: WPS433

    peak_memory = {
        "peak_process_rss_bytes": 0,
        "peak_tree_rss_bytes": 0,
        "peak_child_process_count": 0,
    }
    timer_started = time.perf_counter()
    while process.poll() is None:
        sample = _sample_process_tree_memory(process)
        for key, value in sample.items():
            if value is None:
                continue
            peak_memory[key] = max(int(peak_memory[key]), int(value))
        time.sleep(0.02)
    stdout, stderr = process.communicate()
    elapsed = time.perf_counter() - timer_started
    sample = _sample_process_tree_memory(process)
    for key, value in sample.items():
        if value is None:
            continue
        peak_memory[key] = max(int(peak_memory[key]), int(value))
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, command, stdout, stderr)
    return {
        "command": command,
        "elapsed_seconds": round(elapsed, 3),
        "peak_process_rss_bytes": peak_memory.get("peak_process_rss_bytes"),
        "peak_tree_rss_bytes": peak_memory.get("peak_tree_rss_bytes"),
        "peak_child_process_count": peak_memory.get("peak_child_process_count"),
        "stdout_tail": stdout.splitlines()[-6:],
        "stderr_tail": stderr.splitlines()[-6:],
    }


def _render_row(case: dict[str, object]) -> str:
    return (
        f"| `{case['repo']}` | `{case['case']}` | `{case['workers']}` | {case['elapsed_seconds']:.3f}s | "
        f"{_format_memory(case.get('peak_tree_rss_bytes'))} | {int(case.get('output_size_bytes') or 0):,} | "
        f"{int(case.get('file_count') or 0):,} |"
    )


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# Chris Reference Benchmark",
        "",
        "Fixture",
        f"- Current repo root: `{report['repo_root']}`",
        f"- Reference repo root: `{report['reference_root']}`",
        f"- Current repo commit: `{report['git_commit']}`",
        f"- Current repo dirty: `{report['git_dirty']}`",
        f"- Current repo Python: `{report['python_executable']}`",
        f"- Reference Python: `{report['reference_python']}`",
        f"- Platform: `{report['platform']}`",
        f"- Ticks per day: `{report['ticks_per_day']}`",
        f"- Warm-up pass: `{report['warmup']}`",
        f"- Command: `{report['command']['display']}`",
        "",
        "| Repo | Case | Workers | Elapsed | Peak RSS | Output bytes | Files |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in report["cases"]:
        lines.append(_render_row(case))
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> None:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(effective_argv)

    repo_root = Path(args.repo_root).resolve()
    reference_root = Path(args.reference_root).resolve()
    output_root = Path(args.output_dir).resolve() if args.output_dir else _default_output_dir(repo_root)
    output_root.mkdir(parents=True, exist_ok=True)
    if any(output_root.iterdir()):
        raise ValueError(f"Reference benchmark output directory must be empty: {output_root}")

    python_executable = str(Path(args.python).resolve())
    if args.reference_python:
        reference_python = str(Path(args.reference_python).resolve())
    else:
        reference_python = str((reference_root / ".venv" / "Scripts" / "python.exe").resolve())
    workers = _worker_values(args.workers)
    shared_trader = _write_shared_trader(output_root / "shared_noop_trader.py")

    if args.warmup:
        warmup_cases = [
            (
                _python_command(
                    python_executable,
                    "-m",
                    "prosperity_backtester",
                    "monte-carlo",
                    str(shared_trader),
                    "--name",
                    "warmup",
                    "--days",
                    "0",
                    "--fill-mode",
                    "base",
                    "--noise-profile",
                    "fitted",
                    "--sessions",
                    "100",
                    "--sample-sessions",
                    "10",
                    "--workers",
                    "1",
                    "--synthetic-tick-limit",
                    str(args.ticks_per_day),
                    "--output-dir",
                    str(output_root / "_warmup_current"),
                ),
                repo_root,
                os.environ.copy(),
            ),
            (
                _python_command(
                    reference_python,
                    "-m",
                    "prosperity3bt",
                    "mc",
                    str(shared_trader),
                    "--sessions",
                    "100",
                    "--sample-sessions",
                    "10",
                    "--ticks-per-day",
                    str(args.ticks_per_day),
                    "--out",
                    str((output_root / "_warmup_reference" / "dashboard.json").resolve()),
                ),
                reference_root,
                {**os.environ, "RAYON_NUM_THREADS": "1"},
            ),
        ]
        for command, cwd, env in warmup_cases:
            _run_with_env(command, cwd, env)

    rows: list[dict[str, object]] = []
    for case_name, sessions, sample_sessions in CASES:
        for worker in workers:
            current_output = output_root / "current_repo" / case_name / f"w{worker}"
            current_command = _python_command(
                python_executable,
                "-m",
                "prosperity_backtester",
                "monte-carlo",
                str(shared_trader),
                "--name",
                case_name,
                "--days",
                "0",
                "--fill-mode",
                "base",
                "--noise-profile",
                "fitted",
                "--sessions",
                str(sessions),
                "--sample-sessions",
                str(sample_sessions),
                "--workers",
                str(worker),
                "--synthetic-tick-limit",
                str(args.ticks_per_day),
                "--output-dir",
                str(current_output),
            )
            current_row = _run_with_env(current_command, repo_root, os.environ.copy())
            current_row.update({
                "repo": "prosperity_backtester",
                "case": case_name,
                "workers": worker,
                "sessions": sessions,
                "sample_sessions": sample_sessions,
                "output_size_bytes": _dir_size(current_output),
                "file_count": _dir_file_count(current_output),
            })
            rows.append(current_row)

            reference_output = output_root / "chris_repo" / case_name / f"w{worker}" / "dashboard.json"
            reference_command = _python_command(
                reference_python,
                "-m",
                "prosperity3bt",
                "mc",
                str(shared_trader),
                "--sessions",
                str(sessions),
                "--sample-sessions",
                str(sample_sessions),
                "--ticks-per-day",
                str(args.ticks_per_day),
                "--out",
                str(reference_output.resolve()),
            )
            reference_env = {**os.environ, "RAYON_NUM_THREADS": str(worker)}
            reference_row = _run_with_env(reference_command, reference_root, reference_env)
            reference_row.update({
                "repo": "chris_roberts",
                "case": case_name,
                "workers": worker,
                "sessions": sessions,
                "sample_sessions": sample_sessions,
                "output_size_bytes": _dir_size(reference_output.parent),
                "file_count": _dir_file_count(reference_output.parent),
            })
            rows.append(reference_row)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "reference_root": str(reference_root),
        "git_commit": _git_text(repo_root, "rev-parse", "HEAD"),
        "git_dirty": bool(_git_text(repo_root, "status", "--porcelain", "--untracked-files=no")),
        "python_executable": python_executable,
        "reference_python": reference_python,
        "platform": platform.platform(),
        "ticks_per_day": int(args.ticks_per_day),
        "warmup": bool(args.warmup),
        "command": {
            "argv": [python_executable, str(Path(__file__).resolve()), *effective_argv],
            "display": subprocess.list2cmdline([python_executable, str(Path(__file__).resolve()), *effective_argv]),
            "cwd": str(Path.cwd().resolve()),
        },
        "cases": rows,
    }

    (output_root / "reference_benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown = render_markdown(report)
    (output_root / "reference_benchmark.md").write_text(markdown, encoding="utf-8")

    print(f"Reference benchmark: {output_root}")
    print(markdown)


if __name__ == "__main__":
    main()
