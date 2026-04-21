import type React from 'react'
import { Activity } from 'lucide-react'
import { useStore } from '../store'
import { MetricCard } from '../components/MetricCard'
import { Card } from '../components/Card'
import { KVGrid } from '../components/KVGrid'
import { DataTable, type ColDef } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { ProductToggle } from '../components/ProductToggle'
import { BundleBadge } from '../components/BundleBadge'
import { fmtNum, fmtInt, fmtPct, fmtDate, colorForValue } from '../lib/format'
import { formatBool, getComparisonRows, interpretBundle, isFiniteNumber, numberOrNull } from '../lib/bundles'
import { POSITION_LIMIT, PRODUCT_LABELS, type DashboardPayload, type DataContractEntry, type Product } from '../types'

export function Overview() {
  const { getActiveRun, activeProduct } = useStore()
  const run = getActiveRun()

  if (!run) {
    return (
      <EmptyState
        icon={<Activity className="h-10 w-10" />}
        title="No run loaded"
        message="Load a dashboard.json bundle to begin analysis."
      />
    )
  }

  const { payload } = run
  const bundle = interpretBundle(payload)
  const meta = payload.meta
  const access = meta?.accessScenario ?? payload.summary?.access_scenario
  const provenance = meta?.provenance
  const runtime = provenance?.runtime
  const git = provenance?.git

  const datasetRows = (payload.datasetReports ?? []).map((r) => ({
    day: r.day,
    timestamps: r.validation?.timestamps,
    issue_score: r.validation?.issue_score,
    crossed_books: r.validation?.crossed_book_rows,
    one_sided: r.validation?.one_sided_book_rows,
    source: r.metadata?.source ?? r.validation?.source ?? 'historical',
  }))

  const datasetCols: ColDef<(typeof datasetRows)[0]>[] = [
    { key: 'day', header: 'Day', fmt: 'int', width: 60 },
    { key: 'timestamps', header: 'Ticks', fmt: 'int' },
    { key: 'issue_score', header: 'Issue score', fmt: 'int', tone: (v) => (Number(v) > 0 ? 'warn' : 'neutral') },
    { key: 'crossed_books', header: 'Crossed', fmt: 'int', tone: (v) => (Number(v) > 0 ? 'bad' : 'neutral') },
    { key: 'one_sided', header: 'One-sided', fmt: 'int', tone: (v) => (Number(v) > 50 ? 'warn' : 'neutral') },
    { key: 'source', header: 'Source', fmt: 'str' },
  ]

  const mafCost = numberOrNull(payload.summary?.maf_cost) ?? numberOrNull(access?.maf_cost)

  return (
    <div className="space-y-5">
      <PageHeader
        kicker="Overview / bundle review"
        title="Strategy state"
        accent="at a glance"
        description="Bundle-aware run metadata, integrity checks and the metrics that are genuinely present in the loaded dashboard JSON."
        meta={<BundleBadge payload={payload} />}
        action={<ProductToggle />}
      />

      {renderBundleOverview(payload, activeProduct)}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card title="Run metadata">
          <KVGrid
            cols={2}
            pairs={[
              { label: 'Bundle type', value: bundle.badge, tone: 'accent' },
              { label: 'Run name', value: meta?.runName },
              { label: 'Trader', value: meta?.traderName },
              { label: 'Mode', value: meta?.mode },
              { label: 'Round', value: meta?.round },
              { label: 'Fill model', value: meta?.fillModel?.name ?? 'not available for this bundle type' },
              { label: 'Access', value: access?.name ?? 'not available for this bundle type' },
              { label: 'MAF cost', value: mafCost == null ? 'not available for this bundle type' : fmtNum(mafCost) },
              { label: 'Created', value: fmtDate(meta?.createdAt) },
              { label: 'Schema v', value: meta?.schemaVersion },
              { label: 'Output profile', value: meta?.outputProfile?.profile ?? 'legacy' },
              { label: 'Dominant risk', value: payload.behaviour?.summary?.dominant_risk_product ?? 'not available for this bundle type' },
              { label: 'Dominant turnover', value: payload.behaviour?.summary?.dominant_turnover_product ?? 'not available for this bundle type' },
            ]}
          />
        </Card>

        <Card title="Dataset integrity">
          {datasetRows.length > 0 ? (
            <DataTable rows={datasetRows} cols={datasetCols} striped />
          ) : (
            <EmptyState
              title="Dataset reports not available"
              message={`${bundle.badge} does not include dataset report rows.`}
            />
          )}
        </Card>
      </div>

      {meta?.outputProfile && (
        <Card title="Output policy">
          <KVGrid
            cols={2}
            pairs={[
              { label: 'Orders', value: formatBool(meta.outputProfile.include_orders) },
              { label: 'Series sidecars', value: formatBool(meta.outputProfile.write_series_csvs) },
              { label: 'Sample path files', value: formatBool(meta.outputProfile.write_sample_path_files) },
              { label: 'Session manifests', value: formatBool(meta.outputProfile.write_session_manifests) },
              { label: 'Child bundles', value: formatBool(meta.outputProfile.write_child_bundles) },
              { label: 'Compact JSON', value: formatBool(meta.outputProfile.compact_json) },
            ]}
          />
        </Card>
      )}

      {provenance && (
        <Card title="Runtime provenance">
          <KVGrid
            cols={2}
            pairs={[
              { label: 'Workflow tier', value: provenance.workflow_tier ?? 'manual' },
              { label: 'Engine backend', value: runtime?.engine_backend ?? 'not recorded' },
              { label: 'Parallelism', value: runtime?.parallelism ?? 'not recorded' },
              { label: 'Worker count', value: runtime?.worker_count ?? 'not recorded' },
              { label: 'Session count', value: runtime?.session_count ?? 'not recorded' },
              { label: 'Sample sessions', value: runtime?.sample_session_count ?? 'not recorded' },
              { label: 'Git branch', value: git?.branch ?? 'not recorded' },
              { label: 'Git commit', value: git?.commit ? String(git.commit).slice(0, 12) : 'not recorded' },
              { label: 'Git dirty', value: formatBool(git?.dirty) },
              { label: 'Working dir', value: provenance.command?.cwd ?? 'not recorded' },
            ]}
          />
        </Card>
      )}

      <Card title="Exact vs approximate assumptions">
        {hasAssumptionNotes(payload) ? (
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <AssumptionList title="Exact" tone="good" items={payload.assumptions?.exact ?? []} />
            <AssumptionList title="Approximate" tone="warn" items={payload.assumptions?.approximate ?? []} />
          </div>
        ) : (
          <EmptyState title="Assumption notes not available" message="This bundle does not include exact or approximate assumption notes." />
        )}
      </Card>

      {payload.dataContract?.length ? (
        <Card title="Bundle data contract" subtitle="Storage fidelity inside this bundle. Use the assumptions card above for model uncertainty and interpretation limits.">
          <div className="grid gap-4 lg:grid-cols-2">
            {payload.dataContract.map((entry) => (
              <div key={entry.key} className="rounded-lg border border-border bg-white/[0.025] p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="font-display text-sm font-semibold uppercase tracking-[0.08em] text-txt">{entry.label}</div>
                  <span className={dataContractToneClass(entry.fidelity)}>{dataContractLabel(entry.fidelity)}</span>
                </div>
                <div className="mt-2 text-sm leading-6 text-txt-soft">{entry.notes}</div>
                <div className="hud-label mt-3 text-muted">Stored in {entry.location}</div>
              </div>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  )
}

function renderBundleOverview(payload: DashboardPayload, activeProduct: Product): React.ReactNode {
  const bundle = interpretBundle(payload)

  if (bundle.type === 'replay') return <ReplayOverview payload={payload} activeProduct={activeProduct} />
  if (bundle.type === 'monte_carlo') return <MonteCarloOverview payload={payload} />
  if (bundle.type === 'comparison') return <ComparisonOverview payload={payload} />
  if (bundle.type === 'round2_scenarios') return <Round2Overview payload={payload} />
  if (bundle.type === 'calibration') return <CalibrationOverview payload={payload} />
  if (bundle.type === 'optimization') return <OptimizationOverview payload={payload} />

  return (
    <Card title="Bundle metrics">
      <EmptyState title="Unknown bundle schema" message="The dashboard could not classify this bundle type confidently." />
    </Card>
  )
}

function ReplayOverview({ payload, activeProduct }: { payload: DashboardPayload; activeProduct: Product }) {
  const summary = payload.summary
  const productSummary = summary?.per_product?.[activeProduct]
  const behaviour = payload.behaviour?.per_product?.[activeProduct]
  const productLabel = PRODUCT_LABELS[activeProduct] ?? activeProduct
  const cards: React.ReactNode[] = []

  if (summary) {
    cards.push(
      <MetricCard key="final-pnl" label="Final PnL" value={fmtNum(summary.final_pnl)} sub={`Max DD ${fmtNum(summary.max_drawdown)}`} tone={colorForValue(summary.final_pnl)} />,
      <MetricCard key="fills" label="Fill count" value={fmtInt(summary.fill_count)} sub={`Orders ${fmtInt(summary.order_count)}`} />,
      <MetricCard key="breaches" label="Limit breaches" value={fmtInt(summary.limit_breaches)} tone={summary.limit_breaches > 0 ? 'bad' : 'good'} sub="Batch-dropped order groups" />,
    )
  }

  if (productSummary) {
    const capUsage = isFiniteNumber(productSummary.final_position)
      ? Math.abs(productSummary.final_position) / POSITION_LIMIT
      : null
    cards.push(
      <MetricCard key="product-mtm" label={`${productLabel} MTM`} value={fmtNum(productSummary.final_mtm)} tone={colorForValue(productSummary.final_mtm)} sub={`Realised ${fmtNum(productSummary.realised)}`} />,
      <MetricCard key="product-position" label={`${productLabel} position`} value={fmtInt(productSummary.final_position)} sub={`Cap ${fmtPct(capUsage)}`} tone={capUsage != null && capUsage >= 1 ? 'warn' : 'neutral'} />,
    )
  }

  if (behaviour) {
    cards.push(
      <MetricCard key="cap-usage" label="Cap usage ratio" value={fmtPct(behaviour.cap_usage_ratio)} tone={numberOrNull(behaviour.cap_usage_ratio) != null && Number(behaviour.cap_usage_ratio) > 0.6 ? 'warn' : 'neutral'} sub={`Peak pos ${fmtInt(behaviour.peak_abs_position)}`} />,
      <MetricCard key="markout" label="Fill markout +5" value={fmtNum(behaviour.average_fill_markout_5)} tone={colorForValue(behaviour.average_fill_markout_5)} sub="Average 5-tick signed edge" />,
    )
  }

  return cards.length ? (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">{cards}</div>
  ) : (
    <Card title="Replay metrics">
      <EmptyState title="Replay summary not available" message="This replay bundle does not include summary metrics." />
    </Card>
  )
}

function MonteCarloOverview({ payload }: { payload: DashboardPayload }) {
  const summary = payload.monteCarlo?.summary
  if (!summary) {
    return (
      <Card title="Monte Carlo metrics">
        <EmptyState title="Monte Carlo summary not available" message="This monte_carlo bundle does not include `monteCarlo.summary`." />
      </Card>
    )
  }

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      <MetricCard label="MC mean" value={fmtNum(summary.mean)} tone={colorForValue(summary.mean)} sub={`Sessions ${fmtInt(summary.session_count)}`} />
      <MetricCard label="MC P05" value={fmtNum(summary.p05)} tone={colorForValue(summary.p05)} sub={`ES05 ${fmtNum(summary.expected_shortfall_05)}`} />
      <MetricCard label="MC median" value={fmtNum(summary.p50)} tone={colorForValue(summary.p50)} sub={`P95 ${fmtNum(summary.p95)}`} />
      <MetricCard label="Positive rate" value={fmtPct(summary.positive_rate)} tone={summary.positive_rate > 0.5 ? 'good' : 'warn'} sub={`Std ${fmtNum(summary.std)}`} />
    </div>
  )
}

function ComparisonOverview({ payload }: { payload: DashboardPayload }) {
  const rows = getComparisonRows(payload)
  const diagnostics = payload.comparisonDiagnostics ?? {}
  const winner = rows[0]
  const gap = numberOrNull(diagnostics.gap_to_second)

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      <MetricCard label="Comparison rows" value={fmtInt(numberOrNull(diagnostics.row_count) ?? rows.length)} sub="Precomputed trader rows" />
      <MetricCard label="Winner" value={String(diagnostics.winner ?? winner?.trader ?? 'not available')} sub={winner ? `PnL ${fmtNum(winner.final_pnl)}` : 'No row winner present'} tone="accent" />
      <MetricCard label="Gap to second" value={fmtNum(gap)} tone={colorForValue(gap)} sub="Winner minus runner-up" />
      <MetricCard label="Scenario count" value={fmtInt(numberOrNull(diagnostics.scenario_count))} sub={`MAF rows ${fmtInt(numberOrNull(diagnostics.maf_sensitive_rows))}`} />
    </div>
  )
}

function Round2Overview({ payload }: { payload: DashboardPayload }) {
  const round2 = payload.round2
  const scenarioRows = round2?.scenarioRows ?? []
  const winnerRows = round2?.winnerRows ?? []
  const bestRow = maxByNumber(scenarioRows, (row) => row.final_pnl)
  const bestBreakEven = maxNumber(scenarioRows.map((row) => row.break_even_maf_vs_no_access))
  const rankingShifts = winnerRows.filter((row) => row.ranking_changed_vs_no_access === true).length
  const scenarioCount = new Set(scenarioRows.map((row) => row.scenario)).size

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      <MetricCard label="Scenarios" value={fmtInt(scenarioCount)} sub={`Rows ${fmtInt(scenarioRows.length)}`} />
      <MetricCard label="Best net PnL" value={fmtNum(bestRow?.final_pnl)} tone={colorForValue(bestRow?.final_pnl)} sub={bestRow?.trader ?? 'No winning row'} />
      <MetricCard label="Best break-even MAF" value={fmtNum(bestBreakEven)} tone={colorForValue(bestBreakEven)} sub="Access edge before fee" />
      <MetricCard label="Ranking shifts" value={fmtInt(rankingShifts)} tone={rankingShifts > 0 ? 'warn' : 'neutral'} sub="Versus no-access baseline" />
    </div>
  )
}

function CalibrationOverview({ payload }: { payload: DashboardPayload }) {
  const calibration = payload.calibration
  const best = calibration?.best
  const candidateCount = numberOrNull(calibration?.diagnostics?.candidate_count) ?? calibration?.grid?.length

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      <MetricCard label="Candidates" value={fmtInt(candidateCount)} sub="Calibration grid size" />
      <MetricCard label="Best score" value={fmtNum(numberOrNull(best?.score))} sub="Lower is better" />
      <MetricCard label="Profit error" value={fmtNum(numberOrNull(best?.profit_error))} tone={colorForValue(numberOrNull(best?.profit_error))} sub="Sim minus live profit" />
      <MetricCard label="Path RMSE" value={fmtNum(numberOrNull(best?.path_rmse))} sub={String(best?.fill_model ?? 'Best model not available')} />
    </div>
  )
}

function OptimizationOverview({ payload }: { payload: DashboardPayload }) {
  const opt = payload.optimization
  const bestRow = opt?.rows?.[0]
  const bestDownsideVariant = opt?.diagnostics?.best_downside_variant
  const bestDownside = opt?.rows?.find((row) => row.variant === bestDownsideVariant)

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      <MetricCard label="Variants tested" value={fmtInt(opt?.diagnostics?.variant_count ?? opt?.rows?.length)} sub="Parameter combinations" />
      <MetricCard label="Best score" value={fmtNum(bestRow?.score)} sub={bestRow?.variant ?? 'Best variant not available'} />
      <MetricCard label="Best replay PnL" value={fmtNum(bestRow?.replay_final_pnl)} tone={colorForValue(bestRow?.replay_final_pnl)} sub={opt?.diagnostics?.best_replay_variant} />
      <MetricCard label="Best P05" value={fmtNum(bestDownside?.mc_p05)} tone={colorForValue(bestDownside?.mc_p05)} sub={opt?.diagnostics?.best_downside_variant} />
    </div>
  )
}

function AssumptionList({ title, tone, items }: { title: string; tone: 'good' | 'warn'; items: string[] }) {
  return (
    <div>
      <div className={tone === 'good' ? 'mb-3 text-xs font-semibold uppercase tracking-wider text-good' : 'mb-3 text-xs font-semibold uppercase tracking-wider text-warn'}>
        {title}
      </div>
      {items.length ? (
        <ul className="space-y-2">
          {items.map((item, i) => (
            <li key={i} className="flex items-start gap-2 text-xs text-txt">
              <span className={tone === 'good' ? 'mt-0.5 text-good' : 'mt-0.5 text-warn'}>{tone === 'good' ? 'OK' : '~'}</span>
              {item}
            </li>
          ))}
        </ul>
      ) : (
        <div className="text-sm text-muted">not available for this bundle type</div>
      )}
    </div>
  )
}

function hasAssumptionNotes(payload: DashboardPayload): boolean {
  return Boolean(payload.assumptions?.exact?.length || payload.assumptions?.approximate?.length)
}

function dataContractLabel(fidelity: DataContractEntry['fidelity']): string {
  if (fidelity === 'exact') return 'Exact'
  if (fidelity === 'compact') return 'Compact'
  if (fidelity === 'bucketed') return 'Bucketed'
  if (fidelity === 'qualitative') return 'Qualitative'
  if (fidelity === 'raw') return 'Raw'
  if (fidelity === 'derived') return 'Derived'
  return String(fidelity)
}

function dataContractToneClass(fidelity: DataContractEntry['fidelity']): string {
  if (fidelity === 'exact' || fidelity === 'raw') {
    return 'hud-label rounded-lg border border-good/25 bg-good/10 px-2 py-1 text-good'
  }
  if (fidelity === 'compact' || fidelity === 'bucketed') {
    return 'hud-label rounded-lg border border-accent/25 bg-accent/10 px-2 py-1 text-accent'
  }
  if (fidelity === 'qualitative' || fidelity === 'derived') {
    return 'hud-label rounded-lg border border-warn/25 bg-warn/10 px-2 py-1 text-warn'
  }
  return 'hud-label rounded-lg border border-border bg-white/[0.025] px-2 py-1 text-muted'
}

function maxNumber(values: unknown[]): number | null {
  const clean = values.map(numberOrNull).filter((value): value is number => value != null)
  if (!clean.length) return null
  return Math.max(...clean)
}

function maxByNumber<T>(rows: T[], getValue: (row: T) => unknown): T | null {
  let best: T | null = null
  let bestValue: number | null = null
  for (const row of rows) {
    const value = numberOrNull(getValue(row))
    if (value == null) continue
    if (bestValue == null || value > bestValue) {
      best = row
      bestValue = value
    }
  }
  return best
}
