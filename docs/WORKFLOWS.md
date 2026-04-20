# Workflows

This page lists the practical research paths used most often during strategy work.

## Replay

Use replay to inspect one trader on historical CSVs.

```bash
python -m prosperity_backtester replay strategies/trader.py --name current --data-dir data/round1 --days -2 -1 0 --fill-mode empirical_baseline
```

Review:

- final and per-product PnL
- realised, unrealised and MTM paths
- fill count and order count
- inventory pressure and limit breaches
- markout and behaviour summaries

## Compare

Use compare for a clean head-to-head under one fixed assumption.

```bash
python -m prosperity_backtester compare strategies/trader.py strategies/starter.py --names current starter --data-dir data/round1 --days 0 --fill-mode empirical_baseline
```

The output ranks traders by replay PnL and writes `comparison.csv`.

## Monte Carlo

Use Monte Carlo to check whether a replay winner is stable across synthetic sessions.

```bash
python -m prosperity_backtester monte-carlo strategies/trader.py --name current --fill-mode empirical_baseline --noise-profile fitted --sessions 128 --sample-sessions 8
```

Review mean, median, P05, expected shortfall, drawdown and limit breaches. The dashboard path bands are computed from all sessions; saved sample runs are examples for qualitative inspection.

## Sweep

Use sweep for small parameter grids where each variant is replayed once.

```bash
python -m prosperity_backtester sweep configs/pepper_sweep.json
```

Use this for quick sensitivity checks before running a heavier optimisation.

## Optimisation

Use optimisation when each variant needs replay and Monte Carlo evidence.

```bash
python -m prosperity_backtester optimize configs/pepper_optimize_quick.json
```

The score combines replay PnL, Monte Carlo mean, downside, expected shortfall, volatility, drawdown and limit-breach penalties.

## Calibration

Use calibration when live-export evidence is available.

```bash
python -m prosperity_backtester calibrate examples/trader_round1_v9.py --name live_v9 --data-dir data/round1 --days 0 --live-export live_exports/259168/259168.json --quick
```

Calibration is useful for choosing conservative assumptions, not for proving exact website replication.

## Scenario Compare

Use scenario compare when rankings need to survive stress.

```bash
python -m prosperity_backtester scenario-compare configs/research_scenarios.json
```

Review `robustness_ranking.csv` and `scenario_winners.csv` before trusting small replay gains.

## Round 2 Scenarios

Use Round 2 scenarios for Market Access Fee and extra-access decisions.

```bash
python -m prosperity_backtester round2-scenarios configs/round2_scenarios.json
```

The default config is replay-only so it finishes in a normal local verification pass.

For a shared bundle containing the main Round 2 strategy comparison:

```bash
python -m prosperity_backtester round2-scenarios configs/round2_all_in_one_research.json --output-dir backtests/round2_all_in_one_research_bundle
```

Review `round2_winners.csv`, `round2_maf_sensitivity.csv` and the dashboard Round 2 tab.

## Dashboard Review

```bash
npm run build --prefix dashboard
python -m prosperity_backtester serve --port 5555
```

Open `http://127.0.0.1:5555/`, load one or more bundles and use the available tabs for that bundle type.

## Storage-Efficient Runs

The default output profile is light. It keeps exact summaries, exact fills, compact quote intent, event-aware compact paths and all-session Monte Carlo path bands while avoiding submitted order dumps, duplicated chart-series sidecars, duplicated Monte Carlo sample files and child bundles under aggregate workflows.

Use full output only for a debugging session:

```bash
python -m prosperity_backtester replay strategies/trader.py --days 0 --output-profile full
python -m prosperity_backtester monte-carlo strategies/trader.py --sessions 128 --sample-sessions 8 --output-profile full
```

Full mode no longer writes child bundles implicitly. Add `--save-child-bundles` to aggregate commands only when you need per-variant or per-scenario bundles:

```bash
python -m prosperity_backtester compare strategies/trader.py strategies/starter.py --output-profile full --save-child-bundles
```

Use `--series-sidecars` when a script needs chart-series CSVs but raw orders and debug sample files are not needed.

Default timestamped runs under `backtests/` keep the newest 30 runs. Use `--keep-runs` or `python -m prosperity_backtester clean --keep 30` to manage retention. Invalid keep counts fail instead of being treated as a no-op.
