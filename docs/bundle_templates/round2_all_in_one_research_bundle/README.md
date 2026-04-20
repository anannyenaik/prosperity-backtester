# round2_all_in_one_research_bundle

All-in-one Round 2 research output for script comparison and upload decisions.

## Contents

- `replay_<strategy>/`: full tick-level run for one strategy. Use for total PnL, per-product PnL, realised/unrealised/MTM, fills, orders, inventory, drawdown, cap usage, behaviour and markouts.
- `compare/`: direct head-to-head table under one fixed assumption. Use for the first-pass ranking.
- `round2_scenarios/`: no-access, extra-access and MAF decision grid. Use `round2_winners.csv` for winners and `round2_maf_sensitivity.csv` for fee sensitivity.
- `monte_carlo_<strategy>/`: targeted robustness check. Use mean, median and P05 to judge typical performance and downside.
- `calibration/` optional: live-export fill calibration when export data is available.

## Dashboard

Load the bundle through the local dashboard server. Replay bundles populate Overview, Replay, product dives, Inspect and behaviour views. Compare bundles populate Comparison. Scenario bundles populate Round 2 and aggregate tables; replay-only tabs can be empty because scenario bundles do not contain one full tick path. Monte Carlo bundles populate Monte Carlo. Calibration bundles populate Calibration.

## Decision Rule

Prefer the script that wins across scenarios, has stronger mean/median Monte Carlo performance, tolerable P05 downside, clean limit behaviour and explainable per-product PnL. Treat local results as ranking evidence, not an exact website forecast. Round 2 MAF cutoff, extra-access usefulness, passive fills and queue priority remain approximate locally.
