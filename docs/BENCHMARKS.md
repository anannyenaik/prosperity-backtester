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
| `mc_full` | 7.47 MB | 18 | Full Monte Carlo roughly doubles bundle size because sample-path files, session manifests and sidecars are written explicitly. |

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

- clean baseline worktree at commit `1f05eb4`
- current working tree with the streaming Monte Carlo backend enabled by default

| Case | Clean baseline | Current repo | Delta |
| --- | ---: | ---: | ---: |
| day `0` light replay, `strategies/trader.py` | `2.862s` | `2.413s` | `-15.7%` |
| day `0` light compare, `strategies/trader.py` vs `strategies/starter.py` | `2.543s` | `2.572s` | `+1.1%` |
| fast pack | `5.494s` | `5.929s` | `+7.9%` |
| validation pack | `18.272s` | `20.358s` | `+11.4%` |
| Monte Carlo quick light, `64/8`, `1` worker | `2.295s` | `2.405s` | `+4.8%` |
| Monte Carlo default light, `100/10`, `1` worker | `3.355s` | `3.318s` | `-1.1%` |
| Monte Carlo default light, `100/10`, `2` workers | `2.591s` | `2.576s` | `-0.6%` |
| Monte Carlo default light, `100/10`, `4` workers | `2.014s` | `2.191s` | `+8.8%` |
| Monte Carlo heavy light, `192/16`, `1` worker | `6.994s` | `7.196s` | `+2.9%` |
| Monte Carlo heavy light, `192/16`, `4` workers | `3.277s` | `3.497s` | `+6.7%` |
| Monte Carlo default full, `100/10`, `1` worker | `4.103s` | `4.142s` | `+1.0%` |

Those baseline deltas are mixed because the pass also strengthens provenance and runtime metadata. The cleaner engine comparison is current `streaming` versus current `classic` on the same codebase:

| Case | Classic | Streaming | Delta |
| --- | ---: | ---: | ---: |
| Monte Carlo default light, `100/10`, `1` worker | `3.517s` | `3.318s` | `-5.7%` |
| Monte Carlo default light, `100/10`, `2` workers | `2.753s` | `2.576s` | `-6.4%` |
| Monte Carlo heavy light, `192/16`, `1` worker | `8.084s` | `7.196s` | `-10.9%` |
| Monte Carlo heavy light, `192/16`, `4` workers | `3.587s` | `3.497s` | `-2.5%` |
| Monte Carlo light, `512/32`, `1` worker | `21.951s` | `20.643s` | `-6.0%` |
| Monte Carlo light, `512/32`, `4` workers | `11.247s` | `10.993s` | `-2.3%` |

`analysis/profile_replay.py` on the current repo reports the slowest replay day as day `0`, with about:

- `1.559s` in the market session
- `0.644s` in replay-row compaction
- `0.286s` in dashboard plus bundle write

Focused Monte Carlo profiling on the tracked `250`-tick fixture now shows the main remaining cost centres as:

- synthetic market generation
- Python session stepping and execution
- all-session path-band aggregation and dashboard construction
- bundle writing

For example, `mc_default_light_w1` on streaming records about:

- `1.047s` in market generation
- `0.053s` in trader execution
- `0.661s` in order execution
- `0.154s` in path metrics
- `0.861s` in compaction, dashboard build and bundle write

The main improvement in this pass is that unsampled Monte Carlo sessions no longer build full replay artefacts. That improves the one-worker practical path meaningfully, but the high-worker ceiling is still limited by Python process overhead rather than raw trader execution alone.

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
