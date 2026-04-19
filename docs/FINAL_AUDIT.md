# Final audit

## Result

The repo is now a serious Round 1 research platform rather than a single-purpose backtester. It has deterministic replay, configurable fill assumptions, Monte Carlo robustness, live-export calibration, comparison, optimisation, run manifests, a local registry and a React signal-observatory dashboard.

## Preserved strengths

- `r1bt/platform.py` remains the main execution and accounting layer.
- `r1bt/experiments.py` remains the workflow layer for replay, Monte Carlo, comparison, sweeps, optimisation and calibration.
- `r1bt/reports.py` remains the bundle contract for `dashboard.json`, CSV sidecars, manifests and `run_registry.jsonl`.
- The React/Vite dashboard remains the product surface because it is already a stronger direction than a static HTML report.

## Important fixes in this pass

- Monte Carlo fair-value bands now include `p25` and `p75`, matching the dashboard chart contract.
- Behaviour summaries now expose concrete counts and quantities used by dashboard deep dives: total fills, passive fills, aggressive fills, buy/sell fill quantities and order quantities.
- The optimisation dashboard now displays scores in the correct direction, with the highest score ranked first.
- Calibration grid highlighting no longer relies on object identity after JSON loading.
- Source comments were cleaned to avoid em dashes.

## Reference benchmark

The public `chrispyroberts/imc-prosperity-4` repo is strongest on Rust-backed Monte Carlo throughput, a simple `prosperity4mcbt` workflow and path-band visualisation. This repo exceeds it for Round 1 team work because it adds live-export ingestion, calibration search, product-level behaviour diagnostics, comparison, optimisation, replay bundle sidecars and a richer dashboard.

The current repo still trails the reference on raw Monte Carlo throughput. A Rust hot loop is not justified yet unless teams need hundreds or thousands of Round 1 sessions per iteration.

## Exact vs approximate

Exact relative to local inputs:

- Historical CSV schema validation and timestamp ordering.
- Visible-book aggressive fills.
- Cash, realised, unrealised and MTM accounting for simulated fills.
- Trader state persistence and common Prosperity datamodel import aliases.
- Synthetic latent fair inside Monte Carlo sessions.

Approximate:

- Passive queue position and same-price priority.
- Missed-fill, latency and adverse-selection controls.
- Historical `analysis_fair`.
- Synthetic market generation.
- Calibration and optimisation scores.

## Remaining limits

- True queue position is not visible from public data.
- Live exports do not always expose enough detail for exact official-engine reconstruction.
- The Python Monte Carlo path is maintainable and adequate for current scale, but not as fast as the Rust reference for very large batches.
