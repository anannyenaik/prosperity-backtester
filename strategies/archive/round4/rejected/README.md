# Rejected Round 4 Candidates

Result: these files are replay references only. They are not active candidates.

## Files

- `r4_hydrogel_candidate.py`: Hydro v1. Replaced by accepted `strategies/archive/round4/accepted/r4_hydrogel_candidate_v2.py` after a 9995-anchor leakage diagnosis.
- `r4_combined_velvet_candidate.py`: first VELVET integration attempt. It replaced the baseline VELVET z-score leg, diluted the premium signal with broad compression, depended heavily on passive fills, and capped carry too tightly.
- `r4_velvet_phase3_candidate.py`: Phase-3 diagnostic candidate used to test VELVET overlay modes. Superseded by `strategies/r4_hydro_velvet_m4_candidate.py`.

Active current candidate: `strategies/r4_hydro_velvet_m4_candidate.py`.
Untouched baseline/control: `strategies/r4_trader.py`.
