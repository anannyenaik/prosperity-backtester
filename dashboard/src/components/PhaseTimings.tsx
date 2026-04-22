import { useMemo } from 'react'
import { Card } from './Card'
import { numberOrNull } from '../lib/bundles'

interface Props {
  phaseTimings: Record<string, unknown> | null | undefined
  sessionCount?: number | null
  workerCount?: number | null
  monteCarloBackend?: string | null
}

interface PhaseRow {
  key: string
  label: string
  seconds: number
  share: number
  hint?: string
}

const PHASE_LABELS: Array<[string, string, string?]> = [
  ['market_generation_seconds', 'Market generation', 'Latent paths, books, trade prints (synthetic only)'],
  ['state_build_seconds', 'State build', 'TradingState, OrderDepth assembly per tick'],
  ['trader_seconds', 'Trader callback', 'Time spent inside trader.run(state)'],
  ['execution_seconds', 'Execution', 'Order matching, fills, ledger updates'],
  ['path_metrics_seconds', 'Path metrics', 'Per-tick PnL, inventory and band buckets'],
  ['postprocess_seconds', 'Postprocess', 'Slippage finalisation, summary aggregation'],
  ['sample_row_compaction_seconds', 'Sample compaction', 'Sample-session row trimming for storage'],
  ['dashboard_build_seconds', 'Dashboard build', 'dashboard.json assembly'],
  ['bundle_write_seconds', 'Bundle write', 'On-disk file emission'],
  ['provenance_capture_seconds', 'Provenance capture', 'Git/runtime snapshotting for dashboard and manifest trust metadata'],
  ['python_overhead_seconds', 'Python overhead', 'Loop, dispatch and unprofiled work'],
]

export function PhaseTimings({ phaseTimings, sessionCount, workerCount, monteCarloBackend }: Props) {
  const rows = useMemo(() => buildRows(phaseTimings), [phaseTimings])
  if (!rows) return null

  const wallSeconds = numberOrNull(phaseTimings?.session_execution_wall_seconds)
  const totalSeconds = numberOrNull(phaseTimings?.session_total_seconds)
  const rustWall = numberOrNull(phaseTimings?.rust_internal_wall_seconds)
  const sessions = sessionCount ?? null
  const throughput = sessions != null && wallSeconds != null && wallSeconds > 0 ? sessions / wallSeconds : null
  const perSession = sessions != null && totalSeconds != null && sessions > 0 ? totalSeconds / sessions : null

  return (
    <Card
      title="Performance breakdown"
      kicker="Runtime / where the time went"
      subtitle="Phase timings recorded by the backend, summed across all sessions. Wall is the actual elapsed time; total includes work that overlapped across worker processes."
    >
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Wall" value={fmtSec(wallSeconds)} hint="Elapsed across all workers" />
        <Stat label="Per session" value={fmtMs(perSession)} hint="Mean total work / session" />
        <Stat label="Throughput" value={throughput == null ? 'n/a' : `${throughput.toFixed(1)} sess/s`} hint="Sessions completed per second" tone="accent" />
        <Stat label="Backend" value={monteCarloBackend ?? 'n/a'} hint={workerCount != null ? `${workerCount} worker${workerCount === 1 ? '' : 's'}` : undefined} />
      </div>

      <div className="mt-5 space-y-2">
        {rows.map((row) => (
          <PhaseRowView key={row.key} row={row} />
        ))}
      </div>

      {rustWall != null && (
        <div className="hud-label mt-4 text-muted">
          Rust engine internal wall {fmtSec(rustWall)}. The Rust backend reports its own parallel section in addition to per-tick timings above.
        </div>
      )}
    </Card>
  )
}

function PhaseRowView({ row }: { row: PhaseRow }) {
  const widthPct = Math.max(0, Math.min(100, row.share * 100))
  return (
    <div className="grid grid-cols-[160px_1fr_60px_60px] items-center gap-3 text-xs">
      <div className="truncate text-txt-soft" title={row.hint}>{row.label}</div>
      <div className="relative h-2 overflow-hidden rounded-full bg-white/[0.04]">
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-accent/70 via-accent/45 to-accent-2/40"
          style={{ width: `${widthPct}%` }}
        />
      </div>
      <div className="font-mono text-right text-muted tabular-nums">{fmtSec(row.seconds)}</div>
      <div className="font-mono text-right text-muted tabular-nums">{(row.share * 100).toFixed(1)}%</div>
    </div>
  )
}

function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: 'accent' | 'neutral' }) {
  const valueClass = tone === 'accent' ? 'text-accent' : 'text-txt'
  return (
    <div className="rounded-lg border border-border bg-white/[0.025] px-3 py-3">
      <div className="hud-label text-muted">{label}</div>
      <div className={`font-display mt-2 text-lg font-semibold ${valueClass}`}>{value}</div>
      {hint && <div className="hud-label mt-2 text-muted">{hint}</div>}
    </div>
  )
}

function buildRows(phaseTimings: Record<string, unknown> | null | undefined): PhaseRow[] | null {
  if (!phaseTimings) return null
  const total = numberOrNull(phaseTimings.session_total_seconds) ?? 0
  if (total <= 0) return null
  const collected: PhaseRow[] = []
  for (const [key, label, hint] of PHASE_LABELS) {
    const seconds = numberOrNull(phaseTimings[key])
    if (seconds == null || seconds <= 0) continue
    collected.push({ key, label, seconds, share: seconds / total, hint })
  }
  if (!collected.length) return null
  collected.sort((a, b) => b.seconds - a.seconds)
  return collected
}

function fmtSec(value: number | null): string {
  if (value == null) return 'n/a'
  if (value < 0.0005) return '<1 ms'
  if (value < 1) return `${(value * 1000).toFixed(0)} ms`
  return `${value.toFixed(2)} s`
}

function fmtMs(value: number | null): string {
  if (value == null) return 'n/a'
  if (value < 0.001) return '<1 ms'
  if (value < 1) return `${(value * 1000).toFixed(1)} ms`
  return `${value.toFixed(3)} s`
}
