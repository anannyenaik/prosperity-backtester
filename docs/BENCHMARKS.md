# Benchmarks

Use the analysis helpers when you want reproducible evidence rather than
one-off timings.

Install the optional analysis extra first:

```bash
python -m pip install -e ".[analysis]"
```

## Benchmark tools

Storage footprint:

```bash
python analysis/benchmark_outputs.py --output-dir backtests/output_benchmark
```

Monitored runtime suite:

```bash
python analysis/benchmark_runtime.py --output-dir backtests/runtime_benchmark --workers 1 2 4 8 --warm-repeat 1
```

Direct CLI cross-check for the short-case throughput headline:

```bash
python analysis/benchmark_direct_cli.py --runtime-report backtests/runtime_benchmark/benchmark_report.json --output-dir backtests/direct_cli_checks --repeats 3
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

Same-machine Chris Roberts reference comparison, if the exact local repo is
available:

```bash
python analysis/benchmark_chris_reference.py --reference-root path/to/imc-prosperity-4/backtester --output-dir backtests/reference_benchmark
```

Architecture bake-off on a real dashboard payload:

```bash
python analysis/architecture_bakeoff.py --output-dir backtests/architecture_bakeoff --bundle backtests/runtime_benchmark/cases/mc_ceiling_light_w8/dashboard.json --workers 8 --tasks 32 --repeats 3
```

The tracked machine-readable summary for this pass lives in
[`docs/BENCHMARK_SUMMARY.json`](BENCHMARK_SUMMARY.json).

## Comparability notes

- Replay, compare and research-pack cases use `strategies/trader.py`. These are
  the practical branch-loop timings.
- The tracked Monte Carlo runtime fixture uses `examples/benchmark_trader.py`
  with a `250`-tick synthetic cap so `1`, `2`, `4` and `8` worker runs stay
  local and reproducible.
- `analysis/benchmark_runtime.py` measures a monitored run, not a bare CLI run.
  Use `analysis/benchmark_direct_cli.py` for the final short-case throughput
  headline.
- `analysis/benchmark_backends.py` is the realistic same-code backend proof.
- `analysis/rss_frontier.py` adds `5 ms` process sampling and diagnostics. Use
  it for memory shape and driver attribution, not the headline throughput
  number.
- `analysis/architecture_bakeoff.py` isolates serialisation and transport
  overhead only. It is not a full engine rewrite prototype.
- The archived Chris Roberts comparison is same-machine and matched on a shared
  no-op trader plus tick budget, but it is not full semantic parity.

## Current proof surface

Fresh current-local artefacts for this pass:

- `backtests/review_2026-04-23_final_pass/runtime`
- `backtests/review_2026-04-23_final_pass/direct_cli_checks`
- `backtests/review_2026-04-23_final_pass/storage`
- `backtests/review_2026-04-23_final_pass/attribution`
- `backtests/review_2026-04-23_final_pass/rss_frontier`
- `backtests/review_2026-04-23_final_pass/rss_frontier_rerun_1`
- `backtests/review_2026-04-23_final_pass/rss_frontier_rerun_2`
- `backtests/review_2026-04-23_final_pass/backend`
- `backtests/review_2026-04-23_final_pass/architecture`
- `backtests/review_2026-04-23_final_pass/wsl_runtime`
- `backtests/review_2026-04-23_final_pass/wsl_rss_frontier`
- `backtests/review_2026-04-23_final_pass/wsl_rss_frontier_rerun_1`
- `backtests/review_2026-04-23_final_pass/wsl_rss_frontier_rerun_2`

Preserved historical external reference evidence:

- `backtests/audited_baseline_2026-04-23_eafb1e4/reference/reference_benchmark.json`

Important caveats:

- The fresh Windows reruns record `git_dirty: true` because the new direct CLI
  helper and its test registration were already present. The replay, Monte
  Carlo, reporting and dashboard runtime code paths still matched `HEAD`
  `b3f9534a815993867160f7ba247ff5957fb032f4`.
- The WSL reruns were taken from a synced Linux-filesystem checkout whose Git
  metadata remained on `eafb1e4...`, so they also record `git_dirty: true`.
- WSL tree RSS is still a summed RSS measure. Fork-shared pages can inflate the
  pack-level totals, so use the targeted Monte Carlo cells and the `5 ms`
  frontier probes for the cleanest cross-environment memory reading.
- A fresh same-machine Chris rerun was not possible in this session because the
  exact local repo path from the earlier audited run was no longer present.

## Current storage results

Measured with
`backtests/review_2026-04-23_final_pass/storage/benchmark_report.json`:

| Case | Size | Files | What it proves |
| --- | ---: | ---: | --- |
| `replay_light` | `1.36 MB` | `6` | Exact replay summary, fills and compact paths stay small enough for routine review. |
| `replay_full` | `1.99 MB` | `12` | Full replay adds raw orders and chart sidecars without a large footprint jump. |
| `mc_light` | `819.9 KB` | `6` | Light Monte Carlo keeps exact distribution metrics, all-session path bands and sampled previews under `1 MB` on the tracked fixture. |
| `mc_full` | `5.16 MB` | `18` | Full Monte Carlo keeps the forensic extras, but the retained footprint is still moderate for the tracked fixture. |

## Current runtime result

Use `backtests/review_2026-04-23_final_pass/runtime/benchmark_report.json` as
the current local monitored runtime report for this pass.

| Case | Elapsed | Peak tree RSS | Output bytes | Files |
| --- | ---: | ---: | ---: | ---: |
| `replay_day0_light` | `2.882s` | `162.8 MB` | `21,148,125` | `6` |
| `compare_day0_light` | `2.386s` | `174.2 MB` | `12,011` | `3` |
| `pack_fast` | `5.530s` | `383.2 MB` | `21,771,681` | `17` |
| `pack_validation` | `17.931s` | `728.4 MB` | `61,822,936` | `17` |
| `mc_quick_light_w8` | `1.252s` | `348.5 MB` | `2,369,584` | `6` |
| `mc_default_light_w8` | `1.355s` | `356.1 MB` | `2,900,861` | `6` |
| `mc_heavy_light_w8` | `2.023s` | `371.5 MB` | `4,439,778` | `6` |
| `mc_ceiling_light_w8` | `3.372s` | `418.2 MB` | `6,645,898` | `6` |
| `mc_default_full_w1` | `3.112s` | `130.8 MB` | `25,175,645` | `122` |

Tracked Monte Carlo scaling on the `250`-tick fixture:

| Case | 1 worker | 2 workers | 4 workers | 8 workers |
| --- | ---: | ---: | ---: | ---: |
| MC quick light (`64/8`) | `1.533s` | `1.439s` | `1.325s` | `1.252s` |
| MC default light (`100/10`) | `2.096s` | `1.854s` | `1.448s` | `1.355s` |
| MC heavy light (`192/16`) | `3.580s` | `n/a` | `n/a` | `2.023s` |
| MC ceiling light (`768/24`) | `n/a` | `n/a` | `n/a` | `3.372s` |

## Harness vs direct CLI

Fresh direct CLI reruns from
`backtests/review_2026-04-23_final_pass/direct_cli_checks/direct_cli_summary.json`
showed:

| Case | Harness | Direct mean | Band vs harness |
| --- | ---: | ---: | --- |
| `replay_day0_light` | `2.882s` | `2.600s` | `-9.8%` |
| `compare_day0_light` | `2.386s` | `2.252s` | `-5.6%` |
| `pack_fast` | `5.530s` | `5.235s` | `-5.3%` |
| `pack_validation` | `17.931s` | `16.238s` | `-9.4%` |
| `mc_default_light_w8` | `1.355s` | `1.323s` | `-2.4%` |
| `mc_heavy_light_w8` | `2.023s` | `1.702s` | `-15.9%` |
| `mc_ceiling_light_w8` | `3.372s` | `3.150s` | `-6.6%` |

The monitored harness remains the right source for RSS and phase accounting.
The new `analysis/benchmark_direct_cli.py` helper now makes the throughput
cross-check reproducible rather than ad hoc.

## Current retained-output and reporting ownership

The fresh attribution pass is tracked in
`backtests/review_2026-04-23_final_pass/attribution/bundle_attribution.json`.

For `mc_default_light_w8`:

- bundle bytes: `2,900,861`
- file count: `6`
- top dashboard owners:
  - `monteCarlo.sampleRuns`: `1,243,393`
  - `monteCarlo.pathBands`: `308,931`
  - `monteCarlo.sampleRuns.fills`: `283,252`
- top file owners:
  - `dashboard_payload`: `1,567,133`
  - `fills_csv`: `1,289,324`

For `mc_ceiling_light_w8`:

- bundle bytes: `6,645,898`
- file count: `6`
- top dashboard owners:
  - `monteCarlo.sampleRuns`: `2,986,485`
  - `monteCarlo.sampleRuns.fills`: `680,250`
  - `monteCarlo.sampleRuns.orderIntent`: `616,955`
  - `monteCarlo.sampleRuns.fairValueSeries`: `534,751`
- top file owners:
  - `dashboard_payload`: `3,349,466`
  - `fills_csv`: `3,098,231`

The retained-byte frontier remains narrow and explicit:

1. `monteCarlo.sampleRuns`
2. `fills.csv`
3. reporting-path write pressure

## Current execution RSS frontier

Windows `5 ms` ceiling probes are tracked in:

- `backtests/review_2026-04-23_final_pass/rss_frontier`
- `backtests/review_2026-04-23_final_pass/rss_frontier_rerun_1`
- `backtests/review_2026-04-23_final_pass/rss_frontier_rerun_2`

Headline numbers for `mc_ceiling_light_w8`:

- runtime-suite tree peak with the coarser `20 ms` sampler: `418.2 MB`
- `5 ms` tree peak reruns: `413.8 MB`, `416.9 MB`, `421.1 MB`
- tree peak phase on every rerun: `execution`
- workers alive at tree peak on every rerun: `8`
- live worker RSS at tree peak: `294.4 MB` to `301.6 MB` total
- parent RSS at tree peak: `131.7 MB` to `136.2 MB`
- later parent-only reporting peak: `233.7 MB` to `316.9 MB`, in `bundle_write`

The remaining ceiling story is still:

1. live worker processes dominate the global peak
2. the parent still contributes a meaningful share at that same moment
3. the later reporting spike is real, but it does not set the global tree peak

## Deployment shape

Current WSL runtime report:

- `backtests/review_2026-04-23_final_pass/wsl_runtime`

Current WSL frontier probes:

- `backtests/review_2026-04-23_final_pass/wsl_rss_frontier`
- `backtests/review_2026-04-23_final_pass/wsl_rss_frontier_rerun_1`
- `backtests/review_2026-04-23_final_pass/wsl_rss_frontier_rerun_2`

Using a Linux-filesystem WSL checkout materially improved the measured
wide-worker Monte Carlo cases:

- `mc_default_light_w8`: `356.1 MB` to `277.4 MB` runtime-suite tree RSS
- `mc_heavy_light_w8`: `371.5 MB` to `305.4 MB`
- `mc_ceiling_light_w8`: `418.2 MB` to `378.0 MB`

The `5 ms` frontier probes also stayed lower:

- Windows tree peak reruns: `413.8 MB` to `421.1 MB`
- WSL tree peak reruns: `390.7 MB` to `391.4 MB`

WSL on the Linux filesystem was also faster on this machine:

- replay day `0`: `2.882s` to `1.997s`
- compare day `0`: `2.386s` to `1.899s`
- `mc_default_light_w8`: `1.355s` to `0.675s`
- `mc_heavy_light_w8`: `2.023s` to `1.202s`
- `mc_ceiling_light_w8`: `3.372s` to `2.853s`

Important caveat:

- the WSL pack-level tree RSS totals are not clean cross-environment memory
  proof because summed Linux RSS overcounts fork-shared pages

The honest deployment guidance is now:

- native Windows remains a good day-to-day development default
- prefer Linux or WSL from a Linux filesystem checkout for
  performance-sensitive or memory-sensitive wide-worker Monte Carlo work

## Backend result

The fresh realistic-trader backend rerun from
`backtests/review_2026-04-23_final_pass/backend/backend_benchmark.json` kept
the same overall answer:

- `streaming` won `5` of `7` measured cells
- `classic` won `2`
- `rust` won `0`

Current honest guidance:

- keep `streaming` as the design default and `auto` target
- keep `classic` as a co-equal parity and performance backend
- keep `rust` explicit and experimental only

## External reference status

A fresh same-machine Chris rerun was not available in this session because the
exact local repo path from the earlier audited run was gone.

The preserved audited report remains:

- `backtests/audited_baseline_2026-04-23_eafb1e4/reference/reference_benchmark.json`

That historical same-machine report still showed:

- default `100/10`: `4.06x` to `15.68x` faster
- ceiling `1000/100`: `9.06x` to `16.54x` faster
- smaller retained bytes in every measured cell
- fewer retained files in every measured cell
- lower RSS on every smaller default `100/10` case
- higher RSS on every `1000/100` ceiling case

Treat that as preserved audited evidence, not fresh-current proof.

## Architecture direction

The fresh bake-off from
`backtests/review_2026-04-23_final_pass/architecture/architecture_bakeoff.json`
still points to the same architecture answer:

- JSON size: `3,349,466` bytes
- MessagePack size: `2,388,457` bytes
- JSON encode/decode: `0.0564s` / `0.0409s`
- MessagePack encode/decode: `0.0092s` / `0.0105s`
- pickle transport: `0.463s`
- shared-memory transport: `0.353s`
- shared-memory speed-up: `1.31x`

That is a stronger transport microbenchmark than the earlier audited run, but
it is still transport-only evidence. It does not close the actual
execution-phase ceiling-RSS frontier, so the architecture guidance remains:

- Python backend
- `streaming` default
- `classic` co-equal option
- JSON canonical contract
- no binary sidecars landed
- no shared-memory transport landed
- no deeper native path justified yet
