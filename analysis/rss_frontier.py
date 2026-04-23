from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import psutil
except ImportError:  # pragma: no cover - analysis-only helper
    psutil = None

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[1]
    repo_root_text = str(repo_root)
    if repo_root_text not in sys.path:
        sys.path.insert(0, repo_root_text)

from analysis.benchmark_runtime import _select_effective_root_process  # noqa: E402


DEFAULT_CASE_NAME = "mc_ceiling_light_w8"
MC_DIAGNOSTICS_PATH_ENV = "PROSPERITY_MC_DIAGNOSTICS_PATH"


def _default_output_dir(repo_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return repo_root / "backtests" / f"{timestamp}_rss_frontier"


def _git_text(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    text = completed.stdout.strip()
    return text or None


def _tail_lines(text: str, keep: int = 8) -> list[str]:
    rows = [line.rstrip() for line in text.splitlines() if line.strip()]
    return rows[-keep:]


def _root_relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "n/a"
    sign = "-" if value < 0 else ""
    units = ("B", "KB", "MB", "GB")
    size = float(abs(value))
    unit = units[0]
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            break
        size /= 1024.0
    return f"{sign}{size:.1f} {unit}"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _baseline_case(report_path: Path | None, case_name: str) -> dict[str, Any] | None:
    if report_path is None or not report_path.is_file():
        return None
    payload = _load_json(report_path)
    for case in payload.get("cases", []):
        if str(case.get("case")) == case_name:
            return case
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe the Monte Carlo execution RSS frontier with process-tree sampling.")
    parser.add_argument("--repo-root", default=".", help="Repo root")
    parser.add_argument("--python", default=sys.executable, help="Python executable")
    parser.add_argument("--output-dir", default=None, help="Directory for the generated probe report")
    parser.add_argument("--baseline-report", default=None, help="Optional runtime benchmark report for same-case comparison")
    parser.add_argument("--trader", default="examples/benchmark_trader.py", help="Monte Carlo trader")
    parser.add_argument("--days", nargs="*", type=int, default=[0], help="Monte Carlo day selection")
    parser.add_argument("--fill-mode", default="base", help="Monte Carlo fill mode")
    parser.add_argument("--noise-profile", default="fitted", help="Noise profile")
    parser.add_argument("--sessions", type=int, default=768, help="Session count")
    parser.add_argument("--sample-sessions", type=int, default=24, help="Sample session count")
    parser.add_argument("--workers", type=int, default=8, help="Worker count")
    parser.add_argument("--synthetic-tick-limit", type=int, default=250, help="Synthetic tick cap")
    parser.add_argument("--sample-interval-ms", type=float, default=5.0, help="Process-tree sample interval in milliseconds")
    parser.add_argument("--case-name", default=DEFAULT_CASE_NAME, help="Case label used in the report")
    return parser


def _sample_process_tree(root_pid: int, expected_command: list[str]) -> dict[str, Any] | None:
    try:
        launch_process = psutil.Process(root_pid)
        root_process = _select_effective_root_process(launch_process, expected_command)
        processes = [root_process, *root_process.children(recursive=True)]
    except (psutil.NoSuchProcess, psutil.Error):
        return None
    sample_time = time.perf_counter()
    effective_root_pid = int(root_process.pid)
    root_rss = 0
    tree_rss = 0
    children: list[dict[str, Any]] = []
    for process in processes:
        try:
            rss_bytes = int(process.memory_info().rss)
            name = process.name()
            cmdline = process.cmdline()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        tree_rss += rss_bytes
        if process.pid == effective_root_pid:
            root_rss = rss_bytes
            continue
        children.append({
            "pid": int(process.pid),
            "name": name,
            "rss_bytes": rss_bytes,
            "cmdline": cmdline,
        })
    children.sort(key=lambda row: int(row["rss_bytes"]), reverse=True)
    return {
        "sample_time_seconds": round(sample_time, 6),
        "launch_pid": int(root_pid),
        "root_pid": effective_root_pid,
        "root_rss_bytes": root_rss,
        "tree_rss_bytes": tree_rss,
        "child_process_count": len(children),
        "child_rss_bytes": [int(row["rss_bytes"]) for row in children],
        "children": children,
    }


def _compact_sample(sample: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_time_seconds": sample["sample_time_seconds"],
        "launch_pid": sample.get("launch_pid"),
        "root_pid": sample.get("root_pid"),
        "root_rss_bytes": sample["root_rss_bytes"],
        "tree_rss_bytes": sample["tree_rss_bytes"],
        "child_process_count": sample["child_process_count"],
        "child_rss_bytes": sample["child_rss_bytes"],
    }


def _worker_lifecycle(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_pid: dict[int, dict[str, Any]] = {}
    for sample in samples:
        sample_time = float(sample["sample_time_seconds"])
        for child in sample.get("children", []):
            pid = int(child["pid"])
            state = by_pid.setdefault(pid, {
                "pid": pid,
                "name": child.get("name"),
                "cmdline": child.get("cmdline"),
                "first_seen_seconds": sample_time,
                "last_seen_seconds": sample_time,
                "max_rss_bytes": int(child["rss_bytes"]),
                "min_rss_bytes": int(child["rss_bytes"]),
                "sample_count": 0,
            })
            rss_bytes = int(child["rss_bytes"])
            state["first_seen_seconds"] = min(float(state["first_seen_seconds"]), sample_time)
            state["last_seen_seconds"] = max(float(state["last_seen_seconds"]), sample_time)
            state["max_rss_bytes"] = max(int(state["max_rss_bytes"]), rss_bytes)
            state["min_rss_bytes"] = min(int(state["min_rss_bytes"]), rss_bytes)
            state["sample_count"] = int(state["sample_count"]) + 1
    return sorted(by_pid.values(), key=lambda row: int(row["max_rss_bytes"]), reverse=True)


def _diagnostic_event(events: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for event in events:
        if event.get("event") == name:
            return event
    return None


def _classify_phase(sample_time: float, events: list[dict[str, Any]]) -> str:
    execution_started = _diagnostic_event(events, "execution_started")
    execution_finished = _diagnostic_event(events, "execution_finished")
    compaction_started = _diagnostic_event(events, "sample_row_compaction_started")
    compaction_finished = _diagnostic_event(events, "sample_row_compaction_finished")
    dashboard_started = _diagnostic_event(events, "dashboard_build_started")
    dashboard_finished = _diagnostic_event(events, "dashboard_build_finished")
    bundle_started = _diagnostic_event(events, "bundle_write_started")
    bundle_finished = _diagnostic_event(events, "bundle_write_finished")
    manifest_started = _diagnostic_event(events, "manifest_refresh_started")
    manifest_finished = _diagnostic_event(events, "manifest_refresh_finished")

    intervals = [
        ("execution", execution_started, execution_finished),
        ("sample_row_compaction", compaction_started, compaction_finished),
        ("dashboard_build", dashboard_started, dashboard_finished),
        ("bundle_write", bundle_started, bundle_finished),
        ("manifest_refresh", manifest_started, manifest_finished),
    ]
    for label, start, finish in intervals:
        if start is None or finish is None:
            continue
        start_time = float(start["perf_counter_seconds"])
        finish_time = float(finish["perf_counter_seconds"])
        if start_time <= sample_time <= finish_time:
            return label
    if execution_finished and compaction_started:
        if float(execution_finished["perf_counter_seconds"]) < sample_time < float(compaction_started["perf_counter_seconds"]):
            return "post_execution_pre_reporting"
    return "unclassified"


def _latest_chunk_before(sample_time: float, events: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        event
        for event in events
        if event.get("event") == "chunk_output_received"
        and float(event.get("perf_counter_seconds") or 0.0) <= sample_time
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda row: float(row["perf_counter_seconds"]))


def _peak_sample_for_phases(
    samples: list[dict[str, Any]],
    events: list[dict[str, Any]],
    *,
    phases: set[str],
    key: str,
) -> dict[str, Any] | None:
    matching = [
        sample
        for sample in samples
        if _classify_phase(float(sample["sample_time_seconds"]), events) in phases
    ]
    if not matching:
        return None
    return max(matching, key=lambda row: int(row[key]))


def _render_markdown(report: dict[str, Any]) -> str:
    peak = report["process_tree"]["tree_peak"]
    parent_peak = report["process_tree"]["parent_peak"]
    exec_summary = report["execution_summary"]
    drivers = report["top_memory_drivers"]
    lines = [
        "# RSS Frontier",
        "",
        f"- Case: `{report['case']['case_name']}`",
        f"- Command: `{report['command']['display']}`",
        f"- Tree peak: `{_format_bytes(peak['tree_rss_bytes'])}` at `{peak['sample_time_seconds']:.3f}s`",
        f"- Parent peak: `{_format_bytes(parent_peak['root_rss_bytes'])}` at `{parent_peak['sample_time_seconds']:.3f}s`",
        f"- Peak phase: `{report['diagnostics']['tree_peak_phase']}`",
        f"- Parent RSS at tree peak: `{_format_bytes(exec_summary['parent_rss_at_tree_peak_bytes'])}`",
        f"- Parent pre-reporting retained RSS: `{_format_bytes(exec_summary['before_reporting_rss_bytes'])}`",
        f"- Workers alive at tree peak: `{exec_summary['worker_count_at_tree_peak']}`",
        f"- Worker RSS at tree peak: `{_format_bytes(exec_summary['worker_rss_min_at_tree_peak_bytes'])}` to `{_format_bytes(exec_summary['worker_rss_max_at_tree_peak_bytes'])}`",
        f"- Reporting peak: `{_format_bytes(exec_summary['reporting_peak_bytes'])}` during `{report['diagnostics'].get('reporting_parent_peak_phase') or report['diagnostics']['parent_peak_phase']}`",
        "",
        "## Drivers",
        "",
    ]
    for driver in drivers:
        lines.append(
            f"- `{driver['name']}`: `{_format_bytes(driver['bytes'])}`. {driver['why']}"
        )
    baseline = report.get("baseline_comparison")
    if baseline:
        lines.extend([
            "",
            "## Baseline",
            "",
            f"- Baseline tree peak: `{_format_bytes(baseline.get('baseline_tree_peak_bytes'))}`",
            f"- Current minus baseline: `{_format_bytes(baseline.get('tree_peak_delta_bytes'))}`",
            f"- Baseline elapsed: `{baseline.get('baseline_elapsed_seconds'):.3f}s`",
            f"- Current elapsed: `{report['run']['elapsed_seconds']:.3f}s`",
        ])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if psutil is None:
        raise SystemExit(
            "psutil is required for analysis/rss_frontier.py. "
            "Install the analysis extras or run `python -m pip install psutil`."
        )
    repo_root = Path(args.repo_root).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else _default_output_dir(repo_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise ValueError(f"Output directory must be empty: {output_dir}")
    bundle_dir = output_dir / "case_output"
    diagnostics_path = output_dir / "mc_diagnostics.jsonl"
    env = os.environ.copy()
    env[MC_DIAGNOSTICS_PATH_ENV] = str(diagnostics_path)

    python_executable = str(Path(args.python).resolve())
    command = [
        python_executable,
        "-m",
        "prosperity_backtester",
        "monte-carlo",
        str(Path(args.trader)),
        "--name",
        "frontier",
        "--days",
        *(str(int(day)) for day in args.days),
        "--fill-mode",
        args.fill_mode,
        "--noise-profile",
        args.noise_profile,
        "--sessions",
        str(int(args.sessions)),
        "--sample-sessions",
        str(int(args.sample_sessions)),
        "--workers",
        str(int(args.workers)),
        "--synthetic-tick-limit",
        str(int(args.synthetic_tick_limit)),
        "--output-dir",
        str(bundle_dir),
    ]

    wall_started = time.perf_counter()
    process = subprocess.Popen(
        command,
        cwd=repo_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    sample_interval_seconds = max(0.001, float(args.sample_interval_ms) / 1000.0)
    samples: list[dict[str, Any]] = []
    while process.poll() is None:
        sample = _sample_process_tree(process.pid, command)
        if sample is not None:
            samples.append(sample)
        time.sleep(sample_interval_seconds)
    final_sample = _sample_process_tree(process.pid, command)
    if final_sample is not None:
        samples.append(final_sample)
    stdout_text, stderr_text = process.communicate()
    wall_elapsed = time.perf_counter() - wall_started
    if process.returncode != 0:
        raise RuntimeError(
            "RSS frontier command failed.\n"
            f"stdout tail: {_tail_lines(stdout_text)}\n"
            f"stderr tail: {_tail_lines(stderr_text)}"
        )

    manifest = _load_json(bundle_dir / "manifest.json")
    diagnostics: list[dict[str, Any]] = []
    if diagnostics_path.is_file():
        diagnostics = [
            json.loads(line)
            for line in diagnostics_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    diagnostics.sort(key=lambda row: float(row.get("perf_counter_seconds") or 0.0))

    if not samples:
        raise RuntimeError("No process-tree samples were captured.")
    tree_peak = max(samples, key=lambda row: int(row["tree_rss_bytes"]))
    parent_peak = max(samples, key=lambda row: int(row["root_rss_bytes"]))
    tree_peak_phase = _classify_phase(float(tree_peak["sample_time_seconds"]), diagnostics)
    parent_peak_phase = _classify_phase(float(parent_peak["sample_time_seconds"]), diagnostics)
    pre_reporting_parent_peak = _peak_sample_for_phases(
        samples,
        diagnostics,
        phases={"execution", "post_execution_pre_reporting"},
        key="root_rss_bytes",
    )
    reporting_parent_peak = _peak_sample_for_phases(
        samples,
        diagnostics,
        phases={"sample_row_compaction", "dashboard_build", "bundle_write", "manifest_refresh"},
        key="root_rss_bytes",
    )
    latest_chunk = _latest_chunk_before(float(tree_peak["sample_time_seconds"]), diagnostics)
    worker_rss = [int(value) for value in tree_peak.get("child_rss_bytes", [])]
    worker_total = sum(worker_rss)
    before_reporting = (((manifest.get("provenance") or {}).get("runtime") or {}).get("phase_rss_bytes") or {}).get("before_reporting_rss_bytes")
    phase_rss = (((manifest.get("provenance") or {}).get("runtime") or {}).get("phase_rss_bytes") or {})
    reporting_peak_candidates = [
        int(row.get("rss_peak_bytes") or 0)
        for row in (
            phase_rss.get("sample_row_compaction") or {},
            phase_rss.get("dashboard_build") or {},
            phase_rss.get("bundle_write") or {},
            phase_rss.get("manifest_refresh") or {},
        )
        if isinstance(row, dict)
    ]
    reporting_peak = max(reporting_peak_candidates) if reporting_peak_candidates else 0
    baseline_case = _baseline_case(Path(args.baseline_report).resolve() if args.baseline_report else None, args.case_name)
    worker_lifecycle = _worker_lifecycle(samples)

    tree_peak_parent = int(tree_peak["root_rss_bytes"])
    pre_reporting_parent_peak_bytes = None if pre_reporting_parent_peak is None else int(pre_reporting_parent_peak["root_rss_bytes"])
    reporting_parent_peak_bytes = None if reporting_parent_peak is None else int(reporting_parent_peak["root_rss_bytes"])
    reporting_parent_peak_phase = (
        None
        if reporting_parent_peak is None
        else _classify_phase(float(reporting_parent_peak["sample_time_seconds"]), diagnostics)
    )
    reporting_transient = None
    if before_reporting is not None and reporting_peak:
        reporting_transient = max(0, int(reporting_peak) - int(before_reporting))

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "git_commit": _git_text(repo_root, "rev-parse", "HEAD"),
        "git_dirty": bool(_git_text(repo_root, "status", "--porcelain", "--untracked-files=no")),
        "platform": platform.platform(),
        "python_executable": python_executable,
        "command": {
            "argv": command,
            "display": subprocess.list2cmdline(command),
            "cwd": str(repo_root),
        },
        "case": {
            "case_name": args.case_name,
            "trader": str(Path(args.trader)),
            "days": [int(day) for day in args.days],
            "fill_mode": args.fill_mode,
            "noise_profile": args.noise_profile,
            "sessions": int(args.sessions),
            "sample_sessions": int(args.sample_sessions),
            "workers": int(args.workers),
            "synthetic_tick_limit": int(args.synthetic_tick_limit),
            "bundle_output_dir": _root_relative(bundle_dir, repo_root),
            "diagnostics_path": _root_relative(diagnostics_path, repo_root),
            "sample_interval_ms": float(args.sample_interval_ms),
        },
        "run": {
            "elapsed_seconds": round(wall_elapsed, 6),
            "stdout_tail": _tail_lines(stdout_text),
            "stderr_tail": _tail_lines(stderr_text),
        },
        "process_tree": {
            "sample_count": len(samples),
            "tree_peak": {
                **_compact_sample(tree_peak),
                "children": tree_peak["children"],
            },
            "parent_peak": {
                **_compact_sample(parent_peak),
                "children": parent_peak["children"],
            },
            "near_peak_samples": [
                _compact_sample(sample)
                for sample in sorted(samples, key=lambda row: int(row["tree_rss_bytes"]), reverse=True)[:10]
            ],
            "samples": [_compact_sample(sample) for sample in samples],
            "worker_lifecycle": worker_lifecycle,
        },
        "diagnostics": {
            "events": diagnostics,
            "tree_peak_phase": tree_peak_phase,
            "parent_peak_phase": parent_peak_phase,
            "pre_reporting_parent_peak_phase": (
                None
                if pre_reporting_parent_peak is None
                else _classify_phase(float(pre_reporting_parent_peak["sample_time_seconds"]), diagnostics)
            ),
            "reporting_parent_peak_phase": reporting_parent_peak_phase,
            "latest_chunk_before_tree_peak": latest_chunk,
        },
        "reporting_phase_rss_bytes": phase_rss,
        "execution_summary": {
            "tree_peak_bytes": int(tree_peak["tree_rss_bytes"]),
            "parent_rss_at_tree_peak_bytes": tree_peak_parent,
            "worker_total_rss_at_tree_peak_bytes": worker_total,
            "worker_count_at_tree_peak": len(worker_rss),
            "worker_rss_min_at_tree_peak_bytes": min(worker_rss) if worker_rss else None,
            "worker_rss_max_at_tree_peak_bytes": max(worker_rss) if worker_rss else None,
            "worker_rss_mean_at_tree_peak_bytes": None if not worker_rss else round(statistics.mean(worker_rss), 2),
            "parent_peak_bytes": int(parent_peak["root_rss_bytes"]),
            "parent_peak_before_reporting_bytes": pre_reporting_parent_peak_bytes,
            "parent_peak_during_reporting_bytes": reporting_parent_peak_bytes,
            "before_reporting_rss_bytes": before_reporting,
            "reporting_peak_bytes": reporting_peak or None,
            "reporting_transient_before_reporting_bytes": reporting_transient,
            "global_peak_persistent_after_reporting": (
                before_reporting is not None
                and int(tree_peak["root_rss_bytes"]) <= int(before_reporting)
            ),
        },
        "top_memory_drivers": [
            {
                "name": "live_worker_processes",
                "bytes": worker_total,
                "why": (
                    f"{len(worker_rss)} workers were still alive at the tree peak, "
                    f"each at {_format_bytes(min(worker_rss) if worker_rss else None)} to "
                    f"{_format_bytes(max(worker_rss) if worker_rss else None)}."
                ),
            },
            {
                "name": "parent_root_at_tree_peak",
                "bytes": tree_peak_parent,
                "why": (
                    "Parent root RSS at the exact global tree peak. "
                    "This is the parent share that coexisted with the live workers and combines with them "
                    "to form the tree peak."
                ),
            },
            {
                "name": "reporting_write_path",
                "bytes": reporting_transient or 0,
                "why": (
                    "The parent later peaks during "
                    f"{reporting_parent_peak_phase or parent_peak_phase}, after workers exit. "
                    "This is real write-path pressure, but it does not set the global tree peak."
                ),
            },
        ],
    }
    if baseline_case is not None:
        report["baseline_comparison"] = {
            "baseline_report": _root_relative(Path(args.baseline_report).resolve(), repo_root),
            "baseline_tree_peak_bytes": int(baseline_case.get("peak_tree_rss_bytes") or 0),
            "baseline_elapsed_seconds": float(baseline_case.get("elapsed_seconds") or 0.0),
            "tree_peak_delta_bytes": int(tree_peak["tree_rss_bytes"]) - int(baseline_case.get("peak_tree_rss_bytes") or 0),
            "elapsed_delta_seconds": round(float(report["run"]["elapsed_seconds"]) - float(baseline_case.get("elapsed_seconds") or 0.0), 6),
        }

    (output_dir / "rss_frontier_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (output_dir / "rss_frontier_report.md").write_text(_render_markdown(report), encoding="utf-8")
    print(f"RSS frontier: {output_dir}")


if __name__ == "__main__":
    main()
