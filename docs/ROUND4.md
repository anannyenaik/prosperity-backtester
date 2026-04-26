Result: Round 4 is now treated as a first-class round with its own data directory, registry entry, counterparty research workflow, candidate strategy, and verification harness.

# Round 4

## Products And Limits

Algorithmic products are unchanged from Round 3:

- `HYDROGEL_PACK`, limit `200`
- `VELVETFRUIT_EXTRACT`, limit `200`
- `VEV_4000`, `VEV_4500`, `VEV_5000`, `VEV_5100`, `VEV_5200`, `VEV_5300`, `VEV_5400`, `VEV_5500`, `VEV_6000`, `VEV_6500`, each limit `300`

The vouchers are calls on `VELVETFRUIT_EXTRACT`. The Round 4 wiki example states `VEV_5000` has `TTE=4` days in Round 4, so final-sim pricing uses `4/365`. Historical diagnostics use the local day mapping `1 -> 7`, `2 -> 6`, `3 -> 5` as a public-data roll-down assumption.

## Data

Round 4 data lives in `data/round4`.

Validated files:

- `prices_round_4_day_1.csv`, `prices_round_4_day_2.csv`, `prices_round_4_day_3.csv`
- `trades_round_4_day_1.csv`, `trades_round_4_day_2.csv`, `trades_round_4_day_3.csv`
- `manifest.json`

Each price day has `120,000` rows, `10,000` timestamps from `0` to `999900`, twelve products per timestamp, no duplicate product/timestamp rows, no missing products, and no crossed books in the imported capsule. Trade rows are `1,407`, `1,333`, and `1,541` for days `1`, `2`, and `3`. All trade quantities are positive, currency is `XIRECS`, and buyer/seller fields contain seven named counterparties.

## Counterparty Workflow

Run:

```bash
python -m prosperity_backtester r4-counterparty-research --data-dir data/round4 --output-dir backtests/r4_counterparty_research_latest
```

Outputs:

- `counterparty_product_side_day.csv`
- `counterparty_product_side_pooled.csv`
- `cross_product_markouts.csv`
- `counterparty_recommendations.csv`
- `summary.json`

The research computes signed markouts after `1`, `5`, `10`, `20`, `50`, `100`, and `300` ticks. Positive signed markout means follow the counterparty. Negative signed markout means fade the counterparty. Recommendations are intentionally conservative and include sample-size, day-split, spread-cost, largest-trade, and timestamp-cluster robustness fields.

## Replay And MC Assumptions

Historical replay uses observed books and observed mids. Buyer and seller names are preserved into `TradingState.market_trades`.

Round 4 MC reuses the coherent Round 3 voucher generator with Round 4 metadata, TTE, days, and named synthetic trade flow. Vouchers are generated from the VELVET path plus IV/residual/spread/depth sampling, not independently. Counterparty flow is resampled from public distributions and can be disabled or sign-flipped through configs. This is a rejection tool, not proof of final robustness.

## Candidate

Active Round 4 candidate:

```bash
strategies/r4_algo_v1_candidate.py
```

It uses:

- live HYDROGEL EWMA fair with `9991` only as a missing-data warm-start prior
- Black-Scholes voucher fair with `4/365` final TTE
- central voucher surface from `VEV_5000` through `VEV_5500`
- bounded counterparty fair-value leans, clipped to about one tick on VELVET
- strict deep-ITM participation with small clips and delta checks
- module-level toggles for counterparty ablations, deep ITM, crossing aggression, HYDROGEL cap, and fill-stress configs

## Verification

Fast harness:

```bash
python -m prosperity_backtester verify-round4 --data-dir data/round4 --output-dir backtests/r4_verification_fast
```

Full smoke:

```bash
python -m prosperity_backtester verify-round4 --data-dir data/round4 --output-dir backtests/r4_verification_full --full
```

Do not promote the candidate from public replay alone. Required gates remain: day splits, fill sensitivity, names-disabled ablation, deep-ITM ablation, HYDROGEL mean shifts, counterparty weakened/sign-flipped stress, VELVET drift, IV shifts, spread widening, liquidity thinning, and paired MC differences.
