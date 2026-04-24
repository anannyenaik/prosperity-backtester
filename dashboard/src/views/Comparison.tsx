import { GitCompare } from 'lucide-react'
import { useStore } from '../store'
import { Card } from '../components/Card'
import { MetricCard } from '../components/MetricCard'
import { DataTable, type ColDef } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { KVGrid } from '../components/KVGrid'
import { BarGroupChart } from '../charts/BarGroupChart'
import { PageHeader } from '../components/PageHeader'
import { BundleBadge } from '../components/BundleBadge'
import { fmtNum, fmtInt, fmtPct, colorForValue } from '../lib/format'
import { getComparisonRows, getTabAvailability, interpretBundle, numberOrNull } from '../lib/bundles'
import { availableProducts, productLabel } from '../lib/products'
import type { ComparisonRow, DashboardPayload, Product } from '../types'

export function Comparison() {
  const { getActiveRun, getCompareRun } = useStore()
  const runA = getActiveRun()
  const runB = getCompareRun()
  const availability = getTabAvailability(runA?.payload, 'compare', {
    comparePayload: runB?.payload,
    sameCompareRun: Boolean(runA && runB && runA.id === runB.id),
  })

  if (!runA || !availability.supported) {
    return (
      <EmptyState
        icon={<GitCompare className="h-10 w-10" />}
        title={availability.title}
        message={availability.message}
      />
    )
  }

  const bundle = interpretBundle(runA.payload)
  const comparisonRows = getComparisonRows(runA.payload)

  if ((bundle.type === 'comparison' || bundle.type === 'round2_scenarios') && comparisonRows.length > 0) {
    return <PrecomputedComparison payload={runA.payload} rows={comparisonRows} />
  }

  if (!runB || runA.id === runB.id) {
    return (
      <EmptyState
        icon={<GitCompare className="h-10 w-10" />}
        title="Select a different comparison run."
        message="The dashboard will not compare a bundle to itself unless explicit comparison rows are present."
      />
    )
  }

  return <SideBySideComparison runA={runA} runB={runB} />
}

function PrecomputedComparison({ payload, rows }: { payload: DashboardPayload; rows: ComparisonRow[] }) {
  const diagnostics = payload.comparisonDiagnostics ?? {}
  const winner = rows[0]
  const winnerPnl = numberOrNull(diagnostics.winner_final_pnl) ?? numberOrNull(winner?.final_pnl)
  const gap = numberOrNull(diagnostics.gap_to_second)
  const scenarioCount = numberOrNull(diagnostics.scenario_count)
  const mafRows = numberOrNull(diagnostics.maf_sensitive_rows)
  const title = interpretBundle(payload).type === 'round2_scenarios' ? 'Scenario' : 'Trader'

  const cols: ColDef<ComparisonRow>[] = [
    { key: 'scenario', header: 'Scenario', fmt: 'str' },
    { key: 'trader', header: 'Trader', fmt: 'str' },
    { key: 'final_pnl', header: 'Net PnL', fmt: 'num', tone: (v) => colorForValue(numberOrNull(v)) },
    { key: 'gross_pnl_before_maf', header: 'Gross', fmt: 'num', tone: (v) => colorForValue(numberOrNull(v)) },
    { key: 'maf_cost', header: 'MAF', fmt: 'num', tone: (v) => (numberOrNull(v) != null && Number(v) > 0 ? 'warn' : 'neutral') },
    { key: 'max_drawdown', header: 'Max DD', fmt: 'num', tone: () => 'warn' },
    { key: 'fill_count', header: 'Fills', fmt: 'int' },
    { key: 'limit_breaches', header: 'Breaches', fmt: 'int', tone: (v) => (numberOrNull(v) != null && Number(v) > 0 ? 'bad' : 'neutral') },
  ]

  const chartRows = rows
    .filter((row) => numberOrNull(row.final_pnl) != null)
    .slice(0, 16)
    .map((row) => ({
      label: row.scenario ? `${row.scenario} / ${row.trader}` : row.trader,
      net: row.final_pnl,
      gross: row.gross_pnl_before_maf,
    }))
  const chartSeries = [
    { key: 'net', name: 'Net PnL', color: '#c7ab66' },
    ...(chartRows.length > 0 && chartRows.every((row) => numberOrNull(row.gross) != null)
      ? [{ key: 'gross', name: 'Gross PnL', color: '#7de7ff' }]
      : []),
  ]

  return (
    <div className="space-y-5">
      <PageHeader
        kicker="Comparison / precomputed rows"
        title={title}
        accent="ranking"
        description="Explicit comparison rows from the loaded bundle, without synthetic self-vs-self deltas."
        meta={<BundleBadge payload={payload} />}
      />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricCard label="Rows" value={fmtInt(rows.length)} sub="Explicit comparison rows" />
        <MetricCard label="Winner" value={String(diagnostics.winner ?? winner?.trader ?? 'not available')} sub={`PnL ${fmtNum(winnerPnl)}`} tone="accent" />
        <MetricCard label="Gap to second" value={fmtNum(gap)} tone={colorForValue(gap)} sub="Winner minus runner-up" />
        <MetricCard label="Scenarios" value={fmtInt(scenarioCount)} sub={`MAF rows ${fmtInt(mafRows)}`} />
      </div>

      <Card title="PnL ranking" subtitle="Rows sorted by the comparison bundle">
        {chartRows.length > 0 ? (
          <BarGroupChart data={chartRows} labelKey="label" series={chartSeries} colorByValue height={300} />
        ) : (
          <EmptyState title="Comparable PnL rows not present" message="The comparison table is present, but no numeric final PnL values were found." />
        )}
      </Card>

      <Card title="Comparison rows" subtitle="Net, gross, MAF, product contribution and execution diagnostics">
        <DataTable rows={rows} cols={cols} maxRows={200} striped emptyMsg="Comparison rows are not present in this bundle." />
      </Card>

      <Card title="Comparison diagnostics">
        <KVGrid
          cols={4}
          pairs={[
            { label: 'Row count', value: fmtInt(numberOrNull(diagnostics.row_count) ?? rows.length) },
            { label: 'Winner', value: String(diagnostics.winner ?? winner?.trader ?? 'not available'), tone: 'accent' },
            { label: 'Winner PnL', value: fmtNum(winnerPnl), tone: colorForValue(winnerPnl) },
            { label: 'Gap to second', value: fmtNum(gap), tone: colorForValue(gap) },
            { label: 'Limit breach count', value: fmtInt(numberOrNull(diagnostics.limit_breach_count)) },
            { label: 'Scenario count', value: fmtInt(scenarioCount) },
            { label: 'MAF sensitive rows', value: fmtInt(mafRows) },
          ]}
        />
      </Card>
    </div>
  )
}

function SideBySideComparison({ runA, runB }: { runA: { name: string; payload: DashboardPayload }; runB: { name: string; payload: DashboardPayload } }) {
  const a = runA.payload
  const b = runB.payload
  const nameA = a.meta?.runName ?? runA.name
  const nameB = b.meta?.runName ?? runB.name
  const products = Array.from(new Set([...availableProducts(a), ...availableProducts(b)]))

  const pnlDelta = delta(a.summary?.final_pnl, b.summary?.final_pnl)
  const ddDelta = delta(a.summary?.max_drawdown, b.summary?.max_drawdown)
  const fillDelta = delta(a.summary?.fill_count, b.summary?.fill_count)
  const breachDelta = delta(a.summary?.limit_breaches, b.summary?.limit_breaches)

  const productRows = products
    .map((prod) => {
      const pa = a.summary?.per_product?.[prod]
      const pb = b.summary?.per_product?.[prod]
      return {
        product: productLabel(a, prod),
        pnl_a: numberOrNull(pa?.final_mtm),
        pnl_b: numberOrNull(pb?.final_mtm),
        pnl_delta: delta(pa?.final_mtm, pb?.final_mtm),
        realised_a: numberOrNull(pa?.realised),
        realised_b: numberOrNull(pb?.realised),
      }
    })
    .filter((row) => row.pnl_a != null || row.pnl_b != null || row.realised_a != null || row.realised_b != null)

  const behaviourRows = products
    .map((prod) => {
      const ba = a.behaviour?.per_product?.[prod]
      const bb = b.behaviour?.per_product?.[prod]
      return {
        product: productLabel(a, prod),
        cap_a: numberOrNull(ba?.cap_usage_ratio),
        cap_b: numberOrNull(bb?.cap_usage_ratio),
        markout5_a: numberOrNull(ba?.average_fill_markout_5),
        markout5_b: numberOrNull(bb?.average_fill_markout_5),
        fills_a: numberOrNull(ba?.total_fills),
        fills_b: numberOrNull(bb?.total_fills),
      }
    })
    .filter((row) => Object.entries(row).some(([key, value]) => key !== 'product' && value != null))

  const pnlBarData = [
    ...(numberOrNull(a.summary?.final_pnl) != null && numberOrNull(b.summary?.final_pnl) != null
      ? [{ label: 'Total', a: a.summary?.final_pnl, b: b.summary?.final_pnl }]
      : []),
    ...products
      .filter((prod) => numberOrNull(a.summary?.per_product?.[prod]?.final_mtm) != null && numberOrNull(b.summary?.per_product?.[prod]?.final_mtm) != null)
      .map((prod) => ({
        label: productLabel(a, prod),
        a: a.summary!.per_product[prod].final_mtm,
        b: b.summary!.per_product[prod].final_mtm,
      })),
  ]

  type ProductRow = (typeof productRows)[0]
  type BehaviourRow = (typeof behaviourRows)[0]

  const productCols: ColDef<ProductRow>[] = [
    { key: 'product', header: 'Product', fmt: 'str' },
    { key: 'pnl_a', header: 'PnL A', fmt: 'num', tone: (v) => colorForValue(numberOrNull(v)) },
    { key: 'pnl_b', header: 'PnL B', fmt: 'num', tone: (v) => colorForValue(numberOrNull(v)) },
    { key: 'pnl_delta', header: 'Delta PnL', fmt: 'num', tone: (v) => colorForValue(numberOrNull(v)) },
    { key: 'realised_a', header: 'Realised A', fmt: 'num', tone: (v) => colorForValue(numberOrNull(v)) },
    { key: 'realised_b', header: 'Realised B', fmt: 'num', tone: (v) => colorForValue(numberOrNull(v)) },
  ]

  const behaviourCols: ColDef<BehaviourRow>[] = [
    { key: 'product', header: 'Product', fmt: 'str' },
    { key: 'cap_a', header: 'Cap A', fmt: 'pct', tone: (v) => (numberOrNull(v) != null && Number(v) > 0.6 ? 'warn' : 'neutral') },
    { key: 'cap_b', header: 'Cap B', fmt: 'pct', tone: (v) => (numberOrNull(v) != null && Number(v) > 0.6 ? 'warn' : 'neutral') },
    { key: 'markout5_a', header: 'Mkt+5 A', fmt: 'num', tone: (v) => colorForValue(numberOrNull(v)) },
    { key: 'markout5_b', header: 'Mkt+5 B', fmt: 'num', tone: (v) => colorForValue(numberOrNull(v)) },
    { key: 'fills_a', header: 'Fills A', fmt: 'int' },
    { key: 'fills_b', header: 'Fills B', fmt: 'int' },
  ]

  return (
    <div className="space-y-5">
      <PageHeader
        kicker="Comparison / side-by-side"
        title="Variant"
        accent="deltas"
        description="Two distinct loaded replay summaries compared directly. Missing fields stay unavailable instead of becoming zero."
        meta={<BundleBadge payload={a} />}
      />

      <div className="grid grid-cols-2 gap-4">
        <RunBox label="Run A (primary)" name={nameA} payload={a} accent="accent" />
        <RunBox label="Run B (compare)" name={nameB} payload={b} accent="accent-2" />
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricCard label="Delta PnL (A - B)" value={fmtNum(pnlDelta)} tone={colorForValue(pnlDelta)} sub={`A ${fmtNum(a.summary?.final_pnl)} / B ${fmtNum(b.summary?.final_pnl)}`} />
        <MetricCard label="Delta drawdown" value={fmtNum(ddDelta)} tone={ddDelta == null ? 'neutral' : ddDelta < 0 ? 'good' : 'bad'} sub={`A ${fmtNum(a.summary?.max_drawdown)} / B ${fmtNum(b.summary?.max_drawdown)}`} />
        <MetricCard label="Delta fills" value={fmtInt(fillDelta)} tone="neutral" sub={`A ${fmtInt(a.summary?.fill_count)} / B ${fmtInt(b.summary?.fill_count)}`} />
        <MetricCard label="Delta breaches" value={fmtInt(breachDelta)} tone={breachDelta == null ? 'neutral' : breachDelta > 0 ? 'bad' : breachDelta < 0 ? 'good' : 'neutral'} sub={`A ${fmtInt(a.summary?.limit_breaches)} / B ${fmtInt(b.summary?.limit_breaches)}`} />
      </div>

      <Card title="PnL comparison" subtitle="Side-by-side by product where both runs include the metric">
        {pnlBarData.length > 0 ? (
          <BarGroupChart
            data={pnlBarData}
            labelKey="label"
            series={[
              { key: 'a', name: nameA, color: '#7de7ff' },
              { key: 'b', name: nameB, color: '#c7ab66' },
            ]}
            height={260}
          />
        ) : (
          <EmptyState title="Comparable PnL metrics not present" message="Both selected runs need replay summary PnL values for this chart." />
        )}
      </Card>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card title="Per-product PnL">
          <DataTable rows={productRows} cols={productCols} striped emptyMsg="Per-product replay summaries are not present in both runs." />
        </Card>
        <Card title="Behaviour comparison">
          <DataTable rows={behaviourRows} cols={behaviourCols} striped emptyMsg="Behaviour summaries are not present in these runs." />
        </Card>
      </div>

      {(a.monteCarlo?.summary || b.monteCarlo?.summary) && (
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
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
                    { label: 'P05', value: fmtNum(mc.p05), tone: colorForValue(mc.p05) },
                    { label: 'Positive rate', value: fmtPct(mc.positive_rate), tone: mc.positive_rate > 0.5 ? 'good' : 'warn' },
                    { label: 'Std dev', value: fmtNum(mc.std), tone: 'neutral' },
                    { label: 'Mean DD', value: fmtNum(mc.mean_max_drawdown), tone: 'warn' },
                    { label: 'Sessions', value: fmtInt(mc.session_count), tone: 'neutral' },
                  ]}
                />
              ) : (
                <div className={`text-xs italic ${color}`}>not available for this bundle type</div>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

function RunBox({ label, name, payload, accent }: { label: string; name: string; payload: DashboardPayload; accent: 'accent' | 'accent-2' }) {
  return (
    <div className={`rounded-lg border px-4 py-3 ${accent === 'accent' ? 'border-accent/30 bg-accent/10' : 'border-accent-2/30 bg-accent-2/10'}`}>
      <div className={accent === 'accent' ? 'mb-1 text-xs font-bold uppercase tracking-wider text-accent' : 'mb-1 text-xs font-bold uppercase tracking-wider text-accent-2'}>{label}</div>
      <div className="truncate text-sm font-semibold text-txt">{name}</div>
      <div className="hud-label mt-1 text-muted">{interpretBundle(payload).badge}</div>
    </div>
  )
}

function delta(a: unknown, b: unknown): number | null {
  const left = numberOrNull(a)
  const right = numberOrNull(b)
  return left == null || right == null ? null : left - right
}
