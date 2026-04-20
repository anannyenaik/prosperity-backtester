from __future__ import annotations

from pathlib import Path

from prosperity_backtester.dataset import load_round1_dataset
from prosperity_backtester.live_export import load_live_export
from prosperity_backtester.server import _find_bundles

ROOT = Path(__file__).resolve().parent.parent


def test_round1_files_present():
    dataset = load_round1_dataset(ROOT / 'data' / 'round1', days=(-2, -1, 0))
    assert set(dataset.keys()) == {-2, -1, 0}


def test_live_export_loader_reads_metadata():
    export = load_live_export(ROOT / 'live_exports' / '259168' / '259168.json')
    assert export.profit is not None
    assert export.graph_points
    assert export.final_positions
    assert export.own_trade_history
    assert len(export.own_trade_history) < len(export.trade_history)


def test_r1bt_compatibility_imports_still_work():
    from r1bt.datamodel import Order
    from prosperity_backtester.datamodel import Order as PrimaryOrder

    assert Order is PrimaryOrder


def test_server_bundle_discovery_uses_manifest_metadata(tmp_path):
    run_dir = tmp_path / 'large_run'
    run_dir.mkdir()
    (run_dir / 'dashboard.json').write_text('x' * 5_100_000, encoding='utf-8')
    (run_dir / 'manifest.json').write_text(
        '{"run_type":"replay","run_name":"large_run","created_at":"2026-04-18T00:00:00+00:00","summary":{"final_pnl":123.45}}',
        encoding='utf-8',
    )

    bundles = _find_bundles(tmp_path)

    assert bundles == [{
        'path': 'large_run/dashboard.json',
        'name': 'large_run',
        'runName': 'large_run',
        'type': 'replay',
        'finalPnl': 123.45,
        'createdAt': '2026-04-18T00:00:00+00:00',
        'sizeBytes': 5_100_000,
    }]
