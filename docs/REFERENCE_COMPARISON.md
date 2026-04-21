# Reference Comparison

This repo was reviewed against two public Prosperity-style research repos on 2026-04-21:

- Chris Roberts: `chrispyroberts/imc-prosperity-4` at `fac270e`
- Nabayan Saha: `nabayansaha/imc-prosperity-4-backtester` at `94ec38d`

The goal is not a vanity feature count. The goal is the strongest practical all-round research platform.

## Where This Repo Clearly Leads

- Wider research surface: replay, compare, calibration, scenario compare, optimisation, Round 2 MAF and access modelling, bundle contracts, retention and benchmark helpers.
- Stronger storage design: light and full output profiles, canonical files, compact order-intent rows, exact fills, explicit debug artefacts and manifest data contracts.
- Stronger dashboard surface: one dashboard for replay, comparison, Monte Carlo, calibration, optimisation, Round 2 and inspect workflows.
- Stronger trust story: manifest provenance, workflow tier, backend metadata, git provenance, output-contract tests and dashboard adapter tests.
- Stronger handoff quality: workflow packs, benchmark helpers, architecture notes, assumptions notes and round-specific docs.

## Versus Chris Roberts

Chris still has the strongest public raw engine ceiling:

- Rust-backed simulator
- session parallelism through Rayon
- a clear heavy Monte Carlo story around large session counts

This repo now wins on the broader practical workflow:

- deterministic replay is first-class rather than secondary
- compare, scenario, calibration and Round 2 decision flows are built in
- Monte Carlo path bands are computed from all sessions, not only from saved sample paths
- bundle storage, provenance and local discovery are materially stronger
- the dashboard is wider and more useful for day-to-day strategy review

Practical Monte Carlo changes in this pass:

- unsampled sessions no longer build full replay artefacts
- worker scheduling is chunked rather than one-session-per-task
- exact all-session path bands are retained
- runtime benchmarking is now reproducible and comparable against a clean baseline worktree

Current honest caveat:

- if the only metric is absolute simulator ceiling at very large session counts, Chris's compiled backend is still the stronger public architecture today
- if the metric is practical local research throughput plus replay, output, trust and dashboard ergonomics together, this repo is the stronger default platform

## Versus Nabayan Saha

Nabayan's main strengths are replay neatness and convenience:

- concise Typer CLI
- `--vis`
- `--merge-pnl`
- `--print`
- `--match-trades`
- `--limit PRODUCT:LIMIT`
- simple custom data-path handling

This repo now closes or surpasses those replay UX points while keeping much more research depth:

- `--data` alias is available alongside `--data-dir`
- `--merge-pnl` is available on compare
- `--print-trader-output` exposes live trader stdout when needed
- `--limit PRODUCT:LIMIT` overrides per-product position limits
- `--open` plus `serve --latest-type ...` gives a short local-open flow
- the dashboard landing screen exposes latest replay, latest MC and latest compare buttons
- run naming is cleaner for auto-generated outputs
- CLI help includes concrete examples instead of only flag lists

This repo still keeps the advantages Nabayan's repo does not try to cover:

- Monte Carlo robustness
- benchmark tooling
- calibration
- scenario compare
- Round 2 access modelling
- richer bundle and manifest contracts

## Practical Recommendation

Choose this repo when you want one default platform for:

- branch-loop replay and compare
- robustness checks
- dashboard review
- storage discipline
- handoff-ready research output

Reach for Chris's architecture only if raw compiled Monte Carlo ceiling becomes the dominant constraint.

Reach for Nabayan's repo only if you want a smaller replay-only tool and do not need the broader research platform.
