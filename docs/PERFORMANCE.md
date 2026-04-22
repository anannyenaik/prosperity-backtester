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
| quick light `64/8` | `1.389s` | `1.147s` | `1.089s` | `1.091s` | `342.6 MB` |
| default light `100/10` | `1.969s` | `1.576s` | `1.198s` | `1.180s` | `351.4 MB` |
| heavy light `192/16` | `3.474s` | `n/a` | `n/a` | `1.527s` | `368.2 MB` |
| ceiling light `768/24` | `n/a` | `n/a` | `n/a` | `3.313s` | `402.7 MB` |

Practical loop timings from the same report:

- replay day 0 light: `2.264s`
- compare day 0 light: `2.220s`
- fast pack: `5.067s`
- validation pack: `16.240s`

Those replay and pack paths were not the target of this pass. Treat the Monte
Carlo win as the confirmed result, not a claim that every workflow improved.

## Same-code backend comparison

The cleanest backend comparison is the same codebase, same machine, same
fixture.

| Case | Streaming | Classic | Rust |
| --- | ---: | ---: | ---: |
| default light `100/10`, 1 worker | `1.969s` | `2.459s` | `3.366s` |
| default light `100/10`, 8 workers | `1.180s` | `1.609s` | `1.913s` |
| heavy light `192/16`, 1 worker | `3.474s` | `4.936s` | `5.661s` |
| heavy light `192/16`, 8 workers | `1.527s` | `2.019s` | `2.895s` |
| ceiling light `768/24`, 8 workers | `3.313s` | `4.627s` | `5.054s` |

Classic now has a small RSS edge on the widest ceiling row, and Rust still
keeps the smallest retained bundle footprint on some rows, but neither backend
beats `streaming` on the practical runtime cells.

## Realistic trader proof

The no-op benchmark is not the whole story, so the current pass also reran
same-code backend checks with repo-tested traders:

- `examples/trader_round1_v9.py`, default `100/10`, `8` workers: `streaming 1.380s`, `classic 1.399s`, `rust 1.895s`
- `examples/trader_round1_v9.py`, heavy `192/16`, `8` workers: `streaming 1.877s`, `classic 2.106s`, `rust 2.423s`
- `strategies/trader.py`, default `100/10`, `8` workers: `streaming 1.280s`, `classic 1.313s`, `rust 1.737s`
- `strategies/trader.py`, heavy `192/16`, `8` workers: `streaming 1.652s`, `classic 1.663s`, `rust 3.385s`

The only meaningful exception was the lightest `trader_round1_v9.py` default
`100/10`, `1` worker cell, where `classic` was faster by `13 ms`. That is too
small to justify changing the default backend.

## Bottleneck diagnosis

After the earlier all-session path-band merge pass, the main residual
bottleneck was no longer path-band reconstruction. The remaining avoidable cost
was light-mode sampled-run preview retention plus Python-list-heavy
all-session accumulator state.

On the pre-change `mc_ceiling_light_w8` light bundle:

- `dashboard.json` alone was about `33.66 MB`
- sampled `sampleRuns` inside that payload accounted for about `31.08 MB`
- peak process-tree RSS was about `632.2 MB`

After the change, the tracked phase profile looks much healthier:

- `mc_default_light_w1`: reporting `0.216s`, dashboard build `0.007s`, bundle write `0.168s`
- `mc_default_light_w8`: reporting `0.217s`, dashboard build `0.006s`, bundle write `0.154s`
- `mc_heavy_light_w8`: reporting `0.301s`, dashboard build `0.010s`, bundle write `0.219s`
- `mc_ceiling_light_w8`: reporting `0.517s`, dashboard build `0.018s`, bundle write `0.385s`

Dashboard build is no longer the dominant tail. Write-path cost and retained
output size are now the main remaining storage-performance frontier.

## What changed

The high-EV change was narrow and deliberate:

1. Light-mode Monte Carlo sampled runs are now explicit previews, capped per
   retained series and annotated with truncation and total-count metadata.
2. The all-session path-band accumulator now stores merged bucket values in
   `array('d')` and keeps envelopes as scalar min or max state instead of
   growing Python float lists.
3. The dashboard surfaces now expose the sampled-run preview policy so the
   storage trade-off is visible rather than implicit.

## What it bought

Confirmed gains against the immediately previous benchmark report:

- `mc_light` bundle size: `3.91 MB -> 1.95 MB` (`-50.2%`)
- `mc_default_light_w8`: `1.513s -> 1.180s` (`-22.0%`), RSS `381.7 MB -> 351.4 MB` (`-8.0%`), output `-63.0%`
- `mc_heavy_light_w8`: `1.989s -> 1.527s` (`-23.2%`), RSS `413.7 MB -> 368.2 MB` (`-11.0%`), output `-64.5%`
- `mc_ceiling_light_w8`: `4.364s -> 3.313s` (`-24.1%`), RSS `602.9 MB -> 402.7 MB` (`-33.2%`), output `-63.6%`

This is the key result of the pass. The repo now spends much less memory and
retains much less output on the tracked light Monte Carlo path without giving
back the runtime lead.

## What still limits the next frontier

The next hard frontier is no longer dashboard assembly. On the tracked fixture,
the remaining shared tail is mostly:

- worker startup and scheduling overhead, about `0.33s` to `0.40s` on the 8-worker cases
- bundle write time, about `0.15s` to `0.38s`
- retained-output size versus Chris Roberts on the shared no-op reference cases
- ceiling-case RSS, where `classic` is still slightly lighter than `streaming`

Cold-vs-warm skew is small on the tracked default streaming case:

- cold `mc_default_light_w8`: `1.376s`
- warm repeat: `1.278s`

So the remaining ceiling work should focus on startup, scheduling, write-path
and retained-output footprint rather than chasing a cache artefact that is not
materially moving the result.
