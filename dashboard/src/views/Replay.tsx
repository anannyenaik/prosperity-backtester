import { BarChart2 } from 'lucide-react'
import { useStore } from '../store'
import { Card } from '../components/Card'
import { MetricCard } from '../components/MetricCard'
import { DataTable, type ColDef } from '../components/DataTable'
import { KVGrid } from '../components/KVGrid'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { ProductToggle } from '../components/ProductToggle'
import { PnlChart } from '../charts/PnlChart'
import { InventoryChart } from '../charts/InventoryChart'
import { FairFillChart } from '../charts/FairFillChart'
import {
  buildPnlData,
  buildInventoryData,
  buildFairFillData,
  byProduct,
  type FillPoint,
} from '../lib/data'
import { fmtNum, fmtInt, fmtPct, colorForValue } from '../lib/format'
import { PRODUCT_LABELS, type Product, type FillRow, type BehaviourPerProduct } from '../types'

export function Replay() {
  const { getActiveRun, activeProduct, timeWindow } = useStore()
  const run = getActiveRun()

  if (!run?.payload.pnlSeries?.length && !run?.payload.summary) {
    return (
      <EmptyState
        icon={<BarChart2 className="w-10 h-10" />}
        title="No replay data"
        message="Load a replay bundle to see per-tick PnL, inventory and fill analysis."
      />
    )
  }

  const { payload } = run
  const product = activeProduct as Product
  const productLabel = PRODUCT_LABELS[product]
  const behaviour = (payload.behaviour?.per_product?.[product] ?? {}) as Partial<BehaviourPerProduct>
  const productSummary = payload.summary?.per_product?.[product]

  const pnlData = buildPnlData(payload.pnlSeries ?? [], product, timeWindow)
  const invData = buildInventoryData(payload.inventorySeries ?? [], product)
  const { fair, fills } = buildFairFillData(
    payload.fairValueSeries ?? [],
    payload.fills ?? [],
    product,
  )

  const topFills = byProduct(payload.fills ?? [], product)
    .sort((a, b) => b.quantity - a.quantity)
    .slice(0, 20)

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

  const sessionRows = payload.sessionRows ?? []
  const sessionCols = [
    { key: 'day', header: 'Day', fmt: 'int' as const },
    { key: 'final_pnl', header: 'PnL', fmt: 'num' as const, tone: (v: unknown) => colorForValue(Number(v)) },
    { key: 'osmium_pnl', header: 'Osmium', fmt: 'num' as const, tone: (v: unknown) => colorForValue(Number(v)) },
    { key: 'pepper_pnl', header: 'Pepper', fmt: 'num' as const, tone: (v: unknown) => colorForValue(Number(v)) },
    { key: 'osmium_position', header: 'Osm pos', fmt: 'int' as const },
    { key: 'pepper_position', header: 'Pep pos', fmt: 'int' as const },
  ]

  return (
    <div className="space-y-5">
      <PageHeader
        kicker="Replay analysis / deterministic path"
        title="Replay"
        accent="diagnostics"
        description="PnL, realised and unrealised contribution, inventory, fair value, fills and behaviour quality for the selected product."
        action={<ProductToggle />}
      />

      {productSummary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <MetricCard label={`${productLabel} MTM`} value={fmtNum(productSummary.final_mtm)} tone={colorForValue(productSummary.final_mtm)} sub={`Realised ${fmtNum(productSummary.realised)}`} />
          <MetricCard label="Unrealised" value={fmtNum(productSummary.unrealised)} tone={colorForValue(productSummary.unrealised)} sub={`Pos ${productSummary.final_position}`} />
          <MetricCard label="Cap usage" value={fmtPct(behaviour.cap_usage_ratio ?? 0)} tone={(behaviour.cap_usage_ratio ?? 0) > 0.6 ? 'warn' : 'neutral'} sub={`Peak ${fmtInt(behaviour.peak_abs_position ?? 0)}/80`} />
          <MetricCard label="Markout +5" value={fmtNum(behaviour.average_fill_markout_5)} tone={colorForValue(behaviour.average_fill_markout_5)} sub="Avg signed edge" />
        </div>
      )}

      {/* PnL chart */}
      <Card title={`${productLabel} / PnL over time`} subtitle="MTM and realised P&L per tick">
        <PnlChart data={pnlData} height={300} />
      </Card>

      {/* Inventory + Fair/fills side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title={`${productLabel} / Inventory`} subtitle="Position path with +/-80 cap lines">
          <InventoryChart data={invData} height={260} />
        </Card>
        <Card title={`${productLabel} / Fair value and fills`} subtitle="Analysis fair, mid price and fill markers">
          <FairFillChart fair={fair} fills={fills} height={260} />
        </Card>
      </div>

      {/* Behaviour diagnostics + per-day breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="Behaviour diagnostics">
          <KVGrid
            cols={2}
            pairs={[
              { label: 'Cap usage', value: fmtPct(behaviour.cap_usage_ratio ?? 0), tone: (behaviour.cap_usage_ratio ?? 0) > 0.6 ? 'warn' : 'neutral' },
              { label: 'Peak position', value: fmtInt(behaviour.peak_abs_position), tone: (behaviour.peak_abs_position ?? 0) >= 80 ? 'bad' : 'neutral' },
              { label: 'Total fills', value: fmtInt(behaviour.total_fills) },
              { label: 'Passive fills', value: fmtInt(behaviour.passive_fill_count) },
              { label: 'Aggressive fills', value: fmtInt(behaviour.aggressive_fill_count) },
              { label: 'Fill markout +1', value: fmtNum(behaviour.average_fill_markout_1), tone: colorForValue(behaviour.average_fill_markout_1) },
              { label: 'Fill markout +5', value: fmtNum(behaviour.average_fill_markout_5), tone: colorForValue(behaviour.average_fill_markout_5) },
              { label: 'Total buy qty', value: fmtInt(behaviour.total_buy_qty) },
              { label: 'Total sell qty', value: fmtInt(behaviour.total_sell_qty) },
            ]}
          />
        </Card>

        {sessionRows.length > 0 && (
          <Card title="Per-day breakdown">
            <DataTable rows={sessionRows as Record<string, unknown>[]} cols={sessionCols} striped />
          </Card>
        )}
      </div>

      {/* Top fills table */}
      <Card title="Largest fills" subtitle={`${productLabel} / sorted by quantity`}>
        <DataTable rows={topFills} cols={fillCols} maxRows={20} striped />
      </Card>
    </div>
  )
}
