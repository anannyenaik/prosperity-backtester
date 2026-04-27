Result: Round 4 is first-class in the backtester, but no R4 strategy is promoted.

# Round 4

## Products And Limits

Algorithmic products are unchanged from Round 3:

- `HYDROGEL_PACK`, limit `200`
- `VELVETFRUIT_EXTRACT`, limit `200`
- `VEV_4000`, `VEV_4500`, `VEV_5000`, `VEV_5100`, `VEV_5200`, `VEV_5300`, `VEV_5400`, `VEV_5500`, `VEV_6000`, `VEV_6500`, each limit `300`

The vouchers are calls on `VELVETFRUIT_EXTRACT`. Final-simulation voucher pricing uses `4/365` TTE unless official local data later contradicts it. Historical diagnostics use the local public-data roll-down `1 -> 7`, `2 -> 6`, `3 -> 5`.

## Data

Round 4 data lives in `data/round4`.

Validated files:

- `prices_round_4_day_1.csv`, `prices_round_4_day_2.csv`, `prices_round_4_day_3.csv`
- `trades_round_4_day_1.csv`, `trades_round_4_day_2.csv`, `trades_round_4_day_3.csv`
- `manifest.json`

Each price day has `120,000` rows, `10,000` timestamps from `0` to `999900`, twelve products per timestamp, no duplicate product/timestamp rows, no missing products, and no crossed books in the imported capsule. Trade rows are `1,407`, `1,333`, and `1,541` for days `1`, `2`, and `3`. Trade quantities are positive, currency is `XIRECS`, and buyer/seller fields contain named counterparties.

Build the strict manifest:

```bash
python -m prosperity_backtester r4-manifest --data-dir data/round4 --output-dir backtests/r4_manifest_latest
```

The manifest writes `manifest_report.json`, `manifest_report.md`, `spread_depth_summary.csv`, and `counterparties_by_product.csv`. It records days, products, timestamp counts, row counts, schema status, data hashes, counterparties by day/product, missing or duplicate timestamp-product rows, crossed books, zero or negative prices, and spread/depth summaries. Zero voucher price levels are reported because public far-OTM books can sit at the price floor; negative prices fail validation.

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

The research computes signed participant-side markouts after `1`, `5`, `10`, `20`, `50`, `100`, and `300` ticks. Buyer and seller names are participant metadata, not aggressor inference. A positive raw markout can only become `follow` if it clears the estimated spread/adverse cost and is day-stable. A positive raw markout below cost is `ignore`, not `fade`. Low-count or mixed-sign effects are not production recommendations.

## Replay And Fill Modes

Historical replay uses observed books and observed mids. Buyer and seller names are preserved into `TradingState.market_trades`.

Fill channels are separated:

- `aggressive_visible`: submitted orders that cross visible book levels.
- `passive_approx`: resting orders filled from market trade prints after direction is inferred from trade price versus the contemporaneous book.
- stress fills from conservative/adverse fill-model settings.

Passive trade matching modes:

- `none`: no passive fills from market trades.
- `worse`: only prints strictly through the resting quote.
- `all`: equal-or-through prints, still requiring safe direction inference.

Named R4 trades usually have both buyer and seller populated. The replay therefore does not treat names as empty-side aggressor markers. If direction is ambiguous, the passive fill is skipped.

## MC Validation

Round 4 MC uses the coherent voucher generator with Round 4 metadata, TTE, days, mean-reverting delta-one paths, and named synthetic trade flow. Vouchers are generated from the VELVET path plus IV/residual/spread/depth sampling, not independently. Counterparty flow is resampled from public distributions and can be disabled or sign-flipped through configs. This is a rejection tool, not proof of final robustness.

Validate MC:

```bash
python -m prosperity_backtester r4-mc-validation --data-dir data/round4 --output-dir backtests/r4_mc_validation_fast --fast
```

The validation report compares public and synthetic mid returns, autocorrelation, volatility, spread, depth, trade counts, trade sizes, counterparty participation, signed markouts, VELVET-voucher correlation, option IV/residuals, HYDROGEL mean reversion, no-op PnL, and seed determinism. It writes JSON and Markdown reports.

## Candidate Fixture

Rejected diagnostic fixture:

```bash
strategies/r4_algo_v1_candidate.py
```

Do not treat this file as active strategy work. It is present so replay, ablation, and MC gates have a non-trivial fixture. No constants should be tuned from this task.

## Verification

Fast harness:

```bash
python -m prosperity_backtester verify-round4 --data-dir data/round4 --output-dir backtests/r4_verification_fast --fast
```

Skip MC:

```bash
python -m prosperity_backtester verify-round4 --data-dir data/round4 --output-dir backtests/r4_verification_skip_mc --skip-mc
```

Full smoke:

```bash
python -m prosperity_backtester verify-round4 --data-dir data/round4 --output-dir backtests/r4_verification_full --full
```

Strict gate:

```bash
python -m prosperity_backtester verify-round4 --data-dir data/round4 --output-dir backtests/r4_verification_strict --strict
```

`verify-round4` always writes `verification_report.json`, `verification_report.md`, and `manifest.json`, even when checks fail. The final decision includes `backtester_decision_grade` and `candidate_promoted`; candidate promotion must remain `false` unless a later strategy task explicitly requests promotion and every gate passes.

Fast and skip-MC verification always validate the full data manifest and counterparty research. To keep the command suitable for a smoke gate, replay and ablation rows use day `1` with a bounded historical tick window and record that in `replay_scope`. Full mode removes that truncation.

Known gaps versus official simulation:

- hidden queue priority is not observable
- passive same-price fills are queue assumptions
- ambiguous named R4 trade prints are skipped
- MC resemblance is checked statistically, not proven equivalent
- no voucher exercise or final cash settlement is applied unless official rules require it
