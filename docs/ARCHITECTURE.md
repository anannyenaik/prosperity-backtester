# Architecture overview

## Product goal

Make Round 1 research fast, reproducible and teammate-friendly.

The platform is built around four workflows:

1. Replay a real trader on historical data or a live export.
2. Stress a trader with Monte Carlo sessions.
3. Compare, sweep and optimise variants.
4. Inspect results in a local dashboard without reading code.

## Core layers

### Data layer

Files:

- `r1bt/dataset.py`
- `r1bt/live_export.py`
- `r1bt/metadata.py`

Responsibilities:

- Load historical Round 1 CSVs.
- Validate schema and structural integrity.
- Load live export `.json` and `.log` files.
- Expose product metadata and dataset reports.

### Trader compatibility layer

Files:

- `r1bt/datamodel.py`
- `r1bt/trader_adapter.py`

Responsibilities:

- Expose a Prosperity-compatible `TradingState`.
- Alias common import paths such as `from datamodel import ...`.
- Load trader modules.
- Apply parameter overrides for sweeps and optimisation.

### Execution and accounting layer

Files:

- `r1bt/fill_models.py`
- `r1bt/platform.py`

Responsibilities:

- Deterministic event replay.
- Visible-book aggressive fills.
- Approximate passive fills.
- Cash, realised, unrealised and MTM accounting.
- Order, fill, inventory and PnL logging.

### Fair-value and behaviour layer

Files:

- `r1bt/fair_value.py`
- `r1bt/behavior.py`

Responsibilities:

- Infer diagnostic fair values on historical replay.
- Expose exact latent fair on synthetic sessions.
- Summarise product behaviour, cap usage, order-to-fill conversion and fill markouts.

### Experiment orchestration layer

Files:

- `r1bt/experiments.py`
- `r1bt/__main__.py`

Responsibilities:

- Replay.
- Monte Carlo.
- Compare.
- Sweep.
- Optimise.
- Calibrate.
- Inspect data.
- Serve the dashboard.

### Reporting layer

File:

- `r1bt/reports.py`

Responsibilities:

- Write `dashboard.json`.
- Write CSV sidecars and manifests.
- Write Monte Carlo sample paths.
- Write `run_registry.jsonl`.
- Preserve exact vs approximate assumptions in every dashboard payload.

### Dashboard layer

Files:

- `dashboard/src/App.tsx`
- `dashboard/src/views/*.tsx`
- `dashboard/src/components/*.tsx`
- `dashboard/src/charts/*.tsx`
- `r1bt/server.py`

Responsibilities:

- Load one or more dashboard bundles by drag/drop.
- Discover bundles through the local server API.
- Render overview, replay, Monte Carlo, calibration, comparison, optimisation and product deep dives.
- Provide inspect mode for timestamp-window analysis.
- Keep the dashboard product-like rather than report-like.
- Discover local bundles from lightweight manifest metadata before loading full dashboard payloads.

## Dashboard design system

The v4 dashboard uses:

- React + Vite + TypeScript for a maintainable app shell.
- Tailwind for local tokens and layout.
- Recharts for resilient, typed chart components.
- Zustand for simple cross-view state.
- Syne for display headings, Cormorant for editorial tone and DM Mono for labels/data.

The visual language is a dark signal observatory:

- Obsidian and midnight backgrounds.
- Cyan and muted gold accents.
- Bone text.
- Glass panels.
- HUD labels.
- Fixed top navigation.
- Restrained grain, scanline and glow.

## Why Python remains the backend default

Round 1 scale does not require a compiled hot loop yet.

Python keeps:

- Trader compatibility simple.
- Local debugging fast.
- Parameter overrides easy.
- Team setup low-friction.

If Monte Carlo volume becomes the bottleneck, the execution hot loop can move behind the same bundle and dashboard contracts.
