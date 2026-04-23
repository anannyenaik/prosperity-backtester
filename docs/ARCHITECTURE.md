# Architecture

Result: the repository is organised around one stable output contract. Historical replay, Monte Carlo, calibration, optimisation, and scenario workflows all produce bundle directories with the same two anchor files:

- `dashboard.json`
- `manifest.json`

That shared contract keeps the CLI, tests, server, and dashboard aligned.

## Core Flow

```text
trader file
  -> trader_adapter.py
  -> dataset.py / live_export.py / round2.py
  -> platform.py and experiments.py
  -> reports.py + storage.py + provenance.py
  -> dashboard.json + manifest.json + CSV sidecars
  -> server.py + dashboard/
```

The main path is:

1. `__main__.py` parses the command and output policy.
2. `experiments.py` resolves traders, configs, datasets, and workflow-specific options.
3. `dataset.py`, `live_export.py`, `metadata.py`, and `round2.py` load the required inputs.
4. `platform.py` runs replay or Monte Carlo sessions using the selected fill model and perturbation settings.
5. `reports.py` builds the bundle payload and writes canonical files.
6. `server.py` exposes local bundles to the React dashboard or the legacy HTML fallback.

## Layers

### Input and compatibility

- `dataset.py` loads Round 1 and Round 2 CSVs and validates their shape.
- `live_export.py` loads tracked live-export fixtures for calibration.
- `datamodel.py` and `trader_adapter.py` let uploaded Prosperity-style traders run without source edits.
- `metadata.py`, `noise.py`, `round2.py`, and `scenarios.py` provide shared configuration and assumptions.

### Execution

- `platform.py` is the main execution engine.
- `fill_models.py` resolves named fill assumptions and empirical fill profiles.
- `simulate.py` generates synthetic books and trades for Monte Carlo.
- `mc_backends.py` chooses the backend for Monte Carlo work.
- `engine.py` holds lower-level ledger and execution primitives that support the wider runtime and older callers.

### Reporting and persistence

- `reports.py` writes `dashboard.json`, `manifest.json`, and workflow-specific CSVs.
- `dashboard_payload.py` compacts large retained sections for storage and expands them again on load.
- `storage.py` controls light versus full output behaviour and retention rules.
- `provenance.py` records git and runtime metadata in the bundle.
- `bundle_attribution.py` is optional analysis tooling for explaining bundle size.

### Review surfaces

- `server.py` serves bundle discovery endpoints and static dashboard assets.
- `dashboard/` is the primary review UI.
- `legacy_dashboard/` is the shipped fallback when the React build is absent.

## Design Decisions

### JSON bundle first

`dashboard.json` is the canonical review payload. The dashboard reads that payload rather than reconstructing results from raw CSV inputs.

Why it stays:

- one contract across all workflows
- easier review and testing
- clear separation between execution and presentation

### Light output by default

The default output profile is `light`. It keeps the evidence needed for review while omitting the heaviest debug artefacts.

Full mode exists for deliberate forensic work:

- raw submitted orders
- full chart sidecars
- Monte Carlo sample-path files
- per-session manifests

### Compatibility is isolated

Compatibility-only surfaces are still present, but they are intentionally narrow:

- `r1bt/` for former package-name imports
- `prosperity_backtester.replay` for older direct replay callers
- `prosperity_backtester.dashboard` for older standalone dashboard code
- `legacy_dashboard/` for environments without a React build

They remain because they are cheap to keep and clearly separated from the main path.

### Experimental work stays out of the default path

The Rust backend and the benchmark helpers are retained, but they are not the primary architecture:

- `rust_mc_engine/` is optional
- `mc_backends.py` keeps Python as the normal path
- `analysis/benchmark_*.py`, `analysis/rss_frontier.py`, and `analysis/architecture_bakeoff.py` are optional analysis tools

## Runtime Surfaces

### Main CLI

`python -m prosperity_backtester ...`

This is the primary interface for:

- replay
- compare
- Monte Carlo
- inspect
- calibrate
- optimise
- scenario compare
- Round 2 scenario analysis
- serve
- clean

### Optional helper scripts

`analysis/research_pack.py` and `analysis/profile_replay.py` are the main optional wrappers around the core runtime. They stay thin on purpose and delegate real work back into `prosperity_backtester/`.

### Dashboard

The dashboard has two layers:

- `dashboard/`: primary React review UI
- `legacy_dashboard/dashboard.html`: fallback for environments without a local React build

### Tests

`tests/` is part of the core architecture because the bundle contract is a major part of the product. Output shape, provenance, retention, adapter logic, and compatibility shims are all covered there.

## Status Boundaries

Core:

- `prosperity_backtester/`
- `data/`
- `strategies/trader.py`
- `strategies/starter.py`
- `tests/`

Optional:

- `dashboard/`
- `analysis/research_pack.py`
- `analysis/profile_replay.py`
- `configs/`
- `examples/`
- `live_exports/`

Experimental:

- `rust_mc_engine/`
- Rust support in `mc_backends.py`
- benchmark helpers in `analysis/`

Legacy:

- `r1bt/`
- `legacy_dashboard/`
- `prosperity_backtester.replay`
- `prosperity_backtester.dashboard`

For the file-by-file map, see [docs/REPOSITORY_GUIDE.md](REPOSITORY_GUIDE.md).
