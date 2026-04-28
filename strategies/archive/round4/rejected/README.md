# Rejected Round 4 Candidates

Result: these files are replay references only. They are not active candidates.

## Files

- `r4_hydrogel_candidate.py`: Hydro v1. Replaced by accepted `strategies/archive/round4/accepted/r4_hydrogel_candidate_v2.py` after a 9995-anchor leakage diagnosis.
- `r4_combined_velvet_candidate.py`: first VELVET integration attempt. It replaced the baseline VELVET z-score leg, diluted the premium signal with broad compression, depended heavily on passive fills, and capped carry too tightly.
- `r4_velvet_phase3_candidate.py`: Phase-3 diagnostic candidate used to test VELVET overlay modes. Superseded by `strategies/archive/round4/accepted/r4_hydro_velvet_m4_candidate.py`.
- `r4_mark22_5400_candidate.py`: Mark22 interception research candidate. Rejected.
- `r4_voucher_central_deep_hardened_candidate.py`: central/deep voucher hardening research candidate. Rejected after candidate grids failed acceptance gates.

Active current candidate: `strategies/r4_voucher_risk_hardened_candidate.py`.
Untouched baseline/control: `strategies/r4_trader.py`.
No strategy logic changed in the hygiene pass that moved the central/deep candidate here.
