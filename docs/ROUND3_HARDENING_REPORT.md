# Round 3 Hardening Report

Result: Round 3 replay, diagnostics, Monte Carlo, dashboard review, and output contracts were hardened and verified on 2026-04-24.

## Repository State

- Branch: `main`
- Local HEAD: `78d5e54 Add vol smile`
- `origin/main`: `fa2bce0 Add round-aware Round 3 backtesting support`
- Dirty flag during proof: `true`
- No commit or push was made.

## Data Validation

| Day | Price rows | Timestamps | Trade rows | Timestamp range | Step | Duplicate rows | Product set |
| --- | ---: | ---: | ---: | --- | --- | ---: | --- |
| 0 | 120,000 | 10,000 | 1,308 | 0 to 999900 | 100 | 0 | exact 12 products |
| 1 | 120,000 | 10,000 | 1,407 | 0 to 999900 | 100 | 0 | exact 12 products |
| 2 | 120,000 | 10,000 | 1,333 | 0 to 999900 | 100 | 0 | exact 12 products |

## Verification

- `python -m pytest -q`: 110 passed in 147.49s.
- `npm test --prefix dashboard`: 34 passed.
- `npm run build --prefix dashboard`: passed.
- No-op Round 3 replay days `0 1 2`: final PnL `0.0`, fills `0`, orders `0`, limit breaches `0`.
- R3 replay and MC manifests include all 12 products, correct limits, option diagnostics, and option diagnostics data-contract entries.

## Performance Proof

| Case | Wall time | Files | Size | Peak RSS evidence |
| --- | ---: | ---: | ---: | ---: |
| Inspect days 0 1 2 with option diagnostics | 19.636s | 1 | 387,613 B | not captured by harness |
| No-op replay day 0 | 13.396s | 5 | 12,837,414 B | not captured by harness |
| No-op replay days 0 1 2 | 40.268s | 5 | 14,058,075 B | not captured by harness |
| MC smoke, 8 sessions, 250 ticks | 21.056s | 5 | 1,995,198 B | bundle write peak 382,066,688 B |
| MC proof, 32 sessions, 250 ticks | 24.127s | 5 | 2,196,455 B | bundle write peak 402,178,048 B |
| MC moderate, 64 sessions, 250 ticks, 1 worker | 26.324s | 5 | 2,217,440 B | bundle write peak 409,350,144 B |
| MC moderate, 64 sessions, 250 ticks, 2 workers | 22.611s | 5 | 2,217,440 B | bundle write peak 446,480,384 B |
| MC moderate, 64 sessions, 250 ticks, 4 workers | 21.867s | 5 | 2,217,436 B | bundle write peak 482,336,768 B |
| Scenario compare `round3_research_scenarios.json` | 153.588s | 5 | 50,203 B | not captured by harness |
| Fill sensitivity `round3_fill_sensitivity.json` | 95.108s | 5 | 54,585 B | not captured by harness |

The values above are from the original 2026-04-24 hardening pass. Replay, inspect, and scenario-compare RSS rows that originally read `not captured by harness` are now covered by the `verify-round3` harness when `psutil` is installed in the active environment.

## End-to-end verification harness (added 2026-04-25)

`python -m prosperity_backtester verify-round3 --data-dir data/round3 --output-dir backtests/r3_verification_latest` is now the single entry point that produces a structured trustworthiness report. It writes `verification_report.json`, `verification_report.md`, and `manifest.json`, and exits non-zero on any failure.

The report combines:

- provenance (Python version, platform, git HEAD, dirty flag, run timestamp, per-file `sha256` data hashes)
- exact data validation against known Round 3 counts
- in-process replay-correctness fixtures (multi-level crossing, fractional MTM, atomic per-product limit enforcement, 12-product execution, two-no-op exact-zero-diff compare)
- option-diagnostics safety (no `NaN`/`Infinity`, primary fit set is `VEV_5000`..`VEV_5500`, every excluded strike flagged)
- Monte Carlo coherence proof (seed determinism, shock direction, vol shift, hydrogel-shock isolation, residual-noise isolation, no negative or crossed synthetic books)
- subprocess sweep over `inspect`, `replay` day 0, `replay` days 0/1/2, `compare`, three Monte Carlo cells, two seed-determinism MC runs, `scenario-compare` for `round3_research_scenarios`, and `scenario-compare` for `round3_fill_sensitivity`
- per-command wall time, output size, file count, peak parent-process RSS, peak process-tree RSS, and child-process count (when `psutil` is installed; the report records the gap explicitly otherwise)

The latest performance/RSS numbers should be regenerated locally rather than transcribed here, since they are environment-specific. Run `verify-round3` and read `backtests/r3_verification_latest/verification_report.md` for the up-to-date table.

## Caveats

- Passive fills remain local approximations. Same-price and worse-price passive print matches are labelled separately.
- Round 3 Monte Carlo is classic Python only. Rust and streaming backends are not active for Round 3.
- Option fair values, fitted IVs, Greeks, residuals, and z-scores are diagnostics and synthetic-calibration inputs, not historical replay marks.
- Replay does not apply voucher exercise or cash settlement.
- Scenario compare is still the slowest checked-in R3 workflow because it replays multiple full historical scenarios.
- `psutil` is included in the dev extra, but is not a runtime dependency. Install the dev extra to capture peak parent and process-tree RSS in the verification report; the harness records the gap when missing.
