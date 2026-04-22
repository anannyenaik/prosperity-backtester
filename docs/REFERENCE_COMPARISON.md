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

Both repos now share the same fundamental compiled Rust + Python-subprocess architecture for Monte Carlo:

- both use a Rust binary with Rayon for session-level parallelism
- both use a Python subprocess per worker for trader execution via line-delimited JSON IPC
- the per-tick IPC overhead (~17μs/tick × 30K ticks/session ≈ +0.5s/session) is inherent to this approach

This repo's Rust backend (`--mc-backend rust`) is a complete implementation with equivalent ceiling throughput. Empirically at 1 worker, both repos' streaming Python backend (~1.68s/session) outperforms the Rust+IPC backend (~2.18s/session) because IPC overhead outweighs Rust computational savings. At 6+ workers both Rust backends scale similarly (Rayon vs Python ProcessPoolExecutor, both truly parallel).

This repo wins on:

- deterministic replay is first-class rather than secondary
- compare, scenario, calibration and Round 2 decision flows are built in
- Monte Carlo path bands are computed from all sessions, not only saved sample paths
- bundle storage, provenance, retention and local discovery are materially stronger
- the dashboard is wider and more useful for day-to-day strategy review
- backend selection is explicit, not implicit (auto=streaming, never surprise-compilations)
- the streaming backend is the correct practical default; `--mc-backend rust` is for deliberate high-worker-count ceiling runs

Measured performance (streaming backend, 250-tick fixture):

- default light MC (100/10): `3.32s` on 1 worker, `2.19s` on 4 workers
- heavy light MC (192/16): `7.20s` on 1 worker, `3.50s` on 4 workers
- streaming vs classic at 100/10: streaming ~5.7% faster on 1 worker, ~6.4% on 2 workers
- 512/32 run: streaming `20.64s` vs classic `21.95s` on 1 worker; `10.99s` vs `11.25s` on 4 workers

Current honest summary:

- raw session throughput ceiling is comparable between repos at high worker counts (both are IPC-bound when Rust is used)
- streaming Python is the faster practical default for typical 1–4 worker local work
- if only raw compiled ceiling matters and workflow depth is irrelevant, this repo's ceiling is now parity
- if practical local research throughput, replay, diagnostics, output trust and dashboard ergonomics matter together, this repo is the stronger platform

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
- `--print` and `--print-trader-output` both expose live trader stdout when needed
- `--vis` aliases `--open`
- `--limit PRODUCT:LIMIT` overrides per-product position limits
- `--match-trades` remains explicit and trust-oriented
- `--open` plus `serve --latest-type ...` gives a short local-open flow
- the dashboard landing screen now exposes latest replay, latest MC, latest compare, latest calibration, latest optimise and latest Round 2 buttons
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

Reach for Chris's architecture only if raw compiled Monte Carlo ceiling is the sole metric and you do not need the broader research workflow.

Reach for Nabayan's repo only if you want a smaller replay-only tool and do not need the broader research platform.
