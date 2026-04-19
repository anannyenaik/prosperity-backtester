import { GitCompare } from 'lucide-react'
import { useStore } from '../store'
import { Card } from '../components/Card'
import { MetricCard } from '../components/MetricCard'
import { DataTable, type ColDef } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { KVGrid } from '../components/KVGrid'
import { BarGroupChart } from '../charts/BarGroupChart'
import { PageHeader } from '../components/PageHeader'
import { fmtNum, fmtInt, fmtPct, colorForValue } from '../lib/format'
import { PRODUCT_LABELS, type Product } from '../types'

export function Comparison() {
  const { getActiveRun, getCompareRun } = useStore()
  const runA = getActiveRun()
  const runB = getCompareRun()

  if (!runA) {
    return (
      <EmptyState
        icon={<GitCompare className="w-10 h-10" />}
        title="No run loaded"
        message="Load a run first, then select a second run to compare."
      />
    )
  }

  if (!runB) {
    return (
      <EmptyState
        icon={<GitCompare className="w-10 h-10" />}
        title="No comparison run"
        message="Select a second run using the Compare selector in the top bar."
      />
    )
  }

  const a = runA.payload
  const b = runB.payload

  const delta = (va: number | undefined, vb: number | undefined) =>
    (va ?? 0) - (vb ?? 0)

  const pnlDelta = delta(a.summary?.final_pnl, b.summary?.final_pnl)
  const ddDelta = delta(a.summary?.max_drawdown, b.summary?.max_drawdown)
  const fillDelta = delta(a.summary?.fill_count, b.summary?.fill_count)
  const breachDelta = delta(a.summary?.limit_breaches, b.summary?.limit_breaches)

  // Per-product comparison rows
  const products: Product[] = ['ASH_COATED_OSMIUM', 'INTARIAN_PEPPER_ROOT']
  const productRows = products.map((prod) => {
    const pa = a.summary?.per_product?.[prod]
    const pb = b.summary?.per_product?.[prod]
    return {
      product: PRODUCT_LABELS[prod],
      pnl_a: pa?.final_mtm ?? 0,
      pnl_b: pb?.final_mtm ?? 0,
      pnl_delta: (pa?.final_mtm ?? 0) - (pb?.final_mtm ?? 0),
      realised_a: pa?.realised ?? 0,
      realised_b: pb?.realised ?? 0,
    }
  })

  // Behaviour comparison
  const behaviourRows = products.map((prod) => {
    const ba = a.behaviour?.per_product?.[prod]
    const bb = b.behaviour?.per_product?.[prod]
    return {
      product: PRODUCT_LABELS[prod],
      cap_a: ba?.cap_usage_ratio ?? 0,
      cap_b: bb?.cap_usage_ratio ?? 0,
      markout5_a: ba?.average_fill_markout_5 ?? 0,
      markout5_b: bb?.average_fill_markout_5 ?? 0,
      fills_a: ba?.total_fills ?? 0,
      fills_b: bb?.total_fills ?? 0,
    }
  })

  // Bar chart: PnL comparison
  const pnlBarData = [
    { label: 'Total', a: a.summary?.final_pnl ?? 0, b: b.summary?.final_pnl ?? 0 },
    ...products.map((p) => ({
      label: PRODUCT_LABELS[p],
      a: a.summary?.per_product?.[p]?.final_mtm ?? 0,
      b: b.summary?.per_product?.[p]?.final_mtm ?? 0,
    })),
  ]

  type ProductRow = (typeof productRows)[0]
  type BehaviourRow = (typeof behaviourRows)[0]

  const productCols: ColDef<ProductRow>[] = [
    { key: 'product', header: 'Product', fmt: 'str' },
    { key: 'pnl_a', header: 'PnL A', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'pnl_b', header: 'PnL B', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'pnl_delta', header: 'Delta PnL', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'realised_a', header: 'Realised A', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'realised_b', header: 'Realised B', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
  ]

  const behaviourCols: ColDef<BehaviourRow>[] = [
    { key: 'product', header: 'Product', fmt: 'str' },
    { key: 'cap_a', header: 'Cap A', fmt: 'pct', tone: (v) => (Number(v) > 0.6 ? 'warn' : 'neutral') },
    { key: 'cap_b', header: 'Cap B', fmt: 'pct', tone: (v) => (Number(v) > 0.6 ? 'warn' : 'neutral') },
    { key: 'markout5_a', header: 'Mkt+5 A', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'markout5_b', header: 'Mkt+5 B', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'fills_a', header: 'Fills A', fmt: 'int' },
    { key: 'fills_b', header: 'Fills B', fmt: 'int' },
  ]

  const nameA = a.meta?.runName ?? runA.name
  const nameB = b.meta?.runName ?? runB.name

  return (
    <div className="space-y-5">
      <PageHeader
        kicker="Comparison / side-by-side"
        title="Variant"
        accent="deltas"
        description="Primary and comparison runs with PnL, drawdown, fills, per-product contribution and behaviour quality."
      />

      <div className="grid grid-cols-2 gap-4">
        <div className="rounded-xl bg-surface border border-accent/30 px-4 py-3">
          <div className="text-accent text-xs font-bold uppercase tracking-wider mb-1">Run A (primary)</div>
          <div className="text-txt text-sm font-semibold truncate">{nameA}</div>
          <div className="text-muted text-xs mt-0.5">{a.type ?? '-'}</div>
        </div>
        <div className="rounded-xl bg-surface border border-accent-2/30 px-4 py-3">
          <div className="text-accent-2 text-xs font-bold uppercase tracking-wider mb-1">Run B (compare)</div>
          <div className="text-txt text-sm font-semibold truncate">{nameB}</div>
          <div className="text-muted text-xs mt-0.5">{b.type ?? '-'}</div>
        </div>
      </div>

      {/* Top delta metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          label="Delta PnL (A - B)"
          value={fmtNum(pnlDelta)}
          tone={colorForValue(pnlDelta)}
          sub={`A: ${fmtNum(a.summary?.final_pnl)} / B: ${fmtNum(b.summary?.final_pnl)}`}
        />
        <MetricCard
          label="Delta Drawdown"
          value={fmtNum(ddDelta)}
          tone={ddDelta < 0 ? 'good' : 'bad'}
          sub={`A: ${fmtNum(a.summary?.max_drawdown)} / B: ${fmtNum(b.summary?.max_drawdown)}`}
        />
        <MetricCard
          label="Delta Fills"
          value={fmtInt(fillDelta)}
          tone="neutral"
          sub={`A: ${fmtInt(a.summary?.fill_count)} / B: ${fmtInt(b.summary?.fill_count)}`}
        />
        <MetricCard
          label="Delta Breaches"
          value={fmtInt(breachDelta)}
          tone={breachDelta > 0 ? 'bad' : breachDelta < 0 ? 'good' : 'neutral'}
          sub={`A: ${fmtInt(a.summary?.limit_breaches ?? 0)} / B: ${fmtInt(b.summary?.limit_breaches ?? 0)}`}
        />
      </div>

      {/* PnL bar comparison */}
      <Card title="PnL comparison" subtitle="Side-by-side by product">
        <BarGroupChart
          data={pnlBarData}
          labelKey="label"
          series={[
            { key: 'a', name: nameA, color: '#7de7ff' },
            { key: 'b', name: nameB, color: '#c7ab66' },
          ]}
          colorByValue
          height={260}
        />
      </Card>

      {/* Per-product breakdown + behaviour */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="Per-product PnL">
          <DataTable rows={productRows} cols={productCols} striped />
        </Card>
        <Card title="Behaviour comparison">
          <DataTable rows={behaviourRows} cols={behaviourCols} striped />
        </Card>
      </div>

      {/* MC side by side */}
      {(a.monteCarlo?.summary || b.monteCarlo?.summary) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {[
            { label: 'A', mc: a.monteCarlo?.summary, color: 'text-accent' },
            { label: 'B', mc: b.monteCarlo?.summary, color: 'text-accent-2' },
          ].map(({ label, mc, color }) => (
            <Card key={label} title={`Monte Carlo / Run ${label}`}>
              {mc ? (
                <KVGrid
                  cols={2}
                  pairs={[
                    { label: 'Mean PnL', value: fmtNum(mc.mean), tone: colorForValue(mc.mean) },
                    { label: 'P05', value: fmtNum(mc.p05), tone: mc.p05 < 0 ? 'bad' : 'good' },
                    { label: 'Positive rate', value: fmtPct(mc.positive_rate), tone: mc.positive_rate > 0.5 ? 'good' : 'warn' },
                    { label: 'Std dev', value: fmtNum(mc.std), tone: 'neutral' },
                    { label: 'Mean DD', value: fmtNum(mc.mean_max_drawdown), tone: 'warn' },
                    { label: 'Sessions', value: fmtInt(mc.session_count), tone: 'neutral' },
                  ]}
                />
              ) : (
                <div className={`text-muted text-xs italic ${color}`}>No MC data</div>
              )}
            </Card>
          ))}
        </div>
      )}

      {/* Fill model metadata */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {[
          { label: 'A', meta: a.meta, color: 'accent' },
          { label: 'B', meta: b.meta, color: 'accent-2' },
        ].map(({ label, meta, color }) => (
          <Card key={label} title={`Run ${label} / metadata`}>
            <KVGrid
              cols={2}
              pairs={[
                { label: 'Run name', value: meta?.runName ?? '-' },
                { label: 'Mode', value: meta?.mode ?? '-' },
                { label: 'Fill model', value: meta?.fillModel?.name ?? '-' },
                { label: 'Trader', value: meta?.traderName ?? '-' },
              ]}
            />
          </Card>
        ))}
      </div>
    </div>
  )
}
