# Benchmarks

Use the benchmark helpers when you want reproducible evidence rather than
one-off timings.

`analysis/architecture_bakeoff.py` needs the optional `analysis` extra:

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
python analysis/benchmark_runtime.py --output-dir backtests/runtime_benchmark --compare-report path/to/previous/benchmark_report.json --workers 1 2 4 8 --warm-repeat 1
```

Bundle byte and RSS attribution:

```bash
python analysis/benchmark_attribution.py --runtime-report backtests/runtime_benchmark/benchmark_report.json --output-dir backtests/bundle_attribution
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
python analysis/architecture_bakeoff.py --output-dir backtests/architecture_bakeoff --bundle backtests/runtime_benchmark/cases/mc_ceiling_light_w8/dashboard.json
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

## Comparability notes

The benchmark suite is intentionally split by purpose.

- Replay, compare and research-pack cases use `strategies/trader.py`. These are
  the practical branch-loop timings.
- The tracked Monte Carlo runtime fixture uses `examples/benchmark_trader.py`
  with a `250`-tick synthetic cap. This keeps `1`, `2`, `4` and `8` worker
  runs local and reproducible.
- `analysis/benchmark_backends.py` is the same-code backend proof. It uses
  repo-tested realistic traders so backend rankings are not reduced to a no-op
  loop.
- `analysis/benchmark_chris_reference.py` is same-machine and same tick-budget,
  but it is not full semantic parity. Chris Roberts' repo has a different
  output contract and tutorial-round product scope.
- `analysis/architecture_bakeoff.py` isolates serialisation and worker-payload
  transport overhead only. It is not a full engine rewrite prototype.

## Current proof split

The current local evidence is intentionally separated into two buckets.

Fresh current-code reruns:

- `backtests/_final_local_output`
- `backtests/_final_local_runtime`
- `backtests/_final_local_attribution`
- `backtests/_final_local_backend`
- `backtests/_final_local_reference`
- `backtests/_final_local_architecture`

Historical same-code throughput baselines:

- `backtests/_baseline_runtime`
- `backtests/_final_runtime_current`

That split exists because the fresh full runtime rerun in
`backtests/_final_local_runtime` was clearly machine-contended. It reproduced
the same output bytes and the same RSS shape, but every wall-clock roughly
doubled together, so it is a correctness rerun rather than the cleanest
headline-throughput proof.

## Current storage results

Measured on 2026-04-22 with the fresh current-local storage rerun in
`backtests/_final_local_output`:

| Case | Size | Files | What it proves |
| --- | ---: | ---: | --- |
| `replay_light` | `1.36 MB` | `6` | Exact replay summary, fills and compact paths remain small enough for routine review. |
| `replay_full` | `1.99 MB` | `12` | Full replay adds raw orders and chart sidecars without a large footprint jump. |
| `mc_light` | `819.8 KB` | `6` | Light Monte Carlo keeps exact distribution metrics, all-session path bands and sampled previews in under `1 MB` on the tracked fixture. |
| `mc_full` | `5.16 MB` | `18` | Full Monte Carlo still carries forensic extras, but is materially smaller than the earlier audited baseline. |

Compared with the clean pre-change 2026-04-22 audit baseline:

- `mc_light`: `1.95 MB -> 819.8 KB` (`-57.9%`)
- `mc_full`: `7.51 MB -> 5.16 MB` (`-31.3%`)
- replay light and full stayed effectively unchanged

## Runtime result

Use the throughput numbers in `backtests/_baseline_runtime` and
`backtests/_final_runtime_current` as the least-contended same-code baseline.
Representative values from that cleaner baseline are:

| Case | Baseline | Peak RSS | Output bytes | Files |
| --- | ---: | ---: | ---: | ---: |
| `replay_day0_light` | `2.031s` | `185.5 MB` | `21,148,045` | `6` |
| `compare_day0_light` | `2.021s` | `187.2 MB` | `11,931` | `3` |
| `pack_fast` | `4.400s` | `380.7 MB` | `21,771,242` | `17` |
| `pack_validation` | `15.139s` | `728.5 MB` | `61,822,499` | `17` |
| `mc_quick_light_w8` | `1.194s` | `361.1 MB` | `2,369,509` | `6` |
| `mc_default_light_w8` | `1.214s` | `364.5 MB` | `2,900,783` | `6` |
| `mc_heavy_light_w8` | `1.499s` | `384.2 MB` | `4,439,696` | `6` |
| `mc_ceiling_light_w8` | `3.079s` | `424.2 MB` | `6,645,816` | `6` |

The fresh exact current-code rerun in `backtests/_final_local_runtime` kept the
same output bytes and the same RSS shape, but the machine was clearly slower
across the board:

- `mc_default_light_w8`: `2.708s`, `363.1 MB`, `2,900,797` bytes
- `mc_heavy_light_w8`: `3.822s`, `381.5 MB`, `4,439,705` bytes
- `mc_ceiling_light_w8`: `8.538s`, `431.5 MB`, `6,645,833` bytes
- `mc_default_full_w1`: `7.106s`, `138.0 MB`, `25,175,571` bytes

Treat that rerun as current-code validation, not as the cleanest throughput
headline.

## Current byte and RSS attribution

The fresh attribution pass is tracked in
`backtests/_final_local_attribution/bundle_attribution.json`.

For `mc_default_light_w8`:

- bundle bytes: `2,900,797`
- `dashboard.json`: `1,567,100`
- `fills.csv`: `1,289,324`
- top dashboard owners:
  - `monteCarlo.sampleRuns`: `1,243,393`
  - `monteCarlo.pathBands`: `308,931`
  - `monteCarlo.sampleRuns.fills`: `283,252`
  - `monteCarlo.sampleRuns.orderIntent`: `257,141`
- reporting-phase RSS:
  - sampled-row compaction: `+19.1 MB`, peak `117.0 MB`
  - dashboard build: `+4.7 MB`, peak `121.8 MB`
  - bundle write: `+6.3 MB`, peak `131.4 MB`

For `mc_ceiling_light_w8`:

- bundle bytes: `6,645,833`
- `dashboard.json`: `3,349,433`
- `fills.csv`: `3,098,231`
- top dashboard owners:
  - `monteCarlo.sampleRuns`: `2,986,485`
  - `monteCarlo.sampleRuns.fills`: `680,250`
  - `monteCarlo.sampleRuns.orderIntent`: `616,955`
  - `monteCarlo.sampleRuns.fairValueSeries`: `534,751`
- reporting-phase RSS:
  - before reporting: `252.2 MB`
  - sampled-row compaction: peak `273.9 MB`
  - dashboard build: peak `219.4 MB`
  - bundle write: peak `246.3 MB`

The fresh execution-phase probes in
`backtests/_final_rss_frontier_current` and
`backtests/_final_rss_process_breakdown_current` showed that the global ceiling
still lands before reporting starts. One high-resolution peak sample captured a
driver process at about `100.3 MB` plus eight live workers at about `35.7 MB`
to `39.9 MB` each.

That makes the current top three targets clear:

1. execution-phase process-tree RSS from the driver plus eight workers
2. `monteCarlo.sampleRuns` preview series
3. `fills.csv`

`pathBands` are no longer the first-order retained-byte problem after the new
compaction pass.

## Realistic backend comparison

The fresh same-code realistic-trader rerun in
`backtests/_final_local_backend/backend_benchmark.json` kept the backend story
mixed and credible:

| Case | Streaming | Classic | Rust | Winner |
| --- | ---: | ---: | ---: | --- |
| `live_v9_default_w1` | `7.684s` | `7.721s` | `10.824s` | `streaming` |
| `live_v9_default_w8` | `3.475s` | `3.541s` | `5.038s` | `streaming` |
| `live_v9_heavy_w8` | `5.231s` | `5.153s` | `6.405s` | `classic` |
| `main_default_w8` | `2.974s` | `3.040s` | `4.098s` | `streaming` |
| `main_heavy_w8` | `4.279s` | `4.148s` | `5.685s` | `classic` |
| `r2_stateful_default_w8` | `3.465s` | `3.115s` | `4.274s` | `classic` |
| `r2_stateful_heavy_w8` | `4.133s` | `3.920s` | `5.255s` | `classic` |

That is why the honest current position is:

- `streaming` remains the best overall default
- `classic` is still a real parity and sometimes faster realistic-trader path
- `rust` stayed slower in every realistic case rerun on the current local
  worktree

## External reference note

Chris Roberts' repo remains the strongest narrow Monte Carlo reference that was
available locally in this pass.

The fresh same-machine rerun in `backtests/_final_local_reference` used:

- one warm-up pass per repo
- the same shared no-op trader file in both repos
- matched `250` ticks per simulated day
- matched `100/10` and `1000/100` session or sample tiers
- matched `1`, `2`, `4` and `8` worker settings

Warm same-machine runtime results still favoured this repo in every measured
cell:

- default `100/10`: `4.43x` to `14.18x` faster
- ceiling `1000/100`: `10.69x` to `17.67x` faster

The retained-output story also held:

- this repo wrote fewer retained bytes in every measured same-machine no-op
  comparison cell
- this repo still used far fewer files, `5` instead of `50` or `410`
- Chris still kept the lighter RSS footprint on every `1000/100` ceiling case

So the honest external claim is:

- same-machine runtime-throughput lead: yes
- same-machine retained-byte lead on the matched no-op benchmark: yes
- same-machine retained file-count lead: yes
- ceiling-RSS lead: no

## Architecture bake-off

The fresh architecture bake-off used
`backtests/_final_local_runtime/cases/mc_ceiling_light_w8/dashboard.json`,
`3,349,433` bytes on disk.

Results:

- MessagePack payload: `2,388,425` bytes versus `3,349,433` for compact JSON
- MessagePack encode: `0.0171s` versus JSON `0.1073s`
- MessagePack decode: `0.0215s` versus JSON `0.0671s`
- shared-memory transport: `0.622s` versus pickled transport `0.590s`

That keeps MessagePack alive as the only still-plausible contract-boundary
architecture move. It also weakens the case for shared memory rather than
strengthening it.
