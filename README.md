# Prosperity Backtester

Prosperity Backtester: round-aware historical replay, diagnostics, Monte Carlo, and research workflows for Rounds 1 to 4.

Round 4 is backtester-first. `strategies/r4_algo_v1_candidate.py` is retained only as a rejected diagnostic fixture until the corrected replay, research, MC, and verification gates produce fresh evidence. Round 3 trader files are archived for benchmark reproduction only.

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

## Round 4 path

Inspect the imported Round 4 capsule:

```bash
python -m prosperity_backtester inspect --round 4 --data-dir data/round4 --days 1 2 3 --json
```

Build the stricter Round 4 manifest:

```bash
python -m prosperity_backtester r4-manifest --data-dir data/round4 --output-dir backtests/r4_manifest_latest
```

Run counterparty research:

```bash
python -m prosperity_backtester r4-counterparty-research --data-dir data/round4 --output-dir backtests/r4_counterparty_research_latest
```

Replay the rejected Round 4 fixture as a diagnostic only:

```bash
python -m prosperity_backtester replay strategies/r4_algo_v1_candidate.py --round 4 --data-dir data/round4 --days 1 2 3 --fill-mode base
```

Validate the Round 4 MC generator:

```bash
python -m prosperity_backtester r4-mc-validation --data-dir data/round4 --output-dir backtests/r4_mc_validation_fast --fast
```

Run the Round 4 verification smoke:

```bash
python -m prosperity_backtester verify-round4 --data-dir data/round4 --output-dir backtests/r4_verification_fast --fast
```

Fast and skip-MC verification validate the full manifest and research outputs, then replay a bounded day-1 window for runtime. The JSON report records the exact `replay_scope`. Use `--full` for full-day replay and broader ablations.

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

Run the archived Round 3 research trader:

```bash
python -m prosperity_backtester replay strategies/archive/round3/r3_algo_v1_2_candidate.py --round 3 --data-dir data/round3 --days 0 1 2 --fill-mode base
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

The submitted and optimised Round 2 strategy pair is archived and still runnable:

- `strategies/archive/round2/r2_algo_v2.py`
- `strategies/archive/round2/r2_algo_v2_optimised.py`

Typical Round 2 commands remain:

```bash
python -m prosperity_backtester inspect --round 2 --data-dir data/round2 --days -1 0 1 --json
python -m prosperity_backtester compare strategies/archive/round2/r2_algo_v2_optimised.py strategies/archive/round2/r2_algo_v2.py --names optimised submitted --round 2 --data-dir data/round2 --days -1 0 1 --fill-mode base --merge-pnl
python -m prosperity_backtester round2-scenarios configs/round2_all_in_one_research.json
```

## Repository map

- `prosperity_backtester/`: replay, Monte Carlo, round registry, reporting, storage, and server code
- `data/`: tracked Round 1, Round 2, Round 3, and Round 4 public fixtures
- `configs/`: checked-in smoke and scenario configs
- `examples/`: smoke helpers and legacy examples
- `docs/`: workflow, assumptions, architecture, and output notes
- `tests/`: regression coverage for runtime, outputs, and bundle contracts

## Notes

- Round 3 historical replay trades the observed books and marks positions to observed mids.
- Round 3 vouchers are not cash-settled or exercised inside historical replay.
- Round 3 option theory is used for diagnostics and coherent synthetic generation, not as a replay price source.
- Round 3 and Round 4 option-chain Monte Carlo currently use the classic Python path.
- Passive fills remain approximate across all rounds.
- Round 2 access and MAF logic remain available, but are intentionally isolated from Round 3.

## Documentation

- [docs/ROUND3.md](docs/ROUND3.md): Round 3 products, data, TTE mapping, diagnostics, and caveats
- [docs/ROUND4.md](docs/ROUND4.md): Round 4 products, counterparty fields, data validation, and research workflow
- [docs/ROUND3_HARDENING_REPORT.md](docs/ROUND3_HARDENING_REPORT.md): verification and performance proof for this hardening pass
- [docs/WORKFLOWS.md](docs/WORKFLOWS.md): practical replay and Monte Carlo workflows
- [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md): exact behaviour versus local modelling assumptions
- [docs/OUTPUTS.md](docs/OUTPUTS.md): bundle structure and metadata
- [docs/REPOSITORY_GUIDE.md](docs/REPOSITORY_GUIDE.md): file and module map
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): runtime layers and round-aware design
- [docs/ROUND2.md](docs/ROUND2.md): historical Round 2 access and MAF workflow
