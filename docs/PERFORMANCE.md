# Performance

Result: the repo still has the strongest overall local performance story, but
execution-phase ceiling RSS remains the blocker to an honest all-axis crown.

All claims below come from fresh current-local benchmark runs on 2026-04-22.
See [`docs/BENCHMARKS.md`](BENCHMARKS.md) and
[`docs/BENCHMARK_SUMMARY.json`](BENCHMARK_SUMMARY.json) for the tracked proof
surface.

## Proof status

Fresh current-local headline artefacts from this dirty worktree are:

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
| `streaming` | normal research work and the default branch loop | Recommended default. It won `5` of the `7` measured realistic-trader cells and keeps the best overall balance of throughput, fidelity and workflow breadth. |
| `classic` | parity checks and cases where you want replay-style materialisation | Real parity option. It still wins some realistic cells, so it is not honest to describe it as only a slower fallback. |
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

The repo still has a strong current-local branch-loop story:

- default day-0 replay: `2.570s`
- default day-0 compare: `2.027s`
- fast pack: `5.299s`
- validation pack: `17.783s`

The retained-output story is also strong on the tracked fixture:

- replay light: `1.36 MB`, `6` files
- replay full: `1.99 MB`, `12` files
- Monte Carlo light: `819.9 KB`, `6` files
- Monte Carlo full: `5.16 MB`, `18` files

The fresh same-machine Chris Roberts rerun still proves:

- `4.18x` to `18.09x` faster on the default `100/10` cases
- `10.27x` to `15.76x` faster on the ceiling `1000/100` cases
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

Fresh ceiling probing showed the true global peak is still execution-phase
process-tree RSS:

- `mc_ceiling_light_w8` runtime report: `417.5 MB` tree RSS
- high-resolution RSS probe: `415.3 MB` tree peak, `execution` phase
- workers alive at the peak: `8`
- live worker RSS at the peak: `277.7 MB`
- parent execution transient above the pre-reporting baseline: about `37 MB`
- reporting transient above the pre-reporting baseline: about `35 MB`

That means the remaining memory story is not "dashboard build is too big". The
true ceiling still comes from eight live workers plus a smaller parent-side
receive and merge bump.

## Architecture direction

The best current architecture remains the streaming-first Python design.

The fresh evidence now says:

- keep `streaming` as the default backend
- keep `classic` as a real parity and performance fallback
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
- pickled transport: `0.718s`
- shared memory: `0.599s`
- speed-up: `1.199x`
- but that is still only a transport microbenchmark, not end-to-end engine
  proof

## Honest verdict

Current honest scorecard:

- runtime throughput: very strong
- retained-output efficiency: very strong
- trust and proof cleanliness: strong, but still limited by the dirty worktree
- ceiling-case RSS: still the main unresolved gap
- architecture finality: close, but not fully closed

The repo is strong enough to claim the best overall local research platform on
the audited evidence. It is not honest yet to claim the best performance on
every important axis, because execution-phase ceiling RSS still trails the best
local external reference.
