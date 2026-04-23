# Workflows

Result: the normal path is small. Inspect the data, run replay, compare against a baseline, run a quick Monte Carlo check, then serve the latest bundle.

Replay and comparison default to day `0` and the light output profile so the common review loop stays fast.

## Standard Review Loop

Inspect the tracked datasets:

```bash
python -m prosperity_backtester inspect --data-dir data/round1 --days -2 -1 0 --json
python -m prosperity_backtester inspect --round 2 --data-dir data/round2 --days -1 0 1 --json
```

Replay one trader:

```bash
python -m prosperity_backtester replay strategies/trader.py --name current --data data/round1 --fill-mode empirical_baseline
```

Compare against the baseline strategy:

```bash
python -m prosperity_backtester compare strategies/trader.py strategies/starter.py --names current starter --data data/round1 --fill-mode empirical_baseline --merge-pnl
```

Run a quick robustness pass:

```bash
python -m prosperity_backtester monte-carlo strategies/trader.py --name current --days 0 --fill-mode empirical_baseline --noise-profile fitted --quick
```

Serve the latest bundle:

```bash
python -m prosperity_backtester serve --latest
```

## Trust Checks

Useful replay-side checks when a result looks too good:

```bash
python -m prosperity_backtester replay strategies/trader.py --name current --data data/round1 --fill-mode empirical_baseline --match-trades worse
python -m prosperity_backtester replay strategies/trader.py --name current --data data/round1 --fill-mode empirical_baseline --match-trades none
python -m prosperity_backtester replay strategies/trader.py --name current --data data/round1 --fill-mode empirical_baseline --limit INTARIAN_PEPPER_ROOT:40 --print
```

## Research Packs

The optional `analysis/research_pack.py` wrapper exposes three presets.

Fast:

```bash
python analysis/research_pack.py fast --trader strategies/trader.py --baseline strategies/starter.py
```

Validation:

```bash
python analysis/research_pack.py validation --trader strategies/trader.py --baseline strategies/starter.py
```

Forensic:

```bash
python analysis/research_pack.py forensic --trader strategies/trader.py --baseline strategies/starter.py
```

Use:

- `fast` for routine branch work
- `validation` for stronger checks across a broader scope
- `forensic` only when you explicitly want full-output evidence

## Replay Profiling

When replay speed looks wrong, profile the phases directly:

```bash
python analysis/profile_replay.py strategies/trader.py --compare-trader strategies/starter.py --data-dir data/round1 --fill-mode empirical_baseline
```

## Calibration

Use calibration when live-export evidence exists:

```bash
python -m prosperity_backtester calibrate examples/trader_round1_v9.py --name live_v9 --data-dir data/round1 --days 0 --live-export live_exports/259168/259168.json --quick
```

See [docs/CALIBRATED_RESEARCH.md](CALIBRATED_RESEARCH.md) for the full flow.

## Scenario Comparison

Use the checked-in calibrated scenario grid when one replay assumption is not enough:

```bash
python -m prosperity_backtester scenario-compare configs/research_scenarios.json
```

Review:

- `scenario_results.csv`
- `scenario_winners.csv`
- `robustness_ranking.csv`
- `scenario_pairwise_mc.csv`

## Parameter Search

Replay-only sweep:

```bash
python -m prosperity_backtester sweep configs/pepper_sweep.json
```

Replay plus Monte Carlo optimisation:

```bash
python -m prosperity_backtester optimize configs/pepper_optimize_quick.json
```

## Round 2

Use Round 2 scenarios for MAF and extra-access decisions:

```bash
python -m prosperity_backtester round2-scenarios configs/round2_scenarios.json
```

See [docs/ROUND2.md](ROUND2.md) for the Round 2-specific details.

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
python -m prosperity_backtester serve --latest-type monte-carlo
```

If the React build is absent, `serve` falls back to `legacy_dashboard/dashboard.html`.

## Retention And Cleanup

Auto-generated runs under `backtests/` keep the newest `30` timestamped directories by default.

Adjust retention per command:

```bash
python -m prosperity_backtester replay strategies/trader.py --keep-runs 10
```

Prune explicitly:

```bash
python -m prosperity_backtester clean --keep 30
```
