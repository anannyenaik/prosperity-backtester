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

The tracked machine-readable summary for the fresh current local proof lives in
[`docs/BENCHMARK_SUMMARY.json`](BENCHMARK_SUMMARY.json).

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
- `analysis/benchmark_runtime.py` measures a monitored run, not a bare CLI run.
  Use the direct CLI reruns in the same review root for the final short-case
  throughput headline.

## Current proof surface

Tracked current-local artefacts for this pass:

- `backtests/review_2026-04-23_head_refresh/runtime`
- `backtests/review_2026-04-23_head_refresh/direct_cli_checks`
- `backtests/review_2026-04-23_head_refresh/storage`
- `backtests/review_2026-04-23_head_refresh/attribution`
- `backtests/review_2026-04-23_head_refresh/rss_frontier`
- `backtests/review_2026-04-23_head_refresh/backend`
- `backtests/review_2026-04-23_head_refresh/reference`
- `backtests/review_2026-04-23_head_refresh/architecture`
- `backtests/review_2026-04-23_head_refresh/wsl_runtime`
- `backtests/review_2026-04-23_head_refresh/wsl_rss_frontier`

Important caveats:

- the measured code state was clean commit `eafb1e4...`; later docs-only
  cleanup does not change the measured engine code
- the runtime harness includes process-tree sampling and one warm measured run
  per cell, so short-case throughput claims should be cross-checked against the
  direct CLI reruns
- the WSL rerun wrote bundles back to `/mnt/d`, so replay and compare wall
  times there are deployment-shape evidence rather than unconditional Linux
  throughput proof
- the Chris Roberts comparison is same-machine and matched on a shared no-op
  trader plus tick budget, but it is not full semantic parity
- the shared-memory result is a transport microbenchmark only

## Current storage results

Measured with
`backtests/review_2026-04-23_head_refresh/storage/benchmark_report.json`:

| Case | Size | Files | What it proves |
| --- | ---: | ---: | --- |
| `replay_light` | `1.36 MB` | `6` | Exact replay summary, fills and compact paths stay small enough for routine review. |
| `replay_full` | `1.99 MB` | `12` | Full replay adds raw orders and chart sidecars without a large footprint jump. |
| `mc_light` | `819.9 KB` | `6` | Light Monte Carlo keeps exact distribution metrics, all-session path bands and sampled previews under `1 MB` on the tracked fixture. |
| `mc_full` | `5.16 MB` | `18` | Full Monte Carlo keeps the forensic extras, but the retained footprint is still moderate for the tracked fixture. |

## Current runtime result

Use `backtests/review_2026-04-23_head_refresh/runtime/benchmark_report.json` as
the current local monitored runtime report for this pass.

| Case | Elapsed | Peak tree RSS | Output bytes | Files |
| --- | ---: | ---: | ---: | ---: |
| `replay_day0_light` | `2.800s` | `160.0 MB` | `21,148,139` | `6` |
| `compare_day0_light` | `2.119s` | `176.6 MB` | `12,025` | `3` |
| `pack_fast` | `5.317s` | `383.8 MB` | `21,771,755` | `17` |
| `pack_validation` | `18.522s` | `713.6 MB` | `61,823,007` | `17` |
| `mc_quick_light_w8` | `1.230s` | `345.8 MB` | `2,369,597` | `6` |
| `mc_default_light_w8` | `1.605s` | `355.0 MB` | `2,900,874` | `6` |
| `mc_heavy_light_w8` | `1.944s` | `369.8 MB` | `4,439,792` | `6` |
| `mc_ceiling_light_w8` | `3.664s` | `412.6 MB` | `6,645,906` | `6` |
| `mc_default_full_w1` | `3.390s` | `127.7 MB` | `25,175,659` | `122` |

For the tracked `250`-tick Monte Carlo fixture, the fresh scaling table is:

| Case | 1 worker | 2 workers | 4 workers | 8 workers |
| --- | ---: | ---: | ---: | ---: |
| MC quick light (64 sess) | `1.622s` | `1.342s` | `1.420s` | `1.230s` |
| MC default light (100 sess) | `1.977s` | `1.679s` | `1.507s` | `1.605s` |
| MC heavy light (192 sess) | `3.720s` | `n/a` | `n/a` | `1.944s` |
| MC ceiling light (768 sess) | `n/a` | `n/a` | `n/a` | `3.664s` |

## Harness vs direct CLI

Fresh direct CLI reruns on the same machine showed:

| Case | Harness | Direct mean | Band vs harness |
| --- | ---: | ---: | --- |
| `replay_day0_light` | `2.800s` | `2.726s` | `-2.6%` |
| `compare_day0_light` | `2.119s` | `2.335s` | `+10.2%` |
| `pack_fast` | `5.317s` | `5.637s` | `+6.0%` |
| `pack_validation` | `18.522s` | `17.156s` | `-7.4%` |
| `mc_default_light_w8` | `1.605s` | `1.346s` | `-16.1%` |
| `mc_heavy_light_w8` | `1.944s` | `1.770s` | `-9.0%` |
| `mc_ceiling_light_w8` | `3.664s` | `3.474s` | `-5.2%` |

The monitored harness is still good for RSS and regression tracking. It is not
honest to present it as a direct CLI equivalent for the short worker-pool Monte
Carlo cells on this machine.

## Current retained-output and reporting ownership

The fresh attribution pass is tracked in
`backtests/review_2026-04-23_head_refresh/attribution/bundle_attribution.json`.

For `mc_default_light_w8`:

- bundle bytes: `2,900,874`
- file count: `6`
- top dashboard owners:
  - `monteCarlo.sampleRuns`: `1,243,393`
  - `monteCarlo.pathBands`: `308,931`
  - `monteCarlo.sampleRuns.fills`: `283,252`
  - `monteCarlo.sampleRuns.orderIntent`: `257,141`
- top file owners:
  - `dashboard_payload`: `1,567,139`
  - `fills_csv`: `1,289,324`
- reporting-phase RSS:
  - before reporting: `93.4 MB`
  - sampled-row compaction peak: `104.7 MB`
  - dashboard build peak: `109.2 MB`
  - bundle write peak: `121.0 MB`

For `mc_ceiling_light_w8`:

- bundle bytes: `6,645,906`
- file count: `6`
- top dashboard owners:
  - `monteCarlo.sampleRuns`: `2,986,485`
  - `monteCarlo.sampleRuns.fills`: `680,250`
  - `monteCarlo.sampleRuns.orderIntent`: `616,955`
  - `monteCarlo.sampleRuns.fairValueSeries`: `534,751`
- top file owners:
  - `dashboard_payload`: `3,349,470`
  - `fills_csv`: `3,098,231`
- reporting-phase RSS:
  - before reporting: `237.6 MB`
  - sampled-row compaction peak: `281.4 MB`
  - dashboard build peak: `292.5 MB`
  - bundle write peak: `318.2 MB`

The retained-byte frontier is now narrow and explicit:

1. `monteCarlo.sampleRuns`
2. `fills.csv`
3. the reporting path itself

## Current execution RSS frontier

The fresh high-resolution ceiling probes are tracked in:

- `backtests/review_2026-04-23_head_refresh/rss_frontier`
- `backtests/review_2026-04-23_head_refresh/rss_frontier_rerun_1`
- `backtests/review_2026-04-23_head_refresh/rss_frontier_rerun_2`

Headline numbers for `mc_ceiling_light_w8`:

- runtime-suite tree peak with the coarser `20 ms` sampler: `412.6 MB`
- high-resolution `5 ms` tree peak reruns: `399.2 MB`, `410.2 MB`, `410.6 MB`
- peak phase on every rerun: `execution`
- workers alive at tree peak on every rerun: `8`
- live worker RSS at tree peak: `266.9 MB` to `287.1 MB`
- parent RSS at tree peak: `123.6 MB` to `137.2 MB`
- later parent-only reporting peak: `233.3 MB` to `319.7 MB`, in `bundle_write`
- latest chunk before the peak:
  - payload pickle size: about `1.41 MB`
  - path-band accumulator pickle size: about `0.88 MB`
  - result count: `48`
  - sampled result count: `1`

That is still the clearest current statement of the remaining memory frontier:

1. live worker processes dominate the global peak
2. the parent still contributes a meaningful `~124 MB` to `~137 MB` at that
   exact same moment
3. later reporting pressure is real, but it does not set the global tree peak

## Deployment shape

The fresh Linux or WSL deployment-shape rerun is tracked in:

- `backtests/review_2026-04-23_head_refresh/wsl_runtime`
- `backtests/review_2026-04-23_head_refresh/wsl_rss_frontier`
- `backtests/review_2026-04-23_head_refresh/wsl_rss_frontier_rerun_1`
- `backtests/review_2026-04-23_head_refresh/wsl_rss_frontier_rerun_2`

What changed under WSL:

- `mc_default_light_w8`: `355.0 MB` to `282.0 MB` runtime-suite tree RSS
- `mc_heavy_light_w8`: `369.8 MB` to `303.6 MB`
- `mc_ceiling_light_w8`: `412.6 MB` to `383.4 MB`
- WSL `5 ms` tree peak reruns: `393.9 MB`, `394.4 MB`, `396.1 MB`

What did not change enough:

- the global peak stayed execution-phase tree RSS
- the external ceiling-RSS gap remained open

What is not a clean throughput claim:

- replay and compare were slower in the WSL run because that Linux checkout
  wrote bundles back to `/mnt/d`

That changes deployment guidance, not the default architecture:

- native Windows remains fine for normal day-to-day work
- Linux or WSL on the Linux filesystem is the preferred environment for
  memory-sensitive wide-worker Monte Carlo studies

## Current backend result

The fresh realistic-trader backend rerun from
`backtests/review_2026-04-23_head_refresh/backend/backend_benchmark.json` kept
the default answer alive more clearly:

- `streaming` won `5` of `7` measured cells
- `classic` won `2` of `7`
- `rust` won `0`

## Current external reference result

The same-machine Chris Roberts rerun from
`backtests/review_2026-04-23_head_refresh/reference/reference_benchmark.json`
used a shared no-op trader plus matched `250`-tick `100/10` and `1000/100`
tiers.

Headline result:

- default `100/10`: `4.06x` to `15.68x` faster
- ceiling `1000/100`: `9.06x` to `16.54x` faster
- smaller retained bytes in every measured cell
- fewer retained files in every measured cell
- lower RSS on every default `100/10` case
- still higher RSS on every `1000/100` ceiling case

## Current architecture result

The fresh architecture bake-off from
`backtests/review_2026-04-23_head_refresh/architecture/architecture_bakeoff.json`
kept the same conclusion:

- JSON size: `3,349,470` bytes
- MessagePack size: `2,388,463` bytes
- JSON encode: `0.053724s`
- MessagePack encode: `0.008493s`
- JSON decode: `0.037129s`
- MessagePack decode: `0.008908s`
- pickle transport: `0.359s`
- shared-memory transport: `0.336s`
- shared-memory speed-up: only `1.069x`

MessagePack remains the only still-plausible contract-boundary move if bundle
load or retained bytes become the next real user problem. Shared memory is
still too weak to justify landing as the answer to the current frontier.
