# Repository Guide

This guide is the fastest way to understand the active submission surface.

## Top-level folders

| Path | Status | What it contains |
| --- | --- | --- |
| `analysis/` | Optional | Helper wrappers, profiling scripts, and benchmark helpers. |
| `backtests/` | Generated output root | Default destination for timestamped run bundles. |
| `configs/` | Core support | Checked-in Round 2 and Round 3 smoke and scenario configs. |
| `dashboard/` | Optional | React review UI source. |
| `data/` | Core | Tracked Round 1, Round 2, and Round 3 public CSV fixtures. |
| `docs/` | Core | Workflow, assumptions, architecture, and round notes. |
| `examples/` | Core support | Smoke helpers and historical examples. |
| `prosperity_backtester/` | Core | Main Python package. |
| `strategies/` | Historical examples | Round 2 tracked strategy files and legacy examples. |
| `tests/` | Core | Regression coverage for runtime, output contracts, and helper scripts. |

## Core Python package

### Entry points and orchestration

| Module | Role |
| --- | --- |
| `prosperity_backtester/__main__.py` | Main CLI entry point. |
| `prosperity_backtester/experiments.py` | High-level orchestration for replay, compare, Monte Carlo, calibration, and scenario workflows. |
| `prosperity_backtester/storage.py` | Output profile settings and pruning. |
| `prosperity_backtester/provenance.py` | Git and runtime provenance capture. |

### Data and metadata

| Module | Role |
| --- | --- |
| `prosperity_backtester/dataset.py` | Loads and validates round-specific CSV datasets. |
| `prosperity_backtester/metadata.py` | Round registry, `ProductMeta`, and `RoundSpec`. |
| `prosperity_backtester/round2.py` | Round 2 access and MAF assumptions. |
| `prosperity_backtester/round3.py` | Round 3 voucher helpers, diagnostics, and coherent synthetic generation. |
| `prosperity_backtester/datamodel.py` | Prosperity-compatible state and order classes. |
| `prosperity_backtester/trader_adapter.py` | Trader loading and compatibility shims. |

### Execution and diagnostics

| Module | Role |
| --- | --- |
| `prosperity_backtester/platform.py` | Main replay and Monte Carlo engine. |
| `prosperity_backtester/fill_models.py` | Fill-model presets and empirical profiles. |
| `prosperity_backtester/fair_value.py` | Diagnostic fair-value estimates and path bands. |
| `prosperity_backtester/behavior.py` | Behaviour summaries such as fills, cap usage, and markouts. |
| `prosperity_backtester/mc_backends.py` | Monte Carlo backend selection. |
| `prosperity_backtester/simulate.py` | Legacy synthetic helpers used by non-Round-3 paths. |

### Reporting

| Module | Role |
| --- | --- |
| `prosperity_backtester/reports.py` | Builds `dashboard.json`, writes `manifest.json`, and writes CSV sidecars. |
| `prosperity_backtester/dashboard_payload.py` | Compacts and expands large dashboard payload sections. |
| `prosperity_backtester/server.py` | Local bundle browser and dashboard server. |

## Key tracked helpers

| Path | Role |
| --- | --- |
| `examples/noop_round3_trader.py` | Runnable Round 3 smoke fixture. |
| `configs/round3_smoke.json` | Minimal Round 3 scenario-compare smoke config. |
| `configs/round3_mc_smoke.json` | Minimal Round 3 Monte Carlo smoke config. |
| `configs/round3_research_scenarios.json` | Round 3 research scenario pack. |
| `docs/ROUND3.md` | Round 3 rules, data, and fidelity notes. |

## Tests

| File | What it covers |
| --- | --- |
| `tests/test_round3.py` | Round 3 metadata, data loading, replay, passive fills, option helpers, and coherent Monte Carlo. |
| `tests/test_round2.py` | Round 2 access assumptions and scenario outputs. |
| `tests/test_platform.py` | Replay, Monte Carlo, and output-profile behaviour. |
| `tests/test_output_hardening.py` | Bundle contract and storage hardening. |
