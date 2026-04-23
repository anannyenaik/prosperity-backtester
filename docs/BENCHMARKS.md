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

The tracked machine-readable summary for the clean audited 2026-04-23 local
state lives in [`docs/BENCHMARK_SUMMARY.json`](BENCHMARK_SUMMARY.json).

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
- the parent share at the exact global tree peak
- the later reporting-only peak and its phase

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
- `analysis/rss_frontier.py` adds diagnostics and `5 ms` process sampling.
  Use it for memory shape and driver attribution, not headline throughput.

## Current proof surface

Tracked current-local artefacts for this pass:

- `backtests/review_2026-04-23_final/runtime`
- `backtests/review_2026-04-23_final/storage`
- `backtests/review_2026-04-23_final/attribution`
- `backtests/review_2026-04-23_final/rss_frontier`
- `backtests/review_2026-04-23_final/backend`
- `backtests/review_2026-04-23_final/reference`
- `backtests/review_2026-04-23_final/architecture`

Important caveats:

- this clone does not retain a separate clean exact-same-worktree historical
  throughput baseline for the final diagnostics-only state
- the core runtime, storage, attribution, backend, reference and architecture
  artefacts were captured on clean commit `d041e8bc4e2b94b7fe0664330df142a88f174569`
- the `rss_frontier*` reruns were captured immediately after the
  parent-versus-reporting RSS wording fix, so they record `git_dirty: true`
  even though they target the same current review root
- the Chris Roberts comparison is same-machine and matched on a shared no-op
  trader plus tick budget, but it is not full semantic parity
- the shared-memory result is a transport microbenchmark only, not end-to-end
  Monte Carlo proof
- the previously tracked dirty-worktree `_final_*` artefacts are now retired
  and should not be used as current proof for this commit

## Current storage results

Measured on 2026-04-23 with
`backtests/review_2026-04-23_final/storage/benchmark_report.json`:

| Case | Size | Files | What it proves |
| --- | ---: | ---: | --- |
| `replay_light` | `1.36 MB` | `6` | Exact replay summary, fills and compact paths stay small enough for routine review. |
| `replay_full` | `1.99 MB` | `12` | Full replay adds raw orders and chart sidecars without a large footprint jump. |
| `mc_light` | `819.8 KB` | `6` | Light Monte Carlo keeps exact distribution metrics, all-session path bands and sampled previews in under `1 MB` on the tracked fixture. |
| `mc_full` | `5.16 MB` | `18` | Full Monte Carlo keeps the forensic extras, but the retained footprint is still moderate for the tracked fixture. |

## Current runtime result

Use `backtests/review_2026-04-23_final/runtime/benchmark_report.json` as the
current local headline runtime report for this pass.

| Case | Elapsed | Peak tree RSS | Output bytes | Files |
| --- | ---: | ---: | ---: | ---: |
| `replay_day0_light` | `2.917s` | `167.4 MB` | `21,148,107` | `6` |
| `compare_day0_light` | `2.207s` | `175.3 MB` | `11,993` | `3` |
| `pack_fast` | `5.203s` | `386.7 MB` | `21,771,578` | `17` |
| `pack_validation` | `17.646s` | `675.8 MB` | `61,822,838` | `17` |
| `mc_quick_light_w8` | `1.242s` | `344.0 MB` | `2,369,567` | `6` |
| `mc_default_light_w8` | `1.417s` | `351.3 MB` | `2,900,848` | `6` |
| `mc_heavy_light_w8` | `1.769s` | `368.1 MB` | `4,439,753` | `6` |
| `mc_ceiling_light_w8` | `3.435s` | `415.9 MB` | `6,645,872` | `6` |
| `mc_default_full_w1` | `3.089s` | `127.3 MB` | `25,175,621` | `122` |

For the tracked `250`-tick Monte Carlo fixture, the fresh current-local scaling
table is:

| Case | 1 worker | 2 workers | 4 workers | 8 workers |
| --- | ---: | ---: | ---: | ---: |
| MC quick light (64 sess) | `1.499s` | `1.366s` | `1.229s` | `1.242s` |
| MC default light (100 sess) | `1.943s` | `1.827s` | `1.432s` | `1.417s` |
| MC heavy light (192 sess) | `3.400s` | `n/a` | `n/a` | `1.769s` |
| MC ceiling light (768 sess) | `n/a` | `n/a` | `n/a` | `3.435s` |

The previously tracked dirty-worktree numbers were `37%` to `46%` slower on
the headline cases and are no longer representative of the current committed
tree.

## Harness vs direct CLI

Fresh direct CLI reruns on the same machine showed:

| Case | Harness | Direct mean | Band vs harness |
| --- | ---: | ---: | --- |
| `replay_day0_light` | `2.917s` | `2.705s` | `-7.3%` |
| `compare_day0_light` | `2.207s` | `2.239s` | `+1.4%` |
| `mc_default_light_w8` | `1.417s` | `1.361s` | `-4.0%` |
| `mc_ceiling_light_w8` | `3.435s` | `3.548s` | `+3.3%` |

That is close enough to treat the monitored harness as honest. The short
single-process replay case pays the largest monitor overhead, but it is still
inside a normal local noise band rather than a different timing mode.

## Current retained-output and reporting ownership

The fresh attribution pass is tracked in
`backtests/review_2026-04-23_final/attribution/bundle_attribution.json`.

For `mc_default_light_w8`:

- bundle bytes: `2,900,848`
- file count: `6`
- top dashboard owners:
  - `monteCarlo.sampleRuns`: `1,243,393`
  - `monteCarlo.pathBands`: `308,931`
  - `monteCarlo.sampleRuns.fills`: `283,252`
  - `monteCarlo.sampleRuns.orderIntent`: `257,141`
- top file owners:
  - `dashboard_payload`: `1,567,126`
  - `fills_csv`: `1,289,324`
- reporting-phase RSS:
  - before reporting: `93.0 MB`
  - sampled-row compaction peak: `111.3 MB`
  - dashboard build peak: `108.9 MB`
  - bundle write peak: `120.8 MB`

For `mc_ceiling_light_w8`:

- bundle bytes: `6,645,872`
- file count: `6`
- top dashboard owners:
  - `monteCarlo.sampleRuns`: `2,986,485`
  - `monteCarlo.sampleRuns.fills`: `680,250`
  - `monteCarlo.sampleRuns.orderIntent`: `616,955`
  - `monteCarlo.sampleRuns.fairValueSeries`: `534,751`
- top file owners:
  - `dashboard_payload`: `3,349,453`
  - `fills_csv`: `3,098,231`
- reporting-phase RSS:
  - sampled-row compaction peak: `279.6 MB`
  - dashboard build peak: `290.8 MB`
  - bundle write peak: `316.7 MB`

The retained-byte frontier is now narrow and explicit:

1. `monteCarlo.sampleRuns` preview series
2. `fills.csv`
3. the reporting path itself

`pathBands` are no longer a first-order retained-byte problem on the current
local evidence.

## Current execution RSS frontier

The fresh high-resolution ceiling probes are tracked in:

- `backtests/review_2026-04-23_final/rss_frontier`
- `backtests/review_2026-04-23_final/rss_frontier_rerun_1`
- `backtests/review_2026-04-23_final/rss_frontier_rerun_2`

Headline numbers for `mc_ceiling_light_w8`:

- runtime-suite tree peak with the coarser `20 ms` sampler: `415.9 MB`
- high-resolution `5 ms` tree peak reruns: `418.1 MB`, `421.0 MB`, `422.7 MB`
- peak phase on every rerun: `execution`
- workers alive at tree peak on every rerun: `8`
- live worker RSS at tree peak: `282.8 MB` to `289.6 MB`
- parent RSS at the tree peak: `128.4 MB` to `138.2 MB`
- later parent-only reporting peak: `269.8 MB` to `316.7 MB`, in `bundle_write`
- pre-reporting retained parent RSS: `188.8 MB` to `236.1 MB`
- reporting transient above the pre-reporting baseline: about `80.6 MB` to
  `81.0 MB`
- latest chunk before the peak:
  - payload pickle size: about `1.41 MB`
  - path-band accumulator pickle size: about `0.88 MB`
  - result count: `48`
  - sampled result count: `1`

That is the clearest current statement of the remaining memory frontier:

1. live worker processes dominate the global peak
2. the parent still contributes a meaningful `~128 MB` to `~138 MB` at that
   exact same moment
3. reporting is still material, but it happens later and does not set the
   global tree peak

## Realistic backend comparison

The fresh same-code realistic-trader rerun in
`backtests/review_2026-04-23_final/backend/backend_benchmark.json` kept the
backend story mixed but stable:

| Case | Streaming | Classic | Rust | Winner |
| --- | ---: | ---: | ---: | --- |
| `live_v9_default_w1` | `3.875s` | `4.093s` | `5.171s` | `streaming` |
| `live_v9_default_w8` | `1.748s` | `1.688s` | `2.281s` | `classic` |
| `live_v9_heavy_w8` | `2.156s` | `2.203s` | `2.721s` | `streaming` |
| `main_default_w8` | `1.458s` | `1.461s` | `1.891s` | `streaming` |
| `main_heavy_w8` | `1.854s` | `1.873s` | `2.459s` | `streaming` |
| `r2_stateful_default_w8` | `1.516s` | `1.481s` | `2.022s` | `classic` |
| `r2_stateful_heavy_w8` | `1.973s` | `1.968s` | `2.731s` | `classic` |

The honest current position is:

- `streaming` remains the design default and narrowly leads this rerun overall
- `classic` is a real parity and performance option, not a slower fallback
- `rust` stayed slower than both Python backends in every measured cell

## External reference result

Chris Roberts' repo remains the strongest narrow Monte Carlo reference that was
available locally in this pass.

The fresh same-machine rerun in
`backtests/review_2026-04-23_final/reference/reference_benchmark.json` used:

- one warm-up pass per repo
- the same shared no-op trader file in both repos
- matched `250` ticks per simulated day
- matched `100/10` and `1000/100` session or sample tiers
- matched `1`, `2`, `4` and `8` worker settings

Warm same-machine runtime results still favoured this repo in every measured
cell:

- default `100/10`: `3.78x` to `15.54x` faster
- ceiling `1000/100`: `9.46x` to `18.80x` faster

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
`backtests/review_2026-04-23_final/runtime/cases/mc_ceiling_light_w8/dashboard.json`,
`3,349,453` bytes on disk.

Results:

- MessagePack payload: `2,388,447` bytes versus `3,349,453` for compact JSON
- MessagePack encode: `0.0097s` versus JSON `0.0568s`
- MessagePack decode: `0.0104s` versus JSON `0.0413s`
- shared-memory transport: `0.351s` versus pickled transport `0.440s`

That keeps MessagePack alive as the only still-plausible contract-boundary
architecture move. Shared memory is no longer negative on the microbenchmark,
but the gain is still too small and too isolated to justify landing it without
an end-to-end win.
