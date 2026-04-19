import { Sliders } from 'lucide-react'
import { useStore } from '../store'
import { Card } from '../components/Card'
import { MetricCard } from '../components/MetricCard'
import { DataTable, type ColDef } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { ProductToggle } from '../components/ProductToggle'
import { HistogramChart } from '../charts/HistogramChart'
import { PathBandsChart } from '../charts/PathBandsChart'
import { PnlChart } from '../charts/PnlChart'
import { buildHistogram, buildBands, buildPnlData } from '../lib/data'
import { fmtNum, fmtInt, fmtPct, colorForValue } from '../lib/format'
import type { McSession, Product } from '../types'

export function MonteCarlo() {
  const { getActiveRun, activeProduct, sampleRunName, setSampleRun } = useStore()
  const run = getActiveRun()
  const mc = run?.payload.monteCarlo

  if (!mc) {
    return (
      <EmptyState
        icon={<Sliders className="w-10 h-10" />}
        title="No Monte Carlo data"
        message="Load a Monte Carlo bundle to see robustness analysis."
      />
    )
  }

  const { summary, sessions, sampleRuns, fairValueBands } = mc
  const product = activeProduct as Product

  const sessionPnls = sessions.map((s) => s.final_pnl)
  const histData = buildHistogram(sessionPnls)

  const bandData = buildBands(fairValueBands?.analysisFair?.[product] ?? [])

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

  return (
    <div className="space-y-5">
      <PageHeader
        kicker="Monte Carlo / robustness lab"
        title="Path stress"
        accent="distribution"
        description="Distribution, downside, path bands and saved sample sessions for robustness decisions."
        action={<ProductToggle />}
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Mean PnL" value={fmtNum(summary.mean)} tone={colorForValue(summary.mean)} sub={`${fmtInt(summary.session_count)} sessions`} />
        <MetricCard label="P05 (downside)" value={fmtNum(summary.p05)} tone={summary.p05 < 0 ? 'bad' : 'good'} sub={`ES05 ${fmtNum(summary.expected_shortfall_05)}`} />
        <MetricCard label="Positive rate" value={fmtPct(summary.positive_rate)} tone={summary.positive_rate > 0.5 ? 'good' : 'warn'} sub={`Std ${fmtNum(summary.std)}`} />
        <MetricCard label="Mean max DD" value={fmtNum(summary.mean_max_drawdown)} tone="warn" sub={`P95 ${fmtNum(summary.p95)}`} />
      </div>

      {/* Distribution + path bands */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="Session PnL distribution" subtitle="Final PnL across all simulated sessions">
          <HistogramChart data={histData} referenceAt={0} height={280} />
        </Card>
        <Card
          title={`Fair value bands / ${activeProduct === 'ASH_COATED_OSMIUM' ? 'Osmium' : 'Pepper'}`}
          subtitle="P10/P50/P90 across synthetic sessions"
        >
          <PathBandsChart data={bandData} height={280} />
        </Card>
      </div>

      {/* Sample path + selector */}
      <Card
        title="Sample session path"
        action={
          <select
            value={sampleRunName ?? ''}
            onChange={(e) => setSampleRun(e.target.value || null)}
            className="bg-surface-2 border border-border text-xs text-txt rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-accent/40"
          >
            <option value="">Auto (best)</option>
            {sampleRuns.map((r) => (
              <option key={r.runName} value={r.runName}>
                {r.runName.split('_').slice(-1)[0]} / {fmtNum(r.summary?.final_pnl ?? 0)}
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
        <DataTable rows={extremeSessions} cols={sessionCols} maxRows={10} striped />
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
                      <div className={`font-bold font-mono ${(stats[k] ?? 0) >= 0 ? 'text-good' : 'text-bad'}`}>
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
