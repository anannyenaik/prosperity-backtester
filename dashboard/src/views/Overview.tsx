import { Activity } from 'lucide-react'
import { useStore } from '../store'
import { MetricCard } from '../components/MetricCard'
import { Card } from '../components/Card'
import { KVGrid } from '../components/KVGrid'
import { DataTable, type ColDef } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { ProductToggle } from '../components/ProductToggle'
import { fmtNum, fmtInt, fmtPct, fmtDate, colorForValue } from '../lib/format'
import { PRODUCT_LABELS, type Product } from '../types'

export function Overview() {
  const { getActiveRun, getCompareRun, activeProduct } = useStore()
  const run = getActiveRun()
  const compare = getCompareRun()

  if (!run) {
    return (
      <EmptyState
        icon={<Activity className="w-10 h-10" />}
        title="No run loaded"
        message="Load a dashboard.json bundle to begin analysis."
      />
    )
  }

  const { payload } = run
  const summary = payload.summary
  const mc = payload.monteCarlo?.summary
  const meta = payload.meta
  const behaviour = payload.behaviour?.per_product?.[activeProduct]
  const productSummary = summary?.per_product?.[activeProduct]
  const productLabel = PRODUCT_LABELS[activeProduct as Product] ?? activeProduct
  const cmp = compare?.payload

  // Dataset integrity rows
  const datasetRows = (payload.datasetReports ?? []).map((r) => ({
    day: r.day,
    timestamps: r.validation?.timestamps,
    issue_score: r.validation?.issue_score,
    crossed_books: r.validation?.crossed_book_rows,
    one_sided: r.validation?.one_sided_book_rows,
    source: r.metadata?.source ?? r.validation?.source ?? 'historical',
  }))

  // Assumptions rows
  const assumptionRows = [
    ...(payload.assumptions?.exact ?? []).map((a) => ({ type: 'exact', item: a })),
    ...(payload.assumptions?.approximate ?? []).map((a) => ({ type: 'approx', item: a })),
  ]

  const datasetCols: ColDef<(typeof datasetRows)[0]>[] = [
    { key: 'day', header: 'Day', fmt: 'int', width: 60 },
    { key: 'timestamps', header: 'Ticks', fmt: 'int' },
    { key: 'issue_score', header: 'Issue score', fmt: 'int', tone: (v) => (Number(v) > 0 ? 'warn' : 'neutral') },
    { key: 'crossed_books', header: 'Crossed', fmt: 'int', tone: (v) => (Number(v) > 0 ? 'bad' : 'neutral') },
    { key: 'one_sided', header: 'One-sided', fmt: 'int', tone: (v) => (Number(v) > 50 ? 'warn' : 'neutral') },
    { key: 'source', header: 'Source', fmt: 'str' },
  ]

  return (
    <div className="space-y-5">
      <PageHeader
        kicker="Overview / run observatory"
        title="Strategy state"
        accent="at a glance"
        description="Run metadata, data integrity, assumptions and the first-pass signals that decide where to inspect next."
        action={<ProductToggle />}
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          label="Final PnL"
          value={fmtNum(summary?.final_pnl ?? 0)}
          sub={`Max DD ${fmtNum(summary?.max_drawdown ?? 0)}`}
          tone={colorForValue(summary?.final_pnl)}
          delta={cmp?.summary ? `vs ${fmtNum((summary?.final_pnl ?? 0) - (cmp.summary.final_pnl ?? 0))}` : undefined}
          deltaTone={colorForValue((summary?.final_pnl ?? 0) - (cmp?.summary?.final_pnl ?? 0))}
        />
        <MetricCard
          label="Fill count"
          value={fmtInt(summary?.fill_count)}
          sub={`Orders ${fmtInt(summary?.order_count)}`}
        />
        <MetricCard
          label="Limit breaches"
          value={fmtInt(summary?.limit_breaches ?? 0)}
          tone={summary?.limit_breaches ? 'bad' : 'good'}
          sub="Batch-dropped order groups"
        />
        <MetricCard
          label="Run type"
          value={payload.type ?? '-'}
          sub={fmtDate(meta?.createdAt)}
          tone="neutral"
        />
      </div>

      {/* MC summary if present */}
      {mc && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <MetricCard label="MC mean" value={fmtNum(mc.mean)} tone={colorForValue(mc.mean)} sub={`Sessions: ${fmtInt(mc.session_count)}`} />
          <MetricCard label="MC P05" value={fmtNum(mc.p05)} tone={colorForValue(mc.p05)} sub={`ES05 ${fmtNum(mc.expected_shortfall_05)}`} />
          <MetricCard label="Positive rate" value={fmtPct(mc.positive_rate)} tone={mc.positive_rate > 0.5 ? 'good' : 'warn'} sub={`Std ${fmtNum(mc.std)}`} />
          <MetricCard label="Mean drawdown" value={fmtNum(mc.mean_max_drawdown)} tone="warn" sub={`Range ${fmtNum(mc.min)} / ${fmtNum(mc.max)}`} />
        </div>
      )}

      {/* Product detail row */}
      {productSummary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <MetricCard
            label={`${productLabel} MTM`}
            value={fmtNum(productSummary.final_mtm)}
            tone={colorForValue(productSummary.final_mtm)}
            sub={`Realised ${fmtNum(productSummary.realised)}`}
          />
          <MetricCard
            label={`${productLabel} position`}
            value={fmtInt(productSummary.final_position)}
            sub={`Cap ${fmtNum((Math.abs(productSummary.final_position) / 80) * 100, 0)}%`}
            tone={Math.abs(productSummary.final_position) >= 80 ? 'warn' : 'neutral'}
          />
          {behaviour && (
            <>
              <MetricCard
                label="Cap usage ratio"
                value={fmtPct(behaviour.cap_usage_ratio)}
                tone={behaviour.cap_usage_ratio > 0.6 ? 'warn' : 'neutral'}
                sub={`Peak pos ${fmtInt(behaviour.peak_abs_position)}`}
              />
              <MetricCard
                label="Fill markout +5"
                value={fmtNum(behaviour.average_fill_markout_5)}
                tone={colorForValue(behaviour.average_fill_markout_5)}
                sub="Avg 5-tick signed edge"
              />
            </>
          )}
        </div>
      )}

      {/* Run metadata + dataset integrity */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="Run metadata">
          <KVGrid
            cols={2}
            pairs={[
              { label: 'Run name', value: meta?.runName },
              { label: 'Trader', value: meta?.traderName },
              { label: 'Mode', value: meta?.mode },
              { label: 'Fill model', value: meta?.fillModel?.name },
              { label: 'Created', value: fmtDate(meta?.createdAt) },
              { label: 'Schema v', value: meta?.schemaVersion },
              { label: 'Dominant risk', value: payload.behaviour?.summary?.dominant_risk_product },
              { label: 'Dominant turnover', value: payload.behaviour?.summary?.dominant_turnover_product },
            ]}
          />
        </Card>

        <Card title="Dataset integrity">
          {datasetRows.length > 0 ? (
            <DataTable rows={datasetRows} cols={datasetCols} striped />
          ) : (
            <EmptyState title="No dataset reports" message="Replay bundles include dataset reports." />
          )}
        </Card>
      </div>

      {/* Exact vs approximate */}
      <Card title="Exact vs approximate assumptions">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <div className="text-good text-xs font-semibold uppercase tracking-wider mb-3">Exact</div>
            <ul className="space-y-2">
              {(payload.assumptions?.exact ?? []).map((a, i) => (
                <li key={i} className="text-txt text-xs flex items-start gap-2">
                  <span className="mt-0.5 text-good">OK</span>
                  {a}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <div className="text-warn text-xs font-semibold uppercase tracking-wider mb-3">Approximate</div>
            <ul className="space-y-2">
              {(payload.assumptions?.approximate ?? []).map((a, i) => (
                <li key={i} className="text-txt text-xs flex items-start gap-2">
                  <span className="mt-0.5 text-warn">~</span>
                  {a}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Card>
    </div>
  )
}
