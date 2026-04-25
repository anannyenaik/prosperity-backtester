# Round 2

Result: the Round 2 workflow is now built around one fixed submitted baseline and one optimised candidate.

Submission-facing scripts:

- `strategies/archive/round2/r2_algo_v2.py`: frozen submitted baseline
- `strategies/archive/round2/r2_algo_v2_optimised.py`: improved candidate

Round 2 outputs remain local decision evidence. They are not a claim about exact hidden website mechanics.

## Inputs

Round 2 uses the public CSV files:

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

`prosperity_backtester.round2.AccessScenario` captures the local access assumption.

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

These values control how much extra access is assumed and how useful that access is locally.

## Main Commands

Inspect Round 2 data:

```bash
python -m prosperity_backtester inspect --round 2 --data-dir data/round2 --days -1 0 1 --json
```

Replay the submitted baseline:

```bash
python -m prosperity_backtester replay strategies/archive/round2/r2_algo_v2.py --round 2 --data-dir data/round2 --days -1 0 1 --fill-mode base
```

Replay the optimised candidate:

```bash
python -m prosperity_backtester replay strategies/archive/round2/r2_algo_v2_optimised.py --round 2 --data-dir data/round2 --days -1 0 1 --fill-mode base
```

Compare the two directly:

```bash
python -m prosperity_backtester compare strategies/archive/round2/r2_algo_v2_optimised.py strategies/archive/round2/r2_algo_v2.py --names optimised submitted --round 2 --data-dir data/round2 --days -1 0 1 --fill-mode base --merge-pnl
```

## Checked-In Review Packs

Quick decision grid:

```bash
python -m prosperity_backtester round2-scenarios configs/round2_scenarios.json
```

Broad access and MAF replay suite:

```bash
python -m prosperity_backtester round2-scenarios configs/round2_all_in_one_research.json
```

Conservative no-access stress suite:

```bash
python -m prosperity_backtester scenario-compare configs/research_scenarios.json
```

Representative access pairwise Monte Carlo confirmation:

```bash
python -m prosperity_backtester round2-scenarios configs/round2_pairwise_mc.json
```

## Output Files

Round 2 scenario bundles write:

- `round2_scenarios.csv`
- `round2_winners.csv`
- `round2_pairwise_mc.csv`
- `round2_maf_sensitivity.csv`
- `dashboard.json`
- `manifest.json`

Scenario-compare stress bundles write:

- `scenario_results.csv`
- `scenario_winners.csv`
- `robustness_ranking.csv`
- `scenario_pairwise_mc.csv`
- `dashboard.json`
- `manifest.json`

## How To Read The Results

Focus on:

- `final_pnl`: net result after MAF where relevant
- `gross_pnl_before_maf`: result before the fee deduction
- `marginal_access_pnl_before_maf`: local value added by access versus the no-access baseline
- `break_even_maf_vs_no_access`: local fee ceiling implied by the model
- `gap_to_second`: how much room the winner had in a given scenario
- `mc_mean_diff_a_minus_b`: pairwise Monte Carlo mean edge where MC is enabled
- `mc_p05_diff`: downside version of the same pairwise edge

Use the replay grid for breadth and the pairwise Monte Carlo rows for stability. One without the other is not enough.

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
