from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
import types
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

from . import datamodel as internal_datamodel


def install_datamodel_aliases() -> None:
    """Expose the bundled datamodel under common Prosperity import paths.

    This is the key compatibility shim for uploaded traders that still import
    `from datamodel import ...` or older backtester package names.
    """
    aliases = {
        "datamodel": internal_datamodel,
        "prosperity_backtester.datamodel": internal_datamodel,
        "r1bt.datamodel": internal_datamodel,
        "prosperity3bt.datamodel": internal_datamodel,
        "prosperity4mcbt.datamodel": internal_datamodel,
    }
    for name, module in aliases.items():
        sys.modules[name] = module

    for package_name in ("prosperity3bt", "prosperity4mcbt"):
        if package_name not in sys.modules:
            package = types.ModuleType(package_name)
            package.datamodel = internal_datamodel
            sys.modules[package_name] = package


class TraderLoadError(RuntimeError):
    pass


def _set_nested_attr_or_key(obj: Any, path: list[str], value: Any) -> None:
    target = obj
    for part in path[:-1]:
        if isinstance(target, dict):
            if part not in target:
                target[part] = {}
            target = target[part]
        else:
            if not hasattr(target, part):
                setattr(target, part, {})
            target = getattr(target, part)
    leaf = path[-1]
    if isinstance(target, dict):
        target[leaf] = value
    else:
        setattr(target, leaf, value)


def apply_module_overrides(module: types.ModuleType, overrides: Optional[Dict[str, Any]]) -> None:
    if not overrides:
        return
    for dotted_path, value in overrides.items():
        parts = dotted_path.split(".")
        if not hasattr(module, parts[0]):
            raise TraderLoadError(f"Override path {dotted_path!r} does not exist on module {module.__name__}")
        root_name = parts[0]
        root = deepcopy(getattr(module, root_name))
        _set_nested_attr_or_key(root, parts[1:], value)
        setattr(module, root_name, root)


def load_trader_module(path: Path, module_overrides: Optional[Dict[str, Any]] = None):
    install_datamodel_aliases()
    path = path.resolve()
    if not path.is_file():
        raise TraderLoadError(f"Trader file not found: {path}")
    parent = str(path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:10]
    module_name = f"_team_trader_{path.stem}_{digest}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise TraderLoadError(f"Could not create import spec for trader: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise TraderLoadError(f"Trader import failed for {path}: {exc}") from exc
    if not hasattr(module, "Trader"):
        raise TraderLoadError(f"Trader file does not define class Trader: {path}")
    apply_module_overrides(module, module_overrides)
    return module


def make_trader(path: Path, module_overrides: Optional[Dict[str, Any]] = None):
    module = load_trader_module(path, module_overrides=module_overrides)
    try:
        trader = module.Trader()
    except Exception as exc:  # pragma: no cover - exercised indirectly by smoke tests
        raise TraderLoadError(f"Trader() construction failed for {path}: {exc}") from exc
    if not callable(getattr(trader, "run", None)):
        raise TraderLoadError(f"Trader instance does not define callable run(state): {path}")
    return trader, module


def describe_overrides(overrides: Optional[Dict[str, Any]]) -> str:
    if not overrides:
        return "{}"
    return json.dumps(overrides, sort_keys=True)
