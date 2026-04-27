# Assumptions

Result: the repo is designed for honest local research, not false claims about hidden website mechanics.

## Exact relative to local inputs

These parts are deterministic once you choose the command, data, and fill model:

- CSV schema validation and dataset loading
- round-aware product and position-limit validation
- visible-book aggressive fills
- trader state persistence through `traderData`
- own-trade hand-off between ticks
- cash, inventory, realised, unrealised, and mark-to-market accounting
- deterministic historical replay over the selected days
- manifest and bundle provenance

## Modelled locally

These parts remain deliberate modelling choices:

- passive queue position
- same-price queue share
- same-price trade-print passive fills, labelled as a queue assumption
- worse-price trade-print passive fills, labelled as a through-print assumption
- missed passive fills
- adverse-selection penalties
- size-dependent slippage
- synthetic market generation for Monte Carlo
- historical `analysis_fair`
- calibration and optimisation scores
- Round 2 extra-access quality and fill uplift assumptions

These are useful for ranking and stress testing. They are not official exchange behaviour.

## Round 3 assumptions

Round 3 adds a few important boundaries:

- historical replay uses the observed book for `HYDROGEL_PACK`, `VELVETFRUIT_EXTRACT`, and every `VEV_*` voucher
- Round 3 positions are marked to the observed market mid, including fractional mids such as `0.5`
- option theory is diagnostic and synthetic support only
- historical voucher replay does not override observed prices with Black-Scholes values
- fitted IV, fair value, Greeks, residuals, and residual z-scores are diagnostics, not replay marks
- coherent Round 3 Monte Carlo samples vouchers from the underlying path, fitted surface, and residual noise
- Round 3 Monte Carlo currently runs through the classic Python path
- no voucher exercise or cash settlement is applied during Round 3 replay unless official rules later require it
- the Ornamental Bio-Pods challenge is separate from the algorithmic replay engine

## Round 4 assumptions

Round 4 adds named market trades, but names are not aggressor proof:

- buyer and seller fields are preserved exactly as counterparty metadata
- passive fill direction is inferred from trade price versus the contemporaneous visible book
- if both names are populated and price does not identify direction safely, the trade print is ambiguous and does not fill passive orders
- `match_trades=all` allows equal-or-through prints after direction inference
- `match_trades=worse` requires a strictly better print than the resting quote
- `match_trades=none` disables passive trade-print fills
- counterparty research labels below-cost positive raw markouts as `ignore`, not `fade`
- Round 4 MC is a seeded rejection and stress tool; it is not treated as official simulator equivalence

## `analysis_fair`

`analysis_fair` still means a local diagnostic construct:

- historical replay: an inferred reference path for diagnostics
- Monte Carlo: the latent or coherent synthetic path used by the simulator

It is useful for markouts, stress testing, and attribution. It is not an official hidden fair value.

## How to read results safely

Treat the repo as strong evidence when:

- one strategy beats another by a healthy margin
- the lead survives several plausible fill assumptions
- replay, stress, and Monte Carlo all point in the same direction

Treat the result as uncertain when:

- the edge is small
- the result depends on optimistic passive fills
- Round 3 voucher diagnostics are unstable at deep ITM or pinned far OTM strikes
- the winner changes under modest stress
- Round 4 results depend on named-counterparty effects that do not survive no-names, shuffled, sign-flipped, day-held-out, or fill-mode ablations
