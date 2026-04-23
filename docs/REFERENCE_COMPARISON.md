# Reference Comparison

Current result: on the matched same-machine Chris Roberts no-op benchmark, this
repo wins runtime, retained bytes and file count, but still loses ceiling-case
RSS.

This page records what the 2026-04-23 local audit could actually prove against
the reference repos that were available in this session.

## Scope note

The strongest fresh external proof in this pass is the same-machine Chris
Roberts rerun from `analysis/benchmark_chris_reference.py`.

The wording below is intentionally about locally audited evidence, not a public
internet-wide leaderboard claim.

## Short conclusion

Current honest conclusion:

- strongest overall research platform on the locally audited evidence: yes
- strongest same-machine runtime-throughput result versus Chris Roberts: yes
- strongest retained-byte result on the matched shared no-op benchmark: yes
- strongest retained file-count result on the matched shared no-op benchmark:
  yes
- strongest ceiling-RSS result versus Chris Roberts: no
- undisputed all-axis performance crown: no

## Versus Chris Roberts

Chris Roberts' repo remains the highest-signal narrow Monte Carlo reference
that was available locally in this pass.

### What the rerun matched

The fresh same-machine rerun used:

- the same shared no-op trader file in both repos
- matched `250` ticks per simulated day
- matched `100/10` and `1000/100` session or sample tiers
- matched `1`, `2`, `4` and `8` worker or thread counts
- one warm-up pass per repo before the measured runs

The exact command is tracked in
[`docs/BENCHMARK_SUMMARY.json`](BENCHMARK_SUMMARY.json) and in
`backtests/_final_reference_current_local/reference_benchmark.json`.

### Runtime result

This repo won every measured runtime cell:

- default `100/10`: `4.80x` to `14.75x` faster
- ceiling `1000/100`: `9.59x` to `18.35x` faster

Representative cells:

| Case | Workers | This repo | Chris Roberts | Speed-up |
| --- | ---: | ---: | ---: | ---: |
| default `100/10` | `1` | `2.796s` | `41.229s` | `14.75x` |
| default `100/10` | `8` | `2.021s` | `9.694s` | `4.80x` |
| ceiling `1000/100` | `1` | `21.626s` | `396.830s` | `18.35x` |
| ceiling `1000/100` | `8` | `6.568s` | `63.016s` | `9.59x` |

### Memory and retained-output result

The all-axis story is still mixed.

What this repo did better:

- less RSS on every smaller default `100/10` case
- fewer retained bytes in every measured same-machine no-op comparison cell
- far fewer retained files, `5` instead of `50` or `410`
- much stronger runtime throughput

What Chris Roberts still did better:

- lower RSS on every `1000/100` ceiling case

Representative ceiling rows:

| Workers | This repo RSS | Chris RSS | This repo bytes | Chris bytes |
| ---: | ---: | ---: | ---: | ---: |
| `1` | `329.9 MB` | `136.1 MB` | `6.87 MB` | `9.69 MB` |
| `4` | `418.4 MB` | `249.1 MB` | `6.87 MB` | `9.69 MB` |
| `8` | `558.8 MB` | `401.9 MB` | `6.87 MB` | `9.69 MB` |

That means the retained-byte gap did close on this matched comparison. The
remaining hard gap is ceiling RSS.

### What this does not prove

This comparison is intentionally narrow.

It does not prove:

- full semantic parity across the two repos
- retained-byte superiority across richer traders or different output
  contracts
- a universal memory-efficiency crown beyond the matched same-machine test

It does prove that, under the matched no-op benchmark used here, the repo
beats the Chris Roberts clone on the output-size axis as well as runtime.

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
hardest remaining gap from this pass, which is ceiling RSS rather than runtime
throughput or retained bytes.

## Honest status

The current evidence supports these claims:

- this repo is ahead on same-machine runtime throughput against the strongest
  local external reference that was rerun
- this repo is ahead on retained output bytes on the matched same-machine
  no-op benchmark
- this repo is ahead on retained file-count efficiency
- this repo is not yet ahead on ceiling-case RSS

That is enough to call the repo the stronger overall local platform. It is not
enough to call it the undisputed winner on every performance axis.
