import { Target } from 'lucide-react'
import { useStore } from '../store'
import { Card } from '../components/Card'
import { MetricCard } from '../components/MetricCard'
import { DataTable, type ColDef } from '../components/DataTable'
import { KVGrid } from '../components/KVGrid'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { BundleBadge } from '../components/BundleBadge'
import { ScatterPlot } from '../charts/ScatterPlot'
import { BarGroupChart } from '../charts/BarGroupChart'
import { fmtNum, fmtInt, colorForValue } from '../lib/format'
import { getTabAvailability } from '../lib/bundles'
import { FILL_MODEL_COLORS } from '../charts/theme'
import type { CalibrationCandidate } from '../types'

export function Calibration() {
  const { getActiveRun } = useStore()
  const run = getActiveRun()
  const availability = getTabAvailability(run?.payload, 'calibration')
  const calibration = run?.payload.calibration

  if (!run || !availability.supported || !calibration) {
    return (
      <EmptyState
        icon={<Target className="h-10 w-10" />}
        title={availability.title}
        message={availability.message}
      />
    )
  }

  const { grid, best, diagnostics } = calibration
  const isBestCandidate = (row: CalibrationCandidate) =>
    row.fill_model === best.fill_model &&
    row.passive_fill_scale === best.passive_fill_scale &&
    row.adverse_selection_ticks === best.adverse_selection_ticks &&
    row.latency_ticks === best.latency_ticks &&
    row.missed_fill_additive === best.missed_fill_additive &&
    row.score === best.score

  // Scatter data: group by fill model
  const fillModels = [...new Set(grid.map((r) => r.fill_model))]
  const scatterDatasets = fillModels.map((fm) => ({
    name: fm,
    color: FILL_MODEL_COLORS[fm] ?? '#7889a4',
    data: grid
      .filter((r) => r.fill_model === fm)
      .map((r) => ({
        x: r.path_rmse,
        y: r.profit_error,
        label: `${fm} / scale ${r.passive_fill_scale} adv ${r.adverse_selection_ticks}`,
      })),
  }))

  // Bias bar chart
  const biasData = Object.entries(diagnostics.profit_bias_counts ?? {}).map(([label, count]) => ({
    label,
    count: count as number,
  }))

  // Per-product calibration
  const productRows = Object.entries(diagnostics.per_product ?? {}).map(([prod, stats]) => ({
    product: prod === 'ASH_COATED_OSMIUM' ? 'Osmium' : 'Pepper',
    mean_abs_pnl_error: stats.mean_abs_pnl_error,
    mean_path_rmse: stats.mean_path_rmse,
    best_path_rmse: stats.best_path_rmse,
  }))

  const gridCols: ColDef<CalibrationCandidate>[] = [
    { key: 'fill_model', header: 'Model', fmt: 'str' },
    { key: 'passive_fill_scale', header: 'Scale', fmt: 'num', digits: 2 },
    { key: 'adverse_selection_ticks', header: 'Adv', fmt: 'int' },
    { key: 'latency_ticks', header: 'Lat', fmt: 'int' },
    { key: 'missed_fill_additive', header: 'Miss', fmt: 'num', digits: 2 },
    { key: 'score', header: 'Score', fmt: 'num', tone: (_v, row) => isBestCandidate(row) ? 'accent' : 'neutral' },
    { key: 'profit_error', header: 'Profit err', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'path_rmse', header: 'Path RMSE', fmt: 'num' },
    { key: 'position_l1_error', header: 'Pos L1', fmt: 'num' },
    { key: 'osmium_path_rmse', header: 'Osm RMSE', fmt: 'num' },
    { key: 'pepper_path_rmse', header: 'Pep RMSE', fmt: 'num' },
  ]

  return (
    <div className="space-y-5">
      <PageHeader
        kicker="Calibration / live mismatch"
        title="Simulator"
        accent="alignment"
        description="Grid-search candidates, live-vs-sim bias, per-product mismatch and the parameters that reduce error."
        meta={<BundleBadge payload={run.payload} />}
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Best score" value={fmtNum(best.score)} sub="Lower is better" />
        <MetricCard label="Profit error" value={fmtNum(best.profit_error)} tone={colorForValue(best.profit_error)} sub="Sim minus live profit" />
        <MetricCard label="Path RMSE" value={fmtNum(best.path_rmse)} sub="Total PnL path error" />
        <MetricCard label="Grid size" value={fmtInt(diagnostics.candidate_count)} sub={`${fillModels.length} fill models`} />
      </div>

      {/* Scatter + bias */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="Calibration frontier" subtitle="Path RMSE vs profit error. Each point is a candidate">
          <ScatterPlot
            datasets={scatterDatasets}
            xLabel="Path RMSE"
            yLabel="Profit error"
            yRefAt={0}
            height={280}
          />
        </Card>
        <Card title="Profit bias counts" subtitle="How many candidates were optimistic / pessimistic / neutral">
          <BarGroupChart
            data={biasData}
            labelKey="label"
            series={[{ key: 'count', name: 'Candidates', color: '#7de7ff' }]}
            height={280}
          />
        </Card>
      </div>

      {/* Best candidate detail */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="Best candidate">
          <KVGrid
            cols={2}
            pairs={[
              { label: 'Fill model', value: best.fill_model },
              { label: 'Passive fill scale', value: fmtNum(best.passive_fill_scale, 2) },
              { label: 'Adverse selection', value: fmtInt(best.adverse_selection_ticks) },
              { label: 'Latency ticks', value: fmtInt(best.latency_ticks) },
              { label: 'Missed fill additive', value: fmtNum(best.missed_fill_additive, 2) },
              { label: 'Score', value: fmtNum(best.score) },
              { label: 'Profit error', value: fmtNum(best.profit_error), tone: colorForValue(best.profit_error) },
              { label: 'Path RMSE', value: fmtNum(best.path_rmse) },
              { label: 'Position L1', value: fmtNum(best.position_l1_error) },
              { label: 'Dominant error', value: best.dominant_error_source ?? '-' },
            ]}
          />
        </Card>

        {productRows.length > 0 && (
          <Card title="Per-product calibration">
            <DataTable
              rows={productRows}
              cols={[
                { key: 'product', header: 'Product', fmt: 'str' },
                { key: 'mean_abs_pnl_error', header: 'Mean |PnL err|', fmt: 'num' },
                { key: 'mean_path_rmse', header: 'Mean RMSE', fmt: 'num' },
                { key: 'best_path_rmse', header: 'Best RMSE', fmt: 'num' },
              ]}
              striped
            />
          </Card>
        )}
      </div>

      {/* By fill model summary */}
      {Object.keys(diagnostics.by_fill_model ?? {}).length > 0 && (
        <Card title="By fill model" subtitle="Calibration performance across all candidates per model type">
          <DataTable
            rows={Object.entries(diagnostics.by_fill_model).map(([model, stats]) => ({ model, ...stats }))}
            cols={[
              { key: 'model', header: 'Model', fmt: 'str' },
              { key: 'candidate_count', header: 'Candidates', fmt: 'int' },
              { key: 'best_score', header: 'Best score', fmt: 'num' },
              { key: 'mean_score', header: 'Mean score', fmt: 'num' },
              { key: 'mean_profit_error', header: 'Mean profit err', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
              { key: 'mean_path_rmse', header: 'Mean RMSE', fmt: 'num' },
            ]}
            striped
          />
        </Card>
      )}

      {/* Full calibration grid */}
      <Card title="Full calibration grid" subtitle="All candidates sorted by score">
        <DataTable rows={[...grid].sort((a, b) => a.score - b.score)} cols={gridCols} maxRows={30} striped />
      </Card>
    </div>
  )
}
