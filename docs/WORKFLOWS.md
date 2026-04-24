# Workflows

Result: the default path is now Round 3 data inspection, Round 3 replay smoke, Round 3 option diagnostics, and coherent Round 3 Monte Carlo. Round 2 remains available as a historical workflow.

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

Run the checked-in Round 3 scenario bundle:

```bash
python -m prosperity_backtester scenario-compare configs/round3_research_scenarios.json
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

Scenario bundle with Round 3 perturbations:

```bash
python -m prosperity_backtester scenario-compare configs/round3_research_scenarios.json
```

## Historical Round 2 workflow

Round 2 submitted-versus-optimised review remains:

```bash
python -m prosperity_backtester inspect --round 2 --data-dir data/round2 --days -1 0 1 --json
python -m prosperity_backtester compare strategies/r2_algo_v2_optimised.py strategies/r2_algo_v2.py --names optimised submitted --round 2 --data-dir data/round2 --days -1 0 1 --fill-mode base --merge-pnl
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
