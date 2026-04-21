# Benchmarks

Use the benchmark helpers when you want reproducible storage and runtime evidence.

Use `analysis/benchmark_outputs.py` for storage footprint and `analysis/benchmark_runtime.py` for runtime.

## Storage Benchmark

```bash
python analysis/benchmark_outputs.py --output-dir backtests/repo_output_benchmark
```

Default benchmark fixture:

- trader: `examples/benchmark_trader.py`
- round: `1`
- days: `0`
- replay fixture: first 250 tracked timestamps copied from `data/round1`
- Monte Carlo fixture: synthetic sessions truncated to the same 250 ticks
- Monte Carlo: 4 sessions, 2 saved sample sessions

This is intentionally a quick storage benchmark, not a research-quality robustness run. Use `--trader`, `--sessions`, `--sample-sessions` or `--fixture-timestamps` when you want numbers for a heavier real strategy.

## Representative Results

Measured on 2026-04-21 with the default command above:

| Case | Size | Files | What it proves |
| --- | ---: | ---: | --- |
| `replay_light` | 1.36 MB | 6 | Exact replay summary and fills fit in a small daily-use bundle. |
| `replay_full` | 1.99 MB | 12 | Full replay adds raw orders and chart-series sidecars for debugging. |
| `mc_light` | 3.89 MB | 6 | Light Monte Carlo keeps exact final distribution stats and all-session path bands without duplicate sample files. |
| `mc_full` | 7.48 MB | 18 | Full Monte Carlo roughly doubles bundle size because sample-path files, session manifests and sidecars are written explicitly. |

## Runtime Benchmark

Reproducible command:

```bash
python analysis/benchmark_runtime.py --output-dir backtests/runtime_benchmark
```

To compare against an earlier report from another worktree or clone:

```bash
python analysis/benchmark_runtime.py --output-dir backtests/runtime_benchmark --compare-report path/to/benchmark_report.json
```

Default runtime benchmark fixture:

- replay and compare use `strategies/trader.py` against tracked day `0`
- pack cases use `analysis/research_pack.py`
- Monte Carlo uses `examples/benchmark_trader.py`
- Monte Carlo synthetic sessions are capped to `250` ticks so quick, default and heavy tiers all stay local and reproducible
- workers default to `1 2 4`

Measured on 2026-04-21 against:

- clean `HEAD` worktree at commit `fd9db66`
- current working tree with the changes in this pass

| Case | Clean `HEAD` | Current repo | What changed |
| --- | ---: | ---: | --- |
| day `0` light replay, `strategies/trader.py` | `2.440s` | `2.326s` | Replay stays fast while provenance and newer UX metadata are preserved. |
| day `0` light compare, `strategies/trader.py` vs `strategies/starter.py` | `2.369s` | `2.503s` | Compare is still short-loop friendly while now exposing merged PnL, limit overrides and richer manifests. |
| fast pack | `7.747s` | `5.561s` | The daily pack benefits from cheaper Monte Carlo reporting and better reuse. |
| validation pack | `22.188s` | `20.653s` | Three-day validation stays deliberate but improves slightly. |
| Monte Carlo quick light, `64/8`, `1` worker | `2.994s` | `2.690s` | Unsampled sessions no longer build full replay artefacts. |
| Monte Carlo default light, `100/10`, `1` worker | `5.020s` | `4.166s` | One-worker practical throughput improves by about `17%`. |
| Monte Carlo heavy light, `192/16`, `1` worker | `10.578s` | `7.221s` | One-worker heavy throughput improves by about `31.7%`. |
| Monte Carlo default full, `100/10`, `1` worker | `5.940s` | `4.450s` | Even full-profile Monte Carlo benefits from skipping unnecessary non-sample work. |
| Monte Carlo default full without sample-path files and session manifests, `1` worker | `5.397s` | `3.961s` | The cost of debug artefacts is now easier to isolate and control. |

`analysis/profile_replay.py` on the current repo reports the slowest replay day as day `-1`, with about:

- `1.641s` in the market session
- `0.775s` in replay-row compaction
- `0.603s` in bundle write

Focused Monte Carlo profiling on the tracked `250`-tick fixture now shows the main remaining cost centres as:

- `run_market_session`
- `generate_synthetic_market_days`
- all-session path-band aggregation
- bundle writing and initial git provenance capture

The main improvement in this pass is that unsampled Monte Carlo sessions stop paying for full fair-value, behaviour and replay-series construction. That is why the one-worker default and heavy cases improve materially without needing a compiled backend.

## Files By Mode

Replay light writes:

- `dashboard.json`
- `manifest.json`
- `run_summary.csv`
- `session_summary.csv`
- `fills.csv`
- `behaviour_summary.csv`

Replay full additionally writes:

- `orders.csv`
- `inventory_series.csv`
- `pnl_series.csv`
- `fair_value_series.csv`
- `behaviour_series.csv`
- `order_intent.csv`

Monte Carlo light writes:

- `dashboard.json`
- `manifest.json`
- `run_summary.csv`
- `session_summary.csv`
- `fills.csv`
- `behaviour_summary.csv`

Monte Carlo full additionally writes:

- `orders.csv`
- `inventory_series.csv`
- `pnl_series.csv`
- `fair_value_series.csv`
- `behaviour_series.csv`
- `order_intent.csv`
- `sample_paths/*.json`
- `sessions/*.json`

## Reading The Trade-off

- Light is the correct daily default when you need exact scalar research metrics, exact fills, compact replay evidence and all-session Monte Carlo bands.
- Full is for local forensic work where raw order rows, full sidecars or separate sample-path files are worth the extra storage.
- Sample runs are qualitative examples in both modes. Monte Carlo path bands and final distribution metrics remain the research-grade population evidence.
- Absolute bundle size depends on strategy activity, fill count, saved sample sessions and retained timestamps. The benchmark is best used as a relative policy check rather than a universal storage forecast.
