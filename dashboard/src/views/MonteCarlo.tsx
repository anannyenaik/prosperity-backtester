import { useState } from 'react'
import { Cpu, Sliders } from 'lucide-react'
import { useStore } from '../store'
import { Card } from '../components/Card'
import { MetricCard } from '../components/MetricCard'
import { DataTable, type ColDef } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { ProductToggle } from '../components/ProductToggle'
import { BundleBadge } from '../components/BundleBadge'
import { HistogramChart } from '../charts/HistogramChart'
import { PathBandsChart } from '../charts/PathBandsChart'
import { PnlChart } from '../charts/PnlChart'
import { buildHistogram, buildBands, buildPnlData } from '../lib/data'
import { fmtNum, fmtInt, fmtPct, colorForValue } from '../lib/format'
import { getTabAvailability, isFiniteNumber } from '../lib/bundles'
import type { McSession, Product } from '../types'

const PATH_METRICS = [
  ['analysisFair', 'Analysis fair'],
  ['mid', 'Mid'],
  ['inventory', 'Inventory'],
  ['pnl', 'PnL'],
] as const
type PathMetric = (typeof PATH_METRICS)[number][0]

export function MonteCarlo() {
  const { getActiveRun, activeProduct, sampleRunName, setSampleRun } = useStore()
  const [pathMetric, setPathMetric] = useState<PathMetric>('analysisFair')
  const run = getActiveRun()
  const availability = getTabAvailability(run?.payload, 'montecarlo')
  const mc = run?.payload.monteCarlo

  if (!run || !availability.supported || !mc) {
    return (
      <EmptyState
        icon={<Sliders className="h-10 w-10" />}
        title={availability.title}
        message={availability.message}
      />
    )
  }

  const { summary, sessions = [], sampleRuns = [], fairValueBands, pathBands } = mc
  const product = activeProduct as Product
  const runtime = run.payload.meta?.provenance?.runtime
  const timings = runtime?.phase_timings_seconds

  const sessionPnls = sessions.map((s) => s.final_pnl).filter(isFiniteNumber)
  const histData = buildHistogram(sessionPnls)

  const allBands = pathBands ?? { analysisFair: fairValueBands?.analysisFair, mid: fairValueBands?.mid }
  const bandData = buildBands(allBands?.[pathMetric]?.[product] ?? [])
  const usingAllSessions = mc.pathBandMethod?.source === 'all_sessions'
  const bandSubtitle = usingAllSessions
    ? 'Exact session quantiles at retained bucket endpoints. Omitted intra-bucket chronology is compacted.'
    : 'Fallback bands from saved sample runs only.'
  const sampleSubtitle = usingAllSessions
    ? 'Qualitative example only. The path bands above are computed from all sessions, not from this sample.'
    : 'Saved sample session path.'

  // Sample run selector
  const selectedSample =
    (sampleRunName && sampleRuns.find((r) => r.runName === sampleRunName)) ||
    sampleRuns[0] ||
    null

  const samplePnlData = selectedSample
    ? buildPnlData(selectedSample.pnlSeries ?? [], product)
    : []

  // Worst / best table
  const sortedSessions = [...sessions].sort((a, b) => a.final_pnl - b.final_pnl)
  const bottomN = sortedSessions.slice(0, 5)
  const topN = sortedSessions.slice(-5).reverse()
  const extremeSessions = [...bottomN, ...topN]

  const sessionCols: ColDef<McSession>[] = [
    { key: 'run_name', header: 'Session', fmt: 'str' },
    { key: 'final_pnl', header: 'PnL', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'fill_count', header: 'Fills', fmt: 'int' },
    { key: 'limit_breaches', header: 'Breaches', fmt: 'int', tone: (v) => (Number(v) > 0 ? 'bad' : 'neutral') },
  ]

  const wallSeconds = isFiniteNumber(timings?.session_execution_wall_seconds)
    ? Number(timings!.session_execution_wall_seconds)
    : null
  const sessionsPerSecond =
    wallSeconds && wallSeconds > 0 && summary.session_count > 0
      ? summary.session_count / wallSeconds
      : null

  return (
    <div className="space-y-5">
      <PageHeader
        kicker="Monte Carlo / robustness lab"
        title="Path stress"
        accent="distribution"
        description="Distribution, downside, all-session path bands and saved sample sessions for robustness decisions."
        meta={<BundleBadge payload={run.payload} />}
        action={<ProductToggle />}
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Mean PnL" value={fmtNum(summary.mean)} tone={colorForValue(summary.mean)} sub={`${fmtInt(summary.session_count)} sessions`} />
        <MetricCard label="P05 (downside)" value={fmtNum(summary.p05)} tone={summary.p05 < 0 ? 'bad' : 'good'} sub={`ES05 ${fmtNum(summary.expected_shortfall_05)}`} />
        <MetricCard label="Positive rate" value={fmtPct(summary.positive_rate)} tone={summary.positive_rate > 0.5 ? 'good' : 'warn'} sub={`Std ${fmtNum(summary.std)}`} />
        <MetricCard label="Mean max DD" value={fmtNum(summary.mean_max_drawdown)} tone="warn" sub={`P95 ${fmtNum(summary.p95)}`} />
      </div>

      {/* Runtime / engine provenance */}
      {runtime && (
        <Card
          title="Engine provenance"
          subtitle="Backend selection, worker configuration and phase timing for this run"
          action={<Cpu className="h-4 w-4 text-muted" />}
        >
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
            {[
              { label: 'Backend', value: runtime.monte_carlo_backend ?? runtime.engine_backend ?? '—' },
              { label: 'Parallelism', value: runtime.parallelism ?? '—' },
              { label: 'Workers', value: runtime.worker_count != null ? String(runtime.worker_count) : '—' },
              { label: 'Sessions', value: runtime.session_count != null ? fmtInt(runtime.session_count) : fmtInt(summary.session_count) },
              { label: 'Wall time', value: wallSeconds != null ? `${wallSeconds.toFixed(1)}s` : '—' },
              { label: 'Sessions/s', value: sessionsPerSecond != null ? sessionsPerSecond.toFixed(2) : '—' },
            ].map((item) => (
              <div key={item.label} className="rounded-lg border border-border bg-surface-2/50 px-3 py-2.5">
                <div className="hud-label text-muted mb-1">{item.label}</div>
                <div className="font-mono text-sm font-semibold text-txt">{item.value}</div>
              </div>
            ))}
          </div>

          {timings && (
            <div className="mt-4 border-t border-border pt-4">
              <div className="hud-label text-muted mb-3">Phase timings (cumulative across all workers)</div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
                {[
                  { key: 'market_generation_seconds', label: 'Market gen' },
                  { key: 'trader_seconds', label: 'Trader' },
                  { key: 'execution_seconds', label: 'Execution' },
                  { key: 'path_metrics_seconds', label: 'Path metrics' },
                  { key: 'postprocess_seconds', label: 'Postprocess' },
                  { key: 'python_overhead_seconds', label: 'Python overhead' },
                ].map(({ key, label }) => {
                  const val = timings[key]
                  return isFiniteNumber(val) ? (
                    <div key={key} className="rounded bg-surface-2/30 px-2.5 py-2">
                      <div className="hud-label text-muted/80 mb-0.5">{label}</div>
                      <div className="font-mono text-xs text-txt-soft">{Number(val).toFixed(2)}s</div>
                    </div>
                  ) : null
                })}
              </div>
            </div>
          )}
        </Card>
      )}

      {/* Distribution + path bands */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="Session PnL distribution" subtitle="Final PnL across all simulated sessions">
          {histData.length > 0 ? (
            <HistogramChart data={histData} referenceAt={0} height={280} />
          ) : (
            <EmptyState title="Session PnL rows not present" message="This Monte Carlo bundle does not include session-level final PnL rows." />
          )}
        </Card>
        <Card
          title={`${PATH_METRICS.find(([key]) => key === pathMetric)?.[1] ?? 'Path'} bands / ${activeProduct === 'ASH_COATED_OSMIUM' ? 'Osmium' : 'Pepper'}`}
          subtitle={bandSubtitle}
          action={
            <select
              value={pathMetric}
              onChange={(event) => setPathMetric(event.target.value as PathMetric)}
              className="bg-surface-2 border border-border text-xs text-txt rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-accent/40"
            >
              {PATH_METRICS.map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          }
        >
          {bandData.length > 0 ? (
            <PathBandsChart data={bandData} height={280} />
          ) : (
            <EmptyState title="Path bands not present" message="This Monte Carlo bundle does not include the selected path-band metric for this product." />
          )}
        </Card>
      </div>

      {/* Sample path + selector */}
      <Card
        title="Sample session path"
        subtitle={sampleSubtitle}
        action={
          <select
            value={sampleRunName ?? ''}
            onChange={(e) => setSampleRun(e.target.value || null)}
            className="bg-surface-2 border border-border text-xs text-txt rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-accent/40"
          >
            <option value="">Auto (best)</option>
            {sampleRuns.map((r) => (
              <option key={r.runName} value={r.runName}>
                {r.runName.split('_').slice(-1)[0]} / {fmtNum(r.summary?.final_pnl)}
              </option>
            ))}
          </select>
        }
      >
        {selectedSample ? (
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-lg bg-surface-2 border border-border px-3 py-2.5">
                <div className="text-muted text-xs uppercase tracking-wide mb-1">PnL</div>
                <div className={`text-sm font-bold ${colorForValue(selectedSample.summary?.final_pnl) === 'good' ? 'text-good' : 'text-bad'}`}>
                  {fmtNum(selectedSample.summary?.final_pnl)}
                </div>
              </div>
              <div className="rounded-lg bg-surface-2 border border-border px-3 py-2.5">
                <div className="text-muted text-xs uppercase tracking-wide mb-1">Fills</div>
                <div className="text-txt text-sm font-bold">{fmtInt(selectedSample.summary?.fill_count)}</div>
              </div>
              <div className="rounded-lg bg-surface-2 border border-border px-3 py-2.5">
                <div className="text-muted text-xs uppercase tracking-wide mb-1">Max DD</div>
                <div className="text-warn text-sm font-bold">{fmtNum(selectedSample.summary?.max_drawdown)}</div>
              </div>
            </div>
            <PnlChart data={samplePnlData} height={240} />
          </div>
        ) : (
          <EmptyState title="No sample paths" message="Increase --sample-sessions when running Monte Carlo." />
        )}
      </Card>

      {/* Worst / best table */}
      <Card title="Extreme sessions" subtitle="5 worst and 5 best sessions">
        <DataTable rows={extremeSessions} cols={sessionCols} maxRows={10} striped emptyMsg="Session rows are not present in this Monte Carlo bundle." />
      </Card>

      {/* Per-product MC summary */}
      {summary.per_product && (
        <Card title="Per-product MC summary">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {Object.entries(summary.per_product).map(([prod, stats]) => (
              <div key={prod} className="rounded-lg bg-surface-2 border border-border p-4">
                <div className="text-muted text-xs uppercase tracking-wider mb-3 font-semibold">
                  {prod === 'ASH_COATED_OSMIUM' ? 'Osmium' : 'Pepper'}
                </div>
                <div className="grid grid-cols-3 gap-3 text-xs">
                  {(['mean', 'min', 'max'] as const).map((k) => (
                    <div key={k}>
                      <div className="text-muted uppercase tracking-wide mb-0.5">{k}</div>
                      <div className={`font-bold font-mono ${colorForValue(stats[k]) === 'good' ? 'text-good' : colorForValue(stats[k]) === 'bad' ? 'text-bad' : 'text-txt-soft'}`}>
                        {fmtNum(stats[k])}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
