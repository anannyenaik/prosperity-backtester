Result: Round 4 active current candidate is `strategies/r4_hydro_velvet_m4_candidate.py`.

# Round 4 Status

## Active Files

- `strategies/r4_hydro_velvet_m4_candidate.py`: active Hydro v2 + VELVET M4 candidate. Defaults to `VELVET_OVERLAY["mode"] = "premium_overlay"` and `PARAMS["VELVET_BASELINE_CAP"] = None`.
- `strategies/r4_trader.py`: untouched baseline and control.

## Archived Files

- `strategies/archive/round4/accepted/r4_hydrogel_candidate_v2.py`: accepted Hydro v2 reference, superseded by the active M4 candidate.
- `strategies/archive/round4/rejected/r4_hydrogel_candidate.py`: rejected Hydro v1.
- `strategies/archive/round4/rejected/r4_combined_velvet_candidate.py`: rejected first combined VELVET attempt.
- `strategies/archive/round4/rejected/r4_velvet_phase3_candidate.py`: archived Phase-3 VELVET diagnostic candidate.

## Caveats

- Reduced baseline VELVET caps of `150` or `100` are documented fallback variants only. The active default remains uncapped baseline VELVET plus the M4 overlay.
- `verify-round4` may still report `candidate_promoted = false` by harness policy unless a separate promotion task explicitly flips that gate.
- `strategies/r4_trader.py` remains the control and should not be edited for this candidate.
