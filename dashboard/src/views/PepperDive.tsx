import { FlameKindling } from 'lucide-react'
import { useStore } from '../store'
import { Card } from '../components/Card'
import { MetricCard } from '../components/MetricCard'
import { DataTable, type ColDef } from '../components/DataTable'
import { KVGrid } from '../components/KVGrid'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { BundleBadge } from '../components/BundleBadge'
import { PnlChart } from '../charts/PnlChart'
import { InventoryChart } from '../charts/InventoryChart'
import { FairFillChart } from '../charts/FairFillChart'
import { HistogramChart } from '../charts/HistogramChart'
import { BarGroupChart } from '../charts/BarGroupChart'
import { buildPnlData, buildInventoryData, buildFairFillData, byProduct, buildMarkoutDist, computeCapStats } from '../lib/data'
import { fmtNum, fmtInt, fmtPct, colorForValue } from '../lib/format'
import { getTabAvailability, isFiniteNumber, numberOrNull } from '../lib/bundles'
import type { FillRow, BehaviourPerProduct } from '../types'

const PRODUCT = 'INTARIAN_PEPPER_ROOT'

export function PepperDive() {
  const { getActiveRun, timeWindow } = useStore()
  const run = getActiveRun()
  const availability = getTabAvailability(run?.payload, 'pepper')

  if (!run || !availability.supported) {
    return (
      <EmptyState
        icon={<FlameKindling className="h-10 w-10" />}
        title={availability.title}
        message={availability.message}
      />
    )
  }

  const { payload } = run
  const behaviour = payload.behaviour?.per_product?.[PRODUCT] as Partial<BehaviourPerProduct> | undefined
  const productSummary = payload.summary?.per_product?.[PRODUCT]

  const pnlData = buildPnlData(payload.pnlSeries ?? [], PRODUCT, timeWindow)
  const invData = buildInventoryData(payload.inventorySeries ?? [], PRODUCT)
  const { fair, fills } = buildFairFillData(
    payload.fairValueSeries ?? [],
    payload.fills ?? [],
    PRODUCT,
  )

  const pepFills = byProduct(payload.fills ?? [], PRODUCT)
  const passiveFills = pepFills.filter((f) => f.kind === 'passive_approx')
  const aggFills = pepFills.filter((f) => f.kind === 'aggressive_visible')

  // Cap stats from inventory series
  const capStats = computeCapStats(payload.inventorySeries ?? [], PRODUCT)

  // Markout distributions
  const markout1Dist = buildMarkoutDist(pepFills, 'markout_1')
  const markout5Dist = buildMarkoutDist(pepFills, 'markout_5')

  // Edge distribution
  const edgeDist = buildMarkoutDist(pepFills, 'signed_edge_to_analysis_fair')

  // Adverse selection
  const passiveWithMarkout = passiveFills.filter((fill) => isFiniteNumber(fill.markout_1))
  const adversePassive = passiveWithMarkout.filter(
    (f) => (f.side === 'buy' && Number(f.markout_1) < 0) || (f.side === 'sell' && Number(f.markout_1) > 0),
  )
  const adverseRate = passiveWithMarkout.length > 0 ? adversePassive.length / passiveWithMarkout.length : null

  // Day-by-day PnL (from sessionRows)
  const sessionRows = payload.sessionRows ?? []
  const dayRows = sessionRows
    .map((s) => {
      const row = s as Record<string, unknown>
      const pnl = numberOrNull(row.pepper_pnl)
      return pnl == null ? null : { label: `Day ${row.day}`, pnl }
    })
    .filter((row): row is { label: string; pnl: number } => row != null)

  // Side breakdown
  const sideData = [
    {
      label: 'Buys',
      passive: pepFills.filter((f) => f.side === 'buy' && f.kind === 'passive_approx').length,
      aggressive: pepFills.filter((f) => f.side === 'buy' && f.kind === 'aggressive_visible').length,
    },
    {
      label: 'Sells',
      passive: pepFills.filter((f) => f.side === 'sell' && f.kind === 'passive_approx').length,
      aggressive: pepFills.filter((f) => f.side === 'sell' && f.kind === 'aggressive_visible').length,
    },
  ]

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
        kicker="Product deep dive / PEPPER"
        title="Directional"
        accent="exposure"
        description="Carry, cap pressure, fair path alignment, harvest behaviour and path sensitivity under replay and sampled MC."
        meta={<BundleBadge payload={payload} />}
      />

      {productSummary ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <MetricCard label="Pepper MTM" value={fmtNum(productSummary.final_mtm)} tone={colorForValue(productSummary.final_mtm)} sub={`Realised ${fmtNum(productSummary.realised)}`} />
          <MetricCard label="Final position" value={fmtInt(productSummary.final_position)} sub={`Unrealised ${fmtNum(productSummary.unrealised)}`} tone={Math.abs(productSummary.final_position) >= 80 ? 'warn' : 'neutral'} />
          <MetricCard label="Time at cap" value={fmtPct(capStats.total ? capStats.fracAtCap : null)} tone={!capStats.total ? 'neutral' : capStats.fracAtCap > 0.1 ? 'bad' : capStats.fracAtCap > 0.04 ? 'warn' : 'good'} sub={capStats.total ? `${fmtInt(capStats.ticksAtCap)} ticks` : 'Inventory series not present'} />
          <MetricCard label="Adverse rate" value={fmtPct(adverseRate)} tone={adverseRate == null ? 'neutral' : adverseRate > 0.4 ? 'bad' : adverseRate > 0.25 ? 'warn' : 'good'} sub="Passive fills with unfav mkt+1" />
        </div>
      ) : (
        <Card title="Pepper summary">
          <EmptyState title="Product summary not present" message="This bundle does not include a PEPPER replay summary." />
        </Card>
      )}

      <Card title="Pepper / PnL over time" subtitle="MTM and realised P&L per tick">
        {pnlData.length > 0 ? (
          <PnlChart data={pnlData} height={300} />
        ) : (
          <EmptyState title="PnL series not present" message="This bundle does not include PEPPER PnL rows." />
        )}
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="Pepper / Inventory" subtitle="Position path with +/-80 cap lines and cap shading">
          {invData.length > 0 ? (
            <InventoryChart data={invData} height={260} />
          ) : (
            <EmptyState title="Inventory series not present" message="This bundle does not include PEPPER inventory rows." />
          )}
        </Card>
        <Card title="Pepper / Fair value and fills" subtitle="Analysis fair, mid price and fill markers">
          {fair.length > 0 || fills.length > 0 ? (
            <FairFillChart fair={fair} fills={fills} height={260} />
          ) : (
            <EmptyState title="Fair value and fill rows not present" message="This bundle does not include PEPPER fair-value or fill rows." />
          )}
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

      {/* Edge + side breakdown */}
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

      {/* Day by day PnL */}
      {dayRows.length > 0 && (
        <Card title="Day-by-day Pepper PnL" subtitle="Final PnL per session">
          <BarGroupChart
            data={dayRows}
            labelKey="label"
            series={[{ key: 'pnl', name: 'PnL', color: '#c7ab66' }]}
            colorByValue
            height={220}
          />
        </Card>
      )}

      {/* Behaviour diagnostics */}
      <Card title="Behaviour diagnostics">
        {behaviour ? (
          <KVGrid
            cols={3}
            pairs={[
              { label: 'Cap usage', value: fmtPct(behaviour.cap_usage_ratio), tone: numberOrNull(behaviour.cap_usage_ratio) != null && Number(behaviour.cap_usage_ratio) > 0.6 ? 'warn' : 'neutral' },
              { label: 'Peak position', value: fmtInt(behaviour.peak_abs_position), tone: numberOrNull(behaviour.peak_abs_position) != null && Number(behaviour.peak_abs_position) >= 80 ? 'bad' : 'neutral' },
              { label: 'Time at cap', value: fmtPct(capStats.total ? capStats.fracAtCap : null), tone: capStats.total && capStats.fracAtCap > 0.1 ? 'bad' : 'neutral' },
              { label: 'Total fills', value: fmtInt(behaviour.total_fills) },
              { label: 'Passive fills', value: fmtInt(behaviour.passive_fill_count) },
              { label: 'Aggressive fills', value: fmtInt(behaviour.aggressive_fill_count) },
              { label: 'Total buy qty', value: fmtInt(behaviour.total_buy_qty) },
              { label: 'Total sell qty', value: fmtInt(behaviour.total_sell_qty) },
              { label: 'Fill markout +1', value: fmtNum(behaviour.average_fill_markout_1), tone: colorForValue(behaviour.average_fill_markout_1) },
              { label: 'Fill markout +5', value: fmtNum(behaviour.average_fill_markout_5), tone: colorForValue(behaviour.average_fill_markout_5) },
            ]}
          />
        ) : (
          <EmptyState title="Behaviour summary not present" message="This bundle does not include PEPPER behaviour metrics." />
        )}
      </Card>

      {/* All Pepper fills */}
      <Card title="All Pepper fills" subtitle="Sorted by quantity descending">
        <DataTable
          rows={[...pepFills].sort((a, b) => b.quantity - a.quantity)}
          cols={fillCols}
          maxRows={30}
          striped
          emptyMsg="PEPPER fill rows are not present in this bundle."
        />
      </Card>
    </div>
  )
}
