# Benchmarks

Use the benchmark helpers when you want reproducible storage and runtime
evidence rather than one-off timing anecdotes.

## Benchmark tools

Storage footprint:

```bash
python analysis/benchmark_outputs.py --output-dir backtests/output_benchmark
```

Runtime suite:

```bash
python analysis/benchmark_runtime.py --output-dir backtests/runtime_benchmark --compare-report path/to/previous/benchmark_report.json --workers 1 2 4 8
```

Optional warm-repeat pass:

```bash
python analysis/benchmark_runtime.py --output-dir backtests/runtime_benchmark_warm --workers 1 2 4 8 --warm-repeat 1
```

## What the runtime harness records

Each runtime case now records:

- wall time
- output bundle size
- peak process RSS
- peak process-tree RSS
- peak child-process count
- engine and reporting phase timings
- startup or scheduling overhead outside the measured engine wall
- provenance capture time
- optional cold and warm timings
- git commit, dirty state, Python executable, platform and machine metadata

This keeps performance claims tied to the environment that produced them.

## Comparability notes

The benchmark suite is intentionally split by purpose.

- Replay, compare and pack cases use `strategies/trader.py`. These are the
  practical branch-loop timings.
- Monte Carlo uses `examples/benchmark_trader.py` and a `250`-tick synthetic
  cap. This keeps 1, 2, 4 and 8 worker runs local and reproducible.
- Backend comparisons are same-code, same-machine comparisons. That is the most
  trustworthy way to compare `streaming`, `classic` and `rust`.
- Cross-repo comparisons are harder. Chris Roberts' repo uses tutorial-round
  products, a different day structure and a different output surface. Same-machine
  notes are useful context, but not an apples-to-apples proof of superiority.

## Current storage results

Measured on 2026-04-22 with the default storage benchmark fixture:

| Case | Size | Files | What it proves |
| --- | ---: | ---: | --- |
| `replay_light` | `1.36 MB` | `6` | Exact replay summary, fills and compact paths remain small enough for daily review. |
| `replay_full` | `1.99 MB` | `12` | Full replay adds raw orders and chart sidecars without exploding bundle size. |
| `mc_light` | `3.91 MB` | `6` | Light Monte Carlo keeps exact all-session summary stats and path bands without duplicate sample files. |
| `mc_full` | `7.51 MB` | `18` | Full Monte Carlo roughly doubles size because sample-path files and session manifests are written explicitly. |

## Current runtime results

Measured on 2026-04-22 on:

- Windows 10
- Python 3.11
- 8 physical cores
- 16 logical CPUs
- 15.6 GB system memory

Representative current results:

| Case | Current | Peak RSS | Notes |
| --- | ---: | ---: | --- |
| `replay_day0_light` | `2.314s` | `195.3 MB` | practical replay loop |
| `compare_day0_light` | `2.404s` | `178.9 MB` | practical compare loop |
| `pack_fast` | `5.298s` | `380.3 MB` | fast research pack |
| `pack_validation` | `17.902s` | `654.4 MB` | validation pack |
| `mc_quick_light_w8` | `1.343s` | `364.5 MB` | quickest 8-worker MC loop |
| `mc_default_light_w8` | `1.513s` | `381.7 MB` | recommended default MC loop |
| `mc_heavy_light_w8` | `1.989s` | `413.7 MB` | heavier validation MC |
| `mc_ceiling_light_w8` | `4.364s` | `602.9 MB` | higher-scale ceiling case |

## Phase timing examples

The benchmark report now breaks Monte Carlo runs into engine, reporting,
provenance and startup or scheduling components.

Tracked examples:

- `mc_default_light_w1`
  - reporting `0.362s`
  - wall `1.442s`
  - startup or scheduling `0.400s`
  - provenance `0.112s`
- `mc_default_light_w8`
  - reporting `0.359s`
  - wall `0.776s`
  - startup or scheduling `0.378s`
  - provenance `0.107s`
- `mc_heavy_light_w8`
  - reporting `0.564s`
  - wall `1.019s`
  - startup or scheduling `0.406s`
  - provenance `0.111s`

This matters because the previous bottleneck was dashboard-side path-band
aggregation. The current report shows that bottleneck is now largely gone.

## Same-code backend comparison

Measured on current HEAD:

| Case | Streaming | Classic | Rust |
| --- | ---: | ---: | ---: |
| default light `100/10`, 1 worker | `2.204s` | `2.675s` | `3.498s` |
| default light `100/10`, 8 workers | `1.513s` | `1.652s` | `2.129s` |
| heavy light `192/16`, 1 worker | `3.977s` | `5.408s` | `5.772s` |
| heavy light `192/16`, 8 workers | `1.989s` | `2.225s` | `3.119s` |
| ceiling light `768/24`, 8 workers | `4.364s` | `7.278s` | `7.426s` |

On the tracked fixture, `streaming` is the winner through the measured
8-worker cases.

## Cold and warm note

The tracked default streaming case has a small warm-run effect:

- cold `mc_default_light_w8`: `1.514s`
- warm repeat: `1.490s`

That is worth recording, but it is not large enough to explain the headline
improvement. The change is real.

## External reference note

Chris Roberts' repo is still the strongest public narrow Monte Carlo reference,
so it is worth checking on the same machine when feasible.

The cleanest shared-fixture pass on 2026-04-22 used:

- the same no-op trader file in both repos
- matched `250` ticks per session
- matched `100/10`, `512/32`, and `1000/100` session or sample tiers
- matched `1`, `2`, `4`, and `8` worker settings

Warm same-machine runtime results favoured this repo in every measured cell:

- default `100/10`: about `4.3x` to `13.9x` faster
- heavy `512/32`: about `8.8x` to `15.2x` faster
- ceiling `1000/100`: about `8.7x` to `13.3x` faster

That shared-fixture pass used Chris's public `prosperity3bt mc` entrypoint with
`--ticks-per-day 250` and `--tomato-support quarter`, because the headline
`prosperity4mcbt` CLI does not expose the tick cap needed for a strict
same-machine normalisation.

The result is still not an undisputed all-axis performance crown:

- Chris kept the lighter RSS footprint in the heavier and ceiling cases
- Chris also kept the smaller retained output footprint
- Chris's native public default still means tutorial-round `10000`-tick sessions

So the honest claim is a strong shared-fixture runtime-throughput lead, not a
blanket claim that every performance dimension now belongs to this repo.
