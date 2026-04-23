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

The tracked machine-readable summary for the audited 2026-04-22 local state
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

Fresh current-local headline artefacts from this dirty worktree:

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

- all results are fresh dirty-worktree local evidence from this clone
- this clone does not retain a separate clean exact-same-worktree historical
  throughput baseline for the final diagnostics-only state
- the Chris Roberts comparison is same-machine and matched on a shared no-op
  trader plus tick budget, but it is not full semantic parity
- the shared-memory result is a transport microbenchmark only, not end-to-end
  Monte Carlo proof

## Current storage results

Measured on 2026-04-22 with
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
| `replay_day0_light` | `2.570s` | `156.9 MB` | `21,148,197` | `6` |
| `compare_day0_light` | `2.027s` | `175.6 MB` | `12,083` | `3` |
| `pack_fast` | `5.299s` | `386.6 MB` | `21,771,803` | `17` |
| `pack_validation` | `17.783s` | `720.5 MB` | `61,823,066` | `17` |
| `mc_quick_light_w8` | `1.282s` | `351.6 MB` | `2,369,651` | `6` |
| `mc_default_light_w8` | `1.321s` | `354.7 MB` | `2,900,938` | `6` |
| `mc_heavy_light_w8` | `1.830s` | `372.1 MB` | `4,439,849` | `6` |
| `mc_ceiling_light_w8` | `3.370s` | `417.5 MB` | `6,645,972` | `6` |
| `mc_default_full_w1` | `3.302s` | `127.8 MB` | `25,175,707` | `122` |

For the tracked `250`-tick Monte Carlo fixture, the fresh current-local scaling
table is:

| Case | 1 worker | 2 workers | 4 workers | 8 workers |
| --- | ---: | ---: | ---: | ---: |
| MC quick light (64 sess) | `1.402s` | `1.370s` | `1.138s` | `1.282s` |
| MC default light (100 sess) | `1.936s` | `1.564s` | `1.320s` | `1.321s` |
| MC heavy light (192 sess) | `3.362s` | `n/a` | `n/a` | `1.830s` |
| MC ceiling light (768 sess) | `n/a` | `n/a` | `n/a` | `3.370s` |

## Current retained-output and reporting ownership

The fresh attribution pass is tracked in
`backtests/_final_attribution_current_local/bundle_attribution.json`.

For `mc_default_light_w8`:

- bundle bytes: `2,900,938`
- file count: `6`
- top dashboard owners:
  - `monteCarlo.sampleRuns`: `1,243,393`
  - `monteCarlo.pathBands`: `308,931`
  - `monteCarlo.sampleRuns.fills`: `283,252`
  - `monteCarlo.sampleRuns.orderIntent`: `257,141`
- reporting-phase RSS:
  - before reporting: `93.1 MB`
  - sampled-row compaction peak: `111.4 MB`
  - dashboard build peak: `109.1 MB`
  - bundle write peak: `120.8 MB`

For `mc_ceiling_light_w8`:

- bundle bytes: `6,645,972`
- file count: `6`
- top dashboard owners:
  - `monteCarlo.sampleRuns`: `2,986,485`
  - `monteCarlo.sampleRuns.fills`: `680,250`
  - `monteCarlo.sampleRuns.orderIntent`: `616,955`
  - `monteCarlo.sampleRuns.fairValueSeries`: `534,751`
- reporting-phase RSS:
  - before reporting: `236.1 MB`
  - sampled-row compaction peak: `279.9 MB`
  - dashboard build peak: `291.1 MB`
  - bundle write peak: `316.8 MB`

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

- tree peak: `415.3 MB`
- parent peak: `276.3 MB`
- peak phase: `execution`
- workers alive at tree peak: `8`
- worker RSS at tree peak: `33.9 MB` to `35.1 MB`
- live worker RSS at tree peak: `277.7 MB`
- parent execution transient above the pre-reporting baseline: `37.0 MB`
- reporting transient above the pre-reporting baseline: `35.1 MB`
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
| `live_v9_default_w1` | `4.039s` | `4.106s` | `4.980s` | `streaming` |
| `live_v9_default_w8` | `1.894s` | `1.948s` | `2.561s` | `streaming` |
| `live_v9_heavy_w8` | `2.639s` | `2.689s` | `3.264s` | `streaming` |
| `main_default_w8` | `1.749s` | `1.691s` | `2.432s` | `classic` |
| `main_heavy_w8` | `2.264s` | `2.332s` | `3.161s` | `streaming` |
| `r2_stateful_default_w8` | `1.798s` | `1.808s` | `2.419s` | `streaming` |
| `r2_stateful_heavy_w8` | `2.383s` | `1.932s` | `3.101s` | `classic` |

The honest current position is:

- `streaming` remains the best overall default
- `classic` is still a real parity and performance fallback
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

- default `100/10`: `4.18x` to `18.09x` faster
- ceiling `1000/100`: `10.27x` to `15.76x` faster

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
`3,349,504` bytes on disk.

Results:

- MessagePack payload: `2,388,492` bytes versus `3,349,504` for compact JSON
- MessagePack encode: `0.0126s` versus JSON `0.0690s`
- MessagePack decode: `0.0276s` versus JSON `0.0536s`
- shared-memory transport: `0.599s` versus pickled transport `0.718s`

That keeps MessagePack alive as the only still-plausible contract-boundary
architecture move. Shared memory is no longer negative on the microbenchmark,
but the gain is still too small and too isolated to justify landing it without
an end-to-end win.
