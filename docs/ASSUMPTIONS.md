# Assumptions And Approximation Boundaries

The platform is designed for robust local decisions. It separates exact mechanics from configurable assumptions so strategy rankings are not mistaken for official website PnL.

## Exact Relative To Local Inputs

- CSV schema validation.
- Timestamp ordering and product presence checks.
- Visible-book aggressive fills.
- Trader state persistence through `traderData`.
- Own-trade hand-off between ticks.
- Cash, inventory, realised, unrealised and MTM accounting.
- Deterministic replay over provided timestamps.
- Synthetic latent fair inside Monte Carlo sessions.

## Approximate

- Passive queue position.
- Same-price queue share.
- Missed passive fills.
- Adverse-selection penalties.
- Size-dependent slippage.
- Latency-like delayed action effects.
- Historical `analysis_fair`.
- Synthetic market generation.
- Calibration and optimisation scores.

## Fair Value

Monte Carlo `analysis_fair` is the latent fair path used by the simulator.

Historical replay `analysis_fair` is an inferred diagnostic proxy from market structure. It is useful for markout and placement analysis, but it is not an official hidden fair value.

## Live-Export Calibration

Calibration compares replay output with fields available in a live export:

- total profit
- PnL path RMSE
- per-product PnL where available
- final position mismatch
- inventory-path mismatch
- fill count and fill quantity mismatch
- passive/aggressive fill mismatch
- activity timing mismatch

Only `tradeHistory` rows where `SUBMISSION` is buyer or seller are treated as own fills.

Calibration cannot reconstruct rejected passive orders, exact queue priority or hidden website matching. Treat the best calibration candidate as a local setting, not as proof of exact website accuracy.

## Empirical Fill Profiles

Empirical fill-profile derivation uses realised live fills and saves:

- product
- side
- quantity
- visible spread
- touch distance
- inferred passive/aggressive label
- liquidity regime

The following remain configurable assumptions:

- passive fill probability
- same-price queue share
- rejected passive order rate
- size slippage curve
- passive and aggressive adverse-selection ticks

## Scenario Analysis

Scenario outputs are decision tools. They are useful for asking:

- whether a script still wins under conservative fills
- whether ranking changes under wider spreads or thinner depth
- whether downside is acceptable under crash or slippage stress
- whether an observed gain is larger than live-vs-sim mismatch

Small edges should survive multiple scenario families before they are trusted.

## Round 2 MAF And Extra Access

Grounded from the challenge statement:

- Round 2 trades `ASH_COATED_OSMIUM` and `INTARIAN_PEPPER_ROOT`.
- A Market Access Fee may grant access to an extra 25% of quotes.
- Only the top 50% of total MAF bids get the contract.
- Losing bids do not pay and do not get extra quote access.

Configurable locally:

- whether the contract is assumed won
- MAF bid deducted from net PnL when the contract is won
- deterministic or stochastic access
- access quality
- visible book volume uplift
- passive fill-rate uplift
- missed-fill reduction
- fill opportunity volume uplift

Unknown website-only mechanics:

- exact extra-quote selection
- exact queue priority
- same-price matching order
- other teams' MAF bids
- official hidden matching path

Round 2 outputs should be read as sensitivity analysis and ranking evidence.
