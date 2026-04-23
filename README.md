# Prosperity Backtester

Internal research platform for Prosperity Round 1 and Round 2 strategy work on:

- `ASH_COATED_OSMIUM`
- `INTARIAN_PEPPER_ROOT`

It supports deterministic replay, configurable fill models, trader comparison, parameter sweeps, optimisation, Monte Carlo robustness checks, live-export calibration, Round 2 Market Access Fee scenarios and a React dashboard for reviewing output bundles.

Use it for relative strategy selection, execution-risk diagnosis and handoff-ready research evidence. It is not an official exchange simulator.

## Copyright

Copyright (c) 2026 Anannye Naik. All rights reserved.

No licence is granted to copy, modify, distribute or reuse the original code or
documentation in this repository without prior written permission. Third-party
or public datasets and other third-party material remain under their own terms.
See [LICENSE](LICENSE).

## Repository Layout

```text
analysis/                 Thin validation, calibration, profiling and research-pack entry scripts
configs/                  Sweep, optimisation, scenario and Round 2 configs
data/round1/              Round 1 public CSV inputs
data/round2/              Round 2 public CSV inputs
dashboard/                React/Vite dashboard source and tracked build output
docs/                     Architecture, workflow and assumption notes
examples/                 Example trader script fixtures, including a lightweight benchmark trader
legacy_dashboard/         Static dashboard fallback used when no React build exists
live_exports/             Tracked live-export fixture data for calibration tests
prosperity_backtester/    Core replay, simulation, calibration and reporting package
r1bt/                     Compatibility wrapper for older local imports
strategies/               Starter and working strategy files
tests/                    Backend and dashboard adapter checks
```

Generated research bundles are written to `backtests/` unless `--output-dir` is supplied. `backtests/`, local logs, virtual environments, caches and `dashboard/node_modules/` are ignored.

Runs default to the lightweight output profile. Replay and compare also default to day `0` so the routine branch loop stays fast. Light bundles keep exact summaries and fills, event-aware compact chart paths, compact submitted quote intent, preview-capped sampled Monte Carlo runs and all-session Monte Carlo path bands while avoiding raw order dumps, duplicated series sidecars, sampled path files and child bundles. Use `--output-profile full` only for deep debugging. Full mode can now be trimmed deliberately with `--no-series-sidecars`, `--no-orders`, `--no-sample-path-files` and `--no-session-manifests`. See [docs/OUTPUTS.md](docs/OUTPUTS.md).

## Setup

Python runtime code uses the standard library only. Tests use `pytest`.

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

Use `python -m pip install -e ".[dev,analysis]"` when you also want the
benchmark, comparison and architecture bake-off helpers.

Dashboard setup:

```bash
cd dashboard
npm ci
npm test
npm run build
```

The installed console command is `prosperity-backtester`. All examples below use `python -m prosperity_backtester` because it works without installation. The older `python -m r1bt` and `r1mcbt` entry points are kept only for compatibility.

## Core Commands

Inspect input data:

```bash
python -m prosperity_backtester inspect --data-dir data/round1 --days -2 -1 0 --json
python -m prosperity_backtester inspect --round 2 --data-dir data/round2 --days 0 --json
```

Replay one trader. This now defaults to day `0` for routine work:

```bash
python -m prosperity_backtester replay strategies/trader.py --name current --data data/round1 --fill-mode empirical_baseline
```

Replay against a tracked live export:

```bash
python -m prosperity_backtester replay examples/trader_round1_v9.py --name live_v9 --data-dir data/round1 --days 0 --fill-mode base --live-export live_exports/259168/259168.json
```

Replay with stricter or disabled passive trade-print matching when you want a trust check against optimistic fill assumptions:

```bash
python -m prosperity_backtester replay strategies/trader.py --name current --data data/round1 --fill-mode empirical_baseline --match-trades worse
python -m prosperity_backtester replay strategies/trader.py --name current --data data/round1 --fill-mode empirical_baseline --match-trades none
python -m prosperity_backtester replay strategies/trader.py --name current --data data/round1 --fill-mode empirical_baseline --limit INTARIAN_PEPPER_ROOT:40 --print
```

Compare trader scripts. This also defaults to day `0`:

```bash
python -m prosperity_backtester compare strategies/trader.py examples/trader_round1_v9.py --names current candidate --data data/round1 --fill-mode empirical_baseline
python -m prosperity_backtester compare strategies/trader.py strategies/starter.py --names current starter --data data/round1 --fill-mode empirical_baseline --merge-pnl
```

Run Monte Carlo:

```bash
python -m prosperity_backtester monte-carlo strategies/trader.py --name current --days 0 --fill-mode empirical_baseline --noise-profile fitted --quick
python -m prosperity_backtester monte-carlo strategies/trader.py --name current --days 0 --fill-mode empirical_baseline --noise-profile fitted --sessions 256 --sample-sessions 16 --workers 4
python -m prosperity_backtester monte-carlo strategies/trader.py --name current --days 0 --fill-mode empirical_baseline --noise-profile fitted --sessions 512 --workers 8 --mc-backend rust
```

## Research Loop

Use the repo in three deliberate tiers.

Fast loop for normal branch testing:

```bash
python analysis/research_pack.py fast --trader strategies/trader.py --baseline strategies/starter.py
```

This writes only:

- `replay/`
- `compare/`
- `monte_carlo/`
- `pack_summary.json`

Validation loop for promising branches:

```bash
python analysis/research_pack.py validation --trader strategies/trader.py --baseline strategies/starter.py
```

Heavy forensic loop for finalists or suspicious behaviour only:

```bash
python analysis/research_pack.py forensic --trader strategies/trader.py --baseline strategies/starter.py
```

Profile replay slowdown by day:

```bash
python analysis/profile_replay.py strategies/trader.py --compare-trader strategies/starter.py --data-dir data/round1 --fill-mode empirical_baseline
```

The proof split is now explicit.

The current audited review root is `backtests/review_2026-04-23_final`.

The core headline artefacts in that review root were captured on clean commit
`d041e8bc4e2b94b7fe0664330df142a88f174569`:

- `runtime/`
- `storage/`
- `attribution/`
- `backend/`
- `reference/`
- `architecture/`

The three `rss_frontier*` reruns were captured immediately after the
parent-versus-reporting RSS wording fix in `analysis/rss_frontier.py`, so those
reports record `git_dirty: true`. Use them for memory shape and driver
attribution, not headline throughput.

Current local branch-loop timings from
`backtests/review_2026-04-23_final/runtime/benchmark_report.json`:

- default day-0 replay: `2.917s`
- default day-0 compare: `2.207s`
- fast pack: `5.203s`
- validation pack: `17.646s`

Tracked `250`-tick Monte Carlo throughput table from the clean current-local
runtime rerun:

| Case | 1 worker | 2 workers | 4 workers | 8 workers |
| --- | ---: | ---: | ---: | ---: |
| MC quick light (64 sess) | `1.499s` | `1.366s` | `1.229s` | `1.242s` |
| MC default light (100 sess) | `1.943s` | `1.827s` | `1.432s` | `1.417s` |
| MC heavy light (192 sess) | `3.400s` | `n/a` | `n/a` | `1.769s` |
| MC ceiling light (768 sess) | `n/a` | `n/a` | `n/a` | `3.435s` |

Current retained-output sizes from
`backtests/review_2026-04-23_final/storage/benchmark_report.json`:

- replay light: `1.36 MB`, `6` files
- replay full: `1.99 MB`, `12` files
- Monte Carlo light: `819.8 KB`, `6` files
- Monte Carlo full: `5.16 MB`, `18` files

Fresh direct CLI spot checks stayed within `-7.3%` to `+3.3%` of the monitored
harness on the headline cases, so the benchmark harness wording is now honest
and defensible rather than a different timing mode.

Fresh `5 ms` ceiling probes on `mc_ceiling_light_w8` now make the remaining gap
precise rather than fuzzy. The sharp remaining blocker is still execution-phase
process-tree RSS, not dashboard assembly:

- tree peak reruns: `418.1 MB`, `421.0 MB`, `422.7 MB`
- workers alive at the tree peak: `8`
- live worker RSS at the tree peak: `282.8 MB` to `289.6 MB`
- parent RSS at the exact tree peak: `128.4 MB` to `138.2 MB`
- later parent-only `bundle_write` peak: `269.8 MB` to `316.7 MB`

The default streaming Monte Carlo backend remains the design default, but the
fresh realistic-trader rerun is now more mixed than the earlier proof text
said. Use `--mc-backend classic` for parity checks and fresh local timing
checks as well as replay-style materialisation. The compiled `rust` backend
remains available for explicit backend experiments only. On the clean rerun in
`backtests/review_2026-04-23_final/backend`, `streaming` won `4` of the `7`
measured cells, `classic` won `3`, and `rust` won none.

Forensic work is still deliberate full-profile work and should be treated as a minute-scale task rather than part of the normal branch loop.

## Platform Positioning

Compared with simpler replay backtesters, this repo now keeps a short daily loop through day-0 defaults, `--match-trades`, per-day PnL output, `--open`, and `serve --latest`, while still carrying compare, optimisation, calibration, scenarios and Round 2 research.

Compared with Monte Carlo-first repos, this repo now makes the practical path
faster and the proof layer clearer. The default `streaming` backend remains the
design default, `classic` is now a co-equal parity and performance option, and
`rust` stays available as an explicit experiment rather than a recommendation.
Chris Roberts' repo remains
the strongest narrow tutorial-round Monte Carlo reference, but this repo is
the stronger end-to-end research platform on the locally available evidence.
On the fresh same-machine shared no-op trader benchmark in
`backtests/review_2026-04-23_final/reference`, with matched `250`-tick
sessions, matched `100/10` and `1000/100` session or sample tiers, and matched
`1`, `2`, `4`, and `8` worker settings, this repo was `3.78x` to `15.54x`
faster on the default cases and `9.46x` to `18.80x` faster on the ceiling
cases,
wrote fewer retained bytes in every measured cell, and used far fewer files
(`5` versus `50` or `410`). On the smaller `100/10` cases it also used less
RSS, but Chris still kept the lighter RSS on the `1000/100` ceiling cases.
That proves a strong same-machine runtime and retained-byte lead on the matched
no-op comparison, not an undisputed all-axis performance crown.

See [docs/REFERENCE_COMPARISON.md](docs/REFERENCE_COMPARISON.md) for the
detailed comparison against the locally available reference repos.

Run a parameter sweep or optimisation:

```bash
python -m prosperity_backtester sweep configs/pepper_sweep.json
python -m prosperity_backtester optimize configs/pepper_optimize_quick.json
```

Derive and use empirical fill assumptions:

```bash
python -m prosperity_backtester derive-fill-profile live_exports/259168/259168.json --profile-name live_empirical
python -m prosperity_backtester calibrate examples/trader_round1_v9.py --name live_v9 --data-dir data/round1 --days 0 --live-export live_exports/259168/259168.json --quick
```

Run calibrated robustness scenarios:

```bash
python -m prosperity_backtester scenario-compare configs/research_scenarios.json
```

## Comparing Trader Scripts

Use `compare` when you want one fixed replay assumption across multiple scripts.

```bash
python -m prosperity_backtester compare strategies/trader.py strategies/starter.py --names current starter --data-dir data/round1 --fill-mode empirical_baseline
```

Good review sequence:

1. Run replay for each serious script and inspect product PnL, drawdown, fills and inventory.
2. Run `compare` under one fixed fill model to get a clean ranking.
3. Run `scenario-compare` to check the ranking under conservative fills, wider spreads, thinner depth, slippage and crash assumptions.
4. Run targeted Monte Carlo on the leading scripts and compare mean, median, P05 and drawdown.
5. Prefer a script that wins across assumptions and has explainable per-product behaviour.

Parameter overrides can be supplied in sweep and optimisation configs using dotted paths such as:

```json
{
  "PARAMS.INTARIAN_PEPPER_ROOT.trend_slope": 0.0015
}
```

## Round 2 Workflow

Round 2 uses the same products and CSV schema with `prices_round_2_day_<day>.csv` and `trades_round_2_day_<day>.csv`.

Replay with no extra access:

```bash
python -m prosperity_backtester replay strategies/trader.py --round 2 --data-dir data/round2 --days 0 --fill-mode base
```

Replay with a local extra-access assumption and MAF deduction:

```bash
python -m prosperity_backtester replay strategies/trader.py --round 2 --data-dir data/round2 --days 0 --fill-mode base --with-extra-access --access-mode deterministic --maf-bid 750 --access-quality 0.75 --access-passive-multiplier 1.12 --access-missed-reduction 0.02
```

Run the standard Round 2 decision grid. This checked-in config is intentionally quick: one day, replay-only, three MAF points and two trader variants.

```bash
python -m prosperity_backtester round2-scenarios configs/round2_scenarios.json
```

Run the all-in-one Round 2 comparison config:

```bash
python -m prosperity_backtester round2-scenarios configs/round2_all_in_one_research.json --output-dir backtests/round2_all_in_one_research_bundle
```

Round 2 outputs are scenario evidence. They model known MAF rules and configurable access assumptions, but cannot know other teams' bids, exact extra-quote selection or hidden queue priority.

## Dashboard

Build the dashboard:

```bash
npm run build --prefix dashboard
```

Serve the repo or a curated review root:

```bash
python -m prosperity_backtester serve --port 5555
python -m prosperity_backtester serve --dir backtests/review_2026-04-23_final/runtime/cases --port 5555
python -m prosperity_backtester serve --latest
python -m prosperity_backtester serve --latest-type replay
python -m prosperity_backtester serve --latest-type monte-carlo
```

Open:

```text
http://127.0.0.1:5555/
```

You can drag one or more `dashboard.json` bundles into the app, use **Open
latest run**, **Latest replay**, **Latest MC**, **Latest compare**, **Latest
calibration**, **Latest optimise**, or **Latest Round 2**, or use **Browse
local server** to discover bundles under the served directory. The server reads
`manifest.json` and `run_registry.jsonl` first when available, hides the main
benchmark scratch bundles, and keeps workflow metadata visible. For the clean
audited review pack from this pass, `backtests/review_2026-04-23_final/runtime/cases`
is still the cleanest review surface.

To finish a workflow and jump straight into the written bundle:

```bash
python -m prosperity_backtester replay strategies/trader.py --data-dir data/round1 --fill-mode empirical_baseline --open
python -m prosperity_backtester monte-carlo strategies/trader.py --days 0 --fill-mode empirical_baseline --noise-profile fitted --quick --open
```

During dashboard development:

```bash
python -m prosperity_backtester serve --port 5555
npm run dev --prefix dashboard
```

The Vite dev server proxies `/api` to `http://127.0.0.1:5555`.

## Storage Benchmark

Measure the default light/full bundle footprint with the tracked quick fixture:

```bash
python analysis/benchmark_outputs.py --output-dir backtests/repo_output_benchmark
```

The helper uses `examples/benchmark_trader.py`, copies the first 250 timestamps from the selected tracked day into a temporary replay fixture, limits synthetic Monte Carlo sessions to the same 250 ticks, runs replay light/full and Monte Carlo light/full, then writes:

- `benchmark_report.json`
- `benchmark_report.md`

The default benchmark case uses 4 Monte Carlo sessions and 2 saved samples so it stays quick. Use `--trader`, `--sessions`, `--sample-sessions` or `--fixture-timestamps` when you need strategy-specific numbers. See [docs/BENCHMARKS.md](docs/BENCHMARKS.md).

## Runtime Benchmark

Benchmark the day-to-day loop, pack tiers and Monte Carlo scaling:

```bash
python analysis/benchmark_runtime.py --output-dir backtests/runtime_benchmark
```

This writes:

- `benchmark_report.json`
- `benchmark_report.md`

Use `--compare-report` to compare the current repo against an earlier report from another worktree or clone.

For a tracked machine-readable summary of the latest audited local run, see
[docs/BENCHMARK_SUMMARY.json](docs/BENCHMARK_SUMMARY.json).

## Bundle Attribution Benchmark

Attribute retained bytes, file counts and reporting-phase RSS to concrete
bundle sections:

```bash
python analysis/benchmark_attribution.py --runtime-report backtests/runtime_benchmark/benchmark_report.json --output-dir backtests/bundle_attribution
```

This writes:

- `bundle_attribution.json`
- `bundle_attribution.md`

## Execution RSS Frontier

Probe the wide-worker Monte Carlo ceiling RSS with process-tree sampling and
machine-readable chunk diagnostics:

```bash
python analysis/rss_frontier.py --output-dir backtests/rss_frontier --baseline-report backtests/runtime_benchmark/benchmark_report.json
```

This writes:

- `rss_frontier_report.json`
- `rss_frontier_report.md`

## Backend Benchmark

Benchmark `streaming`, `classic` and `rust` on realistic repo traders:

```bash
python analysis/benchmark_backends.py --output-dir backtests/backend_benchmark --warmup 1 --measured-repeats 2
```

This writes:

- `backend_benchmark.json`
- `backend_benchmark.md`

## External Reference Benchmark

Compare this repo against a local Chris Roberts clone on the same machine:

```bash
python analysis/benchmark_chris_reference.py --reference-root path/to/imc-prosperity-4/backtester --output-dir backtests/reference_benchmark
```

This writes:

- `reference_benchmark.json`
- `reference_benchmark.md`

## Architecture Bake-Off

Run the transport and serialisation micro-benchmarks on a real dashboard
payload:

```bash
python analysis/architecture_bakeoff.py --output-dir backtests/architecture_bakeoff --bundle backtests/runtime_benchmark/cases/mc_ceiling_light_w8/dashboard.json
```

This writes:

- `architecture_bakeoff.json`
- `architecture_bakeoff.md`

## Bundle Types

Replay bundles:

- `dashboard.json`
- `manifest.json`
- `run_summary.csv`
- `session_summary.csv`
- `fills.csv`
- `behaviour_summary.csv`

In light mode, `dashboard.json` is the canonical source for compact `inventorySeries`, `pnlSeries`, `fairValueSeries`, `behaviourSeries` and `orderIntent`. Full replay bundles also include full series CSV sidecars, `order_intent.csv` and raw `orders.csv`. Use `--series-sidecars` when you want chart-series CSVs without switching on every full-mode artefact.

Monte Carlo light bundles add exact final distribution stats, all-session
`pathBands` and sampled qualitative preview runs inside `dashboard.json`. The
light bundle may store `sessions`, sampled preview series and path-band leaves
using the internal `row_table_v1` encoding, which the dashboard expands on
load. The path-band quantiles are exact across all sessions at retained bucket
endpoints; omitted ticks contribute min/max envelopes. When `pathBands`
already carry `analysisFair` and `mid`, duplicate `fairValueBands` are not
retained separately. Full Monte Carlo bundles also add:

- `sample_paths/`
- `sessions/`

Comparison bundles add:

- `comparison.csv`

Optimisation bundles add:

- `optimization.csv`

Calibration bundles add:

- `calibration_grid.csv`
- `empirical_profile/empirical_fill_profile.json`

Round 2 scenario bundles add:

- `round2_scenarios.csv`
- `round2_winners.csv`
- `round2_pairwise_mc.csv`
- `round2_maf_sensitivity.csv`

Calibrated scenario bundles add:

- `scenario_results.csv`
- `scenario_winners.csv`
- `robustness_ranking.csv`
- `scenario_pairwise_mc.csv`

Every generated parent output directory receives `run_registry.jsonl`. Auto-generated timestamped runs under `backtests/` keep the newest 30 runs by default, sorted by the timestamp in the folder name with `manifest.json` `created_at` as a fallback. Custom `--output-dir` paths are never pruned automatically.

Every `manifest.json` also records:

- resolved output profile
- bundle data contract
- canonical, sidecar and debug file lists
- total bundle size and file count
- command provenance
- workflow tier
- backend, Monte Carlo backend, parallelism and worker metadata
- data scope and runtime phase timings where relevant
- git commit, branch and dirty-worktree state when available

## Interpreting Outputs

- `final_pnl`: net result after any MAF deduction.
- `gross_pnl_before_maf`: strategy PnL before a winning MAF fee is deducted.
- `per_product`: source of PnL by product.
- `realised`, `unrealised`, `mtm`: closed PnL, open inventory value and full mark-to-market value.
- `fills`: exact execution rows retained in light and full replay bundles.
- `orderIntent`: compact submitted quote intent retained in light mode, including best submitted bid/ask, signed quantity, aggressive/passive quantity, quote width and one-sided flags.
- `orders`: raw submitted order rows available in full mode.
- `inventorySeries`: compact dashboard position path and limit pressure.
- `max_drawdown`: largest peak-to-trough loss in the run.
- `behaviour_summary`: cap usage, fill mix, markouts and product-level diagnostics.
- `fairValueSeries`: compact diagnostic fair-value proxy on historical replay and latent fair in Monte Carlo.
- `round2_winners.csv`: scenario winners under each Round 2 assumption.
- `round2_maf_sensitivity.csv`: access value before and after tested MAF levels.
- Monte Carlo `mean`, `p50`, `p05` and expected shortfall: average, typical, downside and tail-risk evidence.
- Monte Carlo `pathBands`: all-session analysis fair, mid, inventory and PnL quantiles for path diagnostics. Sampled runs remain examples, not the source of the bands.
- Monte Carlo sample-run `*PreviewTruncated` and `*TotalCount` fields: show when light mode retained only a preview of the sampled run rather than every row.

## New Round Handoff

Use [docs/NEW_ROUND_CHECKLIST.md](docs/NEW_ROUND_CHECKLIST.md) when a new round drops. It covers data onboarding, product registration, mechanism hooks, templates, trust checks, benchmark refresh and docs updates.

## Config Files

Configs are JSON objects. Relative paths are resolved from the current working directory when they exist there, otherwise from the config file location.

Common fields:

- `name`: output/run label.
- `round`: `1` or `2`.
- `data_dir`: input CSV directory.
- `days`: list of days to load.
- `trader`: base trader path.
- `traders`: explicit list of trader objects with `name`, `path` and optional `overrides`.
- `variants`: parameter variants for sweep, optimisation or scenario comparison.
- `fill_model`: built-in fill model name.
- `fill_config`: optional empirical fill-profile JSON.
- `perturbation`: replay or Monte Carlo perturbation fields.
- `synthetic_tick_limit`: optional Monte Carlo tick cap for smoke or benchmark runs.
- `mc_sessions`, `mc_sample_sessions`, `mc_seed`, `mc_workers`: Monte Carlo controls.
- `mc_backend`: `auto` (resolves to `streaming`), `streaming`, `classic`, or `rust` (explicit only, never auto-selected).
- `output_profile`: `light` or `full`.
- `save_child_bundles`: keep per-variant or per-scenario child bundles for aggregate workflows.
- `write_series_csvs` or `series_sidecars`: write chart-series CSV sidecars.
- `include_orders`: write raw submitted order rows.
- `write_sample_path_files`: write duplicate Monte Carlo `sample_paths/` files.
- `write_session_manifests`: write one Monte Carlo manifest per saved session.
- `max_series_rows_per_product`: light-mode compact path budget. `0` keeps every row.
- `max_mc_path_rows_per_product`: Monte Carlo path-band bucket budget. `0` keeps every timestamp.
- `max_sample_preview_rows_per_series`: light-mode sampled-run preview budget per Monte Carlo series. `0` keeps every saved row.
- `pretty_json`: write indented JSON for debugging.
- `compact_json`: force compact JSON.

Useful starting points:

- `configs/pepper_sweep.json`
- `configs/pepper_optimize_quick.json`
- `configs/research_scenarios.json`
- `configs/round2_scenarios.json`
- `configs/round2_all_in_one_research.json`

## Trader Compatibility

Add a Python file with the standard Prosperity contract:

```python
class Trader:
    def run(self, state):
        return orders, conversions, trader_data
```

Supported import styles:

- `from datamodel import ...`
- `from prosperity_backtester.datamodel import ...`
- `from prosperity3bt.datamodel import ...`
- `from prosperity4mcbt.datamodel import ...`

## Assumptions And Limits

Exact relative to local inputs:

- CSV schema validation and timestamp ordering.
- Visible-book aggressive fills.
- Trader state and own-trade hand-off.
- Cash, inventory, realised, unrealised and MTM accounting.
- Deterministic replay over provided timestamps.
- Synthetic latent fair inside Monte Carlo.

Approximate:

- Passive queue position and same-price priority.
- Missed passive fills.
- Adverse selection and size-dependent slippage.
- Empirical fill probabilities when rejected passive opportunities are not visible.
- Historical analysis fair.
- Synthetic market generation.
- Calibration and optimisation scores.
- Round 2 extra-access usefulness and MAF bid cutoff.

Use the platform to rank scripts, find fragility and prepare upload decisions. Treat small PnL gaps as suspect until they survive conservative fills, scenario checks and Monte Carlo downside tests.

## Verification

Recommended checks before sharing a research branch:

```bash
python -m compileall -q prosperity_backtester r1bt analysis strategies tests
python -m pytest -q
npm test --prefix dashboard
npm run build --prefix dashboard
python analysis/profile_replay.py strategies/trader.py --compare-trader strategies/starter.py --data-dir data/round1 --fill-mode empirical_baseline
python analysis/benchmark_outputs.py --output-dir backtests/repo_output_benchmark
python analysis/benchmark_runtime.py --output-dir backtests/runtime_benchmark --workers 1 2 4 8
```

With `uv`:

```bash
uv run --with pytest pytest -q
```
