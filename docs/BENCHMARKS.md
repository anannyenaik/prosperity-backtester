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

The tracked machine-readable summary for the audited 2026-04-22 run lives in
[`docs/BENCHMARK_SUMMARY.json`](BENCHMARK_SUMMARY.json).

## What the harness records

Runtime, storage, backend and reference reports now record:

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
- bundle-write and provenance timings
- non-engine overhead outside the measured engine wall

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

## Current storage results

Measured on 2026-04-22 with the default storage benchmark fixture:

| Case | Size | Files | What it proves |
| --- | ---: | ---: | --- |
| `replay_light` | `1.36 MB` | `6` | Exact replay summary, fills and compact paths remain small enough for routine review. |
| `replay_full` | `1.99 MB` | `12` | Full replay adds raw orders and chart sidecars without a large footprint jump. |
| `mc_light` | `1.95 MB` | `6` | Light Monte Carlo keeps exact final stats and all-session path bands while preview-capping sampled qualitative runs. |
| `mc_full` | `7.51 MB` | `18` | Full Monte Carlo adds sample-path files, session manifests and sidecars for forensic work. |

## Current runtime results

Measured on 2026-04-22 on:

- Windows 10
- Python 3.11
- 8 physical cores
- 16 logical CPUs
- 15.6 GB system memory

Representative current results:

| Case | Current | Peak RSS | Output bytes | Files | Notes |
| --- | ---: | ---: | ---: | ---: | --- |
| `replay_day0_light` | `2.176s` | `203.6 MB` | `21,148,069` | `6` | practical replay loop |
| `compare_day0_light` | `2.201s` | `187.5 MB` | `11,955` | `3` | practical compare loop |
| `pack_fast` | `4.718s` | `381.0 MB` | `22,851,777` | `17` | fast research pack |
| `pack_validation` | `15.510s` | `719.9 MB` | `65,000,459` | `17` | validation pack |
| `mc_quick_light_w8` | `1.193s` | `352.6 MB` | `4,760,035` | `6` | quickest wide-worker MC loop |
| `mc_default_light_w1` | `1.863s` | `112.9 MB` | `5,746,126` | `6` | best single-worker default MC |
| `mc_default_light_w8` | `1.345s` | `361.0 MB` | `5,746,122` | `6` | recommended default MC loop |
| `mc_heavy_light_w8` | `1.635s` | `378.1 MB` | `8,610,065` | `6` | heavier validation MC |
| `mc_ceiling_light_w8` | `3.182s` | `417.6 MB` | `13,453,231` | `6` | higher-scale ceiling case |
| `mc_default_full_w1` | `2.567s` | `148.1 MB` | `34,131,310` | `122` | full forensic baseline |
| `mc_default_full_trimmed_w1` | `2.171s` | `153.2 MB` | `21,062,986` | `12` | full profile with storage trims |

## Phase timing examples

The runtime harness splits engine work from reporting, provenance and shared
overhead.

Tracked examples:

- `mc_default_light_w1`
  reporting `0.207s`, non-engine overhead `0.382s`, provenance `0.108s`
- `mc_default_light_w8`
  reporting `0.232s`, non-engine overhead `0.416s`, provenance `0.118s`
- `mc_heavy_light_w8`
  reporting `0.304s`, non-engine overhead `0.401s`, provenance `0.105s`
- `mc_ceiling_light_w8`
  reporting `0.477s`, non-engine overhead `0.447s`, provenance `0.108s`

Dashboard build itself is only `7 ms` to `20 ms` in those rows. The remaining
tail is mostly bundle writing, sampled-row compaction and worker startup or
scheduling overhead.

## Realistic backend comparison

Same-code realistic-trader runs show that backend rankings are now
strategy-sensitive:

| Case | Streaming | Classic | Rust | Winner |
| --- | ---: | ---: | ---: | --- |
| `live_v9_default_w1` | `3.235s` | `3.344s` | `4.093s` | `streaming` |
| `live_v9_default_w8` | `1.490s` | `1.493s` | `1.950s` | `streaming` by `3 ms` |
| `live_v9_heavy_w8` | `2.021s` | `2.332s` | `2.992s` | `streaming` |
| `main_default_w8` | `1.454s` | `1.348s` | `1.692s` | `classic` |
| `main_heavy_w8` | `1.711s` | `1.887s` | `2.293s` | `streaming` |
| `r2_stateful_default_w8` | `1.494s` | `1.440s` | `1.794s` | `classic` |
| `r2_stateful_heavy_w8` | `1.754s` | `1.788s` | `2.388s` | `streaming` |

That is why the honest current position is:

- `streaming` remains the best overall default
- `classic` is a real parity option, not a purely slower fallback
- `rust` stayed slower in every realistic case rerun on 2026-04-22

## External reference note

Chris Roberts' repo remains the strongest narrow Monte Carlo reference that was
available locally in this pass.

The same-machine rerun used:

- one warm-up pass per repo
- the same no-op trader file in both repos
- matched `250` ticks per simulated day
- matched `100/10` and `1000/100` session or sample tiers
- matched `1`, `2`, `4`, and `8` worker or thread counts

Warm same-machine runtime results favoured this repo in every measured cell:

- default `100/10`: `4.34x` to `18.69x` faster
- ceiling `1000/100`: `11.36x` to `17.50x` faster

The output and memory story is more mixed:

- this repo used less RSS on the smaller `100/10` cases
- Chris kept the lighter RSS footprint on every `1000/100` ceiling case
- Chris kept the smaller retained output footprint in every rerun
- this repo used far fewer files, `5` instead of `50` or `410`

So the honest claim is a strong same-machine runtime-throughput lead and a much
cleaner retained file-count story, not a blanket all-axis performance crown.

## Architecture bake-off

The architecture bake-off used the real
`backtests/_phase5_runtime_current/cases/mc_ceiling_light_w8/dashboard.json`
payload, `10,157,359` bytes on disk.

Results:

- MessagePack payload: `8,393,320` bytes versus `10,157,359` for compact JSON
- MessagePack encode: `0.028s` versus JSON `0.127s`
- MessagePack decode: `0.048s` versus JSON `0.087s`
- Shared-memory transport: `0.336s` versus pickled transport `0.462s`
- Shared-memory transport speed-up: `1.375x`

That proves there is still real upside in binary serialisation and lower-copy
worker transport. It does not prove that an immediate worker-architecture
rewrite would dominate the current design across all important metrics.
