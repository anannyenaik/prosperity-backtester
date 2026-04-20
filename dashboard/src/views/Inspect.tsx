import { useMemo, useState } from 'react'
import { Crosshair, Radar } from 'lucide-react'
import { useStore } from '../store'
import { Card } from '../components/Card'
import { DataTable, type ColDef } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { KVGrid } from '../components/KVGrid'
import { MetricCard } from '../components/MetricCard'
import { PageHeader } from '../components/PageHeader'
import { ProductToggle } from '../components/ProductToggle'
import { BundleBadge } from '../components/BundleBadge'
import { FairFillChart } from '../charts/FairFillChart'
import { InventoryChart } from '../charts/InventoryChart'
import { PnlChart } from '../charts/PnlChart'
import {
  buildFairFillDataFromRows,
  buildInventoryDataFromRows,
  buildPnlDataFromRows,
  byProduct,
  globalTs,
  rowsAround,
} from '../lib/data'
import { colorForValue, fmtInt, fmtNum, fmtPct, fmtPrice, fmtTimestamp } from '../lib/format'
import { getTabAvailability, numberOrNull } from '../lib/bundles'
import type { FillRow, OrderRow, Product } from '../types'

const RADIUS_OPTIONS = [25, 75, 150, 400]

function mean(values: Array<number | null | undefined>) {
  const clean = values.filter((value): value is number => value != null && Number.isFinite(value))
  if (!clean.length) return null
  return clean.reduce((acc, value) => acc + value, 0) / clean.length
}

function sortedByTime<T extends { day: number; timestamp: number }>(rows: T[]) {
  return [...rows].sort((a, b) => globalTs(a) - globalTs(b))
}

function inRange<T extends { day: number; timestamp: number }>(rows: T[], start: number, end: number) {
  return rows.filter((row) => {
    const ts = globalTs(row)
    return ts >= start && ts <= end
  })
}

export function Inspect() {
  const { getActiveRun, activeProduct } = useStore()
  const [cursorIndex, setCursorIndex] = useState(0)
  const [radius, setRadius] = useState(75)
  const run = getActiveRun()
  const availability = getTabAvailability(run?.payload, 'inspect')

  if (!run || !availability.supported || !run.payload.pnlSeries?.length) {
    return (
      <EmptyState
        icon={<Radar className="h-10 w-10" />}
        title={availability.supported ? 'PnL series not present' : availability.title}
        message={availability.supported ? 'This bundle has replay-style data, but not the PnL rows needed for inspect mode.' : availability.message}
      />
    )
  }

  const { payload } = run
  const product = activeProduct as Product

  const series = useMemo(() => {
    const pnl = sortedByTime(byProduct(payload.pnlSeries ?? [], product))
    const inventory = sortedByTime(byProduct(payload.inventorySeries ?? [], product))
    const fair = sortedByTime(byProduct(payload.fairValueSeries ?? [], product))
    const fills = sortedByTime(byProduct(payload.fills ?? [], product))
    const orders = sortedByTime(byProduct(payload.orders ?? [], product))
    return { pnl, inventory, fair, fills, orders }
  }, [payload, product])

  const safeIndex = Math.max(0, Math.min(series.pnl.length - 1, cursorIndex))
  const selected = series.pnl[safeIndex]
  const selectedTs = selected ? globalTs(selected) : 0
  const windowPnlRows = rowsAround(series.pnl, safeIndex, radius)
  const startTs = windowPnlRows.length ? globalTs(windowPnlRows[0]) : selectedTs
  const endTs = windowPnlRows.length ? globalTs(windowPnlRows[windowPnlRows.length - 1]) : selectedTs
  const windowInventoryRows = inRange(series.inventory, startTs, endTs)
  const windowFairRows = inRange(series.fair, startTs, endTs)
  const windowFillRows = inRange(series.fills, startTs, endTs)
  const windowOrderRows = inRange(series.orders, startTs, endTs)
  const selectedFair =
    series.fair.find((row) => globalTs(row) === selectedTs) ??
    windowFairRows[Math.max(0, Math.floor(windowFairRows.length / 2))]

  const pnlData = buildPnlDataFromRows(windowPnlRows)
  const inventoryData = buildInventoryDataFromRows(windowInventoryRows)
  const fairFillData = buildFairFillDataFromRows(windowFairRows, windowFillRows)

  const startPnl = numberOrNull(windowPnlRows[0]?.mtm ?? selected?.mtm)
  const endPnl = numberOrNull(windowPnlRows[windowPnlRows.length - 1]?.mtm ?? selected?.mtm)
  const windowPnlDelta = startPnl != null && endPnl != null ? endPnl - startPnl : null
  const buyQty = windowFillRows.filter((fill) => fill.side === 'buy').reduce((acc, fill) => acc + fill.quantity, 0)
  const sellQty = windowFillRows.filter((fill) => fill.side === 'sell').reduce((acc, fill) => acc + fill.quantity, 0)
  const passiveCount = windowFillRows.filter((fill) => fill.kind === 'passive_approx').length
  const aggressiveCount = windowFillRows.filter((fill) => fill.kind === 'aggressive_visible').length
  const avgEdge = mean(windowFillRows.map((fill) => fill.signed_edge_to_analysis_fair))
  const avgMarkout5 = mean(windowFillRows.map((fill) => fill.markout_5))
  const nearCap = windowInventoryRows.filter((row) => Math.abs(row.position) >= 64).length
  const nearCapRate = windowInventoryRows.length ? nearCap / windowInventoryRows.length : null

  const fillCols: ColDef<FillRow>[] = [
    { key: 'day', header: 'Day', fmt: 'int', width: 56 },
    { key: 'timestamp', header: 'Tick', fmt: 'int' },
    { key: 'side', header: 'Side', fmt: 'str', tone: (v) => (v === 'buy' ? 'good' : 'bad') },
    { key: 'price', header: 'Price', fmt: 'num', digits: 0, align: 'right' },
    { key: 'quantity', header: 'Qty', fmt: 'int', align: 'right' },
    { key: 'kind', header: 'Kind', fmt: 'str' },
    { key: 'markout_5', header: 'M+5', fmt: 'num', tone: (v) => colorForValue(Number(v)), align: 'right' },
    { key: 'signed_edge_to_analysis_fair', header: 'Edge', fmt: 'num', tone: (v) => colorForValue(Number(v)), align: 'right' },
  ]

  const orderCols: ColDef<OrderRow>[] = [
    { key: 'day', header: 'Day', fmt: 'int', width: 56 },
    { key: 'timestamp', header: 'Tick', fmt: 'int' },
    { key: 'submitted_quantity', header: 'Qty', fmt: 'int', align: 'right', tone: (v) => colorForValue(Number(v)) },
    { key: 'submitted_price', header: 'Price', fmt: 'num', digits: 0, align: 'right' },
    { key: 'order_role', header: 'Role', fmt: 'str' },
    { key: 'distance_to_touch', header: 'Dist', fmt: 'num', align: 'right' },
    { key: 'signed_edge_to_analysis_fair', header: 'Edge', fmt: 'num', align: 'right', tone: (v) => colorForValue(Number(v)) },
  ]

  const jumpTo = (target: 'start' | 'middle' | 'end') => {
    if (target === 'start') setCursorIndex(0)
    if (target === 'middle') setCursorIndex(Math.floor(series.pnl.length / 2))
    if (target === 'end') setCursorIndex(Math.max(0, series.pnl.length - 1))
  }

  return (
    <div>
      <PageHeader
        kicker="Inspect shell / timestamp window"
        title="Focused run"
        accent="analysis"
        description="Focused fair, mid, fill, inventory and PnL rows around a selected timestamp."
        meta={<BundleBadge payload={payload} />}
        action={<ProductToggle />}
      />

      <div className="glass-panel mb-5 rounded-lg p-4">
        <div className="grid gap-4 xl:grid-cols-[minmax(260px,0.5fr)_minmax(0,1fr)_auto] xl:items-center">
          <div>
            <div className="hud-label text-muted">Selected window</div>
            <div className="font-display mt-2 text-sm font-semibold uppercase tracking-[0.12em] text-txt">
              {windowPnlRows.length ? `${fmtTimestamp(startTs)} to ${fmtTimestamp(endTs)}` : 'No rows'}
            </div>
          </div>
          <input
            type="range"
            min={0}
            max={Math.max(0, series.pnl.length - 1)}
            value={safeIndex}
            onChange={(event) => setCursorIndex(Number(event.target.value))}
            className="h-2 w-full accent-cyan-300"
          />
          <div className="flex flex-wrap gap-2">
            {(['start', 'middle', 'end'] as const).map((target) => (
              <button key={target} className="subtle-button rounded-lg px-3 py-2 text-xs uppercase tracking-[0.18em]" onClick={() => jumpTo(target)}>
                {target}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-4">
          <span className="hud-label text-muted">Radius</span>
          {RADIUS_OPTIONS.map((option) => (
            <button
              key={option}
              onClick={() => setRadius(option)}
              className={radius === option ? 'signal-button rounded-lg px-3 py-2 text-xs' : 'subtle-button rounded-lg px-3 py-2 text-xs'}
            >
              {option} ticks
            </button>
          ))}
          <span className="hud-label ml-auto text-accent">
            {run.name} / {product}
          </span>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[300px_minmax(0,1fr)_320px]">
        <div className="space-y-5">
          <Card title="Slice context" kicker="Left rail">
            <KVGrid
              cols={1}
              pairs={[
                { label: 'Run', value: payload.meta?.runName ?? run.name, tone: 'accent' },
                { label: 'Trader', value: payload.meta?.traderName },
                { label: 'Mode', value: payload.meta?.mode },
                { label: 'Fill model', value: payload.meta?.fillModel?.name },
                { label: 'Window rows', value: fmtInt(windowPnlRows.length) },
                { label: 'Order rows', value: fmtInt(windowOrderRows.length) },
              ]}
            />
          </Card>

          <Card title="Timestamp readout" kicker="Lock">
            <div className="flex items-center gap-3 text-accent">
              <Crosshair className="h-5 w-5" />
              <span className="font-display text-xl font-bold uppercase tracking-[0.08em]">{fmtTimestamp(selectedTs)}</span>
            </div>
            <KVGrid
              cols={1}
              className="mt-4"
              pairs={[
                { label: 'Day', value: selected?.day },
                { label: 'Tick', value: selected?.timestamp },
                { label: 'Fair', value: fmtPrice(selectedFair?.analysis_fair as number | null | undefined), tone: 'accent' },
                { label: 'Mid', value: fmtPrice(selectedFair?.mid as number | null | undefined) },
                { label: 'Position', value: fmtInt(selected?.position), tone: numberOrNull(selected?.position) != null && Math.abs(Number(selected?.position)) >= 80 ? 'warn' : 'neutral' },
              ]}
            />
          </Card>
        </div>

        <div className="min-w-0 space-y-5">
          <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
            <MetricCard label="Window PnL" value={fmtNum(windowPnlDelta)} tone={colorForValue(windowPnlDelta)} sub={`MTM now ${fmtNum(selected?.mtm)}`} />
            <MetricCard label="Fills" value={fmtInt(windowFillRows.length)} sub={`Buy ${fmtInt(buyQty)} / Sell ${fmtInt(sellQty)}`} />
            <MetricCard label="Avg edge" value={fmtNum(avgEdge)} tone={colorForValue(avgEdge)} sub={`M+5 ${fmtNum(avgMarkout5)}`} />
            <MetricCard label="Near cap" value={fmtPct(nearCapRate)} tone={nearCapRate != null && nearCapRate > 0.25 ? 'warn' : 'neutral'} sub={`${fmtInt(nearCap)} ticks near cap`} />
          </div>

          <Card title="PnL guide rail" subtitle="MTM and realised PnL inside the selected timestamp window">
            <PnlChart data={pnlData} height={285} />
          </Card>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card title="Fair, mid and fills" subtitle="Fill points are restricted to the selected window">
              <FairFillChart fair={fairFillData.fair} fills={fairFillData.fills} height={265} />
            </Card>
            <Card title="Inventory focus" subtitle="Position path with cap rails">
              <InventoryChart data={inventoryData} height={265} />
            </Card>
          </div>
        </div>

        <div className="space-y-5">
          <Card title="Window annotations" kicker="Right rail">
            <div className="space-y-3">
              {[
                {
                  label: 'Execution density',
                  value: `${fmtInt(windowFillRows.length)} fills / ${fmtInt(windowOrderRows.length)} orders`,
                  tone: 'text-accent',
                },
                {
                  label: 'Fill mix',
                  value: `${fmtInt(passiveCount)} passive / ${fmtInt(aggressiveCount)} aggressive`,
                  tone: 'text-accent-2',
                },
                {
                  label: 'Fair to mid',
                  value:
                    selectedFair?.analysis_fair != null && selectedFair?.mid != null
                      ? fmtNum(Number(selectedFair.analysis_fair) - Number(selectedFair.mid), 2)
                      : '-',
                  tone: 'text-txt',
                },
              ].map((item) => (
                <div key={item.label} className="rounded-lg border border-border bg-white/[0.025] p-4">
                  <div className="hud-label text-muted">{item.label}</div>
                  <div className={`font-display mt-2 text-lg font-bold uppercase tracking-[0.06em] ${item.tone}`}>{item.value}</div>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Selected tick accounting">
            <KVGrid
              cols={1}
              pairs={[
                { label: 'Cash', value: fmtNum(selected?.cash) },
                { label: 'Realised', value: fmtNum(selected?.realised), tone: colorForValue(selected?.realised) },
                { label: 'Unrealised', value: fmtNum(selected?.unrealised), tone: colorForValue(selected?.unrealised) },
                { label: 'MTM', value: fmtNum(selected?.mtm), tone: colorForValue(selected?.mtm) },
                { label: 'Spread', value: fmtNum(selected?.spread) },
              ]}
            />
          </Card>
        </div>
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        <Card title="Window fills" subtitle="Exact rows available in the bundle for this selected slice">
          <DataTable rows={windowFillRows} cols={fillCols} maxRows={30} />
        </Card>
        <Card title="Window orders" subtitle="Submitted orders around the same timestamp range">
          <DataTable rows={windowOrderRows} cols={orderCols} maxRows={30} />
        </Card>
      </div>
    </div>
  )
}
