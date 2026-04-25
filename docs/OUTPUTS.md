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

`optionDiagnostics` contains:

- top-level `underlying`, `final_tte_days`, and `surface_fit_vouchers`
- one `days[]` entry per analysed day
- per-voucher summaries for strike, average mid, spread, depth, intrinsic, time value, moneyness, IV distribution, fitted IV, model fair, residual distribution, residual z-score scale, delta, gamma, vega, move beta, fit inclusion, warnings, and observation counts
- compact `chain_samples[]` rows with timestamp, underlying mid, observed voucher mid, intrinsic, time value, moneyness, implied IV, fitted IV, model fair, residual, residual z-score, spread, depth, delta, gamma, vega, and fit source
- `surface_fit_policy` and `surface_fit_quality` diagnostics explaining included strikes and fallback use

These fields are diagnostic and synthetic-calibration support. Historical replay still uses observed books and observed mids.

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
| `round3_verification` | Round 3 trustworthiness sweep | `verification_report.json`, `verification_report.md`, plus child run directories for each subprocess command |

## Round 3 verification report

`verify-round3` writes:

- `verification_report.json`: structured payload with provenance, summary, per-check results, per-command results, and caveats
- `verification_report.md`: human-readable summary with a check table and a performance/RSS/output-size table
- `manifest.json`: lightweight type/status alias for discoverability

`verification_report.json` schema highlights:

- `provenance.git.commit`, `git.dirty`, `git.branch`
- `provenance.runtime.python_version`, `runtime.executable`
- `mode`: `full` or `quick`; quick mode is `--skip-heavy-mc`
- `psutil_available`: `true` when peak RSS is captured, otherwise the `caveats[]` records the gap
- `summary.overall_status`: `"pass"` or `"fail"`
- `checks[].name` and `checks[].status` for each in-process correctness gate (`data_validation`, `option_diagnostics`, `mc_coherence`, replay fixtures, `dashboard_payload`, `mc_seed_determinism`)
- `commands[]` records per subprocess: `name`, `command`, `wall_seconds`, `peak_rss_mb_process`, `peak_rss_mb_tree`, `peak_child_process_count`, `output_size_bytes`, `output_file_count`, `status`, `rss_capture_method`, and `rss_caveats`. Captured stdout files, including `inspect_report.json`, are included in output-size accounting.
- `caveats[]`: explicit notes about passive-fill approximation, classic-only Round 3 MC, and missing RSS capture when applicable

Each subprocess writes its bundle into a sibling directory under the verification output (for example `replay_noop_days012/dashboard.json`), so the harness output is self-contained and replayable.

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

Fill rows may include passive-fill fidelity fields:

- `kind=aggressive_visible` and `exact=true` for visible-book aggressive fills
- `kind=passive_approx` and `exact=false` for trade-print passive fills
- `passive_match_type=same_price` for same-price queue assumptions
- `passive_match_type=worse_price` for prints through the resting order price
- `approximation_reason` with the local assumption used
