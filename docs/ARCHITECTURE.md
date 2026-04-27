# Architecture

Result: the repository is organised around one stable bundle contract and one round-aware runtime registry. Historical replay, Monte Carlo, comparison, and scenario workflows all flow through the same core path.

## Core flow

```text
trader file
  -> trader_adapter.py
  -> dataset.py + metadata.py + round2.py + round3.py
  -> platform.py and experiments.py
  -> reports.py + storage.py + provenance.py
  -> dashboard.json + manifest.json + CSV sidecars
  -> server.py + dashboard/
```

## Round-aware design

The old global-product assumption has been replaced by a round registry:

- `metadata.py` defines `ProductMeta`, `RoundSpec`, and the round registry
- `get_round_spec()`, `products_for_round()`, and `position_limit_for()` are the normal entry points
- Round 1 and Round 2 keep the two-product delta-1 setup
- Round 3 adds `HYDROGEL_PACK`, `VELVETFRUIT_EXTRACT`, and the ten `VEV_*` vouchers
- Round 4 keeps the Round 3 product set and adds named buyer/seller market-trade metadata

Round-specific logic is isolated:

- `round2.py`: Round 2 access and MAF assumptions only
- `round3.py`: voucher metadata, TTE helpers, option diagnostics, and coherent Round 3 synthetic generation
- `r4_manifest.py`: strict Round 4 schema, count, hash, spread/depth, trade-size, and counterparty manifest
- `counterparty_research.py`: participant-side markout and recommendation labelling infrastructure
- `r4_mc_validation.py`: Round 4 MC validation, scenario-smoke, transform checks, and evidence-based decision-grade reporting
- `verify_round4.py`: Round 4 verification harness and final gate report

## Main layers

### Inputs

- `dataset.py` loads and validates Round 1, Round 2, and Round 3 CSVs
- Round 4 uses the same dataset loader with the Round 4 registry and preserves buyer/seller names
- `metadata.py` provides round specs and product metadata
- `datamodel.py` and `trader_adapter.py` keep trader compatibility stable

### Execution

- `platform.py` is the main replay and Monte Carlo engine
- `fill_models.py` resolves named fill assumptions
- `round3.py` computes voucher diagnostics and generates coherent Round 3 synthetic paths from the underlying, fitted IV surface, and voucher residuals
- Round 4 MC reuses the coherent voucher generator with Round 4 metadata, named trade-flow sampling, shuffled/day-held-out/stale/thinning/liquidity stress modes, and explicit model-risk limitations
- `round2.py` stays out of Round 3 execution

### Reporting

- `reports.py` builds the canonical dashboard payload and manifest
- `dashboard_payload.py` compacts large retained sections for storage
- `storage.py` controls light versus full output profiles
- `provenance.py` records git and runtime metadata

### Verification

- `verify_round3.py` runs the Round 3 trustworthiness sweep: data validation, replay-correctness fixtures, option-diagnostics safety, MC coherence, dashboard payload checks, and a subprocess sweep over `inspect`, `replay`, `compare`, `monte-carlo`, and `scenario-compare`. It samples peak parent and process-tree RSS via `psutil` (when available) and writes `verification_report.json`, `verification_report.md`, and `manifest.json`. The CLI command `verify-round3` exits non-zero on any failure so the harness can gate further work.
- `verify_round4.py` runs manifest, data, counterparty presence, counterparty research, no-op replay, candidate fixture replay, ablations, synthetic smoke, MC validation, and MC seed smoke. It always writes `verification_report.json`, `verification_report.md`, and `manifest.json`. Strict mode exits non-zero unless `backtester_decision_grade` is true.

## Design boundaries

- Historical replay trades the observed public books.
- Passive fills remain approximate.
- Round 3 option theory is diagnostic and synthetic support only.
- Round 3 Monte Carlo uses the classic Python execution path; Rust and streaming backends are not Round 3 engines.
- Round 4 Monte Carlo also uses the classic Python path.
- Round 4 MC can be decision-grade as a rejection and stress harness when hard gates pass. It is not an official simulator oracle.
- Round 2 access logic cannot leak into Round 3.
