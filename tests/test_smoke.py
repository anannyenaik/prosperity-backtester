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
        (
            '{"run_type":"replay","run_name":"large_run","created_at":"2026-04-18T00:00:00+00:00",'
            '"summary":{"final_pnl":123.45},"output_profile":{"profile":"light"},'
            '"bundle_stats":{"total_size_bytes":5100123,"file_count":2}}'
        ),
        encoding='utf-8',
    )

    bundles = _find_bundles(tmp_path)

    assert len(bundles) == 1
    assert bundles[0] == {
        'path': 'large_run/dashboard.json',
        'name': 'large_run',
        'runName': 'large_run',
        'type': 'replay',
        'profile': 'light',
        'finalPnl': 123.45,
        'createdAt': '2026-04-18T00:00:00+00:00',
        'sizeBytes': 5_100_123,
        'dashboardSizeBytes': 5_100_000,
        'fileCount': 2,
        'workflowTier': None,
        'engineBackend': None,
        'monteCarloBackend': None,
        'parallelism': None,
        'workerCount': None,
        'gitCommit': None,
        'gitDirty': None,
        'source': 'manifest',
    }


def test_server_bundle_discovery_includes_explicit_child_bundles(tmp_path):
    parent = tmp_path / 'parent_bundle'
    child = parent / 'variant_a' / 'replay'
    child.mkdir(parents=True)
    parent.mkdir(exist_ok=True)
    (parent / 'dashboard.json').write_text('{}', encoding='utf-8')
    (parent / 'manifest.json').write_text('{"run_type":"comparison","run_name":"parent_bundle","created_at":"2026-04-18T00:00:00+00:00"}', encoding='utf-8')
    (child / 'dashboard.json').write_text('{}', encoding='utf-8')
    (child / 'manifest.json').write_text('{"run_type":"replay","run_name":"variant_a_replay","created_at":"2026-04-19T00:00:00+00:00"}', encoding='utf-8')

    bundles = _find_bundles(tmp_path)

    assert [bundle['path'] for bundle in bundles] == [
        'parent_bundle/variant_a/replay/dashboard.json',
        'parent_bundle/dashboard.json',
    ]


def test_server_bundle_discovery_skips_internal_warmup_bundles(tmp_path):
    warmup = tmp_path / '_warmup_current'
    real = tmp_path / '2026-04-23_12-00-00_replay_review'
    warmup.mkdir()
    real.mkdir()
    (warmup / 'dashboard.json').write_text('{}', encoding='utf-8')
    (warmup / 'manifest.json').write_text(
        '{"run_type":"replay","run_name":"warmup","created_at":"2026-04-23T12:05:00+00:00"}',
        encoding='utf-8',
    )
    (real / 'dashboard.json').write_text('{}', encoding='utf-8')
    (real / 'manifest.json').write_text(
        '{"run_type":"replay","run_name":"review","created_at":"2026-04-23T12:00:00+00:00"}',
        encoding='utf-8',
    )

    bundles = _find_bundles(tmp_path)

    assert [bundle['path'] for bundle in bundles] == [
        '2026-04-23_12-00-00_replay_review/dashboard.json',
    ]


def test_server_bundle_discovery_uses_registry_metadata_when_manifest_is_minimal(tmp_path):
    backtests = tmp_path / 'backtests'
    run_dir = backtests / '2026-04-21_12-00-00_replay_tiny'
    run_dir.mkdir(parents=True)
    (run_dir / 'dashboard.json').write_text('{}', encoding='utf-8')
    (run_dir / 'manifest.json').write_text('{"run_type":"replay","run_name":"tiny","created_at":"2026-04-21T12:00:00+00:00"}', encoding='utf-8')
    (backtests / 'run_registry.jsonl').write_text(
        json.dumps({
            'run_name': 'tiny',
            'run_type': 'replay',
            'created_at': '2026-04-21T12:00:00+00:00',
            'workflow_tier': 'fast',
            'engine_backend': 'python',
            'parallelism': 'single_process',
            'worker_count': 1,
            'git_commit': 'abc123def456',
            'git_dirty': True,
            'output_profile': 'light',
            'final_pnl': 12.5,
            'dashboard_json': str((run_dir / 'dashboard.json').resolve()),
        }) + '\n',
        encoding='utf-8',
    )

    bundles = _find_bundles(tmp_path)

    assert len(bundles) == 1
    bundle = bundles[0]
    assert bundle['path'] == 'backtests/2026-04-21_12-00-00_replay_tiny/dashboard.json'
    assert bundle['workflowTier'] == 'fast'
    assert bundle['engineBackend'] == 'python'
    assert bundle['monteCarloBackend'] is None
    assert bundle['parallelism'] == 'single_process'
    assert bundle['workerCount'] == 1
    assert bundle['gitCommit'] == 'abc123def456'
    assert bundle['gitDirty'] is True
    assert bundle['profile'] == 'light'
    assert bundle['finalPnl'] == 12.5


def test_server_bundle_discovery_skips_registry_seeded_warmup_bundles(tmp_path):
    backtests = tmp_path / 'backtests'
    warmup_dir = backtests / '_warmup_current'
    review_dir = backtests / '2026-04-23_12-00-00_replay_review'
    warmup_dir.mkdir(parents=True)
    review_dir.mkdir(parents=True)
    (warmup_dir / 'dashboard.json').write_text('{}', encoding='utf-8')
    (review_dir / 'dashboard.json').write_text('{}', encoding='utf-8')
    (backtests / 'run_registry.jsonl').write_text(
        '\n'.join([
            json.dumps({
                'run_name': 'warmup',
                'run_type': 'replay',
                'created_at': '2026-04-23T12:05:00+00:00',
                'dashboard_json': str((warmup_dir / 'dashboard.json').resolve()),
            }),
            json.dumps({
                'run_name': 'review',
                'run_type': 'replay',
                'created_at': '2026-04-23T12:00:00+00:00',
                'dashboard_json': str((review_dir / 'dashboard.json').resolve()),
            }),
        ]) + '\n',
        encoding='utf-8',
    )

    bundles = _find_bundles(tmp_path)

    assert [bundle['path'] for bundle in bundles] == [
        'backtests/2026-04-23_12-00-00_replay_review/dashboard.json',
    ]


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
