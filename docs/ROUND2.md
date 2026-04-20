# Round 2 Workflow

Round 2 support is an explicit scenario workflow for Market Access Fee decisions and extra-quote assumptions. It is intended for comparing scripts across plausible local assumptions, not for claiming exact website reconstruction.

## Inputs

Round 2 CSV files use the same schema as the Round 1 public files:

```text
prices_round_2_day_<day>.csv
trades_round_2_day_<day>.csv
```

Default location:

```text
data/round2/
```

Supported products:

- `ASH_COATED_OSMIUM`
- `INTARIAN_PEPPER_ROOT`

## Access Scenario Fields

`prosperity_backtester.round2.AccessScenario` defines the local MAF/access assumption.

Important fields:

- `enabled`: whether extra quote access is active.
- `contract_won`: whether the MAF auction is assumed won.
- `mode`: `none`, `deterministic` or `stochastic`.
- `maf_bid`: fee deducted from net PnL only when `contract_won` is true.
- `extra_quote_fraction`: default `0.25`.
- `access_quality`: how useful the extra 25% quote access is locally.
- `access_probability`: tick-level activation probability for stochastic access.
- `book_volume_share`: how access affects visible book volume.
- `passive_fill_rate_multiplier`: multiplicative passive fill uplift.
- `passive_fill_rate_bonus`: additive passive fill uplift.
- `missed_fill_reduction`: reduction in missed passive fills.
- `trade_volume_share`: fill-opportunity volume uplift.

Every replay stores gross PnL before MAF, MAF cost, net final PnL and access metadata.

## Commands

Inspect Round 2 data:

```bash
python -m prosperity_backtester inspect --round 2 --data-dir data/round2 --days 0 --json
```

Replay with no extra access:

```bash
python -m prosperity_backtester replay strategies/trader.py --round 2 --data-dir data/round2 --days 0 --fill-mode base
```

Replay with deterministic extra access and a 750 MAF:

```bash
python -m prosperity_backtester replay strategies/trader.py --round 2 --data-dir data/round2 --days 0 --fill-mode base --with-extra-access --access-mode deterministic --maf-bid 750 --access-quality 0.75 --access-passive-multiplier 1.12 --access-missed-reduction 0.02
```

Compare two scripts under one access assumption:

```bash
python -m prosperity_backtester compare strategies/trader.py examples/trader_round1_v9.py --names current candidate --round 2 --data-dir data/round2 --days 0 --with-extra-access --access-mode stochastic --access-quality 0.8 --access-probability 0.65 --maf-bid 1000
```

Run the standard Round 2 grid. This is the quick checked-in decision config: one day, replay-only, three MAF points and two trader variants.

```bash
python -m prosperity_backtester round2-scenarios configs/round2_scenarios.json
```

Run the all-in-one comparison config:

```bash
python -m prosperity_backtester round2-scenarios configs/round2_all_in_one_research.json --output-dir backtests/round2_all_in_one_research_bundle
```

Serve the dashboard:

```bash
python -m prosperity_backtester serve --port 5555
```

Then load the generated `dashboard.json` and open the Round 2 tab.

## Scenario Bundle Outputs

- `round2_scenarios.csv`: one row per trader and scenario.
- `round2_winners.csv`: replay and Monte Carlo winners by scenario.
- `round2_pairwise_mc.csv`: pairwise Monte Carlo differences where MC is enabled.
- `round2_maf_sensitivity.csv`: rows useful for fee sensitivity and break-even MAF review.
- `dashboard.json`: dashboard-ready payload with the same scenario evidence.
- `manifest.json`: lightweight metadata for dashboard discovery.

## Reading Round 2 Results

- `final_pnl` is net of MAF when the contract is won.
- `gross_pnl_before_maf` is the result before MAF deduction.
- `marginal_access_pnl_before_maf` compares access scenario gross PnL against the no-access baseline for the same trader.
- `break_even_maf_vs_no_access` estimates how much fee the access benefit can absorb locally.
- `ranking_changed_vs_no_access` flags whether access assumptions changed the replay winner.
- Pairwise MC rows are aligned by seed inside a scenario so the difference distribution is more meaningful.

## Recommended Decision Flow

1. Replay each serious script with no access and inspect product PnL, inventory and drawdown.
2. Run `round2-scenarios` with no-access, low-quality access, base access and stochastic access.
3. Review `round2_winners.csv` for winner stability.
4. Review `round2_maf_sensitivity.csv` for access value before the fee.
5. Run targeted Monte Carlo on leading scripts if replay gaps are small.
6. Prefer scripts that remain strong under low-quality access and conservative fees.

## Limits

Known:

- MAF may grant access to an extra 25% of quotes.
- Only the top 50% of total MAF bids get the contract.
- Losing bidders do not pay and do not get access.

Unknown:

- exact extra-quote selection
- exact queue priority
- same-price priority
- other teams' bids
- official realised PnL under the hidden matching engine

Use Round 2 mode for robust relative decisions, not false precision.
