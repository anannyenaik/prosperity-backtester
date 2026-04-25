# Prosperity Backtester

Prosperity Backtester: Now round-aware and ready for Round 3 historical replay, Round 3 option diagnostics, and coherent Round 3 Monte Carlo, while preserving the existing Round 1 and Round 2 workflows.

No Round 3 alpha strategy is checked in. The tracked `examples/noop_round3_trader.py` file is a smoke fixture only.

## Quick start

Runtime code uses the Python standard library only. Tests use `pytest`; the dev extra also installs `psutil` so `verify-round3` can capture process-tree RSS.

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

Install the React dashboard dependencies only if you want the optional UI:

```bash
npm ci --prefix dashboard
npm test --prefix dashboard
npm run build --prefix dashboard
```

## Round 3 path

Run the verification harness first; it gates trader-script work and writes a structured pass/fail report:

```bash
python -m prosperity_backtester verify-round3 --data-dir data/round3 --output-dir backtests/r3_verification_latest
```

Quick mode skips only the heavy 64-session worker sweep, while still running data validation, replay fixtures, option diagnostics, MC coherence, dashboard payload proof, and small MC subprocesses:

```bash
python -m prosperity_backtester verify-round3 --data-dir data/round3 --output-dir backtests/r3_verification_fast --skip-heavy-mc
```

`verify-round3` validates data counts, runs replay-correctness fixtures, asserts option-diagnostic safety, runs MC coherence and seed-determinism checks, and launches `inspect`, `replay`, `compare`, `monte-carlo`, and `scenario-compare` subprocesses. It captures wall time, output size, and (when `psutil` is installed) peak parent and process-tree RSS for every command. Without `psutil`, the harness still runs and reports RSS as unavailable.

Inspect the tracked Round 3 public data:

```bash
python -m prosperity_backtester inspect --round 3 --data-dir data/round3 --days 0 1 2 --json
```

Run a deterministic Round 3 replay smoke:

```bash
python -m prosperity_backtester replay examples/noop_round3_trader.py --round 3 --data-dir data/round3 --days 0 1 2 --fill-mode base
```

Run a coherent Round 3 Monte Carlo smoke:

```bash
python -m prosperity_backtester monte-carlo examples/noop_round3_trader.py --round 3 --data-dir data/round3 --days 0 --sessions 8 --sample-sessions 2 --synthetic-tick-limit 250
```

Run the checked-in Round 3 scenario bundle:

```bash
python -m prosperity_backtester scenario-compare configs/round3_research_scenarios.json
```

Run the generic Round 3 passive-fill sensitivity grid:

```bash
python -m prosperity_backtester scenario-compare configs/round3_fill_sensitivity.json
```

Open the latest bundle:

```bash
python -m prosperity_backtester serve --latest
```

## Historical Round 2 path

The submitted and optimised Round 2 strategy pair is still tracked:

- `strategies/r2_algo_v2.py`
- `strategies/r2_algo_v2_optimised.py`

Typical Round 2 commands remain:

```bash
python -m prosperity_backtester inspect --round 2 --data-dir data/round2 --days -1 0 1 --json
python -m prosperity_backtester compare strategies/r2_algo_v2_optimised.py strategies/r2_algo_v2.py --names optimised submitted --round 2 --data-dir data/round2 --days -1 0 1 --fill-mode base --merge-pnl
python -m prosperity_backtester round2-scenarios configs/round2_all_in_one_research.json
```

## Repository map

- `prosperity_backtester/`: replay, Monte Carlo, round registry, reporting, storage, and server code
- `data/`: tracked Round 1, Round 2, and Round 3 public fixtures
- `configs/`: checked-in smoke and scenario configs
- `examples/`: smoke helpers and legacy examples
- `docs/`: workflow, assumptions, architecture, and output notes
- `tests/`: regression coverage for runtime, outputs, and bundle contracts

## Notes

- Round 3 historical replay trades the observed books and marks positions to observed mids.
- Round 3 vouchers are not cash-settled or exercised inside historical replay.
- Round 3 option theory is used for diagnostics and coherent synthetic generation, not as a replay price source.
- Round 3 Monte Carlo currently uses the classic Python backend.
- Passive fills remain approximate across all rounds.
- Round 2 access and MAF logic remain available, but are intentionally isolated from Round 3.

## Documentation

- [docs/ROUND3.md](docs/ROUND3.md): Round 3 products, data, TTE mapping, diagnostics, and caveats
- [docs/ROUND3_HARDENING_REPORT.md](docs/ROUND3_HARDENING_REPORT.md): verification and performance proof for this hardening pass
- [docs/WORKFLOWS.md](docs/WORKFLOWS.md): practical replay and Monte Carlo workflows
- [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md): exact behaviour versus local modelling assumptions
- [docs/OUTPUTS.md](docs/OUTPUTS.md): bundle structure and metadata
- [docs/REPOSITORY_GUIDE.md](docs/REPOSITORY_GUIDE.md): file and module map
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): runtime layers and round-aware design
- [docs/ROUND2.md](docs/ROUND2.md): historical Round 2 access and MAF workflow
