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

## V2 Candidate Test Pass (2026-04-25)

`strategies/r3_algo_v1.py` was preserved as `strategies/r3_algo_v1_aggressive_baseline.py` and
a blueprint-aligned variant was written to `strategies/r3_algo_v2_candidate.py` to test the
hypothesis that the published blueprint (slow-EMA Hydrogel, fixed `BASE_IV=0.239` smile,
canonical delta bands, passive-leaning vouchers) would beat the aggressive baseline on
robustness.

### Audit findings (current `r3_algo_v1.py` vs blueprint)

- Hydrogel cap: code is `60` soft; blueprint after teammate feedback wants `150` soft / `200` hard. Confirmed: `60`.
- Hydrogel fair: code uses `0.62 * 9991 + 0.28 * live_ewma + 0.10 * mid` (anchor-heavy); blueprint wants slow-EMA-dominant with `α=0.0002`. Confirmed: anchor-heavy.
- Voucher execution: code crosses visible book via `cross_edge` walking; blueprint says canonical v1 should be passive-only. Confirmed: crosses.
- IV model: code uses `PRIOR_IV=0.26` plus a live centre-IV from current mids and dynamic per-strike residual offsets; blueprint wants `BASE_IV=0.239` plus rounded per-strike offsets and a clipped EWMA correction. Confirmed: live centre.
- Delta bands: code uses voucher delta soft `135` / hard `175` and portfolio soft `150` / hard `190`; blueprint canonical is portfolio soft `35` / hard `70`. Confirmed: wide.

### Backtester observation

`fills.csv` from any base-mode replay shows zero passive fills for both the aggressive
baseline (`HYDROGEL_PACK` is `aggressive_visible` only, voucher PnL is realised by book
crossing) and the v2 candidate. The published fill-sensitivity table also shows
`base = no_passive = worse_only = 31,712.50` for the baseline, which is only consistent
with passive matching contributing zero to the historical replay.

This means a strictly passive-only voucher policy harvests no edge in this backtester's
base fill model. A first pass of v2 with passive-only vouchers produced exactly that:
`VEV_*` placed `~60k` orders and got `0` fills. The v2 candidate was therefore revised to
keep selective taking with a more conservative `cross_edge` while still using the
blueprint IV model.

### v2 candidate constants

- `BASE_IV = 0.239`, `IV_CORRECTION_CLIP = 0.020`, per-strike offsets per blueprint.
- Hydrogel: `0.40 * anchor + 0.50 * slow_ewma + 0.10 * mid`, slow `α=0.0002`, soft cap `100`, hard `200`.
- Voucher: selective take when `edge > max(1.10, 0.55 * spread)`, plus join-touch passive quotes.
- Voucher delta soft `100` / hard `160`; portfolio delta soft `90` / hard `140`.
- Hedge only when net delta exceeds soft band and Velvet spread is reasonable; target half-band, not zero.

### v2 candidate results

Replay (`base` fill model):

| Day | Total | HYDROGEL | VELVET | VEV_5000 | VEV_5100 | VEV_5200 | VEV_5300 | VEV_5400 | VEV_5500 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 4,984.00 | 5,422.00 | -966.00 | -- | -- | -- | -- | 222.00 | -- |
| 1 | 8,405.50 | 9,281.00 | -- | -- | -720.00 | -405.00 | -- | -- | -- |
| 2 | 23,898.00 | 16,912.00 | 328.50 | 310.00 | 3,239.50 | 3,748.00 | -637.00 | -51.00 | 48.00 |

Fill sensitivity:

| Scenario | v2 PnL | baseline PnL |
| --- | ---: | ---: |
| base | 23,898.00 | 31,712.50 |
| no_passive | 23,898.00 | 31,712.50 |
| worse_only | 23,898.00 | 31,712.50 |
| conservative_queue | 15,968.00 | 24,398.50 |
| harsh_adverse | 10,716.00 | 19,405.50 |

Research scenarios:

| Scenario | v2 PnL | baseline PnL |
| --- | ---: | ---: |
| historical_baseline | 23,898.00 | 31,712.50 |
| underlying_up_vol_richer | 23,898.00 | 31,712.50 |
| voucher_liquidity_stress | 15,968.00 | 24,398.50 |
| hydrogel_liquidity_stress | 15,968.00 | 24,398.50 |

Monte Carlo, 32 sessions, day 0:

| Metric | v2 candidate | baseline |
| --- | ---: | ---: |
| mean | -1,073.54 | -376.91 |
| p05 | -6,193.50 | -3,074.45 |
| min | -9,438.86 | -4,524.66 |
| max | 2,739.52 | 2,067.60 |
| win rate | 13/32 (40.6%) | 16/32 (50%) |

### Conclusion

The candidate is **rejected**. It is uniformly weaker than the aggressive baseline on
replay, fill sensitivity, research scenarios, and Monte Carlo.

The candidate's slow-EMA-dominant Hydrogel fair concedes mean-reversion edge whenever the
slow EMA has already drifted toward perturbed prices: the implicit prior that prices revert
to `9991` is a live edge against the local MC harness (which generates synthetic days
around the historical mean), and the slow EMA destroys it. Tighter delta bands also bleed
through Velvet hedge churn (`-2,256` MTM at `60/110`, recovered to `+329` at `90/140`).

Both the baseline and the candidate fail the strict promotion gate:
**neither is submission-worthy under the user's MC criteria.** The baseline is closer
(MC mean `-377` vs `-1,074`).

### Implications for next pass

The local MC harness centres synthetic perturbations on the historical mean, so it
rewards a fixed `9991` anchor. That makes the harness a poor test of the blueprint's
"in-final-sim the anchor may move" concern. Future work needs:

1. A modified MC scenario that breaks the anchor (e.g. `+50` Hydrogel mean shift) to
   see whether the slow-EMA candidate dominates the baseline in that regime.
2. A hybrid Hydrogel fair that anchors when `slow_ewma` is close to `9991` and switches
   to slow EMA only when material drift is detected — this captures both regimes.
3. Voucher edge attribution: in v2, central strikes (`VEV_5100`/`VEV_5200`) provide the
   majority of voucher PnL; outer strikes (`VEV_5300`-`VEV_5500`) lose money under
   conservative fill models. A strict `VEV_5000`/`VEV_5100`/`VEV_5200` only set is
   worth measuring against the current full set.

## Persistent Hydrogel Mean-Shift Harness and v1.2 Candidate (2026-04-25)

Decision: keep `strategies/r3_algo_v1.py` unchanged as the best current historical
baseline. Add `strategies/r3_algo_v1_2_candidate.py` as the single serious candidate
for final-simulation robustness review. Do not call v1.2 final-sim proven yet.

Harness change:

- Added `python -m prosperity_backtester round3-hydrogel-meanshift`.
- The command runs synthetic Round 3 MC only. It does not emit historical replay rows.
- `hydrogel_shock` is applied persistently to the synthetic HYDROGEL latent path from
  `shock_tick` onward.
- The output reports absolute `mc_mean`, `mc_p05`, `mc_min`, `mc_max`, win rate, limit
  breaches and per-product attribution per strategy.

v1.2 design:

- Kept v1 voucher logic unchanged.
- Replaced only the HYDROGEL block.
- `9991` is retained as a bounded warm-start prior, not the dominant live fair.
- HYDROGEL fair is mostly slow live EMA plus bounded fast/mid terms.
- Size and edge tighten when slow EMA drifts from `9991` or fast-vs-slow trend widens.
- Soft HYDROGEL cap remains at or below `60`; peak historical position was `60`.

Replay and fill results:

| Strategy | Replay | Conservative queue | Harsh adverse | Breaches |
| --- | ---: | ---: | ---: | ---: |
| v1 | 31,712.50 | 24,398.50 | 19,405.50 | 0 |
| rejected v1.1 | 17,426.00 | 6,146.00 | -1,576.00 | 0 |
| v1.2 | 21,870.50 | 13,264.50 | 7,508.50 | 0 |

MC32, nearest-rank p05 for comparability with prior notes:

| Strategy | Mean | p05 | Min | Max | Win rate | Breaches |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| v1 | -376.91 | -3,074.45 | -4,524.66 | 2,067.60 | 50.0% | 0 |
| rejected v1.1 | -279.88 | -2,950.80 | -3,421.44 | 2,004.87 | 50.0% | 0 |
| v1.2 | -215.33 | -2,309.66 | -2,982.57 | 2,307.73 | 50.0% | 0 |

Persistent synthetic HYDROGEL mean-shift, 16 sessions per shift:

| Shift | v1 mean / p05 / min | v1.1 mean / p05 / min | v1.2 mean / p05 / min |
| ---: | ---: | ---: | ---: |
| -100 | -649.65 / -3,705.17 / -3,878.67 | 215.21 / -1,809.62 / -2,316.20 | 584.98 / -1,368.52 / -1,639.67 |
| -60 | 352.74 / -3,915.31 / -4,412.89 | 650.80 / -4,190.19 / -5,160.86 | 809.42 / -1,396.32 / -1,930.69 |
| -30 | -1,047.20 / -6,022.64 / -7,056.88 | -185.58 / -4,212.65 / -4,780.12 | -275.85 / -3,960.13 / -4,415.90 |
| 0 | 1,228.44 / -916.18 / -1,334.53 | 964.03 / -1,396.72 / -1,843.45 | 891.46 / -1,472.99 / -1,500.53 |
| +30 | 1,920.83 / -1,041.59 / -1,477.37 | 596.75 / -2,442.15 / -3,663.81 | 738.23 / -1,747.14 / -2,829.61 |
| +60 | 32.89 / -5,214.21 / -6,616.68 | -166.59 / -4,371.33 / -4,696.75 | 251.33 / -2,895.81 / -3,610.22 |
| +100 | 2,323.56 / -841.01 / -942.02 | 2,111.95 / -64.49 / -654.47 | 1,751.50 / 224.22 / 50.48 |

Interpretation:

- v1.2 materially reduces fixed-anchor HYDROGEL tail risk under persistent shifted paths.
- v1 still wins public replay and some neutral/up-shift means.
- v1.2 does not dominate every stress: neutral and `+30` synthetic p05 are worse than v1,
  and the hydrogel-liquidity research MC mean worsened versus v1.
- v1.2 is therefore a stronger final-simulation robustness candidate, not a proven final
  submission.

Next highest-EV task:

- Run a fresh MC seed batch and a second mean-shift batch for v1 vs v1.2.
- If v1.2 keeps the tail advantage without a new breach or severe replay loss, promote it
  over v1 for final-simulation risk. Otherwise keep v1 as the active historical baseline.
