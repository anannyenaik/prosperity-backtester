import { Cpu } from 'lucide-react'
import { useStore } from '../store'
import { Card } from '../components/Card'
import { MetricCard } from '../components/MetricCard'
import { DataTable, type ColDef } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { KVGrid } from '../components/KVGrid'
import { ScatterPlot } from '../charts/ScatterPlot'
import { PageHeader } from '../components/PageHeader'
import { BundleBadge } from '../components/BundleBadge'
import { fmtNum, fmtInt, colorForValue } from '../lib/format'
import { getTabAvailability } from '../lib/bundles'
import type { OptimizationRow } from '../types'

export function Optimization() {
  const { getActiveRun } = useStore()
  const run = getActiveRun()
  const availability = getTabAvailability(run?.payload, 'optimize')
  const opt = run?.payload.optimization

  if (!run || !availability.supported || !opt) {
    return (
      <EmptyState
        icon={<Cpu className="h-10 w-10" />}
        title={availability.title}
        message={availability.message}
      />
    )
  }

  const { rows, diagnostics } = opt
  const bestVariant = diagnostics.best_score_variant
  const bestRow = rows.find((r) => r.variant === bestVariant) ?? rows[0]

  // Scatter: score vs replay PnL
  const scatterDatasets = [
    {
      name: 'Candidates',
      color: '#c7ab66',
      data: rows
        .filter((r) => r.variant !== bestVariant)
        .map((r) => ({
          x: r.score,
          y: r.replay_final_pnl,
          label: r.variant,
        })),
    },
    {
      name: 'Best',
      color: '#7de7ff',
      data: bestRow
        ? [{ x: bestRow.score, y: bestRow.replay_final_pnl, label: bestRow.variant }]
        : [],
    },
  ]

  const sortedRows = [...rows].sort((a, b) => b.score - a.score)

  const cols: ColDef<OptimizationRow>[] = [
    { key: 'variant', header: 'Variant', fmt: 'str' },
    { key: 'score', header: 'Score', fmt: 'num', tone: (_, row) => row.variant === bestVariant ? 'accent' : 'neutral' },
    { key: 'replay_final_pnl', header: 'Replay PnL', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'mc_p05', header: 'MC P05', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'mc_expected_shortfall_05', header: 'ES05', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'mc_std', header: 'Std', fmt: 'num' },
    { key: 'mc_mean_drawdown', header: 'Mean DD', fmt: 'num', tone: () => 'warn' },
  ]

  return (
    <div className="space-y-5">
      <PageHeader
        kicker="Optimisation / sweep"
        title="Parameter"
        accent="frontier"
        description="Ranked variants, replay-vs-robustness trade-offs, downside winners and stability diagnostics."
        meta={<BundleBadge payload={run.payload} />}
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Variants tested" value={fmtInt(diagnostics.variant_count)} sub="Parameter combinations" />
        <MetricCard label="Best score" value={fmtNum(bestRow?.score)} sub={`${bestVariant} / higher is better`} />
        <MetricCard label="Best replay PnL" value={fmtNum(bestRow?.replay_final_pnl)} tone={colorForValue(bestRow?.replay_final_pnl)} sub={diagnostics.best_replay_variant} />
        <MetricCard label="Best P05" value={fmtNum(rows.find((r) => r.variant === diagnostics.best_downside_variant)?.mc_p05)} tone="good" sub={diagnostics.best_downside_variant} />
      </div>

      {/* Scatter + diagnostics */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="Score vs replay PnL frontier" subtitle="Each point is a parameter variant. Best is highlighted in cyan.">
          <ScatterPlot
            datasets={scatterDatasets}
            xLabel="Score"
            yLabel="Replay PnL"
            height={280}
          />
        </Card>
        <Card title="Experiment diagnostics">
          <KVGrid
            cols={2}
            pairs={[
              { label: 'Best score variant', value: diagnostics.best_score_variant },
              { label: 'Best replay variant', value: diagnostics.best_replay_variant },
              { label: 'Best downside variant', value: diagnostics.best_downside_variant },
              { label: 'Most stable variant', value: diagnostics.most_stable_variant },
              { label: 'Score gap to #2', value: diagnostics.score_gap_to_second != null ? fmtNum(diagnostics.score_gap_to_second) : '-' },
              { label: 'Frontier size', value: fmtInt(diagnostics.frontier.length) },
            ]}
          />
        </Card>
      </div>

      {/* Score frontier */}
      {diagnostics.frontier.length > 0 && (
        <Card title="Score frontier" subtitle="Top-ranked variants with replay and downside context">
          <DataTable rows={diagnostics.frontier} cols={cols} striped />
        </Card>
      )}

      {/* Full grid */}
        <Card title="All variants" subtitle="Sorted by score descending">
        <DataTable rows={sortedRows} cols={cols} maxRows={50} striped />
      </Card>
    </div>
  )
}
