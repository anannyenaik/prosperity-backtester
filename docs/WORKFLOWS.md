# Workflows

Result: the normal review path is now submitted versus optimised on Round 2, followed by access scenarios, conservative stress, and pairwise Monte Carlo confirmation.

## Standard Review Loop

Inspect the tracked Round 2 data:

```bash
python -m prosperity_backtester inspect --round 2 --data-dir data/round2 --days -1 0 1 --json
```

Run the direct compare:

```bash
python -m prosperity_backtester compare strategies/r2_algo_v2_optimised.py strategies/r2_algo_v2.py --names optimised submitted --round 2 --data-dir data/round2 --days -1 0 1 --fill-mode base --merge-pnl
```

Run the broad access and MAF suite:

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

Serve the latest bundle:

```bash
python -m prosperity_backtester serve --latest
```

## Fast Checks

Replay only the optimised candidate:

```bash
python -m prosperity_backtester replay strategies/r2_algo_v2_optimised.py --round 2 --data-dir data/round2 --days -1 0 1 --fill-mode base
```

Run the smaller checked-in decision grid:

```bash
python -m prosperity_backtester round2-scenarios configs/round2_scenarios.json
```

## Trust Checks

Useful replay-side checks when a result looks too good:

```bash
python -m prosperity_backtester replay strategies/r2_algo_v2_optimised.py --round 2 --data-dir data/round2 --days -1 0 1 --fill-mode base --match-trades worse
python -m prosperity_backtester replay strategies/r2_algo_v2_optimised.py --round 2 --data-dir data/round2 --days -1 0 1 --fill-mode base --match-trades none
python -m prosperity_backtester replay strategies/r2_algo_v2_optimised.py --round 2 --data-dir data/round2 --days 0 --limit INTARIAN_PEPPER_ROOT:40 --print
```

Useful access-side checks:

```bash
python -m prosperity_backtester compare strategies/r2_algo_v2_optimised.py strategies/r2_algo_v2.py --names optimised submitted --round 2 --data-dir data/round2 --days -1 0 1 --with-extra-access --access-mode deterministic --maf-bid 1000 --access-quality 0.75 --access-passive-multiplier 1.12 --access-missed-reduction 0.02 --merge-pnl
python -m prosperity_backtester compare strategies/r2_algo_v2_optimised.py strategies/r2_algo_v2.py --names optimised submitted --round 2 --data-dir data/round2 --days -1 0 1 --with-extra-access --access-mode stochastic --maf-bid 1000 --access-quality 0.8 --access-probability 0.65 --access-passive-multiplier 1.15 --access-missed-reduction 0.02 --merge-pnl
```

## Research Helpers

The optional `analysis/research_pack.py` wrapper now defaults to the Round 2 submitted-versus-optimised pair.

Fast:

```bash
python analysis/research_pack.py fast
```

Validation:

```bash
python analysis/research_pack.py validation
```

Forensic:

```bash
python analysis/research_pack.py forensic
```

Use:

- `fast` for a quick smoke check
- `validation` for the normal multi-day confirmation pass
- `forensic` only when you want full-output evidence

## Replay Profiling

When replay speed looks wrong, profile the phases directly:

```bash
python analysis/profile_replay.py strategies/r2_algo_v2_optimised.py --compare-trader strategies/r2_algo_v2.py --round 2 --data-dir data/round2 --days -1 0 1 --fill-mode base
```

## Optional Calibration

Live-export calibration remains available as a historical side workflow:

```bash
python -m prosperity_backtester calibrate examples/trader_round1_v9.py --name live_v9 --data-dir data/round1 --days 0 --live-export live_exports/259168/259168.json --quick
```

See [docs/CALIBRATED_RESEARCH.md](CALIBRATED_RESEARCH.md) for details.

## Dashboard Review

Build the React dashboard locally when you want the full review UI:

```bash
npm ci --prefix dashboard
npm test --prefix dashboard
npm run build --prefix dashboard
```

Then serve bundles:

```bash
python -m prosperity_backtester serve --port 5555
python -m prosperity_backtester serve --dir backtests --port 5555
python -m prosperity_backtester serve --latest
python -m prosperity_backtester serve --latest-type replay
python -m prosperity_backtester serve --latest-type round2-scenarios
```

If the React build is absent, `serve` falls back to `legacy_dashboard/dashboard.html`.

## Retention And Cleanup

Auto-generated runs under `backtests/` keep the newest `30` timestamped directories by default.

Adjust retention per command:

```bash
python -m prosperity_backtester replay strategies/r2_algo_v2_optimised.py --round 2 --data-dir data/round2 --keep-runs 10
```

Prune explicitly:

```bash
python -m prosperity_backtester clean --keep 30
```
