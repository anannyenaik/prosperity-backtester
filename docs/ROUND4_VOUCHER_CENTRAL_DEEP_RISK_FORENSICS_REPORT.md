Result: PASS_RAW, REJECT_CANDIDATE. Active M3 remains best.

The raw central/deep risk is real: final inventory is structurally short calls from VEV_4000 through VEV_5300, BS net-delta max is 1,853.6, and terminal VELVET +100 proxy is -167.4k. The risk is not free to remove. VEV_5300 is the weakest central strike and justified candidate testing, but one-sided caps and stop-add gates bought only small stress relief while cutting replay PnL. Net-delta add gates improved adverse/harsh fill stress at 1700, but did not reduce p95 net delta, did not improve terminal shock, and cost 10.1k base PnL. Stronger gates were destructive. Do not promote the new research candidate. Submit remains `strategies/r4_voucher_risk_hardened_candidate.py`.

## Repo State

| Item | Value |
| --- | --- |
| Starting commit | `b055ba239cf5bacb189f9626b41d83b33b96eeda` |
| Branch | `main` |
| Status before edits | no tracked diff, existing untracked research files present |
| Active baseline | `strategies/r4_voucher_risk_hardened_candidate.py`, `M3_upper_long_cap_200` |
| Control | `strategies/r4_trader.py` |
| Files changed by this pass | `analysis/voucher_central_deep_risk_forensics.py`, `strategies/r4_voucher_central_deep_hardened_candidate.py`, this report |

Generated forensic artefacts in `backtests/r4_voucher_central_deep_risk_forensics/`:

`summary.json`, `multi_delta_summary.json`, `multi_delta_per_tick.csv`, `empirical_delta_per_strike_day.json`, `empirical_delta_pooled.json`, `cap_entry_events.csv`, `cap_entry_summary.csv`, `marginal_add_attribution_250.csv`, `marginal_add_attribution_275.csv`, `extended_stress_matrix.json`, `day_attribution_stability.json`, plus derived `extreme_net_delta_adds.csv/json`.

Candidate grid artefacts are in `backtests/r4_voucher_central_deep_candidate_grid/`.

## Active M3 Recap

| Metric | Value |
| --- | ---: |
| Total PnL | 619,806 |
| Voucher PnL | 443,614 |
| Day 1 independent PnL | 237,054 |
| Day 2 independent PnL | 188,072 |
| Day 3 independent PnL | 212,980 |
| Fill stress, base voucher | 443,614 |
| Fill stress, adverse voucher | 233,019 |
| Fill stress, harsh voucher | 145,617 |
| BS net delta p95 | 1,689.1 |
| BS net delta max abs | 1,853.6 |

Final positions: VEV_4000 -300, VEV_4500 -300, VEV_5000 -300, VEV_5100 -300, VEV_5200 -300, VEV_5300 -300, VEV_5400 +200, VEV_5500 +200, VEV_6000 0, VEV_6500 0, VELVET -200.

## Central/Deep Attribution

Stress loss is terminal VELVET +100 proxy contribution. Cap dwell is share of ticks with `abs(position) >= 290`.

| Product | Bucket | Day 1 | Day 2 | Day 3 | Pooled | Final pos | Time +300 | Time -300 | Near cap | Cap dwell | Stress loss | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| VEV_4000 | deep | 18,637 | 18,694 | 25,567 | 59,406 | -300 | 37.1% | 37.5% | 74.7% | 74.7% | -30,000 | Keep, profitable but directional |
| VEV_4500 | deep | 22,401 | 28,123 | 29,078 | 73,807 | -300 | 37.0% | 37.3% | 74.3% | 74.3% | -30,000 | Keep, strong contribution |
| VEV_5000 | central | 30,538 | 32,880 | 34,105 | 92,023 | -300 | 38.3% | 37.4% | 75.7% | 75.7% | -29,523 | Keep, main engine |
| VEV_5100 | central | 23,214 | 30,589 | 29,781 | 79,252 | -300 | 45.3% | 37.5% | 82.8% | 82.8% | -27,467 | Keep, main engine |
| VEV_5200 | central | 36,162 | 23,819 | 24,710 | 79,870 | -300 | 50.9% | 42.5% | 93.3% | 93.3% | -21,974 | Useful but large risk |
| VEV_5300 | central | 18,574 | 8,153 | 11,426 | 42,760 | -300 | 51.4% | 40.1% | 91.5% | 91.5% | -13,560 | Weakest target, but cap tests failed |

Central total is 293,905. Deep total is 133,213. Removing these exposures broadly would remove most of the voucher money engine.

## Position Lifecycle

Cap-entry events are balanced across long and short entries, but final inventory is all short in central/deep. Mean 100-tick unfavourable VELVET move after short cap entry was not consistently bad: VEV_5300 short cap entries had mean -9.75 ticks, VEV_5200 short -6.72, VEV_5100 short -1.93, VEV_5000 short -2.50. That argues against a simple "cap entry is toxic" rule.

Near-cap adds at `abs(pos) >= 275`:

| Product | Tail add lots | Long add lots | Short add lots |
| --- | ---: | ---: | ---: |
| VEV_4000 | 174 | 75 | 99 |
| VEV_4500 | 203 | 96 | 107 |
| VEV_5000 | 176 | 83 | 93 |
| VEV_5100 | 136 | 54 | 82 |
| VEV_5200 | 152 | 75 | 77 |
| VEV_5300 | 188 | 89 | 99 |

At BS net-delta threshold 1700, central/deep extreme-delta-increasing lots were small: VEV_4000 33, VEV_4500 52, VEV_5300 26, and zero for VEV_5000/5100/5200. Upper vouchers dominated that threshold. At threshold 1500, central/deep lots become material, especially VEV_5300 at 1,140 lots, but the 1500 add gate cost 45.2k base PnL.

PnL after cap-entry is approximate in this pass. The script measures forward VELVET and voucher markouts after cap-entry, not fill-level realised PnL by cap episode. That limitation matters, so candidate acceptance relies on replay grids rather than cap-entry markout alone.

## Realised vs MTM

| Product | Realised | MTM/terminal | Total |
| --- | ---: | ---: | ---: |
| VEV_4000 | 52,258 | 7,148 | 59,406 |
| VEV_4500 | 66,014 | 7,793 | 73,807 |
| VEV_5000 | 83,339 | 8,684 | 92,023 |
| VEV_5100 | 70,781 | 8,471 | 79,252 |
| VEV_5200 | 72,471 | 7,399 | 79,870 |
| VEV_5300 | 37,785 | 4,975 | 42,760 |

Most central/deep PnL is realised, not only terminal MTM. That is why terminal-only de-risking helps stress a little but does not remove the core exposure.

## Net Delta Diagnostics

| Model | p05 | p50 | p95 | p99 | Max abs |
| --- | ---: | ---: | ---: | ---: | ---: |
| BS | -1,767.0 | -223.3 | 1,689.1 | n/a | 1,853.6 |
| Empirical | -1,447.3 | -37.6 | 1,429.5 | 1,429.5 | 1,447.3 |
| Conservative bucket | -1,605.0 | -87.5 | 1,527.1 | 1,546.4 | 1,691.6 |

BS bucket max abs: central 947.5, deep 600.0, upper 108.0, VELVET 200.0. The conclusion is model-stable: central/deep dominate directional exposure even when empirical deltas are lower than BS.

## Stress Results

| Stress | PnL impact |
| --- | ---: |
| VELVET +50 | -81,863 |
| VELVET +100 | -167,374 |
| VELVET +150 | -254,906 |
| VELVET -50 | +76,830 |
| VELVET -100 | +147,687 |
| IV +3 vol pts | -4,455 |
| IV +5 vol pts | -7,497 |
| IV +8 vol pts | -12,143 |
| VELVET +100 and IV +5 | -170,714 |
| VELVET -100 and IV -5 | +156,075 |
| Terminal half-spread liquidation proxy | -7,550 |
| Terminal full-spread liquidation proxy | -15,100 |
| Lower TTE proxy, 1 day | +15,487 |

The book is short upside and short vega at terminal. Lower TTE helps because the short-call inventory benefits from decay in this proxy.

## Candidate Grid

| Variant | Parameters | Base total | Voucher | Day 1 | Day 2 | Day 3 | Adverse voucher | Harsh voucher | Delta p95 | Delta max | Stress improvement | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| M3 active | upper +200 cap | 619,806 | 443,614 | 237,054 | 188,072 | 212,980 | 233,019 | 145,617 | 1,689 | 1,854 | 0 | Keep incumbent |
| M6 terminal stop-add | VEV_5200/5300, final 15%, level 250 | 618,401 | 442,209 | 236,623 | 188,959 | 211,512 | 232,318 | 145,176 | 1,689 | 1,854 | +5,922 | Reject, no delta or fill gain |
| M3 one-sided cap | VEV_5300 short cap 200 | 612,658 | 436,466 | 234,243 | 186,939 | 210,434 | 230,236 | 144,620 | 1,689 | 1,803 | +4,520 | Reject, weak risk gain |
| M3 central cap | VEV_5000-5300 short cap 275 | 607,144 | 430,952 | 233,639 | 184,527 | 206,669 | 225,168 | 139,670 | 1,689 | 1,775 | +7,710 | Reject, costs too much |
| M4 net-delta add gate | threshold 1700 | 609,739 | 433,547 | 231,985 | 185,933 | 211,289 | 241,009 | 161,058 | 1,689 | 1,748 | 0 | Reject, p95 and terminal unchanged |

Stress improvement is VELVET +100 terminal proxy improvement versus active M3. The 1700 net-delta gate improves adverse voucher by 7,990 and harsh voucher by 15,441, but base cost is 10,067 and max delta improves only 5.7%, with p95 unchanged. It fails Case B.

## Parameter Stability

VEV_5300 short caps were smooth but too weak: caps 275/250/225/200 cost 1.8k/3.6k/5.4k/7.1k base PnL and improve VELVET +100 stress by only 1.1k/2.3k/3.4k/4.5k. Delta p95 is unchanged throughout.

Central short caps are blunt: central short cap 275 costs 12.7k and improves VELVET +100 stress by 7.7k; cap 250 costs 25.3k and improves 15.4k. That is not a stable acceptable trade-off.

Stop-add near cap is not better than caps. VEV_5300 stop-add 275/250/225 costs 2.9k/5.7k/8.5k and still leaves p95 delta near unchanged.

Net-delta gates have a clear but unacceptable cost curve: thresholds 1700/1500/1300/1100/900 cost 10.1k/45.2k/104.0k/156.4k/213.2k base PnL. The first threshold with meaningful delta reduction is already too expensive; the 1700 threshold is fill-stress helpful but not a central/deep terminal-risk fix.

Terminal stop-add is cheap but shallow: 275 and 250 levels improve VELVET +100 stress by about 3.0k and 5.9k with no p95 or max-delta improvement, and adverse/harsh fill PnL worsens slightly.

## Final Recommendation

REJECT_NO_CHANGE_ACTIVE_M3.

Keep `strategies/r4_voucher_risk_hardened_candidate.py` as the active submission candidate. The copied `strategies/r4_voucher_central_deep_hardened_candidate.py` is research-only and defaults to M3-equivalent behaviour. Do not promote it.

## Next Action

Submit `strategies/r4_voucher_risk_hardened_candidate.py` unless later evidence finds a stronger, model-stable central/deep risk control. Remaining risks are honest: terminal short-call exposure is large, VELVET upside shocks are bad, and central/deep PnL may include directional exposure. Current evidence says surgical de-risking either does too little or damages the money engine.

## Verification

Commands run:

```text
git status --short --branch
git log --oneline -5
git diff --stat
Test-Path analysis/voucher_central_deep_risk_forensics.py
python -m py_compile analysis/voucher_central_deep_risk_forensics.py
python -m py_compile strategies/r4_voucher_risk_hardened_candidate.py
python -m analysis.voucher_central_deep_risk_forensics --smoke
python -m analysis.voucher_central_deep_risk_forensics
python -m py_compile strategies/r4_voucher_central_deep_hardened_candidate.py
python -m prosperity_backtester replay strategies/r4_voucher_risk_hardened_candidate.py --round 4 --data-dir data/round4 --days 1 2 3 --fill-mode base --output-dir backtests/r4_active_m3_replay_verify
python -m prosperity_backtester replay strategies/r4_voucher_central_deep_hardened_candidate.py --round 4 --data-dir data/round4 --days 1 2 3 --fill-mode base --output-dir backtests/r4_central_deep_candidate_default_replay_verify
python -m pytest -q -k "round4 or r4" --timeout=120
python -m prosperity_backtester verify-round4 --data-dir data/round4 --output-dir backtests/r4_verification_fast_strict_central_deep --fast --strict
```

Verification results:

| Check | Result |
| --- | --- |
| Active strategy compile | pass |
| Forensic script compile | pass |
| Research candidate compile | pass |
| Smoke forensics | pass |
| Full forensics | pass |
| Active M3 replay | 619,806 PnL, zero breaches |
| Candidate default replay | 619,806 PnL, zero breaches |
| Pytest Round 4 target | 12 passed, 4 skipped |
| Fast strict Round 4 verifier | pass, 12/12 gates, decision-grade true, candidate promoted false |
