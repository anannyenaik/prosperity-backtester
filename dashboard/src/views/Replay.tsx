import { BarChart2 } from 'lucide-react'
import { useStore } from '../store'
import { Card } from '../components/Card'
import { MetricCard } from '../components/MetricCard'
import { DataTable, type ColDef } from '../components/DataTable'
import { KVGrid } from '../components/KVGrid'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { ProductToggle } from '../components/ProductToggle'
import { BundleBadge } from '../components/BundleBadge'
import { PnlChart } from '../charts/PnlChart'
import { InventoryChart } from '../charts/InventoryChart'
import { FairFillChart } from '../charts/FairFillChart'
import {
  buildPnlData,
  buildInventoryData,
  buildFairFillData,
  byProduct,
} from '../lib/data'
import { fmtNum, fmtInt, fmtPct, colorForValue } from '../lib/format'
import { getTabAvailability, numberOrNull } from '../lib/bundles'
import { positionLimit, productLabel, productShortLabel } from '../lib/products'
import type { Product, FillRow, BehaviourPerProduct } from '../types'

export function Replay() {
  const { getActiveRun, activeProduct, timeWindow } = useStore()
  const run = getActiveRun()
  const availability = getTabAvailability(run?.payload, 'replay')

  if (!run || !availability.supported) {
    return (
      <EmptyState
        icon={<BarChart2 className="h-10 w-10" />}
        title={availability.title}
        message={availability.message}
      />
    )
  }

  const { payload } = run
  const product = activeProduct as Product
  const productLabelText = productLabel(payload, product)
  const productShort = productShortLabel(payload, product)
  const productCap = positionLimit(payload, product)
  const behaviour = payload.behaviour?.per_product?.[product] as Partial<BehaviourPerProduct> | undefined
  const productSummary = payload.summary?.per_product?.[product]

  const pnlData = buildPnlData(payload.pnlSeries ?? [], product, timeWindow)
  const invData = buildInventoryData(payload.inventorySeries ?? [], product, productCap)
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
    {
      key: 'selected_product_pnl',
      header: `${productShort} MTM`,
      fmt: 'num' as const,
      render: (_value: unknown, row: Record<string, unknown>) => fmtNum(numberOrNull((row.per_product_pnl as Record<string, unknown> | undefined)?.[product])),
    },
    {
      key: 'selected_product_position',
      header: `${productShort} pos`,
      fmt: 'int' as const,
      render: (_value: unknown, row: Record<string, unknown>) => fmtInt(numberOrNull((row.per_product_position as Record<string, unknown> | undefined)?.[product])),
    },
    { key: 'fill_count', header: 'Fills', fmt: 'int' as const },
    { key: 'limit_breaches', header: 'Breaches', fmt: 'int' as const },
  ]

  return (
    <div className="space-y-5">
      <PageHeader
        kicker="Replay analysis / deterministic path"
        title="Replay"
        accent="diagnostics"
        description="PnL, realised and unrealised contribution, inventory, fair value, fills and behaviour quality for the selected product."
        meta={<BundleBadge payload={payload} />}
        action={<ProductToggle />}
      />

      {productSummary ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <MetricCard label={`${productLabelText} MTM`} value={fmtNum(productSummary.final_mtm)} tone={colorForValue(productSummary.final_mtm)} sub={`Realised ${fmtNum(productSummary.realised)}`} />
          <MetricCard label="Unrealised" value={fmtNum(productSummary.unrealised)} tone={colorForValue(productSummary.unrealised)} sub={`Pos ${productSummary.final_position}`} />
          <MetricCard label="Cap usage" value={fmtPct(behaviour?.cap_usage_ratio)} tone={numberOrNull(behaviour?.cap_usage_ratio) != null && Number(behaviour?.cap_usage_ratio) > 0.6 ? 'warn' : 'neutral'} sub={`Peak ${fmtInt(behaviour?.peak_abs_position)}/${fmtInt(productCap)}`} />
          <MetricCard label="Markout +5" value={fmtNum(behaviour?.average_fill_markout_5)} tone={colorForValue(behaviour?.average_fill_markout_5)} sub="Avg signed edge" />
        </div>
      ) : (
        <Card title={`${productLabelText} summary`}>
          <EmptyState title="Product summary not present" message="This replay bundle does not include a per-product summary for the selected product." />
        </Card>
      )}

      <Card title={`${productLabelText} / PnL over time`} subtitle="MTM and realised P&L per tick">
        {pnlData.length > 0 ? (
          <PnlChart data={pnlData} height={300} />
        ) : (
          <EmptyState title="PnL series not present" message="This replay bundle does not include PnL rows for the selected product." />
        )}
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title={`${productLabelText} / Inventory`} subtitle={`Position path with +/-${productCap} cap lines`}>
          {invData.length > 0 ? (
            <InventoryChart data={invData} height={260} positionLimit={productCap} />
          ) : (
            <EmptyState title="Inventory series not present" message="This replay bundle does not include inventory rows for the selected product." />
          )}
        </Card>
        <Card title={`${productLabelText} / Fair value and fills`} subtitle="Analysis fair, mid price and fill markers">
          {fair.length > 0 || fills.length > 0 ? (
            <FairFillChart fair={fair} fills={fills} height={260} />
          ) : (
            <EmptyState title="Fair value and fill rows not present" message="This replay bundle does not include fair-value or fill rows for the selected product." />
          )}
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="Behaviour diagnostics">
          {behaviour ? (
            <KVGrid
              cols={2}
              pairs={[
                { label: 'Cap usage', value: fmtPct(behaviour.cap_usage_ratio), tone: numberOrNull(behaviour.cap_usage_ratio) != null && Number(behaviour.cap_usage_ratio) > 0.6 ? 'warn' : 'neutral' },
                { label: 'Peak position', value: fmtInt(behaviour.peak_abs_position), tone: numberOrNull(behaviour.peak_abs_position) != null && Number(behaviour.peak_abs_position) >= productCap ? 'bad' : 'neutral' },
                { label: 'Total fills', value: fmtInt(behaviour.total_fills) },
                { label: 'Passive fills', value: fmtInt(behaviour.passive_fill_count) },
                { label: 'Aggressive fills', value: fmtInt(behaviour.aggressive_fill_count) },
                { label: 'Fill markout +1', value: fmtNum(behaviour.average_fill_markout_1), tone: colorForValue(behaviour.average_fill_markout_1) },
                { label: 'Fill markout +5', value: fmtNum(behaviour.average_fill_markout_5), tone: colorForValue(behaviour.average_fill_markout_5) },
                { label: 'Total buy qty', value: fmtInt(behaviour.total_buy_qty) },
                { label: 'Total sell qty', value: fmtInt(behaviour.total_sell_qty) },
              ]}
            />
          ) : (
            <EmptyState title="Behaviour summary not present" message="This replay bundle does not include behaviour metrics for the selected product." />
          )}
        </Card>

        {sessionRows.length > 0 && (
          <Card title="Per-day breakdown">
            <DataTable rows={sessionRows as Record<string, unknown>[]} cols={sessionCols} striped />
          </Card>
        )}
      </div>

      <Card title="Largest fills" subtitle={`${productLabelText} / sorted by quantity`}>
        <DataTable rows={topFills} cols={fillCols} maxRows={20} striped emptyMsg="Fill rows are not present for this product." />
      </Card>
    </div>
  )
}
