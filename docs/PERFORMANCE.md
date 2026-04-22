# Performance

This page answers four questions:

- which Monte Carlo backend is honestly recommended now
- what the latest verified gains actually were
- where the current bottlenecks still sit
- whether a deeper architecture move is justified already

All claims below come from local benchmark runs on 2026-04-22. See
[`docs/BENCHMARKS.md`](BENCHMARKS.md) and
[`docs/BENCHMARK_SUMMARY.json`](BENCHMARK_SUMMARY.json) for the tracked proof
surface.

## Current backend choice

There are three Monte Carlo backends in
`prosperity_backtester/mc_backends.py`:

| Backend | Use it when | Current verdict |
| --- | --- | --- |
| `streaming` | normal research work and the default branch loop | Recommended default. Still the best overall balance of runtime, fidelity and workflow simplicity. |
| `classic` | parity checks and cases where you want full replay-style materialisation | Real parity option. It now wins some realistic `8`-worker default cells, so it is not honest to describe it as only a slower fallback. |
| `rust` | explicit backend experiments when you want to test the native path | Kept available, but not recommended. It stayed slower than `streaming` and `classic` on every realistic case rerun in this pass. |

`auto` still resolves to `streaming`.

## Current runtime

Tracked Monte Carlo timings from the audited runtime suite:

| Case | 1 worker | 2 workers | 4 workers | 8 workers | Peak RSS at widest case |
| --- | ---: | ---: | ---: | ---: | ---: |
| quick light `64/8` | `1.429s` | `1.260s` | `1.138s` | `1.193s` | `352.6 MB` |
| default light `100/10` | `1.863s` | `1.548s` | `1.265s` | `1.345s` | `361.0 MB` |
| heavy light `192/16` | `3.028s` | `n/a` | `n/a` | `1.635s` | `378.1 MB` |
| ceiling light `768/24` | `n/a` | `n/a` | `n/a` | `3.182s` | `417.6 MB` |

Practical loop timings from the same report:

- replay day 0 light: `2.176s`
- compare day 0 light: `2.201s`
- fast pack: `4.718s`
- validation pack: `15.510s`

## Same-code realistic backend proof

The no-op benchmark is not enough. The backend benchmark was rerun against
realistic repo traders:

| Case | Streaming | Classic | Rust | Winner |
| --- | ---: | ---: | ---: | --- |
| `live_v9_default_w1` | `3.235s` | `3.344s` | `4.093s` | `streaming` |
| `live_v9_default_w8` | `1.490s` | `1.493s` | `1.950s` | `streaming` by `3 ms` |
| `live_v9_heavy_w8` | `2.021s` | `2.332s` | `2.992s` | `streaming` |
| `main_default_w8` | `1.454s` | `1.348s` | `1.692s` | `classic` |
| `main_heavy_w8` | `1.711s` | `1.887s` | `2.293s` | `streaming` |
| `r2_stateful_default_w8` | `1.494s` | `1.440s` | `1.794s` | `classic` |
| `r2_stateful_heavy_w8` | `1.754s` | `1.788s` | `2.388s` | `streaming` |

That is the key correction to the earlier story. `streaming` is still the best
default, but it is no longer honest to say it wins every meaningful realistic
multi-worker cell.

## What the latest pass actually improved

Two different improvements landed in this overall pass.

The earlier high-value gain was the reporting and retention work in
`prosperity_backtester/reports.py` plus the lower-copy trade path in
`prosperity_backtester/platform.py`. That remains the major Monte Carlo memory
and retained-output win.

The later smaller gain in this pass was a hot-path fix in
`prosperity_backtester/fill_models.py`: `config_for()` no longer constructs a
fresh base config on every lookup when a product override already exists.

Against the older `backtests/_phase4_runtime_baseline/benchmark_report.json`
report that the harness compared against, the latest local numbers are:

- replay day 0 light: `2.313s -> 2.176s` (`-5.9%`)
- compare day 0 light: `2.223s -> 2.201s` (`-1.0%`)
- fast pack: `5.117s -> 4.718s` (`-7.8%`)
- validation pack: `17.786s -> 15.510s` (`-12.8%`)
- default MC light, `1` worker: `2.079s -> 1.863s` (`-10.4%`)

The widest benchmark-trader Monte Carlo rows are mixed on this machine:

- quick MC light, `8` workers: `1.155s -> 1.193s` (`+3.3%`)
- default MC light, `8` workers: `1.219s -> 1.345s` (`+10.3%`)
- heavy MC light, `8` workers: `1.526s -> 1.635s` (`+7.1%`)
- ceiling MC light, `8` workers: `3.107s -> 3.182s` (`+2.4%`)

So the honest conclusion is:

- the earlier retention pass delivered the major light-mode Monte Carlo win
- the later fill-model fix improved real hot-path waste
- the combined pass does not justify a blanket claim that every runtime cell is now faster

## Current bottleneck picture

Fresh profiling on the current default Monte Carlo case still shows the hot
path inside the Python engine rather than the dashboard frontend:

- `mc_backends.py:run_streaming_synthetic_session`
- `platform.py:_execute_order_batch`
- `reports.py:accumulate_path_band_rows`
- `fill_models.py:config_for`

The remaining shared tail is mostly:

- worker startup or scheduling overhead, about `0.38s` to `0.45s`
- bundle writing, about `0.16s` to `0.31s`
- sampled-row compaction, about `0.04s` to `0.14s`
- retained-output size and ceiling RSS, especially versus Chris Roberts on the shared no-op comparison

Dashboard build itself is no longer the main problem. It is only `7 ms` to
`20 ms` in the tracked Monte Carlo rows.

## External reference result

The same-machine Chris Roberts rerun proves a strong runtime-throughput lead:

- default `100/10`: this repo is `4.34x` to `18.69x` faster
- ceiling `1000/100`: this repo is `11.36x` to `17.50x` faster

But the all-axis story is still mixed:

- this repo uses fewer files, `5` rather than `50` or `410`
- this repo uses less RSS on the smaller default cases
- Chris keeps lower RSS on every ceiling case
- Chris keeps the smaller retained output footprint throughout

That is enough for a runtime-throughput lead. It is not enough for an
undisputed memory or retained-output crown.

## Architecture direction

The architecture bake-off does show real upside in lower-copy transport and
binary serialisation:

- MessagePack reduced the real dashboard payload from `10.16 MB` to `8.39 MB`
- MessagePack encoded faster, `0.028s` versus JSON `0.127s`
- shared-memory transport beat pickled transport, `0.336s` versus `0.462s`

Those are meaningful signals, but not a kill shot against the current design.
The best current architecture is still the streaming-first Python engine with:

- `streaming` as the default backend
- `classic` kept for parity checks
- `rust` kept as an explicit experiment, not a default
- JSON kept as the canonical dashboard bundle contract

The next frontier is still lower retained bytes, lower ceiling RSS and less
shared worker overhead, not a broad native rewrite.
