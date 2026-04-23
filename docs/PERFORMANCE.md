# Performance

Result: the audited 2026-04-23 proof still supports calling this repo the
strongest overall local Prosperity research platform. It does not yet support
an all-axis performance crown, because wide-worker ceiling RSS still loses to
the strongest local external reference.

The core runtime, storage, attribution, backend, reference and architecture
artefacts in `backtests/review_2026-04-23_final` were captured on clean commit
`d041e8bc4e2b94b7fe0664330df142a88f174569`. The three `rss_frontier*` reruns
were captured immediately after the RSS attribution wording fix and therefore
record `git_dirty: true`.

## Proof status

Current proof artefacts:

- `backtests/review_2026-04-23_final/runtime`
- `backtests/review_2026-04-23_final/storage`
- `backtests/review_2026-04-23_final/attribution`
- `backtests/review_2026-04-23_final/rss_frontier`
- `backtests/review_2026-04-23_final/backend`
- `backtests/review_2026-04-23_final/reference`
- `backtests/review_2026-04-23_final/architecture`

Important limits:

- this clone still does not retain a clean exact-same-worktree historical
  baseline for the final diagnostics state
- the `rss_frontier*` reruns were taken after an analysis-layer reporting fix,
  so they should be read as current memory-shape proof rather than clean-tree
  headline throughput proof
- the Chris Roberts comparison is same-machine and matched on a shared no-op
  trader plus tick budget, but it is not full semantic parity
- the shared-memory result is a transport microbenchmark only

## Runtime

Headline current-local warm timings from
`backtests/review_2026-04-23_final/runtime/benchmark_report.json`:

- day-0 replay: `2.917s`
- day-0 compare: `2.207s`
- fast pack: `5.203s`
- validation pack: `17.646s`
- default Monte Carlo light, `100/10`, `8` workers: `1.417s`
- heavy Monte Carlo light, `192/16`, `8` workers: `1.769s`
- ceiling Monte Carlo light, `768/24`, `8` workers: `3.435s`

Tracked Monte Carlo scaling on the `250`-tick fixture:

| Case | 1 worker | 2 workers | 4 workers | 8 workers |
| --- | ---: | ---: | ---: | ---: |
| MC quick light (`64/8`) | `1.499s` | `1.366s` | `1.229s` | `1.242s` |
| MC default light (`100/10`) | `1.943s` | `1.827s` | `1.432s` | `1.417s` |
| MC heavy light (`192/16`) | `3.400s` | `n/a` | `n/a` | `1.769s` |
| MC ceiling light (`768/24`) | `n/a` | `n/a` | `n/a` | `3.435s` |

The previously tracked dirty-worktree timings are now retired. They were
`37%` to `46%` slower than the clean audited run on the headline cases and no
longer represent the current committed tree.

## Harness sanity check

The monitored runtime harness is not materially overstating or understating the
headline CLI timings.

Fresh direct CLI reruns on the same machine gave:

- `replay_day0_light`: harness `2.917s`, direct mean `2.705s`, `-7.3%`
- `compare_day0_light`: harness `2.207s`, direct mean `2.239s`, `+1.4%`
- `mc_default_light_w8`: harness `1.417s`, direct mean `1.361s`, `-4.0%`
- `mc_ceiling_light_w8`: harness `3.435s`, direct mean `3.548s`, `+3.3%`

That sits inside a normal local rerun and monitor-overhead band, not a separate
timing mode that would mislead readers.

## Retained output

Current retained-output sizes from
`backtests/review_2026-04-23_final/storage/benchmark_report.json`:

- replay light: `1.36 MB`, `6` files
- replay full: `1.99 MB`, `12` files
- Monte Carlo light: `819.8 KB`, `6` files
- Monte Carlo full: `5.16 MB`, `18` files

Retained-byte ownership in light Monte Carlo remains led by:

1. `monteCarlo.sampleRuns`
2. `fills.csv`
3. the reporting path itself

For `mc_default_light_w8`:

- dashboard payload: `1,567,126` bytes
- `fills.csv`: `1,289,324` bytes
- top dashboard owner: `monteCarlo.sampleRuns` at `1,243,393` bytes

For `mc_ceiling_light_w8`:

- dashboard payload: `3,349,453` bytes
- `fills.csv`: `3,098,231` bytes
- top dashboard owner: `monteCarlo.sampleRuns` at `2,986,485` bytes

That means the retained-byte frontier is narrow. It is no longer honest to
describe `pathBands` as the dominant storage problem.

## Memory frontier

The clean runtime report and the high-resolution RSS probe now tell a consistent
story:

- runtime suite tree peak on `mc_ceiling_light_w8`: `415.9 MB`
- `5 ms` RSS-frontier reruns: `418.1 MB`, `421.0 MB`, `422.7 MB`
- tree peak phase on every rerun: `execution`
- workers alive at tree peak on every rerun: `8`
- live worker RSS at tree peak: `282.8 MB` to `289.6 MB`
- parent RSS at tree peak: `128.4 MB` to `138.2 MB`
- later parent-only reporting peak: `269.8 MB` to `316.7 MB`, in `bundle_write`

The corrected RSS report wording matters. The parent-side driver at the global
peak is the parent's actual RSS at the tree peak, not the later
`bundle_write` peak after workers have exited.

So the remaining ceiling story is:

1. live worker processes dominate the global peak
2. the parent still contributes a meaningful `~128 MB` to `~138 MB` at that
   same moment
3. reporting still adds real parent-only pressure later, but it does not set
   the global tree peak

That is enough to reject the idea that the remaining problem is mainly
dashboard assembly.

## Backend choice

Current realistic-trader backend rerun from
`backtests/review_2026-04-23_final/backend/backend_benchmark.json`:

- `streaming` won `4` of `7` measured cells
- `classic` won `3` of `7`
- `rust` won `0`

Current honest guidance:

- keep `streaming` as the design default and `auto` target
- keep `classic` as a co-equal parity and performance backend
- keep `rust` explicit and experimental only

## External reference

Current same-machine Chris Roberts rerun from
`backtests/review_2026-04-23_final/reference/reference_benchmark.json`:

- default `100/10`: `3.78x` to `15.54x` faster
- ceiling `1000/100`: `9.46x` to `18.80x` faster
- smaller retained bytes in every measured cell
- far fewer retained files, `5` instead of `50` or `410`

What still loses:

- RSS on every `1000/100` ceiling case

So the repo wins throughput, retained bytes and retained file count on the
matched same-machine test, but not ceiling RSS.

## Architecture direction

The fresh bake-off kept the same overall answer:

- MessagePack remains the only still-plausible contract-boundary move
- shared memory improved to a `1.253x` transport-only win
- neither result solves the current end-to-end ceiling-RSS frontier

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
- trust and proof cleanliness: strong again after the clean rerun and RSS
  wording fix
- deployment and workflow sanity: strong, but still benefits from serving the
  curated runtime case root instead of every raw benchmark scratch directory
- memory efficiency: not yet 10/10, because wide-worker ceiling RSS still
  trails the best local reference

The repo is ready to claim the strongest overall local research platform on the
audited evidence. It is not ready to claim the best performance on every
important axis.
