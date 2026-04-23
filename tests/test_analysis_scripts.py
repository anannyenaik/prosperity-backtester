from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "script_path",
    [
        "analysis/benchmark_outputs.py",
        "analysis/benchmark_attribution.py",
        "analysis/benchmark_backends.py",
        "analysis/benchmark_chris_reference.py",
        "analysis/architecture_bakeoff.py",
        "analysis/rss_frontier.py",
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


class _FakeProcess:
    def __init__(self, pid: int, cmdline: list[str], rss_bytes: int, children: list["_FakeProcess"] | None = None):
        self.pid = pid
        self._cmdline = list(cmdline)
        self._rss_bytes = int(rss_bytes)
        self._children = list(children or [])

    def cmdline(self) -> list[str]:
        return list(self._cmdline)

    def memory_info(self) -> SimpleNamespace:
        return SimpleNamespace(rss=self._rss_bytes)

    def children(self, recursive: bool = False) -> list["_FakeProcess"]:
        if not recursive:
            return list(self._children)
        descendants: list[_FakeProcess] = []
        for child in self._children:
            descendants.append(child)
            descendants.extend(child.children(recursive=True))
        return descendants


def test_benchmark_runtime_selects_effective_root_process_when_venv_launcher_wraps_python():
    from analysis.benchmark_runtime import _select_effective_root_process

    worker = _FakeProcess(
        pid=30384,
        cmdline=["python.exe", "-c", "from multiprocessing.spawn import spawn_main(...)", "--multiprocessing-fork"],
        rss_bytes=36_000_000,
    )
    main = _FakeProcess(
        pid=16708,
        cmdline=["python.exe", "-m", "prosperity_backtester", "monte-carlo", "examples/benchmark_trader.py"],
        rss_bytes=144_000_000,
        children=[worker],
    )
    launcher = _FakeProcess(
        pid=9000,
        cmdline=[r"D:\Programming\prosperity-backtester\.venv\Scripts\python.exe"],
        rss_bytes=11_000_000,
        children=[main],
    )

    selected = _select_effective_root_process(
        launcher,
        [
            r"D:\Programming\prosperity-backtester\.venv\Scripts\python.exe",
            "-m",
            "prosperity_backtester",
            "monte-carlo",
            "examples/benchmark_trader.py",
        ],
    )

    assert selected is main
