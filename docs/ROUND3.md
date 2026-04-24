# Round 3

Result: the backtester now treats Round 3 as a first-class round with explicit product metadata, validated public data, historical TTE mapping, option diagnostics, and coherent synthetic generation.

## Algorithmic products

Delta-1 products:

- `HYDROGEL_PACK`, position limit `200`
- `VELVETFRUIT_EXTRACT`, position limit `200`

Voucher products, each with position limit `300`:

- `VEV_4000`
- `VEV_4500`
- `VEV_5000`
- `VEV_5100`
- `VEV_5200`
- `VEV_5300`
- `VEV_5400`
- `VEV_5500`
- `VEV_6000`
- `VEV_6500`

Each `VEV_*` symbol is a call-style voucher on `VELVETFRUIT_EXTRACT`. The strike is the numeric suffix.

Currency: `XIRECS`

## Timestamp and day conventions

- timestamp step: `100`
- ticks per day: `10,000`
- timestamps run from `0` to `999900`
- public historical days: `0`, `1`, `2`

## Historical TTE mapping

- day `0` -> `8` days to expiry
- day `1` -> `7` days to expiry
- day `2` -> `6` days to expiry
- final simulation starts at `5` days to expiry

## Tracked public data

Tracked under `data/round3/`:

- `prices_round_3_day_0.csv`
- `prices_round_3_day_1.csv`
- `prices_round_3_day_2.csv`
- `trades_round_3_day_0.csv`
- `trades_round_3_day_1.csv`
- `trades_round_3_day_2.csv`
- `manifest.json`

The tracked data manifest records source capsule names, hashes, imported files, per-file hashes, row counts, timestamps, and product sets.

## Validation counts

Price files:

- each day has `120,000` price rows
- each day has `10,000` timestamps
- each timestamp has all `12` Round 3 products

Trade files:

- day `0`: `1,308` rows
- day `1`: `1,407` rows
- day `2`: `1,333` rows

The loader validates schema, timestamp range, timestamp step, duplicate timestamp-product rows, missing product rows, product set, trade symbols, currency, and quantity signs. Crossed books, one-sided books, and empty books are counted and reported.

## Replay interpretation

Historical Round 3 replay follows these rules:

- aggressive orders trade exactly against visible public book levels
- residual passive quantity is controlled by the configured passive fill model
- positions are marked to the observed market mid
- fractional mids are preserved
- voucher prices are not overridden by theory during historical replay
- voucher exercise and expiry settlement are not applied during replay

## Option diagnostics

`prosperity_backtester.round3` provides:

- voucher symbol and strike parsing
- intrinsic value, time value, moneyness, Black-Scholes price, delta, gamma, vega, and implied-vol inversion
- per-day voucher diagnostics with average mid, spread, depth, intrinsic, time value, IV, fitted IV, model fair, residual, delta, gamma, vega, and underlying-move beta statistics
- compact chain samples with timestamp-level observed mid, fitted fair, residual z-score, spread, depth, and inclusion reason
- surface-fit quality diagnostics, including direct versus fallback fit counts and included-strike residual quality

Default surface-fit policy:

- primary fit set: `VEV_5000` through `VEV_5500`
- deep ITM `VEV_4000` and `VEV_4500` are excluded by default
- pinned far OTM `VEV_6000` and `VEV_6500` are excluded by default

The surface is a robust per-timestamp linear IV fit over the primary strikes. If a timestamp cannot support a fit, the code reuses the previous fit, then falls back to the per-day median surface and records that source. It does not claim statistical confidence when the fit is thin.

## Coherent Monte Carlo

Round 3 synthetic generation is calibrated from the historical Round 3 data:

- `HYDROGEL_PACK` has an independent delta-1 path
- `VELVETFRUIT_EXTRACT` has its own underlying path
- vouchers are generated from the underlying path, TTE, fitted surface, and sampled residuals
- underlying shocks propagate through the voucher chain
- Hydrogel shocks do not mechanically move voucher fairs
- prices are clamped non-negative and generated books must remain crossed-book safe

Round 3 Monte Carlo currently uses the classic Python backend. The streaming and Rust Monte Carlo backends are not active for Round 3.

## Known caveats

- `HYDROGEL_PACK` appears effectively independent of `VELVETFRUIT_EXTRACT`
- `VEV_6000` and `VEV_6500` are often pinned around `0.5` mid and may print `0.0` in trades
- passive fills remain approximate
- passive print fills are labelled as same-price queue assumptions or worse-price through-print assumptions
- public trade data is sparse, so hidden queue behaviour is not claimed

## Manual challenge

The Ornamental Bio-Pods challenge is separate from the algorithmic replay engine.

Documented summary:

- reserve prices are uniform from `670` to `920` in steps of `5`
- resale value is `920`
- two bids are submitted
- bid 1 clears immediately if above reserve
- bid 2 clears only with the documented mean-second-bid penalty rule

This repo may add helper analysis for it, but it is intentionally not wired into the algorithmic exchange replay path.

## Recommended workflow

1. Inspect `data/round3` with `inspect --json`.
2. Replay a no-op or minimal trader first.
3. Replay candidate traders on historical books.
4. Review option diagnostics before fitting any surface.
5. Run coherent Monte Carlo with underlying, volatility, and liquidity perturbations.
6. Re-run under conservative passive-fill settings before trusting small edges.
