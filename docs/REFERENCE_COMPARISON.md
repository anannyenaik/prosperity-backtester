# Reference Comparison

This page records what the 2026-04-22 local audit could actually prove against
the reference repos that were available in this session.

## Scope and visibility note

The strongest fresh external proof in this pass is the same-machine Chris
Roberts rerun from `analysis/benchmark_chris_reference.py`.

This repo's GitHub remote was visible locally, but public visibility was not
verified in-session. If this repo is private, the proof surface here is an
internal audit rather than a public leaderboard claim. The wording below is
therefore intentionally about locally audited evidence, not internet-wide
closure.

## Short conclusion

Current honest conclusion:

- strongest overall research platform on the locally audited evidence: yes
- strongest same-machine runtime-throughput result versus Chris Roberts: yes
- strongest retained-output efficiency result versus Chris Roberts: no
- strongest ceiling-RSS result versus Chris Roberts: no
- undisputed all-axis performance crown: no

## Versus Chris Roberts

Chris Roberts' repo remains the highest-signal narrow Monte Carlo reference
that was available locally in this pass.

### What the rerun matched

The fresh same-machine rerun used:

- the same no-op trader file in both repos
- matched `250` ticks per simulated day
- matched `100/10` and `1000/100` session or sample tiers
- matched `1`, `2`, `4`, and `8` worker or thread counts
- one warm-up pass per repo before the measured runs

The exact command is tracked in
[`docs/BENCHMARK_SUMMARY.json`](BENCHMARK_SUMMARY.json) and in
`backtests/_phase5_reference_benchmark/reference_benchmark.json`.

### Runtime result

This repo won every measured runtime cell:

- default `100/10`: `4.34x` to `18.69x` faster
- ceiling `1000/100`: `11.36x` to `17.50x` faster

Representative cells:

| Case | Workers | This repo | Chris Roberts | Speed-up |
| --- | ---: | ---: | ---: | ---: |
| default `100/10` | `1` | `1.179s` | `22.031s` | `18.69x` |
| default `100/10` | `8` | `1.084s` | `4.702s` | `4.34x` |
| ceiling `1000/100` | `1` | `11.431s` | `200.091s` | `17.50x` |
| ceiling `1000/100` | `8` | `3.598s` | `40.890s` | `11.36x` |

### Memory and retained-output result

The all-axis story is mixed.

What this repo did better:

- less RSS on the smaller default `100/10` cases
- far fewer retained files, `5` instead of `50` or `410`
- much stronger runtime throughput

What Chris Roberts still did better:

- lower RSS on every `1000/100` ceiling case
- smaller retained output footprint in every rerun

That means the runtime lead is real, but the repo still does not own every
performance dimension.

### Workflow and platform result

Chris Roberts' repo still has a cleaner narrow Monte Carlo story when that is
the only job.

This repo still has the stronger overall research system:

- deterministic replay is first-class
- compare, sweep, optimisation, calibration and scenario work live in one CLI
- output profiles and storage trade-offs are explicit
- manifests, provenance and dashboard contracts are stronger
- the dashboard supports replay, comparison, Monte Carlo and aggregate review

## Other references

Other local references still matter for context, but they were not rerun as
fresh same-machine benchmarks in this pass.

- Nabayan Saha remains a useful replay-first ergonomics reference.
- Jasper van Merle remains a useful historical small-backtester reference.

Those repos can still shape workflow judgement, but they do not change the
hardest remaining gap from this pass, which is retained bytes and ceiling RSS
rather than runtime throughput.

## Honest status

The current evidence supports these claims:

- this repo is ahead on same-machine runtime throughput against the strongest
  local external reference that was rerun
- this repo is ahead on retained file-count efficiency
- this repo is not yet ahead on retained output bytes
- this repo is not yet ahead on ceiling-case RSS

That is enough to call the repo the stronger overall local platform. It is not
enough to call it the undisputed winner on every performance axis.
