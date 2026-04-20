# Calibrated research workflow

## Result

The platform is now aimed at robust local decisions, not fake-perfect website reconstruction.

It strengthens:

- empirical fill profiling from live exports
- product-specific passive fill assumptions
- size-dependent slippage and adverse selection
- fitted latent Monte Carlo noise
- baseline, stress, crash, spread/depth, slippage and fill-quality scenarios
- live-vs-sim mismatch diagnostics
- reproducible scenario comparison bundles

## Gap analysis

What was already strong:

- deterministic replay over Prosperity CSVs
- visible-book aggressive fills
- cash, inventory, realised, unrealised and MTM accounting
- Monte Carlo sampling and saved path bundles
- trader comparison, sweeps and optimisation
- live export loading
- product behaviour summaries and dashboard output
- Round 2 MAF/access scenarios

Recent changes that are genuinely useful:

- Round 2 is modelled as scenario analysis rather than claimed truth
- comparison and optimisation bundles are reproducible
- behaviour summaries expose fill counts, cap usage and markouts
- live-vs-sim calibration already scores PnL, fills, position and path error
- dashboard payloads preserve exact vs approximate assumptions

Weaknesses fixed in this pass:

- live `tradeHistory` was previously counted as own fills even when rows did not involve `SUBMISSION`
- passive fill modelling was mostly global presets rather than product-specific calibrated assumptions
- slippage was a flat tick adjustment and did not worsen with order size
- Monte Carlo noise did not expose the fitted R1/R2 values as a reusable profile
- there was no general calibrated scenario workflow outside Round 2
- live-vs-sim diagnostics did not split passive/aggressive, activity timing or inventory-path mismatch clearly enough

Remaining weak points:

- rejected passive orders are not visible in live exports
- true queue priority is unknown
- hidden website matching and other teams' behaviour are unknown
- one live export is not enough to prove stable calibration

## The 90% accuracy claim

Treat any "90% accurate" claim as unproven until it is validated on held-out live exports.

A believable validation standard would require:

- calibration on one set of live sessions
- held-out testing on different sessions
- total PnL error, per-product PnL error and inventory-path error inside agreed bands
- ranking stability across original vs updated strategies
- scenario sensitivity showing that the winner is not only winning under friendly fills

The current platform can support that validation, but it should not claim exact website accuracy.

## Design

Empirical fills:

- `derive-fill-profile` filters live fills to rows where `SUBMISSION` is buyer or seller
- passive/aggressive labels are inferred from the visible touch at fill time
- product, side, quantity, spread, touch distance and liquidity regime are saved
- output includes `empirical_fill_profile.json`, `empirical_fill_rows.csv` and `empirical_fill_summary.csv`
- derived profiles are inspectable JSON and can be reused with `--fill-config`

Fill assumptions:

- built-in models now include `empirical_baseline`, `empirical_optimistic`, `empirical_conservative`, `slippage_stress` and `low_fill_quality`
- OSMIUM and PEPPER have separate product configs
- wide-spread and thin-depth regimes can override fill quality
- baseline/conservative/optimistic remain explicit assumptions, not claims of truth

Slippage:

- aggressive fills include flat slippage, aggressive adverse selection and size-dependent slippage
- passive fills separately record adverse-selection ticks
- each fill logs reference price, slippage ticks, size slippage ticks and fill regime
- run summaries include total and per-product slippage cost
- `--slippage-multiplier 0` gives a clean no-slippage comparison

Noise:

- fitted latent noise values are exposed through `r1bt/noise.py`
- current fitted values are `3.70` for OSMIUM and `3.22` for PEPPER
- profiles are `none`, `fitted`, `baseline`, `stress` and `crash`
- profiles can be scaled rather than treated as permanent truth

Stress scenarios:

- `scenario-compare` runs a general baseline/stress/crash grid
- default stresses cover crash shock, wider spread, thinner depth, harsher slippage and lower fill quality
- outputs include scenario winners, pairwise Monte Carlo rows and robustness ranking

Live-vs-sim diagnostics:

- total profit error
- PnL path RMSE
- per-product PnL error
- final position L1 error
- inventory-path error
- fill count and fill quantity error
- passive/aggressive fill mismatch
- active tick overlap and timing mismatch
- ranking usefulness label

## Commands

Derive an empirical fill profile:

```bash
python -m r1bt derive-fill-profile live_exports/259168/259168.log --profile-name live_empirical
```

Replay with empirical fills and fitted noise:

```bash
python -m r1bt replay strategies/trader.py --data-dir data/round1 --days 0 --fill-mode empirical_baseline --noise-profile fitted
```

Compare two scripts:

```bash
python -m r1bt compare strategies/trader.py examples/trader_round1_v9.py --names current candidate --data-dir data/round1 --days 0 --fill-mode empirical_baseline
```

Compare with and without slippage:

```bash
python -m r1bt replay strategies/trader.py --data-dir data/round1 --days 0 --fill-mode empirical_baseline --slippage-multiplier 0
python -m r1bt replay strategies/trader.py --data-dir data/round1 --days 0 --fill-mode slippage_stress --slippage-multiplier 1.5
```

Run the calibrated scenario grid:

```bash
python -m r1bt scenario-compare configs/research_scenarios.json
```

Run a longer Monte Carlo check:

```bash
python -m r1bt monte-carlo strategies/trader.py --fill-mode empirical_baseline --noise-profile fitted --sessions 512 --sample-sessions 32 --workers 4
```

Calibrate against a live export:

```bash
python -m r1bt calibrate examples/trader_round1_v9.py --name live_v9 --data-dir data/round1 --days 0 --live-export live_exports/259168/259168.log
```

## Output files

Scenario bundles include:

- `dashboard.json`
- `manifest.json`
- `scenario_results.csv`
- `scenario_winners.csv`
- `robustness_ranking.csv`
- `scenario_pairwise_mc.csv`

Fill profile bundles include:

- `empirical_fill_profile.json`
- `empirical_fill_rows.csv`
- `empirical_fill_summary.csv`

Calibration bundles include:

- `calibration_grid.csv`
- `empirical_profile/empirical_fill_profile.json`
- manifest metadata with the best candidate and validation note

## Validation plan

1. Use one or more live exports to derive empirical fill profiles.
2. Run `calibrate` on a calibration session and save the best settings.
3. Replay held-out live sessions with the chosen fill model.
4. Check total PnL error, per-product PnL error, fill-count error, fill-quantity error and inventory-path RMSE.
5. Compare original and updated strategy scripts under the same calibrated assumptions.
6. Run `scenario-compare` with baseline, stress, crash, wide-spread, harsh-slippage and lower-fill-quality scenarios.
7. Trust a strategy gain more when it survives conservative fills and stress scenarios.
8. Treat gains smaller than the observed live-vs-sim error band as suspect until confirmed by held-out logs.

## Honest limitations

Local backtests still cannot know:

- true website queue position
- hidden order matching
- rejected passive orders
- other teams' MAF bids or adaptation
- hidden quote selection in Round 2
- website-only latency or throttling effects

The right use is robust strategy ranking and fragility diagnosis, not exact official PnL prediction.
