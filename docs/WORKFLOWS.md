# Workflows

Result: the default Round 4 path is manifest, research, replay smoke, MC validation, then verify-round4. Round 3 and Round 2 remain available as historical workflows.

## Round 4 verification path

Run the complete data manifest first:

```bash
python -m prosperity_backtester r4-manifest --data-dir data/round4 --output-dir backtests/r4_manifest_latest
```

Run counterparty research as infrastructure, not strategy tuning:

```bash
python -m prosperity_backtester r4-counterparty-research --data-dir data/round4 --output-dir backtests/r4_counterparty_research_latest
```

Replay no-op and the rejected fixture only as simulator diagnostics:

```bash
python -m prosperity_backtester replay examples/noop_round3_trader.py --round 4 --data-dir data/round4 --days 1 2 3 --fill-mode base --output-dir backtests/r4_noop_replay_latest
python -m prosperity_backtester replay strategies/r4_algo_v1_candidate.py --round 4 --data-dir data/round4 --days 1 2 3 --fill-mode base --output-dir backtests/r4_candidate_replay_latest
```

Validate MC. A `pass` status means the rejection/stress hard gates passed; it is still not proof of official simulator equivalence:

```bash
python -m prosperity_backtester r4-mc-validation --data-dir data/round4 --output-dir backtests/r4_mc_validation_fast --fast
python -m prosperity_backtester r4-mc-validation --data-dir data/round4 --output-dir backtests/r4_mc_validation_full --full
```

Run verification modes:

```bash
python -m prosperity_backtester verify-round4 --data-dir data/round4 --output-dir backtests/r4_verification_fast --fast
python -m prosperity_backtester verify-round4 --data-dir data/round4 --output-dir backtests/r4_verification_skip_mc --skip-mc
python -m prosperity_backtester verify-round4 --data-dir data/round4 --output-dir backtests/r4_verification_full --full
python -m prosperity_backtester verify-round4 --data-dir data/round4 --output-dir backtests/r4_verification_strict --strict
```

`--fast` truncates replay and ablation to a day-1 tick window and records it in `replay_scope`. `--full` removes replay truncation. `--skip-mc` records MC as skipped and still writes reports. `--strict` exits non-zero while any blocker remains. No Round 4 command promotes `strategies/r4_algo_v1_candidate.py`.

Slow pytest integration tests are skipped by default and marked explicitly:

```bash
python -m pytest -q
python -m pytest -q -m "not slow"
python -m pytest -q --runslow
```

## Round 3 verification (run this first)

Trader-script work should only start after the harness reports `pass`:

```bash
python -m prosperity_backtester verify-round3 --data-dir data/round3 --output-dir backtests/r3_verification_latest
```

The harness covers:

- provenance (Python, OS, git HEAD, dirty flag, run timestamp, data file `sha256` hashes)
- exact data validation against the known Round 3 counts (price rows, timestamps, products, trade rows per day)
- replay-correctness fixtures (multi-level crossing, fractional MTM, atomic per-product limit enforcement, all-12-product execution, two-no-op exact-zero-diff compare)
- option-diagnostics proof (no `NaN`/`Infinity`, primary fit set is `VEV_5000`..`VEV_5500`, every excluded strike is flagged)
- Monte Carlo coherence proof (seed determinism, shock direction, vol shift, hydrogel-shock isolation, residual-noise isolation, no negative or crossed synthetic books)
- subprocess sweep over `inspect`, `replay`, `compare`, `monte-carlo`, `scenario-compare round3_research_scenarios`, and `scenario-compare round3_fill_sensitivity`
- per-command wall time, output size, file count, peak parent-process RSS, peak process-tree RSS, and child-process count (when `psutil` is installed)

It writes `verification_report.json`, `verification_report.md`, and `manifest.json`. Use `--skip-heavy-mc` to drop the 64-session x workers 1/2/4 sweep when iterating quickly. The CLI exits non-zero on any failure.

Quick mode command:

```bash
python -m prosperity_backtester verify-round3 --data-dir data/round3 --output-dir backtests/r3_verification_fast --skip-heavy-mc
```

Quick mode still runs data validation, replay fixtures, option diagnostics, MC coherence, dashboard payload proof, seed determinism, and small MC subprocesses. Install the dev extra (`python -m pip install -e ".[dev]"`) to include `psutil`; without it, RSS fields are reported as unavailable rather than estimated.

## Round 3 smoke path

Inspect the tracked data first:

```bash
python -m prosperity_backtester inspect --round 3 --data-dir data/round3 --days 0 1 2 --json
```

Run a no-op replay smoke:

```bash
python -m prosperity_backtester replay examples/noop_round3_trader.py --round 3 --data-dir data/round3 --days 0 1 2 --fill-mode base
```

Run a coherent Monte Carlo smoke:

```bash
python -m prosperity_backtester monte-carlo examples/noop_round3_trader.py --round 3 --data-dir data/round3 --days 0 --sessions 8 --sample-sessions 2 --synthetic-tick-limit 250
```

Run the small coherence proof bundle:

```bash
python -m prosperity_backtester monte-carlo examples/noop_round3_trader.py --round 3 --data-dir data/round3 --days 0 --sessions 32 --sample-sessions 4 --synthetic-tick-limit 250 --output-dir backtests/r3_mc_coherence_proof
```

Run the checked-in Round 3 scenario bundle:

```bash
python -m prosperity_backtester scenario-compare configs/round3_research_scenarios.json
```

Run passive-fill sensitivity:

```bash
python -m prosperity_backtester scenario-compare configs/round3_fill_sensitivity.json
```

## Round 3 research loop

Use this order when you start testing real Round 3 traders later:

1. Inspect the raw data and validation counts.
2. Replay a no-op or trivial trader to confirm zero unexpected fills.
3. Replay the candidate trader on historical data only.
4. Review the Round 3 option diagnostics before fitting any surface or pricing model.
5. Run coherent Monte Carlo with underlying and volatility perturbations.
6. Re-run under conservative passive-fill settings before trusting small edges.

The checked-in Round 3 configs use `examples/noop_round3_trader.py` so they remain runnable without pretending a real strategy is bundled.

## Useful Round 3 commands

Historical replay with the full three-day public set:

```bash
python -m prosperity_backtester replay your_trader.py --round 3 --data-dir data/round3 --days 0 1 2 --fill-mode base
```

Coherent Monte Carlo with a short synthetic path:

```bash
python -m prosperity_backtester monte-carlo your_trader.py --round 3 --data-dir data/round3 --days 0 --sessions 32 --sample-sessions 4 --synthetic-tick-limit 250 --vol-shift 0.02 --vol-scale 1.1
```

Round 3 Monte Carlo currently resolves to the classic Python backend. Do not read Rust or streaming backend timings as active Round 3 support.

Scenario bundle with Round 3 perturbations:

```bash
python -m prosperity_backtester scenario-compare configs/round3_research_scenarios.json
```

## Historical Round 2 workflow

Round 2 submitted-versus-optimised review remains:

```bash
python -m prosperity_backtester inspect --round 2 --data-dir data/round2 --days -1 0 1 --json
python -m prosperity_backtester compare strategies/archive/round2/r2_algo_v2_optimised.py strategies/archive/round2/r2_algo_v2.py --names optimised submitted --round 2 --data-dir data/round2 --days -1 0 1 --fill-mode base --merge-pnl
python -m prosperity_backtester round2-scenarios configs/round2_all_in_one_research.json
```

## Dashboard review

Build the React dashboard only when you want the richer UI:

```bash
npm ci --prefix dashboard
npm test --prefix dashboard
npm run build --prefix dashboard
```

Then serve bundles:

```bash
python -m prosperity_backtester serve --latest
python -m prosperity_backtester serve --latest-type replay
python -m prosperity_backtester serve --latest-type scenario-compare
```
