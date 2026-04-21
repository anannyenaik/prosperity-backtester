from __future__ import annotations

import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Sequence


def _git_root(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _git_text(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = completed.stdout.strip()
    return text or None


@lru_cache(maxsize=32)
def _git_snapshot(root_text: str) -> tuple[str | None, bool | None, str | None]:
    root = Path(root_text)
    return (
        _git_text(root, "rev-parse", "HEAD"),
        bool(_git_text(root, "status", "--porcelain", "--untracked-files=no")),
        _git_text(root, "rev-parse", "--abbrev-ref", "HEAD"),
    )


def infer_workflow_tier(argv: Sequence[str] | None = None) -> str | None:
    tokens = [str(token) for token in (sys.argv if argv is None else argv)]
    if not tokens:
        return None
    lowered = [token.lower() for token in tokens]
    stemmed = {Path(token).name.lower() for token in tokens}

    if "research_pack.py" in stemmed:
        for tier in ("fast", "validation", "forensic"):
            if tier in lowered:
                return tier
        return "pack"
    if "profile_replay.py" in stemmed:
        return "profiling"
    if "benchmark_runtime.py" in stemmed or "benchmark_outputs.py" in stemmed:
        return "benchmark"
    if any(token in {"replay", "monte-carlo", "compare", "sweep", "optimize", "calibrate", "round2-scenarios", "scenario-compare"} for token in lowered):
        return "manual"
    return None


def capture_provenance(
    *,
    runtime_context: Mapping[str, object] | None = None,
    argv: Sequence[str] | None = None,
    start: Path | None = None,
) -> dict[str, object]:
    argv = [str(token) for token in (sys.argv if argv is None else argv)]
    root = _git_root(start)
    commit, dirty, branch = (None, None, None) if root is None else _git_snapshot(str(root))
    git = {
        "root": None if root is None else str(root),
        "commit": commit,
        "dirty": dirty,
        "branch": branch,
    }
    runtime = {
        "python_version": sys.version,
        "executable": sys.executable,
    }
    if runtime_context:
        runtime.update(runtime_context)
    return {
        "workflow_tier": infer_workflow_tier(argv),
        "command": {
            "argv": argv,
            "display": None if not argv else subprocess.list2cmdline(argv),
            "cwd": str(Path.cwd().resolve()),
        },
        "git": git,
        "runtime": runtime,
    }
