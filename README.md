# Prosperity Backtester

Result: this repository is a submission-ready Prosperity research toolkit for deterministic replay, Monte Carlo robustness checks, live-export calibration, Round 2 access scenario analysis, and local dashboard review.

It covers two public products:

- `ASH_COATED_OSMIUM`
- `INTARIAN_PEPPER_ROOT`

The submission surface is intentionally small:

- core runtime: `prosperity_backtester/`, `data/`, `strategies/`, `tests/`
- optional reviewer tooling: `dashboard/`, `analysis/`, `configs/`, `examples/`, `live_exports/`
- experimental or compatibility-only areas: `rust_mc_engine/`, `r1bt/`, `legacy_dashboard/`

## Quick Start

Runtime code uses the Python standard library only. Tests use `pytest`.

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

Install the extra analysis dependencies only if you want the optional research or benchmark helpers:

```bash
python -m pip install -e ".[dev,analysis]"
```

The review dashboard is a separate optional React app:

```bash
npm ci --prefix dashboard
npm test --prefix dashboard
npm run build --prefix dashboard
```

`python -m prosperity_backtester serve` uses the React build when `dashboard/dist/` exists. If you skip the build, it falls back to `legacy_dashboard/dashboard.html`.

## Reviewer Path

Inspect the input data:

```bash
python -m prosperity_backtester inspect --data-dir data/round1 --days -2 -1 0 --json
python -m prosperity_backtester inspect --round 2 --data-dir data/round2 --days -1 0 1 --json
```

Run the main replay workflow:

```bash
python -m prosperity_backtester replay strategies/trader.py --data data/round1 --fill-mode empirical_baseline
```

Compare a working strategy against the baseline:

```bash
python -m prosperity_backtester compare strategies/trader.py strategies/starter.py --names current starter --data data/round1 --fill-mode empirical_baseline --merge-pnl
```

Run a quick robustness check:

```bash
python -m prosperity_backtester monte-carlo strategies/trader.py --days 0 --fill-mode empirical_baseline --noise-profile fitted --quick
```

Open the latest output bundle:

```bash
python -m prosperity_backtester serve --latest
```

## Repository Layout

| Path | Status | Purpose |
| --- | --- | --- |
| `analysis/` | Optional | Research-pack, profiling, calibration, validation, and benchmark helpers. |
| `backtests/` | Generated output root | Default location for auto-named run bundles. Kept empty in git on purpose. |
| `configs/` | Optional | Example JSON configs for sweep, optimisation, scenario, and Round 2 runs. |
| `dashboard/` | Optional | React review UI source and dashboard adapter tests. Build locally when needed. |
| `data/` | Core | Round 1 and Round 2 CSV fixtures used by tests and examples. |
| `docs/` | Core | Submission-facing documentation. |
| `examples/` | Optional | Example trader fixtures, including a small benchmark trader and a tracked live-export trader. |
| `legacy_dashboard/` | Legacy | Static HTML fallback used only when no React build is present. |
| `live_exports/` | Optional | Tracked live-export fixture data for calibration tests and examples. |
| `prosperity_backtester/` | Core | Main Python package. CLI, engine, reporting, storage, and server all live here. |
| `r1bt/` | Legacy | Compatibility wrapper for older imports and `python -m r1bt`. |
| `rust_mc_engine/` | Experimental | Optional Rust Monte Carlo backend. Not the default path. |
| `strategies/` | Core examples | Baseline, working, and Round 2 strategy files. |
| `tests/` | Core | Python regression tests for runtime, outputs, adapters, and analysis helpers. |

Important top-level files:

| File | Purpose |
| --- | --- |
| `pyproject.toml` | Packaging, extras, console scripts, and setuptools package discovery. |
| `.gitignore` | Ignores local environments, build outputs, caches, and generated runs. |
| `LICENSE` | Repository licence terms. |
| `README.md` | Submission overview and reviewer path. |

For the detailed file and module map, see [docs/REPOSITORY_GUIDE.md](docs/REPOSITORY_GUIDE.md).

## Core Commands

Replay defaults to day `0` and the light output profile:

```bash
python -m prosperity_backtester replay strategies/trader.py --data data/round1 --fill-mode empirical_baseline
```

Compare multiple traders under one replay assumption:

```bash
python -m prosperity_backtester compare strategies/trader.py strategies/starter.py --names current starter --data data/round1 --fill-mode empirical_baseline --merge-pnl
```

Run Monte Carlo directly:

```bash
python -m prosperity_backtester monte-carlo strategies/trader.py --days 0 --fill-mode empirical_baseline --noise-profile fitted --sessions 256 --sample-sessions 16 --workers 4
```

Use the preset research tiers:

```bash
python analysis/research_pack.py fast --trader strategies/trader.py --baseline strategies/starter.py
python analysis/research_pack.py validation --trader strategies/trader.py --baseline strategies/starter.py
python analysis/research_pack.py forensic --trader strategies/trader.py --baseline strategies/starter.py
```

Run calibration against the tracked live export:

```bash
python -m prosperity_backtester calibrate examples/trader_round1_v9.py --name live_v9 --data-dir data/round1 --days 0 --live-export live_exports/259168/259168.json --quick
```

Run calibrated scenario comparison:

```bash
python -m prosperity_backtester scenario-compare configs/research_scenarios.json
```

Run Round 2 access scenarios:

```bash
python -m prosperity_backtester round2-scenarios configs/round2_scenarios.json
```

Prune old auto-generated output directories:

```bash
python -m prosperity_backtester clean --keep 30
```

## Status Guide

Core:

- `prosperity_backtester.__main__`
- `prosperity_backtester.experiments`
- `prosperity_backtester.platform`
- `prosperity_backtester.dataset`
- `prosperity_backtester.reports`
- `prosperity_backtester.storage`
- `prosperity_backtester.server`

Optional:

- `analysis/research_pack.py`
- `analysis/profile_replay.py`
- `dashboard/`
- `configs/`
- `live_exports/`

Experimental:

- `rust_mc_engine/`
- Rust support inside `prosperity_backtester.mc_backends`
- benchmark and architecture bake-off helpers in `analysis/`

Legacy or compatibility-only:

- `r1bt/`
- `legacy_dashboard/`
- `prosperity_backtester.replay`
- `prosperity_backtester.dashboard`

## Documentation

- [docs/REPOSITORY_GUIDE.md](docs/REPOSITORY_GUIDE.md): top-level folders, important files, and module map
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): system layers and runtime flow
- [docs/WORKFLOWS.md](docs/WORKFLOWS.md): practical commands and review loops
- [docs/OUTPUTS.md](docs/OUTPUTS.md): bundle structure, output profiles, and retention
- [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md): exact behaviour versus local modelling assumptions
- [docs/ROUND2.md](docs/ROUND2.md): Round 2 access workflow
- [docs/CALIBRATED_RESEARCH.md](docs/CALIBRATED_RESEARCH.md): live-export calibration workflow
