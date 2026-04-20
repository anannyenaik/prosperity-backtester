# Assumptions and approximation boundaries

## Historical replay

### Exact

- historical timestamps
- historical visible book snapshots
- visible-book aggressive fills
- account updates from simulated fills
- position limits after clamping

### Approximate

- passive queue position
- same-price queue share
- missed fills
- adverse selection penalties
- size-dependent slippage
- re-entry assumptions
- fill timing under latency-like delays

## Fair value

### Synthetic Monte Carlo

`analysis_fair` is exact relative to the simulator because it is the latent fair path used to generate books and trades.

### Historical replay

`analysis_fair` is inferred from market structure and should be treated as a diagnostic proxy, not as the official hidden exchange fair.

## Live-export calibration

Calibration is practical rather than perfect.

It compares:

- total profit
- total PnL path RMSE
- final position mismatch
- fill count mismatch
- fill quantity mismatch
- passive vs aggressive fill mismatch
- activity timing mismatch
- inventory-path mismatch
- per-product PnL mismatch where available
- per-product path RMSE where live activity paths are available
- optimism, pessimism and dominant error-source attribution

It does not claim exact reconstruction of the official matching engine.

Live `tradeHistory` can include market prints as well as own fills. The loader treats only rows where `SUBMISSION` is buyer or seller as own fills for calibration.

## Empirical fills and slippage

Empirical fill profiles are grounded in realised live fills:

- product
- side
- quantity
- visible spread
- touch distance
- passive/aggressive label inferred from visible touch
- liquidity regime

Still configurable assumptions:

- passive fill probability
- same-price queue share
- rejected passive order rate
- size slippage curve
- passive adverse-selection ticks
- aggressive adverse-selection ticks

Unknown:

- rejected passive opportunities not shown in live exports
- exact queue priority
- hidden matching and website-only effects

## Calibrated scenarios

Scenario outputs are decision tools.

Baseline, stress, crash, wider-spread, harsher-slippage and lower-fill-quality scenarios should be used to ask:

- does the strategy still win under conservative fills
- does it collapse under thinner depth or shocks
- is the gain larger than live-vs-sim mismatch
- is the ranking stable across assumptions

## Monte Carlo

Monte Carlo is intended for:

- robustness testing
- parameter comparison
- stability analysis
- FV-path stress

It is not intended as a literal forecast of official competition profit.

## Round 2 MAF and extra quote access

### Grounded

- Round 2 keeps `ASH_COATED_OSMIUM` and `INTARIAN_PEPPER_ROOT`.
- A Market Access Fee may grant access to an extra 25% of quotes.
- Only the top 50% of total MAF bids get the contract.
- Losing bids do not pay and do not get the extra quote access.

### Configurable locally

- contract won or not won
- MAF bid deducted from net PnL when the contract is won
- deterministic or stochastic access
- access quality
- visible book volume uplift
- passive fill rate uplift
- missed fill reduction
- fill opportunity volume uplift

### Unknown website-only mechanics

- exact extra quote selection
- exact queue priority
- how extra quotes translate into fills
- other teams' MAF bids
- official hidden matching path

Round 2 outputs should be read as scenario comparisons and sensitivity analysis, not exact website reconstruction.
