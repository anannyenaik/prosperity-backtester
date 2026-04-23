# Assumptions

Result: the repo is designed for reliable local ranking, not for claiming exact reconstruction of the hidden competition website.

The code separates what is exact relative to the public inputs from what is modelled locally.

## Exact Relative To Local Inputs

These parts are deterministic and directly grounded in the tracked CSV inputs or the local run configuration:

- CSV schema validation and dataset loading
- timestamp ordering and product presence checks
- visible-book aggressive fills
- trader state persistence through `traderData`
- own-trade hand-off between ticks
- cash, inventory, realised, unrealised, and mark-to-market accounting
- deterministic replay over the selected historical days
- manifest and bundle provenance

## Modelled Locally

These parts are deliberate modelling choices:

- passive queue position
- same-price queue share
- missed passive fills
- adverse-selection penalties
- size-dependent slippage
- latency-like delayed action effects
- historical `analysis_fair`
- synthetic market generation for Monte Carlo
- calibration and optimisation scores
- Round 2 extra-access quality and fill uplift assumptions

These are useful because they make conservative ranking possible, but they are not claims about hidden exchange mechanics.

## `analysis_fair`

`analysis_fair` means different things in the two main modes:

- historical replay: an inferred diagnostic fair-value proxy
- Monte Carlo: the latent fair path used by the simulator itself

It is useful for markout and placement analysis. It is not an official hidden fair value.

## Live-Export Calibration

Calibration compares local replay output against whatever fields exist in a tracked live export, such as:

- total profit
- PnL-path error
- per-product PnL where available
- final-position mismatch
- inventory-path mismatch
- fill-count and fill-quantity mismatch
- passive versus aggressive fill mismatch
- activity timing mismatch

Calibration can help choose conservative local assumptions. It cannot recover:

- rejected passive orders
- true queue priority
- hidden matching details
- website-only latency or throttling

## Scenario Analysis

Scenario outputs should be read as stress testing, not prediction.

Use them to ask:

- does the ranking survive worse fill assumptions?
- does the strategy stay acceptable under spread or depth stress?
- is the downside still acceptable under slippage or crash stress?
- is a small improvement larger than likely modelling error?

Small edges should survive several scenario families before they are trusted.

## Round 2 Access Assumptions

Grounded from the public challenge description:

- Round 2 trades `ASH_COATED_OSMIUM` and `INTARIAN_PEPPER_ROOT`
- a Market Access Fee may grant access to an extra 25% of quotes
- only the top 50% of MAF bids get the contract
- losing bids do not pay and do not receive extra access

Still unknown:

- exact extra-quote selection
- exact queue priority
- same-price matching order
- other teams' MAF bids
- official hidden matching behaviour

Round 2 outputs are therefore sensitivity analysis, not proof of exact realised website PnL.

## How To Read Results Safely

Treat the repo as strong evidence when:

- one strategy beats another by a healthy margin
- the lead survives several plausible fill assumptions
- replay, scenario, and Monte Carlo evidence point in the same direction

Treat the result as uncertain when:

- the edge is small
- the result depends on optimistic passive fills
- the winner changes under modest scenario stress
- calibration against live data remains poor
