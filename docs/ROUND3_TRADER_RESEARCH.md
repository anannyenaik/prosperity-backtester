# Round 3 Trader Research

Result: `strategies/r3_algo_v1.py` is a conservative first serious Round 3 trader, but it is not yet a final submission candidate because 32-session Monte Carlo is slightly negative.

## Strategy Design

- `HYDROGEL_PACK`: active mean-reversion trader. Fair value blends fixed anchor `9991`, live EWMA, and live mid. A trend guard avoids adding while price is still moving away from the anchor. Soft cap is `60`, exchange cap is `200`.
- `VELVETFRUIT_EXTRACT`: hedge reserve only. Standalone trading is disabled. Delta hedging is intentionally wide because local tests showed spread cost outweighed the benefit for the current voucher book.
- `VEV_5000` to `VEV_5500`: active central voucher set. The trader estimates live IV from current mids, uses a rolling central IV, applies per-strike price residual EWMAs, and trades only visible-book dislocations after spread and residual scale.
- `VEV_4000`, `VEV_4500`, `VEV_6000`, `VEV_6500`: disabled by default and excluded from the fit. Deep ITM vouchers have noisy IV from tiny extrinsic value; far OTM vouchers are pinned.

## Public Strategy Lessons Used

- Volatility smile and moneyness fitting are useful, but this Round 3 chain looks flat enough that v1 uses a central live IV rather than a quadratic fit.
- Black-Scholes conversion is useful for turning IV residuals into price-space edges.
- Deep ITM and far OTM strikes should not drive the surface.
- Rolling live IV and residual EWMAs are safer than static fitted coefficients.
- Delta hedging is not automatically good. For this data, routine hedging consumed edge, so v1 only hedges at wide delta bands.
- Simple, bounded state is preferred over fragile rolling windows.

## Signals Tested

- Hydrogel distance from `9991`: accepted, repeatable across days 0, 1, and 2.
- Hydrogel EWMA deviation and trend-away guard: accepted as risk control. Lower Hydrogel take thresholds were rejected because they reduced all-day PnL.
- Hydrogel bot/timestamp pattern: rejected for v1. It may explain liquidity, but exact event timing is not final-simulation safe.
- Velvetfruit short-term mean reversion: rejected for standalone trading. The signal was weaker and hedge capacity is more valuable.
- Voucher residual mean reversion: accepted only in central strikes and with small size. It is directionally useful but still modest in fill-aware replay.
- Voucher seller dominance: accepted only as a small execution prior. v1 does not depend on passive fills.
- Static quadratic smile: disabled by default. It is plausible but not proven superior on this VEV chain.
- Vertical monotonicity and convexity violations: rejected as a v1 alpha. No central monotonicity or convexity breaks survived.
- Deep ITM intrinsic dislocations and far OTM pinned prices: monitored conceptually, disabled in trading.

## Backtest Summary

Candidate settings:

- Hydrogel soft cap: `60`
- Active voucher soft cap: `150`
- Aggregate voucher delta soft cap: `135`
- Portfolio hedge soft band: `150`
- Final TTE: `5 / 365`

Historical replay, base fill:

| Day | Total PnL | Notes |
| ---: | ---: | --- |
| 0 | 9,426.50 | Positive, led by Hydrogel |
| 1 | 19,674.50 | Positive, Hydrogel plus `VEV_5100` |
| 2 | 31,712.50 | Positive, Hydrogel plus `VEV_5000`/`VEV_5100` |

Per-product final PnL:

- `HYDROGEL_PACK`: `26,521.00`
- `VEV_5000`: `2,245.00`
- `VEV_5100`: `3,402.50`
- `VEV_5200`: `-226.00`
- `VEV_5300`: `-275.00`
- `VEV_5400`: `45.00`
- `VELVETFRUIT_EXTRACT` and disabled vouchers: `0.00`

Fill sensitivity:

| Scenario | PnL |
| --- | ---: |
| base | 31,712.50 |
| no_passive | 31,712.50 |
| worse_only | 31,712.50 |
| conservative_queue | 24,398.50 |
| harsh_adverse | 19,405.50 |

Research scenarios:

| Scenario | PnL |
| --- | ---: |
| historical_baseline | 31,712.50 |
| underlying_up_vol_richer | 31,712.50 |
| voucher_liquidity_stress | 24,398.50 |
| hydrogel_liquidity_stress | 24,398.50 |

Monte Carlo, 32 sessions:

- Mean: `-376.91`
- p05: `-3,074.45`
- Min/max: `-4,524.66` / `2,067.60`
- Win rate: `50.00%`

## Caveats

- The strategy is not yet submission-worthy because MC mean is slightly negative.
- Hydrogel is still the main PnL source and the main MC tail source.
- Voucher trading is intentionally small; v1 has not yet extracted the large options edge seen in top public writeups.
- The current Monte Carlo generator may understate Hydrogel anchor mean reversion, but the result is still a valid warning.

## Test Commands

```bash
python -m prosperity_backtester replay strategies/r3_algo_v1.py --round 3 --data-dir data/round3 --days 0 1 2 --fill-mode base --output-dir backtests/r3_algo_v1_replay_cap60_wide_hedge
python -m prosperity_backtester scenario-compare configs/r3_algo_v1_fill_sensitivity.json --output-dir backtests/r3_algo_v1_fill_sensitivity_candidate
python -m prosperity_backtester scenario-compare configs/r3_algo_v1_research.json --output-dir backtests/r3_algo_v1_research_scenarios_candidate
python -m prosperity_backtester monte-carlo strategies/r3_algo_v1.py --round 3 --data-dir data/round3 --days 0 --sessions 32 --sample-sessions 4 --synthetic-tick-limit 250 --output-dir backtests/r3_algo_v1_mc32_cap60_wide_hedge
```

## V2 Ideas

- Highest EV: improve Hydrogel generalisation by calibrating the anchor confidence from live book behaviour rather than a fixed cap trade-off.
- Rework voucher fair value around bid/ask IV and per-strike residual half-life, then retest with no-passive and MC.
- Test a strict active set of only `VEV_5000` and `VEV_5100`, since `VEV_5200` and `VEV_5300` lost money in fill-aware replay.
- Add a measured hedge-cost model before re-enabling routine `VELVETFRUIT_EXTRACT` hedging.
