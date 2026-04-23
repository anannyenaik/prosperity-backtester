# Performance

Result: the repo still has the strongest overall local research-platform
performance story, but the current-local runtime picture is now more mixed and
execution-phase ceiling RSS remains the blocker to an honest all-axis crown.

All claims below come from fresh current-local benchmark runs on 2026-04-23.
See [`docs/BENCHMARKS.md`](BENCHMARKS.md) and
[`docs/BENCHMARK_SUMMARY.json`](BENCHMARK_SUMMARY.json) for the tracked proof
surface.

## Proof status

The tracked current-local headline artefacts were captured from a dirty
worktree:

- `backtests/_final_output_current_local`
- `backtests/_final_runtime_current_local`
- `backtests/_final_attribution_current_local`
- `backtests/_final_rss_frontier_current_local_v2`
- `backtests/_final_backend_current_local`
- `backtests/_final_reference_current_local`
- `backtests/_final_architecture_current_local`

Important limits:

- this clone does not retain a separate clean exact-same-worktree historical
  throughput baseline for the final diagnostics-only state
- the Chris Roberts comparison is same-machine and matched on a shared no-op
  trader plus tick budget, but it is not full semantic parity
- the shared-memory result is a transport microbenchmark only

## Current backend choice

There are three Monte Carlo backends in
`prosperity_backtester/mc_backends.py`:

| Backend | Use it when | Current verdict |
| --- | --- | --- |
| `streaming` | normal research work and the default branch loop | Design default, not raw-speed leader in this rerun. It won `3` of the `7` measured realistic-trader cells and remains the path-band-first architecture baseline. |
| `classic` | parity checks and cases where you want replay-style materialisation | Co-equal Python backend. It won `4` of the `7` measured realistic-trader cells, so it is not honest to describe it as only a slower fallback. |
| `rust` | explicit backend experiments | Kept available, but not recommended. It stayed slower than both Python backends in every fresh realistic rerun in this pass. |

`auto` still resolves to `streaming`.

## Quality-compromise check

No current headline win depends on silently dropping decision-critical
information.

Why that statement is evidence-backed:

- light mode still keeps exact replay summaries and exact fills
- Monte Carlo light mode still keeps exact final distributions and all-session
  path bands
- sampled Monte Carlo runs are still clearly qualitative previews, with
  truncation fields carried in the contract
- manifests, provenance, runtime phase timings and reporting-phase RSS are
  still written and benchmarked
- runtime claims include bundle writing rather than hiding cost in a later
  phase

The retained-byte gains come from compact layout and duplicate-structure
removal, not from weakening realism, reproducibility, storage trust or review
workflow.

## What the current pass proved

The current-local runtime story is now mixed rather than uniformly stronger
than the older audit baseline:

- default day-0 replay: `5.259s`
- default day-0 compare: `3.980s`
- fast pack: `9.667s`
- validation pack: `28.105s`
- default Monte Carlo light, `100/10`, `8` workers: `2.278s`
- heavy Monte Carlo light, `192/16`, `8` workers: `3.082s`
- ceiling Monte Carlo light, `768/24`, `8` workers: `6.405s`

Replay, compare and fast-pack are roughly flat-to-slower than the older audit
baseline on this machine. Wide-worker Monte Carlo and the matched same-machine
external reference still show a strong local throughput story.

The retained-output story is also strong on the tracked fixture:

- replay light: `1.36 MB`, `6` files
- replay full: `1.99 MB`, `12` files
- Monte Carlo light: `819.9 KB`, `6` files
- Monte Carlo full: `5.16 MB`, `18` files

The fresh same-machine Chris Roberts rerun still proves:

- `4.80x` to `14.75x` faster on the default `100/10` cases
- `9.59x` to `18.35x` faster on the ceiling `1000/100` cases
- fewer retained bytes in every measured cell
- far fewer retained files, `5` instead of `50` or `410`

What it does not prove is a memory-efficiency crown. Chris still keeps lower
RSS on every ceiling case.

## Current bottleneck picture

Fresh attribution and RSS probing now make the remaining frontier explicit.

Retained-byte ownership in light Monte Carlo is led by:

1. `monteCarlo.sampleRuns` preview series
2. `fills.csv`
3. the reporting path itself

The corrected high-resolution ceiling probe showed the true global peak is
still execution-phase process-tree RSS:

- `mc_ceiling_light_w8` runtime report: `411.5 MB` tree RSS
- corrected RSS probe: `404.4 MB` tree peak, `execution` phase
- workers alive at the tree peak: `8`
- live worker RSS at the tree peak: `266.9 MB`
- parent RSS at the tree peak: `137.4 MB`
- later parent-only peak: `282.7 MB`
- parent execution transient above the pre-reporting baseline: about `43.6 MB`
- reporting transient above the pre-reporting baseline: about `43.5 MB`

That means the remaining memory story is not "dashboard build is too big". The
true ceiling still comes from eight live workers plus a smaller parent-side
receive and merge bump.

## Architecture direction

The best current architecture remains the streaming-first Python design, but
the backend default is less final than the earlier proof text implied.

The fresh evidence now says:

- keep `streaming` as the design default for now
- keep `classic` as a real parity and performance option
- keep `rust` experimental only
- do not land optional binary sidecars now
- do not land shared-memory transport now
- do not pursue deeper native code without a real isolated compute kernel

Why optional binary sidecars do not land now:

- MessagePack shrank the real payload from `3.35 MB` to `2.39 MB`
- MessagePack encoded and decoded faster than compact JSON
- but the remaining blocker is execution RSS, not contract-boundary bytes
- keeping JSON canonical plus adding a sidecar would increase retained bytes by
  default

Why shared memory still does not land now:

- the fresh bake-off moved from a loss to a small win
- pickled transport: `0.631s`
- shared memory: `0.583s`
- speed-up: `1.081x`
- but that is still only a transport microbenchmark, not end-to-end engine
  proof

## Honest verdict

Current honest scorecard:

- runtime throughput: strong overall, but no longer a clean across-the-board
  local win versus the older audit baseline
- retained-output efficiency: very strong
- trust and proof cleanliness: strong, but still limited because the tracked
  measurements came from a dirty worktree
- ceiling-case RSS: still the main unresolved gap
- architecture finality: closer, but not fully closed because the backend
  choice inside the current Python design is still mixed

The repo is strong enough to claim the best overall local research platform on
the audited evidence. It is not honest yet to claim the best performance on
every important axis, because execution-phase ceiling RSS still trails the best
local external reference.
