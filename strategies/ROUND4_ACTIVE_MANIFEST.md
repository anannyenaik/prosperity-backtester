# Round 4 Active Manifest

Result: the active Round 4 strategy files are limited to the current candidate and original control.

## Active Files

- Active candidate: `strategies/r4_voucher_risk_hardened_candidate.py`
- Baseline/control: `strategies/r4_trader.py`

## Archived Files

- Accepted reference: `strategies/archive/round4/accepted/r4_hydro_velvet_m4_candidate.py`
- Research reference: `strategies/archive/round4/research/r4_voucher_bs_candidate.py`
- Rejected reference: `strategies/archive/round4/rejected/r4_mark22_5400_candidate.py`

## Latest Accepted Modules

- Hydro v2
- VELVET M4
- Voucher upper-long cap hardening

## Notes

- `r4_voucher_risk_hardened_candidate.py` is the current active Round 4 candidate.
- `r4_trader.py` remains the original baseline/control.
- `r4_hydro_velvet_m4_candidate.py` is a frozen accepted Hydro + VELVET M4 reference, superseded by the voucher-risk-hardened candidate.
- `r4_voucher_bs_candidate.py` remains research-only: BS diagnostics accepted, BS trading rejected.
- `r4_mark22_5400_candidate.py` remains research-only/rejected: Mark22 interception rejected.
- No Hydro, VELVET, voucher, BS, Mark22, risk, parameter, or trading logic changed in this hygiene pass.
