# Outputs

Result: every workflow writes a bundle directory built around `dashboard.json` and `manifest.json`.

Those two files are the stable review contract. CSV sidecars add convenience and exportability, but the dashboard is expected to work from the bundle payload itself.

## Bundle Contract

Every bundle is expected to contain:

- `dashboard.json`: canonical review payload
- `manifest.json`: lightweight metadata, file inventory, bundle stats, and provenance

The dashboard server uses `manifest.json` and `run_registry.jsonl` first so large bundles can be discovered without loading the full payload immediately.

## Bundle Types

| Bundle type | Main purpose | Typical extra files |
| --- | --- | --- |
| `replay` | One trader on historical data | `run_summary.csv`, `session_summary.csv`, `fills.csv`, `behaviour_summary.csv` |
| `comparison` | Multiple traders under one replay assumption | `comparison.csv` |
| `monte_carlo` | Distribution and path-band robustness checks | `run_summary.csv`, `session_summary.csv`, `fills.csv`, `behaviour_summary.csv` |
| `calibration` | Replay-versus-live calibration grid | `calibration_grid.csv`, `empirical_profile/` |
| `optimization` | Variant ranking by replay plus Monte Carlo score | `optimization.csv` |
| `scenario_compare` | Ranking under calibrated stress scenarios | `scenario_results.csv`, `scenario_winners.csv`, `robustness_ranking.csv`, `scenario_pairwise_mc.csv` |
| `round2_scenarios` | Ranking under MAF and extra-access assumptions | `round2_scenarios.csv`, `round2_winners.csv`, `round2_pairwise_mc.csv`, `round2_maf_sensitivity.csv` |

## Light Versus Full Output

All CLI workflows default to the `light` profile.

### Light profile

Light mode keeps:

- exact summary rows
- exact fill rows
- compact replay path data inside `dashboard.json`
- compact order-intent data instead of raw order rows
- Monte Carlo sample previews
- all-session Monte Carlo path bands

Light mode omits by default:

- raw submitted orders
- chart-series CSV sidecars
- duplicated Monte Carlo sample-path files
- per-session Monte Carlo manifests
- child bundles for aggregate workflows

### Full profile

Use `--output-profile full` when you explicitly want debug-heavy evidence:

```bash
python -m prosperity_backtester replay strategies/trader.py --days 0 --output-profile full
python -m prosperity_backtester monte-carlo strategies/trader.py --sessions 128 --sample-sessions 8 --output-profile full
```

Full mode can still be trimmed:

```bash
python -m prosperity_backtester monte-carlo strategies/trader.py --sessions 128 --sample-sessions 8 --output-profile full --no-orders --no-sample-path-files --no-session-manifests
```

## Optional Heavy Extras

The heavy extras are explicit:

- `orders.csv`
- `inventory_series.csv`
- `pnl_series.csv`
- `fair_value_series.csv`
- `behaviour_series.csv`
- `order_intent.csv`
- `sample_paths/`
- `sessions/`

These appear only when the selected output options require them.

## Child Bundles

Aggregate workflows such as comparison, optimisation, scenario comparison, and Round 2 scenarios do not keep child bundles unless requested.

Enable them deliberately:

```bash
python -m prosperity_backtester compare strategies/trader.py strategies/starter.py --output-profile full --save-child-bundles
```

## Compact Storage Notes

Some large retained payload sections may be stored in the internal `row_table_v1` encoding inside `dashboard.json`. This is expected.

The React dashboard expands those sections on load, so JSON remains the canonical contract.

Common compact sections:

- Monte Carlo `sessions`
- Monte Carlo sample-run series
- Monte Carlo path-band leaves

## Manifest And Registry

`manifest.json` records:

- run type and run name
- creation time
- output profile
- bundle byte and file counts
- canonical, sidecar, and debug file lists
- provenance such as argv, git metadata, backend choice, worker count, and runtime timings

Each parent output root also receives `run_registry.jsonl`. That registry lets the server discover recent bundles cheaply.

## Retention

When a workflow uses the default auto-named output path under `backtests/`, the CLI keeps the newest `30` timestamped runs by default.

Change the retention count:

```bash
python -m prosperity_backtester replay strategies/trader.py --keep-runs 10
```

Prune explicitly:

```bash
python -m prosperity_backtester clean --keep 30
```

Custom `--output-dir` paths and manually named directories are never pruned automatically.
