# Round 4 Voucher Risk Hardening Report

## Verdict

Accepted: `M3_upper_long_cap_200` in `strategies/r4_voucher_risk_hardened_candidate.py`.

This is a targeted cap on positive inventory in `VEV_5400` and `VEV_5500` only. It preserves 99.75% of M0 base PnL and improves harsh-fill voucher PnL by 5.28%. It does not make M0 clean, and it does not prove final-simulation robustness from public replay alone.

## File Status

- `strategies/r4_hydro_velvet_m4_candidate.py`: untouched, previous active candidate preserved.
- `strategies/r4_trader.py`: untouched.
- `strategies/r4_voucher_risk_hardened_candidate.py`: new promoted candidate, default `VOUCHER_RISK["mode"] = "M3_upper_long_cap_200"`.
- `analysis/voucher_m0_risk_forensics.py`: new forensic and validation runner.
- Backtest artefacts used: `backtests/r4_voucher_m0_forensics/`.

## M0 Forensic Audit

M0 base replay:

| Metric | Value |
|---|---:|
| Total PnL | 621,368 |
| HYDROGEL | 99,005 |
| VELVET | 77,187 |
| Vouchers | 445,176 |
| Deep bucket | 133,213 |
| Central bucket | 293,905 |
| Upper bucket | 18,058 |
| Breaches | 0 |

Per-strike M0 summary:

| Strike | PnL | Final pos | Mean abs pos | +300 time | -300 time | Fill count | Markout5 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 4000 | 59,406 | -300 | 248.1 | 37.14% | 37.52% | 566 | 0.226 |
| 4500 | 73,807 | -300 | 247.4 | 36.98% | 37.34% | 669 | 2.311 |
| 5000 | 92,023 | -300 | 259.1 | 38.28% | 37.43% | 421 | 7.253 |
| 5100 | 79,252 | -300 | 265.6 | 45.32% | 37.45% | 292 | 7.552 |
| 5200 | 79,870 | -300 | 284.4 | 50.86% | 42.45% | 329 | 6.076 |
| 5300 | 42,760 | -300 | 281.6 | 51.40% | 40.14% | 316 | 3.635 |
| 5400 | 13,283 | +300 | 277.0 | 56.85% | 30.86% | 240 | 1.550 |
| 5500 | 4,775 | +300 | 269.3 | 59.52% | 22.76% | 213 | 0.464 |

Upper vouchers are the only clean surgical target. Central and deep vouchers have much larger public PnL and should not be broadly shrunk from this evidence.

## Delta And Stress

M0 net VELVET-equivalent delta:

| Metric | Value |
|---|---:|
| p05 | -1,765.3 |
| p50 | -203.7 |
| p95 | 1,712.6 |
| max abs | 1,853.6 |

M0 terminal proxy stress:

| Stress | PnL impact |
|---|---:|
| IV -5 vol pts | +6,524 |
| IV -2 vol pts | +2,643 |
| IV +2 vol pts | -2,668 |
| IV +5 vol pts | -6,698 |
| Underlying -100 | +147,022 |
| Underlying -50 | +76,368 |
| Underlying +50 | -80,940 |
| Underlying +100 | -164,799 |
| Upper adverse +5 ticks | -3,000 |
| Deep adverse +5 ticks | -3,000 |
| Terminal full-spread liquidation proxy | -15,300 |

These are proxy diagnostics, not replayed final-simulation outcomes.

## Mode Definitions

- `M0_control`: exact old voucher z-score.
- `M1_diagnostics_only`: diagnostics only, same orders as M0.
- `M2_upper_long_cap_250`: cap positive `5400/5500` inventory at +250.
- `M3_upper_long_cap_200`: cap positive `5400/5500` inventory at +200.
- `M4_5400_only_cap`: cap positive `5400` only.
- `M5_5500_only_cap`: cap positive `5500` only.
- `M6_terminal_upper_reduction`: no observed public effect at tested thresholds.
- `M7_extreme_BS_veto_upper`: no observed public effect at tested edges.
- `M8_extreme_BS_veto_all`: broad diagnostic control, rejected.
- `M9_net_delta_soft_cap`: rejected, too expensive.
- `M10_selective_combined`: cap 200 plus rare BS veto matched M3 exactly on tested rows, rejected as unnecessary complexity.

## Pooled Results

| Mode | Total | Voucher | Upper | Decision |
|---|---:|---:|---:|---|
| M0 | 621,368 | 445,176 | 18,058 | Control |
| M1 | 621,368 | 445,176 | 18,058 | Parity passed |
| M2 cap 250 | 620,637 | 444,445 | 17,327 | Rejected, weak stress gain |
| M3 cap 200 | 619,806 | 443,614 | 16,496 | Accepted |
| M4 5400 cap 250 | 620,717 | 444,525 | 17,407 | Rejected |
| M5 5500 cap 250 | 621,288 | 445,096 | 17,978 | Rejected |
| M8 all-voucher veto | 602,502 | 426,310 | 18,058 | Rejected, broad damage |
| M9 net delta cap 1300 | 520,161 | 343,969 | 667 | Rejected, destroys engine |

## Day Splits

Independent day totals:

| Mode | Day 1 | Day 2 | Day 3 |
|---|---:|---:|---:|
| M0 | 238,735 | 188,760 | 212,180 |
| M3 | 237,054 | 188,072 | 212,980 |
| M3 vs M0 | -1,681 | -688 | +800 |
| M3 vs M0 % | -0.70% | -0.36% | +0.38% |

No independent day split worsened by more than 3%.

## Fill Stress

| Fill mode | M0 total | M3 total | M0 voucher | M3 voucher | Voucher diff |
|---|---:|---:|---:|---:|---:|
| base | 621,368 | 619,806 | 445,176 | 443,614 | -1,562 |
| no_passive | 617,536 | 615,974 | 445,176 | 443,614 | -1,562 |
| worse | 621,368 | 619,806 | 445,176 | 443,614 | -1,562 |
| adverse | 356,206 | 360,954 | 228,271 | 233,019 | +4,748 |
| harsh | 249,857 | 257,162 | 138,312 | 145,617 | +7,305 |

M3 improves harsh voucher PnL by 5.28%, which clears Gate A.

## M3 Risk Stress

M3 terminal proxy stress:

| Stress | M0 | M3 | Change |
|---|---:|---:|---:|
| Upper adverse +5 ticks | -3,000 | -2,000 | +1,000 |
| Terminal full-spread liquidation proxy | -15,300 | -15,100 | +200 |
| IV +5 vol pts | -6,698 | -7,497 | -799 |
| Underlying +100 | -164,799 | -167,374 | -2,575 |
| Underlying -100 | +147,022 | +147,687 | +665 |

The upper cap improves upper inventory shock and harsh-fill tail, but slightly worsens IV-up and underlying-up proxy stress because long upper calls were also a small hedge. This is accepted only because the fill-tail improvement and cap-time reduction are larger and the base cost is small.

## Per-Strike Cap Review

M3 leaves `4000` through `5300` unchanged. It changes only upper positive inventory:

| Strike | M0 PnL | M3 PnL | M0 final | M3 final | M0 +300 time | M3 +300 time |
|---|---:|---:|---:|---:|---:|---:|
| 5400 | 13,283 | 11,957 | +300 | +200 | 56.85% | 0.00% |
| 5500 | 4,775 | 4,539 | +300 | +200 | 59.52% | 0.00% |

Net delta p95 improves from 1,712.6 to 1,689.1, but max abs is unchanged at 1,853.6 because deep and central vouchers dominate. The accepted risk reduction is cap-time and upper-bucket tail reduction, not a full portfolio delta fix.

## Decision

Accepted `M3_upper_long_cap_200` under Gate A:

- Preserves 99.75% of M0 base PnL.
- Improves harsh voucher PnL by 5.28%.
- Does not worsen any independent day split by more than 3%.
- Removes positive +300 cap time for `VEV_5400` and `VEV_5500`.
- Does not touch Hydro, VELVET, deep vouchers, central vouchers, 6000, or 6500.

Rejected modes:

- `M2`: too little harsh/adverse improvement.
- `M4` and `M5`: one-strike caps were too weak.
- `M6` and `M7`: no public effect at tested thresholds.
- `M8`: broad veto damaged voucher PnL.
- `M9`: net-delta caps destroyed the voucher engine.
- `M10`: same tested output as M3, added no value.

## Active Candidate

Promoted candidate: `strategies/r4_voucher_risk_hardened_candidate.py`.

Previous frozen active file remains available and untouched: `strategies/r4_hydro_velvet_m4_candidate.py`.

## Next Step

Run strict verification and keep the promoted candidate only if submission packaging points to `strategies/r4_voucher_risk_hardened_candidate.py`. Do not port this into `r4_hydro_velvet_m4_candidate.py` without explicit approval.
