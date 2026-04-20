import { Target } from 'lucide-react'
import { useStore } from '../store'
import { Card } from '../components/Card'
import { MetricCard } from '../components/MetricCard'
import { DataTable, type ColDef } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { BundleBadge } from '../components/BundleBadge'
import { BarGroupChart } from '../charts/BarGroupChart'
import { fmtNum, fmtInt, fmtPct, colorForValue } from '../lib/format'
import { formatBool, getTabAvailability, numberOrNull } from '../lib/bundles'
import type { Round2PairwiseRow, Round2ScenarioRow, Round2WinnerRow } from '../types'

export function Round2() {
  const { getActiveRun } = useStore()
  const run = getActiveRun()
  const availability = getTabAvailability(run?.payload, 'round2')
  const round2 = run?.payload.round2
  const meta = run?.payload.meta
  const access = meta?.accessScenario

  const scenarioRows = round2?.scenarioRows ?? []
  const winnerRows = round2?.winnerRows ?? []
  const mafRows = round2?.mafSensitivityRows ?? []
  const pairwiseRows = round2?.pairwiseRows ?? []

  if (!run || !availability.supported || !round2) {
    return (
      <EmptyState
        icon={<Target className="h-10 w-10" />}
        title={availability.title}
        message={availability.message}
      />
    )
  }

  const bestRow = maxByNumber(scenarioRows, (row) => row.final_pnl)
  const accessRows = scenarioRows.filter((row) => row.extra_access_enabled)
  const bestBreakEven = accessRows.reduce<number | null>((best, row) => {
    const value = row.break_even_maf_vs_no_access
    if (value == null) return best
    return best == null ? value : Math.max(best, value)
  }, null)
  const changedCount = winnerRows.filter((row) => row.ranking_changed_vs_no_access).length
  const scenarioCount = new Set(scenarioRows.map((row) => row.scenario)).size || numberOrNull(access?.scenario_count)

  const scenarioCols: ColDef<Round2ScenarioRow>[] = [
    { key: 'scenario', header: 'Scenario', fmt: 'str' },
    { key: 'trader', header: 'Trader', fmt: 'str' },
    { key: 'final_pnl', header: 'Net PnL', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'gross_pnl_before_maf', header: 'Gross', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'maf_cost', header: 'MAF', fmt: 'num', tone: (v) => (Number(v) > 0 ? 'warn' : 'neutral') },
    { key: 'marginal_access_pnl_before_maf', header: 'Access edge', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'osmium_pnl', header: 'Osmium', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'pepper_pnl', header: 'Pepper', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'max_drawdown', header: 'Max DD', fmt: 'num', tone: () => 'warn' },
    { key: 'fill_count', header: 'Fills', fmt: 'int' },
    { key: 'mc_mean', header: 'MC mean', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'mc_p05', header: 'MC P05', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
  ]

  const winnerCols: ColDef<Round2WinnerRow>[] = [
    { key: 'scenario', header: 'Scenario', fmt: 'str' },
    { key: 'winner', header: 'Replay winner', fmt: 'str' },
    { key: 'winner_final_pnl', header: 'Winner PnL', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'gap_to_second', header: 'Gap', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'mc_winner', header: 'MC winner', fmt: 'str' },
    { key: 'mc_winner_mean', header: 'MC mean', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    {
      key: 'ranking_changed_vs_no_access',
      header: 'Ranking shift',
      fmt: 'str',
      render: (v) => (v == null ? '-' : v ? 'yes' : 'no'),
      tone: (v) => (v ? 'warn' : 'neutral'),
    },
  ]

  const pairwiseCols: ColDef<Round2PairwiseRow>[] = [
    { key: 'scenario', header: 'Scenario', fmt: 'str' },
    { key: 'trader_a', header: 'A', fmt: 'str' },
    { key: 'trader_b', header: 'B', fmt: 'str' },
    { key: 'replay_diff_a_minus_b', header: 'Replay diff', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'mc_mean_diff_a_minus_b', header: 'MC diff', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'mc_p05_diff', header: 'Diff P05', fmt: 'num', tone: (v) => colorForValue(Number(v)) },
    { key: 'a_win_rate', header: 'A win rate', fmt: 'pct', tone: (v) => (Number(v) > 0.6 ? 'good' : Number(v) < 0.4 ? 'bad' : 'warn') },
    { key: 'sessions', header: 'Runs', fmt: 'int' },
    { key: 'likely_winner', header: 'Likely winner', fmt: 'str' },
  ]

  const mafChartRows = mafRows.slice(0, 24).map((row) => ({
    label: `${row.trader} / ${row.maf_bid == null ? 'MAF n/a' : fmtInt(row.maf_bid)}`,
    net: row.final_pnl,
    gross: row.gross_pnl_before_maf,
  })).filter((row) => numberOrNull(row.net) != null)
  const mafSeries = [
    { key: 'net', name: 'Net', color: '#c7ab66' },
    ...(mafChartRows.length > 0 && mafChartRows.every((row) => numberOrNull(row.gross) != null)
      ? [{ key: 'gross', name: 'Gross', color: '#7de7ff' }]
      : []),
  ]

  const registry = round2?.assumptionRegistry

  return (
    <div className="space-y-5">
      <PageHeader
        kicker="Round 2 / MAF decision board"
        title="Access"
        accent="scenarios"
        description="Net PnL, access value, MAF sensitivity, product contribution and ranking stability across explicit local assumptions."
        meta={<BundleBadge payload={run.payload} />}
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Scenarios" value={fmtInt(scenarioCount)} sub={`Round ${meta?.round ?? 2}`} />
        <MetricCard label="Best net PnL" value={fmtNum(bestRow?.final_pnl)} tone={colorForValue(bestRow?.final_pnl)} sub={bestRow?.trader ?? 'No winning row'} />
        <MetricCard label="Best break-even MAF" value={fmtNum(bestBreakEven)} tone={colorForValue(bestBreakEven)} sub="Access edge before fee" />
        <MetricCard label="Ranking shifts" value={fmtInt(changedCount)} tone={changedCount > 0 ? 'warn' : 'neutral'} sub="Versus no-access baseline" />
      </div>

      {access && Object.keys(access).length > 0 && (
        <Card title="Active access assumption">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            {[
              ['Scenario', access.name ?? 'not available'],
              ['Contract won', formatBool(access.contract_won)],
              ['MAF bid', fmtNum(access.maf_bid)],
              ['Expected extra quotes', fmtPct(access.expected_extra_quote_fraction)],
              ['Mode', access.mode ?? 'not available'],
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg border border-border bg-surface-2 px-3 py-3">
                <div className="hud-label text-muted">{label}</div>
                <div className="font-display mt-2 truncate text-sm font-bold uppercase tracking-[0.08em] text-txt">{value}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {winnerRows.length > 0 && (
        <Card title="Scenario winners" subtitle="Replay and Monte Carlo ranking by assumption">
          <DataTable rows={winnerRows} cols={winnerCols} striped />
        </Card>
      )}

      {scenarioRows.length > 0 && (
        <Card title="Scenario table" subtitle="Net, gross, MAF, product contribution and robustness">
          <DataTable rows={scenarioRows} cols={scenarioCols} maxRows={200} striped />
        </Card>
      )}

      {mafChartRows.length > 0 && (
        <Card title="MAF sensitivity" subtitle="Net versus gross PnL under tested fee levels">
          <BarGroupChart
            data={mafChartRows}
            labelKey="label"
            series={mafSeries}
            colorByValue
            height={300}
          />
        </Card>
      )}

      {pairwiseRows.length > 0 && (
        <Card title="Pairwise Monte Carlo confidence" subtitle="Aligned-seed differences by scenario">
          <DataTable rows={pairwiseRows} cols={pairwiseCols} maxRows={120} striped />
        </Card>
      )}

      {registry && (
        <Card title="Assumption boundary">
          <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
            {([
              ['Grounded', registry.grounded ?? []],
              ['Configurable', registry.configurable ?? []],
              ['Unknown', registry.unknown ?? []],
            ] as const).map(([title, items]) => (
              <div key={title}>
                <div className="hud-label mb-3 text-accent">{title}</div>
                <ul className="space-y-2 text-xs leading-5 text-txt-soft">
                  {items.map((item, idx) => (
                    <li key={idx}>{item}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}

function maxByNumber<T>(rows: T[], getValue: (row: T) => unknown): T | null {
  let best: T | null = null
  let bestValue: number | null = null
  for (const row of rows) {
    const value = numberOrNull(getValue(row))
    if (value == null) continue
    if (bestValue == null || value > bestValue) {
      best = row
      bestValue = value
    }
  }
  return best
}
