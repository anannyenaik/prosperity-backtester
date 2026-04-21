# Output Benchmarks

Use the benchmark helper when you want a quick, reproducible view of what light mode saves and what full mode costs.

For runtime diagnosis rather than storage footprint, use:

```bash
python analysis/profile_replay.py strategies/trader.py --compare-trader strategies/starter.py --data-dir data/round1 --fill-mode empirical_baseline
```

## Reproducible Command

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

## Runtime Diagnosis

Measured on 2026-04-21.

Baseline public `main` was a clean clone at commit `3808b3e`.

| Case | Public `main` | Current repo | What changed |
| --- | ---: | ---: | --- |
| day `0` light replay, `strategies/trader.py` | `14.1s` | `2.5s` | Replay rows are compacted once and then reused for the dashboard plus bundle write. |
| day `0` light compare, `strategies/trader.py` vs `strategies/starter.py` | `3.1s` | `2.7s` | Day-0 compare stays cheap enough for routine branch testing. |
| day `0` Monte Carlo, `examples/benchmark_trader.py`, `8` sessions, `2` samples, `1` worker | timed out after `124s` | `18.9s` | Sample-session compaction is cached and reused instead of being rebuilt twice. |
| same Monte Carlo case, `4` workers | timed out after `124s` | `10.4s` | Worker parallelism becomes useful once reporting overhead is removed. |
| fast pack, `strategies/trader.py` | not available on public `main` | `6.1s` | Replay, compare and smoke Monte Carlo now have an explicit routine preset. |
| validation pack, `strategies/trader.py` | not available on public `main` | `24.5s` | Three-day validation is deliberate but still local-iteration friendly. |

`analysis/profile_replay.py` on the current repo reports the slowest public day as day `0`, with about:

- `1.74s` in the market session
- `0.74s` in replay-row compaction
- `0.35s` in dashboard build plus bundle write

The practical bottleneck was duplicate reporting work, not the core simulator. That is why the current repo focuses on faster Python reporting and clearer workflow separation rather than introducing a Rust backend prematurely.

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
