from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


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


def _tail_lines(text: str, keep: int = 6) -> list[str]:
    return [line for line in text.splitlines() if line.strip()][-keep:]


def _root_relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _case_output(case_name: str, output_root: Path) -> Path:
    return output_root / "cases" / case_name


def _run_case(
    *,
    case_name: str,
    command: list[str],
    repo_root: Path,
    output_dir: Path,
    case_meta: dict[str, object],
) -> dict[str, object]:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - start
    manifest = _json_or_empty(output_dir / "manifest.json")
    bundle_stats = manifest.get("bundle_stats") if isinstance(manifest.get("bundle_stats"), dict) else {}
    provenance = manifest.get("provenance") if isinstance(manifest.get("provenance"), dict) else {}
    runtime = provenance.get("runtime") if isinstance(provenance.get("runtime"), dict) else {}
    size_bytes = int(bundle_stats.get("total_size_bytes") or _dir_size(output_dir))
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
        "workflow_tier": provenance.get("workflow_tier"),
        "engine_backend": runtime.get("engine_backend"),
        "parallelism": runtime.get("parallelism"),
        "worker_count": runtime.get("worker_count"),
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
) -> dict[str, object]:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - start
    pack_summary = _json_or_empty(output_dir / "pack_summary.json")
    return {
        "case": case_name,
        "command": command,
        "output_dir": _root_relative(output_dir, repo_root),
        "elapsed_seconds": round(elapsed, 3),
        "size_bytes": _dir_size(output_dir),
        "workflow_tier": case_meta.get("workflow_tier"),
        "engine_backend": "python",
        "parallelism": "mixed",
        "worker_count": case_meta.get("worker_count"),
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


def _render_case_row(case: dict[str, object], baseline_lookup: dict[str, dict[str, object]]) -> str:
    baseline = baseline_lookup.get(str(case["case"]))
    baseline_seconds = None if baseline is None else float(baseline.get("elapsed_seconds") or 0.0)
    current_seconds = float(case.get("elapsed_seconds") or 0.0)
    throughput = case.get("throughput_sessions_per_second")
    throughput_text = "n/a" if throughput is None else f"{float(throughput):.2f}"
    return (
        f"| `{case['case']}` | {current_seconds:.3f}s | "
        f"{_format_seconds(baseline_seconds)} | {_format_delta(current_seconds, baseline_seconds)} | "
        f"{throughput_text} | {int(case.get('size_bytes') or 0):,} |"
    )


def render_runtime_benchmark_markdown(report: dict[str, object], baseline_report: dict[str, object] | None = None) -> str:
    baseline_lookup = {
        str(case["case"]): case
        for case in (baseline_report or {}).get("cases", [])
        if isinstance(case, dict)
    }
    lines = [
        "# Runtime Benchmark",
        "",
        "Fixture",
        f"- Repo root: `{report['repo_root']}`",
        f"- Git commit: `{report['git_commit']}`",
        f"- Git dirty: `{report['git_dirty']}`",
        f"- Python: `{report['python_executable']}`",
        f"- Platform: `{report['platform']}`",
        f"- Trader: `{report['trader']}`",
        f"- Monte Carlo trader: `{report['mc_trader']}`",
        f"- Baseline trader: `{report['baseline_trader']}`",
        f"- Data dir: `{report['data_dir']}`",
        f"- Fill mode: `{report['fill_mode']}`",
        f"- MC fill mode: `{report['mc_fill_mode']}`",
        f"- MC synthetic tick limit: `{report['mc_synthetic_tick_limit']}`",
        "",
        "| Case | Current | Baseline | Delta | Sessions/s | Output bytes |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in report["cases"]:
        lines.append(_render_case_row(case, baseline_lookup))
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
    parser.add_argument("--mc-synthetic-tick-limit", type=int, default=250, help="Synthetic tick cap for Monte Carlo benchmark cases")
    parser.add_argument("--workers", nargs="*", type=int, default=[1, 2, 4], help="Worker counts for quick and default Monte Carlo cases")
    parser.add_argument("--quick-sessions", type=int, default=64)
    parser.add_argument("--quick-sample-sessions", type=int, default=8)
    parser.add_argument("--default-sessions", type=int, default=100)
    parser.add_argument("--default-sample-sessions", type=int, default=10)
    parser.add_argument("--heavy-sessions", type=int, default=192)
    parser.add_argument("--heavy-sample-sessions", type=int, default=16)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
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
    baseline_report = _json_or_empty(Path(args.compare_report).resolve()) if args.compare_report else None

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
    ))

    for preset in ("fast", "validation"):
        pack_dir = _case_output(f"pack_{preset}", output_root)
        cases.append(_run_pack_case(
            case_name=f"pack_{preset}",
            command=_python_command(
                python_executable,
                "analysis/research_pack.py",
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
    ))

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "git_commit": _git_text(repo_root, "rev-parse", "HEAD"),
        "git_dirty": bool(_git_text(repo_root, "status", "--porcelain", "--untracked-files=no")),
        "python_executable": python_executable,
        "platform": platform.platform(),
        "trader": trader,
        "mc_trader": mc_trader,
        "baseline_trader": baseline_trader,
        "data_dir": data_dir,
        "fill_mode": args.fill_mode,
        "mc_fill_mode": args.mc_fill_mode,
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
