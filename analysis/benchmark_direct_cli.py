from __future__ import annotations

import argparse
import json
import platform
import shutil
import statistics
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
    _format_delta,
    _format_seconds,
    _git_text,
    _json_or_empty,
    _root_relative,
    _tail_lines,
    _with_output_dir,
)


DEFAULT_CASES = (
    "replay_day0_light",
    "compare_day0_light",
    "pack_fast",
    "pack_validation",
    "mc_default_light_w8",
    "mc_heavy_light_w8",
    "mc_ceiling_light_w8",
)


def _default_output_dir(repo_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return repo_root / "backtests" / f"{timestamp}_direct_cli_checks"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run direct CLI timing spot checks from a monitored runtime benchmark report")
    parser.add_argument("--repo-root", default=".", help="Repo root")
    parser.add_argument("--python", default=sys.executable, help="Python executable")
    parser.add_argument("--runtime-report", required=True, help="Path to benchmark_runtime.py benchmark_report.json")
    parser.add_argument("--output-dir", default=None, help="Directory for direct CLI rerun bundles and summary")
    parser.add_argument("--cases", nargs="*", default=list(DEFAULT_CASES), help="Case names from the runtime report to rerun directly")
    parser.add_argument("--repeats", type=int, default=3, help="Measured direct CLI repeats per selected case")
    return parser


def _case_lookup(runtime_report: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        str(case.get("case")): case
        for case in runtime_report.get("cases", [])
        if isinstance(case, dict) and case.get("case")
    }


def _run_direct_command(
    *,
    command: list[str],
    repo_root: Path,
) -> tuple[subprocess.CompletedProcess[str], float]:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    elapsed = time.perf_counter() - started
    return completed, elapsed


def _case_output_dir(output_root: Path, case_name: str) -> Path:
    return output_root / case_name


def _summarise_case(
    *,
    case_name: str,
    case_report: dict[str, object],
    repo_root: Path,
    output_root: Path,
    repeats: int,
) -> dict[str, object]:
    command = case_report.get("command")
    if not isinstance(command, list) or not command:
        raise ValueError(f"Runtime report case {case_name!r} does not include a runnable command list")
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    case_output_dir = _case_output_dir(output_root, case_name)
    if case_output_dir.exists():
        shutil.rmtree(case_output_dir, ignore_errors=True)

    measured: list[float] = []
    completed: subprocess.CompletedProcess[str] | None = None
    for repeat_index in range(repeats):
        run_output_dir = case_output_dir if repeat_index == repeats - 1 else case_output_dir.parent / f"{case_output_dir.name}__repeat_{repeat_index}"
        completed, elapsed = _run_direct_command(
            command=_with_output_dir(command, run_output_dir),
            repo_root=repo_root,
        )
        measured.append(elapsed)
        if run_output_dir != case_output_dir and run_output_dir.exists():
            shutil.rmtree(run_output_dir, ignore_errors=True)
    assert completed is not None

    harness_seconds = float(case_report.get("elapsed_seconds") or 0.0)
    mean_seconds = statistics.fmean(measured)
    stdev_seconds = statistics.stdev(measured) if len(measured) > 1 else 0.0
    return {
        "case": case_name,
        "command": command,
        "output_dir": _root_relative(case_output_dir, repo_root),
        "harness_elapsed_seconds": round(harness_seconds, 3),
        "direct_elapsed_seconds": [round(value, 3) for value in measured],
        "direct_mean_seconds": round(mean_seconds, 3),
        "direct_best_seconds": round(min(measured), 3),
        "direct_worst_seconds": round(max(measured), 3),
        "direct_stdev_seconds": round(stdev_seconds, 3),
        "direct_vs_harness_percent_delta": round(((mean_seconds - harness_seconds) / harness_seconds) * 100, 1) if harness_seconds > 0 else None,
        "size_bytes": _dir_size(case_output_dir),
        "file_count": _dir_file_count(case_output_dir),
        "stdout_tail": _tail_lines(completed.stdout),
        "stderr_tail": _tail_lines(completed.stderr),
    }


def _render_case_row(case: dict[str, object]) -> str:
    return (
        f"| `{case['case']}` | {case['harness_elapsed_seconds']:.3f}s | "
        f"{case['direct_mean_seconds']:.3f}s | {_format_seconds(case.get('direct_best_seconds'))} | "
        f"{_format_seconds(case.get('direct_worst_seconds'))} | {_format_seconds(case.get('direct_stdev_seconds'))} | "
        f"{_format_delta(case.get('direct_mean_seconds'), case.get('harness_elapsed_seconds'))} |"
    )


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# Direct CLI Checks",
        "",
        "Fixture",
        f"- Repo root: `{report['repo_root']}`",
        f"- Git commit: `{report['git_commit']}`",
        f"- Git dirty: `{report['git_dirty']}`",
        f"- Python: `{report['python_executable']}`",
        f"- Platform: `{report['platform']}`",
        f"- Runtime report: `{report['runtime_report']}`",
        f"- Repeats per case: `{report['repeats']}`",
        f"- Command: `{report['command']['display']}`",
        "",
        "| Case | Harness | Direct mean | Best | Worst | Stdev | Mean vs harness |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in report["cases"]:
        lines.append(_render_case_row(case))
    lines.extend([
        "",
        "Interpretation",
        "- These timings are bare CLI wall-clock reruns of the same case commands, with process-tree monitoring removed.",
        "- Use them for short-case throughput headlines when the monitored harness adds a material distortion band.",
        "- Keep the monitored harness for RSS, phase timings and regression tracking.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(effective_argv)

    repo_root = Path(args.repo_root).resolve()
    runtime_report_path = Path(args.runtime_report).resolve()
    runtime_report = _json_or_empty(runtime_report_path)
    if not runtime_report:
        raise ValueError(f"Could not load runtime report: {runtime_report_path}")
    output_root = Path(args.output_dir).resolve() if args.output_dir else _default_output_dir(repo_root)
    output_root.mkdir(parents=True, exist_ok=True)
    if any(output_root.iterdir()):
        raise ValueError(f"Direct CLI output directory must be empty: {output_root}")

    case_lookup = _case_lookup(runtime_report)
    selected_cases = [str(case_name) for case_name in args.cases]
    missing = [case_name for case_name in selected_cases if case_name not in case_lookup]
    if missing:
        raise ValueError(f"Runtime report is missing requested case(s): {', '.join(missing)}")

    cases = [
        _summarise_case(
            case_name=case_name,
            case_report=case_lookup[case_name],
            repo_root=repo_root,
            output_root=output_root,
            repeats=max(1, int(args.repeats)),
        )
        for case_name in selected_cases
    ]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "runtime_report": _root_relative(runtime_report_path, repo_root),
        "git_commit": _git_text(repo_root, "rev-parse", "HEAD"),
        "git_dirty": bool(_git_text(repo_root, "status", "--porcelain", "--untracked-files=no")),
        "python_executable": str(Path(args.python).resolve()),
        "platform": platform.platform(),
        "repeats": max(1, int(args.repeats)),
        "command": {
            "argv": [str(Path(args.python).resolve()), str(Path(__file__).resolve()), *effective_argv],
            "display": subprocess.list2cmdline([str(Path(args.python).resolve()), str(Path(__file__).resolve()), *effective_argv]),
            "cwd": str(Path.cwd().resolve()),
        },
        "cases": cases,
        "conclusion": (
            "Use direct CLI means for short-case throughput headlines when the monitored harness delta is material. "
            "Keep the monitored harness as the source of truth for RSS and phase accounting."
        ),
    }

    (output_root / "direct_cli_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown = render_markdown(report)
    (output_root / "direct_cli_summary.md").write_text(markdown, encoding="utf-8")

    print(f"Direct CLI checks: {output_root}")
    print(markdown)


if __name__ == "__main__":
    main()
