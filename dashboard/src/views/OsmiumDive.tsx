import { Layers } from 'lucide-react'
import { useStore } from '../store'
import { Card } from '../components/Card'
import { MetricCard } from '../components/MetricCard'
import { DataTable, type ColDef } from '../components/DataTable'
import { KVGrid } from '../components/KVGrid'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { PnlChart } from '../charts/PnlChart'
import { InventoryChart } from '../charts/InventoryChart'
import { FairFillChart } from '../charts/FairFillChart'
import { HistogramChart } from '../charts/HistogramChart'
import { BarGroupChart } from '../charts/BarGroupChart'
import { buildPnlData, buildInventoryData, buildFairFillData, byProduct, buildMarkoutDist } from '../lib/data'
import { fmtNum, fmtInt, fmtPct, colorForValue } from '../lib/format'
import type { FillRow, BehaviourPerProduct } from '../types'

const PRODUCT = 'ASH_COATED_OSMIUM'

export function OsmiumDive() {
  const { getActiveRun, timeWindow } = useStore()
  const run = getActiveRun()

  if (!run?.payload.pnlSeries?.length && !run?.payload.summary) {
    return (
      <EmptyState
        icon={<Layers className="w-10 h-10" />}
        title="No replay data"
        message="Load a replay bundle to see the Osmium deep dive."
      />
    )
  }

  const { payload } = run
  const behaviour = (payload.behaviour?.per_product?.[PRODUCT] ?? {}) as Partial<BehaviourPerProduct>
  const productSummary = payload.summary?.per_product?.[PRODUCT]

  const pnlData = buildPnlData(payload.pnlSeries ?? [], PRODUCT, timeWindow)
  const invData = buildInventoryData(payload.inventorySeries ?? [], PRODUCT)
  const { fair, fills } = buildFairFillData(
    payload.fairValueSeries ?? [],
    payload.fills ?? [],
    PRODUCT,
  )

  const osmFills = byProduct(payload.fills ?? [], PRODUCT)
  const passiveFills = osmFills.filter((f) => f.kind === 'passive_approx')
  const aggFills = osmFills.filter((f) => f.kind === 'aggressive_visible')

  // Markout distributions
  const markout1Dist = buildMarkoutDist(osmFills, 'markout_1')
  const markout5Dist = buildMarkoutDist(osmFills, 'markout_5')

  // Spread capture: distribution of edge_to_analysis_fair
  const edgeDist = buildMarkoutDist(osmFills, 'signed_edge_to_analysis_fair')

  // Side breakdown bar
  const sideData = [
    {
      label: 'Buys',
      passive: osmFills.filter((f) => f.side === 'buy' && f.kind === 'passive_approx').length,
      aggressive: osmFills.filter((f) => f.side === 'buy' && f.kind === 'aggressive_visible').length,
    },
    {
      label: 'Sells',
      passive: osmFills.filter((f) => f.side === 'sell' && f.kind === 'passive_approx').length,
      aggressive: osmFills.filter((f) => f.side === 'sell' && f.kind === 'aggressive_visible').length,
    },
  ]

  // Adverse selection: passive fills where markout_1 is unfavourable
  const adversePassive = passiveFills.filter(
    (f) => (f.side === 'buy' && (f.markout_1 ?? 0) < 0) || (f.side === 'sell' && (f.markout_1 ?? 0) > 0),
  )
  const adverseRate = passiveFills.length > 0 ? adversePassive.length / passiveFills.length : 0

  const fillCols: ColDef<FillRow>[] = [
    { key: 'day', header: 'Day', fmt: 'int', width: 50 },
    { key: 'timestamp', header: 'Tick', fmt: 'int' },
    { key: 'side', header: 'Side', fmt: 'str', tone: (v) => (v === 'buy' ? 'good' : 'bad') },
    { key: 'price', header: 'Price', fmt: 'num', digits: 0 },
    { key: 'quantity', header: 'Qty', fmt: 'int' },
    { key: 'kind', header: 'Kind', fmt: 'str' },
    { key: 'markout_1', header: 'Mkt+1', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'markout_5', header: 'Mkt+5', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'signed_edge_to_analysis_fair', header: 'Edge', fmt: 'num', digits: 1, tone: (v) => colorForValue(Number(v)) },
  ]

  return (
    <div className="space-y-5">
      <PageHeader
        kicker="Product deep dive / OSMIUM"
        title="Spread capture"
        accent="quality"
        description="Passive versus aggressive fills, edge to fair, one-sided participation, level utilisation and adverse selection."
      />

      {productSummary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <MetricCard label="Osmium MTM" value={fmtNum(productSummary.final_mtm)} tone={colorForValue(productSummary.final_mtm)} sub={`Realised ${fmtNum(productSummary.realised)}`} />
          <MetricCard label="Final position" value={fmtInt(productSummary.final_position)} sub={`Unrealised ${fmtNum(productSummary.unrealised)}`} tone={Math.abs(productSummary.final_position) >= 80 ? 'warn' : 'neutral'} />
          <MetricCard label="Passive fills" value={fmtInt(passiveFills.length)} sub={`Aggressive: ${fmtInt(aggFills.length)}`} tone="neutral" />
          <MetricCard label="Adverse rate" value={fmtPct(adverseRate)} tone={adverseRate > 0.4 ? 'bad' : adverseRate > 0.25 ? 'warn' : 'good'} sub="Passive fills with unfav mkt+1" />
        </div>
      )}

      {/* PnL chart */}
      <Card title="Osmium / PnL over time" subtitle="MTM and realised P&L per tick">
        <PnlChart data={pnlData} height={300} />
      </Card>

      {/* Inventory + Fair/fills */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="Osmium / Inventory" subtitle="Position path with +/-80 cap lines">
          <InventoryChart data={invData} height={260} />
        </Card>
        <Card title="Osmium / Fair value and fills" subtitle="Analysis fair, mid price and fill markers">
          <FairFillChart fair={fair} fills={fills} height={260} />
        </Card>
      </div>

      {/* Markout distributions */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="Markout +1 distribution" subtitle="1-tick P&L attribution per fill">
          <HistogramChart data={markout1Dist} referenceAt={0} height={240} />
        </Card>
        <Card title="Markout +5 distribution" subtitle="5-tick P&L attribution per fill">
          <HistogramChart data={markout5Dist} referenceAt={0} height={240} />
        </Card>
      </div>

      {/* Edge distribution + side breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="Edge to analysis fair" subtitle="Signed edge at fill time">
          <HistogramChart data={edgeDist} referenceAt={0} height={240} />
        </Card>
        <Card title="Fill breakdown" subtitle="Passive vs aggressive by side">
          <BarGroupChart
            data={sideData}
            labelKey="label"
            series={[
              { key: 'passive', name: 'Passive', color: '#7de7ff' },
              { key: 'aggressive', name: 'Aggressive', color: '#c7ab66' },
            ]}
            height={240}
          />
        </Card>
      </div>

      {/* Behaviour diagnostics */}
      <Card title="Behaviour diagnostics">
        <KVGrid
          cols={3}
          pairs={[
            { label: 'Cap usage', value: fmtPct(behaviour.cap_usage_ratio ?? 0), tone: (behaviour.cap_usage_ratio ?? 0) > 0.6 ? 'warn' : 'neutral' },
            { label: 'Peak position', value: fmtInt(behaviour.peak_abs_position), tone: (behaviour.peak_abs_position ?? 0) >= 80 ? 'bad' : 'neutral' },
            { label: 'Total fills', value: fmtInt(behaviour.total_fills) },
            { label: 'Passive fills', value: fmtInt(behaviour.passive_fill_count) },
            { label: 'Aggressive fills', value: fmtInt(behaviour.aggressive_fill_count) },
            { label: 'Total buy qty', value: fmtInt(behaviour.total_buy_qty) },
            { label: 'Total sell qty', value: fmtInt(behaviour.total_sell_qty) },
            { label: 'Fill markout +1', value: fmtNum(behaviour.average_fill_markout_1), tone: colorForValue(behaviour.average_fill_markout_1) },
            { label: 'Fill markout +5', value: fmtNum(behaviour.average_fill_markout_5), tone: colorForValue(behaviour.average_fill_markout_5) },
          ]}
        />
      </Card>

      {/* All Osmium fills */}
      <Card title="All Osmium fills" subtitle="Sorted by quantity descending">
        <DataTable
          rows={[...osmFills].sort((a, b) => b.quantity - a.quantity)}
          cols={fillCols}
          maxRows={30}
          striped
        />
      </Card>
    </div>
  )
}
