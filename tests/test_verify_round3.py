from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Mapping

import pytest

from prosperity_backtester.dataset import load_round_dataset
from prosperity_backtester.metadata import products_for_round
from prosperity_backtester.round3 import compute_option_diagnostics
from prosperity_backtester.verify_round3 import (
    CheckResult,
    _scan_finite,
    dashboard_payload_proof,
    mc_coherence_proof,
    option_diagnostics_proof,
    render_markdown,
    replay_correctness_checks,
    run_with_rss,
    run_verify_round3,
    validate_data,
)


ROOT = Path(__file__).resolve().parent.parent
ROUND3_DATA = ROOT / "data" / "round3"
NOOP_TRADER = ROOT / "tests" / "fixtures" / "noop_round3_trader.py"


def _walk_finite(payload) -> None:
    issues = _scan_finite(payload)
    assert not issues, f"non-finite values found in payload at: {issues[:5]}"


def test_data_validation_matches_known_r3_counts():
    result = validate_data(ROUND3_DATA, (0, 1, 2))
    assert result.status == "pass", result.error
    detail = result.detail
    days = {row["day"]: row for row in detail["days"]}
    assert set(days) == {0, 1, 2}
    assert days[0]["price_rows"] == 120_000
    assert days[0]["timestamps"] == 10_000
    assert days[0]["timestamp_min"] == 0
    assert days[0]["timestamp_max"] == 999_900
    assert days[0]["trade_rows"] == 1_308
    assert days[1]["trade_rows"] == 1_407
    assert days[2]["trade_rows"] == 1_333
    assert days[0]["products_seen"] == list(products_for_round(3))
    assert detail["file_manifest"]
    for entry in detail["file_manifest"]:
        if entry["exists"]:
            assert "sha256" in entry
            assert len(entry["sha256"]) == 64


def test_option_diagnostics_proof_is_clean_and_finite():
    result = option_diagnostics_proof(ROUND3_DATA, (0,))
    assert result.status == "pass", result.error
    assert result.detail["round"] == 3
    # Raw diagnostics should have no NaN/Inf leaks when serialised.
    dataset = load_round_dataset(ROUND3_DATA, (0, 1, 2), round_number=3)
    diagnostics = compute_option_diagnostics([dataset[0], dataset[1], dataset[2]])
    _walk_finite(diagnostics)


def test_mc_coherence_proof_catches_basic_invariants():
    result = mc_coherence_proof(ROUND3_DATA)
    assert result.status == "pass", result.error
    assert result.detail["seed_determinism"] is True
    assert result.detail["products_match_r3_set"] is True


def test_replay_correctness_fixtures_pass(tmp_path: Path):
    results = replay_correctness_checks(tmp_path, NOOP_TRADER, ROUND3_DATA)
    assert all(r.status == "pass" for r in results), "\n".join(
        f"{r.name}: {r.status} {r.error}" for r in results
    )
    names = {r.name for r in results}
    assert {
        "multi_level_crossing",
        "fractional_mtm",
        "limit_enforcement_is_atomic_per_product",
        "trader_can_reach_all_12_products",
        "noop_compare_exact_zero_diff",
    } <= names


def test_scan_finite_detects_nan_and_inf():
    payload = {
        "ok": 1.0,
        "nested": {"values": [1, 2, float("nan")]},
        "inf": float("inf"),
    }
    issues = _scan_finite(payload)
    assert any("inf" in p for p in issues)
    assert any("nested.values[2]" in p for p in issues)


def test_dashboard_payload_proof_reports_meaningful_issues(tmp_path: Path):
    # Create a stub dashboard bundle with missing diagnostics.
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "dashboard.json").write_text(
        json.dumps({
            "products": list(products_for_round(3)),
            "productMetadata": {p: {} for p in products_for_round(3)},
            "assumptions": {"round2": "leak"},
            "dataContract": [],
        }),
        encoding="utf-8",
    )
    (bundle / "manifest.json").write_text(
        json.dumps({
            "position_limits": {p: 999 for p in products_for_round(3)},
        }),
        encoding="utf-8",
    )
    result = dashboard_payload_proof(bundle)
    assert result.status == "fail"
    assert result.error is not None
    assert "round2" in result.error or "option_diagnostics" in result.error


def test_run_with_rss_accounts_captured_stdout_file(tmp_path: Path):
    inspect_out = tmp_path / "inspect_report.json"
    result = run_with_rss(
        "inspect_fixture",
        [sys.executable, "-c", "import json; print(json.dumps({'ok': True}))"],
        cwd=ROOT,
        capture_stdout_path=inspect_out,
        output_paths=[inspect_out],
        timeout_seconds=10,
    )

    assert result.status == "ok"
    assert result.output_size_bytes == inspect_out.stat().st_size
    assert result.output_file_count == 1

    markdown = render_markdown({
        "generated_at": "fixture",
        "data_dir": str(ROUND3_DATA),
        "output_dir": str(tmp_path),
        "mode": "quick",
        "psutil_available": True,
        "provenance": {"git": {}, "runtime": {}},
        "summary": {"overall_status": "pass", "passed": 0, "failed": 0, "skipped": 0},
        "checks": [],
        "commands": [result.to_dict()],
        "caveats": [],
    })
    command_row = next(line for line in markdown.splitlines() if "`inspect_fixture`" in line)
    cells = [cell.strip() for cell in command_row.strip("|").split("|")]
    assert cells[5] != "n/a"
    assert cells[6] == "1"


def test_run_with_rss_without_psutil_reports_rss_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import prosperity_backtester.verify_round3 as verify_round3

    monkeypatch.setattr(verify_round3, "_HAVE_PSUTIL", False)
    monkeypatch.setattr(verify_round3, "psutil", None)

    result = verify_round3.run_with_rss(
        "no_psutil_fixture",
        [sys.executable, "-c", "print('ok')"],
        cwd=ROOT,
        timeout_seconds=10,
    )

    assert result.status == "ok"
    assert result.rss_capture_method == "none"
    assert result.peak_rss_mb_process is None
    assert result.peak_rss_mb_tree is None
    assert result.peak_child_process_count is None
    assert any("psutil is not installed" in caveat for caveat in result.rss_caveats)


@pytest.mark.slow
def test_run_verify_round3_skip_heavy_end_to_end(tmp_path: Path):
    # Integration test — deliberately gated under --runslow if configured.
    # It exercises subprocess-launched replay + compare + inspect, but skips
    # the heavier MC sweep to keep pytest tractable in CI-like environments.
    report = run_verify_round3(
        data_dir=ROUND3_DATA,
        output_dir=tmp_path / "verification",
        days=(0,),
        mc_sessions_fast=2,
        mc_sessions_medium=4,
        mc_sessions_heavy=4,
        mc_synthetic_tick_limit=80,
        skip_heavy_mc=True,
        noop_trader=NOOP_TRADER,
    )
    assert (tmp_path / "verification" / "verification_report.json").is_file()
    assert (tmp_path / "verification" / "verification_report.md").is_file()
    assert (tmp_path / "verification" / "manifest.json").is_file()
    assert isinstance(report.get("summary"), Mapping)
