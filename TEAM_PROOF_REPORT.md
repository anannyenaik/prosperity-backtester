# Team proof report

This repo demonstrates a full Round 1 research workflow:

- deterministic replay of real trader files
- configurable fill assumptions
- Monte Carlo robustness sessions
- fair-value and behaviour diagnostics
- live-export calibration
- trader comparison
- parameter sweeps and optimisation
- reusable dashboard bundles
- a polished React dashboard with inspect mode

## Verified for submission

Commands run locally:

```bash
uv run --with pytest pytest -q
npm.cmd ci
npm.cmd run build
```

Result: 9 backend tests passed, dashboard dependencies installed with no reported vulnerabilities, and the dashboard production build completed successfully.

## Dataset proof

The bundled Round 1 data loads for days `-2`, `-1` and `0`.

Observed validation summary:

- Day `-2`: 20,000 price rows, 773 trade rows, 10,000 timestamps, no missing products, no crossed books.
- Day `-1`: 20,000 price rows, 760 trade rows, 10,000 timestamps, no missing products, no crossed books.
- Day `0`: 20,000 price rows, 743 trade rows, 10,000 timestamps, no missing products, no crossed books.

There are one-sided and empty book rows in the source data. The platform reports them rather than hiding them.

## Dashboard proof

The dashboard now supports:

- Overview cards and run metadata.
- Replay PnL, realised/unrealised, inventory, fair/mid/fill views and largest fills.
- Monte Carlo distribution, downside, path bands and sample sessions.
- Calibration frontier, best candidate, bias counts and per-product mismatch.
- Side-by-side run comparison and deltas.
- Optimisation score frontier and ranked tables.
- OSMIUM spread-capture deep dive.
- PEPPER exposure and cap-pressure deep dive.
- Inspect mode with a timestamp slider, radius controls, side rails, slice metrics, fair/mid/fills/inventory charts and order/fill tables.

## Exact vs approximate

Exact:

- CSV parsing and schema validation.
- Visible-book aggressive fills.
- Trader state persistence.
- Cash, inventory, realised, unrealised and MTM accounting.
- Synthetic latent fair inside Monte Carlo.

Approximate:

- Passive queue position.
- Same-price queue share.
- Historical fair inference.
- Adverse-selection penalties.
- Calibration and optimisation scoring.

## Bottom line

The repo is now closer to an internal team-grade research platform than a one-off competition script. The main remaining modelling gap is execution realism, especially passive queue and live-export reconstruction.
