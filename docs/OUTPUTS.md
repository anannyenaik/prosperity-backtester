# Outputs

Result: every workflow writes a bundle directory built around `dashboard.json` and `manifest.json`.

## Bundle contract

Every bundle is expected to contain:

- `dashboard.json`: canonical review payload
- `manifest.json`: lightweight metadata, file inventory, bundle stats, provenance, and source-data references when available

## Round-aware metadata

The canonical payload now carries round-aware fields:

- `meta.round`
- `meta.roundName`
- `products`
- `productMetadata`
- `positionLimits`
- `roundSpec`
- `datasetReports`
- `validation`

Round 3 replay bundles may also include:

- `optionDiagnostics`
- Round 3 `summary.option_diagnostics`

Round 3 manifests may additionally carry:

- `tte_days_by_historical_day`
- `final_tte_days`
- `source_data_manifest` if a tracked `data/<round>/manifest.json` exists

## Bundle types

| Bundle type | Main purpose | Typical extra files |
| --- | --- | --- |
| `replay` | One trader on historical data | `run_summary.csv`, `session_summary.csv`, `fills.csv`, `behaviour_summary.csv` |
| `comparison` | Multiple traders under one replay assumption | `comparison.csv` |
| `monte_carlo` | Distribution and path-band robustness checks | `run_summary.csv`, `session_summary.csv`, `fills.csv`, `behaviour_summary.csv` |
| `calibration` | Replay-versus-live calibration grid | `calibration_grid.csv`, `empirical_profile/` |
| `optimization` | Variant ranking by replay plus Monte Carlo score | `optimization.csv` |
| `scenario_compare` | Ranking under configured stress scenarios | `scenario_results.csv`, `scenario_winners.csv`, `robustness_ranking.csv`, `scenario_pairwise_mc.csv` |
| `round2_scenarios` | Ranking under MAF and extra-access assumptions | `round2_scenarios.csv`, `round2_winners.csv`, `round2_pairwise_mc.csv`, `round2_maf_sensitivity.csv` |

## Light versus full output

All CLI workflows default to the `light` profile.

Light mode keeps:

- exact summary rows
- exact fill rows
- compact replay path data inside `dashboard.json`
- compact order-intent data instead of raw submitted orders
- Monte Carlo sample previews
- all-session Monte Carlo path bands

Full mode can additionally keep:

- raw submitted orders
- chart-series CSV sidecars
- sample path files
- per-session manifests
- child bundles for aggregate workflows

## Manifest notes

`manifest.json` records:

- run type and run name
- round number and round name when available
- products, product metadata, and position limits for replay and Monte Carlo bundles
- TTE mappings for rounds that have them
- creation time
- output profile
- bundle byte and file counts
- canonical, sidecar, and debug file lists
- provenance such as argv, git metadata, backend choice, worker count, and runtime timings
- source data manifest metadata when a tracked data manifest is available
