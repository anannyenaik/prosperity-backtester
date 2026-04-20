# Output Storage

Generated bundles are designed to be useful in the dashboard without quietly growing into very large local archives.

## Default Light Profile

All CLI workflows default to `--output-profile light`.

Light bundles keep:

- `dashboard.json`
- `manifest.json`
- summary CSVs
- fills
- downsampled inventory, PnL, fair-value and behaviour series
- aggregate comparison, optimisation, calibration, scenario and Round 2 rows
- Monte Carlo distribution rows and sampled runs inside `dashboard.json`

Light bundles omit:

- submitted order rows
- per-session Monte Carlo manifest files
- duplicated `sample_paths/` JSON files
- child replay and Monte Carlo bundles inside compare, sweep, optimisation, calibration and scenario workflows

The dashboard remains useful in light mode. Overview, Replay, product dives, Monte Carlo, Comparison, Calibration, Round 2 and Alpha Lab still have the fields they need. Inspect mode explains when submitted orders were omitted.

## Full Profile

Use `--output-profile full` when you need exact order rows, full-resolution series or separate sampled path files for a debugging session:

```bash
python -m prosperity_backtester replay strategies/trader.py --days 0 --output-profile full
python -m prosperity_backtester monte-carlo strategies/trader.py --sessions 512 --sample-sessions 32 --output-profile full
```

Full mode writes all rows, pretty-printed JSON, `orders.csv`, Monte Carlo `sample_paths/`, per-session manifests and child bundles for aggregate workflows.

## Config Controls

Config files may set:

- `output_profile`: `light` or `full`
- `max_series_rows_per_product`: default `1000` in light mode, `0` means no downsampling
- `include_orders`: write submitted order rows
- `write_sample_path_files`: write Monte Carlo `sample_paths/`
- `write_session_manifests`: write one manifest per Monte Carlo session
- `save_child_bundles`: keep child replay and Monte Carlo bundles under aggregate runs
- `compact_json`: compact or pretty-print JSON

CLI `--output-profile` overrides a config profile. `--save-child-bundles` can be used with aggregate commands when child bundles are needed without enabling every full-mode artefact.

## Retention

When a command uses the default `backtests/<timestamp>_<label>` output directory, the CLI keeps the newest 30 timestamped runs and prunes older timestamped run directories. Custom `--output-dir` paths are never pruned automatically.

Adjust the default:

```bash
python -m prosperity_backtester replay strategies/trader.py --keep-runs 10
```

Prune explicitly:

```bash
python -m prosperity_backtester clean --dir backtests --keep 30
```

Only timestamped auto-run directories are eligible for pruning.
