from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


_AUTO_RUN_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_.+")


@dataclass(frozen=True)
class OutputOptions:
    profile: str = "light"
    max_series_rows_per_product: int = 1_000
    include_orders: bool = False
    write_series_csvs: bool = False
    write_sample_path_files: bool = False
    write_session_manifests: bool = False
    write_child_bundles: bool = False
    max_mc_path_rows_per_product: int = 800
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
                write_series_csvs=True,
                write_sample_path_files=True,
                write_session_manifests=True,
                write_child_bundles=False if write_child_bundles is None else bool(write_child_bundles),
                max_mc_path_rows_per_product=0,
                json_indent=None,
            )
        return cls(write_child_bundles=False if write_child_bundles is None else bool(write_child_bundles))

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "OutputOptions":
        options = cls.from_profile(str(config.get("output_profile", "light")))
        if "max_series_rows_per_product" in config:
            options = _replace(options, max_series_rows_per_product=max(0, int(config["max_series_rows_per_product"])))
        if "include_orders" in config:
            options = _replace(options, include_orders=bool(config["include_orders"]))
        if "write_series_csvs" in config:
            options = _replace(options, write_series_csvs=bool(config["write_series_csvs"]))
        if "series_sidecars" in config:
            options = _replace(options, write_series_csvs=bool(config["series_sidecars"]))
        if "write_sample_path_files" in config:
            options = _replace(options, write_sample_path_files=bool(config["write_sample_path_files"]))
        if "write_session_manifests" in config:
            options = _replace(options, write_session_manifests=bool(config["write_session_manifests"]))
        if "save_child_bundles" in config:
            options = _replace(options, write_child_bundles=bool(config["save_child_bundles"]))
        if "write_child_bundles" in config:
            options = _replace(options, write_child_bundles=bool(config["write_child_bundles"]))
        if "max_mc_path_rows_per_product" in config:
            options = _replace(options, max_mc_path_rows_per_product=max(0, int(config["max_mc_path_rows_per_product"])))
        if "pretty_json" in config:
            options = _replace(options, json_indent=2 if bool(config["pretty_json"]) else None)
        if "compact_json" in config:
            options = _replace(options, json_indent=None if bool(config["compact_json"]) else 2)
        return options

    def to_manifest(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "max_series_rows_per_product": self.max_series_rows_per_product,
            "include_orders": self.include_orders,
            "write_series_csvs": self.write_series_csvs,
            "write_sample_path_files": self.write_sample_path_files,
            "write_session_manifests": self.write_session_manifests,
            "write_child_bundles": self.write_child_bundles,
            "max_mc_path_rows_per_product": self.max_mc_path_rows_per_product,
            "compact_json": self.json_indent is None,
            "pretty_json": self.json_indent is not None,
        }


def _replace(options: OutputOptions, **changes: object) -> OutputOptions:
    values = options.__dict__ | changes
    return OutputOptions(**values)


def validate_keep_count(value: int) -> int:
    keep = int(value)
    if keep < 1:
        raise ValueError("keep count must be at least 1")
    return keep


def _parse_auto_run_timestamp(path: Path) -> datetime | None:
    stamp = path.name[:19]
    try:
        return datetime.strptime(stamp, "%Y-%m-%d_%H-%M-%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_iso_datetime(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _manifest_created_at(path: Path) -> datetime | None:
    manifest = path / "manifest.json"
    if not manifest.is_file():
        return None
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    return _parse_iso_datetime(payload.get("created_at") or payload.get("createdAt"))


def _auto_run_created_at(path: Path) -> datetime:
    return _parse_auto_run_timestamp(path) or _manifest_created_at(path) or datetime.min.replace(tzinfo=timezone.utc)


def prune_old_auto_runs(root: Path, keep: int) -> list[Path]:
    keep = validate_keep_count(keep)
    if not root.exists():
        return []
    root = root.resolve()
    candidates = [
        path
        for path in root.iterdir()
        if path.is_dir() and _AUTO_RUN_DIR.match(path.name)
    ]
    candidates.sort(key=_auto_run_created_at, reverse=True)
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
