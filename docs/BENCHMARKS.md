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
| `mc_light` | `1.95 MB` | `6` | Light Monte Carlo keeps exact all-session summary stats and path bands while preview-capping sampled qualitative runs in `dashboard.json`. |
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
| `replay_day0_light` | `2.264s` | `167.8 MB` | practical replay loop |
| `compare_day0_light` | `2.220s` | `175.8 MB` | practical compare loop |
| `pack_fast` | `5.067s` | `382.9 MB` | fast research pack |
| `pack_validation` | `16.240s` | `651.2 MB` | validation pack |
| `mc_quick_light_w8` | `1.091s` | `342.6 MB` | quickest 8-worker MC loop |
| `mc_default_light_w8` | `1.180s` | `351.4 MB` | recommended default MC loop |
| `mc_heavy_light_w8` | `1.527s` | `368.2 MB` | heavier validation MC |
| `mc_ceiling_light_w8` | `3.313s` | `402.7 MB` | higher-scale ceiling case |

## Phase timing examples

The benchmark report now breaks Monte Carlo runs into engine, reporting,
provenance and startup or scheduling components.

Tracked examples:

- `mc_default_light_w1`
  - reporting `0.216s`
  - wall `1.412s`
  - startup or scheduling `0.341s`
  - provenance `0.109s`
- `mc_default_light_w8`
  - reporting `0.217s`
  - wall `0.632s`
  - startup or scheduling `0.332s`
  - provenance `0.103s`
- `mc_heavy_light_w8`
  - reporting `0.301s`
  - wall `0.889s`
  - startup or scheduling `0.337s`
  - provenance `0.104s`

This matters because dashboard build itself is now only `6` to `18 ms` in the
tracked cases. The remaining reporting tail is mostly bundle write work and
sample preview compaction, not path-band reconstruction.

## Same-code backend comparison

Measured on current HEAD:

| Case | Streaming | Classic | Rust |
| --- | ---: | ---: | ---: |
| default light `100/10`, 1 worker | `1.969s` | `2.459s` | `3.366s` |
| default light `100/10`, 8 workers | `1.180s` | `1.609s` | `1.913s` |
| heavy light `192/16`, 1 worker | `3.474s` | `4.936s` | `5.661s` |
| heavy light `192/16`, 8 workers | `1.527s` | `2.019s` | `2.895s` |
| ceiling light `768/24`, 8 workers | `3.313s` | `4.627s` | `5.054s` |

On the tracked fixture, `streaming` is the winner through the measured
8-worker cases.

## Realistic trader proof

Same-code backend checks with repo-tested realistic traders still favour
`streaming` where the practical research loop matters:

| Trader and case | Streaming | Classic | Rust |
| --- | ---: | ---: | ---: |
| `trader_round1_v9`, default `100/10`, 8 workers | `1.380s` | `1.399s` | `1.895s` |
| `trader_round1_v9`, heavy `192/16`, 8 workers | `1.877s` | `2.106s` | `2.423s` |
| `strategies/trader.py`, default `100/10`, 8 workers | `1.280s` | `1.313s` | `1.737s` |
| `strategies/trader.py`, heavy `192/16`, 8 workers | `1.652s` | `1.663s` | `3.385s` |

The only near-tie on the lighter one-thread cases was `trader_round1_v9`
default `100/10`, where `classic` was faster by `13 ms`. Rust stayed slower in
the meaningful multi-worker cells, even when it kept the lowest RSS.

## Cold and warm note

The tracked default streaming case has a small warm-run effect:

- cold `mc_default_light_w8`: `1.376s`
- warm repeat: `1.278s`

That is worth recording, but it is not large enough to explain the headline
improvement. The change is real.

## External reference note

Chris Roberts' repo is still the strongest public narrow Monte Carlo reference,
so it is worth checking on the same machine when feasible.

The cleanest shared-fixture pass on 2026-04-22 used:

- the same no-op trader file in both repos
- matched `250` ticks per session
- matched `100/10` and `1000/100` session or sample tiers
- matched `1`, `2`, `4`, and `8` worker settings
- one warm-up run per repo before the measured pass

Warm same-machine runtime results favoured this repo in every measured cell:

- default `100/10`: about `4.3x` to `19.0x` faster
- ceiling `1000/100`: about `10.6x` to `13.1x` faster

That shared-fixture pass used Chris's public `prosperity3bt mc` entrypoint with
`--ticks-per-day 250` and `--tomato-support quarter`, because the headline
`prosperity4mcbt` CLI does not expose the tick cap needed for a strict
same-machine normalisation.

The result is still not an undisputed all-axis performance crown:

- this repo used less RSS on the smaller default `100/10` cases, but Chris kept the lighter RSS footprint on `1000/100`
- Chris also kept the smaller retained output footprint, by about `1.9x` on the rerun
- Chris's native public default still means tutorial-round `10000`-tick sessions

So the honest claim is a strong shared-fixture runtime-throughput lead, not a
blanket claim that every performance dimension now belongs to this repo.
