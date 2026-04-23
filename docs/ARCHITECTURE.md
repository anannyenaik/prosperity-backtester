# Architecture

The repository is organised around output bundles. Each workflow runs a trader,
records structured sidecars, writes a `dashboard.json` payload and, where
useful, writes `manifest.json` metadata for fast dashboard discovery.

## Layers

### Data

Files:

- `prosperity_backtester/dataset.py`
- `prosperity_backtester/live_export.py`
- `prosperity_backtester/metadata.py`
- `prosperity_backtester/noise.py`
- `prosperity_backtester/round2.py`
- `prosperity_backtester/scenarios.py`

Responsibilities:

- Load Round 1 and Round 2 CSVs.
- Validate schema, timestamps, products, duplicate rows and book issues.
- Load tracked live-export JSON fixtures.
- Store product metadata and fitted noise profiles.
- Describe Round 2 access assumptions and calibrated research scenarios.

### Trader Compatibility

Files:

- `prosperity_backtester/datamodel.py`
- `prosperity_backtester/trader_adapter.py`

Responsibilities:

- Provide the Prosperity `TradingState`, `OrderDepth`, `Order` and `Trade`
  contract.
- Support common imports such as `from datamodel import ...`.
- Load trader files safely and apply config override dictionaries.

### Execution and Accounting

Files:

- `prosperity_backtester/platform.py`
- `prosperity_backtester/mc_backends.py`
- `prosperity_backtester/fill_models.py`
- `prosperity_backtester/simulate.py`
- `prosperity_backtester/engine.py`

Responsibilities:

- Replay market days tick by tick.
- Match visible aggressive fills exactly against the local book.
- Approximate passive fills through named fill models.
- Apply perturbations, slippage, latency-like effects and adverse-selection
  assumptions.
- Track cash, inventory, realised, unrealised and mark-to-market PnL.
- Generate synthetic Monte Carlo market days.
- Provide a default streaming Monte Carlo backend plus a classic parity backend.
- Emit compact per-session path metrics for Monte Carlo all-session bands
  without returning full non-sample paths.

### Diagnostics

Files:

- `prosperity_backtester/fair_value.py`
- `prosperity_backtester/behavior.py`
- `prosperity_backtester/live_export.py`

Responsibilities:

- Infer historical diagnostic fair values.
- Expose exact latent fair values in synthetic sessions.
- Compute markouts, cap usage, fill mix and product behaviour summaries.
- Compare replay output with live-export PnL, fills, positions and timing where
  fields exist.

### Workflow Orchestration

Files:

- `prosperity_backtester/experiments.py`
- `prosperity_backtester/__main__.py`
- `analysis/benchmark_outputs.py`
- `analysis/benchmark_runtime.py`
- `analysis/benchmark_attribution.py`
- `analysis/benchmark_backends.py`
- `analysis/benchmark_chris_reference.py`
- `analysis/architecture_bakeoff.py`

Responsibilities:

- Run replay, Monte Carlo, comparison, sweep, optimisation, calibration and
  scenario workflows.
- Load JSON config files with clear validation errors.
- Resolve trader, data and fill-config paths.
- Expose short replay and compare defaults plus convenience flags such as
  `--data`, `--merge-pnl`, `--limit`, `--print`, `--vis`, `--mc-backend` and
  `serve --latest-type`.
- Keep CLI commands thin and reproducible.
- Provide lightweight, reproducible bundle-size, runtime, attribution, backend,
  reference and architecture benchmark workflows.

### Reporting

Files:

- `prosperity_backtester/reports.py`
- `prosperity_backtester/dashboard_payload.py`
- `prosperity_backtester/bundle_attribution.py`
- `prosperity_backtester/storage.py`
- `prosperity_backtester/benchmark.py`
- `prosperity_backtester/provenance.py`

Responsibilities:

- Build dashboard payloads.
- Apply event-aware light path compaction and compact order-intent summaries.
- Aggregate Monte Carlo path bands from every session.
- Compact retained Monte Carlo `sessions`, sampled preview series and path-band
  leaves for storage while keeping JSON as the canonical dashboard contract.
- Drop duplicate `fairValueBands` when `pathBands` already carry the same
  analysis-fair and mid information.
- Write CSV sidecars, manifests, sample paths and session manifests according
  to output policy.
- Append `run_registry.jsonl` entries.
- Record command, workflow-tier, runtime-backend, data-scope, phase-timing and
  git provenance in both `dashboard.json` and `manifest.json`.
- Record reporting-phase RSS deltas and peaks for Monte Carlo reporting.
- Preserve exact and approximate assumption notes in output bundles.
- Preserve exact, compact, bucketed, qualitative and raw bundle data-contract
  notes.
- Record canonical, sidecar and debug file lists plus total bundle size in
  `manifest.json`.
- Apply light/full storage profiles and safe retention for auto-generated runs.

### Dashboard

Files:

- `dashboard/src/`
- `prosperity_backtester/server.py`
- `legacy_dashboard/dashboard.html`

Responsibilities:

- Load one or more `dashboard.json` bundles.
- Discover local bundles through `/api/runs`.
- Prefer `run_registry.jsonl` and `manifest.json` for low-cost discovery,
  latest-run routing and richer landing-screen metadata.
- Expand compact row-table sections back into normal arrays on load so the UI
  stays schema-stable.
- Render bundle-aware tabs for replay, comparison, Monte Carlo, calibration,
  optimisation, Round 2, Alpha Lab and product deep dives.
- Show compatibility messages when a bundle does not contain the data required
  by a tab.
- Surface runtime timing and reporting-RSS provenance when present.

## Data Contract

The dashboard should consume bundle fields rather than reconstructing results
from raw CSVs. Backend workflows are responsible for writing:

- `type`
- `meta`
- `assumptions`
- `dataContract`
- `datasetReports`
- workflow-specific payload sections
- exact sidecar CSV files for summary, fills and aggregate tables
- optional chart-series sidecar CSV files when requested

When adding a workflow, prefer extending this bundle contract over adding a
one-off report format.

## Design Choices

- Python remains the backend because trader compatibility, debugging and config
  iteration still matter more than raw throughput at current scale.
- Light mode is the day-to-day research profile. It keeps exact summaries and
  fills, compact paths, compact quote intent, preview-capped sampled Monte
  Carlo runs and all-session Monte Carlo path bands in `dashboard.json`.
- Monte Carlo work is chunked across workers, and unsampled sessions stream
  only the path metrics needed for final distributions and all-session path
  bands.
- Monte Carlo sampled runs are intentionally qualitative examples. Population
  path bands come from every session through bucketed path metrics.
- Full mode is for local debugging. It writes raw order rows, full series
  sidecars and sampled path files, but child bundles require an explicit
  `--save-child-bundles`.
- Round 2 is modelled as scenario analysis, not as a claim about hidden website
  mechanics.
- The React dashboard is the primary review surface. The static dashboard is
  only a fallback.

## 2026-04-23 Architecture Decision

The best current architecture remains the existing streaming-first Python
design, not a broad rewrite.

That recommendation is based on five measured facts from this pass:

- the repo kept a strong same-machine runtime lead over the local Chris Roberts
  reference
- the retained-byte gap on the matched shared no-op comparison closed, while
  the ceiling-RSS gap did not
- fresh current-local ceiling probes put the global RSS peak in execution-phase
  process-tree RSS rather than parent-only reporting RSS
- the fresh realistic-trader backend rerun kept the two Python backends alive,
  with `classic` winning `4` of `7` measured cells, `streaming` winning `3`,
  and `rust` behind in every cell
- the refreshed architecture bake-off kept MessagePack attractive at the
  contract boundary, while shared memory showed only a small transport-only win
  rather than a compelling end-to-end case

## Alternatives Considered

| Option | What it could win | What killed it in this pass | Verdict |
| --- | --- | --- | --- |
| Keep the current streaming-first Python architecture | Best end-to-end balance of throughput, install simplicity, trader compatibility and workflow breadth | Nothing killed the overall design, but the backend choice inside it is now more mixed than the earlier proof text claimed. | Keep and refine |
| Add lower-copy shared-memory worker transport | Could cut worker payload duplication and some scheduling overhead | The fresh bake-off improved the transport microbenchmark to `0.583s` versus `0.631s`, but that is still only a `1.081x` transport-only result with no end-to-end runtime or RSS proof. | Keep experimental only |
| Add optional binary serialisation or sidecars while keeping JSON canonical | Could reduce retained bytes and serialisation cost without breaking the dashboard contract | MessagePack was materially smaller and faster on the real payload, but it still does not solve the remaining execution RSS problem. A default JSON-plus-sidecar write would also increase retained bytes. | Still alive, but not landing now |
| Make Rust the default backend | Could improve ceiling throughput if native compute dominated | Same-code reruns kept `rust` slower than both `streaming` and `classic` on every realistic case, while also adding Cargo and subprocess complexity. | Keep explicit only |
| Targeted C, C++ or Rust acceleration for one kernel | Could help if one pure compute kernel dominated | Current hot spots are still mixed Python control flow, trader boundary calls, execution logic, reporting and write overhead. No isolated kernel was shown to justify crossing the native boundary yet. | Not justified now |
| Cython or Numba | Could speed up numeric loops with lower toolchain burden than C++ | The hot path is still stateful order execution and trader interaction, not a clean vector or numeric kernel. | Not justified now |
| Vectorised numeric rewrite | Could help if the engine were dominated by array-friendly maths | The engine remains event-driven, branchy and trader-callback-heavy. Profiling did not show an array-shaped bottleneck. | Wrong shape for the bottleneck |

## Current Best Architecture

The best architecture from here is:

- keep the current Python engine with `streaming` as the design default
- keep `classic` as a co-equal parity and performance backend
- keep `rust` as an explicit experiment rather than a default
- keep JSON as the canonical dashboard bundle contract
- do not land optional binary sidecars yet
- only revisit binary sidecars if retained bytes or load-time matter more than
  ceiling RSS
- defer shared-memory transport unless an end-to-end rerun shows materially
  more than the current `1.081x` transport-only gain

That is a stronger answer than "native code is not needed". The reason is not
taste. The reason is that the measured bottlenecks are still a mixed system
problem rather than a single compute kernel that native code would clearly
dominate.

## Exact Remaining Frontier

The remaining frontier is narrower than it looks:

- live worker processes dominate the tree peak (`~267 MB` = `8 x ~33-35 MB`
  Python interpreter plus imports on Windows spawn, essentially a floor for
  this architecture)
- parent-side sampled-row compaction growth is still `~44 MB`, but is not the
  global peak
- retained bytes are already led by sampled preview series and exact fill
  retention and are tracked in `docs/BENCHMARKS.md`

The obvious-looking parent-side streaming chunk-merge was attempted in this
pass and measured to worsen the global tree peak, not improve it. The previous
deferred-merge design was already optimal for tree peak:

- deferred merge design (current): parent holds pickled chunks in memory
  during execution, processes them after workers exit. Parent RSS at tree
  peak: `~135 MB`. Global tree peak: `404 MB` to `424 MB` across reruns.
- streaming merge (tried, reverted): parent merges path bands, extracts
  results and merges profile as each chunk arrives. This shifts the
  allocation into the execution window where workers are still alive. Parent
  RSS at tree peak: `~191 MB`. Global tree peak: `458 MB` on both reruns.

The reason is that global tree peak happens near the end of execution, when
all workers are still paying their `~33-35 MB` floor. Moving parent-side
allocation earlier makes the parent heavier at that exact moment, even though
it lowers the parent's own isolated peak later.

That leaves the remaining ceiling-RSS gap as an architectural cost of
`spawn`-based multiprocessing on Windows plus Python interpreter overhead per
worker. Materially lowering it would require either:

- a single-process native engine with thread-level parallelism that does not
  pay a per-tick Python/native IPC cost (the current Rust engine pays that
  cost and still loses to the Python backends on realistic cases), or
- a fork-first design that is not portable to Windows.

If retained bytes or bundle load time become the next dominant user problem,
optional binary sidecars remain the strongest still-alive architecture option.
If a later profiling pass isolates one true compute kernel, a targeted native
prototype becomes credible. Neither condition has been met strongly enough yet.
