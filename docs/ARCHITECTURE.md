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

Round-specific logic is isolated:

- `round2.py`: Round 2 access and MAF assumptions only
- `round3.py`: voucher metadata, TTE helpers, option diagnostics, and coherent Round 3 synthetic generation

## Main layers

### Inputs

- `dataset.py` loads and validates Round 1, Round 2, and Round 3 CSVs
- `metadata.py` provides round specs and product metadata
- `datamodel.py` and `trader_adapter.py` keep trader compatibility stable

### Execution

- `platform.py` is the main replay and Monte Carlo engine
- `fill_models.py` resolves named fill assumptions
- `round3.py` generates coherent Round 3 synthetic paths from the underlying and voucher chain
- `round2.py` stays out of Round 3 execution

### Reporting

- `reports.py` builds the canonical dashboard payload and manifest
- `dashboard_payload.py` compacts large retained sections for storage
- `storage.py` controls light versus full output profiles
- `provenance.py` records git and runtime metadata

## Design boundaries

- Historical replay trades the observed public books.
- Passive fills remain approximate.
- Round 3 option theory is diagnostic and synthetic support only.
- Round 2 access logic cannot leak into Round 3.
