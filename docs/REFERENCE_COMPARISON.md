# Reference Comparison

This repo was audited against the highest-signal public references on
2026-04-22.

Primary references reviewed from source:

- `anannyenaik/prosperity-backtester` at `32af42d`
- `chrispyroberts/imc-prosperity-4` at `fac270e`
- `nabayansaha/imc-prosperity-4-backtester` at `94ec38d`
- `jmerle/imc-prosperity-3-backtester` at `26f52ee`

Secondary references were not roadmap-changing for this pass.

The goal of this review was not feature counting. The goal was to answer one
question: what still blocks this repo from being the strongest public Prosperity
research platform overall, and what still blocks an honest claim on
performance.

## Short conclusion

This repo is already the strongest public overall platform.

What was still missing before this pass was:

- cleaner benchmark proof
- a tighter performance story
- removal of one real residual bottleneck in Monte Carlo reporting

The reference audit did not justify a broad architectural rewrite.

## Versus Chris Roberts

Chris Roberts' repo is the strongest narrow Monte Carlo reference.

What it still does better:

- smaller surface area if you only care about tutorial-round Monte Carlo
- a very direct Rust-first story
- a simpler install and mental model for that single use case once Cargo is in place

What this repo already does better:

- deterministic replay is first-class, not a side path
- compare, sweep, optimisation, calibration, scenario review and Round 2 access work live in one system
- output contracts, provenance and retention are materially stronger
- light vs full storage policy is explicit and benchmarked
- the dashboard covers replay, comparison, Monte Carlo and aggregate workflows instead of only one mode

What was genuinely reusable from the audit:

- treat Chris as the main public performance credibility reference
- keep backend choice explicit
- keep same-machine notes honest when workloads are not directly comparable

What was mostly noise for this roadmap:

- tutorial-round-only modelling assumptions
- any claim that a Rust subprocess design should automatically become this
  repo's default architecture

Same-machine note, recorded after the one-time Cargo build:

- `prosperity4mcbt example_trader.py --quick`: about `15.974s`
- `prosperity4mcbt example_trader.py --heavy`: about `148.707s`

That note is useful context, but it is not an apples-to-apples comparison with
this repo's Round 1 benchmark fixture. Chris's repo uses tutorial-round
products, `10000` ticks per day and a different output contract, so it does not
change the roadmap by itself.

## Versus Nabayan Saha

Nabayan's repo is still a useful replay-ergonomics reference.

What it still does better:

- smaller replay-first CLI surface
- very low ceremony for simple visual replay runs

What this repo already does better:

- much broader workflow coverage
- stronger trust controls and manifest metadata
- better storage policy and output discipline
- stronger dashboard breadth
- stronger benchmark and proof tooling

What was genuinely reusable:

- keep the common replay ergonomics short
- keep flags like `--match-trades`, `--merge-pnl`, `--print`, `--limit` and
  quick visual open flows easy to reach

What was mostly noise:

- anything beyond replay convenience, because this repo already covers the
  deeper research loop Nabayan's repo does not try to solve

## Versus Jasper van Merle

Jasper's repo matters as a historical reference, but it did not change the
current roadmap.

What it still does better:

- very small, approachable replay-and-visualiser baseline for older rounds

What this repo already does better:

- current-round workflow depth
- benchmark credibility
- provenance and contract surface
- Monte Carlo and robustness tooling

What was reusable:

- keep the repo approachable despite broader scope

What was mostly noise:

- old-round-only assumptions
- missing modern trust and benchmark surfaces

## Roadmap impact

The reference audit pointed to one high-EV conclusion:

- do not rewrite the core architecture
- tighten the evidence moat
- fix the reporting bottleneck the profiler actually showed

That is what the 2026-04-22 pass did.

## Honest status

Current honest status after this pass:

- overall public-platform lead: yes
- same-machine shared-benchmark runtime lead over Chris Roberts: yes
- memory and retained-output efficiency lead over Chris Roberts: no
- undisputed all-axis performance crown across public repos: not yet proven

The remaining proof gap is no longer a shared-fixture runtime check. A strict
same-machine no-op trader pass now shows this repo ahead on runtime through the
measured `1`, `2`, `4`, and `8` worker cases. What is still missing for an
undisputed public performance crown is lower RSS and a lighter retained-output
footprint on the heavier cases. Until that improves, this repo can honestly
claim the best overall platform and a strong measured runtime-throughput lead,
but not a blanket win across every performance dimension.
