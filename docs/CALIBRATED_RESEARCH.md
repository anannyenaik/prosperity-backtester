# Calibrated Research

Result: calibration is for choosing useful local assumptions, not for proving exact website replication.

Use this workflow when live-export evidence exists and the ranking between strategies is sensitive to fill quality, slippage, or execution assumptions.

## When To Use It

Calibration is most useful when:

- a live export exists for a known trader version
- replay looks obviously too optimistic or too pessimistic
- two candidate strategies are close
- inventory timing or passive-fill quality is driving the decision

## Derive An Empirical Fill Profile

Build a fill profile from the tracked live export:

```bash
python -m prosperity_backtester derive-fill-profile live_exports/259168/259168.json --profile-name live_empirical
```

This writes:

- `empirical_fill_profile.json`
- `empirical_fill_rows.csv`
- `empirical_fill_summary.csv`

## Run Calibration

Quick pass:

```bash
python -m prosperity_backtester calibrate examples/trader_round1_v9.py --name live_v9 --data-dir data/round1 --days 0 --live-export live_exports/259168/259168.json --quick
```

Broader pass:

```bash
python -m prosperity_backtester calibrate examples/trader_round1_v9.py --name live_v9 --data-dir data/round1 --days 0 --live-export live_exports/259168/259168.json
```

The calibration score combines local replay-versus-live mismatches such as:

- profit error
- path error
- fill-count error
- position error
- per-product path error where available

Lower is better. It is still a local modelling choice.

## Replay Under Calibrated Assumptions

Once you have a sensible baseline, replay the active strategy under the same assumptions:

```bash
python -m prosperity_backtester replay strategies/trader.py --data-dir data/round1 --days 0 --fill-mode empirical_baseline --noise-profile fitted
```

Useful trust checks:

```bash
python -m prosperity_backtester replay strategies/trader.py --data-dir data/round1 --days 0 --fill-mode empirical_baseline --slippage-multiplier 0
python -m prosperity_backtester replay strategies/trader.py --data-dir data/round1 --days 0 --fill-mode slippage_stress --slippage-multiplier 1.5
```

## Scenario Comparison

Use the checked-in scenario grid when you want a calibrated ranking rather than one replay assumption:

```bash
python -m prosperity_backtester scenario-compare configs/research_scenarios.json
```

The default grid includes baseline, stressed, crash, spread/depth, and slippage variants.

Review:

- `scenario_results.csv`
- `scenario_winners.csv`
- `robustness_ranking.csv`
- `scenario_pairwise_mc.csv`

## Monte Carlo Follow-Up

For a leading strategy, run a longer robustness pass:

```bash
python -m prosperity_backtester monte-carlo strategies/trader.py --fill-mode empirical_baseline --noise-profile fitted --sessions 512 --sample-sessions 32 --workers 4
```

Read the result with this split in mind:

- mean and median: central tendency
- P05 and expected shortfall: downside
- drawdown: path risk
- limit breaches: execution safety

Sample runs in the dashboard are qualitative examples only. The reported path bands and summary statistics use the full session population.

## What Calibration Cannot Prove

Calibration cannot discover:

- hidden queue rules
- rejected passive orders
- website-only latency
- hidden matching details
- other teams' behaviour

Use it to reduce modelling error, not to claim exact parity.
