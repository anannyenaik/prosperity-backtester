# Calibrated Research Workflow

The calibrated workflow helps choose fill, slippage and stress assumptions that are useful for local strategy ranking. It does not prove exact website accuracy.

## When To Use It

Use calibrated research when:

- a live export exists for a known trader version
- replay looks too optimistic or too pessimistic
- two scripts have a small PnL gap
- fill quality or inventory timing is driving the result
- you need a conservative upload decision

## Empirical Fill Profile

Derive a profile from the tracked live-export fixture:

```bash
python -m prosperity_backtester derive-fill-profile live_exports/259168/259168.json --profile-name live_empirical
```

Outputs:

- `empirical_fill_profile.json`
- `empirical_fill_rows.csv`
- `empirical_fill_summary.csv`

The derivation filters live `tradeHistory` to rows where `SUBMISSION` is buyer or seller, then records product, side, quantity, spread, touch distance and inferred passive/aggressive role.

## Calibration Grid

Run a quick calibration pass:

```bash
python -m prosperity_backtester calibrate examples/trader_round1_v9.py --name live_v9 --data-dir data/round1 --days 0 --live-export live_exports/259168/259168.json --quick
```

Run the full grid by omitting `--quick`.

The calibration score combines:

- total profit error
- PnL path RMSE
- fill count error
- final position error
- per-product path error where available

Lower score is better. A best score is still a local modelling choice.

## Replay With Calibrated Assumptions

```bash
python -m prosperity_backtester replay strategies/trader.py --data-dir data/round1 --days 0 --fill-mode empirical_baseline --noise-profile fitted
```

Compare no-slippage and harsher-slippage assumptions:

```bash
python -m prosperity_backtester replay strategies/trader.py --data-dir data/round1 --days 0 --fill-mode empirical_baseline --slippage-multiplier 0
python -m prosperity_backtester replay strategies/trader.py --data-dir data/round1 --days 0 --fill-mode slippage_stress --slippage-multiplier 1.5
```

## Scenario Grid

Run the calibrated scenario grid:

```bash
python -m prosperity_backtester scenario-compare configs/research_scenarios.json
```

Default scenarios cover:

- empirical baseline
- conservative fills
- wider spreads
- thinner depth
- harsher slippage
- lower fill quality
- crash-style price shock

Outputs:

- `scenario_results.csv`
- `scenario_winners.csv`
- `robustness_ranking.csv`
- `scenario_pairwise_mc.csv`
- `dashboard.json`
- `manifest.json`

## Monte Carlo Robustness

Run a longer check for a leading script:

```bash
python -m prosperity_backtester monte-carlo strategies/trader.py --fill-mode empirical_baseline --noise-profile fitted --sessions 512 --sample-sessions 32 --workers 4
```

This still uses the light output profile unless `--output-profile full` is added. Light mode keeps exact final distribution stats, all-session path bands and sampled dashboard paths without writing duplicate sample files.

Use:

- mean for average robustness
- median for typical outcome
- P05 and expected shortfall for downside
- max drawdown for path risk
- limit breaches for execution safety

## Validation Standard

A useful calibration should be judged on held-out evidence where possible:

1. Derive fills from one live export.
2. Calibrate on a separate live session.
3. Replay a held-out session with the chosen assumptions.
4. Check total PnL error, per-product PnL error, fill count, fill quantity and inventory path.
5. Compare current and candidate scripts under the same assumptions.
6. Run scenario and Monte Carlo checks before trusting small edges.

## Limits

Local calibration cannot know:

- rejected passive orders
- true queue position
- hidden matching
- website-only latency or throttling
- other teams' behaviour
- Round 2 extra-quote selection

Use the workflow for ranking stability, fragility diagnosis and conservative decision-making.
