from __future__ import annotations

import argparse
import json
import platform as platform_module
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

if __package__ in {None, ""}:
    repo_root_text = str(Path(__file__).resolve().parent.parent)
    if repo_root_text not in sys.path:
        sys.path.insert(0, repo_root_text)

from analysis.benchmark_runtime import _git_text  # noqa: E402
from prosperity_backtester.bundle_attribution import build_bundle_attribution  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Attribute retained bytes, file counts and dashboard sections for benchmark bundles")
    parser.add_argument("--runtime-report", default=None, help="Path to benchmark_report.json from analysis/benchmark_runtime.py")
    parser.add_argument("--bundle-dir", action="append", default=[], help="Explicit bundle directory to inspect; may be passed multiple times")
    parser.add_argument("--output-dir", default=None, help="Directory for the attribution report")
    return parser


def _default_output_dir(repo_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    return repo_root / "backtests" / f"{timestamp}_bundle_attribution"


def _load_runtime_report(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _bundle_dirs_from_runtime_report(report_path: Path, repo_root: Path) -> list[Path]:
    report = _load_runtime_report(report_path)
    bundle_dirs: list[Path] = []
    for case in report.get("cases", []):
        if not isinstance(case, dict):
            continue
        output_dir = case.get("output_dir")
        if not output_dir:
            continue
        bundle_dir = (repo_root / str(output_dir)).resolve()
        if bundle_dir.is_dir() and (bundle_dir / "dashboard.json").is_file():
            bundle_dirs.append(bundle_dir)
    return bundle_dirs


def _root_relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _inspect_bundle(bundle_dir: Path, repo_root: Path) -> dict[str, object]:
    dashboard_path = bundle_dir / "dashboard.json"
    manifest_path = bundle_dir / "manifest.json"
    payload = json.loads(dashboard_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    bundle_files = manifest.get("bundle_files") if isinstance(manifest.get("bundle_files"), list) else []
    attribution = build_bundle_attribution(payload, bundle_files, include_object_sizes=True)
    dashboard_sections = attribution["dashboard_sections"]
    file_components = attribution["file_components"]
    top_dashboard = dashboard_sections[:8]
    top_files = file_components[:8]
    return {
        "bundle_dir": _root_relative(bundle_dir, repo_root),
        "run_type": payload.get("type"),
        "bundle_stats": manifest.get("bundle_stats") if isinstance(manifest.get("bundle_stats"), dict) else {},
        "phase_timings_seconds": (((manifest.get("provenance") or {}).get("runtime") or {}).get("phase_timings_seconds") or {}),
        "phase_rss_bytes": (((manifest.get("provenance") or {}).get("runtime") or {}).get("phase_rss_bytes") or {}),
        "dashboard_sections": dashboard_sections,
        "file_components": file_components,
        "top_dashboard_sections": top_dashboard,
        "top_file_components": top_files,
    }


def _top_targets(bundles: list[dict[str, object]]) -> list[dict[str, object]]:
    scores: dict[str, dict[str, object]] = {}
    for bundle in bundles:
        for row in bundle.get("dashboard_sections", []):
            if not isinstance(row, dict):
                continue
            component = str(row.get("component") or "")
            if not component:
                continue
            state = scores.setdefault(component, {"component": component, "json_bytes_total": 0, "bundle_count": 0})
            state["json_bytes_total"] = int(state["json_bytes_total"]) + int(row.get("json_bytes") or 0)
            state["bundle_count"] = int(state["bundle_count"]) + 1
    ranked = []
    for state in scores.values():
        bundle_count = max(1, int(state["bundle_count"]))
        ranked.append({
            "component": state["component"],
            "mean_json_bytes": round(int(state["json_bytes_total"]) / bundle_count),
            "bundle_count": bundle_count,
        })
    return sorted(ranked, key=lambda row: int(row["mean_json_bytes"]), reverse=True)[:10]


def _render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# Bundle Attribution",
        "",
        "Fixture",
        f"- Generated at: `{report['generated_at']}`",
        f"- Repo root: `{report['repo_root']}`",
        f"- Git commit: `{report['git_commit']}`",
        f"- Git dirty: `{report['git_dirty']}`",
        f"- Platform: `{report['platform']}`",
    ]
    runtime_report = report.get("runtime_report")
    if runtime_report:
        lines.append(f"- Runtime report: `{runtime_report}`")
    lines.extend([
        "",
        "## Top retained dashboard targets",
        "",
        "| Component | Mean JSON bytes | Bundles |",
        "| --- | ---: | ---: |",
    ])
    for row in report["top_targets"]:
        lines.append(f"| `{row['component']}` | {int(row['mean_json_bytes']):,} | {int(row['bundle_count'])} |")
    for bundle in report["bundles"]:
        lines.extend([
            "",
            f"## {bundle['bundle_dir']}",
            "",
            f"- Run type: `{bundle.get('run_type')}`",
            f"- Bundle bytes: `{int((bundle.get('bundle_stats') or {}).get('total_size_bytes') or 0):,}`",
            f"- Files: `{int((bundle.get('bundle_stats') or {}).get('file_count') or 0):,}`",
            "",
            "Top dashboard sections",
        ])
        for row in bundle["top_dashboard_sections"]:
            lines.append(f"- `{row['component']}`: `{int(row.get('json_bytes') or 0):,}` bytes")
        lines.extend(["", "Top file components"])
        for row in bundle["top_file_components"]:
            lines.append(f"- `{row['component']}`: `{int(row.get('size_bytes') or 0):,}` bytes across `{int(row.get('file_count') or 0)}` files")
        phase_rss = bundle.get("phase_rss_bytes")
        if isinstance(phase_rss, dict) and phase_rss:
            lines.extend(["", "Reporting-phase RSS"])
            before = phase_rss.get("before_reporting_rss_bytes")
            after = phase_rss.get("after_reporting_rss_bytes")
            if isinstance(before, (int, float)) or isinstance(after, (int, float)):
                if isinstance(before, (int, float)):
                    lines.append(f"- Before reporting: `{int(before):,}` bytes")
                if isinstance(after, (int, float)):
                    lines.append(f"- After reporting: `{int(after):,}` bytes")
            for key in ("sample_row_compaction", "dashboard_build", "bundle_write", "manifest_refresh"):
                row = phase_rss.get(key)
                if isinstance(row, dict):
                    lines.append(
                        f"- `{key}`: peak `{int(row.get('rss_peak_bytes') or 0):,}`, "
                        f"delta `{int(row.get('rss_delta_bytes') or 0):,}` bytes"
                    )
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parent.parent
    runtime_report = Path(args.runtime_report).resolve() if args.runtime_report else None
    output_dir = Path(args.output_dir).resolve() if args.output_dir else _default_output_dir(repo_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise ValueError(f"Attribution output directory must be empty: {output_dir}")

    bundle_dirs = [Path(path).resolve() for path in args.bundle_dir]
    if runtime_report is not None:
        bundle_dirs.extend(_bundle_dirs_from_runtime_report(runtime_report, repo_root))
    unique_bundle_dirs: list[Path] = []
    seen: set[Path] = set()
    for bundle_dir in bundle_dirs:
        if bundle_dir in seen:
            continue
        seen.add(bundle_dir)
        unique_bundle_dirs.append(bundle_dir)
    if not unique_bundle_dirs:
        raise ValueError("Provide --runtime-report or at least one --bundle-dir")

    bundles = [_inspect_bundle(bundle_dir, repo_root) for bundle_dir in unique_bundle_dirs]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "git_commit": _git_text(repo_root, "rev-parse", "HEAD"),
        "git_dirty": bool(_git_text(repo_root, "status", "--porcelain", "--untracked-files=no")),
        "platform": platform_module.platform(),
        "runtime_report": None if runtime_report is None else _root_relative(runtime_report, repo_root),
        "bundles": bundles,
        "top_targets": _top_targets(bundles),
    }
    (output_dir / "bundle_attribution.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (output_dir / "bundle_attribution.md").write_text(_render_markdown(report), encoding="utf-8")
    print(f"Bundle attribution: {output_dir}")


if __name__ == "__main__":
    main()
