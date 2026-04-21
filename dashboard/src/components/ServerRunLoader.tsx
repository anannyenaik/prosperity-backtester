import { useMemo, useState } from 'react'
import { RefreshCw, Server } from 'lucide-react'
import { clsx } from 'clsx'
import { useStore, type ServerRunMeta } from '../store'
import type { DashboardPayload } from '../types'
import { fmtBytes, fmtDate, fmtNum } from '../lib/format'

const TYPE_BUTTONS = [
  ['replay', 'Latest replay'],
  ['monte_carlo', 'Latest MC'],
  ['comparison', 'Latest compare'],
] as const

type RunFilter = 'all' | 'replay' | 'monte_carlo' | 'comparison' | 'calibration' | 'optimization' | 'round2_scenarios'

const RUN_TYPE_MAP: Record<string, Exclude<RunFilter, 'all'>> = {
  replay: 'replay',
  mc: 'monte_carlo',
  montecarlo: 'monte_carlo',
  'monte-carlo': 'monte_carlo',
  monte_carlo: 'monte_carlo',
  compare: 'comparison',
  comparison: 'comparison',
  scenario_compare: 'comparison',
  'scenario-compare': 'comparison',
  calibrate: 'calibration',
  calibration: 'calibration',
  optimize: 'optimization',
  optimise: 'optimization',
  optimization: 'optimization',
  optimisation: 'optimization',
  round2: 'round2_scenarios',
  'round2-scenarios': 'round2_scenarios',
  round2_scenarios: 'round2_scenarios',
}

export function ServerRunLoader() {
  const { serverRuns, setServerRuns, loadRun } = useStore()
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState<RunFilter>('all')

  async function fetchRuns(): Promise<ServerRunMeta[]> {
    setLoading(true)
    try {
      const res = await fetch('/api/runs')
      if (res.ok) {
        const data = await res.json()
        const runs = data as ServerRunMeta[]
        setServerRuns(runs)
        setOpen(true)
        return runs
      }
    } catch {
      setOpen(true)
    } finally {
      setLoading(false)
    }
    return []
  }

  async function loadFromServer(run: ServerRunMeta) {
    const res = await fetch(`/api/run/${encodeURIComponent(run.path)}`)
    if (res.ok) {
      const payload = (await res.json()) as DashboardPayload
      loadRun(payload, run.name)
    }
  }

  async function loadLatestFromServer(kind?: Exclude<RunFilter, 'all'>) {
    const runs = await fetchRuns()
    const target = kind ? runs.find((run) => normaliseRunType(run.type) === kind) : runs[0]
    if (target) {
      await loadFromServer(target)
    }
  }

  const visibleRuns = useMemo(() => {
    if (filter === 'all') return serverRuns
    return serverRuns.filter((run) => normaliseRunType(run.type) === filter)
  }, [filter, serverRuns])

  const availableFilters = useMemo(() => {
    const types = new Set<RunFilter>(['all'])
    for (const run of serverRuns) {
      const type = normaliseRunType(run.type)
      if (type) types.add(type)
    }
    return Array.from(types)
  }, [serverRuns])

  return (
    <div className="mt-4">
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => void loadLatestFromServer()}
          disabled={loading}
          className="subtle-button inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs"
        >
          {loading ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Server className="h-3.5 w-3.5" />}
          Open latest run
        </button>
        {TYPE_BUTTONS.map(([type, label]) => (
          <button
            key={type}
            onClick={() => void loadLatestFromServer(type)}
            disabled={loading}
            className="subtle-button inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs"
          >
            {loading ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Server className="h-3.5 w-3.5" />}
            {label}
          </button>
        ))}
        <button
          onClick={() => void fetchRuns()}
          disabled={loading}
          className="subtle-button inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs"
        >
          {loading ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Server className="h-3.5 w-3.5" />}
          Browse local server
        </button>
      </div>

      {open && serverRuns.length > 0 && (
        <div className="mt-3 overflow-hidden rounded-lg border border-border bg-bg/45">
          <div className="border-b border-border bg-white/[0.03] px-4 py-3">
            <div className="hud-label text-muted">
              Available bundles ({visibleRuns.length} shown of {serverRuns.length})
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {availableFilters.map((item) => (
                <button
                  key={item}
                  onClick={() => setFilter(item)}
                  className={clsx(
                    'rounded-lg px-3 py-2 text-[11px] uppercase tracking-[0.12em]',
                    filter === item ? 'signal-button' : 'subtle-button',
                  )}
                >
                  {filterLabel(item)}
                </button>
              ))}
            </div>
          </div>
          <div className="max-h-72 overflow-y-auto divide-y divide-border">
            {visibleRuns.map((run) => (
              <button
                key={run.path}
                onClick={() => loadFromServer(run)}
                className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left transition-colors hover:bg-accent/5"
              >
                <span className="min-w-0">
                  <span className="block truncate font-display text-xs font-semibold uppercase tracking-[0.08em] text-txt">
                    {run.name}
                  </span>
                  <span className="hud-label mt-1 flex flex-wrap gap-2 text-muted">
                    <span>{filterLabel(normaliseRunType(run.type))}</span>
                    {run.profile && <span>{run.profile}</span>}
                    {run.workflowTier && <span>{run.workflowTier}</span>}
                    {run.engineBackend && <span>{run.engineBackend}</span>}
                    {run.workerCount != null && run.workerCount > 1 && <span>{run.workerCount} workers</span>}
                    {run.gitDirty === true && <span>dirty git</span>}
                    {run.sizeBytes != null && <span>{fmtBytes(run.sizeBytes)}</span>}
                    <span>{fmtDate(run.createdAt)}</span>
                  </span>
                  <span className="mt-1 block truncate text-[11px] text-muted/85">{run.path}</span>
                </span>
                {run.finalPnl != null && (
                  <span className={clsx('font-mono text-xs', run.finalPnl >= 0 ? 'text-good' : 'text-bad')}>
                    {fmtNum(run.finalPnl)}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {open && serverRuns.length === 0 && (
        <div className="mt-3 rounded-lg border border-border bg-white/[0.025] px-4 py-3 text-sm text-muted">
          No dashboard bundles were found under the served directory.
        </div>
      )}
    </div>
  )
}

function normaliseRunType(value: string | null | undefined): RunFilter {
  const key = (value ?? 'unknown').toLowerCase()
  return RUN_TYPE_MAP[key] ?? 'all'
}

function filterLabel(value: RunFilter) {
  return {
    all: 'All',
    replay: 'Replay',
    monte_carlo: 'MC',
    comparison: 'Compare',
    calibration: 'Calibration',
    optimization: 'Optimise',
    round2_scenarios: 'Round 2',
  }[value]
}
