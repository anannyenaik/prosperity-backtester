# Round 2 Research Workflow

## Result

The platform now supports Round 2 as an explicit research mode with configurable Market Access Fee scenarios, access/no-access comparisons, MAF sensitivity, Monte Carlo robustness, dashboard metadata and saved decision artefacts.

It does not claim to reconstruct the hidden website mechanics. The extra 25% quote access is modelled as a configurable local assumption so scripts can be compared across plausible worlds.

## Gap Analysis

Already strong before this upgrade:

- deterministic replay over historical CSVs
- visible-book aggressive fills
- configurable passive fill presets and perturbations
- Monte Carlo sessions with sample paths
- strategy comparison, sweeps and optimisation
- live-export calibration diagnostics where export fields exist
- product-level behaviour diagnostics for OSMIUM and PEPPER
- dashboard bundle loading, inspect mode and product dives

Missing or weak for Round 2:

- CSV loading was tied to `prices_round_1_day_*.csv`
- Round 2 was not represented in manifests or dashboard metadata
- no MAF fee accounting
- no explicit access/no-access scenario object
- no scenario sweep for access quality, contract win/loss or MAF values
- no scenario-by-scenario winner table
- no access marginal value or break-even MAF output
- Monte Carlo comparison did not align around Round 2 access assumptions
- docs did not separate known facts from configurable assumptions and unknown website-only behaviour

## Design

Round 2 support has three layers.

### Deterministic Replay

Use `--round 2` or a config with `"round": 2`.

The loader expects Round 2 CSVs named:

```text
prices_round_2_day_<day>.csv
trades_round_2_day_<day>.csv
```

The schema is the same as the current Round 1 CSV schema. Products remain:

- `ASH_COATED_OSMIUM`
- `INTARIAN_PEPPER_ROOT`

### Scenario Layer

The access model is defined by `r1bt.round2.AccessScenario`.

Important fields:

- `enabled`: extra quote access assumption is active
- `contract_won`: MAF auction is assumed won
- `maf_bid`: fee deducted from net PnL only when `contract_won` is true
- `mode`: `none`, `deterministic` or `stochastic`
- `extra_quote_fraction`: default `0.25`
- `access_quality`: how useful the extra 25% is locally
- `access_probability`: tick-level probability for stochastic access
- `book_volume_share`: how much access affects observed book volume
- `passive_fill_rate_multiplier`
- `passive_fill_rate_bonus`
- `missed_fill_reduction`
- `trade_volume_share`

Every replay stores:

- gross PnL before MAF
- MAF cost
- net final PnL
- access scenario metadata

### Monte Carlo Layer

Round 2 scenario configs can run Monte Carlo under each access assumption. Pairwise comparisons use aligned seeds within each scenario so the difference distribution is more useful than comparing unrelated random paths.

Outputs include:

- MC mean, standard deviation, P05, P50, P95
- expected shortfall
- positive rate
- pairwise mean difference
- pairwise win rate
- likely winner by scenario

## Commands

Replay a Round 2 trader with no access:

```bash
python -m r1bt replay strategies/trader.py --round 2 --data-dir data/round2 --days 0 --fill-mode base
```

Replay with deterministic extra access and a 750 MAF:

```bash
python -m r1bt replay strategies/trader.py --round 2 --data-dir data/round2 --days 0 --fill-mode base --with-extra-access --access-mode deterministic --maf-bid 750 --access-quality 0.75 --access-passive-multiplier 1.12 --access-missed-reduction 0.02
```

Compare two traders under one access assumption:

```bash
python -m r1bt compare strategies/trader.py examples/trader_round1_v9.py --names current candidate --round 2 --data-dir data/round2 --days 0 --with-extra-access --access-mode stochastic --access-quality 0.8 --access-probability 0.65 --maf-bid 1000
```

Run the full Round 2 scenario grid:

```bash
python -m r1bt round2-scenarios configs/round2_scenarios.json
```

Serve the dashboard:

```bash
python -m r1bt serve --port 5555
```

Then load the generated `dashboard.json` and open the `Round 2` tab.

## Scenario Config

`configs/round2_scenarios.json` is the starting point.

It supports:

- multiple strategy variants
- multiple access scenarios
- `maf_values` expansion
- optional Monte Carlo per scenario
- fixed seeds and worker count

The main CSV outputs are:

- `round2_scenarios.csv`
- `round2_winners.csv`
- `round2_pairwise_mc.csv`
- `round2_maf_sensitivity.csv`

The dashboard payload contains the same data under `round2`.

## Calibration

Existing live-export calibration still works. Round 2 access metadata can be passed to calibration commands, but exact live alignment remains limited by whatever the website export exposes.

Useful mismatch checks remain:

- product-level PnL error
- fill count error
- final position mismatch
- path RMSE
- dominant error source

## Honest Limitations

Known from the challenge statement:

- paying an MAF may grant access to an extra 25% of quotes
- only the top 50% of total MAF bids get the contract
- losing bidders do not pay and do not get access

Configurable local assumptions:

- whether the contract is won
- how useful the extra quote access is
- whether access is deterministic or stochastic
- how access affects visible volume, passive fills and fill opportunities
- MAF values to test

Unknown without website feedback:

- exact quote selection behind the extra 25%
- exact queue priority and matching behaviour
- whether extra quotes mainly change book volume, passive fill odds or trade opportunity volume
- other teams' MAF bids
- official realised PnL path under the hidden matching engine

Use this tool for robust relative decisions, not false precision.
