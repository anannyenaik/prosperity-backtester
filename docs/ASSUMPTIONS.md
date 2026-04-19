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
- per-product PnL mismatch where available
- per-product path RMSE where live activity paths are available
- optimism, pessimism and dominant error-source attribution

It does not claim exact reconstruction of the official matching engine.

## Monte Carlo

Monte Carlo is intended for:

- robustness testing
- parameter comparison
- stability analysis
- FV-path stress

It is not intended as a literal forecast of official competition profit.
