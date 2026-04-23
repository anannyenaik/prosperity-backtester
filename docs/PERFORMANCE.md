# Performance

Result: the fresh 2026-04-23 local proof still supports calling this repo the
strongest overall local Prosperity research platform. It still does not support
an all-axis performance crown, because wide-worker ceiling RSS remains behind
the strongest local external reference.

The current local proof root is `backtests/review_2026-04-23_head_refresh`.
The measured code state was clean commit
`eafb1e48828118334fbda391f4fec33099c39b42`.

## Proof status

Current proof artefacts:

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

Important limits:

- the measured code state is clean commit `eafb1e4...`; later docs-only cleanup
  does not change the measured engine code
- the monitored runtime suite includes process-tree sampling and one warm
  measured run per cell, so short-case throughput claims should be cross-checked
  against the direct CLI spot checks
- the WSL deployment-shape rerun wrote bundles back to `/mnt/d`, so replay and
  compare wall times there are not a clean Linux throughput claim
- the Chris Roberts comparison is same-machine and matched on a shared no-op
  trader plus tick budget, but it is not full semantic parity
- the shared-memory result is a transport microbenchmark only

## Runtime

Headline monitored warm timings from
`backtests/review_2026-04-23_head_refresh/runtime/benchmark_report.json`:

- day-0 replay: `2.800s`
- day-0 compare: `2.119s`
- fast pack: `5.317s`
- validation pack: `18.522s`
- default Monte Carlo light, `100/10`, `8` workers: `1.605s`
- heavy Monte Carlo light, `192/16`, `8` workers: `1.944s`
- ceiling Monte Carlo light, `768/24`, `8` workers: `3.664s`

Tracked Monte Carlo scaling on the `250`-tick fixture:

| Case | 1 worker | 2 workers | 4 workers | 8 workers |
| --- | ---: | ---: | ---: | ---: |
| MC quick light (`64/8`) | `1.622s` | `1.342s` | `1.420s` | `1.230s` |
| MC default light (`100/10`) | `1.977s` | `1.679s` | `1.507s` | `1.605s` |
| MC heavy light (`192/16`) | `3.720s` | `n/a` | `n/a` | `1.944s` |
| MC ceiling light (`768/24`) | `n/a` | `n/a` | `n/a` | `3.664s` |

## Harness sanity

The monitored harness is still useful, but it is no longer honest to present it
as a direct CLI equivalent on the shorter worker-pool Monte Carlo cells.

Fresh same-machine direct CLI reruns gave:

- `replay_day0_light`: harness `2.800s`, direct mean `2.726s`, `-2.6%`
- `compare_day0_light`: harness `2.119s`, direct mean `2.335s`, `+10.2%`
- `pack_fast`: harness `5.317s`, direct mean `5.637s`, `+6.0%`
- `pack_validation`: harness `18.522s`, direct mean `17.156s`, `-7.4%`
- `mc_default_light_w8`: harness `1.605s`, direct mean `1.346s`, `-16.1%`
- `mc_heavy_light_w8`: harness `1.944s`, direct mean `1.770s`, `-9.0%`
- `mc_ceiling_light_w8`: harness `3.664s`, direct mean `3.474s`, `-5.2%`

The precise reason is simple:

- `analysis/benchmark_runtime.py` measures a monitored run, not a bare CLI run
- it keeps process-tree sampling live during the measurement
- it records one warm measured run per cell rather than a direct multi-repeat
  mean

Use the monitored suite for regression tracking, RSS and phase accounting. Use
the direct CLI checks in the same review root for the final short-case
throughput headline.

## Retained output

Current retained-output sizes from
`backtests/review_2026-04-23_head_refresh/storage/benchmark_report.json`:

- replay light: `1.36 MB`, `6` files
- replay full: `1.99 MB`, `12` files
- Monte Carlo light: `819.9 KB`, `6` files
- Monte Carlo full: `5.16 MB`, `18` files

Retained-byte ownership in light Monte Carlo is still led by:

1. `monteCarlo.sampleRuns`
2. `fills.csv`
3. the reporting path itself

For `mc_default_light_w8`:

- dashboard payload: `1,567,139` bytes
- `fills.csv`: `1,289,324` bytes
- top dashboard owner: `monteCarlo.sampleRuns` at `1,243,393` bytes

For `mc_ceiling_light_w8`:

- dashboard payload: `3,349,470` bytes
- `fills.csv`: `3,098,231` bytes
- top dashboard owner: `monteCarlo.sampleRuns` at `2,986,485` bytes

That keeps retained-output efficiency in a strong place. The remaining storage
frontier is narrow and explicit, not a broad bundle bloat problem.

## Memory frontier

The clean runtime report and the high-resolution RSS probe still tell the same
overall story:

- runtime-suite tree peak on `mc_ceiling_light_w8`: `412.6 MB`
- `5 ms` RSS-frontier reruns: `399.2 MB`, `410.2 MB`, `410.6 MB`
- tree peak phase on every rerun: `execution`
- workers alive at tree peak on every rerun: `8`
- live worker RSS at tree peak: `266.9 MB` to `287.1 MB`
- parent RSS at tree peak: `123.6 MB` to `137.2 MB`
- later parent-only reporting peak: `233.3 MB` to `319.7 MB`, in `bundle_write`

The remaining ceiling story is still:

1. live worker processes dominate the global peak
2. the parent still contributes a meaningful `~124 MB` to `~137 MB` at that
   same moment
3. the later reporting spike is real, but it does not set the global tree peak

That is enough to reject the idea that the remaining problem is mainly
dashboard assembly.

## Deployment shape

Fresh same-code WSL reruns did reduce the wide-worker RSS shape:

- `mc_default_light_w8`: `355.0 MB` to `282.0 MB` runtime-suite tree RSS
- `mc_heavy_light_w8`: `369.8 MB` to `303.6 MB`
- `mc_ceiling_light_w8`: `412.6 MB` to `383.4 MB`

The high-resolution ceiling probe also stayed lower in WSL:

- Windows `5 ms` tree peak reruns: `399.2 MB` to `410.6 MB`
- WSL `5 ms` tree peak reruns: `393.9 MB` to `396.1 MB`

Replay and compare were slower in the WSL run from this pass because that Linux
checkout wrote bundles back to `/mnt/d`. So the honest deployment guidance is:

- keep native Windows as the normal day-to-day development default
- prefer Linux or WSL on the Linux filesystem for memory-sensitive wide-worker
  Monte Carlo runs

This does change deployment guidance. It does not change the architecture
decision, because the gain is still modest and the external ceiling-RSS gap
remains open.

## Backend choice

Current realistic-trader backend rerun from
`backtests/review_2026-04-23_head_refresh/backend/backend_benchmark.json`:

- `streaming` won `5` of `7` measured cells
- `classic` won `2` of `7`
- `rust` won `0`

Current honest guidance:

- keep `streaming` as the design default and `auto` target
- keep `classic` as a co-equal parity and performance backend
- keep `rust` explicit and experimental only

## External reference

Current same-machine Chris Roberts rerun from
`backtests/review_2026-04-23_head_refresh/reference/reference_benchmark.json`:

- default `100/10`: `4.06x` to `15.68x` faster
- ceiling `1000/100`: `9.06x` to `16.54x` faster
- smaller retained bytes in every measured cell
- fewer retained files in every measured cell

What still loses:

- RSS on every `1000/100` ceiling case

So the repo still wins throughput, retained bytes and retained file count on
the matched same-machine test, but not ceiling RSS.

## Architecture direction

The fresh bake-off kept the same overall answer:

- MessagePack remains materially smaller and faster at the contract boundary
- shared memory was only a `1.069x` transport-only win
- neither result addresses the actual end-to-end ceiling-RSS frontier

That keeps the best current architecture as:

- Python backend
- `streaming` default
- `classic` co-equal option
- JSON canonical contract
- no binary sidecars landed
- no shared-memory transport landed
- no deeper native path justified yet

## Honest verdict

Current honest scorecard:

- runtime throughput: very strong
- retained-output efficiency: very strong
- trust and proof cleanliness: stronger now that the docs match the fresh local
  reruns and the harness caveat is explicit
- deployment and workflow sanity: stronger, with explicit Windows versus Linux
  guidance for the remaining memory frontier
- memory efficiency: not yet 10/10, because wide-worker ceiling RSS still
  trails the best local reference

The repo is ready to claim the strongest overall local research platform on the
current local evidence. It is not ready to claim the best performance on every
important axis.
