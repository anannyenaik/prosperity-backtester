# Performance

Result: the fresh 2026-04-23 local proof supports calling this repo the
strongest overall local Prosperity research platform. It still does not
support an all-axis performance crown, because wide-worker ceiling RSS remains
behind the strongest local external reference on the matched `1000/100` cases.

The current local proof root is `backtests/review_2026-04-23_final_pass`.

## Proof status

Current proof artefacts:

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

Important limits:

- the fresh Windows reruns record `git_dirty: true` because the new direct CLI
  helper and its test registration were already present, but the replay, Monte
  Carlo, reporting and dashboard runtime code paths still matched `HEAD`
  `b3f9534a815993867160f7ba247ff5957fb032f4`
- the monitored runtime suite includes process-tree sampling and one warm
  measured run per cell, so short-case throughput claims should be
  cross-checked against the direct CLI reruns
- the WSL deployment-shape reruns came from a synced Linux-filesystem checkout
  whose Git metadata still reported `eafb1e4...`, so they are deployment-shape
  evidence rather than clean-commit Git proof
- WSL tree RSS is still a summed RSS measure, so pack-level totals can
  overcount fork-shared pages
- the Chris Roberts comparison is same-machine and matched on a shared no-op
  trader plus tick budget, but it is not full semantic parity
- the shared-memory result is a transport microbenchmark only

## Runtime

Headline monitored warm timings from
`backtests/review_2026-04-23_final_pass/runtime/benchmark_report.json`:

- day-0 replay: `2.882s`
- day-0 compare: `2.386s`
- fast pack: `5.530s`
- validation pack: `17.931s`
- default Monte Carlo light, `100/10`, `8` workers: `1.355s`
- heavy Monte Carlo light, `192/16`, `8` workers: `2.023s`
- ceiling Monte Carlo light, `768/24`, `8` workers: `3.372s`

Tracked Monte Carlo scaling on the `250`-tick fixture:

| Case | 1 worker | 2 workers | 4 workers | 8 workers |
| --- | ---: | ---: | ---: | ---: |
| MC quick light (`64/8`) | `1.533s` | `1.439s` | `1.325s` | `1.252s` |
| MC default light (`100/10`) | `2.096s` | `1.854s` | `1.448s` | `1.355s` |
| MC heavy light (`192/16`) | `3.580s` | `n/a` | `n/a` | `2.023s` |
| MC ceiling light (`768/24`) | `n/a` | `n/a` | `n/a` | `3.372s` |

## Harness sanity

The monitored harness is useful, but it is not honest to present it as a bare
CLI equivalent on the shorter worker-pool Monte Carlo cells.

Fresh same-machine direct CLI reruns gave:

- `replay_day0_light`: harness `2.882s`, direct mean `2.600s`, `-9.8%`
- `compare_day0_light`: harness `2.386s`, direct mean `2.252s`, `-5.6%`
- `pack_fast`: harness `5.530s`, direct mean `5.235s`, `-5.3%`
- `pack_validation`: harness `17.931s`, direct mean `16.238s`, `-9.4%`
- `mc_default_light_w8`: harness `1.355s`, direct mean `1.323s`, `-2.4%`
- `mc_heavy_light_w8`: harness `2.023s`, direct mean `1.702s`, `-15.9%`
- `mc_ceiling_light_w8`: harness `3.372s`, direct mean `3.150s`, `-6.6%`

The reason is straightforward:

- `analysis/benchmark_runtime.py` measures a monitored run, not a bare CLI run
- it keeps process-tree sampling live during the measurement
- it records one warm measured run per cell rather than a direct multi-repeat
  mean

Use the monitored suite for regression tracking, RSS and phase accounting. Use
the direct CLI checks in the same review root for the short-case throughput
headline.

## Retained output

Current retained-output sizes from
`backtests/review_2026-04-23_final_pass/storage/benchmark_report.json`:

- replay light: `1.36 MB`, `6` files
- replay full: `1.99 MB`, `12` files
- Monte Carlo light: `819.9 KB`, `6` files
- Monte Carlo full: `5.16 MB`, `18` files

Retained-byte ownership in light Monte Carlo is still led by:

1. `monteCarlo.sampleRuns`
2. `fills.csv`
3. reporting-path write pressure

For `mc_default_light_w8`:

- dashboard payload: `1,567,133` bytes
- `fills.csv`: `1,289,324` bytes
- top dashboard owner: `monteCarlo.sampleRuns` at `1,243,393` bytes

For `mc_ceiling_light_w8`:

- dashboard payload: `3,349,466` bytes
- `fills.csv`: `3,098,231` bytes
- top dashboard owner: `monteCarlo.sampleRuns` at `2,986,485` bytes

That keeps retained-output efficiency in a strong place. The remaining storage
frontier is narrow and explicit, not a broad bundle-bloat problem.

## Memory frontier

The clean runtime report and the high-resolution RSS probes still tell the same
overall story:

- runtime-suite tree peak on `mc_ceiling_light_w8`: `418.2 MB`
- `5 ms` RSS-frontier reruns: `413.8 MB`, `416.9 MB`, `421.1 MB`
- tree peak phase on every rerun: `execution`
- workers alive at tree peak on every rerun: `8`
- live worker RSS at tree peak: `294.4 MB` to `301.6 MB`
- parent RSS at tree peak: `131.7 MB` to `136.2 MB`
- later parent-only reporting peak: `233.7 MB` to `316.9 MB`, in
  `bundle_write`

The remaining ceiling story is still:

1. live worker processes dominate the global peak
2. the parent still contributes a meaningful `~132 MB` to `~136 MB` at that
   same moment
3. the later reporting spike is real, but it does not set the global tree peak

That is enough to reject the idea that the remaining problem is mainly
dashboard assembly.

## Deployment shape

Fresh same-code WSL reruns from a Linux-filesystem checkout reduced both the
wide-worker RSS shape and the key runtime cells:

- `replay_day0_light`: `2.882s` to `1.997s`
- `compare_day0_light`: `2.386s` to `1.899s`
- `mc_default_light_w8`: `1.355s` to `0.675s`, tree RSS `356.1 MB` to
  `277.4 MB`
- `mc_heavy_light_w8`: `2.023s` to `1.202s`, tree RSS `371.5 MB` to
  `305.4 MB`
- `mc_ceiling_light_w8`: `3.372s` to `2.853s`, tree RSS `418.2 MB` to
  `378.0 MB`

The high-resolution ceiling probes also stayed lower in WSL:

- Windows `5 ms` tree peak reruns: `413.8 MB` to `421.1 MB`
- WSL `5 ms` tree peak reruns: `390.7 MB` to `391.4 MB`

The honest deployment guidance is:

- native Windows remains the simpler day-to-day development default
- prefer Linux or WSL on the Linux filesystem for memory-sensitive or
  throughput-sensitive wide-worker Monte Carlo work

This does change deployment guidance. It does not change the architecture
decision, because the gain is still modest relative to the external
ceiling-RSS gap.

## Backend choice

Current realistic-trader backend rerun from
`backtests/review_2026-04-23_final_pass/backend/backend_benchmark.json`:

- `streaming` won `5` of `7` measured cases
- `classic` won `2` of `7`
- `rust` won `0`

Current honest guidance:

- keep `streaming` as the design default and `auto` target
- keep `classic` as a co-equal parity and performance backend
- keep `rust` explicit and experimental only

## External reference

A fresh same-machine Chris Roberts rerun was not available in this session
because the exact local repo path from the earlier audited run was gone.

The preserved audited report still showed:

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

- JSON payload: `3,349,466` bytes
- MessagePack payload: `2,388,457` bytes
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

## Honest verdict

Current honest scorecard:

- runtime throughput: very strong
- retained-output efficiency: very strong
- trust and proof cleanliness: stronger, because the docs now match the fresh
  local reruns and the harness caveat is explicit and reproducible
- deployment and workflow sanity: stronger, with explicit Windows versus Linux
  guidance for the remaining memory frontier
- memory efficiency: not yet `10/10`, because wide-worker ceiling RSS still
  trails the best local reference

The repo is ready to claim the strongest overall local research platform on the
current local evidence. It is not ready to claim the best performance on every
important axis.
