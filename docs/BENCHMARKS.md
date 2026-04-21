# Output Benchmarks

Use the benchmark helper when you want a quick, reproducible view of what light mode saves and what full mode costs.

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
