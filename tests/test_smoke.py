from __future__ import annotations

import json
import os
from pathlib import Path

from prosperity_backtester.dataset import load_round1_dataset
from prosperity_backtester.live_export import load_live_export
from prosperity_backtester.server import _find_bundles
from prosperity_backtester.storage import prune_old_auto_runs

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


def test_prune_old_auto_runs_keeps_named_directories(tmp_path):
    old_run = tmp_path / '2026-04-18_00-00-00_replay'
    new_run = tmp_path / '2026-04-19_00-00-00_replay'
    manual = tmp_path / 'round2_all_in_one_research_bundle'
    for path in (old_run, new_run, manual):
        path.mkdir()
        (path / 'dashboard.json').write_text('{}', encoding='utf-8')
    os.utime(old_run, (1, 1))
    os.utime(new_run, (2, 2))
    (tmp_path / 'run_registry.jsonl').write_text(
        '\n'.join([
            '{"output_dir":"' + str(old_run).replace('\\', '\\\\') + '"}',
            '{"output_dir":"' + str(new_run).replace('\\', '\\\\') + '"}',
            '{"output_dir":"' + str(manual).replace('\\', '\\\\') + '"}',
        ]) + '\n',
        encoding='utf-8',
    )

    removed = prune_old_auto_runs(tmp_path, keep=1)

    assert removed == [old_run.resolve()]
    assert not old_run.exists()
    assert new_run.exists()
    assert manual.exists()
    registry = [
        json.loads(line)["output_dir"]
        for line in (tmp_path / 'run_registry.jsonl').read_text(encoding='utf-8').splitlines()
    ]
    assert str(old_run) not in registry
    assert str(new_run) in registry
    assert str(manual) in registry
