"""Compatibility wrapper for the former package name.

Use :mod:`prosperity_backtester` for new code.
"""
from __future__ import annotations

import importlib
import sys

import prosperity_backtester as _impl
from prosperity_backtester import *  # noqa: F401,F403

__all__ = _impl.__all__

_SUBMODULES = (
    "behavior",
    "dashboard",
    "datamodel",
    "dataset",
    "engine",
    "experiments",
    "fair_value",
    "fill_models",
    "live_export",
    "metadata",
    "noise",
    "platform",
    "replay",
    "reports",
    "round2",
    "scenarios",
    "server",
    "simulate",
    "trader_adapter",
)

for _name in _SUBMODULES:
    sys.modules[f"{__name__}.{_name}"] = importlib.import_module(f"prosperity_backtester.{_name}")
