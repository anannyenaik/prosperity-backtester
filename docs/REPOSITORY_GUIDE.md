# Repository Guide

This guide documents the submission surface from the top level down. Use it when you want to understand the repo quickly without reading the whole codebase.

Status labels used here:

- `Core`: part of the main submission workflow
- `Optional`: useful tooling or examples, but not required for the core replay path
- `Experimental`: kept for comparison or future work, not the default path
- `Legacy`: compatibility or fallback code that still works, but should not be the starting point

## Top-Level Folders

| Path | Status | What it contains |
| --- | --- | --- |
| `analysis/` | Optional | Thin Python entry points for research packs, replay profiling, validation, calibration wrappers, and benchmark helpers. |
| `backtests/` | Generated output root | The default destination for timestamped run bundles. The repo keeps only `.gitkeep`. |
| `configs/` | Optional | Example JSON configs for sweep, optimisation, scenario comparison, and Round 2 scenario runs. |
| `dashboard/` | Optional | React review UI source. Includes adapter tests and local build configuration. |
| `data/` | Core | Tracked Round 1 and Round 2 public CSV fixtures used by examples and tests. |
| `docs/` | Core | Submission documentation. |
| `examples/` | Optional | Example trader files. Includes a tracked live-export trader and a small benchmark fixture. |
| `legacy_dashboard/` | Legacy | Static HTML dashboard fallback. Used only when a React build is not present. |
| `live_exports/` | Optional | Tracked live-export fixture used for calibration tests and examples. |
| `prosperity_backtester/` | Core | Main Python package. Contains the CLI, dataset loading, execution logic, reporting, storage, and the local bundle server. |
| `r1bt/` | Legacy | Former package-name compatibility wrapper and old `python -m r1bt` entry point. |
| `rust_mc_engine/` | Experimental | Optional Rust implementation of the Monte Carlo backend. |
| `strategies/` | Core examples | Baseline and working strategy files used by the main workflows. |
| `tests/` | Core | Python tests for replay, Monte Carlo, outputs, adapters, server discovery, and optional helpers. |

## Top-Level Files

| File | Status | Purpose |
| --- | --- | --- |
| `README.md` | Core | Submission overview, quick start, and reviewer path. |
| `pyproject.toml` | Core | Packaging metadata, optional extras, console scripts, and package discovery. |
| `.gitignore` | Core | Ignores local environments, build outputs, caches, and generated bundles. |
| `LICENSE` | Core | Licence terms for the repository contents. |

## Core Python Package

### Entry points and workflow orchestration

| Module | Status | Role |
| --- | --- | --- |
| `prosperity_backtester/__main__.py` | Core | Main CLI entry point. Parses commands, output options, Round 2 access flags, and auto-output naming. |
| `prosperity_backtester/experiments.py` | Core | High-level orchestration for replay, comparison, Monte Carlo, calibration, optimisation, and scenario workflows. |
| `prosperity_backtester/research.py` | Optional | Helpers behind `analysis/research_pack.py` and `analysis/profile_replay.py`. |
| `prosperity_backtester/storage.py` | Core | Output profile settings, JSON formatting policy, and pruning of old auto-generated runs. |
| `prosperity_backtester/provenance.py` | Core support | Captures git and runtime provenance for manifests and dashboard payloads. |

### Data and trader loading

| Module | Status | Role |
| --- | --- | --- |
| `prosperity_backtester/dataset.py` | Core | Loads and validates Round 1 and Round 2 CSVs into in-memory datasets. |
| `prosperity_backtester/live_export.py` | Optional | Loads tracked live-export JSON fixtures and normalises them for calibration. |
| `prosperity_backtester/metadata.py` | Core support | Product metadata, limits, labels, and other static constants. |
| `prosperity_backtester/noise.py` | Core support | Named Monte Carlo noise profiles and scaling helpers. |
| `prosperity_backtester/trader_adapter.py` | Core | Loads trader files, installs `datamodel` import aliases, and applies override dictionaries. |
| `prosperity_backtester/datamodel.py` | Core | Prosperity-compatible `TradingState`, `Order`, `OrderDepth`, `Trade`, and related types. |

### Execution and simulation

| Module | Status | Role |
| --- | --- | --- |
| `prosperity_backtester/platform.py` | Core | Main replay and Monte Carlo session engine. Produces fills, orders, summaries, series, and diagnostics. |
| `prosperity_backtester/fill_models.py` | Core | Fill-model presets, empirical profile derivation, and fill-model resolution. |
| `prosperity_backtester/round2.py` | Core | Round 2 Market Access Fee and extra-access scenario model. |
| `prosperity_backtester/scenarios.py` | Core | Scenario definitions for calibrated research runs. |
| `prosperity_backtester/simulate.py` | Core support | Synthetic order-book and trade generation used by Monte Carlo sessions. |
| `prosperity_backtester/mc_backends.py` | Optional | Backend selection for Monte Carlo, including the Python default path and the Rust bridge. |
| `prosperity_backtester/rust_strategy_worker.py` | Experimental | Python worker shim used by the Rust backend to execute trader code. |
| `prosperity_backtester/engine.py` | Core support | Lower-level session and accounting primitives, retained for engine compatibility and legacy callers. |

### Diagnostics and reporting

| Module | Status | Role |
| --- | --- | --- |
| `prosperity_backtester/fair_value.py` | Core support | Diagnostic fair-value estimates and Monte Carlo path-band helpers. |
| `prosperity_backtester/behavior.py` | Core support | Behaviour summaries such as fills, cap usage, and markouts. |
| `prosperity_backtester/reports.py` | Core | Builds `dashboard.json`, writes CSV sidecars, writes manifests, and records data-contract metadata. |
| `prosperity_backtester/dashboard_payload.py` | Core | Compacts retained dashboard payload sections for storage and expands them again on load. |
| `prosperity_backtester/bundle_attribution.py` | Optional | Estimates bundle-size ownership by dashboard section and output file. |
| `prosperity_backtester/server.py` | Core | Lightweight HTTP server for browsing local bundles and serving the dashboard UI. |

### Optional, experimental, and legacy package modules

| Module | Status | Role |
| --- | --- | --- |
| `prosperity_backtester/benchmark.py` | Optional | Shared benchmark helpers used by the `analysis/benchmark_*.py` scripts. |
| `prosperity_backtester/replay.py` | Legacy | Older direct replay helper kept for compatibility. The main workflows use `experiments.py`. |
| `prosperity_backtester/dashboard.py` | Legacy | Older standalone dashboard builder kept for compatibility with older callers. |

## Dashboard

| Path | Status | Role |
| --- | --- | --- |
| `dashboard/package.json` | Optional | Dashboard scripts and dependencies. |
| `dashboard/src/App.tsx` | Optional | App entry point and landing screen. Loads server-run bundles from `/api/runs` when present. |
| `dashboard/src/store.ts` | Optional | Local dashboard state management. |
| `dashboard/src/lib/bundles.ts` | Optional | Bundle-type detection, compact row-table expansion, and tab-availability logic. |
| `dashboard/src/views/` | Optional | Screen-level views for replay, Monte Carlo, comparison, calibration, optimisation, Round 2, and inspection tabs. |
| `dashboard/src/components/` | Optional | Shared UI components for metrics, loaders, tables, and navigation. |
| `dashboard/tests/alphaAdapter.test.mjs` | Optional | Adapter and classification tests for Alpha Lab behaviour. |
| `dashboard/tests/bundleAdapter.test.mjs` | Optional | Adapter tests for bundle-type detection and compact payload expansion. |
| `legacy_dashboard/dashboard.html` | Legacy | HTML fallback used when the React app has not been built locally. |

## Analysis Scripts

### Main optional scripts

| File | Status | Role |
| --- | --- | --- |
| `analysis/research_pack.py` | Optional | Runs the `fast`, `validation`, and `forensic` preset research tiers. |
| `analysis/profile_replay.py` | Optional | Profiles replay phases for one trader or two comparable traders. |
| `analysis/calibrate.py` | Optional | Thin wrapper around the calibration workflow. |
| `analysis/validate.py` | Optional | Thin replay validation wrapper. |

### Benchmark and architecture helpers

| File pattern | Status | Role |
| --- | --- | --- |
| `analysis/benchmark_*.py` | Experimental | Storage, runtime, backend, direct CLI, attribution, and external-reference benchmarking helpers. |
| `analysis/rss_frontier.py` | Experimental | Higher-resolution process-tree RSS probe for Monte Carlo runs. |
| `analysis/architecture_bakeoff.py` | Experimental | Serialisation and transport experiment helper. |

These scripts are kept because they are tested and reusable, but they are not required to review or use the core backtester.

## Strategies, Examples, Configs, and Fixtures

| Path | Status | Role |
| --- | --- | --- |
| `strategies/trader.py` | Core example | Main Round 1 working trader used by the default replay and research examples. |
| `strategies/starter.py` | Core example | Baseline market-making reference used in comparisons and research packs. |
| `strategies/prosperity_r2_340934_plus_offset110.py` | Optional | Round 2 working strategy snapshot. |
| `strategies/r2_algo_v2.py` | Optional | Round 2 working strategy snapshot. |
| `examples/trader_round1_v9.py` | Optional | Tracked trader fixture used for live-export calibration examples. |
| `examples/benchmark_trader.py` | Optional | Small deterministic trader used by benchmark and worker-pool tests. |
| `configs/research_scenarios.json` | Optional | Calibrated scenario-comparison config. |
| `configs/round2_scenarios.json` | Optional | Small Round 2 decision-grid config. |
| `configs/round2_all_in_one_research.json` | Optional | Larger Round 2 comparison config across multiple traders and MAF values. |
| `configs/pepper_sweep.json` | Optional | Small replay-only parameter sweep example. |
| `configs/pepper_optimize.json` | Optional | Replay plus Monte Carlo optimisation example. |
| `configs/pepper_optimize_quick.json` | Optional | Smaller optimisation example for quick checks. |
| `live_exports/259168/259168.json` | Optional | Tracked live-export JSON fixture used by calibration tests and docs. |
| `live_exports/259168/259168.py` | Optional | Source trader snapshot associated with the live-export fixture. |

## Experimental and Compatibility Areas

| Path | Status | Notes |
| --- | --- | --- |
| `rust_mc_engine/Cargo.toml` | Experimental | Rust package definition for the optional Monte Carlo backend. |
| `rust_mc_engine/src/main.rs` | Experimental | Rust Monte Carlo runner and Python trader bridge. |
| `r1bt/__init__.py` | Legacy | Re-exports `prosperity_backtester` under the former package name. |
| `r1bt/__main__.py` | Legacy | Compatibility entry point for `python -m r1bt`. |

## Tests

| File | Status | What it covers |
| --- | --- | --- |
| `tests/test_platform.py` | Core | End-to-end replay, Monte Carlo, output-profile, and live-export behaviour. |
| `tests/test_output_hardening.py` | Core | Bundle-contract and storage hardening checks. |
| `tests/test_round2.py` | Core | Round 2 access assumptions and scenario outputs. |
| `tests/test_fill_models.py` | Core | Fill-model behaviour and empirical profile logic. |
| `tests/test_scenarios.py` | Core | Scenario configuration and comparison flows. |
| `tests/test_research.py` | Core | Research-pack and profiling helpers. |
| `tests/test_smoke.py` | Core | Repo fixtures, compatibility imports, and bundle discovery behaviour. |
| `tests/test_analysis_scripts.py` | Optional surface | Analysis-helper script coverage. |
| `tests/test_benchmark.py` | Optional surface | Benchmark helper coverage. |
