# New Round Checklist

Use this list when a new Prosperity round drops.

## 1. Data And Product Registration

- add the new round CSV fixtures under `data/round<round>/`
- update `prosperity_backtester/metadata.py` with product labels, limits and any round-specific metadata
- confirm `dataset.py` accepts the new file names, products and timestamp shape
- run `python -m prosperity_backtester inspect --round <round> --data data/round<round> --days ... --json`

## 2. Mechanism Hooks

- check whether replay needs new exchange mechanics, conversions, baskets or derivatives
- add the smallest hook needed in `platform.py`, `simulate.py` or round-specific helpers
- keep deterministic replay exact where the public inputs allow it
- document every new approximation boundary in `docs/ASSUMPTIONS.md`

## 3. Round Templates

- copy or adapt the nearest config under `configs/`
- add a new research bundle template under `docs/bundle_templates/` if the review workflow changes
- add one lightweight strategy or fixture under `examples/` if tests need round-specific coverage

## 4. Dashboard Compatibility

- make sure the bundle `type` and payload shape remain explicit
- add any new aggregate rows or summaries to `reports.py`
- check `dashboard/src/lib/bundles.ts` and the relevant view tabs
- run `npm test --prefix dashboard`
- run `npm run build --prefix dashboard`

## 5. Trust Checks

- add one replay smoke test for the new round
- add one output-contract or manifest-provenance test if the bundle shape changes
- add one dashboard adapter test if the new round introduces a new bundle type or compatibility branch
- rerun `python -m pytest -q`

## 6. Performance And Benchmarks

- rerun `analysis/profile_replay.py` on the default daily replay loop
- rerun `analysis/benchmark_outputs.py`
- rerun `analysis/benchmark_runtime.py`
- if you changed Monte Carlo hot-path code, rerun one benchmark with the default backend and one with `--mc-backend classic`
- refresh any workflow numbers in `README.md`, `docs/WORKFLOWS.md` and `docs/BENCHMARKS.md`

## 7. Docs And Handoff

- update `README.md` with the new default commands
- update `docs/WORKFLOWS.md` if the fast, validation or forensic loops changed
- update `docs/OUTPUTS.md` if bundle shape or provenance changed
- update `docs/ARCHITECTURE.md` if a new layer or hook was added
- update `docs/REFERENCE_COMPARISON.md` only if the repo's public positioning actually changed

## 8. Release Sanity Check

- confirm `--open`, `serve --latest` and `serve --latest-type` still work
- confirm auto-generated bundle naming still reads cleanly
- confirm retention still prunes only timestamped auto-run directories
- confirm the final docs reflect the real current defaults rather than aspirational ones
