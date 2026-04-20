from __future__ import annotations

import re
import shutil
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


_AUTO_RUN_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_.+")


@dataclass(frozen=True)
class OutputOptions:
    profile: str = "light"
    max_series_rows_per_product: int = 1_000
    include_orders: bool = False
    write_sample_path_files: bool = False
    write_session_manifests: bool = False
    write_child_bundles: bool = False
    json_indent: int | None = None

    @classmethod
    def from_profile(
        cls,
        profile: str | None,
        *,
        write_child_bundles: bool | None = None,
    ) -> "OutputOptions":
        name = (profile or "light").strip().lower()
        if name not in {"light", "full"}:
            raise ValueError("output profile must be 'light' or 'full'")
        if name == "full":
            return cls(
                profile="full",
                max_series_rows_per_product=0,
                include_orders=True,
                write_sample_path_files=True,
                write_session_manifests=True,
                write_child_bundles=True if write_child_bundles is None else bool(write_child_bundles),
                json_indent=2,
            )
        return cls(write_child_bundles=False if write_child_bundles is None else bool(write_child_bundles))

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "OutputOptions":
        options = cls.from_profile(str(config.get("output_profile", "light")))
        if "max_series_rows_per_product" in config:
            options = _replace(options, max_series_rows_per_product=max(0, int(config["max_series_rows_per_product"])))
        if "include_orders" in config:
            options = _replace(options, include_orders=bool(config["include_orders"]))
        if "write_sample_path_files" in config:
            options = _replace(options, write_sample_path_files=bool(config["write_sample_path_files"]))
        if "write_session_manifests" in config:
            options = _replace(options, write_session_manifests=bool(config["write_session_manifests"]))
        if "save_child_bundles" in config:
            options = _replace(options, write_child_bundles=bool(config["save_child_bundles"]))
        if "compact_json" in config:
            options = _replace(options, json_indent=None if bool(config["compact_json"]) else 2)
        return options

    def to_manifest(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "max_series_rows_per_product": self.max_series_rows_per_product,
            "include_orders": self.include_orders,
            "write_sample_path_files": self.write_sample_path_files,
            "write_session_manifests": self.write_session_manifests,
            "write_child_bundles": self.write_child_bundles,
            "compact_json": self.json_indent is None,
        }


def _replace(options: OutputOptions, **changes: object) -> OutputOptions:
    values = options.__dict__ | changes
    return OutputOptions(**values)


def prune_old_auto_runs(root: Path, keep: int) -> list[Path]:
    if keep < 1 or not root.exists():
        return []
    root = root.resolve()
    candidates = [
        path
        for path in root.iterdir()
        if path.is_dir() and _AUTO_RUN_DIR.match(path.name)
    ]
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    removed: list[Path] = []
    for path in candidates[keep:]:
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        shutil.rmtree(resolved)
        removed.append(resolved)
    _compact_registry(root)
    return removed


def _compact_registry(root: Path) -> None:
    registry = root / "run_registry.jsonl"
    if not registry.is_file():
        return
    kept: list[str] = []
    for line in registry.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            kept.append(line)
            continue
        output_dir = row.get("output_dir")
        dashboard_json = row.get("dashboard_json")
        if (output_dir and Path(str(output_dir)).exists()) or (dashboard_json and Path(str(dashboard_json)).exists()):
            kept.append(json.dumps(row, sort_keys=True))
    registry.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
