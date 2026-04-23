# Round 2

Result: Round 2 support is a scenario-analysis workflow for Market Access Fee decisions and extra-access assumptions. It is intentionally local and decision-focused, not a claim about exact hidden website mechanics.

## Inputs

Round 2 uses the same public CSV shape as Round 1:

```text
prices_round_2_day_<day>.csv
trades_round_2_day_<day>.csv
```

Default location:

```text
data/round2/
```

Products:

- `ASH_COATED_OSMIUM`
- `INTARIAN_PEPPER_ROOT`

## Access Scenario Model

`prosperity_backtester.round2.AccessScenario` captures the local assumption.

Important fields:

- `enabled`
- `contract_won`
- `mode`
- `maf_bid`
- `extra_quote_fraction`
- `access_quality`
- `access_probability`
- `book_volume_share`
- `passive_fill_rate_multiplier`
- `passive_fill_rate_bonus`
- `missed_fill_reduction`
- `trade_volume_share`

These fields control how much extra access is assumed and how useful that access is locally.

## Core Commands

Inspect Round 2 data:

```bash
python -m prosperity_backtester inspect --round 2 --data-dir data/round2 --days 0 --json
```

Replay with no extra access:

```bash
python -m prosperity_backtester replay strategies/trader.py --round 2 --data-dir data/round2 --days 0 --fill-mode base
```

Replay with deterministic extra access:

```bash
python -m prosperity_backtester replay strategies/trader.py --round 2 --data-dir data/round2 --days 0 --fill-mode base --with-extra-access --access-mode deterministic --maf-bid 750 --access-quality 0.75 --access-passive-multiplier 1.12 --access-missed-reduction 0.02
```

Compare scripts under one access assumption:

```bash
python -m prosperity_backtester compare strategies/trader.py examples/trader_round1_v9.py --names current candidate --round 2 --data-dir data/round2 --days 0 --with-extra-access --access-mode stochastic --access-quality 0.8 --access-probability 0.65 --maf-bid 1000
```

Run the checked-in Round 2 scenario grid:

```bash
python -m prosperity_backtester round2-scenarios configs/round2_scenarios.json
```

Run the broader all-in-one config:

```bash
python -m prosperity_backtester round2-scenarios configs/round2_all_in_one_research.json --output-dir backtests/round2_all_in_one_research_bundle
```

## Output Files

Round 2 scenario bundles write:

- `round2_scenarios.csv`
- `round2_winners.csv`
- `round2_pairwise_mc.csv`
- `round2_maf_sensitivity.csv`
- `dashboard.json`
- `manifest.json`

## How To Read The Results

Focus on:

- `final_pnl`: net result after MAF when the contract is won
- `gross_pnl_before_maf`: result before the fee
- `marginal_access_pnl_before_maf`: value added by access versus the no-access baseline
- `break_even_maf_vs_no_access`: local fee ceiling suggested by the model
- `ranking_changed_vs_no_access`: whether the access assumption changed the winner

If Monte Carlo is enabled, use the pairwise rows to see whether the replay ranking survives stochastic variation.

## Limits

Grounded from the public statement:

- the access contract may grant an extra 25% of quotes
- only the top 50% of bids win the contract
- losing bids do not pay and do not receive access

Still unknown:

- exact extra-quote selection
- true queue priority
- same-price matching priority
- other teams' bids
- hidden realised website matching behaviour

Use Round 2 outputs for robust relative decisions, not false precision.
