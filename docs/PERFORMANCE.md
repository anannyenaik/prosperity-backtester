# Performance

Result: the repo still has the strongest overall local performance story, and
the retained-byte win held up again, but ceiling-case RSS and final proof
cleanliness are still the blockers to a full all-axis crown.

All claims below come from local benchmark runs on 2026-04-22. See
[`docs/BENCHMARKS.md`](BENCHMARKS.md) and
[`docs/BENCHMARK_SUMMARY.json`](BENCHMARK_SUMMARY.json) for the tracked proof
surface.

The proof split matters:

- `backtests/_final_local_output`, `_final_local_attribution`,
  `_final_local_backend`, `_final_local_reference` and
  `_final_local_architecture` are fresh reruns from the current dirty
  worktree.
- `backtests/_final_local_runtime` is also a fresh current-code rerun, but it
  was clearly machine-contended. Output bytes and RSS stayed in family while
  every wall-clock roughly doubled together.
- `backtests/_baseline_runtime` and `backtests/_final_runtime_current` are
  therefore still the cleanest same-code throughput baselines for this
  worktree.

## Current backend choice

There are three Monte Carlo backends in
`prosperity_backtester/mc_backends.py`:

| Backend | Use it when | Current verdict |
| --- | --- | --- |
| `streaming` | normal research work and the default branch loop | Recommended default. Still the best overall balance of throughput, fidelity, install sanity and workflow breadth. |
| `classic` | parity checks and cases where you want full replay-style materialisation | Real parity option. It still wins several realistic measured cells, so it is not honest to describe it as only a slower fallback. |
| `rust` | explicit backend experiments when you want to test the native path | Kept available, but not recommended. It stayed slower than both Python backends on every realistic rerun in this pass. |

`auto` still resolves to `streaming`.

## What the current pass actually proved

The highest-value change in this pass was not a broad engine rewrite. It was a
storage and reporting refinement pass:

- Monte Carlo `sessions` are now stored as slim row tables
- sampled preview series are stored as compact row tables
- path-band leaves are stored compactly
- duplicate `fairValueBands` are dropped when `pathBands` already carry the
  same analysis-fair and mid information
- large JSON payloads are written directly to disk instead of being rendered
  into one extra in-memory string first

That produced a real retained-byte win, and the fresh current-local storage
rerun reproduced it exactly:

- storage benchmark `mc_light`: `1.95 MB -> 819.8 KB` (`-57.9%`)
- storage benchmark `mc_full`: `7.51 MB -> 5.16 MB` (`-31.3%`)
- runtime suite `mc_default_light_w8`: `5.75 MB -> 2.90 MB`
- runtime suite `mc_ceiling_light_w8`: `13.45 MB -> 6.65 MB`

Runtime stayed broadly neutral rather than one-sided in the least-contended
same-code baselines:

- `mc_default_light_w8`: `1.370s -> 1.321s`
- `mc_ceiling_light_w8`: `3.061s -> 3.089s`
- `mc_heavy_light_w8`: `1.515s -> 1.828s`

The fresh full current-code runtime rerun in `backtests/_final_local_runtime`
did not overturn that conclusion. It kept the same output bytes and the same
RSS shape, but the machine was obviously slower across every case, so it is a
current-code validation rerun rather than the cleanest throughput headline.

## Current bottleneck picture

Fresh attribution on the current code kept the retained-byte frontier narrow.

The biggest retained-byte owners in light Monte Carlo are now:

1. `monteCarlo.sampleRuns` preview series, especially `fills`, `orderIntent`,
   `fairValueSeries`, `behaviourSeries` and `pnlSeries`
2. `fills.csv`
3. the reporting path itself, specifically sampled-row compaction and bundle
   writing

`pathBands` used to be a first-order retained-byte problem. After the current
compaction pass they no longer are.

Fresh local ceiling probes now make the peak shape explicit:

- the fresh runtime-suite rerun recorded `452.5 MB` tree RSS on
  `mc_ceiling_light_w8`
- targeted current-local ceiling probes ranged from `450.7 MB` to `459.0 MB`
  tree RSS
- every targeted probe put the global peak in execution rather than reporting
- one high-resolution peak sample showed one driver process at about
  `100.3 MB` plus eight live workers at about `35.7 MB` to `39.9 MB` each
- parent-only reporting RSS stayed lower:
  - before reporting: `252.2 MB`
  - sampled-row compaction peak: `273.9 MB`
  - dashboard build peak: `219.4 MB`
  - bundle-write peak: `246.3 MB`

That is why dashboard build time is no longer the main concern. The true tail
is execution-phase process-tree RSS, with sampled-row compaction and exact fill
retention still the main parent-side costs.

## Same-code backend proof

The no-op benchmark is not enough. The backend benchmark was rerun against
realistic repo traders:

| Case | Streaming | Classic | Rust | Winner |
| --- | ---: | ---: | ---: | --- |
| `live_v9_default_w1` | `7.684s` | `7.721s` | `10.824s` | `streaming` |
| `live_v9_default_w8` | `3.475s` | `3.541s` | `5.038s` | `streaming` |
| `live_v9_heavy_w8` | `5.231s` | `5.153s` | `6.405s` | `classic` |
| `main_default_w8` | `2.974s` | `3.040s` | `4.098s` | `streaming` |
| `main_heavy_w8` | `4.279s` | `4.148s` | `5.685s` | `classic` |
| `r2_stateful_default_w8` | `3.465s` | `3.115s` | `4.274s` | `classic` |
| `r2_stateful_heavy_w8` | `4.133s` | `3.920s` | `5.255s` | `classic` |

That is the key correction to any oversimplified story:

- `streaming` remains the best default overall
- `classic` still matters and still wins realistic cells
- `rust` is still an experiment rather than a production default

## External reference result

The fresh same-machine Chris Roberts rerun still proves more than a runtime
lead on the matched shared no-op benchmark:

- default `100/10`: this repo is `4.43x` to `14.18x` faster
- ceiling `1000/100`: this repo is `10.69x` to `17.67x` faster
- this repo writes fewer retained bytes in every measured cell
- this repo still writes far fewer files, `5` instead of `50` or `410`

But the all-axis story is still not closed:

- this repo uses less RSS on the smaller default cases
- Chris keeps lower RSS on every ceiling case

That is enough to claim a strong same-machine throughput lead and a
same-machine retained-byte lead on the matched no-op comparison. It is not
enough to claim a full memory-efficiency crown.

## Architecture direction

The architecture bake-off still shows real upside in binary serialisation:

- MessagePack reduced the real payload from `3.35 MB` to `2.39 MB`
- MessagePack encoded and decoded materially faster than JSON

Shared-memory transport got weaker rather than stronger on the fresh rerun:

- pickled transport: `0.590s`
- shared memory: `0.622s`
- speed-up: `0.948x`

That changes the architecture judgement slightly:

- streaming-first Python still remains the best current architecture
- optional binary sidecars remain the only still-plausible architecture move,
  but they do not land now because they do not solve ceiling RSS and a default
  JSON-plus-sidecar write would increase retained bytes
- lower-copy shared-memory transport is currently weaker than the status quo on
  the fresh bake-off evidence
- Rust, C++, C, Cython and Numba still do not have an isolated measured kernel
  that justifies crossing the native boundary now

## Honest verdict

Current honest scorecard:

- runtime throughput: very strong on the least-contended same-code baseline,
  but the fresh full current-code rerun was too machine-contended to be the
  cleanest headline proof
- retained-output efficiency: materially stronger and now much closer to
  closure
- ceiling-case RSS: still the main unresolved gap
- trust and proof cleanliness: materially better, but still limited by the
  dirty worktree and by the need to separate fresh contended reruns from the
  cleaner historical same-code runtime baseline
- architecture finality: not fully closed, but the live options are now much
  narrower and clearer than before
