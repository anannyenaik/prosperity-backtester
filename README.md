# Prosperity research platform

Round 1 and Round 2 research platform for:

- `ASH_COATED_OSMIUM`
- `INTARIAN_PEPPER_ROOT`

The platform covers deterministic replay, configurable fill models, Round 2 Market Access Fee scenarios, Monte Carlo robustness, live-export calibration, comparison, sweeps, optimisation, trader compatibility, reproducible output bundles and a React dashboard.

Round 2 support is a decision tool, not a fake website clone. It separates known facts, configurable assumptions and unknown website-only mechanics.

## What changed in v5

- Added empirical fill-profile derivation from live exports, with own fills filtered to `SUBMISSION` trades.
- Added product-specific fill assumptions and liquidity-regime overrides.
- Added size-dependent slippage, passive adverse-selection fields and per-product slippage reporting.
- Added fitted latent noise profiles using current R1/R2 values: OSMIUM `3.70`, PEPPER `3.22`.
- Added calibrated `scenario-compare` for baseline, stress, crash, spread/depth, harsh-slippage and lower-fill-quality checks.
- Expanded live-vs-sim diagnostics with fill quantity, passive/aggressive mismatch, inventory-path error and activity timing.

## What changed in v4

- Rebuilt the dashboard as a polished signal observatory with React, Vite, TypeScript, Tailwind and Recharts.
- Added first-class Round 2 mode for `prices_round_2_day_*.csv` / `trades_round_2_day_*.csv`.
- Added configurable MAF and extra-quote access scenarios.
- Added Round 2 scenario sweeps, MAF sensitivity, scenario winners and pairwise Monte Carlo ranking diagnostics.
- Added a Round 2 dashboard tab with access assumptions, break-even MAF and ranking stability.
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
data/round2/              Optional Round 2 CSV inputs using round_2 filenames
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
python -m r1bt replay strategies/trader.py --name main_strategy --data-dir data/round1 --days -2 -1 0 --fill-mode empirical_baseline
```

Replay against a live export:

```bash
python -m r1bt replay examples/trader_round1_v9.py --name live_v9 --data-dir data/round1 --days 0 --fill-mode base --live-export live_exports/259168/259168.log
```

Run Monte Carlo:

```bash
python -m r1bt monte-carlo examples/trader_round1_v9.py --name live_v9 --days 0 --fill-mode empirical_baseline --noise-profile fitted --quick
```

Compare traders:

```bash
python -m r1bt compare strategies/trader.py examples/trader_round1_v9.py --names main_strategy live_v9 --data-dir data/round1 --days 0 --fill-mode empirical_baseline
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

Derive an empirical fill profile:

```bash
python -m r1bt derive-fill-profile live_exports/259168/259168.log --profile-name live_empirical
```

Run the calibrated robustness grid:

```bash
python -m r1bt scenario-compare configs/research_scenarios.json
```

Compare no-slippage versus harsher-slippage assumptions:

```bash
python -m r1bt replay strategies/trader.py --data-dir data/round1 --days 0 --fill-mode empirical_baseline --slippage-multiplier 0
python -m r1bt replay strategies/trader.py --data-dir data/round1 --days 0 --fill-mode slippage_stress --slippage-multiplier 1.5
```

## Round 2 workflow

Inspect Round 2 data:

```bash
python -m r1bt inspect --round 2 --data-dir data/round2 --days 0 --json
```

Replay with no extra access:

```bash
python -m r1bt replay strategies/trader.py --round 2 --data-dir data/round2 --days 0 --fill-mode base
```

Replay with a local extra-access assumption and MAF deduction:

```bash
python -m r1bt replay strategies/trader.py --round 2 --data-dir data/round2 --days 0 --fill-mode base --with-extra-access --access-mode deterministic --maf-bid 750 --access-quality 0.75 --access-passive-multiplier 1.12 --access-missed-reduction 0.02
```

Compare current and candidate scripts under one access assumption:

```bash
python -m r1bt compare strategies/trader.py examples/trader_round1_v9.py --names current candidate --round 2 --data-dir data/round2 --days 0 --with-extra-access --access-mode stochastic --access-quality 0.8 --access-probability 0.65 --maf-bid 1000
```

Run the Round 2 decision grid:

```bash
python -m r1bt round2-scenarios configs/round2_scenarios.json
```

Key outputs:

- `round2_scenarios.csv`
- `round2_winners.csv`
- `round2_pairwise_mc.csv`
- `round2_maf_sensitivity.csv`
- dashboard `Round 2` tab

## Round 2 all-in-one research bundle

Use `round2_all_in_one_research_bundle` as the shared output folder for serious Round 2 study. It should collect every bundle needed to compare scripts, inspect risk and make an upload decision without guessing which file answers which question.

Recommended contents:

- Replay bundles for each strategy: inspect one script at full detail. Use these for total PnL, per-product PnL, realised/unrealised/MTM paths, fills, orders, inventory, max drawdown, cap usage, behaviour summaries and markout metrics.
- Compare bundle: rank scripts under one fixed replay assumption. Use this for the clean head-to-head table and first-pass winner.
- Round 2 scenario bundle: test the same scripts across no-access, extra-access and MAF assumptions. Use `round2_winners.csv` for scenario winners and `round2_maf_sensitivity.csv` for fee sensitivity.
- Targeted Monte Carlo bundles: stress the leading scripts on synthetic paths. Use mean, median and P05 to check robustness rather than relying on one replay print.
- Optional calibration bundle: tune or validate fill assumptions against live exports when useful export data exists.

How to read the outputs:

- Total PnL: final net result after any MAF deduction.
- Per-product PnL: identifies whether the edge comes from OSMIUM, PEPPER or both.
- Realised, unrealised and MTM: separates closed trades, open inventory value and full mark-to-market path.
- Fills and orders: shows execution quality and activity level; high orders with low fills can mean passive quoting is not converting.
- Inventory and cap usage: shows how much position risk the script takes and whether it sits near limits.
- Max drawdown: largest peak-to-trough loss in the run.
- Behaviour and markout metrics: checks whether fills are favourable after 1 or 5 ticks, and whether quote placement is helping.
- Scenario winners: shows which script wins under each Round 2 access/MAF assumption.
- MAF sensitivity: shows how much fee a script can absorb before access is no longer worth it.
- Monte Carlo mean, median and P05: mean is average robustness, median is typical run, P05 is downside risk.

Dashboard mapping:

- Replay bundles feed the Overview, Replay, product dive, Inspect and behaviour views.
- Compare bundles feed the Comparison view.
- Round 2 scenario bundles feed the Round 2 view and comparison-style tables. Replay-specific tabs can be empty because scenario bundles contain aggregate rows, not a full tick-by-tick session.
- Monte Carlo bundles feed the Monte Carlo view.
- Calibration bundles feed the Calibration view.

Recommended workflow:

1. Inspect replay bundles for each script and check PnL source, inventory, drawdown, fills and limit breaches.
2. Inspect the compare bundle for the direct ranking under one fixed assumption.
3. Inspect the scenario bundle for winner stability across access quality and MAF levels.
4. Inspect Monte Carlo bundles for mean, median, P05 and drawdown robustness.
5. Pick the script that wins broadly, survives downside checks and has acceptable inventory/execution behaviour.

How to judge a winner:

- Prefer scripts that win across scenarios, not only one setting.
- Prefer robust mean and median performance with a tolerable P05, not one lucky replay print.
- Use this local backtester for ranking, risk diagnosis and decision support, not exact website PnL prediction.

Round 2 limitations:

- The MAF cutoff is website-only because other teams' bids are not known.
- Extra-access usefulness is approximate locally.
- Passive fills, queue position and same-price priority are approximate.

Template note: [docs/bundle_templates/round2_all_in_one_research_bundle/README.md](docs/bundle_templates/round2_all_in_one_research_bundle/README.md) is a compact README for the bundle folder itself.

See [docs/ROUND2.md](docs/ROUND2.md) for the gap analysis, design plan, scenario fields and limitations.
See [docs/CALIBRATED_RESEARCH.md](docs/CALIBRATED_RESEARCH.md) for the calibrated fill, slippage, noise, scenario and validation workflow.

## Dashboard

The dashboard is bundle-aware. It reads the bundle `type` from `dashboard.json` first, then falls back to the actual payload sections when older or partial bundles are loaded. Tabs intentionally show a compatibility message instead of zero-valued cards when the loaded bundle does not contain the required schema.

Dashboard compatibility:

- Overview: works for every recognised bundle and only shows metrics present in that bundle.
- Replay: requires a `replay` bundle with top-level replay series.
- Inspect, Osmium and Pepper: require replay-style per-tick series such as PnL, inventory, fair value, fills or orders.
- Monte Carlo: requires a `monte_carlo` bundle with `monteCarlo.summary`.
- Calibration: requires a `calibration` bundle.
- Comparison: works with `comparison` bundles, compatible `round2_scenarios` comparison diagnostics, or two distinct loaded replay summaries.
- Optimisation: requires an `optimization` bundle.
- Round 2: requires a `round2_scenarios` bundle.

If a tab is unavailable, that is usually intentional: for example, a Round 2 scenario bundle contains aggregate scenario rows, not per-tick replay data, while a Monte Carlo bundle contains distribution and sample-path data, not a top-level replay summary.

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

Round 2 scenario bundles additionally include:

- `round2_scenarios.csv`
- `round2_winners.csv`
- `round2_pairwise_mc.csv`
- `round2_maf_sensitivity.csv`

Calibrated scenario bundles additionally include:

- `scenario_results.csv`
- `scenario_winners.csv`
- `robustness_ranking.csv`
- `scenario_pairwise_mc.csv`

Empirical fill-profile bundles include:

- `empirical_fill_profile.json`
- `empirical_fill_rows.csv`
- `empirical_fill_summary.csv`

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
- Round 2 CSV ingestion and schema checks when files are present
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
- Size-dependent slippage
- Empirical fill probabilities when rejected passive opportunities are not visible
- Extra-quote access usefulness under MAF scenarios
- Historical analysis fair
- Synthetic market generation
- Calibration and optimisation scores

The important distinction is that Monte Carlo `analysis_fair` is the simulator latent fair, while historical replay `analysis_fair` is an inferred diagnostic proxy.

## Tests

```bash
python -m pytest -q
npm test --prefix dashboard
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
- The official Round 2 extra-quote selection and matching mechanics are not known locally.
- Other teams' MAF bids are not known locally.
- Live exports may not expose enough detail for exact inventory-path reconstruction.
- Historical fair value is inferred, not official hidden fair.
- Very large Monte Carlo batches may eventually justify moving the hot loop out of Python.
