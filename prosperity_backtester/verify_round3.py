"""Round 3 verification harness.

Bundles the checks that prove the Round 3 backtester is trustworthy before
trader-script work starts. The harness captures provenance, data validation,
replay correctness fixtures, option-diagnostics proof, MC coherence, scenario
sweeps and per-command performance/RSS metrics.

The design keeps the heaviest commands as subprocesses so that a parent psutil
poller can observe peak resident-set size across the whole process tree. Fast
fixture checks run in-process to keep the overall harness runtime reasonable.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform as platform_module
import statistics
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    import psutil  # type: ignore
    _HAVE_PSUTIL = True
except Exception:  # pragma: no cover - psutil is optional
    psutil = None  # type: ignore
    _HAVE_PSUTIL = False


from .dataset import load_round_dataset
from .experiments import TraderSpec, run_compare, run_replay
from .metadata import get_round_spec, products_for_round
from .platform import PerturbationConfig, generate_synthetic_market_days
from .provenance import capture_provenance
from .round3 import (
    ROUND3_HYDROGEL,
    ROUND3_SURFACE_FIT_VOUCHERS,
    ROUND3_UNDERLYING,
    ROUND3_VOUCHERS,
    compute_option_diagnostics,
    prepare_round3_synthetic_context,
    parse_voucher_symbol,
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CommandResult:
    name: str
    command: List[str]
    returncode: int
    wall_seconds: float
    peak_rss_mb_process: Optional[float]
    peak_rss_mb_tree: Optional[float]
    peak_child_process_count: Optional[int]
    rss_capture_method: str
    rss_caveats: List[str]
    output_dir: Optional[str] = None
    output_size_bytes: Optional[int] = None
    output_file_count: Optional[int] = None
    stdout_tail: Optional[str] = None
    stderr_tail: Optional[str] = None
    status: str = "ok"
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "command": list(self.command),
            "returncode": int(self.returncode),
            "wall_seconds": round(self.wall_seconds, 4),
            "peak_rss_mb_process": self.peak_rss_mb_process,
            "peak_rss_mb_tree": self.peak_rss_mb_tree,
            "peak_child_process_count": self.peak_child_process_count,
            "rss_capture_method": self.rss_capture_method,
            "rss_caveats": list(self.rss_caveats),
            "output_dir": self.output_dir,
            "output_size_bytes": self.output_size_bytes,
            "output_file_count": self.output_file_count,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "status": self.status,
            "error": self.error,
        }


@dataclass
class CheckResult:
    name: str
    status: str  # "pass" | "fail" | "skip"
    detail: Dict[str, object] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": dict(self.detail),
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Subprocess runner with RSS sampling
# ---------------------------------------------------------------------------


def _poll_interval_seconds() -> float:
    # 80ms keeps overhead low while still catching short-lived peaks in
    # ~1s inspect commands. Long-running MC runs tolerate a coarser sample
    # but 80ms remains cheap at ~12 polls/second.
    return 0.08


def _sample_process_rss(process: "psutil.Process") -> Tuple[Optional[float], Optional[float], Optional[int]]:
    """Return (parent_rss_mb, tree_rss_mb, child_count).

    Missing values signal transient race conditions with rapidly exiting
    children and are simply skipped in the peak calculation.
    """
    if psutil is None:  # pragma: no cover - guarded by caller
        return None, None, None
    try:
        parent_rss = float(process.memory_info().rss) / (1024.0 * 1024.0)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None, None, None
    tree_rss = parent_rss
    child_count = 0
    try:
        for child in process.children(recursive=True):
            try:
                tree_rss += float(child.memory_info().rss) / (1024.0 * 1024.0)
                child_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return parent_rss, tree_rss, child_count


def run_with_rss(
    name: str,
    command: Sequence[str],
    *,
    cwd: Path,
    output_dir: Optional[Path] = None,
    output_paths: Optional[Sequence[Path]] = None,
    env: Optional[Mapping[str, str]] = None,
    capture_stdout_path: Optional[Path] = None,
    timeout_seconds: Optional[float] = 1800.0,
) -> CommandResult:
    """Run a subprocess while polling psutil for peak RSS.

    stdout/stderr are written to temporary files (or `capture_stdout_path` for
    stdout) so the OS pipe buffer cannot deadlock against us when the child
    produces megabytes of output. We sample RSS at ~12Hz while the process is
    alive. When ``capture_stdout_path`` is set the full stdout stream is kept
    on disk; otherwise we just retain a tail in the report. ``output_dir`` and
    ``output_paths`` are only for size accounting.
    """

    argv = [str(arg) for arg in command]
    start = time.perf_counter()
    rss_caveats: List[str] = []
    peak_parent: Optional[float] = None
    peak_tree: Optional[float] = None
    peak_children: Optional[int] = None
    method = "psutil_poll" if _HAVE_PSUTIL else "none"
    if not _HAVE_PSUTIL:
        rss_caveats.append(
            "psutil is not installed; process-tree RSS is unavailable. "
            "Install psutil to enable peak-RSS capture."
        )

    merged_env = dict(os.environ)
    if env:
        merged_env.update({str(k): str(v) for k, v in env.items()})

    stdout_handle = (
        open(capture_stdout_path, "w", encoding="utf-8")
        if capture_stdout_path is not None
        else tempfile.NamedTemporaryFile(mode="w+", delete=False, encoding="utf-8")
    )
    stderr_temp = tempfile.NamedTemporaryFile(mode="w+", delete=False, encoding="utf-8")

    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=merged_env,
            stdout=stdout_handle,
            stderr=stderr_temp,
            text=True,
        )
    except OSError as exc:
        try:
            stdout_handle.close()
        finally:
            stderr_temp.close()
        return CommandResult(
            name=name,
            command=argv,
            returncode=-1,
            wall_seconds=time.perf_counter() - start,
            peak_rss_mb_process=None,
            peak_rss_mb_tree=None,
            peak_child_process_count=None,
            rss_capture_method="none",
            rss_caveats=[f"subprocess launch failed: {exc}"],
            output_dir=str(output_dir) if output_dir is not None else None,
            status="fail",
            error=str(exc),
        )

    timeout_hit = False
    if _HAVE_PSUTIL:
        try:
            watcher = psutil.Process(proc.pid)
            poll_started = time.perf_counter()
            while proc.poll() is None:
                parent_rss, tree_rss, child_count = _sample_process_rss(watcher)
                if parent_rss is not None:
                    peak_parent = parent_rss if peak_parent is None else max(peak_parent, parent_rss)
                if tree_rss is not None:
                    peak_tree = tree_rss if peak_tree is None else max(peak_tree, tree_rss)
                if child_count is not None:
                    peak_children = child_count if peak_children is None else max(peak_children, child_count)
                if timeout_seconds is not None and (time.perf_counter() - poll_started) > timeout_seconds:
                    timeout_hit = True
                    break
                time.sleep(_poll_interval_seconds())
            parent_rss, tree_rss, child_count = _sample_process_rss(watcher)
            if parent_rss is not None:
                peak_parent = parent_rss if peak_parent is None else max(peak_parent, parent_rss)
            if tree_rss is not None:
                peak_tree = tree_rss if peak_tree is None else max(peak_tree, tree_rss)
            if child_count is not None:
                peak_children = child_count if peak_children is None else max(peak_children, child_count)
        except psutil.NoSuchProcess:
            rss_caveats.append("subprocess exited before psutil could start sampling RSS")
    else:
        try:
            proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timeout_hit = True

    if timeout_hit:
        rss_caveats.append(f"subprocess exceeded {timeout_seconds}s and was terminated")
        try:
            proc.kill()
        except OSError:
            pass

    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass
        proc.wait()

    elapsed = time.perf_counter() - start

    # Drain stdio from temp files
    stdout_text = ""
    stderr_text = ""
    try:
        stdout_handle.close()
    finally:
        if capture_stdout_path is not None:
            try:
                stdout_text = capture_stdout_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                stdout_text = ""
        else:
            tmp_path = Path(stdout_handle.name)
            try:
                stdout_text = tmp_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                stdout_text = ""
            finally:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
    try:
        stderr_temp.close()
    finally:
        tmp_path = Path(stderr_temp.name)
        try:
            stderr_text = tmp_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            stderr_text = ""
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    accounted_paths = list(output_paths or [])
    if output_dir is not None:
        accounted_paths.append(output_dir)
    output_size, output_count = _paths_size(accounted_paths) if accounted_paths else (None, None)

    return_code = int(proc.returncode if proc.returncode is not None else -1)
    status = "ok" if return_code == 0 and not timeout_hit else "fail"
    error: Optional[str] = None
    if status == "fail":
        if timeout_hit:
            error = f"timed out after {timeout_seconds}s"
        else:
            tail = stderr_text.strip().splitlines()[-1] if stderr_text.strip() else f"exit {return_code}"
            error = tail

    return CommandResult(
        name=name,
        command=argv,
        returncode=return_code,
        wall_seconds=elapsed,
        peak_rss_mb_process=None if peak_parent is None else round(peak_parent, 2),
        peak_rss_mb_tree=None if peak_tree is None else round(peak_tree, 2),
        peak_child_process_count=peak_children,
        rss_capture_method=method,
        rss_caveats=rss_caveats,
        output_dir=str(output_dir) if output_dir is not None else None,
        output_size_bytes=output_size,
        output_file_count=output_count,
        stdout_tail=_tail_text(stdout_text, 20),
        stderr_tail=_tail_text(stderr_text, 20),
        status=status,
        error=error,
    )


def _tail_text(text: Optional[str], line_count: int) -> Optional[str]:
    if not text:
        return None
    lines = text.splitlines()
    if len(lines) <= line_count:
        return "\n".join(lines)
    return "\n".join(lines[-line_count:])


def _dir_size(path: Path) -> Tuple[int, int]:
    total = 0
    count = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            try:
                total += entry.stat().st_size
                count += 1
            except OSError:
                continue
    return total, count


def _paths_size(paths: Sequence[Path]) -> Tuple[int, int]:
    total = 0
    count = 0
    seen: set[Path] = set()
    for path in paths:
        if path.is_file():
            try:
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                total += path.stat().st_size
                count += 1
            except OSError:
                continue
            continue
        if not path.is_dir():
            continue
        for entry in path.rglob("*"):
            if not entry.is_file():
                continue
            try:
                resolved = entry.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                total += entry.stat().st_size
                count += 1
            except OSError:
                continue
    return total, count


# ---------------------------------------------------------------------------
# File hashing / data manifest
# ---------------------------------------------------------------------------


def _hash_file(path: Path, *, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _data_file_manifest(data_dir: Path, days: Sequence[int]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for day in days:
        for kind in ("prices", "trades"):
            name = f"{kind}_round_3_day_{day}.csv"
            path = data_dir / name
            if not path.is_file():
                rows.append({"file": name, "exists": False})
                continue
            stat = path.stat()
            rows.append({
                "file": name,
                "exists": True,
                "size_bytes": int(stat.st_size),
                "sha256": _hash_file(path),
            })
    return rows


# ---------------------------------------------------------------------------
# Data validation
# ---------------------------------------------------------------------------


_EXPECTED_TRADE_ROWS = {0: 1308, 1: 1407, 2: 1333}
_EXPECTED_TIMESTAMPS = 10_000
_EXPECTED_TIMESTAMP_MIN = 0
_EXPECTED_TIMESTAMP_MAX = 999_900
_EXPECTED_TIMESTAMP_STEP = 100


def validate_data(data_dir: Path, days: Sequence[int]) -> CheckResult:
    try:
        dataset = load_round_dataset(data_dir, days, round_number=3)
    except Exception as exc:  # pragma: no cover - surfaced in report
        return CheckResult(
            name="data_validation",
            status="fail",
            detail={},
            error=f"load_round_dataset failed: {exc}",
        )
    expected_products = list(products_for_round(3))
    days_out: List[Dict[str, object]] = []
    failures: List[str] = []
    for day, day_dataset in dataset.items():
        validation = dict(day_dataset.validation)
        row = {
            "day": int(day),
            "price_rows": int(validation.get("price_rows", 0)),
            "expected_price_rows": int(validation.get("expected_price_rows", 0)),
            "trade_rows": int(validation.get("trade_rows", 0)),
            "expected_trade_rows": int(_EXPECTED_TRADE_ROWS.get(int(day), 0)),
            "timestamps": int(validation.get("timestamps", 0)),
            "expected_timestamps": int(_EXPECTED_TIMESTAMPS),
            "timestamp_min": validation.get("timestamp_min"),
            "timestamp_max": validation.get("timestamp_max"),
            "timestamp_step_ok": bool(validation.get("timestamp_step_ok")),
            "products_seen": validation.get("products_seen"),
            "exact_product_match": bool(validation.get("exact_product_match")),
            "duplicate_book_rows": int(validation.get("duplicate_book_rows", 0)),
            "empty_book_rows": int(validation.get("empty_book_rows", 0)),
            "one_sided_book_rows": int(validation.get("one_sided_book_rows", 0)),
            "crossed_book_rows": int(validation.get("crossed_book_rows", 0)),
            "trade_rows_unknown_symbol": int(validation.get("trade_rows_unknown_symbol", 0)),
            "trade_rows_unknown_timestamp": int(validation.get("trade_rows_unknown_timestamp", 0)),
            "trade_rows_invalid_currency": int(validation.get("trade_rows_invalid_currency", 0)),
            "trade_rows_invalid_quantity": int(validation.get("trade_rows_invalid_quantity", 0)),
            "price_level_parse_errors": int(validation.get("price_level_parse_errors", 0)),
            "volume_parse_errors": int(validation.get("volume_parse_errors", 0)),
        }
        missing_products = validation.get("missing_products") or {}
        row["missing_products_count"] = len(missing_products) if isinstance(missing_products, dict) else 0
        if row["price_rows"] != row["expected_price_rows"]:
            failures.append(f"day {day}: price_rows {row['price_rows']} != expected {row['expected_price_rows']}")
        if row["expected_trade_rows"] and row["trade_rows"] != row["expected_trade_rows"]:
            failures.append(f"day {day}: trade_rows {row['trade_rows']} != expected {row['expected_trade_rows']}")
        if row["timestamps"] != row["expected_timestamps"]:
            failures.append(f"day {day}: timestamps {row['timestamps']} != expected {row['expected_timestamps']}")
        if row["timestamp_min"] != _EXPECTED_TIMESTAMP_MIN:
            failures.append(f"day {day}: timestamp_min {row['timestamp_min']} != {_EXPECTED_TIMESTAMP_MIN}")
        if row["timestamp_max"] != _EXPECTED_TIMESTAMP_MAX:
            failures.append(f"day {day}: timestamp_max {row['timestamp_max']} != {_EXPECTED_TIMESTAMP_MAX}")
        if not row["timestamp_step_ok"]:
            failures.append(f"day {day}: timestamp_step not consistent")
        if row["products_seen"] != expected_products:
            failures.append(f"day {day}: products_seen mismatch")
        if not row["exact_product_match"]:
            failures.append(f"day {day}: exact_product_match is False")
        if row["duplicate_book_rows"]:
            failures.append(f"day {day}: duplicate_book_rows={row['duplicate_book_rows']}")
        if row["trade_rows_unknown_symbol"]:
            failures.append(f"day {day}: unknown-symbol trade rows={row['trade_rows_unknown_symbol']}")
        if row["trade_rows_invalid_currency"]:
            failures.append(f"day {day}: invalid-currency trade rows={row['trade_rows_invalid_currency']}")
        if row["trade_rows_invalid_quantity"]:
            failures.append(f"day {day}: invalid-quantity trade rows={row['trade_rows_invalid_quantity']}")
        days_out.append(row)

    detail = {
        "data_dir": str(data_dir),
        "products_expected": expected_products,
        "days": days_out,
        "timestamp_step_expected": _EXPECTED_TIMESTAMP_STEP,
        "file_manifest": _data_file_manifest(data_dir, days),
    }
    status = "pass" if not failures else "fail"
    return CheckResult(
        name="data_validation",
        status=status,
        detail=detail,
        error=None if status == "pass" else "; ".join(failures),
    )


# ---------------------------------------------------------------------------
# Replay correctness fixtures
# ---------------------------------------------------------------------------


_ROUND3_TINY_HEADER = (
    "day;timestamp;product;"
    "bid_price_1;bid_volume_1;bid_price_2;bid_volume_2;bid_price_3;bid_volume_3;"
    "ask_price_1;ask_volume_1;ask_price_2;ask_volume_2;ask_price_3;ask_volume_3;"
    "mid_price;profit_and_loss\n"
)


_ROUND3_TINY_PRODUCT_ROWS = {
    "HYDROGEL_PACK": "0;0;HYDROGEL_PACK;99;10;;;;;100;10;;;;;99.5;0\n",
    "VELVETFRUIT_EXTRACT": "0;0;VELVETFRUIT_EXTRACT;5249;20;;;;;5251;1;5252;2;;;5250.0;0\n",
    "VEV_4000": "0;0;VEV_4000;1250;5;;;;;1252;5;;;;;1251.0;0\n",
    "VEV_4500": "0;0;VEV_4500;760;5;;;;;762;5;;;;;761.0;0\n",
    "VEV_5000": "0;0;VEV_5000;9;5;8;5;;;10;1;11;2;;;10.5;0\n",
    "VEV_5100": "0;0;VEV_5100;6;5;;;;;7;5;;;;;6.5;0\n",
    "VEV_5200": "0;0;VEV_5200;4;5;;;;;5;5;;;;;4.5;0\n",
    "VEV_5300": "0;0;VEV_5300;3;5;;;;;4;5;;;;;3.5;0\n",
    "VEV_5400": "0;0;VEV_5400;2;5;;;;;3;5;;;;;2.5;0\n",
    "VEV_5500": "0;0;VEV_5500;1;5;;;;;2;5;;;;;1.5;0\n",
    "VEV_6000": "0;0;VEV_6000;0;5;;;;;1;5;;;;;0.5;0\n",
    "VEV_6500": "0;0;VEV_6500;0;5;;;;;1;5;;;;;0.5;0\n",
}


def _write_round3_tiny_dataset(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    ordered_rows = [_ROUND3_TINY_PRODUCT_ROWS[product] for product in products_for_round(3)]
    (data_dir / "prices_round_3_day_0.csv").write_text(
        _ROUND3_TINY_HEADER + "".join(ordered_rows), encoding="utf-8"
    )
    (data_dir / "trades_round_3_day_0.csv").write_text(
        "timestamp;buyer;seller;symbol;currency;price;quantity\n",
        encoding="utf-8",
    )


def _write_trader(path: Path, body: str) -> Path:
    path.write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")
    return path


_MULTI_LEVEL_TRADER = """
from datamodel import Order


class Trader:
    def run(self, state):
        return {
            "VELVETFRUIT_EXTRACT": [Order("VELVETFRUIT_EXTRACT", 5252, 3)],
            "VEV_5000": [Order("VEV_5000", 11, 3)],
        }, 0, state.traderData
"""


_LIMIT_TRADER = """
from datamodel import Order


class Trader:
    def run(self, state):
        return {
            "VEV_5000": [Order("VEV_5000", 10, 301)],
            "HYDROGEL_PACK": [Order("HYDROGEL_PACK", 100, 1)],
            "VELVETFRUIT_EXTRACT": [Order("VELVETFRUIT_EXTRACT", 5251, 1)],
        }, 0, state.traderData
"""


_ALL_PRODUCTS_TRADER = """
from datamodel import Order


class Trader:
    def run(self, state):
        orders = {}
        for product, depth in state.order_depths.items():
            if depth.sell_orders:
                orders[product] = [Order(product, min(depth.sell_orders), 1)]
        return orders, 0, state.traderData
"""


def replay_correctness_checks(work_dir: Path, noop_trader: Path, data_dir: Path) -> List[CheckResult]:
    results: List[CheckResult] = []
    tiny_data = work_dir / "tiny_data"
    _write_round3_tiny_dataset(tiny_data)

    # 1. Multi-level crossing
    try:
        trader = _write_trader(work_dir / "multi_level.py", _MULTI_LEVEL_TRADER)
        artefact = run_replay(
            trader_spec=TraderSpec(name="multi_level", path=trader),
            days=(0,),
            data_dir=tiny_data,
            fill_model_name="optimistic",
            perturbation=PerturbationConfig(),
            output_dir=work_dir / "multi_level_out",
            run_name="multi_level",
            round_number=3,
        )
        velvet = [(f["price"], f["quantity"]) for f in artefact.fills if f["product"] == "VELVETFRUIT_EXTRACT"]
        voucher = [(f["price"], f["quantity"]) for f in artefact.fills if f["product"] == "VEV_5000"]
        detail = {
            "velvetfruit_fills": velvet,
            "voucher_fills": voucher,
            "expected_velvet": [[5251, 1], [5252, 2]],
            "expected_voucher": [[10, 1], [11, 2]],
        }
        ok = velvet == [(5251, 1), (5252, 2)] and voucher == [(10, 1), (11, 2)]
        results.append(CheckResult(
            name="multi_level_crossing",
            status="pass" if ok else "fail",
            detail=detail,
            error=None if ok else "multi-level fill prices/quantities did not match expected walk-up",
        ))
    except Exception as exc:
        results.append(CheckResult(name="multi_level_crossing", status="fail", error=str(exc)))

    # 2. Fractional MTM
    try:
        trader = _write_trader(work_dir / "fractional_mtm.py",
            """
from datamodel import Order


class Trader:
    def run(self, state):
        return {"VEV_5000": [Order("VEV_5000", 11, 2)]}, 0, state.traderData
""")
        artefact = run_replay(
            trader_spec=TraderSpec(name="fractional_mtm", path=trader),
            days=(0,),
            data_dir=tiny_data,
            fill_model_name="optimistic",
            perturbation=PerturbationConfig(),
            output_dir=work_dir / "fractional_out",
            run_name="fractional_mtm",
            round_number=3,
        )
        pnl_row = next((row for row in artefact.pnl_series if row["product"] == "VEV_5000"), None)
        per_product = artefact.summary["per_product"]["VEV_5000"]
        detail = {
            "cash": per_product["cash"],
            "final_position": per_product["final_position"],
            "mark": None if pnl_row is None else pnl_row["mark"],
            "mid": None if pnl_row is None else pnl_row["mid"],
        }
        ok = (
            per_product["cash"] == -21.0
            and per_product["final_position"] == 2
            and pnl_row is not None
            and pnl_row["mark"] == 10.5
            and pnl_row["mid"] == 10.5
        )
        results.append(CheckResult(
            name="fractional_mtm",
            status="pass" if ok else "fail",
            detail=detail,
            error=None if ok else "fractional mark or cash did not match expected",
        ))
    except Exception as exc:
        results.append(CheckResult(name="fractional_mtm", status="fail", error=str(exc)))

    # 3. Limit enforcement + unrelated-product isolation
    try:
        trader = _write_trader(work_dir / "limit_check.py", _LIMIT_TRADER)
        artefact = run_replay(
            trader_spec=TraderSpec(name="limit_check", path=trader),
            days=(0,),
            data_dir=tiny_data,
            fill_model_name="optimistic",
            perturbation=PerturbationConfig(),
            output_dir=work_dir / "limit_out",
            run_name="limit_check",
            round_number=3,
        )
        per_product = artefact.summary["per_product"]
        fill_products = {fill["product"] for fill in artefact.fills}
        detail = {
            "limit_breaches": artefact.summary["limit_breaches"],
            "vev_5000_position": per_product["VEV_5000"]["final_position"],
            "hydrogel_position": per_product["HYDROGEL_PACK"]["final_position"],
            "velvet_position": per_product["VELVETFRUIT_EXTRACT"]["final_position"],
            "fill_products": sorted(fill_products),
        }
        ok = (
            artefact.summary["limit_breaches"] == 1
            and per_product["VEV_5000"]["final_position"] == 0
            and per_product["HYDROGEL_PACK"]["final_position"] == 1
            and per_product["VELVETFRUIT_EXTRACT"]["final_position"] == 1
            and fill_products == {"HYDROGEL_PACK", "VELVETFRUIT_EXTRACT"}
        )
        results.append(CheckResult(
            name="limit_enforcement_is_atomic_per_product",
            status="pass" if ok else "fail",
            detail=detail,
            error=None if ok else "limit enforcement did not isolate the breaching product",
        ))
    except Exception as exc:
        results.append(CheckResult(name="limit_enforcement_is_atomic_per_product", status="fail", error=str(exc)))

    # 4. All 12 products reachable
    try:
        trader = _write_trader(work_dir / "all_products.py", _ALL_PRODUCTS_TRADER)
        artefact = run_replay(
            trader_spec=TraderSpec(name="all_products", path=trader),
            days=(0,),
            data_dir=tiny_data,
            fill_model_name="optimistic",
            perturbation=PerturbationConfig(),
            output_dir=work_dir / "all_products_out",
            run_name="all_products",
            round_number=3,
        )
        fill_products = {fill["product"] for fill in artefact.fills}
        expected = set(products_for_round(3))
        detail = {
            "fill_products": sorted(fill_products),
            "expected_products": sorted(expected),
            "final_positions": dict(artefact.summary["final_positions"]),
        }
        ok = (
            fill_products == expected
            and all(pos == 1 for pos in artefact.summary["final_positions"].values())
            and artefact.summary["limit_breaches"] == 0
        )
        results.append(CheckResult(
            name="trader_can_reach_all_12_products",
            status="pass" if ok else "fail",
            detail=detail,
            error=None if ok else "not all 12 products executed",
        ))
    except Exception as exc:
        results.append(CheckResult(name="trader_can_reach_all_12_products", status="fail", error=str(exc)))

    # 5. No-op two-trader compare (quick, day 0 only)
    try:
        compare_out = work_dir / "noop_compare_out"
        rows = run_compare(
            trader_specs=[
                TraderSpec(name="noop_a", path=noop_trader),
                TraderSpec(name="noop_b", path=noop_trader),
            ],
            days=(0,),
            data_dir=data_dir,
            fill_model_name="base",
            perturbation=PerturbationConfig(),
            output_dir=compare_out,
            run_name="noop_compare",
            round_number=3,
        )
        detail = {
            "final_pnl_a": rows[0]["final_pnl"],
            "final_pnl_b": rows[1]["final_pnl"],
            "per_product_pnl_a": dict(rows[0]["per_product_pnl"]),
            "per_product_pnl_b": dict(rows[1]["per_product_pnl"]),
        }
        ok = (
            len(rows) == 2
            and rows[0]["final_pnl"] == 0
            and rows[1]["final_pnl"] == 0
            and rows[0]["per_product_pnl"] == rows[1]["per_product_pnl"]
            and all(value == 0 for value in rows[0]["per_product_pnl"].values())
        )
        results.append(CheckResult(
            name="noop_compare_exact_zero_diff",
            status="pass" if ok else "fail",
            detail=detail,
            error=None if ok else "noop compare produced a non-zero diff or non-zero per-product PnL",
        ))
    except Exception as exc:
        results.append(CheckResult(name="noop_compare_exact_zero_diff", status="fail", error=str(exc)))

    return results


# ---------------------------------------------------------------------------
# Option diagnostics proof
# ---------------------------------------------------------------------------


def _is_finite_or_none(value: Any) -> bool:
    if value is None:
        return True
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f)


def _scan_finite(node: Any) -> List[str]:
    issues: List[str] = []

    def _walk(prefix: str, n: Any) -> None:
        if isinstance(n, dict):
            for key, value in n.items():
                _walk(f"{prefix}.{key}" if prefix else str(key), value)
        elif isinstance(n, (list, tuple)):
            for idx, value in enumerate(n):
                _walk(f"{prefix}[{idx}]", value)
        elif isinstance(n, float):
            if not math.isfinite(n):
                issues.append(prefix)

    _walk("", node)
    return issues


def option_diagnostics_proof(data_dir: Path, days: Sequence[int]) -> CheckResult:
    try:
        dataset = load_round_dataset(data_dir, days, round_number=3)
        market_days = [dataset[day] for day in days]
        diagnostics = compute_option_diagnostics(market_days)
    except Exception as exc:
        return CheckResult(name="option_diagnostics", status="fail", error=str(exc))

    issues: List[str] = []
    nan_paths = _scan_finite(diagnostics)
    if nan_paths:
        issues.append(f"non-finite values at: {nan_paths[:5]}")
    if diagnostics.get("round") != 3:
        issues.append("diagnostics round != 3")
    days_payload = diagnostics.get("days") or []
    if len(days_payload) != len(days):
        issues.append(f"expected {len(days)} days, got {len(days_payload)}")

    day_summaries: List[Dict[str, object]] = []
    expected_surface_fit = list(ROUND3_SURFACE_FIT_VOUCHERS)
    for day_row in days_payload:
        policy = day_row.get("surface_fit_policy") or {}
        included = list(policy.get("included") or [])
        excluded = list(policy.get("excluded") or [])
        fit_quality = day_row.get("surface_fit_quality") or {}
        fit_source_counts = (fit_quality or {}).get("fit_source_counts") or {}
        direct_count = int(fit_source_counts.get("direct", 0))
        fallback_count = int(fit_source_counts.get("previous", 0)) + int(fit_source_counts.get("day_median", 0))
        vouchers_rows = day_row.get("vouchers") or []
        useful = {row["product"]: row for row in vouchers_rows if row.get("include_in_surface_fit")}
        ambient = {row["product"]: row for row in vouchers_rows if not row.get("include_in_surface_fit")}
        warnings_count = sum(len(row.get("warnings", [])) for row in vouchers_rows)
        day_summaries.append({
            "day": day_row.get("day"),
            "tte_days": day_row.get("tte_days"),
            "included": included,
            "excluded": excluded,
            "direct_fit_count": direct_count,
            "fallback_fit_count": fallback_count,
            "useful_count": len(useful),
            "excluded_count": len(ambient),
            "total_warnings": warnings_count,
            "chain_samples": len(day_row.get("chain_samples") or []),
        })
        if included != expected_surface_fit:
            issues.append(f"day {day_row.get('day')}: included mismatch ({included} vs expected)")
        if not vouchers_rows:
            issues.append(f"day {day_row.get('day')}: no voucher rows emitted")

    detail = {
        "days": day_summaries,
        "round": diagnostics.get("round"),
        "underlying": diagnostics.get("underlying"),
        "final_tte_days": diagnostics.get("final_tte_days"),
        "surface_fit_vouchers": list(diagnostics.get("surface_fit_vouchers") or []),
        "nan_or_inf_paths": nan_paths[:10],
    }
    status = "pass" if not issues else "fail"
    return CheckResult(
        name="option_diagnostics",
        status=status,
        detail=detail,
        error=None if status == "pass" else "; ".join(issues),
    )


# ---------------------------------------------------------------------------
# MC coherence proof (in-process; heavy end-to-end MC is also run as subprocess)
# ---------------------------------------------------------------------------


def mc_coherence_proof(data_dir: Path) -> CheckResult:
    try:
        dataset = load_round_dataset(data_dir, (0, 1, 2), round_number=3)
        historical = [dataset[0], dataset[1], dataset[2]]
        context = prepare_round3_synthetic_context(historical, tick_count=30)
    except Exception as exc:
        return CheckResult(name="mc_coherence", status="fail", error=str(exc))

    seed_a = 20260424
    seed_b = 71113

    def _gen(perturb: PerturbationConfig, seed: int):
        return generate_synthetic_market_days(
            days=(0,),
            seed=seed,
            perturb=perturb,
            round_spec=get_round_spec(3),
            round3_context=context,
        )[0]

    base_perturb = PerturbationConfig(synthetic_tick_limit=30, option_residual_noise_scale=0.0)
    up_perturb = PerturbationConfig(synthetic_tick_limit=30, shock_tick=5, underlying_shock=120.0, option_residual_noise_scale=0.0)
    down_perturb = PerturbationConfig(synthetic_tick_limit=30, shock_tick=5, underlying_shock=-120.0, option_residual_noise_scale=0.0)
    vol_perturb = PerturbationConfig(synthetic_tick_limit=30, option_residual_noise_scale=0.0, vol_shift=0.10)
    hydrogel_perturb = PerturbationConfig(synthetic_tick_limit=30, shock_tick=5, hydrogel_shock=500.0, option_residual_noise_scale=0.0)
    residual_perturb = PerturbationConfig(synthetic_tick_limit=30, option_residual_noise_scale=1.0)

    try:
        base_day_a = _gen(base_perturb, seed_a)
        base_day_b = _gen(base_perturb, seed_a)  # same seed
        base_day_c = _gen(base_perturb, seed_b)
        up_day = _gen(up_perturb, seed_a)
        down_day = _gen(down_perturb, seed_a)
        vol_day = _gen(vol_perturb, seed_a)
        hydrogel_day = _gen(hydrogel_perturb, seed_a)
        residual_day = _gen(residual_perturb, seed_a)
    except Exception as exc:
        return CheckResult(name="mc_coherence", status="fail", error=str(exc))

    issues: List[str] = []

    # Seed determinism
    underlying_a = [base_day_a.books_by_timestamp[ts][ROUND3_UNDERLYING].reference_fair for ts in base_day_a.timestamps]
    underlying_b = [base_day_b.books_by_timestamp[ts][ROUND3_UNDERLYING].reference_fair for ts in base_day_b.timestamps]
    underlying_c = [base_day_c.books_by_timestamp[ts][ROUND3_UNDERLYING].reference_fair for ts in base_day_c.timestamps]
    if underlying_a != underlying_b:
        issues.append("same-seed underlying path differs")
    if underlying_a == underlying_c:
        issues.append("different seeds produced identical paths")

    # Product set
    first_ts = base_day_a.timestamps[0]
    if set(base_day_a.books_by_timestamp[first_ts]) != set(products_for_round(3)):
        issues.append("generated product set != R3 product set")

    # Positive books + coherent quotes
    for ts, snapshots in base_day_a.books_by_timestamp.items():
        for product, snap in snapshots.items():
            if snap.bids and snap.bids[0][0] < 0:
                issues.append(f"negative bid at {ts} for {product}")
            if snap.asks and snap.asks[0][0] < 0:
                issues.append(f"negative ask at {ts} for {product}")
            if snap.bids and snap.asks and snap.bids[0][0] >= snap.asks[0][0]:
                issues.append(f"crossed book at {ts} for {product}")

    # Shock coherence on a later timestamp
    timestamp = 1500
    if timestamp in up_day.books_by_timestamp and timestamp in base_day_a.books_by_timestamp:
        if up_day.books_by_timestamp[timestamp][ROUND3_UNDERLYING].reference_fair <= base_day_a.books_by_timestamp[timestamp][ROUND3_UNDERLYING].reference_fair:
            issues.append("positive underlying shock did not increase underlying fair")
        if down_day.books_by_timestamp[timestamp][ROUND3_UNDERLYING].reference_fair >= base_day_a.books_by_timestamp[timestamp][ROUND3_UNDERLYING].reference_fair:
            issues.append("negative underlying shock did not decrease underlying fair")
        for symbol in ("VEV_5000", "VEV_5200", "VEV_5500"):
            up_fair = up_day.books_by_timestamp[timestamp][symbol].reference_fair
            base_fair = base_day_a.books_by_timestamp[timestamp][symbol].reference_fair
            down_fair = down_day.books_by_timestamp[timestamp][symbol].reference_fair
            if up_fair < base_fair:
                issues.append(f"{symbol}: up shock decreased voucher fair")
            if down_fair > base_fair:
                issues.append(f"{symbol}: down shock increased voucher fair")

    # Vol shift: ATM/OTM calls should not decrease
    for symbol in ("VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500"):
        vol_fair = vol_day.books_by_timestamp[timestamp][symbol].reference_fair
        base_fair = base_day_a.books_by_timestamp[timestamp][symbol].reference_fair
        if vol_fair < base_fair:
            issues.append(f"{symbol}: vol_shift did not raise call fair")

    # Hydrogel shock must not move vouchers
    for symbol in ("VEV_5000", "VEV_5300", "VEV_5500"):
        if hydrogel_day.books_by_timestamp[timestamp][symbol].reference_fair != base_day_a.books_by_timestamp[timestamp][symbol].reference_fair:
            issues.append(f"{symbol}: hydrogel shock mechanically moved voucher")

    # Hydrogel shock should move hydrogel
    if [hydrogel_day.books_by_timestamp[ts][ROUND3_HYDROGEL].reference_fair for ts in hydrogel_day.timestamps] == [
        base_day_a.books_by_timestamp[ts][ROUND3_HYDROGEL].reference_fair for ts in base_day_a.timestamps
    ]:
        issues.append("hydrogel shock did not change hydrogel path")

    # Residual noise touches vouchers but not underlying
    residual_underlying = [residual_day.books_by_timestamp[ts][ROUND3_UNDERLYING].reference_fair for ts in residual_day.timestamps]
    if residual_underlying != underlying_a:
        issues.append("residual noise altered underlying path")
    if all(
        residual_day.books_by_timestamp[ts]["VEV_5000"].reference_fair
        == base_day_a.books_by_timestamp[ts]["VEV_5000"].reference_fair
        for ts in base_day_a.timestamps
    ):
        issues.append("residual noise failed to perturb vouchers")

    detail = {
        "seed_determinism": underlying_a == underlying_b and underlying_a != underlying_c,
        "products_match_r3_set": set(base_day_a.books_by_timestamp[first_ts]) == set(products_for_round(3)),
        "timestamps_checked": len(base_day_a.timestamps),
        "issue_count": len(issues),
    }
    status = "pass" if not issues else "fail"
    return CheckResult(
        name="mc_coherence",
        status=status,
        detail=detail,
        error=None if status == "pass" else "; ".join(issues[:8]),
    )


# ---------------------------------------------------------------------------
# Dashboard payload proof (runs inside the replay bundle already produced)
# ---------------------------------------------------------------------------


def dashboard_payload_proof(bundle_dir: Path) -> CheckResult:
    dashboard = bundle_dir / "dashboard.json"
    manifest = bundle_dir / "manifest.json"
    if not dashboard.is_file() or not manifest.is_file():
        return CheckResult(
            name="dashboard_payload",
            status="fail",
            error=f"missing dashboard/manifest in {bundle_dir}",
        )
    try:
        payload = json.loads(dashboard.read_text(encoding="utf-8"))
        manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return CheckResult(name="dashboard_payload", status="fail", error=f"JSON parse error: {exc}")

    expected = list(products_for_round(3))
    products_in_payload = list(payload.get("products") or [])
    metadata_keys = set(payload.get("productMetadata") or {})
    issues: List[str] = []
    if products_in_payload != expected:
        issues.append("dashboard products != R3 expected set")
    if metadata_keys != set(expected):
        issues.append("dashboard productMetadata missing products")
    if "optionDiagnostics" not in payload:
        issues.append("dashboard lacks optionDiagnostics")
    else:
        od = payload["optionDiagnostics"]
        if int(od.get("round", 0)) != 3:
            issues.append("optionDiagnostics.round != 3")
        if len(od.get("days") or []) < 1:
            issues.append("optionDiagnostics has no days")
    # R2 access leakage check
    assumptions = payload.get("assumptions") or {}
    if "round2" in assumptions:
        issues.append("dashboard surfaces round2 assumptions block for R3 bundle")
    access = payload.get("accessScenario") or manifest_payload.get("access_scenario") or {}
    if access and str(access.get("name", "")).startswith("extra"):
        issues.append("accessScenario still marks extra_access for R3")
    # Data contract should include option_diagnostics when diagnostics present
    data_contract = payload.get("dataContract") or []
    keys = {item.get("key") for item in data_contract if isinstance(item, dict)}
    if "option_diagnostics" not in keys:
        issues.append("data contract missing option_diagnostics key")

    position_limits = manifest_payload.get("position_limits") or {}
    if int(position_limits.get("HYDROGEL_PACK", 0)) != 200:
        issues.append("HYDROGEL_PACK limit not 200 in manifest")
    if int(position_limits.get("VELVETFRUIT_EXTRACT", 0)) != 200:
        issues.append("VELVETFRUIT_EXTRACT limit not 200 in manifest")
    for voucher in ROUND3_VOUCHERS:
        if int(position_limits.get(voucher, 0)) != 300:
            issues.append(f"{voucher} limit not 300 in manifest")
            break

    status = "pass" if not issues else "fail"
    detail = {
        "bundle_dir": str(bundle_dir),
        "products": products_in_payload,
        "has_option_diagnostics": "optionDiagnostics" in payload,
        "data_contract_keys": sorted(keys),
        "position_limits_sample": {
            key: position_limits.get(key)
            for key in ("HYDROGEL_PACK", "VELVETFRUIT_EXTRACT", "VEV_5000", "VEV_6500")
        },
    }
    return CheckResult(
        name="dashboard_payload",
        status=status,
        detail=detail,
        error=None if status == "pass" else "; ".join(issues),
    )


# ---------------------------------------------------------------------------
# Performance table + markdown rendering
# ---------------------------------------------------------------------------


def _fmt_mb(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}"


def _fmt_bytes(value: Optional[int]) -> str:
    if value is None:
        return "n/a"
    v = float(value)
    if v >= 1e9:
        return f"{v / 1e9:.2f} GB"
    if v >= 1e6:
        return f"{v / 1e6:.2f} MB"
    if v >= 1e3:
        return f"{v / 1e3:.1f} KB"
    return f"{int(v)} B"


def render_markdown(report: Dict[str, object]) -> str:
    provenance = report.get("provenance") or {}
    git = (provenance.get("git") or {}) if isinstance(provenance, dict) else {}
    runtime = (provenance.get("runtime") or {}) if isinstance(provenance, dict) else {}
    checks = report.get("checks") or []
    commands = report.get("commands") or []
    summary = report.get("summary") or {}

    lines: List[str] = [
        "# Round 3 Verification Report",
        "",
        f"- Generated at: `{report.get('generated_at')}`",
        f"- Data dir: `{report.get('data_dir')}`",
        f"- Output dir: `{report.get('output_dir')}`",
        f"- Mode: `{report.get('mode', 'full')}`",
        f"- Git commit: `{git.get('commit')}`",
        f"- Git dirty: `{git.get('dirty')}`",
        f"- Git branch: `{git.get('branch')}`",
        f"- Python: `{runtime.get('python_version')}`",
        f"- Platform: `{report.get('platform')}`",
        f"- psutil available: `{report.get('psutil_available')}`",
        "",
        f"Overall status: **{summary.get('overall_status')}** "
        f"({summary.get('passed', 0)} passed, {summary.get('failed', 0)} failed, {summary.get('skipped', 0)} skipped)",
        "",
        "## Checks",
        "",
        "| Check | Status | Error |",
        "| --- | --- | --- |",
    ]
    for check in checks:
        error = str(check.get("error") or "")
        error = error.replace("|", "\\|")
        if len(error) > 80:
            error = error[:80] + "..."
        lines.append(f"| `{check.get('name')}` | {check.get('status')} | {error} |")

    lines.extend([
        "",
        "## Performance / RSS / Output size",
        "",
        "| Command | Wall (s) | Peak RSS parent (MB) | Peak RSS tree (MB) | Children | Output size | Files | Status |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |",
    ])
    for cmd in commands:
        lines.append(
            "| `{name}` | {wall:.2f} | {parent} | {tree} | {children} | {size} | {files} | {status} |".format(
                name=cmd.get("name"),
                wall=float(cmd.get("wall_seconds") or 0.0),
                parent=_fmt_mb(cmd.get("peak_rss_mb_process")),
                tree=_fmt_mb(cmd.get("peak_rss_mb_tree")),
                children=cmd.get("peak_child_process_count") if cmd.get("peak_child_process_count") is not None else "n/a",
                size=_fmt_bytes(cmd.get("output_size_bytes")),
                files=cmd.get("output_file_count") if cmd.get("output_file_count") is not None else "n/a",
                status=cmd.get("status"),
            )
        )

    caveats = report.get("caveats") or []
    if caveats:
        lines.extend(["", "## Caveats", ""])
        for caveat in caveats:
            lines.append(f"- {caveat}")

    lines.extend(["", "## Command transcripts", ""])
    for cmd in commands:
        lines.append(f"### {cmd.get('name')}")
        lines.append("")
        lines.append("```")
        lines.append(" ".join(str(part) for part in (cmd.get("command") or [])))
        lines.append("```")
        if cmd.get("rss_caveats"):
            lines.append("")
            lines.append("RSS caveats:")
            for caveat in cmd.get("rss_caveats") or []:
                lines.append(f"- {caveat}")
        tail = cmd.get("stderr_tail")
        if tail:
            lines.extend(["", "stderr tail:", "```", tail, "```"])
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def run_verify_round3(
    *,
    data_dir: Path,
    output_dir: Path,
    days: Sequence[int] = (0, 1, 2),
    mc_sessions_fast: int = 8,
    mc_sessions_medium: int = 32,
    mc_sessions_heavy: int = 64,
    mc_synthetic_tick_limit: int = 250,
    mc_workers: Sequence[int] = (1, 2, 4),
    skip_heavy_mc: bool = False,
    noop_trader: Optional[Path] = None,
    research_scenarios_config: Optional[Path] = None,
    fill_sensitivity_config: Optional[Path] = None,
) -> Dict[str, object]:
    repo_root = Path(__file__).resolve().parent.parent
    data_dir = data_dir.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    noop_trader = (noop_trader or (repo_root / "examples" / "noop_round3_trader.py")).resolve()
    research_scenarios_config = (research_scenarios_config or (repo_root / "configs" / "round3_research_scenarios.json")).resolve()
    fill_sensitivity_config = (fill_sensitivity_config or (repo_root / "configs" / "round3_fill_sensitivity.json")).resolve()

    started = datetime.now(timezone.utc)
    provenance = capture_provenance(start=repo_root)
    checks: List[CheckResult] = []
    commands: List[CommandResult] = []

    # ---- Data validation
    checks.append(validate_data(data_dir, days))

    # ---- Option diagnostics
    checks.append(option_diagnostics_proof(data_dir, days))

    # ---- MC coherence (in-process)
    checks.append(mc_coherence_proof(data_dir))

    # ---- Replay correctness fixtures (in-process, small)
    work_dir = output_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    checks.extend(replay_correctness_checks(work_dir, noop_trader, data_dir))

    # ---- Subprocess: inspect (stdout streamed to inspect_report.json)
    inspect_out = output_dir / "inspect_report.json"
    commands.append(run_with_rss(
        name="inspect_round3_all_days",
        command=[
            sys.executable, "-m", "prosperity_backtester", "inspect",
            "--round", "3",
            "--data-dir", str(data_dir),
            "--days", *[str(d) for d in days],
            "--json",
        ],
        cwd=repo_root,
        output_dir=None,
        output_paths=[inspect_out],
        capture_stdout_path=inspect_out,
    ))

    # ---- Subprocess: replay day 0 no-op
    noop_day0_dir = output_dir / "replay_noop_day0"
    commands.append(run_with_rss(
        name="replay_noop_day0",
        command=[
            sys.executable, "-m", "prosperity_backtester", "replay",
            str(noop_trader),
            "--round", "3",
            "--data-dir", str(data_dir),
            "--days", "0",
            "--fill-mode", "base",
            "--output-dir", str(noop_day0_dir),
        ],
        cwd=repo_root,
        output_dir=noop_day0_dir,
    ))

    # ---- Subprocess: replay all days no-op (bundle used for dashboard payload proof)
    noop_all_dir = output_dir / "replay_noop_days012"
    commands.append(run_with_rss(
        name="replay_noop_days012",
        command=[
            sys.executable, "-m", "prosperity_backtester", "replay",
            str(noop_trader),
            "--round", "3",
            "--data-dir", str(data_dir),
            "--days", "0", "1", "2",
            "--fill-mode", "base",
            "--output-dir", str(noop_all_dir),
        ],
        cwd=repo_root,
        output_dir=noop_all_dir,
    ))

    # ---- Dashboard payload proof on the three-day bundle
    if commands[-1].status == "ok":
        checks.append(dashboard_payload_proof(noop_all_dir))
    else:
        checks.append(CheckResult(name="dashboard_payload", status="skip", error="replay failed"))

    # ---- Subprocess: compare two no-op traders (R3)
    compare_dir = output_dir / "compare_noop_day0"
    commands.append(run_with_rss(
        name="compare_noop_day0",
        command=[
            sys.executable, "-m", "prosperity_backtester", "compare",
            str(noop_trader), str(noop_trader),
            "--names", "noop_a", "noop_b",
            "--round", "3",
            "--data-dir", str(data_dir),
            "--days", "0",
            "--fill-mode", "base",
            "--output-dir", str(compare_dir),
        ],
        cwd=repo_root,
        output_dir=compare_dir,
    ))

    # ---- Subprocess: Monte Carlo — fast, medium, heavy × workers
    def _mc_name(sessions: int, workers: int) -> str:
        return f"monte_carlo_{sessions}s_w{workers}"

    for sessions, label_workers in (
        (mc_sessions_fast, (1,)),
        (mc_sessions_medium, (1,)),
    ):
        for workers in label_workers:
            out = output_dir / _mc_name(sessions, workers)
            commands.append(run_with_rss(
                name=_mc_name(sessions, workers),
                command=[
                    sys.executable, "-m", "prosperity_backtester", "monte-carlo",
                    str(noop_trader),
                    "--round", "3",
                    "--data-dir", str(data_dir),
                    "--days", "0",
                    "--sessions", str(sessions),
                    "--sample-sessions", "2",
                    "--synthetic-tick-limit", str(mc_synthetic_tick_limit),
                    "--workers", str(workers),
                    "--output-dir", str(out),
                ],
                cwd=repo_root,
                output_dir=out,
            ))

    if not skip_heavy_mc:
        for workers in mc_workers:
            out = output_dir / _mc_name(mc_sessions_heavy, workers)
            commands.append(run_with_rss(
                name=_mc_name(mc_sessions_heavy, workers),
                command=[
                    sys.executable, "-m", "prosperity_backtester", "monte-carlo",
                    str(noop_trader),
                    "--round", "3",
                    "--data-dir", str(data_dir),
                    "--days", "0",
                    "--sessions", str(mc_sessions_heavy),
                    "--sample-sessions", "4",
                    "--synthetic-tick-limit", str(mc_synthetic_tick_limit),
                    "--workers", str(workers),
                    "--output-dir", str(out),
                ],
                cwd=repo_root,
                output_dir=out,
            ))

    # ---- Subprocess: scenario compare research
    research_out = output_dir / "scenario_research"
    commands.append(run_with_rss(
        name="scenario_compare_research",
        command=[
            sys.executable, "-m", "prosperity_backtester", "scenario-compare",
            str(research_scenarios_config),
            "--output-dir", str(research_out),
        ],
        cwd=repo_root,
        output_dir=research_out,
    ))

    # ---- Subprocess: scenario compare fill sensitivity
    fill_out = output_dir / "scenario_fill_sensitivity"
    commands.append(run_with_rss(
        name="scenario_compare_fill_sensitivity",
        command=[
            sys.executable, "-m", "prosperity_backtester", "scenario-compare",
            str(fill_sensitivity_config),
            "--output-dir", str(fill_out),
        ],
        cwd=repo_root,
        output_dir=fill_out,
    ))

    # ---- Seed determinism across two MC runs with the same seed
    mc_seed_a = output_dir / "mc_seed_determinism_a"
    mc_seed_b = output_dir / "mc_seed_determinism_b"
    commands.append(run_with_rss(
        name="mc_seed_determinism_a",
        command=[
            sys.executable, "-m", "prosperity_backtester", "monte-carlo",
            str(noop_trader),
            "--round", "3",
            "--data-dir", str(data_dir),
            "--days", "0",
            "--sessions", "4",
            "--sample-sessions", "2",
            "--synthetic-tick-limit", "120",
            "--seed", "2026",
            "--output-dir", str(mc_seed_a),
        ],
        cwd=repo_root,
        output_dir=mc_seed_a,
    ))
    commands.append(run_with_rss(
        name="mc_seed_determinism_b",
        command=[
            sys.executable, "-m", "prosperity_backtester", "monte-carlo",
            str(noop_trader),
            "--round", "3",
            "--data-dir", str(data_dir),
            "--days", "0",
            "--sessions", "4",
            "--sample-sessions", "2",
            "--synthetic-tick-limit", "120",
            "--seed", "2026",
            "--output-dir", str(mc_seed_b),
        ],
        cwd=repo_root,
        output_dir=mc_seed_b,
    ))
    if all(commands[i].status == "ok" for i in (-2, -1)):
        checks.append(_mc_seed_determinism_check(mc_seed_a, mc_seed_b))
    else:
        checks.append(CheckResult(name="mc_seed_determinism", status="skip", error="mc runs failed"))

    # ---- Aggregate results
    finished = datetime.now(timezone.utc)
    passed = sum(1 for c in checks if c.status == "pass")
    failed = sum(1 for c in checks if c.status == "fail")
    skipped = sum(1 for c in checks if c.status == "skip")
    command_failures = sum(1 for c in commands if c.status != "ok")
    overall_status = "pass" if failed == 0 and command_failures == 0 else "fail"

    caveats = [
        "Passive fills are approximate by design. The fill-sensitivity scenario set stresses this explicitly.",
        "Round 3 Monte Carlo remains classic-only. The Rust engine is not wired up for Round 3.",
        "Historical replay trades observed books and marks to observed mids. No option exercise or cash settlement is simulated.",
    ]
    if not _HAVE_PSUTIL:
        caveats.append("psutil is not installed in the active environment; peak RSS is unavailable for subprocess commands.")

    report: Dict[str, object] = {
        "generated_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "wall_seconds_total": round((finished - started).total_seconds(), 3),
        "mode": "quick" if skip_heavy_mc else "full",
        "skip_heavy_mc": bool(skip_heavy_mc),
        "data_dir": str(data_dir),
        "output_dir": str(output_dir),
        "days": list(int(d) for d in days),
        "platform": platform_module.platform(),
        "python_executable": sys.executable,
        "psutil_available": bool(_HAVE_PSUTIL),
        "provenance": provenance,
        "summary": {
            "overall_status": overall_status,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "command_failures": command_failures,
            "check_count": len(checks),
            "command_count": len(commands),
        },
        "checks": [c.to_dict() for c in checks],
        "commands": [c.to_dict() for c in commands],
        "caveats": caveats,
    }

    (output_dir / "verification_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    (output_dir / "verification_report.md").write_text(render_markdown(report), encoding="utf-8")
    # Simple manifest alias for discoverability
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "type": "round3_verification",
                "created_at": started.isoformat(),
                "data_dir": str(data_dir),
                "overall_status": overall_status,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "command_count": len(commands),
                "report": "verification_report.json",
                "report_markdown": "verification_report.md",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return report


def _mc_seed_determinism_check(dir_a: Path, dir_b: Path) -> CheckResult:
    try:
        dash_a = json.loads((dir_a / "dashboard.json").read_text(encoding="utf-8"))
        dash_b = json.loads((dir_b / "dashboard.json").read_text(encoding="utf-8"))
    except Exception as exc:
        return CheckResult(name="mc_seed_determinism", status="fail", error=str(exc))
    summary_a = ((dash_a.get("monteCarlo") or {}).get("summary") or {})
    summary_b = ((dash_b.get("monteCarlo") or {}).get("summary") or {})
    detail = {
        "mean_a": summary_a.get("mean"),
        "mean_b": summary_b.get("mean"),
        "std_a": summary_a.get("std"),
        "std_b": summary_b.get("std"),
        "session_count_a": summary_a.get("session_count"),
        "session_count_b": summary_b.get("session_count"),
    }
    ok = summary_a.get("mean") == summary_b.get("mean") and summary_a.get("std") == summary_b.get("std")
    return CheckResult(
        name="mc_seed_determinism",
        status="pass" if ok else "fail",
        detail=detail,
        error=None if ok else "MC summaries differ between two identical-seed runs",
    )
