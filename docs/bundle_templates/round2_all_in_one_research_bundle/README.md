# Round 2 All-In-One Research Bundle

Shared Round 2 output folder for script comparison and upload decisions.

## Expected Contents

- `replay_<strategy>/`: optional full tick-level replay bundle for one script.
- `compare/`: direct head-to-head comparison under one fixed assumption.
- `round2_scenarios/`: no-access, extra-access and MAF scenario grid.
- `monte_carlo_<strategy>/`: optional targeted robustness bundle for a leading script.
- `calibration/` optional: live-export fill calibration where export data exists.

## Dashboard Use

Serve the repository root and load the bundle outputs through the dashboard.

Replay bundles populate Overview, Replay, product dives and Inspect. Comparison bundles populate Comparison. Round 2 scenario bundles populate Round 2 and aggregate ranking tables. Monte Carlo bundles populate Monte Carlo with all-session path bands. Calibration bundles populate Calibration.

## Decision Rule

Prefer the script that wins across scenarios, has stronger mean and median Monte Carlo performance, tolerable P05 downside, clean limit behaviour and explainable per-product PnL.

Treat local results as ranking evidence. MAF cutoff, extra-access usefulness, passive fills and queue priority remain approximate locally.
