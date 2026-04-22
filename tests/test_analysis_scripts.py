from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "script_path",
    [
        "analysis/benchmark_outputs.py",
        "analysis/benchmark_backends.py",
        "analysis/benchmark_chris_reference.py",
        "analysis/architecture_bakeoff.py",
        "analysis/research_pack.py",
        "analysis/profile_replay.py",
        "analysis/validate.py",
        "analysis/calibrate.py",
    ],
)
def test_analysis_scripts_bootstrap_repo_root_for_help(script_path: str):
    env = os.environ.copy()
    env["PYTHONPATH"] = ""
    result = subprocess.run(
        [sys.executable, "-S", script_path, "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()


def test_reference_benchmark_shared_trader_is_valid_python(tmp_path: Path):
    from analysis.benchmark_chris_reference import _write_shared_trader

    path = _write_shared_trader(tmp_path / "shared_noop_trader.py")
    source = path.read_text(encoding="utf-8")

    compile(source, str(path), "exec")
    namespace: dict[str, object] = {}
    exec(source, namespace)

    trader = namespace["Trader"]()
    state = type("State", (), {"traderData": "carry"})()

    assert trader.run(state) == ({}, 0, "carry")
