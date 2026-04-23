# Benchmarks

Use the benchmark helpers when you want reproducible evidence rather than
one-off timings.

The optional analysis helpers need the `analysis` extra:

```bash
python -m pip install -e ".[analysis]"
```

## Benchmark tools

Storage footprint:

```bash
python analysis/benchmark_outputs.py --output-dir backtests/output_benchmark
```

Runtime suite:

```bash
python analysis/benchmark_runtime.py --output-dir backtests/runtime_benchmark --workers 1 2 4 8 --warm-repeat 1
```

Bundle byte and reporting-path RSS attribution:

```bash
python analysis/benchmark_attribution.py --runtime-report backtests/runtime_benchmark/benchmark_report.json --output-dir backtests/bundle_attribution
```

Execution RSS frontier probe:

```bash
python analysis/rss_frontier.py --output-dir backtests/rss_frontier --baseline-report backtests/runtime_benchmark/benchmark_report.json
```

Same-code backend comparison on realistic traders:

```bash
python analysis/benchmark_backends.py --output-dir backtests/backend_benchmark --warmup 1 --measured-repeats 2
```

Same-machine Chris Roberts reference comparison:

```bash
python analysis/benchmark_chris_reference.py --reference-root path/to/imc-prosperity-4/backtester --output-dir backtests/reference_benchmark
```

Architecture bake-off on a real dashboard payload:

```bash
python analysis/architecture_bakeoff.py --output-dir backtests/architecture_bakeoff --bundle backtests/runtime_benchmark/cases/mc_ceiling_light_w8/dashboard.json --workers 8 --tasks 32 --repeats 3
```

The tracked machine-readable summary for the audited 2026-04-23 local state
lives in [`docs/BENCHMARK_SUMMARY.json`](BENCHMARK_SUMMARY.json).

## What the harness records

Runtime, storage, backend and reference reports record:

- exact command arguments
- git commit and dirty state
- Python executable
- platform and machine metadata
- retained output size and file count
- peak process RSS and process-tree RSS where relevant
- workflow-specific caveats

The runtime suite also records:

- cold and warm timings
- throughput
- worker counts
- engine phase timings
- reporting-phase RSS deltas and peaks for sampled-row compaction, dashboard
  build and bundle writing
- non-engine overhead outside the measured engine wall

The attribution suite records:

- exact retained JSON bytes by schema section
- exact retained bytes and file counts by written file component
- writer-path attribution for each section or file bucket
- row-table storage metadata for compact Monte Carlo sections

The RSS frontier probe records:

- process RSS, tree RSS and child-process counts over time
- exact execution and reporting phase boundaries
- worker lifecycle samples
- chunk payload and path-band accumulator sizes near the peak

## Rerun noise characterisation

Fresh same-code reruns on 2026-04-23 (no broken state, no extra load) showed
the following noise bands on the headline cases. This is the frame to use
when interpreting any single-run number.

| Case | Fresh reruns | Committed headline | Band vs headline |
| --- | --- | ---: | --- |
| `mc_ceiling_light_w8` (wall, 3 warm) | `6.129`, `6.305`, `6.312`s | `6.405s` | `-4%` to `-1%` |
| `mc_default_light_w8` (wall, 3 warm) | `2.333`, `2.382`, `2.394`s | `2.278s` | `+2%` to `+5%` |
| `replay_day0_light` (wall, 3 warm) | `4.883`, `4.936`, `4.952`s | `5.259s` | `-7%` to `-6%` |
| `mc_ceiling_light_w8` tree peak (2 RSS-probe reruns) | `~423`, `~424 MB` | `~404 MB` | `+5%` |

Two conclusions fall out of that:

- no committed number is regressing against fresh reruns once you allow for a
  normal `~5-7%` local noise band
- single tree-peak numbers below `~425 MB` on `mc_ceiling_light_w8` should be
  read as "inside the noise band", not as an improvement or regression

## Comparability notes

The benchmark suite is intentionally split by purpose.

- Replay, compare and research-pack cases use `strategies/trader.py`. These are
  the practical branch-loop timings.
- The tracked Monte Carlo runtime fixture uses `examples/benchmark_trader.py`
  with a `250`-tick synthetic cap. This keeps `1`, `2`, `4` and `8` worker
  runs local and reproducible.
- `analysis/benchmark_backends.py` is the same-code backend proof. It uses
  realistic repo traders so backend rankings are not reduced to a no-op loop.
- `analysis/benchmark_chris_reference.py` is same-machine and matched on a
  shared no-op trader plus tick budget, but it is not full semantic parity.
- `analysis/architecture_bakeoff.py` isolates serialisation and worker-payload
  transport overhead only. It is not a full engine rewrite prototype.
- `analysis/rss_frontier.py` adds diagnostics and process sampling overhead.
  Use it for memory shape and driver attribution, not headline throughput.

## Current proof surface

Tracked current-local headline artefacts captured from a dirty worktree:

- `backtests/_final_output_current_local`
- `backtests/_final_runtime_current_local`
- `backtests/_final_attribution_current_local`
- `backtests/_final_rss_frontier_current_local_v2`
- `backtests/_final_backend_current_local`
- `backtests/_final_reference_current_local`
- `backtests/_final_architecture_current_local`

Exploratory artefacts from this pass still exist, but are not the headline
proof:

- `backtests/_audit_*`
- `backtests/_final_runtime_after_patch`
- `backtests/_final_runtime_after_sample_split`
- `backtests/_target_runtime_*`

Important caveats:

- all results were captured from a dirty worktree in this clone before this
  proof refresh was committed
- this clone does not retain a separate clean exact-same-worktree historical
  throughput baseline for the final diagnostics-only state
- the Chris Roberts comparison is same-machine and matched on a shared no-op
  trader plus tick budget, but it is not full semantic parity
- the shared-memory result is a transport microbenchmark only, not end-to-end
  Monte Carlo proof

## Current storage results

Measured on 2026-04-23 with
`backtests/_final_output_current_local/benchmark_report.json`:

| Case | Size | Files | What it proves |
| --- | ---: | ---: | --- |
| `replay_light` | `1.36 MB` | `6` | Exact replay summary, fills and compact paths stay small enough for routine review. |
| `replay_full` | `1.99 MB` | `12` | Full replay adds raw orders and chart sidecars without a large footprint jump. |
| `mc_light` | `819.9 KB` | `6` | Light Monte Carlo keeps exact distribution metrics, all-session path bands and sampled previews in under `1 MB` on the tracked fixture. |
| `mc_full` | `5.16 MB` | `18` | Full Monte Carlo keeps the forensic extras, but the retained footprint is still moderate for the tracked fixture. |

## Current runtime result

Use `backtests/_final_runtime_current_local/benchmark_report.json` as the
current local headline runtime report for this pass.

| Case | Elapsed | Peak tree RSS | Output bytes | Files |
| --- | ---: | ---: | ---: | ---: |
| `replay_day0_light` | `5.259s` | `163.6 MB` | `21,148,197` | `6` |
| `compare_day0_light` | `3.980s` | `175.1 MB` | `12,083` | `3` |
| `pack_fast` | `9.667s` | `373.3 MB` | `21,771,812` | `17` |
| `pack_validation` | `28.105s` | `653.6 MB` | `61,823,064` | `17` |
| `mc_quick_light_w8` | `2.087s` | `344.7 MB` | `2,369,646` | `6` |
| `mc_default_light_w8` | `2.278s` | `357.1 MB` | `2,900,929` | `6` |
| `mc_heavy_light_w8` | `3.082s` | `359.0 MB` | `4,439,848` | `6` |
| `mc_ceiling_light_w8` | `6.405s` | `411.5 MB` | `6,645,976` | `6` |
| `mc_default_full_w1` | `6.800s` | `127.1 MB` | `25,175,713` | `122` |

For the tracked `250`-tick Monte Carlo fixture, the fresh current-local scaling
table is:

| Case | 1 worker | 2 workers | 4 workers | 8 workers |
| --- | ---: | ---: | ---: | ---: |
| MC quick light (64 sess) | `2.924s` | `2.500s` | `2.128s` | `2.087s` |
| MC default light (100 sess) | `3.952s` | `3.245s` | `2.520s` | `2.278s` |
| MC heavy light (192 sess) | `6.838s` | `n/a` | `n/a` | `3.082s` |
| MC ceiling light (768 sess) | `n/a` | `n/a` | `n/a` | `6.405s` |

## Current retained-output and reporting ownership

The fresh attribution pass is tracked in
`backtests/_final_attribution_current_local/bundle_attribution.json`.

For `mc_default_light_w8`:

- bundle bytes: `2,900,929`
- file count: `6`
- top dashboard owners:
  - `monteCarlo.sampleRuns`: `1,243,393`
  - `monteCarlo.pathBands`: `308,931`
  - `monteCarlo.sampleRuns.fills`: `283,252`
  - `monteCarlo.sampleRuns.orderIntent`: `257,141`
- reporting-phase RSS:
  - before reporting: `91.9 MB`
  - sampled-row compaction peak: `110.2 MB`
  - dashboard build peak: `114.9 MB`
  - bundle write peak: `125.9 MB`

For `mc_ceiling_light_w8`:

- bundle bytes: `6,645,976`
- file count: `6`
- top dashboard owners:
  - `monteCarlo.sampleRuns`: `2,986,485`
  - `monteCarlo.sampleRuns.fills`: `680,250`
  - `monteCarlo.sampleRuns.orderIntent`: `616,955`
  - `monteCarlo.sampleRuns.fairValueSeries`: `534,751`
- reporting-phase RSS:
  - before reporting: `239.2 MB`
  - sampled-row compaction peak: `282.7 MB`
  - dashboard build peak: `208.0 MB`
  - bundle write peak: `233.5 MB`

The retained-byte frontier is now narrow and explicit:

1. `monteCarlo.sampleRuns` preview series
2. `fills.csv`
3. the reporting path itself

`pathBands` are no longer a first-order retained-byte problem on the current
local evidence.

## Current execution RSS frontier

The fresh high-resolution ceiling probe is tracked in
`backtests/_final_rss_frontier_current_local_v2/rss_frontier_report.json`.

Headline numbers for `mc_ceiling_light_w8`:

- tree peak: `404.4 MB`
- parent peak: `282.7 MB`
- peak phase: `execution`
- workers alive at tree peak: `8`
- worker RSS at tree peak: `32.6 MB` to `35.0 MB`
- live worker RSS at tree peak: `266.9 MB`
- parent RSS at tree peak: `137.4 MB`
- parent execution transient above the pre-reporting baseline: `43.6 MB`
- reporting transient above the pre-reporting baseline: `43.5 MB`
- latest chunk before the peak:
  - payload pickle size: `1,477,700` bytes
  - path-band accumulator pickle size: `927,287` bytes
  - result count: `48`
  - sampled result count: `1`

That is the clearest current statement of the remaining memory frontier:

1. live worker processes dominate the global peak
2. parent-side chunk receive and merge adds a smaller but real execution bump
3. reporting is still material, but it is no longer the global tree peak

## Realistic backend comparison

The fresh same-code realistic-trader rerun in
`backtests/_final_backend_current_local/backend_benchmark.json` kept the
backend story mixed but stable:

| Case | Streaming | Classic | Rust | Winner |
| --- | ---: | ---: | ---: | --- |
| `live_v9_default_w1` | `7.478s` | `7.437s` | `9.056s` | `classic` |
| `live_v9_default_w8` | `2.679s` | `2.650s` | `3.541s` | `classic` |
| `live_v9_heavy_w8` | `3.770s` | `3.893s` | `4.732s` | `streaming` |
| `main_default_w8` | `2.451s` | `2.378s` | `3.237s` | `classic` |
| `main_heavy_w8` | `3.194s` | `3.109s` | `4.311s` | `classic` |
| `r2_stateful_default_w8` | `2.470s` | `2.517s` | `3.564s` | `streaming` |
| `r2_stateful_heavy_w8` | `3.441s` | `3.564s` | `4.483s` | `streaming` |

The honest current position is:

- `streaming` remains the design default, but not the raw-speed leader in this rerun
- `classic` is a real parity and performance option, not a slower fallback
- `rust` stayed slower than both Python backends in every measured cell

## External reference result

Chris Roberts' repo remains the strongest narrow Monte Carlo reference that was
available locally in this pass.

The fresh same-machine rerun in
`backtests/_final_reference_current_local/reference_benchmark.json` used:

- one warm-up pass per repo
- the same shared no-op trader file in both repos
- matched `250` ticks per simulated day
- matched `100/10` and `1000/100` session or sample tiers
- matched `1`, `2`, `4` and `8` worker settings

Warm same-machine runtime results still favoured this repo in every measured
cell:

- default `100/10`: `4.80x` to `14.75x` faster
- ceiling `1000/100`: `9.59x` to `18.35x` faster

The retained-output story also held:

- this repo wrote fewer retained bytes in every measured cell
- this repo used far fewer files, `5` instead of `50` or `410`
- this repo used less RSS on every smaller default `100/10` case
- Chris still kept lower RSS on every `1000/100` ceiling case

So the honest external claim is:

- same-machine runtime-throughput lead: yes
- same-machine retained-byte lead on the matched no-op benchmark: yes
- same-machine retained file-count lead: yes
- ceiling-RSS lead: no

## Architecture bake-off

The fresh architecture bake-off used
`backtests/_final_runtime_current_local/cases/mc_ceiling_light_w8/dashboard.json`,
`3,349,505` bytes on disk.

Results:

- MessagePack payload: `2,388,492` bytes versus `3,349,505` for compact JSON
- MessagePack encode: `0.0192s` versus JSON `0.1074s`
- MessagePack decode: `0.0242s` versus JSON `0.0919s`
- shared-memory transport: `0.583s` versus pickled transport `0.631s`

That keeps MessagePack alive as the only still-plausible contract-boundary
architecture move. Shared memory is no longer negative on the microbenchmark,
but the gain is still too small and too isolated to justify landing it without
an end-to-end win.
