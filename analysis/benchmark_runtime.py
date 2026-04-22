from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

try:
    import psutil
except ImportError:  # pragma: no cover - optional analysis dependency
    psutil = None


def _git_text(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = completed.stdout.strip()
    return text or None


def _json_or_empty(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _dir_size(path: Path) -> int:
    return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())


def _dir_file_count(path: Path) -> int:
    return sum(1 for child in path.rglob("*") if child.is_file())


def _format_seconds(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}s"


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _format_delta(current: float | None, baseline: float | None) -> str:
    if current is None or baseline is None or baseline == 0:
        return "n/a"
    change = (current - baseline) / baseline
    sign = "+" if change >= 0 else ""
    return f"{sign}{change * 100:.1f}%"


def _format_memory(value: object) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "n/a"
    if number <= 0:
        return "n/a"
    return f"{number / (1024 * 1024):.1f} MB"


def _tail_lines(text: str, keep: int = 6) -> list[str]:
    return [line for line in text.splitlines() if line.strip()][-keep:]


def _root_relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _case_output(case_name: str, output_root: Path) -> Path:
    return output_root / "cases" / case_name


def _sample_process_tree_memory(process: subprocess.Popen[str]) -> dict[str, int | None]:
    if psutil is None:
        return {
            "peak_process_rss_bytes": None,
            "peak_tree_rss_bytes": None,
            "peak_child_process_count": None,
        }
    with contextlib.suppress(psutil.Error):
        root = psutil.Process(process.pid)
        processes = [root, *root.children(recursive=True)]
        process_rss = 0
        tree_rss = 0
        peak_children = max(0, len(processes) - 1)
        for candidate in processes:
            with contextlib.suppress(psutil.Error):
                rss = int(candidate.memory_info().rss)
                tree_rss += rss
                if candidate.pid == process.pid:
                    process_rss = rss
        return {
            "peak_process_rss_bytes": process_rss,
            "peak_tree_rss_bytes": tree_rss,
            "peak_child_process_count": peak_children,
        }
    return {
        "peak_process_rss_bytes": None,
        "peak_tree_rss_bytes": None,
        "peak_child_process_count": None,
    }


def _kill_process_tree(process: subprocess.Popen[str]) -> None:
    if psutil is not None:
        with contextlib.suppress(psutil.Error):
            root = psutil.Process(process.pid)
            for child in root.children(recursive=True):
                with contextlib.suppress(psutil.Error):
                    child.kill()
    with contextlib.suppress(OSError):
        process.kill()


def _run_command_with_monitoring(
    *,
    command: list[str],
    repo_root: Path,
    timeout_seconds: float | None = None,
    sample_interval_seconds: float = 0.02,
) -> tuple[subprocess.CompletedProcess[str], float, dict[str, int | None]]:
    process = subprocess.Popen(
        command,
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    start = time.perf_counter()
    peak_memory = {
        "peak_process_rss_bytes": 0,
        "peak_tree_rss_bytes": 0,
        "peak_child_process_count": 0,
    }
    deadline = None if timeout_seconds is None else time.perf_counter() + timeout_seconds
    while process.poll() is None:
        sample = _sample_process_tree_memory(process)
        for key in peak_memory:
            value = sample.get(key)
            if value is None:
                continue
            peak_memory[key] = max(int(peak_memory[key]), int(value))
        if deadline is not None and time.perf_counter() >= deadline:
            _kill_process_tree(process)
            stdout, stderr = process.communicate()
            raise subprocess.TimeoutExpired(command, timeout_seconds or 0.0, output=stdout, stderr=stderr)
        time.sleep(sample_interval_seconds)
    stdout, stderr = process.communicate()
    elapsed = time.perf_counter() - start
    sample = _sample_process_tree_memory(process)
    for key in peak_memory:
        value = sample.get(key)
        if value is None:
            continue
        peak_memory[key] = max(int(peak_memory[key]), int(value))
    completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(completed.returncode, command, stdout, stderr)
    return completed, elapsed, peak_memory


def _with_output_dir(command: list[str], output_dir: Path) -> list[str]:
    updated = list(command)
    for index, token in enumerate(updated[:-1]):
        if token == "--output-dir":
            updated[index + 1] = str(output_dir)
            return updated
    return updated


def _phase_seconds(phase_timings: dict[str, object], key: str) -> float | None:
    try:
        value = float(phase_timings.get(key) or 0.0)
    except (TypeError, ValueError):
        return None
    return value


def _mc_non_engine_overhead(elapsed: float, phase_timings: dict[str, object]) -> float | None:
    session_wall = _phase_seconds(phase_timings, "session_execution_wall_seconds")
    if session_wall is None:
        return None
    reporting_seconds = sum(
        _phase_seconds(phase_timings, key) or 0.0
        for key in ("sample_row_compaction_seconds", "dashboard_build_seconds", "bundle_write_seconds")
    )
    return max(0.0, elapsed - session_wall - reporting_seconds)


def _run_case(
    *,
    case_name: str,
    command: list[str],
    repo_root: Path,
    output_dir: Path,
    case_meta: dict[str, object],
    warm_repeat: int = 0,
) -> dict[str, object]:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    attempts = max(0, int(warm_repeat)) + 1
    cold_elapsed = None
    best_warm_elapsed = None
    completed: subprocess.CompletedProcess[str] | None = None
    elapsed = 0.0
    peak_memory = {
        "peak_process_rss_bytes": None,
        "peak_tree_rss_bytes": None,
        "peak_child_process_count": None,
    }
    for attempt in range(attempts):
        run_output_dir = output_dir if attempt == attempts - 1 else output_dir.parent / f"{output_dir.name}__warmup_{attempt}"
        completed, elapsed, peak_memory = _run_command_with_monitoring(
            command=_with_output_dir(command, run_output_dir),
            repo_root=repo_root,
        )
        if attempt == 0:
            cold_elapsed = elapsed
        elif best_warm_elapsed is None or elapsed < best_warm_elapsed:
            best_warm_elapsed = elapsed
        if run_output_dir != output_dir and run_output_dir.exists():
            shutil.rmtree(run_output_dir, ignore_errors=True)
    assert completed is not None
    manifest = _json_or_empty(output_dir / "manifest.json")
    bundle_stats = manifest.get("bundle_stats") if isinstance(manifest.get("bundle_stats"), dict) else {}
    provenance = manifest.get("provenance") if isinstance(manifest.get("provenance"), dict) else {}
    runtime = provenance.get("runtime") if isinstance(provenance.get("runtime"), dict) else {}
    phase_timings = runtime.get("phase_timings_seconds") if isinstance(runtime.get("phase_timings_seconds"), dict) else {}
    size_bytes = int(bundle_stats.get("total_size_bytes") or _dir_size(output_dir))
    file_count = int(bundle_stats.get("file_count") or _dir_file_count(output_dir))
    session_count = case_meta.get("session_count")
    throughput = None
    if isinstance(session_count, int) and session_count > 0 and elapsed > 0:
        throughput = session_count / elapsed
    return {
        "case": case_name,
        "command": command,
        "output_dir": _root_relative(output_dir, repo_root),
        "elapsed_seconds": round(elapsed, 3),
        "size_bytes": size_bytes,
        "file_count": file_count,
        "workflow_tier": provenance.get("workflow_tier"),
        "engine_backend": runtime.get("engine_backend"),
        "monte_carlo_backend": runtime.get("monte_carlo_backend"),
        "parallelism": runtime.get("parallelism"),
        "worker_count": runtime.get("worker_count"),
        "phase_timings_seconds": phase_timings,
        "peak_process_rss_bytes": peak_memory.get("peak_process_rss_bytes"),
        "peak_tree_rss_bytes": peak_memory.get("peak_tree_rss_bytes"),
        "peak_child_process_count": peak_memory.get("peak_child_process_count"),
        "non_engine_overhead_seconds": _mc_non_engine_overhead(elapsed, phase_timings),
        "cold_elapsed_seconds": None if attempts <= 1 else round(float(cold_elapsed or 0.0), 3),
        "warm_best_elapsed_seconds": None if attempts <= 1 else round(float(best_warm_elapsed or elapsed), 3),
        "throughput_sessions_per_second": throughput,
        "stdout_tail": _tail_lines(completed.stdout),
        "stderr_tail": _tail_lines(completed.stderr),
        **case_meta,
    }


def _run_pack_case(
    *,
    case_name: str,
    command: list[str],
    repo_root: Path,
    output_dir: Path,
    case_meta: dict[str, object],
    warm_repeat: int = 0,
) -> dict[str, object]:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    attempts = max(0, int(warm_repeat)) + 1
    cold_elapsed = None
    best_warm_elapsed = None
    completed: subprocess.CompletedProcess[str] | None = None
    elapsed = 0.0
    peak_memory = {
        "peak_process_rss_bytes": None,
        "peak_tree_rss_bytes": None,
        "peak_child_process_count": None,
    }
    for attempt in range(attempts):
        run_output_dir = output_dir if attempt == attempts - 1 else output_dir.parent / f"{output_dir.name}__warmup_{attempt}"
        completed, elapsed, peak_memory = _run_command_with_monitoring(
            command=_with_output_dir(command, run_output_dir),
            repo_root=repo_root,
        )
        if attempt == 0:
            cold_elapsed = elapsed
        elif best_warm_elapsed is None or elapsed < best_warm_elapsed:
            best_warm_elapsed = elapsed
        if run_output_dir != output_dir and run_output_dir.exists():
            shutil.rmtree(run_output_dir, ignore_errors=True)
    assert completed is not None
    pack_summary = _json_or_empty(output_dir / "pack_summary.json")
    return {
        "case": case_name,
        "command": command,
        "output_dir": _root_relative(output_dir, repo_root),
        "elapsed_seconds": round(elapsed, 3),
        "size_bytes": _dir_size(output_dir),
        "file_count": _dir_file_count(output_dir),
        "workflow_tier": case_meta.get("workflow_tier"),
        "engine_backend": "python",
        "parallelism": "mixed",
        "worker_count": case_meta.get("worker_count"),
        "peak_process_rss_bytes": peak_memory.get("peak_process_rss_bytes"),
        "peak_tree_rss_bytes": peak_memory.get("peak_tree_rss_bytes"),
        "peak_child_process_count": peak_memory.get("peak_child_process_count"),
        "cold_elapsed_seconds": None if attempts <= 1 else round(float(cold_elapsed or 0.0), 3),
        "warm_best_elapsed_seconds": None if attempts <= 1 else round(float(best_warm_elapsed or elapsed), 3),
        "throughput_sessions_per_second": None,
        "stdout_tail": _tail_lines(completed.stdout),
        "stderr_tail": _tail_lines(completed.stderr),
        "pack_summary": pack_summary,
        **case_meta,
    }


def _python_command(python_executable: str, *args: str) -> list[str]:
    return [python_executable, *args]


def _mc_case_meta(*, tier: str, workers: int, session_count: int, sample_session_count: int, output_profile: str) -> dict[str, object]:
    return {
        "kind": "monte_carlo",
        "tier": tier,
        "worker_count": workers,
        "session_count": session_count,
        "sample_session_count": sample_session_count,
        "output_profile": output_profile,
    }


def _format_phase_seconds(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"{number:.3f}s"


def _mc_phase_line(case: dict[str, object]) -> str | None:
    phase = case.get("phase_timings_seconds")
    if not isinstance(phase, dict) or not phase:
        return None
    reporting_seconds = sum(
        float(phase.get(key) or 0.0)
        for key in ("sample_row_compaction_seconds", "dashboard_build_seconds", "bundle_write_seconds")
    )
    backend = case.get("monte_carlo_backend") or case.get("engine_backend") or "unknown"
    rust_wall = phase.get("rust_internal_wall_seconds")
    rust_suffix = f", rust-parallel-wall {_format_phase_seconds(rust_wall)}" if rust_wall is not None else ""
    provenance_suffix = f", provenance {_format_phase_seconds(phase.get('provenance_capture_seconds'))}"
    overhead_suffix = f", startup/scheduling {_format_phase_seconds(case.get('non_engine_overhead_seconds'))}"
    return (
        f"- `{case['case']}` [{backend}]: market generation {_format_phase_seconds(phase.get('market_generation_seconds'))}, "
        f"trader {_format_phase_seconds(phase.get('trader_seconds'))}, "
        f"execution {_format_phase_seconds(phase.get('execution_seconds'))}, "
        f"path metrics {_format_phase_seconds(phase.get('path_metrics_seconds'))}, "
        f"reporting {_format_phase_seconds(reporting_seconds)}, "
        f"wall {_format_phase_seconds(phase.get('session_execution_wall_seconds'))}"
        f"{overhead_suffix}"
        f"{provenance_suffix}"
        f"{rust_suffix}"
    )


def _render_case_row(case: dict[str, object], baseline_lookup: dict[str, dict[str, object]]) -> str:
    baseline = baseline_lookup.get(str(case["case"]))
    baseline_seconds = None if baseline is None else float(baseline.get("elapsed_seconds") or 0.0)
    current_seconds = float(case.get("elapsed_seconds") or 0.0)
    throughput = case.get("throughput_sessions_per_second")
    throughput_text = "n/a" if throughput is None else f"{float(throughput):.2f}"
    backend = case.get("monte_carlo_backend") or case.get("engine_backend") or "n/a"
    peak_rss_text = _format_memory(case.get("peak_tree_rss_bytes"))
    return (
        f"| `{case['case']}` | {backend} | {current_seconds:.3f}s | "
        f"{_format_seconds(baseline_seconds)} | {_format_delta(current_seconds, baseline_seconds)} | "
        f"{throughput_text} | {peak_rss_text} | {int(case.get('size_bytes') or 0):,} | {int(case.get('file_count') or 0):,} |"
    )


def render_runtime_benchmark_markdown(report: dict[str, object], baseline_report: dict[str, object] | None = None) -> str:
    baseline_lookup = {
        str(case["case"]): case
        for case in (baseline_report or {}).get("cases", [])
        if isinstance(case, dict)
    }
    benchmark_command = report.get("benchmark_command")
    lines = [
        "# Runtime Benchmark",
        "",
        "Fixture",
        f"- Repo root: `{report['repo_root']}`",
        f"- Git commit: `{report['git_commit']}`",
        f"- Git dirty: `{report['git_dirty']}`",
        f"- Python: `{report['python_executable']}`",
        f"- Platform: `{report['platform']}`",
        f"- Logical CPUs: `{report.get('cpu_count_logical')}`",
        f"- Physical CPUs: `{report.get('cpu_count_physical')}`",
        f"- System memory: `{_format_memory(report.get('system_memory_bytes'))}`",
        f"- Memory sampler: `{report.get('memory_sampler')}`",
        f"- Trader: `{report['trader']}`",
        f"- Monte Carlo trader: `{report['mc_trader']}`",
        f"- Baseline trader: `{report['baseline_trader']}`",
        f"- Data dir: `{report['data_dir']}`",
        f"- Fill mode: `{report['fill_mode']}`",
        f"- MC fill mode: `{report['mc_fill_mode']}`",
        f"- Requested MC backend: `{report['requested_mc_backend'] or 'default'}`",
        f"- MC synthetic tick limit: `{report['mc_synthetic_tick_limit']}`",
    ]
    if isinstance(benchmark_command, dict) and benchmark_command.get("display"):
        lines.append(f"- Command: `{benchmark_command['display']}`")
    lines.extend([
        "",
        "| Case | Backend | Current | Baseline | Delta | Sessions/s | Peak RSS | Output bytes | Files |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for case in report["cases"]:
        lines.append(_render_case_row(case, baseline_lookup))
    phase_lines = [
        line
        for line in (
            _mc_phase_line(case)
            for case in report["cases"]
            if case.get("kind") == "monte_carlo" and case.get("case") in {f"mc_default_light_w{max(report['workers'])}", "mc_default_light_w1", f"mc_heavy_light_w{max(report['workers'])}"}
        )
        if line is not None
    ]
    if phase_lines:
        lines.extend([
            "",
            "Monte Carlo phase profile",
            *phase_lines,
        ])
    warm_lines = [
        f"- `{case['case']}`: cold {_format_seconds(case.get('cold_elapsed_seconds'))}, warm-best {_format_seconds(case.get('warm_best_elapsed_seconds'))}"
        for case in report["cases"]
        if case.get("cold_elapsed_seconds") is not None and case.get("warm_best_elapsed_seconds") is not None
    ]
    if warm_lines:
        lines.extend([
            "",
            "Cold vs warm",
            *warm_lines,
        ])
    lines.extend([
        "",
        "Guidance",
        f"- Day-0 replay loop: `{report['recommendations']['replay']}`",
        f"- Day-0 compare loop: `{report['recommendations']['compare']}`",
        f"- Quick MC loop: `{report['recommendations']['mc_quick']}`",
        f"- Default MC loop: `{report['recommendations']['mc_default']}`",
        f"- Heavy MC loop: `{report['recommendations']['mc_heavy']}`",
        "",
    ])
    return "\n".join(lines)


def _worker_values(values: Iterable[int]) -> list[int]:
    deduped = sorted({max(1, int(value)) for value in values})
    return deduped or [1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark replay, compare, pack and Monte Carlo runtime on one repo root")
    parser.add_argument("--repo-root", default=".", help="Repo root to benchmark")
    parser.add_argument("--python", default=sys.executable, help="Python executable to use")
    parser.add_argument("--output-dir", default=None, help="Directory for benchmark reports and case outputs")
    parser.add_argument("--compare-report", default=None, help="Optional previous benchmark_report.json to compare against")
    parser.add_argument("--trader", default="strategies/trader.py", help="Replay and compare trader")
    parser.add_argument("--baseline-trader", default="strategies/starter.py", help="Baseline trader for compare and pack cases")
    parser.add_argument("--mc-trader", default="examples/benchmark_trader.py", help="Monte Carlo benchmark trader")
    parser.add_argument("--data-dir", default="data/round1", help="Historical data directory")
    parser.add_argument("--fill-mode", default="empirical_baseline", help="Replay and compare fill mode")
    parser.add_argument("--mc-fill-mode", default="base", help="Monte Carlo fill mode")
    parser.add_argument("--mc-backend", default=None, choices=["auto", "classic", "streaming", "rust"], help="Optional Monte Carlo backend override for repos that support it")
    parser.add_argument("--mc-synthetic-tick-limit", type=int, default=250, help="Synthetic tick cap for Monte Carlo benchmark cases")
    parser.add_argument("--workers", nargs="*", type=int, default=[1, 2, 4], help="Worker counts for quick and default Monte Carlo cases")
    parser.add_argument("--warm-repeat", type=int, default=0, help="Extra warm reruns per case. The final saved output is from the last run.")
    parser.add_argument("--quick-sessions", type=int, default=64)
    parser.add_argument("--quick-sample-sessions", type=int, default=8)
    parser.add_argument("--default-sessions", type=int, default=100)
    parser.add_argument("--default-sample-sessions", type=int, default=10)
    parser.add_argument("--heavy-sessions", type=int, default=192)
    parser.add_argument("--heavy-sample-sessions", type=int, default=16)
    parser.add_argument("--ceiling-sessions", type=int, default=768)
    parser.add_argument("--ceiling-sample-sessions", type=int, default=24)
    return parser


def _mc_backend_args(value: str | None) -> list[str]:
    if not value:
        return []
    return ["--mc-backend", value]


def main(argv: list[str] | None = None) -> None:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(effective_argv)
    repo_root = Path(args.repo_root).resolve()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_root = Path(args.output_dir).resolve() if args.output_dir else repo_root / "backtests" / f"{timestamp}_runtime_benchmark"
    output_root.mkdir(parents=True, exist_ok=True)
    if any(output_root.iterdir()):
        raise ValueError(f"Runtime benchmark output directory must be empty: {output_root}")

    python_executable = str(Path(args.python).resolve())
    data_dir = str(Path(args.data_dir))
    trader = str(Path(args.trader))
    baseline_trader = str(Path(args.baseline_trader))
    mc_trader = str(Path(args.mc_trader))
    workers = _worker_values(args.workers)
    max_worker = workers[-1]
    warm_repeat = max(0, int(args.warm_repeat))
    baseline_report = _json_or_empty(Path(args.compare_report).resolve()) if args.compare_report else None
    mc_backend_args = _mc_backend_args(args.mc_backend)

    cases: list[dict[str, object]] = []

    replay_light_dir = _case_output("replay_day0_light", output_root)
    cases.append(_run_case(
        case_name="replay_day0_light",
        command=_python_command(
            python_executable,
            "-m",
            "prosperity_backtester",
            "replay",
            trader,
            "--name",
            "current",
            "--data-dir",
            data_dir,
            "--days",
            "0",
            "--fill-mode",
            args.fill_mode,
            "--output-dir",
            str(replay_light_dir),
        ),
        repo_root=repo_root,
        output_dir=replay_light_dir,
        case_meta={"kind": "replay", "tier": "fast", "output_profile": "light"},
        warm_repeat=warm_repeat,
    ))

    replay_full_dir = _case_output("replay_day0_full", output_root)
    cases.append(_run_case(
        case_name="replay_day0_full",
        command=_python_command(
            python_executable,
            "-m",
            "prosperity_backtester",
            "replay",
            trader,
            "--name",
            "current",
            "--data-dir",
            data_dir,
            "--days",
            "0",
            "--fill-mode",
            args.fill_mode,
            "--output-profile",
            "full",
            "--output-dir",
            str(replay_full_dir),
        ),
        repo_root=repo_root,
        output_dir=replay_full_dir,
        case_meta={"kind": "replay", "tier": "forensic", "output_profile": "full"},
        warm_repeat=warm_repeat,
    ))

    compare_dir = _case_output("compare_day0_light", output_root)
    cases.append(_run_case(
        case_name="compare_day0_light",
        command=_python_command(
            python_executable,
            "-m",
            "prosperity_backtester",
            "compare",
            trader,
            baseline_trader,
            "--names",
            "current",
            "baseline",
            "--data-dir",
            data_dir,
            "--days",
            "0",
            "--fill-mode",
            args.fill_mode,
            "--output-dir",
            str(compare_dir),
        ),
        repo_root=repo_root,
        output_dir=compare_dir,
        case_meta={"kind": "comparison", "tier": "fast", "output_profile": "light"},
        warm_repeat=warm_repeat,
    ))

    for preset in ("fast", "validation"):
        pack_dir = _case_output(f"pack_{preset}", output_root)
        cases.append(_run_pack_case(
            case_name=f"pack_{preset}",
            command=_python_command(
                python_executable,
                "-m",
                "analysis.research_pack",
                preset,
                "--trader",
                trader,
                "--baseline",
                baseline_trader,
                "--data-dir",
                data_dir,
                "--fill-mode",
                args.fill_mode,
                "--mc-workers",
                str(max_worker),
                "--output-dir",
                str(pack_dir),
            ),
            repo_root=repo_root,
            output_dir=pack_dir,
            case_meta={"kind": "pack", "tier": preset, "workflow_tier": preset, "worker_count": max_worker},
            warm_repeat=warm_repeat,
        ))

    for worker in workers:
        case_dir = _case_output(f"mc_quick_light_w{worker}", output_root)
        cases.append(_run_case(
            case_name=f"mc_quick_light_w{worker}",
            command=_python_command(
                python_executable,
                "-m",
                "prosperity_backtester",
                "monte-carlo",
                mc_trader,
                "--name",
                "benchmark",
                "--days",
                "0",
                "--fill-mode",
                args.mc_fill_mode,
                "--noise-profile",
                "fitted",
                "--sessions",
                str(args.quick_sessions),
                "--sample-sessions",
                str(args.quick_sample_sessions),
                "--workers",
                str(worker),
                *mc_backend_args,
                "--synthetic-tick-limit",
                str(args.mc_synthetic_tick_limit),
                "--output-dir",
                str(case_dir),
            ),
            repo_root=repo_root,
            output_dir=case_dir,
            case_meta=_mc_case_meta(
                tier="quick",
                workers=worker,
                session_count=args.quick_sessions,
                sample_session_count=args.quick_sample_sessions,
                output_profile="light",
            ),
            warm_repeat=warm_repeat,
        ))

    for worker in workers:
        case_dir = _case_output(f"mc_default_light_w{worker}", output_root)
        cases.append(_run_case(
            case_name=f"mc_default_light_w{worker}",
            command=_python_command(
                python_executable,
                "-m",
                "prosperity_backtester",
                "monte-carlo",
                mc_trader,
                "--name",
                "benchmark",
                "--days",
                "0",
                "--fill-mode",
                args.mc_fill_mode,
                "--noise-profile",
                "fitted",
                "--sessions",
                str(args.default_sessions),
                "--sample-sessions",
                str(args.default_sample_sessions),
                "--workers",
                str(worker),
                *mc_backend_args,
                "--synthetic-tick-limit",
                str(args.mc_synthetic_tick_limit),
                "--output-dir",
                str(case_dir),
            ),
            repo_root=repo_root,
            output_dir=case_dir,
            case_meta=_mc_case_meta(
                tier="default",
                workers=worker,
                session_count=args.default_sessions,
                sample_session_count=args.default_sample_sessions,
                output_profile="light",
            ),
            warm_repeat=warm_repeat,
        ))

    heavy_workers = sorted({1, max_worker})
    for worker in heavy_workers:
        case_dir = _case_output(f"mc_heavy_light_w{worker}", output_root)
        cases.append(_run_case(
            case_name=f"mc_heavy_light_w{worker}",
            command=_python_command(
                python_executable,
                "-m",
                "prosperity_backtester",
                "monte-carlo",
                mc_trader,
                "--name",
                "benchmark",
                "--days",
                "0",
                "--fill-mode",
                args.mc_fill_mode,
                "--noise-profile",
                "fitted",
                "--sessions",
                str(args.heavy_sessions),
                "--sample-sessions",
                str(args.heavy_sample_sessions),
                "--workers",
                str(worker),
                *mc_backend_args,
                "--synthetic-tick-limit",
                str(args.mc_synthetic_tick_limit),
                "--output-dir",
                str(case_dir),
            ),
            repo_root=repo_root,
            output_dir=case_dir,
            case_meta=_mc_case_meta(
                tier="heavy",
                workers=worker,
                session_count=args.heavy_sessions,
                sample_session_count=args.heavy_sample_sessions,
                output_profile="light",
            ),
            warm_repeat=warm_repeat,
        ))

    ceiling_dir = _case_output(f"mc_ceiling_light_w{max_worker}", output_root)
    cases.append(_run_case(
        case_name=f"mc_ceiling_light_w{max_worker}",
        command=_python_command(
            python_executable,
            "-m",
            "prosperity_backtester",
            "monte-carlo",
            mc_trader,
            "--name",
            "benchmark",
            "--days",
            "0",
            "--fill-mode",
            args.mc_fill_mode,
            "--noise-profile",
            "fitted",
            "--sessions",
            str(args.ceiling_sessions),
            "--sample-sessions",
            str(args.ceiling_sample_sessions),
            "--workers",
            str(max_worker),
            *mc_backend_args,
            "--synthetic-tick-limit",
            str(args.mc_synthetic_tick_limit),
            "--output-dir",
            str(ceiling_dir),
        ),
        repo_root=repo_root,
        output_dir=ceiling_dir,
        case_meta=_mc_case_meta(
            tier="ceiling",
            workers=max_worker,
            session_count=args.ceiling_sessions,
            sample_session_count=args.ceiling_sample_sessions,
            output_profile="light",
        ),
        warm_repeat=warm_repeat,
    ))

    mc_full_dir = _case_output("mc_default_full_w1", output_root)
    cases.append(_run_case(
        case_name="mc_default_full_w1",
        command=_python_command(
            python_executable,
            "-m",
            "prosperity_backtester",
            "monte-carlo",
            mc_trader,
            "--name",
            "benchmark",
            "--days",
            "0",
            "--fill-mode",
            args.mc_fill_mode,
            "--noise-profile",
            "fitted",
            "--sessions",
            str(args.default_sessions),
            "--sample-sessions",
            str(args.default_sample_sessions),
            "--workers",
            "1",
            *mc_backend_args,
            "--synthetic-tick-limit",
            str(args.mc_synthetic_tick_limit),
            "--output-profile",
            "full",
            "--output-dir",
            str(mc_full_dir),
        ),
        repo_root=repo_root,
        output_dir=mc_full_dir,
        case_meta=_mc_case_meta(
            tier="default",
            workers=1,
            session_count=args.default_sessions,
            sample_session_count=args.default_sample_sessions,
            output_profile="full",
        ),
        warm_repeat=warm_repeat,
    ))

    mc_full_trimmed_dir = _case_output("mc_default_full_trimmed_w1", output_root)
    cases.append(_run_case(
        case_name="mc_default_full_trimmed_w1",
        command=_python_command(
            python_executable,
            "-m",
            "prosperity_backtester",
            "monte-carlo",
            mc_trader,
            "--name",
            "benchmark",
            "--days",
            "0",
            "--fill-mode",
            args.mc_fill_mode,
            "--noise-profile",
            "fitted",
            "--sessions",
            str(args.default_sessions),
            "--sample-sessions",
            str(args.default_sample_sessions),
            "--workers",
            "1",
            *mc_backend_args,
            "--synthetic-tick-limit",
            str(args.mc_synthetic_tick_limit),
            "--output-profile",
            "full",
            "--no-sample-path-files",
            "--no-session-manifests",
            "--output-dir",
            str(mc_full_trimmed_dir),
        ),
        repo_root=repo_root,
        output_dir=mc_full_trimmed_dir,
        case_meta=_mc_case_meta(
            tier="default",
            workers=1,
            session_count=args.default_sessions,
            sample_session_count=args.default_sample_sessions,
            output_profile="full_trimmed",
        ),
        warm_repeat=warm_repeat,
    ))

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "git_commit": _git_text(repo_root, "rev-parse", "HEAD"),
        "git_dirty": bool(_git_text(repo_root, "status", "--porcelain", "--untracked-files=no")),
        "benchmark_command": {
            "argv": [python_executable, str(Path(__file__).resolve()), *effective_argv],
            "display": subprocess.list2cmdline([python_executable, str(Path(__file__).resolve()), *effective_argv]),
            "cwd": str(Path.cwd().resolve()),
        },
        "python_executable": python_executable,
        "platform": platform.platform(),
        "cpu_count_logical": psutil.cpu_count(logical=True) if psutil is not None else os.cpu_count(),
        "cpu_count_physical": psutil.cpu_count(logical=False) if psutil is not None else None,
        "system_memory_bytes": None if psutil is None else int(psutil.virtual_memory().total),
        "memory_sampler": "psutil process-tree rss" if psutil is not None else "unavailable",
        "trader": trader,
        "mc_trader": mc_trader,
        "baseline_trader": baseline_trader,
        "data_dir": data_dir,
        "fill_mode": args.fill_mode,
        "mc_fill_mode": args.mc_fill_mode,
        "requested_mc_backend": args.mc_backend,
        "mc_synthetic_tick_limit": args.mc_synthetic_tick_limit,
        "workers": workers,
        "cases": cases,
        "recommendations": {
            "replay": "replay_day0_light",
            "compare": "compare_day0_light",
            "mc_quick": f"mc_quick_light_w{max_worker}",
            "mc_default": f"mc_default_light_w{max_worker}",
            "mc_heavy": f"mc_heavy_light_w{max_worker}",
        },
    }

    report_path = output_root / "benchmark_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown = render_runtime_benchmark_markdown(report, baseline_report)
    (output_root / "benchmark_report.md").write_text(markdown, encoding="utf-8")

    print(f"Runtime benchmark: {output_root}")
    print(markdown)


if __name__ == "__main__":
    main()
