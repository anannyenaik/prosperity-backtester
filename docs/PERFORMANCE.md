# Performance

How the Monte Carlo and replay hot paths are organised, what we measured, and
what remains. The aim is honest benchmark-backed claims, not theoretical wins.

## Backend choice

There are three Monte Carlo backends in `prosperity_backtester/mc_backends.py`:

| Backend | When to use | Trade-off |
| --- | --- | --- |
| `streaming` (default) | All practical worker counts up to ~6 cores | Pure-Python tick loop, no IPC, lowest overhead per session. Recommended. |
| `classic` | Parity checks vs the replay engine | Materialises the full per-session market dataset, then runs `run_market_session`. Slower than streaming, identical results. |
| `rust` | Explicit `--workers ≥ 6` ceiling runs | Compiled Rust + Rayon engine. Eliminates Python overhead in the parallel section, but pays per-tick line-delimited JSON IPC to the Python trader worker. Wins only when there is enough parallel work to amortise IPC. **Never auto-selected.** |

The `auto` sentinel always resolves to `streaming`. To use Rust, pass
`--mc-backend rust` deliberately. Configurations that the Rust path cannot
honour (access scenarios, `--print-trader-output`) raise on use rather than
silently falling back, so timing comparisons remain honest.

## Hot-path optimisation pass (2026-04-22)

The streaming backend dominates on 1–4 workers, so it received a focused
optimisation pass. All wins are pure-Python and apply to **both** streaming
and classic Monte Carlo, plus the shared replay engine that calls into
`_execute_order_batch` and `_scaled_snapshot` via `run_market_session`.

1. **`_scaled_snapshot` identity fast-path** (`prosperity_backtester/platform.py`).
   When `spread_shift_ticks==0`, `order_book_volume_scale==1.0`,
   `book_noise_std==0.0` and `access_volume_multiplier==1.0`, return the
   original snapshot unchanged. This is the dominant path for default configs
   and was the largest single win (~80 % market-generation reduction on the
   benchmark fixture).
2. **`_execute_order_batch` early returns**. Skip the entire body when
   `not orders`. After the aggressive pass, also early-return when there are
   no passive candidates — this avoids the per-tick `TradePrint` copy and the
   passive-snapshot allocation that previously ran on every aggressive-only
   tick.
3. **`make_book` no-`Bot 3` fast-path** (`prosperity_backtester/simulate.py`).
   The empirical book is built as `(inner, outer)` pairs in the correct sort
   order. When no Bot 3 quote is inserted (the common case), skip the
   `dict`-aggregation dedupe and the `sorted()` step.
4. **`bisect`-backed sampler** (`_Sampler.draw`). The hand-rolled binary
   search was replaced with `bisect.bisect_left`, which is a C builtin.
5. **Tick-aware path generation**. `simulate_latent_fair` and
   `sample_trade_counts` now accept an optional `tick_count` so synthetic
   benchmark fixtures (`--synthetic-tick-limit 250`) no longer allocate full
   10 000-element latent paths and trade-count lists per session per product.
6. **`TradePrint` direct construction** instead of `dataclasses.asdict + **`,
   used on the rare passive ticks that need to mutate trade quantities.

### RNG ordering note

Optimisation #5 changes the rng-consumption count for runs with
`--synthetic-tick-limit < 10000`. **Full-day runs (no tick limit) consume
identical rng draws as before**, so historical Monte Carlo summaries on
production-sized fixtures are unchanged.

For shortened benchmark fixtures (CI, `analysis/benchmark_*`) the absolute
PnL number shifts slightly. Cross-backend parity (streaming ↔ classic) is
preserved because both paths now thread `tick_count` through the same
helpers.

## Headline numbers (benchmark fixture, post-optimisation)

`analysis/benchmark_runtime.py` on the tracked 250-tick Monte Carlo fixture
with `examples/benchmark_trader.py`:

| Case | Pre-opt 1w | Post-opt 1w | Δ | Post-opt 4w | Sessions/s 4w |
| --- | ---: | ---: | ---: | ---: | ---: |
| MC quick light (64 sess) | — | `1.50s` | — | `1.29s` | 49.4 |
| MC default light (100 sess) | `3.32s` | `2.05s` | `-38 %` | `1.66s` | 60.1 |
| MC heavy light (192 sess) | `7.20s` | `3.67s` | `-49 %` | `2.72s` | 70.6 |
| MC ceiling light (256 sess) | — | — | — | `3.32s` | 77.1 |
| Replay day-0 light | `2.41s` | `2.28s` | `-5 %` | n/a | n/a |
| Day-0 compare light | `2.57s` | `2.24s` | `-13 %` | n/a | n/a |
| Fast pack | `5.93s` | `4.65s` | `-22 %` | n/a | n/a |
| Validation pack | `20.36s` | `15.59s` | `-23 %` | n/a | n/a |

The pre-optimisation column comes from the previous public README (commit
`48259ec`); the post-optimisation column is the current
`backtests/runtime_benchmark_post/benchmark_report.md`.

Replay benefits less than Monte Carlo because the `_scaled_snapshot` identity
fast-path saves more on synthetic data (which calls `_scaled_snapshot` per
product per tick) than on historical replay (which already had cheaper
upstream snapshot construction).

## When to reach for the Rust backend

Use `--mc-backend rust` when:

- you are running with `--workers ≥ 6` and the per-tick IPC cost is amortised,
- you do not need access scenarios or `--print-trader-output`,
- you have `cargo` available (the binary is built once at first use, ~30–90 s).

At lower worker counts the per-tick line-delimited JSON IPC overhead
(`~17 µs/tick × 30 K ticks ≈ +0.5 s/session`) exceeds the Rust speed
advantage. The streaming backend wins outright, which is why it is the
default and why `auto` resolves to it.

## Why we did not embed Python in Rust

`PyO3` / `pybind11` style embedding would eliminate the per-tick JSON IPC,
but the trader callback would still hold the GIL inside the Rust process and
multi-worker scaling would have to fall back to sub-interpreters or
multiprocessing — neither cleanly. The marginal win does not justify the
install/portability cost (a `cargo` toolchain becomes mandatory, and the
runtime stops being stdlib-only). The pure-Python streaming backend with the
optimisations above is faster than the existing Rust subprocess design at
1–4 workers and is competitive at higher worker counts; the Rust backend is
preserved as the explicit ceiling tool for high-core machines.

## How to reproduce

```bash
python analysis/benchmark_runtime.py --output-dir backtests/runtime_benchmark_post --workers 1 2 4
```

The harness records git commit, Python version, platform, per-phase timings
and full provenance in each case manifest. Use `--compare-report` against an
earlier `benchmark_report.json` to get a delta column for regression tracking.
