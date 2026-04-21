from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Sequence

from .experiments import TraderSpec, run_monte_carlo, run_replay
from .platform import PerturbationConfig
from .storage import OutputOptions


_TRADEOFFS = {
    ("replay", "light"): (
        "Exact replay summary and fills, compact event-aware paths, compact submitted quote intent. "
        "Best daily default when raw order rows are not needed."
    ),
    ("replay", "full"): (
        "Adds raw submitted orders and full chart-series sidecars. "
        "Use when debugging quote placement, order-level sequencing or exact path chronology."
    ),
    ("monte_carlo", "light"): (
        "Exact final distribution metrics and all-session path bands, with sample runs kept only inside dashboard.json. "
        "Best daily default for robustness review."
    ),
    ("monte_carlo", "full"): (
        "Adds duplicate sample path files, session manifests and full sample-path sidecars. "
        "Use for forensic Monte Carlo debugging or export-heavy workflows."
    ),
}


def _format_bytes(size_bytes: int) -> str:
    value = float(size_bytes)
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f} GB"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f} MB"
    if value >= 1_000:
        return f"{value / 1_000:.1f} KB"
    return f"{int(value)} B"


def _scan_bundle_files(output_dir: Path) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for path in sorted(p for p in output_dir.rglob("*") if p.is_file()):
        relative_path = str(path.relative_to(output_dir)).replace("\\", "/")
        rows.append({
            "path": relative_path,
            "size_bytes": path.stat().st_size,
        })
    return rows


def _copy_benchmark_fixture(source_dir: Path, target_dir: Path, days: Sequence[int], round_number: int, timestamp_limit: int) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    for day in days:
        prices_name = f"prices_round_{round_number}_day_{day}.csv"
        trades_name = f"trades_round_{round_number}_day_{day}.csv"
        price_source = source_dir / prices_name
        trade_source = source_dir / trades_name
        if not price_source.is_file():
            raise FileNotFoundError(f"Missing benchmark fixture source: {price_source}")
        if not trade_source.is_file():
            raise FileNotFoundError(f"Missing benchmark fixture source: {trade_source}")

        allowed_timestamps: List[str] = []
        seen_timestamps: set[str] = set()
        price_rows: List[str] = []
        with price_source.open(encoding="utf-8") as handle:
            header = handle.readline()
            for line in handle:
                parts = line.rstrip("\n").split(";")
                if len(parts) < 2:
                    continue
                timestamp = parts[1]
                if timestamp not in seen_timestamps and len(allowed_timestamps) < timestamp_limit:
                    seen_timestamps.add(timestamp)
                    allowed_timestamps.append(timestamp)
                if timestamp in seen_timestamps:
                    price_rows.append(line)
        (target_dir / prices_name).write_text(header + "".join(price_rows), encoding="utf-8")

        trade_rows: List[str] = []
        with trade_source.open(encoding="utf-8") as handle:
            trade_header = handle.readline()
            for line in handle:
                parts = line.rstrip("\n").split(";")
                if not parts:
                    continue
                if parts[0] in seen_timestamps:
                    trade_rows.append(line)
        (target_dir / trades_name).write_text(trade_header + "".join(trade_rows), encoding="utf-8")
    return target_dir


def _load_manifest(output_dir: Path) -> Dict[str, object]:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.is_file():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _bundle_summary(output_dir: Path) -> Dict[str, object]:
    manifest = _load_manifest(output_dir)
    bundle_files = manifest.get("bundle_files") if isinstance(manifest.get("bundle_files"), list) else _scan_bundle_files(output_dir)
    bundle_stats = manifest.get("bundle_stats") if isinstance(manifest.get("bundle_stats"), dict) else {}
    total_size = int(bundle_stats.get("total_size_bytes") or sum(int(row.get("size_bytes", 0) or 0) for row in bundle_files))
    file_count = int(bundle_stats.get("file_count") or len(bundle_files))
    return {
        "bundle_size_bytes": total_size,
        "bundle_size_human": _format_bytes(total_size),
        "file_count": file_count,
        "canonical_files": list(manifest.get("canonical_files") or []),
        "sidecar_files": list(manifest.get("sidecar_files") or []),
        "debug_files": list(manifest.get("debug_files") or []),
        "files": bundle_files,
    }


def _case_result(case_name: str, run_type: str, profile: str, output_dir: Path) -> Dict[str, object]:
    summary = _bundle_summary(output_dir)
    return {
        "case": case_name,
        "run_type": run_type,
        "profile": profile,
        "output_dir": str(output_dir),
        "research_tradeoff": _TRADEOFFS[(run_type, profile)],
        **summary,
    }


def render_benchmark_markdown(report: Dict[str, object]) -> str:
    lines = [
        "# Output Benchmark",
        "",
        "Fixture",
        f"- Trader: `{report['trader_name']}`",
        f"- Trader path: `{report['trader_path']}`",
        f"- Data dir: `{report['data_dir']}`",
        f"- Round: `{report['round']}`",
        f"- Days: `{', '.join(str(day) for day in report['days'])}`",
        f"- Benchmark fixture: first `{report['fixture_timestamp_limit']}` timestamps per selected day copied to `{report['fixture_data_dir']}`",
        f"- Fill model: `{report['fill_model']}`",
        f"- Monte Carlo sessions: `{report['mc_sessions']}`",
        f"- Monte Carlo sample sessions: `{report['mc_sample_sessions']}`",
        "",
        "| Case | Size | Files | Trade-off |",
        "| --- | ---: | ---: | --- |",
    ]
    for case in report["cases"]:
        lines.append(
            f"| `{case['case']}` | {case['bundle_size_human']} | {case['file_count']} | {case['research_tradeoff']} |"
        )
    lines.append("")
    for case in report["cases"]:
        lines.append(f"## {case['case']}")
        lines.append("")
        lines.append(f"- Size: {case['bundle_size_human']} ({case['bundle_size_bytes']} bytes)")
        lines.append(f"- Files: {case['file_count']}")
        lines.append(f"- Canonical files: {', '.join(case['canonical_files']) if case['canonical_files'] else 'none'}")
        lines.append(f"- Sidecar files: {', '.join(case['sidecar_files']) if case['sidecar_files'] else 'none'}")
        lines.append(f"- Debug files: {', '.join(case['debug_files']) if case['debug_files'] else 'none'}")
        lines.append("- File list:")
        for row in case["files"]:
            lines.append(f"  - `{row['path']}` ({row['size_bytes']} bytes)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def run_output_benchmark(
    *,
    output_root: Path,
    trader_spec: TraderSpec,
    data_dir: Path,
    days: Sequence[int],
    round_number: int,
    fill_model_name: str,
    perturbation: PerturbationConfig,
    mc_sessions: int,
    mc_sample_sessions: int,
    mc_seed: int = 20260418,
    mc_workers: int = 1,
    fixture_timestamp_limit: int = 250,
) -> Dict[str, object]:
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    if any(output_root.iterdir()):
        raise ValueError(f"Benchmark output directory must be empty: {output_root}")

    benchmark_data_dir = _copy_benchmark_fixture(
        data_dir.resolve(),
        output_root / "_benchmark_fixture",
        days,
        round_number,
        fixture_timestamp_limit,
    )

    replay_light_dir = output_root / "replay_light"
    replay_full_dir = output_root / "replay_full"
    mc_light_dir = output_root / "mc_light"
    mc_full_dir = output_root / "mc_full"

    run_replay(
        trader_spec=trader_spec,
        days=days,
        data_dir=benchmark_data_dir,
        fill_model_name=fill_model_name,
        perturbation=perturbation,
        output_dir=replay_light_dir,
        run_name="replay_light",
        output_options=OutputOptions.from_profile("light"),
        register=False,
    )
    run_replay(
        trader_spec=trader_spec,
        days=days,
        data_dir=benchmark_data_dir,
        fill_model_name=fill_model_name,
        perturbation=perturbation,
        output_dir=replay_full_dir,
        run_name="replay_full",
        output_options=OutputOptions.from_profile("full"),
        register=False,
    )
    run_monte_carlo(
        trader_spec=trader_spec,
        sessions=mc_sessions,
        sample_sessions=mc_sample_sessions,
        days=days,
        fill_model_name=fill_model_name,
        perturbation=perturbation,
        output_dir=mc_light_dir,
        base_seed=mc_seed,
        run_name="mc_light",
        workers=mc_workers,
        output_options=OutputOptions.from_profile("light"),
        register=False,
    )
    run_monte_carlo(
        trader_spec=trader_spec,
        sessions=mc_sessions,
        sample_sessions=mc_sample_sessions,
        days=days,
        fill_model_name=fill_model_name,
        perturbation=perturbation,
        output_dir=mc_full_dir,
        base_seed=mc_seed,
        run_name="mc_full",
        workers=mc_workers,
        output_options=OutputOptions.from_profile("full"),
        register=False,
    )

    report = {
        "trader_name": trader_spec.name,
        "trader_path": str(trader_spec.path),
        "data_dir": str(data_dir),
        "fixture_data_dir": str(benchmark_data_dir),
        "fixture_timestamp_limit": int(fixture_timestamp_limit),
        "round": int(round_number),
        "days": list(days),
        "fill_model": fill_model_name,
        "mc_sessions": int(mc_sessions),
        "mc_sample_sessions": int(mc_sample_sessions),
        "cases": [
            _case_result("replay_light", "replay", "light", replay_light_dir),
            _case_result("replay_full", "replay", "full", replay_full_dir),
            _case_result("mc_light", "monte_carlo", "light", mc_light_dir),
            _case_result("mc_full", "monte_carlo", "full", mc_full_dir),
        ],
    }

    (output_root / "benchmark_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (output_root / "benchmark_report.md").write_text(render_benchmark_markdown(report), encoding="utf-8")
    return report
