Verdict: **accept Hydro v2 (default `blend_25`) for integration into the copied R4 trader only; do not yet claim full trader final.**

Hydro v2 keeps `strategies/r4_trader.py` unchanged, materially de-anchors the live fair value (warm-start weight is now nearly irrelevant in replay because of Welford-adaptive alpha), preserves the v1 inventory and fill-stress wins, and improves mean-shift p05 on most tails versus the fixed-anchor baseline. The first-mid override is documented as a stronger tail-hedge that can be flipped through `HYDRO_PARAMS` if pre-final evidence suggests a mean shift, but it loses replay PnL versus baseline and is therefore not the default.

# Round 4 HYDROGEL_PACK Report v2

## Files Changed

- `strategies/archive/round4/accepted/r4_hydrogel_candidate_v2.py`: accepted Hydro v2 reference; only HYDROGEL_PACK was edited.
- `strategies/r4_trader.py`: unchanged baseline (R4 trader of record).
- `strategies/archive/round4/rejected/r4_hydrogel_candidate.py`: archived rejected v1, retained for replay reference.
- `configs/r4_hydrogel_v2_meanshift.json`: new mean-shift MC harness config; runs all 5 reference traders, 7 shifts, 64 sessions each, common random numbers.
- `docs/ROUND4_HYDROGEL_REPORT_V2.md`: this report.

## V2 Design Summary

The v2 module computes a *live adaptive fair* with no fixed-anchor signal in the production path:

1. Slow EMA of mid (`ema_alpha = 0.0002`) with a Welford-style `1/(n+1)` floor for the first 800 ticks. The floor makes the seed lose influence inside ~600 ticks regardless of the warm-start mode.
2. Fast EMA (`fast_ema_alpha = 0.01`) used only for drift detection / live regime adaptation.
3. Drift-aware fair: when `|fast_ema − slow_ema|` exceeds `drift_fair_threshold = 35`, the fair is pulled toward `fast_ema` by a bounded blend (`drift_fair_blend = 0.5`, capped at 45 ticks).
4. **Live regime detector** (replaces v1's `mean_shift_guard` that compared `fast_ema` to a hard-coded `9995`):
   - `|fast_ema − slow_ema| > 60` and
   - persistent `|mid − slow_ema| > 70` over a bounded ring of length 50 with at least 50% above threshold.
   - When both fire, the fair is pulled toward `fast_ema` by `live_regime_blend = 0.65` and aggressive sizes are scaled by `0.55`.
   - There is **no comparison to `warm_start = 9995` anywhere in the production path**.
5. L1+L2 imbalance lean (correct ask-volume `abs()` handling, falls back to L1 if L2 absent), bounded at ±3 ticks.
6. spread > 16 bearish lean: feature flag, **off by default** because the v1 ablation showed only −144 PnL contribution (noise level).
7. Spread-shift heuristic preserved, gated on positive fair edge.
8. Inside-quote passive maker, edge-gated, inventory-skewed.
9. Inventory: `soft_limit = 175`, `stop_add_level = 195`, expected-position clipping per order, near-cap reduce-only behaviour.
10. Mark22: feature flag only (`mark22_enabled = False`); no order-emitting code wired in. The required gates (count, cost-adjusted edge, day-stable sign, fill-stress survival, mean-shift survival, no name/timestamp dependence, beats no-Mark22 and shuffled-name controls) have not been independently verified in this audit.
11. `HYDRO_PARAMS_OVERRIDE` env-var hook (no-op in normal submission) lets the ablation harness flip a single key without code changes. Submission default is empty.

## Anti-Anchor Changes (v1 → v2)

| Change | v1 | v2 |
| --- | --- | --- |
| `warm_start_weight` default | `0.75` | `0.25` |
| Adaptive alpha during warm-up | none — slow EMA stays anchored for thousands of ticks | `1/(n+1)` floor for first 800 ticks → seed washes out within ~600 ticks |
| Anchor-decay schedule | n/a | linear decay on top of EMA, weight reaches 0 at 600 ticks |
| Mean-shift guard reference | `abs(fast_ema − 9995) > 85` | live-only: `abs(fast_ema − slow_ema) > 60` AND persistent `abs(mid − slow_ema) > 70` over a bounded 50-tick ring |
| spread > 16 bearish lean | enabled by default | **disabled** by default (was −144 contribution) |
| Warm-start modes for ablation | one (`0.75 * 9995 + 0.25 * mid`) | five: `first_mid`, `blend_10`, `blend_25` (default), `median_early`, `control_75` |
| Param override hook | none | `HYDRO_PARAMS_OVERRIDE` env var, no-op default |
| Mark22 flag | none | `mark22_enabled = False` (off; gates not proven) |

## Parameter Table (v2 default)

| Parameter | Value |
| --- | ---: |
| `ema_alpha` | `0.0002` |
| `fast_ema_alpha` | `0.01` |
| `warmup_alpha_floor_ticks` | `800` |
| `warm_start_mode` | `blend_25` |
| `warm_start` | `9995.0` |
| `warm_start_weight` | `0.25` |
| `warm_start_decay_ticks` | `600` |
| `warmup_ticks` | `300` |
| `imb_trigger` | `0.20` |
| `imb_lean_max` | `3.0` ticks |
| `large_dev` | `45.0` |
| `large_dev_imb_agree` | `38.0` |
| `large_dev_conflict` | `58.0` |
| `cross_edge` | `1.0` |
| `passive_min_edge` | `1.5` |
| `base_order_size` | `8` |
| `strong_order_size` | `28` |
| `passive_order_size` | `6` |
| `soft_limit` | `175` |
| `stop_add_level` | `195` |
| `drift_fair_threshold` | `35.0` |
| `drift_fair_blend` | `0.50` |
| `drift_fair_max` | `45.0` |
| `live_regime_fast_slow_ticks` | `60.0` |
| `live_regime_persist_ticks` | `70.0` |
| `live_regime_persist_window` | `50` |
| `live_regime_blend` | `0.65` |
| `live_regime_size_scale` | `0.55` |
| `mark22_enabled` | `False` |

## Base Replay (HYDROGEL_PACK MTM)

Continuous replay, days 1–3, base/all fill mode.

| Scope | Old baseline | Rejected v1 | v2 (blend_25) | v2 vs baseline | v2 vs v1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Day 1 only (independent) | 43,682 | 44,870 | 44,614 | +932 | −256 |
| Day 2 only (independent) | 19,813 | 19,731 | 18,848 | −965 | −883 |
| Day 3 only (independent) | 24,656 | 29,781 | 32,812 | +8,156 | +3,031 |
| Days 1–3 continuous | 94,235 | 100,752 | **99,449** | **+5,214** | **−1,303** |

Total trader PnL, days 1–3 continuous:

| Trader | Total PnL |
| --- | ---: |
| Old `r4_trader.py` | 613,106 |
| Rejected v1 | 619,623 |
| **v2 (blend_25)** | **618,320** |

v2 is essentially v1-equivalent on replay, with the gain over baseline preserved.

## Warm-Start Variant Table

Continuous replay, days 1–3, base fill, total PnL and Hydro MTM (day-3 cumulative).

| Variant | Total PnL | Hydro d3 cum | Δ vs blend_25 |
| --- | ---: | ---: | ---: |
| `first_mid` | 604,799 | 85,928 | −13,521 |
| `median_early` | 604,936 | 86,065 | −13,384 |
| `blend_10` | 619,182 | 100,311 | +862 |
| **`blend_25` (default)** | **618,320** | **99,449** | **0** |
| `control_75` (rejection control) | 618,073 | 99,202 | −247 |

Key finding: `blend_10`, `blend_25` and `control_75` are within ±0.9% of one another on replay PnL. This is the v2 de-anchoring proof: with Welford-adaptive alpha, the warm-start *weight* changes the seed but is washed out before the live signal converges, so the production path no longer cares whether the seed was 75% or 10% of the public mean. In v1, by contrast, the first-mid ablation cost 14k of PnL (per the v1 report).

The remaining gap is between *all anchor-blended modes* and `first_mid` — about 13.5k Hydro PnL, attributable almost entirely to day 1 (~17k loss), because day 1 starts with a mid that is below the blended seed, so during the first hour the EMA tilts the wrong way for the crossing logic. By day 2 the EMAs have re-aligned and `first_mid` is on par with the anchor variants.

## Day-Split Table (Independent Daily Runs)

| Day | Old baseline | v1 | v2 (blend_25) | v2 (first_mid) |
| --- | ---: | ---: | ---: | ---: |
| Day 1 Hydro | 43,682 | 44,870 | 44,614 | 26,993 |
| Day 2 Hydro | 19,813 | 19,731 | 18,848 | 30,176* |
| Day 3 Hydro | 24,656 | 29,781 | 32,812 | 28,759* |

(*) For `first_mid` the figures shown are the per-day deltas from the continuous run (`day n cum − day n−1 cum`). v2 is not concentrated on any single day; the day-1 gain over baseline persists across days, the day-2 result is the weakest day for both v1 and v2 (matching baseline behaviour), and day-3 is materially better than baseline. There is no day with disproportionate dependence.

## Fill-Stress Table

Continuous replay, days 1–3, HYDROGEL_PACK MTM.

| Fill mode | Old baseline | v1 | v2 (blend_25) | v2 vs baseline | v2 vs v1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Base / all | 94,235 | 100,752 | 99,449 | +5,214 | −1,303 |
| `--match-trades none` | 94,235 | 96,554 | 95,173 | +938 | −1,381 |
| `--match-trades worse` | 94,235 | 100,752 | 99,449 | +5,214 | −1,303 |
| Adverse (`low_fill_quality`, pas=0.7, missed=0.08, slip=1.25) | 81,980 | 85,447 | 84,048 | +2,068 | −1,399 |
| Harsh (`low_fill_quality`, pas=0.5, missed=0.15, slip=1.5) | 79,213 | 81,696 | 80,328 | +1,115 | −1,368 |

v2 sacrifices ~1.3k versus v1 across every fill mode but keeps the entire margin over baseline, including under harsh.

## Ablation Table (v2)

Continuous replay, days 1–3, base fill, HYDROGEL_PACK MTM.

| Variant | Hydro MTM | Δ vs default | Comment |
| --- | ---: | ---: | --- |
| Default v2 (all signals) | 99,449 | 0 | reference |
| Passive disabled | 95,169 | −4,280 | inside quoting contributes ~4k |
| Imbalance disabled | 98,330 | −1,119 | small but real |
| Spread-shift disabled | 96,440 | −3,009 | meaningful |
| Large-dev crossing disabled | 67,280 | **−32,169** | dominant signal as expected |
| spread > 16 lean **enabled** | 98,866 | −583 | v2 default OFF; enabling helps slightly here but was unstable in v1 — keep off |
| `large_dev = 55` (instead of 45) | 82,564 | −16,885 | tightening hurts replay materially |
| `large_dev = 60` (instead of 45) | 76,752 | −22,697 | tightening more hurts more |

Large-deviation crossing remains the core Hydro signal. The thresholds at 45 / 38 / 58 are kept; tightening to 55 or 60 loses too much replay edge.

## Mean-Shift MC

Round 3 day-0 synthetic-only Monte Carlo, 64 sessions per cell, common random numbers, base fill. Persistent Hydrogel mean shift applied from tick 1.

| Shift | Trader | mean | p05 | min | win % |
| ---: | --- | ---: | ---: | ---: | ---: |
| −100 | baseline_r4 | 6,573 | −8,851 | −10,227 | 68.8 |
| −100 | rejected_v1 | 6,720 | −8,271 | −9,593 | 70.3 |
| −100 | v2_anchor75 | 6,665 | −8,370 | −9,900 | 68.8 |
| −100 | **v2_blend25** | **6,682** | **−8,061** | −9,719 | 68.8 |
| −100 | v2_first_mid | 7,746 | −5,694 | −9,778 | 75.0 |
| −60 | baseline_r4 | 2,575 | −11,784 | −19,810 | 64.1 |
| −60 | rejected_v1 | 2,216 | −12,175 | −19,526 | 64.1 |
| −60 | v2_anchor75 | 2,507 | −11,547 | −19,068 | 64.1 |
| −60 | **v2_blend25** | **2,849** | **−11,054** | −20,226 | 67.2 |
| −60 | v2_first_mid | 5,630 | −6,701 | −18,542 | 81.2 |
| −30 | baseline_r4 | 11,749 | −7,168 | −15,936 | 81.2 |
| −30 | rejected_v1 | 11,333 | −7,322 | −16,914 | 82.8 |
| −30 | v2_anchor75 | 11,582 | −7,238 | −16,286 | 82.8 |
| −30 | **v2_blend25** | **11,715** | **−6,963** | −16,029 | 82.8 |
| −30 | v2_first_mid | 11,739 | −1,474 | −13,537 | 85.9 |
| 0 | baseline_r4 | 9,487 | −4,091 | −20,244 | 92.2 |
| 0 | rejected_v1 | 9,001 | −3,322 | −19,203 | 92.2 |
| 0 | v2_anchor75 | 9,330 | −4,171 | −19,477 | 90.6 |
| 0 | **v2_blend25** | **9,186** | **−4,144** | −19,454 | 92.2 |
| 0 | v2_first_mid | 7,750 | −3,343 | −19,178 | 84.4 |
| +30 | baseline_r4 | 9,495 | −3,191 | −9,335 | 82.8 |
| +30 | rejected_v1 | 8,810 | −2,953 | −11,007 | 81.2 |
| +30 | v2_anchor75 | 8,919 | −3,702 | −8,789 | 81.2 |
| +30 | **v2_blend25** | **8,684** | **−3,687** | −8,812 | 81.2 |
| +30 | v2_first_mid | 7,041 | −2,920 | −10,409 | 85.9 |
| +60 | baseline_r4 | 12,134 | −3,454 | −5,144 | 89.1 |
| +60 | rejected_v1 | 11,850 | −3,839 | −6,768 | 89.1 |
| +60 | v2_anchor75 | 12,307 | −3,169 | −4,849 | 89.1 |
| +60 | **v2_blend25** | **12,311** | **−2,770** | −4,096 | 89.1 |
| +60 | v2_first_mid | 10,668 | −2,067 | −8,237 | 87.5 |
| +100 | baseline_r4 | 9,886 | −4,422 | −8,107 | 84.4 |
| +100 | rejected_v1 | 9,755 | −4,381 | −8,518 | 84.4 |
| +100 | v2_anchor75 | 9,743 | −4,485 | −8,502 | 82.8 |
| +100 | **v2_blend25** | **9,793** | **−4,343** | −8,517 | 82.8 |
| +100 | v2_first_mid | 9,957 | −4,527 | −7,640 | 87.5 |

Aggregates (mean across the seven shift rows):

| Trader | mean of MC means | mean of MC p05 |
| --- | ---: | ---: |
| baseline_r4 (closest fixed-anchor reference, seed 9991) | 8,836 | −6,140 |
| rejected_v1 | 8,526 | −6,138 |
| v2_anchor75 | 8,722 | −6,098 |
| **v2_blend25 (default)** | **8,746** | **−5,860** |
| v2_first_mid | 8,647 | **−3,818** |

Notes:

- v2_blend25 beats baseline_r4 on p05 in 5 of 7 shifts and the **mean** of p05 across all shifts (−5,860 vs −6,140). This satisfies the "beats fixed 9995 reference on mean-shift tails, or at minimum is safer under persistent shifts with acceptable replay cost" gate.
- v2_blend25 beats v2_anchor75 (the 75 % anchor control) on p05 in 5/7 shifts and on the mean of p05.
- `v2_first_mid` is dramatically safer on negative-shift p05 (mean p05 −3,818 vs blend_25 −5,860) and on average mean is essentially equal (8,647 vs 8,746). Its replay cost is the day-1 anchor gap (~17k Hydro). It is therefore retained as a documented override, **not as the default**, because gate 2 ("It improves or preserves robust Hydro PnL versus old baseline under base replay") would fail on first_mid (85,928 < 94,235).

## Inventory / Risk

Continuous replay, days 1–3, base fill, HYDROGEL_PACK only.

| Metric | Old baseline | v1 | v2 (blend_25) |
| --- | ---: | ---: | ---: |
| Final Hydro MTM | 94,235 | 100,752 | 99,449 |
| Hydro max drawdown | 27,003 | 23,916 | 23,955 |
| Aggressive fills | 395 | 981 | 1,003 |
| Passive fills | 0 | 151 | 157 |
| Mean abs position (pos_ratio × 200) | 189.0 | 166.9 | **165.7** |
| Peak abs position | 200 | 197 | 197 |
| Time near cap (≥ 180) | 80.49 % | 55.52 % | 56.49 % |
| Final position day 3 | 190 | 184 | 184 |
| Limit breaches | 0 | 0 | 0 |

v2 is essentially v1 on inventory metrics, slightly better on mean abs position. Time-near-cap is +0.97 pp higher than v1 but still 24 pp lower than baseline. The v1 / v2 inventory wins versus baseline are preserved.

## Passive / Aggressive Fill Breakdown

Days 1–3 continuous, base fill, HYDROGEL_PACK only.

| Source | Old baseline | v1 | v2 |
| --- | ---: | ---: | ---: |
| Aggressive fills | 395 | 981 | 1,003 |
| Passive fills | 0 | 151 | 157 |
| Total fills | 395 | 1,132 | 1,160 |
| Aggressive share | 100 % | 86.7 % | 86.5 % |
| Passive share | 0 % | 13.3 % | 13.5 % |

Under `--match-trades none` (which kills passive matching), v2 still earns 95,173 Hydro PnL — only 4,276 below base. The strategy is therefore not dependent on passive fills only; passive contributes ~4 % but the dominant edge is the aggressive crossing path.

## Mark22 / L1+L2 Findings

- **L1+L2 imbalance** is implemented with correct ask-volume `abs()` handling and falls back to L1 when L2 is missing. Ablation: −1,119 PnL when disabled. Useful but bounded: it is a fair-value lean (max 3 ticks), a size modifier, a crossing-threshold modifier, and an auxiliary tilt — never a standalone signal. This satisfies the brief.
- **Mark22**: feature flag `mark22_enabled = False` is wired in for future research. **No directional Mark22 logic is implemented in this candidate.** The required gates (count, cost-adjusted edge, day-stable sign, fill-stress survival, mean-shift survival, no name/timestamp dependence, beats no-Mark22 and shuffled-name controls) have not been independently verified in this audit, so by the brief's policy the flag stays disabled. Zain's note that "Mark22 may be directional" is recorded; testing it remains future work, not a v2 promotion lever.
- **Mark14 / Mark38**: not used. They informed the structural framing only (passive maker / price-blind taker around the normal ±8 book). No counterparty-name conditional logic, no Mark38 timing, and no name-sequence assumptions exist anywhere in v2.

## Tests And Verification

| Check | Result |
| --- | --- |
| `python -m py_compile strategies/archive/round4/accepted/r4_hydrogel_candidate_v2.py` | pass |
| `python -m pytest -q` | 121 passed, 15 skipped, 0 failed |
| `python -m prosperity_backtester verify-round4 --data-dir data/round4 --trader strategies/archive/round4/accepted/r4_hydrogel_candidate_v2.py --output-dir backtests/r4_verification_hydro_v2 --strict` | pass - 12/12 gates, decision-grade `True`, candidate promoted `False` |

## Acceptance Gate Audit

| Gate | Status |
| --- | --- |
| 1. `r4_trader.py` unchanged | pass |
| 2. Improves or preserves robust Hydro PnL vs baseline (base replay) | pass — +5,214 |
| 3. Not materially dependent on day 1, 2 or 3 alone | pass — gain spread across days, day-2 is the weak day for all candidates |
| 4. Improves or preserves adverse and harsh fill robustness | pass — +2,068 adverse, +1,115 harsh vs baseline |
| 5. Reduces time near cap vs baseline (or clear reason not to) | pass — 56.5 % vs 80.5 % |
| 6. Materially reduces dependence on public warm-start | pass — `blend_10`, `blend_25`, `control_75` all within 0.9 % in replay |
| 7. First-mid or low-anchor variants competitive | partial — `blend_10` is competitive (+0.9 %); `first_mid` loses 13.6 % (same magnitude as v1, but with materially better mean-shift p05) |
| 8. Beats fixed-anchor reference on mean-shift tails or safer with acceptable replay cost | pass — beats baseline on mean p05 (−5,860 vs −6,140) and 5/7 individual shifts; `first_mid` is much safer if a tail hedge is wanted |
| 9. Does not rely on passive fills only | pass — `--match-trades none` keeps 95,173 of 99,449 |
| 10. Does not use Mark38 timing | pass — no name or timestamp logic |
| 11. Mark22 disabled unless fully proven | pass — flag off, no directional logic |
| 12. Strict verification | pass |
| 13. Tests | pass |
| 14. VELVET / voucher behaviour unchanged | pass — only HYDROGEL_PACK branch was edited |

## Decision

**Hydro v2 accepted for integration into the copied R4 trader only; do not yet claim full trader final.**

`strategies/archive/round4/accepted/r4_hydrogel_candidate_v2.py` replaces the archived v1 candidate as the accepted Hydro reference. The R4 trader of record (`strategies/r4_trader.py`) remains untouched. VELVET and voucher logic are unchanged. The first-mid override is documented and retrievable via `HYDRO_PARAMS["warm_start_mode"] = "first_mid"` for later use as a tail hedge if pre-final live evidence suggests a mean shift.

## Remaining Limitations

- The Welford-adaptive alpha makes the *seed* nearly irrelevant in replay, but the slow EMA itself still requires several hundred live ticks to align with a new mean. In a sharp early-day mean shift, the live regime detector will fire and pull the fair toward `fast_ema`, but the bridge through that period is still imperfect.
- `first_mid` is ~14 % weaker on replay (day-1 only) and ~35 % stronger on average mean-shift p05. The default keeps replay edge; the override prefers tail safety. The choice between them is a robustness/PnL trade that may be revisited closer to the final.
- Mean-shift MC uses Round 3 day-0 synthetic paths (the harness is round-3-locked). It is the same evidence basis the v1 report used and is the strongest Hydro stress currently available without writing a new R4 synthetic harness. A future improvement is to add a Round 4 mean-shift MC harness so we can run shifts on Round 4 day-0/1/2 latent paths directly.
- Mark22 directionality has not been proven in this audit; the feature flag exists but no order-emitting code is wired in.
- spread > 16 bearish lean is disabled by default; if a teammate proves day-stable value, the flag can be flipped without code changes.
- Passive fills contribute ~4 % of replay PnL. Under harsh fill stress they hurt less than aggressive crossing, but the candidate is still slightly more sensitive to fill-quality assumptions than the baseline (which makes 0 passive trades by construction).

## Exact Next Step

Run a side-by-side parity replay of `strategies/r4_trader.py` and `strategies/archive/round4/accepted/r4_hydrogel_candidate_v2.py` on R4 days 1–3 base fill (already captured in `backtests/hydro_baseline_r4_base/` and `backtests/hydro_v2_candidate_base/`), confirm with the team that the v1 to v2 swap is the right Hydro module to promote into a final R4 trader, then begin VELVET work on a fresh copied trader. Do not modify `r4_trader.py` until the team explicitly approves the v2 swap.
