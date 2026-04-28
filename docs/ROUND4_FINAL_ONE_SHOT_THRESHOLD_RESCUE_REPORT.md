# Round 4 Final One-Shot Threshold Rescue Report

## 1. Verdict

Verdict: **PROMOTE_FINAL_ONE_SHOT**.

Promoted variant: **V2_CAP_SAFE_THRESHOLD**.

Final submission file: `strategies/r4_trader.py`.

Rationale: V2 keeps most of the rejected threshold upside while removing the specific cap-dwell failure. Versus active M3 it improves base total by **+57,201**, adverse voucher by **+35,287**, harsh voucher by **+26,579**, improves every day split, has zero breaches, lowers BS net-delta p95, and does not increase BS net-delta max.

## 2. Active Submission File

`strategies/r4_trader.py` was first integrated from accepted M3 and replayed at **619,806** with zero breaches.

After V2 passed, `strategies/r4_final_one_shot_candidate.py` was set to `THRESHOLD_RESCUE["mode"] = "cap_safe"` and copied to `strategies/r4_trader.py`.

`strategies/r4_trader.py` therefore no longer byte-matches accepted M3. It is now the promoted final one-shot submission file.

## 3. Changed Files

- `archive/r4_trader_pre_m3_integration.py`
- `strategies/r4_trader.py`
- `strategies/r4_final_one_shot_candidate.py`
- `analysis/r4_final_one_shot_threshold_rescue.py`
- `docs/ROUND4_FINAL_ONE_SHOT_THRESHOLD_RESCUE_REPORT.md`

## 4. Commands Run

```powershell
git pull
git status --short --branch
git log --oneline -5
git diff --stat
git rev-parse HEAD
python -m py_compile strategies/r4_trader.py strategies/r4_final_one_shot_candidate.py
python -m prosperity_backtester replay strategies/r4_trader.py --round 4 --data-dir data/round4 --days 1 2 3 --fill-mode base --output-dir backtests/r4_trader_m3_integration_replay
python -m prosperity_backtester replay strategies/r4_final_one_shot_candidate.py --round 4 --data-dir data/round4 --days 1 2 3 --fill-mode base --output-dir backtests/r4_final_one_shot_default_replay
python -m py_compile analysis/r4_final_one_shot_threshold_rescue.py strategies/r4_trader.py strategies/r4_final_one_shot_candidate.py
python -m analysis.r4_final_one_shot_threshold_rescue
python -m py_compile strategies/r4_trader.py strategies/r4_final_one_shot_candidate.py analysis/r4_final_one_shot_threshold_rescue.py
python -m prosperity_backtester replay strategies/r4_trader.py --round 4 --data-dir data/round4 --days 1 2 3 --fill-mode base --output-dir backtests/r4_final_promoted_replay
python -m prosperity_backtester verify-round4 --data-dir data/round4 --output-dir backtests/r4_final_one_shot_verify_fast_strict --fast --strict
pytest -q -k "round4 or r4" --timeout=120
python -m pytest -q -k "round4 or r4" --timeout=120
```

The direct `pytest` command failed because `pytest` was not on PATH. `python -m pytest` passed.

## 5. Variant Table

| Variant | Base total | Voucher PnL | Day 1 | Day 2 | Day 3 | Adverse voucher | Harsh voucher | Breaches | Net delta p95 | Net delta max | VEV_4000 dwell | VEV_4500 dwell | VEV_5100 dwell | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| V0_ACTIVE_M3 | 619,806 | 443,614 | 237,054 | 188,072 | 212,980 | 233,019 | 145,617 | 0 | 1,689 | 1,854 | 74.8% | 74.8% | 82.9% | Baseline |
| V1_REJECTED_REFERENCE | 688,843 | 512,651 | 256,082 | 189,039 | 247,676 | 278,560 | 181,903 | 0 | 1,676 | 1,854 | 80.3% | 77.2% | 92.1% | Reject, cap dwell failure |
| V2_CAP_SAFE_THRESHOLD | 677,007 | 500,815 | 254,371 | 190,070 | 245,569 | 268,306 | 172,196 | 0 | 1,676 | 1,854 | 70.8% | 68.2% | 79.5% | **Promote** |
| V3_DELTA_ADD_GATED_THRESHOLD | 675,044 | 498,852 | 260,937 | 188,607 | 245,355 | 262,112 | 164,174 | 0 | 1,679 | 1,854 | 71.2% | 71.0% | 91.9% | Reject, 5100 dwell still high |
| V4_COMBINED_CAP_AND_DELTA_SAFE | 671,480 | 495,288 | 257,932 | 189,485 | 244,159 | 261,121 | 164,261 | 0 | 1,679 | 1,854 | 71.3% | 71.0% | 79.5% | Good, but dominated by V2 |
| V5_SELECTIVE_STRIKE_THRESHOLD | 658,422 | 482,230 | 265,684 | 174,488 | 236,831 | 244,174 | 145,683 | 0 | 1,680 | 1,854 | 74.8% | 74.8% | 79.5% | Reject, day 2 worsens >3% |

## 6. Cap And Delta Diagnostics

| Variant | 4000 | 4500 | 5000 | 5100 | 5200 | 5300 | 5400 | 5500 | Net p95 | Net max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Active M3 | 74.8% | 74.8% | 75.9% | 82.9% | 93.5% | 91.7% | 30.9% | 23.0% | 1,689 | 1,854 |
| Rejected reference | 80.3% | 77.2% | 75.9% | 92.1% | 93.5% | 91.7% | 30.9% | 23.0% | 1,676 | 1,854 |
| Promoted V2 | 70.8% | 68.2% | 75.9% | 79.5% | 93.5% | 91.7% | 30.9% | 23.0% | 1,676 | 1,854 |

Known-danger side dwell:

| Product | Active short | Active long | Rejected short | Rejected long | V2 short | V2 long |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| VEV_4000 | 37.6% | 37.2% | 40.6% | 39.7% | 36.7% | 34.1% |
| VEV_4500 | 37.8% | 37.1% | 40.4% | 36.8% | 36.9% | 31.3% |
| VEV_5100 | 37.5% | 45.4% | 45.3% | 46.8% | 39.8% | 39.7% |

## 7. Threshold Edge Diagnosis

The rejected +69,037 base uplift came only from three voucher changes:

| Product | Threshold change | Rejected PnL lift |
| --- | --- | ---: |
| VEV_4000 | 1.50 to 1.75 | +13,678 |
| VEV_4500 | 1.50 to 1.75 | +14,479 |
| VEV_5100 | 1.50 to 1.00 | +40,880 |

`VEV_4000` and `VEV_4500` gained from the raised threshold removing some active z-score trades. That also increased time near cap, so the raw edge was not clean execution. `VEV_5100` gained from extra lower-threshold orders and caused the largest cap-dwell deterioration.

V2 blocks only threshold-delta orders that would increase absolute voucher inventory when already near cap: `abs(position) >= 250`, and `>= 225` for `VEV_4000`, `VEV_4500`, `VEV_5100`. It also restores baseline risk-reducing orders near cap when the raised threshold would have removed them. This preserved most of the upside and made cap dwell better than active M3 on all three danger strikes.

No timestamp, day, name, Mark22, gamma, BS residual, or passive-MM logic was added.

## 8. Final Recommendation

Submit `strategies/r4_trader.py`.

Remaining risk: the strategy is still public-replay validated, not final-simulation proven. V2 is accepted because its improvement survives day split, adverse and harsh fills, cap dwell diagnostics, and BS net-delta diagnostics. It does not prove the hidden simulation will preserve the threshold edge.
