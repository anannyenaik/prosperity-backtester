# Workflows

Use the repo in three tiers.

- Fast loop: routine branch testing
- Validation loop: promising branches
- Heavy forensic loop: finalists, suspicious behaviour, or raw-order debugging

The normal default is day `0` replay and compare in light mode. Three-day and
full-fidelity work are deliberate.

## Fast loop

Use this for normal branch testing.

Default replay and compare target day `0`:

```bash
python -m prosperity_backtester replay strategies/trader.py --name current --data data/round1 --fill-mode empirical_baseline
python -m prosperity_backtester compare strategies/trader.py strategies/starter.py --names current starter --data data/round1 --fill-mode empirical_baseline --merge-pnl
```

Use the bundled fast pack when you want the standard replay, compare and smoke
Monte Carlo set in one go:

```bash
python analysis/research_pack.py fast --trader strategies/trader.py --baseline strategies/starter.py
```

Measured on 2026-04-23 on this machine:

- default day-0 replay: about `2.88s` in the monitored suite, `2.60s` on
  fresh direct CLI reruns
- default day-0 compare: about `2.39s` in the monitored suite, `2.25s` on
  fresh direct CLI reruns
- fast pack: about `5.53s` in the monitored suite, `5.24s` on fresh direct CLI
  reruns

Useful trust checks during the fast loop:

```bash
python -m prosperity_backtester replay strategies/trader.py --name current --data data/round1 --fill-mode empirical_baseline --match-trades worse
python -m prosperity_backtester replay strategies/trader.py --name current --data data/round1 --fill-mode empirical_baseline --match-trades none
python -m prosperity_backtester replay strategies/trader.py --name current --data data/round1 --fill-mode empirical_baseline --limit INTARIAN_PEPPER_ROOT:40 --print
```

## Validation loop

Use this when a branch looks worth promoting.

```bash
python analysis/research_pack.py validation --trader strategies/trader.py --baseline strategies/starter.py
```

This gives:

- three-day replay
- three-day compare
- stronger Monte Carlo than the fast loop, still trimmed for local iteration

Measured on 2026-04-23 on this machine:

- validation pack: about `17.93s` in the monitored suite, `16.24s` on fresh
  direct CLI reruns

## Heavy forensic loop

Use this only when you explicitly want full-fidelity evidence.

```bash
python analysis/research_pack.py forensic --trader strategies/trader.py --baseline strategies/starter.py
```

This switches replay and Monte Carlo to full output and uses a heavier Monte
Carlo run across all three days.

Treat this as a minute-scale task rather than part of the default branch loop.

## Replay profiling

Use the profiling helper when replay speed looks wrong.

```bash
python analysis/profile_replay.py strategies/trader.py --compare-trader strategies/starter.py --data-dir data/round1 --fill-mode empirical_baseline
```

The helper benchmarks each requested day separately and reports:

- dataset load time
- trader construction time
- market-session time
- replay-row compaction time
- dashboard build time
- bundle write time

Rerun this helper locally before using any exact replay-phase timings in docs or
reviews. The tracked headline proof for this pass lives in the benchmark
reports, not in a fixed replay-profile snapshot.

## Monte Carlo

Use Monte Carlo directly when you want custom sessions, days or workers.

```bash
python -m prosperity_backtester monte-carlo strategies/trader.py --name current --days 0 --fill-mode empirical_baseline --noise-profile fitted --quick
python -m prosperity_backtester monte-carlo strategies/trader.py --name current --days 0 --fill-mode empirical_baseline --noise-profile fitted --sessions 256 --sample-sessions 16 --workers 4 --mc-backend classic
```

Review mean, median, P05, expected shortfall, drawdown and limit breaches. The
dashboard path bands are computed from all sessions. Saved sample runs are
preview-capped examples for qualitative inspection only in light mode.

Measured on 2026-04-23 on the tracked `250`-tick fixture:

- quick light, `64/8`, `1` worker: about `1.53s`
- quick light, `64/8`, `4` workers: about `1.33s`
- quick light, `64/8`, `8` workers: about `1.25s`
- default light, `100/10`, `1` worker: about `2.10s`
- default light, `100/10`, `4` workers: about `1.45s`
- default light, `100/10`, `8` workers: about `1.36s` in the monitored suite,
  `1.32s` on fresh direct CLI reruns
- heavy light, `192/16`, `1` worker: about `3.58s`
- heavy light, `192/16`, `8` workers: about `2.02s` in the monitored suite,
  `1.70s` on fresh direct CLI reruns
- ceiling light, `768/24`, `8` workers: about `3.37s` in the monitored suite,
  `3.15s` on fresh direct CLI reruns

Backend guidance is now simple:

- use `streaming` for the default path-band-first architecture
- use `classic` when you want a parity fallback or a fresh local timing check
  against replay-style materialisation
- use `rust` only for explicit backend experiments

On the fresh realistic-trader rerun in
`backtests/review_2026-04-23_final_pass/backend`, `streaming` won `5` of the
`7` measured cases, `classic` won `2`, and `rust` won none.

## Recommended environment

Use native Windows when you want the simplest local workflow.

For the best same-machine throughput or lowest RSS on wide-worker Monte Carlo
cases, prefer Linux or WSL from a Linux filesystem checkout rather than
`/mnt/d`.

Fresh same-code local reruns showed:

- `mc_default_light_w8`: `1.355s` to `0.675s`, tree RSS `356.1 MB` to
  `277.4 MB`
- `mc_heavy_light_w8`: `2.023s` to `1.202s`, tree RSS `371.5 MB` to
  `305.4 MB`
- `mc_ceiling_light_w8`: `3.372s` to `2.853s`, tree RSS `418.2 MB` to
  `378.0 MB`

The WSL reruns from this pass are deployment-shape evidence, not clean-commit
Git proof, because the synced Linux checkout retained older Git metadata.

## Sweep

Use sweep for small parameter grids where each variant is replayed once.

```bash
python -m prosperity_backtester sweep configs/pepper_sweep.json
```

## Optimisation

Use optimisation when each variant needs replay and Monte Carlo evidence.

```bash
python -m prosperity_backtester optimize configs/pepper_optimize_quick.json
```

The score combines replay PnL, Monte Carlo mean, downside, expected shortfall,
volatility, drawdown and limit-breach penalties.

## Calibration

Use calibration when live-export evidence is available.

```bash
python -m prosperity_backtester calibrate examples/trader_round1_v9.py --name live_v9 --data-dir data/round1 --days 0 --live-export live_exports/259168/259168.json --quick
```

Calibration is useful for choosing conservative assumptions, not for proving
exact website replication. It is not part of the default fast pack.

## Scenario compare

Use scenario compare when rankings need to survive stress.

```bash
python -m prosperity_backtester scenario-compare configs/research_scenarios.json
```

Review `robustness_ranking.csv` and `scenario_winners.csv` before trusting
small replay gains.

## Round 2 scenarios

Use Round 2 scenarios for Market Access Fee and extra-access decisions.

```bash
python -m prosperity_backtester round2-scenarios configs/round2_scenarios.json
```

The checked-in default config is replay-only so it stays suitable for a normal
local verification pass.

## Dashboard review

```bash
npm run build --prefix dashboard
python -m prosperity_backtester serve --port 5555
python -m prosperity_backtester serve --dir backtests/review_2026-04-23_final_pass/runtime/cases --port 5555
python -m prosperity_backtester serve --latest
python -m prosperity_backtester serve --latest-type replay
python -m prosperity_backtester serve --latest-type monte-carlo
```

Open `http://127.0.0.1:5555/`, then use the latest-run shortcuts or browse the
local server directly. For the clean audited proof bundles from this pass,
prefer serving `backtests/review_2026-04-23_final_pass/runtime/cases` rather
than the entire review root. The server hides the main benchmark scratch
bundles, but `runtime/cases` is still the cleanest review surface.

To finish a run and open its bundle directly:

```bash
python -m prosperity_backtester replay strategies/trader.py --data data/round1 --fill-mode empirical_baseline --open
python -m prosperity_backtester monte-carlo strategies/trader.py --days 0 --fill-mode empirical_baseline --noise-profile fitted --quick --open
```

## Storage and retention

The default output profile is light. Use full mode only for forensic work.

Default timestamped runs under `backtests/` keep the newest `30` runs. Use
`--keep-runs` or:

```bash
python -m prosperity_backtester clean --keep 30
```

to keep local output lists readable.
