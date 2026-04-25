from __future__ import annotations

import json
from pathlib import Path

import pytest

from prosperity_backtester.__main__ import main
from prosperity_backtester.server import _find_bundles
from prosperity_backtester.workspace import WorkspaceSource, assemble_workspace_payload, write_workspace_bundle

ROOT = Path(__file__).resolve().parent.parent


def _base_payload(run_type: str, run_name: str) -> dict:
    return {
        "type": run_type,
        "meta": {
            "schemaVersion": 3,
            "runName": run_name,
            "traderName": f"{run_name}_trader",
            "mode": run_type,
            "round": 2,
            "fillModel": {
                "name": "base",
                "passive_fill_rate": 0.5,
                "same_price_queue_share": 0.1,
                "queue_pressure": 0.1,
                "missed_fill_probability": 0.0,
                "adverse_selection_ticks": 0,
                "aggressive_slippage_ticks": 0,
            },
            "perturbations": {},
            "outputProfile": {"profile": "light"},
            "createdAt": "2026-04-24T10:00:00+00:00",
            "provenance": {
                "workflow_tier": "manual",
                "command": {
                    "display": f"python -m prosperity_backtester {run_type} {run_name}",
                    "cwd": str(ROOT),
                },
                "git": {
                    "commit": "abc123def4567890",
                    "dirty": False,
                    "branch": "main",
                },
                "runtime": {
                    "engine_backend": "python",
                    "parallelism": "single_process",
                    "worker_count": 1,
                },
            },
        },
        "products": ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"],
        "assumptions": {"exact": [f"{run_name} exact"], "approximate": [f"{run_name} approximate"]},
        "datasetReports": [],
        "validation": {},
    }


def _replay_payload(run_name: str) -> dict:
    payload = _base_payload("replay", run_name)
    payload["summary"] = {
        "final_pnl": 125.0,
        "fill_count": 2,
        "order_count": 3,
        "limit_breaches": 0,
        "max_drawdown": 4.0,
        "final_positions": {"ASH_COATED_OSMIUM": 1, "INTARIAN_PEPPER_ROOT": 0},
        "per_product": {
            "ASH_COATED_OSMIUM": {
                "cash": 0.0,
                "realised": 10.0,
                "unrealised": 2.0,
                "final_mtm": 12.0,
                "final_position": 1,
                "avg_entry_price": 10000.0,
            }
        },
        "fair_value": {},
        "behaviour": {},
    }
    payload["pnlSeries"] = [
        {
            "day": 0,
            "timestamp": 100,
            "product": "ASH_COATED_OSMIUM",
            "cash": 0.0,
            "realised": 10.0,
            "unrealised": 2.0,
            "mtm": 12.0,
            "mark": 1.0,
            "mid": 1.0,
            "fair": 1.0,
            "spread": 1.0,
            "position": 1,
        }
    ]
    payload["inventorySeries"] = [
        {
            "day": 0,
            "timestamp": 100,
            "product": "ASH_COATED_OSMIUM",
            "position": 1,
            "avg_entry_price": 10000.0,
            "mid": 1.0,
            "fair": 1.0,
        }
    ]
    payload["fairValueSeries"] = [
        {
            "day": 0,
            "timestamp": 100,
            "product": "ASH_COATED_OSMIUM",
            "analysis_fair": 1.0,
            "mid": 1.0,
        }
    ]
    payload["fills"] = [
        {
            "day": 0,
            "timestamp": 100,
            "product": "ASH_COATED_OSMIUM",
            "side": "buy",
            "price": 1.0,
            "quantity": 1,
            "kind": "aggressive_visible",
            "exact": True,
            "source_trade_price": 1.0,
            "mid": 1.0,
            "reference_fair": 1.0,
            "best_bid": 1.0,
            "best_ask": 2.0,
            "markout_1": 1.0,
            "markout_5": 1.0,
            "analysis_fair": 1.0,
            "signed_edge_to_analysis_fair": 1.0,
        }
    ]
    return payload


def _comparison_payload(run_name: str, trader_name: str) -> dict:
    payload = _base_payload("comparison", run_name)
    payload["comparison"] = [
        {
            "trader": trader_name,
            "final_pnl": 240000.0,
            "gross_pnl_before_maf": 240000.0,
            "maf_cost": 0.0,
            "max_drawdown": 100.0,
            "fill_count": 625,
            "order_count": 89926,
            "limit_breaches": 0,
        }
    ]
    payload["comparisonDiagnostics"] = {
        "row_count": 1,
        "winner": trader_name,
        "winner_final_pnl": 240000.0,
        "scenario_count": 1,
        "maf_sensitive_rows": 0,
    }
    return payload


def _round2_payload(run_name: str) -> dict:
    payload = _base_payload("round2_scenarios", run_name)
    scenario_rows = [
        {
            "scenario": "access_base_maf_0",
            "trader": "plus_offset110",
            "round": 2,
            "final_pnl": 248278.0,
            "gross_pnl_before_maf": 248278.0,
            "maf_cost": 0.0,
            "maf_bid": 0.0,
            "contract_won": True,
            "extra_access_enabled": True,
            "expected_extra_quote_fraction": 0.1875,
            "marginal_access_pnl_before_maf": 559.0,
            "break_even_maf_vs_no_access": 559.0,
            "max_drawdown": 100.0,
            "fill_count": 627,
            "limit_breaches": 0,
        }
    ]
    payload["comparison"] = scenario_rows
    payload["comparisonDiagnostics"] = {
        "row_count": 1,
        "winner": "plus_offset110",
        "winner_final_pnl": 248278.0,
        "scenario_count": 1,
        "maf_sensitive_rows": 0,
    }
    payload["round2"] = {
        "scenarioRows": scenario_rows,
        "winnerRows": [
            {
                "scenario": "access_base_maf_0",
                "winner": "plus_offset110",
                "winner_final_pnl": 248278.0,
                "gap_to_second": None,
                "ranking_changed_vs_no_access": False,
            }
        ],
        "pairwiseRows": [],
        "mafSensitivityRows": scenario_rows,
        "assumptionRegistry": {"grounded": [], "configurable": [], "unknown": []},
    }
    return payload


def _source(name: str, payload: dict) -> WorkspaceSource:
    return WorkspaceSource(
        path=Path(name) / "dashboard.json",
        payload=payload,
        relative_path=f"{name}/dashboard.json",
    )


def test_workspace_assembly_records_promoted_and_shadowed_sections():
    assembly = assemble_workspace_payload(
        [
            _source("compare_primary", _comparison_payload("compare_primary", "primary")),
            _source("compare_secondary", _comparison_payload("compare_secondary", "secondary")),
            _source("round2_suite", _round2_payload("round2_suite")),
            _source("replay_bundle", _replay_payload("replay_bundle")),
        ],
        name="review_workspace",
    )

    workspace = assembly.payload["workspace"]

    assert assembly.present_sections == [
        "overview",
        "replay",
        "compare",
        "round2",
        "inspect",
        "osmium",
        "pepper",
        "alpha",
    ]
    assert "montecarlo" in assembly.missing_sections
    assert "calibration" in assembly.missing_sections
    assert workspace["integrity"]["status"] == "overlap"
    assert workspace["integrity"]["promotedBy"]["compare"] == "compare_primary/dashboard.json"
    assert workspace["integrity"]["promotedBy"]["round2"] == "round2_suite/dashboard.json"
    assert workspace["integrity"]["promotedBy"]["replay"] == "replay_bundle/dashboard.json"
    assert "compare_secondary/dashboard.json" in workspace["integrity"]["shadowedBy"]["compare"]
    assert "round2_suite/dashboard.json" in workspace["integrity"]["shadowedBy"]["compare"]

    compare_secondary = assembly.source_records[1]
    assert compare_secondary["promotedSections"] == []
    assert compare_secondary["shadowedSections"] == ["compare", "alpha"]
    assert "provenance only" in compare_secondary["note"].lower()

    round2_suite = assembly.source_records[2]
    assert "round2" in round2_suite["promotedSections"]
    assert "compare" in round2_suite["shadowedSections"]


def test_workspace_bundle_cli_builds_real_pack_into_temporary_output(tmp_path):
    output_dir = tmp_path / "workspace_bundle"
    source_dir = ROOT / "backtests" / "final_round2_study_pack"
    if not source_dir.is_dir():
        pytest.skip(
            "backtests/final_round2_study_pack is generated output and is not checked in; "
            "regenerate it to run this end-to-end workspace integration test."
        )

    main([
        "workspace-bundle",
        "--from-dir",
        str(source_dir),
        "--name",
        "final_round2_workspace",
        "--output-dir",
        str(output_dir),
    ])

    dashboard_path = output_dir / "dashboard.json"
    manifest_path = output_dir / "manifest.json"

    assert dashboard_path.is_file()
    assert manifest_path.is_file()

    payload = json.loads(dashboard_path.read_text(encoding="utf-8"))
    assert payload["type"] == "workspace"
    assert payload["workspace"]["name"] == "final_round2_workspace"
    assert len(payload["workspace"]["sources"]) == 4
    assert payload["workspace"]["integrity"]["status"] == "overlap"
    assert "compare" in payload["workspace"]["sections"]["present"]
    assert "round2" in payload["workspace"]["sections"]["present"]
    assert "alpha" in payload["workspace"]["sections"]["present"]
    assert "replay" in payload["workspace"]["sections"]["missing"]
    assert "montecarlo" in payload["workspace"]["sections"]["missing"]


def test_server_bundle_discovery_surfaces_workspace_metadata(tmp_path):
    output_dir = tmp_path / "workspace_bundle"
    write_workspace_bundle(
        [
            _source("compare_primary", _comparison_payload("compare_primary", "primary")),
            _source("replay_bundle", _replay_payload("replay_bundle")),
        ],
        output_dir,
        name="workspace_review",
    )

    bundles = _find_bundles(tmp_path)

    assert len(bundles) == 1
    assert bundles[0]["path"] == "workspace_bundle/dashboard.json"
    assert bundles[0]["type"] == "workspace"
    assert bundles[0]["workspaceName"] == "workspace_review"
    assert bundles[0]["workspaceSourceCount"] == 2
    assert "replay" in bundles[0]["workspaceSectionsPresent"]
    assert "compare" in bundles[0]["workspaceSectionsPresent"]
    assert "round2" in bundles[0]["workspaceSectionsMissing"]
