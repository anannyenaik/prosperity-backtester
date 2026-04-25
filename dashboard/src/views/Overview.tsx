import type React from 'react'
import { Activity, CheckCircle2, CircleDot } from 'lucide-react'
import { useStore } from '../store'
import { MetricCard } from '../components/MetricCard'
import { Card } from '../components/Card'
import { KVGrid } from '../components/KVGrid'
import { DataTable, type ColDef } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { ProductToggle } from '../components/ProductToggle'
import { BundleBadge } from '../components/BundleBadge'
import { PhaseTimings } from '../components/PhaseTimings'
import { fmtNum, fmtInt, fmtPct, fmtDate, fmtBytes, colorForValue } from '../lib/format'
import { formatBool, getComparisonRows, getTabAvailability, interpretBundle, isFiniteNumber, numberOrNull } from '../lib/bundles'
import { positionLimit, productLabel, productShortLabel } from '../lib/products'
import { POSITION_LIMIT, PRODUCT_LABELS, type DashboardPayload, type DataContractEntry, type Product, type WorkspaceIntegrity, type WorkspaceSectionKey, type WorkspaceSourceBundle } from '../types'

const WORKSPACE_SECTION_KEYS: WorkspaceSectionKey[] = [
  'overview',
  'replay',
  'montecarlo',
  'calibration',
  'compare',
  'optimize',
  'round2',
  'inspect',
  'osmium',
  'pepper',
  'alpha',
]

const WORKSPACE_SECTION_LABELS: Record<WorkspaceSectionKey, string> = {
  overview: 'Overview',
  replay: 'Replay',
  montecarlo: 'Monte Carlo',
  calibration: 'Calibration',
  compare: 'Comparison',
  optimize: 'Optimisation',
  round2: 'Round 2',
  inspect: 'Inspect',
  osmium: 'Osmium',
  pepper: 'Pepper',
  alpha: 'Alpha Lab',
}

function workspaceSectionLabel(key: string): string {
  return WORKSPACE_SECTION_LABELS[key as WorkspaceSectionKey] ?? key
}

function formatWorkspaceSectionList(value: string[] | WorkspaceSectionKey[] | null | undefined): string {
  if (!value?.length) return 'None'
  return value.map((section) => workspaceSectionLabel(section)).join(', ')
}

function workspaceIntegrityLabel(status: WorkspaceIntegrity['status'] | undefined): string {
  if (status === 'overlap') return 'Overlap flagged'
  if (status === 'partial') return 'Partial coverage'
  return 'Clean assembly'
}

function workspaceIntegrityTone(status: WorkspaceIntegrity['status'] | undefined): 'good' | 'warn' {
  return status === 'overlap' || status === 'partial' ? 'warn' : 'good'
}

function shortSourcePath(value: string | null | undefined): string {
  if (!value) return 'not recorded'
  const parts = value.replace(/\\/g, '/').split('/')
  return parts.slice(-2).join('/')
}

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
  const roundNumber = numberOrNull(meta?.round)
  const showRound2Access = roundNumber === 2 || payload.type === 'round2_scenarios' || Boolean(payload.round2)
  const provenance = meta?.provenance
  const runtime = provenance?.runtime
  const git = provenance?.git
  const phaseTimings = runtime?.phase_timings_seconds
  const phaseRss = runtime?.phase_rss_bytes
  const dataScope = runtime?.data_scope
  const reportingSeconds = sumNumberValues([
    phaseTimings?.sample_row_compaction_seconds,
    phaseTimings?.dashboard_build_seconds,
    phaseTimings?.bundle_write_seconds,
  ])
  const reportingPeak = maxNumber([
    phaseRss?.sample_row_compaction?.rss_peak_bytes,
    phaseRss?.dashboard_build?.rss_peak_bytes,
    phaseRss?.bundle_write?.rss_peak_bytes,
    phaseRss?.manifest_refresh?.rss_peak_bytes,
  ])
  const reportingDeltaLeader = maxLabelledNumber([
    ['Sample row compaction', phaseRss?.sample_row_compaction?.rss_delta_bytes],
    ['Dashboard build', phaseRss?.dashboard_build?.rss_delta_bytes],
    ['Bundle write', phaseRss?.bundle_write?.rss_delta_bytes],
    ['Manifest refresh', phaseRss?.manifest_refresh?.rss_delta_bytes],
  ])

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
  const optionDiagnosticDays = Array.isArray(payload.optionDiagnostics?.days)
    ? (payload.optionDiagnostics.days as Array<Record<string, unknown>>)
    : []
  const latestOptionDiagnostics = optionDiagnosticDays[optionDiagnosticDays.length - 1]
  const optionChainRows = Array.isArray(latestOptionDiagnostics?.vouchers)
    ? (latestOptionDiagnostics.vouchers as Array<Record<string, unknown>>).map((row) => {
        const product = String(row.product ?? '')
        const productSummary = payload.summary?.per_product?.[product]
        const warnings = Array.isArray(row.warnings) ? row.warnings.map(String) : []
        return {
          ...row,
          product,
          include_in_surface_fit: row.include_in_surface_fit === true,
          fit_group: row.include_in_surface_fit === true ? 'Surface fit' : 'Diagnostic',
          position: productSummary?.final_position ?? null,
          pnl_contribution: productSummary?.final_mtm ?? null,
          warning_count: warnings.length,
          warning_text: warnings.join('\n'),
        }
      })
    : []
  const optionSurfaceFitCount = optionChainRows.filter((row) => row.include_in_surface_fit === true).length
  const optionWarningCount = optionChainRows.reduce((total, row) => total + Number(row.warning_count ?? 0), 0)
  const optionChainCols: ColDef<Record<string, unknown>>[] = [
    {
      key: 'product',
      header: 'Product',
      fmt: 'str',
      render: (_value, row) => {
        const product = String(row.product ?? '')
        return (
          <span className="block min-w-[92px]">
            <span className="block font-display text-xs font-semibold uppercase tracking-[0.08em] text-txt">
              {productShortLabel(payload, product)}
            </span>
            <span className="hud-label mt-1 block text-muted">{productLabel(payload, product)}</span>
          </span>
        )
      },
    },
    { key: 'fit_group', header: 'Fit', fmt: 'str' },
    { key: 'strike', header: 'Strike', fmt: 'int', align: 'right' },
    { key: 'average_mid', header: 'Mid', fmt: 'num', digits: 2, align: 'right' },
    { key: 'average_spread', header: 'Spread', fmt: 'num', digits: 2, align: 'right' },
    { key: 'iv_median', header: 'IV', fmt: 'num', digits: 3, align: 'right' },
    { key: 'fitted_iv_mean', header: 'Fit IV', fmt: 'num', digits: 3, align: 'right' },
    { key: 'model_fair_mean', header: 'Fair', fmt: 'num', digits: 2, align: 'right' },
    { key: 'residual_median', header: 'Residual', fmt: 'num', digits: 2, align: 'right', tone: (v) => colorForValue(Number(v)) },
    { key: 'delta_mean', header: 'Delta', fmt: 'num', digits: 3, align: 'right' },
    { key: 'position', header: 'Pos', fmt: 'int', align: 'right' },
    { key: 'pnl_contribution', header: 'PnL', fmt: 'num', digits: 1, align: 'right', tone: (v) => colorForValue(Number(v)) },
    {
      key: 'warning_count',
      header: 'Notes',
      fmt: 'int',
      render: (_value, row) => {
        const count = Number(row.warning_count ?? 0)
        return (
          <span
            title={String(row.warning_text ?? '')}
            className={count > 0 ? 'rounded-md border border-warn/25 bg-warn/10 px-2 py-1 text-warn' : 'text-muted'}
          >
            {count > 0 ? `${count} note${count === 1 ? '' : 's'}` : 'Clean'}
          </span>
        )
      },
    },
  ]
  const runMetadataPairs = [
    { label: 'Bundle type', value: bundle.badge, tone: 'accent' as const },
    { label: 'Run name', value: meta?.runName },
    { label: 'Trader', value: meta?.traderName },
    { label: 'Mode', value: meta?.mode },
    { label: 'Round', value: meta?.round },
    { label: 'Fill model', value: meta?.fillModel?.name ?? 'not available for this bundle type' },
    ...(showRound2Access
      ? [
          { label: 'Access', value: access?.name ?? 'not available for this bundle type' },
          { label: 'MAF cost', value: mafCost == null ? 'not available for this bundle type' : fmtNum(mafCost) },
        ]
      : []),
    { label: 'Created', value: fmtDate(meta?.createdAt) },
    { label: 'Schema v', value: meta?.schemaVersion },
    { label: 'Output profile', value: meta?.outputProfile?.profile ?? 'legacy' },
    { label: 'Dominant risk', value: payload.behaviour?.summary?.dominant_risk_product ?? 'not available for this bundle type' },
    { label: 'Dominant turnover', value: payload.behaviour?.summary?.dominant_turnover_product ?? 'not available for this bundle type' },
  ]

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
            pairs={runMetadataPairs}
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

      {Array.isArray(payload.optionDiagnostics?.days) && payload.optionDiagnostics.days.length > 0 && (
        <Card title="Round 3 option diagnostics">
          <KVGrid
            cols={2}
            pairs={[
              { label: 'Underlying', value: String(payload.optionDiagnostics.underlying ?? 'not recorded'), tone: 'accent' },
              { label: 'Days analysed', value: fmtInt(payload.optionDiagnostics.days.length) },
              { label: 'Surface-fit vouchers', value: Array.isArray(payload.optionDiagnostics.surface_fit_vouchers) ? payload.optionDiagnostics.surface_fit_vouchers.join(', ') : 'not recorded' },
              { label: 'Final TTE', value: payload.optionDiagnostics.final_tte_days == null ? 'not recorded' : `${payload.optionDiagnostics.final_tte_days} days` },
            ]}
          />
        </Card>
      )}

      {optionChainRows.length > 0 && (
        <Card
          title="Round 3 option chain"
          subtitle={`Compact day ${String(latestOptionDiagnostics?.day ?? 'latest')} voucher diagnostics. Fair values are diagnostic only; replay uses observed books.`}
          action={
            <div className="flex flex-wrap justify-end gap-2">
              <span className="hud-label rounded-lg border border-accent/20 bg-accent/10 px-2.5 py-1 text-accent">
                {fmtInt(optionSurfaceFitCount)} surface-fit
              </span>
              <span className="hud-label rounded-lg border border-warn/20 bg-warn/10 px-2.5 py-1 text-warn">
                {fmtInt(optionWarningCount)} notes
              </span>
            </div>
          }
        >
          <DataTable rows={optionChainRows} cols={optionChainCols} striped />
        </Card>
      )}

      {meta?.outputProfile && (
        <Card title="Output policy">
          <KVGrid
            cols={2}
            pairs={[
              { label: 'MC sample preview rows', value: meta.outputProfile.max_sample_preview_rows_per_series ?? 'legacy' },
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
              { label: 'MC backend', value: runtime?.monte_carlo_backend ?? 'not recorded' },
              { label: 'Parallelism', value: runtime?.parallelism ?? 'not recorded' },
              { label: 'Worker count', value: runtime?.worker_count ?? 'not recorded' },
              { label: 'Session count', value: runtime?.session_count ?? 'not recorded' },
              { label: 'Sample sessions', value: runtime?.sample_session_count ?? 'not recorded' },
              { label: 'Data source', value: dataScope?.source ?? 'not recorded' },
              { label: 'Days', value: formatDayList(dataScope?.days) },
              { label: 'MC session wall', value: formatSecondsValue(phaseTimings?.session_execution_wall_seconds) },
              { label: 'Reporting time', value: formatSecondsValue(reportingSeconds) },
              { label: 'Git branch', value: git?.branch ?? 'not recorded' },
              { label: 'Git commit', value: git?.commit ? String(git.commit).slice(0, 12) : 'not recorded' },
              { label: 'Git dirty', value: formatBool(git?.dirty) },
              { label: 'Working dir', value: provenance.command?.cwd ?? 'not recorded' },
            ]}
          />
        </Card>
      )}

      {phaseRss && (
        <Card title="Reporting RSS" subtitle="Measured memory growth inside sampled-row compaction, dashboard assembly and bundle writing.">
          <KVGrid
            cols={2}
            pairs={[
              { label: 'Before reporting', value: fmtBytes(numberOrNull(phaseRss.before_reporting_rss_bytes)) },
              { label: 'Peak during reporting', value: fmtBytes(reportingPeak), tone: 'warn' },
              { label: 'Compaction delta', value: fmtBytes(numberOrNull(phaseRss.sample_row_compaction?.rss_delta_bytes)) },
              { label: 'Compaction peak', value: fmtBytes(numberOrNull(phaseRss.sample_row_compaction?.rss_peak_bytes)) },
              { label: 'Dashboard build delta', value: fmtBytes(numberOrNull(phaseRss.dashboard_build?.rss_delta_bytes)) },
              { label: 'Bundle write delta', value: fmtBytes(numberOrNull(phaseRss.bundle_write?.rss_delta_bytes)) },
              { label: 'After reporting', value: fmtBytes(numberOrNull(phaseRss.after_reporting_rss_bytes)) },
              { label: 'Largest RSS jump', value: reportingDeltaLeader?.label ?? 'not recorded', tone: 'accent' },
            ]}
          />
        </Card>
      )}

      <PhaseTimings
        phaseTimings={phaseTimings as Record<string, unknown> | null | undefined}
        sessionCount={numberOrNull(runtime?.session_count)}
        workerCount={numberOrNull(runtime?.worker_count)}
        monteCarloBackend={runtime?.monte_carlo_backend ?? null}
      />

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

  if (bundle.isWorkspace) return <WorkspaceOverview payload={payload} activeProduct={activeProduct} />
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

function WorkspaceOverview({ payload, activeProduct }: { payload: DashboardPayload; activeProduct: Product }) {
  const workspace = payload.workspace
  const bundle = interpretBundle(payload)
  const integrity = workspace?.integrity
  const sectionCards = WORKSPACE_SECTION_KEYS.map((key) => {
    const availability =
      key === 'overview'
        ? {
            supported: true,
            title: 'Overview available',
            message: 'Workspace overview is always available.',
          }
        : getTabAvailability(payload, key)

    return {
      key,
      label: workspaceSectionLabel(key),
      availability,
      sourcePath: integrity?.promotedBy?.[key],
    }
  })
  const availableCount = sectionCards.filter((section) => section.availability.supported).length
  const missingLabels = sectionCards
    .filter((section) => !section.availability.supported)
    .map((section) => section.label)
  const overlapCount = Object.values(integrity?.shadowedBy ?? {}).filter((paths) => Array.isArray(paths) && paths.length > 0).length
  const promotedRows = (Object.entries(integrity?.promotedBy ?? {}) as Array<[WorkspaceSectionKey, string]>)
    .sort((left, right) => WORKSPACE_SECTION_KEYS.indexOf(left[0]) - WORKSPACE_SECTION_KEYS.indexOf(right[0]))

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricCard
          label="Available sections"
          value={availableCount}
          sub={`${sectionCards.length} workspace tabs visible`}
          tone="good"
        />
        <MetricCard
          label="Source bundles"
          value={workspace?.sources.length ?? 0}
          sub={workspace?.name ?? 'workspace'}
          tone="accent"
        />
        <MetricCard
          label="Missing sections"
          value={sectionCards.length - availableCount}
          sub={missingLabels.length ? missingLabels.slice(0, 2).join(', ') : 'Full tab coverage'}
          tone={missingLabels.length > 0 ? 'warn' : 'good'}
        />
        <MetricCard
          label="Integrity"
          value={workspaceIntegrityLabel(integrity?.status)}
          sub={overlapCount > 0 ? `${overlapCount} overlapped sections retained as provenance` : 'No overlapping section claims'}
          tone={workspaceIntegrityTone(integrity?.status)}
        />
      </div>

      <Card
        title="Workspace control tower"
        subtitle="Every dashboard section stays visible, with honest enablement and source provenance for the data this workspace actually carries."
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-6">
          {sectionCards.map((section) => {
            const isPresent = section.availability.supported
            return (
              <div
                key={section.key}
                className={
                  isPresent
                    ? 'rounded-lg border border-good/30 bg-good/10 px-3 py-3'
                    : 'rounded-lg border border-border bg-white/[0.02] px-3 py-3 opacity-70'
                }
                title={section.availability.supported ? section.availability.message : section.availability.title}
              >
                <div className="flex items-center gap-2">
                  {isPresent ? (
                    <CheckCircle2 className="h-4 w-4 text-good" />
                  ) : (
                    <CircleDot className="h-4 w-4 text-muted" />
                  )}
                  <span className="font-display text-xs font-semibold uppercase tracking-[0.08em]">{section.label}</span>
                </div>
                <div className="hud-label mt-2 text-muted">{isPresent ? 'available' : 'not included in this workspace'}</div>
                <div className="mt-2 text-xs leading-5 text-txt-soft">{section.availability.message}</div>
                {section.sourcePath && (
                  <div className="hud-label mt-3 text-accent-2">from {shortSourcePath(section.sourcePath)}</div>
                )}
              </div>
            )
          })}
        </div>

        {missingLabels.length > 0 && (
          <div className="mt-4 rounded-lg border border-border bg-white/[0.02] px-4 py-3 text-sm leading-6 text-txt-soft">
            Missing sections: {missingLabels.join(', ')}.
          </div>
        )}

        {promotedRows.length > 0 && (
          <div className="mt-4 grid gap-2 lg:grid-cols-2 xl:grid-cols-3">
            {promotedRows.map(([section, path]) => (
              <div key={`${section}:${path}`} className="rounded-lg border border-border bg-white/[0.025] px-3 py-3">
                <div className="hud-label text-muted">Promoted source</div>
                <div className="mt-2 font-display text-xs font-semibold uppercase tracking-[0.08em] text-txt">
                  {workspaceSectionLabel(section)}
                </div>
                <div className="mt-2 text-sm text-txt-soft">{shortSourcePath(path)}</div>
                <div className="hud-label mt-2 text-accent-2">{path}</div>
              </div>
            ))}
          </div>
        )}

        {integrity?.warnings?.length ? (
          <div className="mt-4 rounded-lg border border-warn/20 bg-warn/10 px-4 py-3">
            <div className="hud-label text-warn">Integrity notes</div>
            <div className="mt-2 space-y-2 text-sm leading-6 text-txt-soft">
              {integrity.warnings.map((warning, index) => (
                <div key={index}>{warning}</div>
              ))}
            </div>
          </div>
        ) : null}
      </Card>

      <Card
        title="Workspace provenance"
        subtitle="Assembly metadata for reproducibility, plus the command and git context recorded when this workspace bundle was built."
      >
        <KVGrid
          cols={2}
          pairs={[
            { label: 'Workspace', value: workspace?.name ?? payload.meta?.runName, tone: 'accent' },
            { label: 'Built', value: fmtDate(workspace?.createdAt ?? payload.meta?.createdAt) },
            { label: 'Source bundles', value: workspace?.sources.length ?? 0 },
            { label: 'Integrity status', value: workspaceIntegrityLabel(integrity?.status), tone: workspaceIntegrityTone(integrity?.status) },
            { label: 'Sections present', value: formatWorkspaceSectionList(workspace?.sections?.present) },
            { label: 'Sections missing', value: formatWorkspaceSectionList(workspace?.sections?.missing) },
            { label: 'Git branch', value: workspace?.gitBranch ?? 'not recorded' },
            { label: 'Git commit', value: workspace?.gitCommit ? String(workspace.gitCommit).slice(0, 12) : 'not recorded' },
            { label: 'Git dirty', value: formatBool(workspace?.gitDirty) },
            { label: 'Assembly command', value: workspace?.command ?? 'not recorded' },
            { label: 'Notes', value: workspace?.notes ?? 'not recorded' },
          ]}
        />
      </Card>

      {workspace && workspace.sources.length > 0 && (
        <Card
          title="Source bundles"
          subtitle="The single-purpose bundles assembled into this workspace, including which sections were promoted and which were retained only as supporting provenance."
        >
          <WorkspaceSourceTable sources={workspace.sources} />
        </Card>
      )}

      {bundle.hasReplaySummary && <ReplayOverview payload={payload} activeProduct={activeProduct} />}
      {bundle.hasMonteCarlo && <MonteCarloOverview payload={payload} />}
      {bundle.hasComparisonRows && !bundle.hasRound2Rows && <ComparisonOverview payload={payload} />}
      {bundle.hasRound2Rows && <Round2Overview payload={payload} />}
      {bundle.hasCalibration && <CalibrationOverview payload={payload} />}
      {bundle.hasOptimization && <OptimizationOverview payload={payload} />}
    </div>
  )
}

function WorkspaceSourceTable({ sources }: { sources: WorkspaceSourceBundle[] }) {
  const cols: ColDef<WorkspaceSourceBundle>[] = [
    { key: 'name', header: 'Source', fmt: 'str' },
    { key: 'type', header: 'Type', fmt: 'str' },
    {
      key: 'promotedSections',
      header: 'Loaded',
      fmt: 'str',
      render: (_value, row) => (row.promotedSections?.length ? formatWorkspaceSectionList(row.promotedSections) : 'Provenance only'),
    },
    {
      key: 'sections',
      header: 'Can power',
      fmt: 'str',
      render: (_value, row) => formatWorkspaceSectionList(row.sections),
    },
    {
      key: 'profile',
      header: 'Trader / profile',
      fmt: 'str',
      render: (_value, row) => {
        const parts = [row.traderName, row.profile].filter((value): value is string => Boolean(value))
        return parts.length ? parts.join(' / ') : 'not recorded'
      },
    },
    {
      key: 'mode',
      header: 'Workflow / git',
      fmt: 'str',
      render: (_value, row) => {
        const parts = [
          row.mode,
          row.workflowTier,
          row.engineBackend,
          row.monteCarloBackend ? `mc:${row.monteCarloBackend}` : null,
          row.gitCommit ? String(row.gitCommit).slice(0, 8) : null,
          row.gitDirty ? 'dirty' : null,
        ].filter((value): value is string => Boolean(value))
        return parts.length ? parts.join(' / ') : 'not recorded'
      },
    },
    { key: 'createdAt', header: 'Created', fmt: 'str', render: (_value, row) => fmtDate(row.createdAt) },
    { key: 'path', header: 'Path', fmt: 'str' },
  ]
  const notes = sources.filter((source) => source.note)

  return (
    <div className="space-y-4">
      <DataTable rows={sources} cols={cols} striped />
      {notes.length > 0 && (
        <div className="grid gap-3 lg:grid-cols-2">
          {notes.map((source) => (
            <div key={`${source.path}:note`} className="rounded-lg border border-border bg-white/[0.025] px-4 py-3">
              <div className="hud-label text-muted">{source.name}</div>
              <div className="mt-2 text-sm leading-6 text-txt-soft">{source.note}</div>
              {source.command && <div className="hud-label mt-3 text-accent-2">{source.command}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ReplayOverview({ payload, activeProduct }: { payload: DashboardPayload; activeProduct: Product }) {
  const summary = payload.summary
  const productSummary = summary?.per_product?.[activeProduct]
  const behaviour = payload.behaviour?.per_product?.[activeProduct]
  const productLabelText = productLabel(payload, activeProduct)
  const productCap = positionLimit(payload, activeProduct)
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
      ? Math.abs(productSummary.final_position) / productCap
      : null
    cards.push(
      <MetricCard key="product-mtm" label={`${productLabelText} MTM`} value={fmtNum(productSummary.final_mtm)} tone={colorForValue(productSummary.final_mtm)} sub={`Realised ${fmtNum(productSummary.realised)}`} />,
      <MetricCard key="product-position" label={`${productLabelText} position`} value={fmtInt(productSummary.final_position)} sub={`Cap ${fmtPct(capUsage)}`} tone={capUsage != null && capUsage >= 1 ? 'warn' : 'neutral'} />,
    )
  }

  if (behaviour) {
    cards.push(
      <MetricCard key="cap-usage" label="Cap usage ratio" value={fmtPct(behaviour.cap_usage_ratio)} tone={numberOrNull(behaviour.cap_usage_ratio) != null && Number(behaviour.cap_usage_ratio) > 0.6 ? 'warn' : 'neutral'} sub={`Peak pos ${fmtInt(behaviour.peak_abs_position)}/${fmtInt(productCap)}`} />,
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
      <MetricCard label="MC median" value={fmtNum(summary.p50)} sub={`P95 ${fmtNum(summary.p95)}`} />
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

function sumNumberValues(values: unknown[]): number | null {
  const clean = values.map(numberOrNull).filter((value): value is number => value != null)
  if (!clean.length) return null
  return clean.reduce((total, value) => total + value, 0)
}

function maxLabelledNumber(entries: Array<[string, unknown]>): { label: string; value: number } | null {
  let best: { label: string; value: number } | null = null
  for (const [label, rawValue] of entries) {
    const value = numberOrNull(rawValue)
    if (value == null) continue
    if (!best || value > best.value) best = { label, value }
  }
  return best
}

function formatSecondsValue(value: unknown): string {
  const number = numberOrNull(value)
  if (number == null) return 'not recorded'
  return `${number.toFixed(3)}s`
}

function formatDayList(value: unknown): string {
  if (!Array.isArray(value) || value.length === 0) return 'not recorded'
  return value.join(', ')
}
