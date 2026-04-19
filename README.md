# R1MCBT team platform v4

Round 1 research platform for:

- `ASH_COATED_OSMIUM`
- `INTARIAN_PEPPER_ROOT`

The platform covers deterministic replay, configurable fill models, Monte Carlo robustness, live-export calibration, comparison, sweeps, optimisation, trader compatibility, reproducible output bundles and a React dashboard.

## What changed in v4

- Rebuilt the dashboard as a polished signal observatory with React, Vite, TypeScript, Tailwind and Recharts.
- Added a dedicated inspect mode for timestamp-window analysis.
- Added stronger product deep dives for OSMIUM and PEPPER.
- Added richer behaviour counts for dashboard diagnostics and product deep dives.
- Fixed Monte Carlo fair-value bands so P10/P25/P50/P75/P90 are all available.
- Fixed optimisation dashboard ordering so higher scores rank first.
- Fixed local server run discovery so the dashboard can load bundles from the repo root.
- Cleaned dashboard styling, typography and chart theming around a dark quant-lab system.

## Repo layout

```text
analysis/                 Thin validation and calibration entry scripts
configs/                  Named sweep and optimisation configs
data/round1/              Historical Round 1 CSV inputs
dashboard/                React/Vite dashboard source
docs/                     Architecture, assumptions and audit notes
examples/                 Example real trader files and config copies
live_exports/             Prosperity export bundle examples
r1bt/                     Core replay, MC, calibration and reporting package
strategies/               Local starter and working strategy files
tests/                    Backend smoke and unit tests
visualizer/               Legacy static dashboard fallback
```

Generated outputs are written to `backtests/` unless an `--output-dir` is provided. The directory is ignored so large replay and Monte Carlo bundles do not ship by accident.

## Install

Python runtime has no required third-party dependency.

For tests:

```bash
python -m pip install pytest
python -m pytest -q
```

For the dashboard:

```bash
cd dashboard
npm ci
npm run build
```

Do not commit `dashboard/node_modules/`.

## Core workflows

Inspect the data:

```bash
python -m r1bt inspect --data-dir data/round1 --days -2 -1 0 --json
```

Replay one trader:

```bash
python -m r1bt replay strategies/trader.py --name main_strategy --data-dir data/round1 --days -2 -1 0 --fill-mode base
```

Replay against a live export:

```bash
python -m r1bt replay examples/trader_round1_v9.py --name live_v9 --data-dir data/round1 --days 0 --fill-mode base --live-export live_exports/259168/259168.log
```

Run Monte Carlo:

```bash
python -m r1bt monte-carlo examples/trader_round1_v9.py --name live_v9 --days 0 --quick
```

Compare traders:

```bash
python -m r1bt compare strategies/trader.py examples/trader_round1_v9.py --names main_strategy live_v9 --data-dir data/round1 --days 0 --fill-mode base
```

Run a sweep:

```bash
python -m r1bt sweep configs/pepper_sweep.json
```

Run optimisation:

```bash
python -m r1bt optimize configs/pepper_optimize_quick.json
```

Run calibration:

```bash
python -m r1bt calibrate examples/trader_round1_v9.py --name live_v9 --data-dir data/round1 --days 0 --live-export live_exports/259168/259168.log --quick
```

## Dashboard

Build the dashboard once:

```bash
cd dashboard
npm install
npm run build
```

Serve it from the repo root:

```bash
python -m r1bt serve --port 5555
```

Open:

```text
http://127.0.0.1:5555/
```

You can drag one or more `dashboard.json` bundles into the app, or use "Load from local server" to discover bundles under the served directory.

The server lists bundles from `manifest.json` metadata where possible, so local discovery stays fast even when a generated `dashboard.json` is large. Selecting a bundle still loads the full dashboard payload.

During dashboard development:

```bash
cd dashboard
npm run dev
```

The Vite dev server proxies `/api` to `http://127.0.0.1:5555`, so keep `python -m r1bt serve` running in another terminal if you want local run discovery.

## Output bundle

Replay bundles include:

- `dashboard.json`
- `manifest.json`
- `run_summary.csv`
- `session_summary.csv`
- `orders.csv`
- `fills.csv`
- `inventory_series.csv`
- `pnl_series.csv`
- `fair_value_series.csv`
- `behaviour_summary.csv`
- `behaviour_series.csv`

Monte Carlo bundles additionally include:

- `sample_paths/`
- `sessions/`

Comparison, calibration and optimisation bundles include their matching CSV tables and manifests.

The parent output directory receives `run_registry.jsonl`.

## Add a trader

Add a Python file with the normal Prosperity contract:

```python
class Trader:
    def run(self, state):
        return orders, conversions, trader_data
```

Supported import styles include:

- `from datamodel import ...`
- `from r1bt.datamodel import ...`
- `from prosperity3bt.datamodel import ...`
- `from prosperity4mcbt.datamodel import ...`

Parameter overrides are supported through sweep and optimisation configs.

## Exact vs approximate

Exact relative to local inputs:

- Round 1 CSV ingestion and schema checks
- Live-export parsing where fields are present
- Visible-book aggressive fills
- Trader state persistence
- Cash, inventory, realised, unrealised and MTM accounting
- Deterministic replay over provided timestamps
- Synthetic latent fair inside Monte Carlo

Approximate:

- Passive fills and queue position
- Same-price queue share
- Adverse selection penalties
- Historical analysis fair
- Synthetic market generation
- Calibration and optimisation scores

The important distinction is that Monte Carlo `analysis_fair` is the simulator latent fair, while historical replay `analysis_fair` is an inferred diagnostic proxy.

## Tests

```bash
python -m pytest -q
npm run build --prefix dashboard
```

With `uv`, the backend tests can also be run without changing the project dependencies:

```bash
uv run --with pytest pytest -q
```

## Generated files

Keep these out of submissions and commits:

- `backtests/` output bundles
- `dashboard/node_modules/`
- `.venv/`
- `.pytest_cache/`
- `__pycache__/`
- `*.log`

The dashboard build output in `dashboard/dist/` is small and useful when serving the app directly with `python -m r1bt serve`. Rebuild it after dashboard source changes.

## Remaining limitations

- True queue position is not known from public data.
- Live exports may not expose enough detail for exact inventory-path reconstruction.
- Historical fair value is inferred, not official hidden fair.
- Very large Monte Carlo batches may eventually justify moving the hot loop out of Python.
