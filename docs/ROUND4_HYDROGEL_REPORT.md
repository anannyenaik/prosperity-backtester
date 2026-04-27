Result: reject final Hydro promotion for now. The copied candidate improves public replay and fill stress, but mean-shift MC is not materially better than a fixed 9995-anchor rejection reference.

# Round 4 HYDROGEL_PACK Report

## Files

- `strategies/r4_hydrogel_candidate.py`: copied from `strategies/r4_trader.py`; only HYDROGEL_PACK logic was changed.
- `strategies/r4_trader.py`: unchanged baseline.
- `docs/ROUND4_HYDROGEL_REPORT.md`: this report.

## Design Summary

The candidate combines live slow EMA fair, weak bounded warm-start context, fast-EMA drift detection, L1+L2 imbalance, positive-edge inside quotes, capped aggressive mean reversion, inventory skew, warm-up size reduction, spread abnormality size reduction, and expected-position order clipping.

No counterparty names, timestamp rules, Mark38 timing, Mark22 Hydro logic, external files, or voucher/VELVET changes were added.

## Parameter Table

| Parameter | Value |
| --- | ---: |
| `ema_alpha` | `0.0002` |
| `fast_ema_alpha` | `0.01` |
| `warm_start` | `9995.0` |
| `warm_start_weight` | `0.75` |
| `warmup_ticks` | `300` |
| `imb_trigger` | `0.20` |
| `imb_lean_max` | `3.0` ticks |
| `large_dev` | `45.0` |
| `large_dev_imb_agree` | `38.0` |
| `large_dev_conflict` | `58.0` |
| `base_order_size` | `8` |
| `strong_order_size` | `28` |
| `passive_order_size` | `6` |
| `soft_limit` | `175` |
| `stop_add_level` | `195` |
| `drift_fair_threshold` | `35.0` ticks |
| `mean_shift_guard_ticks` | `85.0` ticks |

## Base Replay

Hydro-only MTM:

| Scope | Old Hydro | New Hydro | Delta |
| --- | ---: | ---: | ---: |
| Day 1 only | 43,682 | 44,870 | +1,188 |
| Day 2 only | 19,813 | 19,731 | -82 |
| Day 3 only | 24,656 | 29,781 | +5,125 |
| Days 1-3 continuous | 94,235 | 100,752 | +6,517 |

Total trader PnL, days 1-3 continuous:

| Trader | Total PnL |
| --- | ---: |
| Old `r4_trader.py` | 613,106 |
| New candidate | 619,623 |

## Risk And Attribution

| Metric | Old Hydro | New Hydro |
| --- | ---: | ---: |
| Final Hydro MTM | 94,235 | 100,752 |
| Realised Hydro PnL | 88,270.16 | 94,585.89 |
| Unrealised Hydro PnL | 5,964.84 | 6,166.11 |
| Aggressive fills | 395 | 981 |
| Passive fills | 0 | 151 |
| Mean abs position | 189.02 | 166.88 |
| Peak abs position | 200 | 197 |
| Time abs position >= 180 | 80.49% | 55.52% |
| Time abs position >= 195 | 67.35% | 35.72% |
| Position p05 / median / p95 | -200 / -160 / 200 | -195 / -90 / 195 |
| Hydro max drawdown | 27,003 | 23,916 |

## Fill Stress

Hydro-only MTM, days 1-3 continuous:

| Fill mode | Old Hydro | New Hydro | Delta |
| --- | ---: | ---: | ---: |
| Base / all | 94,235 | 100,752 | +6,517 |
| No passive | 94,235 | 96,554 | +2,319 |
| Worse | 94,235 | 100,752 | +6,517 |
| Adverse | 81,980 | 85,447 | +3,467 |
| Harsh | 79,213 | 81,696 | +2,483 |

## Ablation

Hydro-only MTM, days 1-3 continuous, base fill:

| Variant | Hydro MTM | Delta vs new |
| --- | ---: | ---: |
| New all signals | 100,752 | 0 |
| Hydro disabled | 0 | -100,752 |
| Passive disabled | 96,550 | -4,202 |
| Imbalance disabled | 97,067 | -3,685 |
| Spread-shift disabled | 96,636 | -4,116 |
| Large-dev crossing disabled | 67,480 | -33,272 |
| Spread lean disabled | 100,608 | -144 |
| First-mid warm-start | 86,411 | -14,341 |

Large-deviation crossing is the core signal. Passive, imbalance, and spread-shift each help, but the first-mid ablation shows the current candidate still depends too much on warm-start context.

## Mean-Shift MC

8 sessions, synthetic tick limit 500, shock tick 1, seed `20260427`. Values are Hydro MTM means with p05 in brackets.

| Hydro shift | Old Hydro | New Hydro | Fixed 9995 anchor |
| ---: | ---: | ---: | ---: |
| -100 | -3,036 (-10,040) | -2,965 (-9,870) | -2,922 (-9,814) |
| -60 | -2,495 (-9,499) | -3,007 (-9,903) | -3,047 (-9,600) |
| -30 | 532 (-4,258) | 220 (-4,435) | 410 (-4,094) |
| 0 | 1,977 (-123) | 1,174 (-118) | 1,816 (-31) |
| +30 | 2,688 (-583) | 1,848 (-753) | 2,822 (-93) |
| +60 | 1,209 (-4,561) | 922 (-5,149) | 1,291 (-3,715) |
| +100 | -127 (-8,026) | -239 (-7,716) | -153 (-7,370) |

This fails the anti-overfit gate. The candidate is not a public fixed-mean script, but the current parameters do not beat the fixed-anchor reference under enough mean-shift MC rows to justify final promotion.

## Verification

Passed:

- `python -m py_compile strategies/r4_hydrogel_candidate.py`
- `python -m pytest -q`: 121 passed, 15 skipped.
- `python -m prosperity_backtester verify-round4 --data-dir data/round4 --trader strategies/r4_hydrogel_candidate.py --output-dir backtests/r4_verification_hydro --strict`: pass, decision-grade true, candidate promoted false.

Baseline before edits:

- `python -m prosperity_backtester verify-round4 --data-dir data/round4 --trader strategies/r4_trader.py --output-dir backtests/hydro_baseline_verify_fast --fast`: pass.

## Decision

Reject Hydro final promotion. Keep the candidate for side-by-side replay because it improves base, no-passive, adverse, harsh, and inventory risk, but do not move to VELVET yet.

Minimum next fixes:

- Reduce warm-start dependence while preserving day-split replay.
- Improve mean-shift MC versus the fixed-anchor reference, especially `0`, `+30`, and `+60`.
- Re-run day splits, fill stress, ablations, and strict verification after any parameter change.
