"""Build a workspace dashboard bundle from a list of single-purpose bundles.

A workspace bundle is a normal dashboard payload whose ``type`` field is
``workspace``. Each top-level analysis section is sourced from a child
dashboard bundle, while the workspace metadata keeps explicit provenance about
which child powered each promoted section and which sources were retained only
as supporting evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .provenance import capture_provenance


REPLAY_FEATURE_KEYS = (
    "summary",
    "orders",
    "orderIntent",
    "fills",
    "inventorySeries",
    "pnlSeries",
    "fairValueSeries",
    "fairValueSummary",
    "behaviour",
    "behaviourSeries",
    "sessionRows",
)

CORE_SECTION_KEYS = (
    "replay",
    "montecarlo",
    "calibration",
    "compare",
    "optimize",
    "round2",
)

ALL_DASHBOARD_SECTIONS = (
    "overview",
    "replay",
    "montecarlo",
    "calibration",
    "compare",
    "optimize",
    "round2",
    "inspect",
    "osmium",
    "pepper",
    "alpha",
)

ALPHA_EVIDENCE_SECTIONS = frozenset({"replay", "montecarlo", "compare", "round2"})
SECTION_ORDER = {section: index for index, section in enumerate(ALL_DASHBOARD_SECTIONS)}


def _is_nonempty(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0
    return True


def _section_order(section: str) -> int:
    return SECTION_ORDER.get(section, 999)


def _bundle_core_sections(payload: Mapping[str, object]) -> list[str]:
    """Return the primary dashboard sections a child payload can contribute."""
    sections: list[str] = []
    if any(_is_nonempty(payload.get(key)) for key in REPLAY_FEATURE_KEYS):
        sections.append("replay")
    monte_carlo = payload.get("monteCarlo")
    if isinstance(monte_carlo, Mapping) and monte_carlo.get("summary"):
        sections.append("montecarlo")
    calibration = payload.get("calibration")
    if isinstance(calibration, Mapping) and (calibration.get("grid") or calibration.get("best")):
        sections.append("calibration")
    if _is_nonempty(payload.get("comparison")):
        sections.append("compare")
    optimization = payload.get("optimization")
    if isinstance(optimization, Mapping) and _is_nonempty(optimization.get("rows")):
        sections.append("optimize")
    round2 = payload.get("round2")
    if isinstance(round2, Mapping) and (_is_nonempty(round2.get("scenarioRows")) or _is_nonempty(round2.get("winnerRows"))):
        sections.append("round2")
    return sections


def _derive_workspace_sections(
    core_sections: Iterable[str],
    *,
    include_overview: bool,
) -> list[str]:
    present = set(core_sections)
    if include_overview:
        present.add("overview")
    if "replay" in present:
        present.update({"inspect", "osmium", "pepper"})
    if present & ALPHA_EVIDENCE_SECTIONS:
        present.add("alpha")
    return [section for section in ALL_DASHBOARD_SECTIONS if section in present]


def _source_workspace_sections(payload: Mapping[str, object]) -> list[str]:
    return _derive_workspace_sections(_bundle_core_sections(payload), include_overview=False)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _collect_string_notes(target: list[str], seen: set[str], value: object) -> None:
    if not isinstance(value, list):
        return
    for item in value:
        if not isinstance(item, str):
            continue
        note = item.strip()
        if not note or note in seen:
            continue
        seen.add(note)
        target.append(note)


def _collect_data_contract_entries(
    target: list[dict[str, object]],
    seen: set[str],
    value: object,
) -> None:
    if not isinstance(value, list):
        return
    for entry in value:
        if not isinstance(entry, Mapping):
            continue
        serialised = json.dumps(dict(entry), sort_keys=True)
        if serialised in seen:
            continue
        seen.add(serialised)
        target.append(dict(entry))


@dataclass(frozen=True)
class WorkspaceSource:
    path: Path
    payload: Mapping[str, object]
    relative_path: str


@dataclass
class WorkspaceAssembly:
    payload: dict[str, object]
    present_sections: list[str] = field(default_factory=list)
    missing_sections: list[str] = field(default_factory=list)
    source_records: list[dict[str, object]] = field(default_factory=list)


def _load_child(path: Path) -> Mapping[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _default_meta(name: str, created_at: str) -> dict[str, object]:
    return {
        "schemaVersion": 3,
        "runName": name,
        "traderName": "workspace",
        "mode": "workspace",
        "fillModel": {
            "name": "workspace",
            "passive_fill_rate": 0.0,
            "same_price_queue_share": 0.0,
            "queue_pressure": 0.0,
            "missed_fill_probability": 0.0,
            "adverse_selection_ticks": 0,
            "aggressive_slippage_ticks": 0,
        },
        "perturbations": {},
        "outputProfile": {
            "profile": "workspace",
        },
        "createdAt": created_at,
    }


def _copy_feature_keys(
    destination: dict[str, object],
    source: Mapping[str, object],
    keys: Sequence[str],
    *,
    contributions: dict[str, str],
) -> bool:
    took_any = False
    for key in keys:
        if key in destination:
            continue
        value = source.get(key)
        if not _is_nonempty(value):
            continue
        destination[key] = value
        contributions[key] = key
        took_any = True
    return took_any


def assemble_workspace_payload(
    sources: Sequence[WorkspaceSource],
    *,
    name: str,
    notes: str | None = None,
    created_at: datetime | None = None,
) -> WorkspaceAssembly:
    """Merge ``sources`` into a single workspace dashboard payload."""
    if not sources:
        raise ValueError("at least one source dashboard bundle is required")

    created = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    created_iso = created.isoformat()
    workspace_payload: dict[str, object] = {
        "type": "workspace",
        "meta": _default_meta(name, created_iso),
        "products": [],
        "assumptions": {"exact": [], "approximate": []},
        "datasetReports": [],
        "validation": {},
    }

    section_feature_map: dict[str, tuple[str, ...]] = {
        "replay": REPLAY_FEATURE_KEYS,
        "montecarlo": ("monteCarlo",),
        "calibration": ("calibration",),
        "compare": ("comparison", "comparisonDiagnostics"),
        "optimize": ("optimization",),
        "round2": ("round2",),
    }

    assembly = WorkspaceAssembly(payload=workspace_payload)
    present_core_sections: set[str] = set()
    promoted_by: dict[str, str] = {}
    shadowed_by: dict[str, list[str]] = {}
    shadowed_core_by: dict[str, list[str]] = {}
    first_populated_meta: Mapping[str, object] | None = None
    seen_products: list[str] = []
    dataset_reports: list[object] = []
    exact_assumptions: list[str] = []
    approximate_assumptions: list[str] = []
    seen_assumptions: set[str] = set()
    data_contract_entries: list[dict[str, object]] = []
    seen_data_contract_entries: set[str] = set()

    for source in sources:
        payload = source.payload
        source_label = source.relative_path
        source_core_sections = _bundle_core_sections(payload)
        source_sections = _source_workspace_sections(payload)
        contributions: dict[str, str] = {}
        promoted_core_sections: list[str] = []
        shadowed_core_sections: list[str] = []

        for section in CORE_SECTION_KEYS:
            if section not in source_core_sections:
                continue
            if section in present_core_sections:
                shadowed_core_sections.append(section)
                shadowed_core_by.setdefault(section, []).append(source_label)
                continue
            keys = section_feature_map[section]
            if _copy_feature_keys(workspace_payload, payload, keys, contributions=contributions):
                present_core_sections.add(section)
                promoted_core_sections.append(section)

        promoted_sections = _derive_workspace_sections(promoted_core_sections, include_overview=False)
        shadowed_sections = [section for section in source_sections if section not in promoted_sections]

        for section in promoted_sections:
            promoted_by.setdefault(section, source_label)
        for section in shadowed_sections:
            shadowed_by.setdefault(section, []).append(source_label)

        meta = _mapping(payload.get("meta"))
        provenance = _mapping(meta.get("provenance"))
        runtime = _mapping(provenance.get("runtime"))
        git = _mapping(provenance.get("git"))
        output_profile = _mapping(meta.get("outputProfile"))

        note: str | None = None
        if promoted_sections and shadowed_sections:
            note = (
                "Promoted "
                + ", ".join(promoted_sections)
                + "; kept "
                + ", ".join(shadowed_sections)
                + " as provenance-only evidence."
            )
        elif not promoted_sections and shadowed_sections:
            note = "Kept for provenance only because earlier source bundles already claimed these sections."
        elif not source_sections:
            note = "Does not expose a dashboard section the workspace can promote."

        assembly.source_records.append(
            {
                "path": source_label,
                "name": meta.get("runName") or source.path.parent.name,
                "runName": meta.get("runName"),
                "type": str(payload.get("type") or "unknown"),
                "createdAt": meta.get("createdAt"),
                "finalPnl": _mapping(payload.get("summary")).get("final_pnl"),
                "sections": source_sections,
                "promotedSections": promoted_sections,
                "shadowedSections": shadowed_sections,
                "profile": output_profile.get("profile"),
                "traderName": meta.get("traderName"),
                "mode": meta.get("mode"),
                "workflowTier": provenance.get("workflow_tier"),
                "engineBackend": runtime.get("engine_backend"),
                "monteCarloBackend": runtime.get("monte_carlo_backend"),
                "workerCount": runtime.get("worker_count"),
                "gitCommit": git.get("commit"),
                "gitDirty": git.get("dirty"),
                "command": _mapping(provenance.get("command")).get("display"),
                "note": note,
                "contributions": contributions,
            }
        )

        products = payload.get("products")
        if isinstance(products, list):
            for product in products:
                if isinstance(product, str) and product not in seen_products:
                    seen_products.append(product)

        reports = payload.get("datasetReports")
        if isinstance(reports, list) and not dataset_reports:
            dataset_reports = list(reports)

        assumptions = _mapping(payload.get("assumptions"))
        _collect_string_notes(exact_assumptions, seen_assumptions, assumptions.get("exact"))
        _collect_string_notes(approximate_assumptions, seen_assumptions, assumptions.get("approximate"))
        _collect_data_contract_entries(data_contract_entries, seen_data_contract_entries, payload.get("dataContract"))

        if first_populated_meta is None and meta:
            first_populated_meta = meta

    if seen_products:
        workspace_payload["products"] = seen_products

    if dataset_reports:
        workspace_payload["datasetReports"] = dataset_reports

    if exact_assumptions or approximate_assumptions:
        workspace_payload["assumptions"] = {
            "exact": exact_assumptions,
            "approximate": approximate_assumptions,
        }

    if data_contract_entries:
        workspace_payload["dataContract"] = data_contract_entries

    if first_populated_meta is not None:
        meta_block = workspace_payload["meta"]
        assert isinstance(meta_block, dict)
        inherited_round = first_populated_meta.get("round")
        if inherited_round is not None and "round" not in meta_block:
            meta_block["round"] = inherited_round

    present_sections = _derive_workspace_sections(present_core_sections, include_overview=True)
    missing_sections = [section for section in ALL_DASHBOARD_SECTIONS if section not in present_sections]

    integrity_status = "clean"
    if shadowed_by:
        integrity_status = "overlap"
    elif missing_sections:
        integrity_status = "partial"

    integrity_warnings = [
        "Section "
        + section
        + " promoted from "
        + promoted_by.get(section, "an earlier source")
        + "; kept "
        + ", ".join(paths)
        + " as provenance-only sources."
        for section, paths in sorted(shadowed_core_by.items(), key=lambda item: _section_order(item[0]))
    ]

    provenance = capture_provenance()
    meta_block = workspace_payload["meta"]
    assert isinstance(meta_block, dict)
    meta_block["provenance"] = provenance
    workspace_payload["workspace"] = {
        "name": name,
        "createdAt": created_iso,
        "notes": notes,
        "sources": assembly.source_records,
        "sections": {
            "present": present_sections,
            "missing": missing_sections,
        },
        "integrity": {
            "status": integrity_status,
            "promotedBy": promoted_by,
            "shadowedBy": shadowed_by or None,
            "warnings": integrity_warnings,
        },
        "command": _mapping(provenance.get("command")).get("display"),
        "gitCommit": _mapping(provenance.get("git")).get("commit"),
        "gitDirty": _mapping(provenance.get("git")).get("dirty"),
        "gitBranch": _mapping(provenance.get("git")).get("branch"),
    }

    assembly.present_sections = present_sections
    assembly.missing_sections = missing_sections
    return assembly


def resolve_sources(
    paths: Iterable[Path] | None,
    *,
    from_dir: Path | None,
) -> list[WorkspaceSource]:
    """Collect child dashboard.json files from explicit paths and/or a directory."""
    resolved: list[WorkspaceSource] = []
    seen_paths: set[Path] = set()
    root: Path | None = from_dir.resolve() if from_dir is not None else None

    def _register(path: Path) -> None:
        resolved_path = path.resolve()
        if resolved_path in seen_paths or not resolved_path.is_file():
            return
        seen_paths.add(resolved_path)
        try:
            payload = _load_child(resolved_path)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"could not read {resolved_path}: {exc}") from exc
        if root is not None:
            try:
                rel = resolved_path.relative_to(root)
                rel_text = str(rel).replace("\\", "/")
            except ValueError:
                rel_text = str(resolved_path)
        else:
            rel_text = str(resolved_path)
        resolved.append(WorkspaceSource(path=resolved_path, payload=payload, relative_path=rel_text))

    if paths:
        for path in paths:
            target = Path(path)
            if target.is_dir():
                target = target / "dashboard.json"
            _register(target)

    if from_dir is not None:
        from_dir = from_dir.resolve()
        if not from_dir.is_dir():
            raise RuntimeError(f"workspace source directory does not exist: {from_dir}")
        for candidate in sorted(from_dir.rglob("dashboard.json")):
            _register(candidate)

    return resolved


def write_workspace_bundle(
    sources: Sequence[WorkspaceSource],
    output_dir: Path,
    *,
    name: str,
    notes: str | None = None,
) -> tuple[Path, WorkspaceAssembly]:
    """Assemble and write a workspace dashboard bundle to ``output_dir``."""
    if not sources:
        raise RuntimeError("no dashboard.json files were found for the workspace")

    output_dir.mkdir(parents=True, exist_ok=True)
    assembly = assemble_workspace_payload(sources, name=name, notes=notes)
    dashboard_path = output_dir / "dashboard.json"
    with dashboard_path.open("w", encoding="utf-8") as handle:
        json.dump(assembly.payload, handle)
    _write_workspace_manifest(output_dir, name=name, assembly=assembly)
    return dashboard_path, assembly


def _write_workspace_manifest(output_dir: Path, *, name: str, assembly: WorkspaceAssembly) -> None:
    dashboard_path = output_dir / "dashboard.json"
    dashboard_size = dashboard_path.stat().st_size if dashboard_path.is_file() else 0
    manifest = {
        "run_name": name,
        "schema_version": 3,
        "created_at": _mapping(assembly.payload.get("meta")).get("createdAt"),
        "run_type": "workspace",
        "mode": "workspace",
        "output_profile": {"profile": "workspace"},
        "workspace": assembly.payload.get("workspace", {}),
        "bundle_stats": {
            "file_count": 2,
            "total_size_bytes": dashboard_size,
            "debug_file_count": 0,
            "sidecar_file_count": 0,
        },
        "canonical_files": ["dashboard.json", "manifest.json"],
        "provenance": _mapping(assembly.payload.get("meta")).get("provenance"),
    }
    manifest_path = output_dir / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle)


__all__ = [
    "ALL_DASHBOARD_SECTIONS",
    "WorkspaceAssembly",
    "WorkspaceSource",
    "assemble_workspace_payload",
    "resolve_sources",
    "write_workspace_bundle",
]
