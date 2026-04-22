# Performance

This page answers four questions:

- which Monte Carlo backend is actually recommended now
- where the last real bottleneck was
- what the 2026-04-22 optimisation pass changed
- what still limits the next step up

All claims below come from local benchmark runs on 2026-04-22. See
[`docs/BENCHMARKS.md`](BENCHMARKS.md) for the exact commands, storage numbers,
comparability notes and the same-machine public-reference note.

## Current backend choice

There are three Monte Carlo backends in
`prosperity_backtester/mc_backends.py`:

| Backend | Use it when | Current verdict |
| --- | --- | --- |
| `streaming` | normal research work, including the tracked 1, 2, 4 and 8 worker cases | Recommended default. Fastest on the tracked fixture through the measured 8-worker cases. |
| `classic` | parity checks against the full replay engine | Honest fallback. Slower, but semantically closest to full replay materialisation. |
| `rust` | explicit backend experiments when you want to test the native path | Kept available, but not recommended on the tracked fixture. Never auto-selected. |

`auto` always resolves to `streaming`.

## Tracked evidence

Measured with:

```bash
python analysis/benchmark_runtime.py --output-dir backtests/runtime_benchmark --compare-report path/to/previous/benchmark_report.json --workers 1 2 4 8
python analysis/benchmark_outputs.py --output-dir backtests/output_benchmark
```

Machine metadata recorded by the harness:

- Windows 10
- Python 3.11
- 8 physical cores, 16 logical CPUs
- 15.6 GB system memory
- process-tree RSS sampling via `psutil`

The Monte Carlo fixture is deliberately reproducible rather than maximal:

- trader: `examples/benchmark_trader.py`
- day: `0`
- synthetic tick cap: `250`
- tiers: quick `64/8`, default `100/10`, heavy `192/16`, ceiling `768/24`

## Current runtime

Tracked Monte Carlo timings:

| Case | 1 worker | 2 workers | 4 workers | 8 workers | Peak RSS at widest case |
| --- | ---: | ---: | ---: | ---: | ---: |
| quick light `64/8` | `1.576s` | `1.515s` | `1.287s` | `1.343s` | `364.5 MB` |
| default light `100/10` | `2.204s` | `1.798s` | `1.495s` | `1.513s` | `381.7 MB` |
| heavy light `192/16` | `3.977s` | `n/a` | `n/a` | `1.989s` | `413.7 MB` |
| ceiling light `768/24` | `n/a` | `n/a` | `n/a` | `4.364s` | `602.9 MB` |

Practical loop timings from the same report:

- replay day 0 light: `2.314s`
- compare day 0 light: `2.404s`
- fast pack: `5.298s`
- validation pack: `17.902s`

Those replay and pack paths were not the target of this pass. Treat the Monte
Carlo win as the confirmed result, not a claim that every workflow improved.

## Same-code backend comparison

The cleanest backend comparison is the same codebase, same machine, same
fixture.

| Case | Streaming | Classic | Rust |
| --- | ---: | ---: | ---: |
| default light `100/10`, 1 worker | `2.204s` | `2.675s` | `3.498s` |
| default light `100/10`, 8 workers | `1.513s` | `1.652s` | `2.129s` |
| heavy light `192/16`, 1 worker | `3.977s` | `5.408s` | `5.772s` |
| heavy light `192/16`, 8 workers | `1.989s` | `2.225s` | `3.119s` |
| ceiling light `768/24`, 8 workers | `4.364s` | `7.278s` | `7.426s` |

The ceiling row comes from direct same-machine commands at current HEAD for
classic and rust, because the backend comparison harness run used a reduced
ceiling session count for speed.

## Bottleneck diagnosis

Before the change, the main residual bottleneck was the reporting path, not the
engine. A focused `cProfile` run on the tracked `mc_default_light_w1` case
showed:

- `reports.build_dashboard_payload`: about `1.803s` cumulative
- `reports._aggregate_mc_path_bands`: about `1.675s` cumulative

That meant unsampled Monte Carlo sessions were paying too much to rebuild
all-session path bands after execution had already finished.

After the change, the same family of cases shows a very different shape:

- `mc_default_light_w1`: reporting `0.362s`, dashboard build `0.044s`
- `mc_default_light_w8`: reporting `0.359s`, dashboard build `0.018s`
- `mc_heavy_light_w8`: reporting `0.564s`, dashboard build `0.018s`

The reporting tail is now mostly bundle write and summary assembly rather than
path-band reconstruction.

## What changed

The high-EV change was narrow and deliberate:

1. All-session Monte Carlo path-band rows are now accumulated during execution,
   merged across workers, and finalised once.
2. When a bundle is being written, unsampled sessions can drop their raw
   `path_metrics` rows after contributing to the merged accumulator.
3. Provenance capture is timed separately from dashboard build, so the phase
   chart now tells the truth about where the time went.
4. The runtime benchmark harness now records peak process RSS, peak process-tree
   RSS, child-process count, startup or scheduling overhead, provenance timing,
   and optional cold-vs-warm timing.

## What it bought

Confirmed gains against the pre-change benchmark report:

- `mc_default_light_w8`: `1.720s -> 1.513s` (`-12.0%`)
- `mc_heavy_light_w8`: `2.575s -> 1.989s` (`-22.8%`)
- `mc_ceiling_light_w8`: `8.998s -> 4.364s` (`-51.5%`)
- `mc_default_full_w1`: `3.008s -> 2.785s` (`-7.4%`)
- `mc_default_full_trimmed_w1`: `2.529s -> 2.369s` (`-6.3%`)

This is the key result of the pass. The repo now spends far less time turning
Monte Carlo outputs into dashboard bundles, especially at higher worker counts.

## What still limits the next frontier

The next hard frontier is no longer dashboard assembly. On the tracked fixture,
the remaining shared tail is mostly:

- worker startup and scheduling overhead, about `0.38s` to `0.53s` on the 8-worker cases
- bundle write time, about `0.41s` to `0.80s`
- aggregate summary and compaction work around sampled sessions

Cold-vs-warm skew is small on the tracked default streaming case:

- cold `mc_default_light_w8`: `1.514s`
- warm repeat: `1.490s`

So the remaining ceiling work should focus on startup, scheduling, write-path
and memory churn rather than chasing a cache artefact that is not materially
moving the result.
