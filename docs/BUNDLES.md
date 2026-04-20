# Bundle Guide

Every workflow writes a `dashboard.json` payload and supporting files. The dashboard uses the bundle `type` field first, then falls back to payload sections when older bundles are loaded.

Bundles default to the light output profile. Light mode keeps dashboard-ready evidence and avoids duplicate debug artefacts. Full mode is available with `--output-profile full`.

## Replay

Purpose: inspect one trader at tick level.

Key files:

- `dashboard.json`
- `manifest.json`
- `run_summary.csv`
- `session_summary.csv`
- `fills.csv`
- `inventory_series.csv`
- `pnl_series.csv`
- `fair_value_series.csv`
- `behaviour_summary.csv`
- `behaviour_series.csv`

Full replay bundles also include `orders.csv`.

Dashboard tabs: Overview, Alpha Lab, Replay, Inspect, Osmium, Pepper, Comparison when two replay bundles are loaded.

## Comparison

Purpose: rank multiple traders under one fixed replay assumption.

Key file:

- `comparison.csv`

Dashboard tabs: Overview, Alpha Lab, Comparison.

## Monte Carlo

Purpose: robustness distribution and sampled path review.

Light Monte Carlo bundles keep session distribution rows and sampled runs inside `dashboard.json`. Full mode also writes:

- `sample_paths/`
- `sessions/`

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
- Monte Carlo bundles contain distribution and sample-path data, not a top-level replay summary.
- Calibration bundles contain grid candidates, not orders or fills for one final replay.

Unavailable tabs should show a compatibility message rather than zero-valued metrics.
