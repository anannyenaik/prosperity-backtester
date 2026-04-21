# Architecture

The repository is organised around output bundles. Each workflow runs a trader, records structured sidecars, writes a `dashboard.json` payload and, where useful, writes `manifest.json` metadata for fast dashboard discovery.

## Layers

### Data

Files:

- `prosperity_backtester/dataset.py`
- `prosperity_backtester/live_export.py`
- `prosperity_backtester/metadata.py`
- `prosperity_backtester/noise.py`
- `prosperity_backtester/round2.py`
- `prosperity_backtester/scenarios.py`

Responsibilities:

- Load Round 1 and Round 2 CSVs.
- Validate schema, timestamps, products, duplicate rows and book issues.
- Load tracked live-export JSON fixtures.
- Store product metadata and fitted noise profiles.
- Describe Round 2 access assumptions and calibrated research scenarios.

### Trader Compatibility

Files:

- `prosperity_backtester/datamodel.py`
- `prosperity_backtester/trader_adapter.py`

Responsibilities:

- Provide the Prosperity `TradingState`, `OrderDepth`, `Order` and `Trade` contract.
- Support common imports such as `from datamodel import ...`.
- Load trader files safely and apply config override dictionaries.

### Execution And Accounting

Files:

- `prosperity_backtester/platform.py`
- `prosperity_backtester/mc_backends.py`
- `prosperity_backtester/fill_models.py`
- `prosperity_backtester/simulate.py`
- `prosperity_backtester/engine.py`

Responsibilities:

- Replay market days tick by tick.
- Match visible aggressive fills exactly against the local book.
- Approximate passive fills through named fill models.
- Apply perturbations, slippage, latency-like effects and adverse-selection assumptions.
- Track cash, inventory, realised, unrealised and mark-to-market PnL.
- Generate synthetic Monte Carlo market days.
- Provide a default streaming Monte Carlo backend plus a classic fallback.
- Emit compact per-session path metrics for Monte Carlo all-session bands without returning full non-sample paths.

### Diagnostics

Files:

- `prosperity_backtester/fair_value.py`
- `prosperity_backtester/behavior.py`
- `prosperity_backtester/live_export.py`

Responsibilities:

- Infer historical diagnostic fair values.
- Expose exact latent fair values in synthetic sessions.
- Compute markouts, cap usage, fill mix and product behaviour summaries.
- Compare replay output with live-export PnL, fills, positions and timing where fields exist.

### Workflow Orchestration

Files:

- `prosperity_backtester/experiments.py`
- `prosperity_backtester/__main__.py`
- `analysis/benchmark_outputs.py`
- `analysis/benchmark_runtime.py`

Responsibilities:

- Run replay, Monte Carlo, comparison, sweep, optimisation, calibration and scenario workflows.
- Load JSON config files with clear validation errors.
- Resolve trader, data and fill-config paths.
- Expose short replay and compare defaults plus convenience flags such as `--data`, `--merge-pnl`, `--limit`, `--print`, `--vis`, `--mc-backend` and `serve --latest-type`.
- Keep CLI commands thin and reproducible.
- Provide lightweight, reproducible bundle-size and runtime benchmark workflows.

### Reporting

File:

- `prosperity_backtester/reports.py`
- `prosperity_backtester/storage.py`
- `prosperity_backtester/benchmark.py`
- `prosperity_backtester/provenance.py`

Responsibilities:

- Build dashboard payloads.
- Apply event-aware light path compaction and compact order-intent summaries.
- Aggregate Monte Carlo path bands from every session.
- Write CSV sidecars, manifests, sample paths and session manifests according to output policy.
- Append `run_registry.jsonl` entries.
- Record command, workflow-tier, runtime-backend, data-scope, phase-timing and git provenance in both `dashboard.json` and `manifest.json`.
- Preserve exact and approximate assumption notes in output bundles.
- Preserve exact, compact, bucketed, qualitative and raw bundle data-contract notes.
- Record canonical, sidecar and debug file lists plus total bundle size in `manifest.json`.
- Apply light/full storage profiles and safe retention for auto-generated runs.

### Dashboard

Files:

- `dashboard/src/`
- `prosperity_backtester/server.py`
- `legacy_dashboard/dashboard.html`

Responsibilities:

- Load one or more `dashboard.json` bundles.
- Discover local bundles through `/api/runs`.
- Prefer `run_registry.jsonl` and `manifest.json` for low-cost discovery, latest-run routing and richer landing-screen metadata.
- Render bundle-aware tabs for replay, comparison, Monte Carlo, calibration, optimisation, Round 2, Alpha Lab and product deep dives.
- Show compatibility messages when a bundle does not contain the data required by a tab.

## Data Contract

The dashboard should consume bundle fields rather than reconstructing results from raw CSVs. Backend workflows are responsible for writing:

- `type`
- `meta`
- `assumptions`
- `dataContract`
- `datasetReports`
- workflow-specific payload sections
- exact sidecar CSV files for summary, fills and aggregate tables
- optional chart-series sidecar CSV files when requested

When adding a workflow, prefer extending this bundle contract over adding a one-off report format.

## Design Choices

- Python remains the backend because trader compatibility, debugging and config iteration matter more than raw throughput at current scale, but Monte Carlo now has a streaming hot path plus a classic fallback.
- Light mode is the day-to-day research profile. It keeps exact summaries and fills, compact paths, compact quote intent and all-session Monte Carlo path bands in `dashboard.json`.
- Monte Carlo work is chunked across workers, and unsampled sessions stream only the path metrics needed for final distributions and all-session path bands.
- Monte Carlo sampled runs are intentionally qualitative examples. Population path bands come from every session through bucketed path metrics.
- Full mode is for local debugging. It writes raw order rows, full series sidecars and sampled path files, but child bundles require an explicit `--save-child-bundles`.
- Round 2 is modelled as scenario analysis, not as a claim about hidden website mechanics.
- The React dashboard is the primary review surface. The static dashboard is only a fallback.
