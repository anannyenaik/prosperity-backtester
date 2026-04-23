# Prosperity Backtester

Result: this repository is now centred on the Round 2 submitted baseline and the final optimised candidate.

The submission-facing strategy pair is:

- `strategies/r2_algo_v2.py`: frozen submitted baseline
- `strategies/r2_algo_v2_optimised.py`: improved local candidate

`strategies/trader.py` and `strategies/starter.py` remain only as older Round 1 fixtures. They are not the main review path.

## Quick Start

Runtime code uses the Python standard library only. Tests use `pytest`.

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

Install the extra analysis dependencies only if you want the optional research helpers:

```bash
python -m pip install -e ".[dev,analysis]"
```

The React dashboard is optional:

```bash
npm ci --prefix dashboard
npm test --prefix dashboard
npm run build --prefix dashboard
```

`python -m prosperity_backtester serve` uses the React build when `dashboard/dist/` exists. Otherwise it falls back to `legacy_dashboard/dashboard.html`.

## Reviewer Path

Inspect the tracked Round 2 data:

```bash
python -m prosperity_backtester inspect --round 2 --data-dir data/round2 --days -1 0 1 --json
```

Run the direct submitted-versus-optimised compare:

```bash
python -m prosperity_backtester compare strategies/r2_algo_v2_optimised.py strategies/r2_algo_v2.py --names optimised submitted --round 2 --data-dir data/round2 --days -1 0 1 --fill-mode base --merge-pnl
```

Run the checked-in access and MAF suite:

```bash
python -m prosperity_backtester round2-scenarios configs/round2_all_in_one_research.json
```

Run the checked-in conservative stress suite:

```bash
python -m prosperity_backtester scenario-compare configs/research_scenarios.json
```

Run the checked-in pairwise Monte Carlo confirmation:

```bash
python -m prosperity_backtester round2-scenarios configs/round2_pairwise_mc.json
```

Open the latest bundle:

```bash
python -m prosperity_backtester serve --latest
```

## Submission Surface

The repo is intentionally small at the top level:

- `strategies/`: submitted and optimised Round 2 scripts, plus legacy Round 1 fixtures
- `data/`: tracked Round 1 and Round 2 public CSV fixtures
- `prosperity_backtester/`: replay, Monte Carlo, reporting, storage, and server code
- `configs/`: checked-in comparison packs for access, stress, and Monte Carlo review
- `docs/`: reviewer-facing workflow and architecture notes
- `tests/`: regression tests for runtime, outputs, and helper scripts

Optional tooling:

- `analysis/`: helper wrappers and benchmark scripts
- `dashboard/`: React review UI
- `live_exports/`: tracked live-export fixture for optional historical calibration

Compatibility or experimental areas:

- `legacy_dashboard/`
- `r1bt/`
- `rust_mc_engine/`

## Core Commands

Replay the submitted baseline:

```bash
python -m prosperity_backtester replay strategies/r2_algo_v2.py --round 2 --data-dir data/round2 --days -1 0 1 --fill-mode base
```

Replay the optimised candidate:

```bash
python -m prosperity_backtester replay strategies/r2_algo_v2_optimised.py --round 2 --data-dir data/round2 --days -1 0 1 --fill-mode base
```

Run the quick decision grid:

```bash
python -m prosperity_backtester round2-scenarios configs/round2_scenarios.json
```

Run the broad replay suite:

```bash
python -m prosperity_backtester round2-scenarios configs/round2_all_in_one_research.json
```

Run the no-access stress suite:

```bash
python -m prosperity_backtester scenario-compare configs/research_scenarios.json
```

Run the pairwise Monte Carlo access check:

```bash
python -m prosperity_backtester round2-scenarios configs/round2_pairwise_mc.json
```

Prune old auto-generated output directories:

```bash
python -m prosperity_backtester clean --keep 30
```

## Notes

- The strongest local Round 2 evidence lives in `compare`, `round2-scenarios`, and `scenario-compare`.
- `analysis/research_pack.py` and `analysis/profile_replay.py` now default to the Round 2 submitted-versus-optimised pair.
- The live-export calibration flow remains available, but it is an optional historical side path rather than the main Round 2 decision workflow.

## Documentation

- [docs/WORKFLOWS.md](docs/WORKFLOWS.md): main review loops and checked-in configs
- [docs/ROUND2.md](docs/ROUND2.md): Round 2 access and MAF workflow
- [docs/OUTPUTS.md](docs/OUTPUTS.md): bundle structure and output profiles
- [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md): exact behaviour versus local modelling assumptions
- [docs/REPOSITORY_GUIDE.md](docs/REPOSITORY_GUIDE.md): file and module map
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): runtime layers and bundle contract
- [docs/CALIBRATED_RESEARCH.md](docs/CALIBRATED_RESEARCH.md): optional live-export calibration workflow
