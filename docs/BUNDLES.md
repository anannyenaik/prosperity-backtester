# Bundle Guide

Every workflow writes a `dashboard.json` payload and supporting files. The dashboard uses the bundle `type` field first, then falls back to payload sections when older bundles are loaded.

Bundles default to the light output profile. Light mode keeps dashboard-ready evidence, exact fills, compact quote intent and all-session Monte Carlo path bands while avoiding duplicate debug artefacts. Full mode is available with `--output-profile full`.

Every bundle manifest now makes the intended shape explicit:

- `canonical_files`: files teammates should inspect first
- `sidecar_files`: optional chart/export helpers
- `debug_files`: explicit heavy extras
- `bundle_stats`: total bytes and file count
- `data_contract`: exact, compact, bucketed, raw or qualitative evidence notes

## Replay

Purpose: inspect one trader at tick level.

Key files:

- `dashboard.json`
- `manifest.json`
- `run_summary.csv`
- `session_summary.csv`
- `fills.csv`
- `behaviour_summary.csv`

Light replay paths live in `dashboard.json` as compact `inventorySeries`, `pnlSeries`, `fairValueSeries`, `behaviourSeries` and `orderIntent`. Full mode or `--series-sidecars` also writes the chart-series CSV sidecars and `order_intent.csv`. Full replay bundles also include raw `orders.csv`.

Dashboard tabs: Overview, Alpha Lab, Replay, Inspect, Osmium, Pepper, Comparison when two replay bundles are loaded.

## Comparison

Purpose: rank multiple traders under one fixed replay assumption.

Key file:

- `comparison.csv`

Dashboard tabs: Overview, Alpha Lab, Comparison.

## Monte Carlo

Purpose: robustness distribution, all-session path bands and sampled path review.

Light Monte Carlo bundles keep session distribution rows, all-session `pathBands` and sampled runs inside `dashboard.json`. `pathBands` cover `analysisFair`, `mid`, `inventory` and `pnl`. Quantiles are exact across all sessions at retained bucket endpoints; omitted ticks contribute min/max envelopes. Full mode also writes:

- `sample_paths/`
- `sessions/`

Saved sample runs remain qualitative examples. They are not the source population for final distribution metrics or all-session path bands.

Dashboard tabs: Overview, Alpha Lab, Monte Carlo.

## Calibration

Purpose: compare replay outputs against live-export evidence.

Additional files:

- `calibration_grid.csv`
- `empirical_profile/empirical_fill_profile.json`
- `empirical_profile/empirical_fill_rows.csv`
- `empirical_profile/empirical_fill_summary.csv`

Dashboard tabs: Overview, Calibration.

## Optimisation

Purpose: rank parameter variants by replay and Monte Carlo score.

Additional file:

- `optimization.csv`

Dashboard tabs: Overview, Optimisation.

## Calibrated Scenario Compare

Purpose: compare scripts across baseline, stress, crash, fill-quality and slippage scenarios.

Additional files:

- `scenario_results.csv`
- `scenario_winners.csv`
- `robustness_ranking.csv`
- `scenario_pairwise_mc.csv`

Dashboard tabs: Overview, Alpha Lab, Comparison.

## Round 2 Scenarios

Purpose: compare scripts across no-access, extra-access and MAF assumptions.

Additional files:

- `round2_scenarios.csv`
- `round2_winners.csv`
- `round2_pairwise_mc.csv`
- `round2_maf_sensitivity.csv`

Dashboard tabs: Overview, Alpha Lab, Round 2, Comparison.

## Interpreting Compatibility Messages

Some tabs are intentionally unavailable for some bundle types. For example:

- Round 2 scenario bundles contain aggregate rows, not full tick-level replay paths.
- Monte Carlo bundles contain distribution, all-session path-band and sample-path data, not a top-level replay summary.
- Calibration bundles contain grid candidates, not orders or fills for one final replay.

Unavailable tabs should show a compatibility message rather than zero-valued metrics.

## Child Bundles

When `--save-child-bundles` is enabled on aggregate workflows, the dashboard server now discovers those nested child bundles individually instead of hiding them behind the parent aggregate bundle.
