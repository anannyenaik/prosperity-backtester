# Output Storage

Generated bundles are designed to be useful in the dashboard without quietly growing into very large local archives.

## Default Light Profile

All CLI workflows default to `--output-profile light`.

Light keeps exactly:

- replay summary metrics, per-product PnL, drawdown, fill count, order count and limit breaches
- `fills.csv` and dashboard `fills`
- session, comparison, optimisation, calibration, scenario and Round 2 aggregate rows
- Monte Carlo final distribution statistics across every session

Light keeps compactly:

- `inventorySeries`, `pnlSeries`, `fairValueSeries` and `behaviourSeries` in `dashboard.json`
- `orderIntent` in `dashboard.json`
- Monte Carlo sampled runs in `dashboard.json`
- Monte Carlo all-session path bands in `dashboard.json`

Light omits by default:

- raw submitted order rows
- chart-series CSV sidecars such as `pnl_series.csv` and `fair_value_series.csv`
- duplicated Monte Carlo `sample_paths/`
- per-session Monte Carlo manifests
- child replay and Monte Carlo bundles inside aggregate workflows

`dashboard.json` is the canonical source for compact chart paths in light mode. Keep using `fills.csv`, summary CSVs and aggregate result tables for scripts that need exact tabular outputs.

## Light Path Fidelity

Light path compaction is event-aware rather than even-sampled. It preserves first and last points, day boundaries, fill timestamps with immediate neighbours, drawdown peak/trough points, regime-change markers where available, and bucket extrema for inventory, PnL, fair-value and behaviour metrics.

Rows representing an omitted interval include bucket fields such as `*_bucket_min`, `*_bucket_max`, `*_bucket_last`, `bucket_start_timestamp`, `bucket_end_timestamp` and `bucket_count`. This keeps charts faithful without retaining every tick.

`orderIntent` replaces raw order rows in light mode. For each timestamp and product it keeps best submitted bid, best submitted ask, signed submitted quantity, aggressive and passive submitted quantity, quote width, row count, quote update count and one-sided quote flags.

## Monte Carlo Path Bands

Monte Carlo final distribution metrics are exact across all sessions.

Monte Carlo path bands are computed from every session, not from `sample_sessions`. Each session returns compact path metrics for:

- `analysisFair`
- `mid`
- `inventory`
- `pnl`

The dashboard stores exact quantiles across sessions at retained bucket endpoints. If a path is bucketed, omitted ticks contribute exact per-session min/max envelopes before the cross-session envelope is written. This means the time axis may be approximate in light mode, but the shown endpoint quantiles and retained envelopes are computed from all sessions.

Sampled runs remain qualitative examples for inspecting individual paths. They are not used as the population for path bands.

## Full Profile

Use `--output-profile full` for a debugging session that needs raw rows or full-resolution paths:

```bash
python -m prosperity_backtester replay strategies/trader.py --days 0 --output-profile full
python -m prosperity_backtester monte-carlo strategies/trader.py --sessions 512 --sample-sessions 32 --output-profile full
```

Full mode keeps raw submitted order rows, full chart-series CSV sidecars, `orders.csv`, `order_intent.csv`, Monte Carlo `sample_paths/` and per-session manifests for sampled runs.

Full mode does not enable child bundles by itself. Use `--save-child-bundles` on aggregate commands when you explicitly want per-variant or per-scenario child replay and Monte Carlo bundles:

```bash
python -m prosperity_backtester compare strategies/trader.py strategies/starter.py --output-profile full --save-child-bundles
```

JSON remains compact by default in both light and full. Use `--pretty-json` or config `pretty_json: true` only when human-readable JSON is worth the extra bytes.

## Sidecars

Light replay bundles write:

- `dashboard.json`
- `manifest.json`
- `run_summary.csv`
- `session_summary.csv`
- `fills.csv`
- `behaviour_summary.csv`

Full mode or `--series-sidecars` additionally writes:

- `inventory_series.csv`
- `pnl_series.csv`
- `fair_value_series.csv`
- `behaviour_series.csv`
- `order_intent.csv`

Full replay also writes `orders.csv`.

## Config Controls

Config files may set:

- `output_profile`: `light` or `full`
- `max_series_rows_per_product`: default `1000` in light mode, `0` means no compaction
- `max_mc_path_rows_per_product`: default `800` in light mode, `0` means every Monte Carlo timestamp
- `include_orders`: write submitted order rows
- `write_series_csvs` or `series_sidecars`: write chart-series CSV sidecars
- `write_sample_path_files`: write Monte Carlo `sample_paths/`
- `write_session_manifests`: write one manifest per Monte Carlo session
- `save_child_bundles` or `write_child_bundles`: keep child bundles under aggregate runs
- `pretty_json`: write indented JSON
- `compact_json`: force compact JSON

CLI `--output-profile`, `--series-sidecars`, `--pretty-json` and `--save-child-bundles` override config output policy for the run.

## Retention

When a command uses the default `backtests/<timestamp>_<label>` output directory, the CLI keeps the newest 30 timestamped runs and prunes older timestamped run directories. Sorting uses the timestamp in the folder name. If that cannot be parsed, `manifest.json` `created_at` is used as a fallback.

Adjust the default:

```bash
python -m prosperity_backtester replay strategies/trader.py --keep-runs 10
```

Prune explicitly:

```bash
python -m prosperity_backtester clean --dir backtests --keep 30
```

`--keep-runs` and `clean --keep` must be at least `1`. Custom `--output-dir` paths and manually named directories are never pruned automatically.
