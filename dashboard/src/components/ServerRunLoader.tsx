import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, RefreshCw, Server, X } from 'lucide-react'
import { clsx } from 'clsx'
import { useStore, type ServerRunMeta } from '../store'
import type { DashboardPayload } from '../types'
import { fmtBytes, fmtDate, fmtNum } from '../lib/format'

type RunFilter = 'all' | 'replay' | 'monte_carlo' | 'comparison' | 'calibration' | 'optimization' | 'round2_scenarios'
type QuickLoadKind = Exclude<RunFilter, 'all'>

interface QuickLoadButton {
  type: QuickLoadKind
  label: string
}

interface BrowserState {
  open: boolean
  status: 'list' | 'empty' | 'error'
  message: string | null
}

interface LoaderNotice {
  variant: 'unavailable' | 'error'
  title: string
  message: string
}

const TYPE_BUTTONS: QuickLoadButton[] = [
  { type: 'replay', label: 'Latest replay' },
  { type: 'monte_carlo', label: 'Latest MC' },
  { type: 'comparison', label: 'Latest compare' },
  { type: 'calibration', label: 'Latest calibration' },
  { type: 'optimization', label: 'Latest optimise' },
  { type: 'round2_scenarios', label: 'Latest Round 2' },
]

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
  const [loadingKey, setLoadingKey] = useState<string | null>(null)
  const [browserState, setBrowserState] = useState<BrowserState>({
    open: false,
    status: 'list',
    message: null,
  })
  const [notice, setNotice] = useState<LoaderNotice | null>(null)
  const [filter, setFilter] = useState<RunFilter>('all')

  useEffect(() => {
    if (!browserState.open || typeof window === 'undefined') return

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setBrowserState((current) => ({ ...current, open: false }))
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [browserState.open])

  async function runWithLoading(key: string, work: () => Promise<void>) {
    if (loadingKey) return
    setLoadingKey(key)
    try {
      await work()
    } finally {
      setLoadingKey(null)
    }
  }

  async function fetchRuns(options: { openBrowser?: boolean } = {}): Promise<ServerRunMeta[] | null> {
    try {
      const res = await fetch('/api/runs')
      if (!res.ok) {
        throw new Error(`Server returned ${res.status}`)
      }
      const runs = (await res.json()) as ServerRunMeta[]
      setServerRuns(runs)
      if (options.openBrowser) {
        setNotice(null)
        setBrowserState({
          open: true,
          status: runs.length > 0 ? 'list' : 'empty',
          message: null,
        })
      }
      return runs
    } catch {
      if (options.openBrowser) {
        setNotice(null)
        setBrowserState({
          open: true,
          status: 'error',
          message: 'Could not reach the local dashboard bundle server. Start the server and try again.',
        })
      }
      return null
    }
  }

  async function loadFromServer(run: ServerRunMeta) {
    const res = await fetch(`/api/run/${encodeURIComponent(run.path)}`)
    if (!res.ok) {
      setNotice({
        variant: 'error',
        title: 'Bundle load failed',
        message: `The server could not open ${run.name}. Try again or browse another bundle.`,
      })
      return
    }
    const payload = (await res.json()) as DashboardPayload
    setNotice(null)
    setBrowserState((current) => ({ ...current, open: false }))
    loadRun(payload, run.name)
  }

  async function openBrowser() {
    await runWithLoading('browse', async () => {
      await fetchRuns({ openBrowser: true })
    })
  }

  async function loadLatestFromServer(kind?: QuickLoadKind) {
    await runWithLoading(kind ? `latest:${kind}` : 'latest', async () => {
      setNotice(null)
      setBrowserState((current) => ({ ...current, open: false }))
      const runs = await fetchRuns()
      if (!runs) {
        setNotice(serverErrorNotice(kind))
        return
      }

      const target = kind ? runs.find((run) => normaliseRunType(run.type) === kind) : runs[0]
      if (!target) {
        setNotice(unavailableNotice(kind))
        return
      }

      await loadFromServer(target)
    })
  }

  async function loadSpecificRun(run: ServerRunMeta) {
    await runWithLoading(`run:${run.path}`, async () => {
      await loadFromServer(run)
    })
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
    <div className="relative mt-4">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void loadLatestFromServer()}
          disabled={loadingKey != null}
          className="subtle-button inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs"
        >
          {loadingKey === 'latest' ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Server className="h-3.5 w-3.5" />}
          Open latest run
        </button>
        {TYPE_BUTTONS.map(({ type, label }) => (
          <button
            key={type}
            type="button"
            onClick={() => void loadLatestFromServer(type)}
            disabled={loadingKey != null}
            className="subtle-button inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs"
          >
            {loadingKey === `latest:${type}` ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Server className="h-3.5 w-3.5" />}
            {label}
          </button>
        ))}
        <button
          type="button"
          onClick={() => {
            if (browserState.open) {
              setBrowserState((current) => ({ ...current, open: false }))
              return
            }
            void openBrowser()
          }}
          disabled={loadingKey != null}
          className="subtle-button inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs"
        >
          {loadingKey === 'browse' ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : browserState.open ? <X className="h-3.5 w-3.5" /> : <Server className="h-3.5 w-3.5" />}
          {browserState.open ? 'Hide browser' : 'Browse local server'}
        </button>
      </div>

      {browserState.open && (
        <>
          <button
            type="button"
            aria-label="Close bundle browser"
            onClick={() => setBrowserState((current) => ({ ...current, open: false }))}
            className="fixed inset-0 z-20 cursor-default bg-transparent"
          />
          <div className="absolute left-0 right-0 top-full z-30 mt-3 pointer-events-none">
            <div className="pointer-events-auto glass-panel flex max-h-[calc(100vh-14rem)] flex-col overflow-hidden rounded-lg border-border-2 shadow-card">
              <div className="flex items-start justify-between gap-4 border-b border-border bg-white/[0.03] px-4 py-3">
                <div>
                  <div className="hud-label text-accent-2">Bundle browser</div>
                  <div className="mt-2 text-sm text-muted">
                    {browserState.status === 'list'
                      ? `Available bundles (${visibleRuns.length} shown of ${serverRuns.length})`
                      : browserState.status === 'empty'
                        ? 'No dashboard bundles found'
                        : 'Local bundle server unavailable'}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setBrowserState((current) => ({ ...current, open: false }))}
                  className="subtle-button inline-flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs"
                >
                  <X className="h-3.5 w-3.5" />
                  Close
                </button>
              </div>

              {browserState.status === 'list' && (
                <>
                  <div className="border-b border-border bg-white/[0.02] px-4 py-3">
                    <div className="flex flex-wrap gap-2">
                      {availableFilters.map((item) => (
                        <button
                          key={item}
                          type="button"
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
                  <div className="min-h-0 flex-1 overflow-y-auto divide-y divide-border">
                    {visibleRuns.map((run) => (
                      <button
                        key={run.path}
                        type="button"
                        disabled={loadingKey != null}
                        onClick={() => void loadSpecificRun(run)}
                        className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left transition-colors hover:bg-accent/5 disabled:cursor-wait disabled:opacity-70"
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
                            {run.monteCarloBackend && <span>mc:{run.monteCarloBackend}</span>}
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
                </>
              )}

              {browserState.status === 'empty' && (
                <div className="px-4 py-4 text-sm leading-6 text-muted">
                  No dashboard bundles were found under the served directory.
                </div>
              )}

              {browserState.status === 'error' && (
                <div className="px-4 py-4 text-sm leading-6 text-muted">
                  {browserState.message}
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {notice && (
        <div className="absolute left-0 right-0 top-full z-30 mt-3 pointer-events-none">
          <div
            role="status"
            aria-live="polite"
            className={clsx(
              'pointer-events-auto rounded-lg border px-4 py-3 shadow-card backdrop-blur-2xl',
              notice.variant === 'unavailable'
                ? 'border-warn/30 bg-surface-2/92'
                : 'border-bad/30 bg-surface-2/92',
            )}
          >
            <div className="flex items-start gap-3">
              <div
                className={clsx(
                  'mt-0.5 rounded-full border p-1.5',
                  notice.variant === 'unavailable'
                    ? 'border-warn/30 bg-warn/10 text-warn'
                    : 'border-bad/30 bg-bad/10 text-bad',
                )}
              >
                <AlertTriangle className="h-3.5 w-3.5" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="hud-label text-accent-2">
                  {notice.variant === 'unavailable' ? 'Quick load unavailable' : 'Quick load error'}
                </div>
                <div className="mt-1 font-display text-sm font-semibold uppercase tracking-[0.08em] text-txt">
                  {notice.title}
                </div>
                <div className="mt-1 text-sm leading-6 text-muted">{notice.message}</div>
                {notice.variant === 'unavailable' && (
                  <button
                    type="button"
                    disabled={loadingKey != null}
                    onClick={() => void openBrowser()}
                    className="subtle-button mt-3 inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs"
                  >
                    {loadingKey === 'browse' ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Server className="h-3.5 w-3.5" />}
                    Browse available bundles
                  </button>
                )}
              </div>
              <button
                type="button"
                onClick={() => setNotice(null)}
                className="subtle-button inline-flex items-center justify-center rounded-lg p-2 text-xs"
                aria-label="Dismiss quick load notice"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
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

function bundleTypeLabel(value: QuickLoadKind): string {
  return {
    replay: 'Replay',
    monte_carlo: 'Monte Carlo',
    comparison: 'Comparison',
    calibration: 'Calibration',
    optimization: 'Optimisation',
    round2_scenarios: 'Round 2 scenario',
  }[value]
}

function unavailableNotice(kind?: QuickLoadKind): LoaderNotice {
  if (!kind) {
    return {
      variant: 'unavailable',
      title: 'No bundle is currently available',
      message: 'The local server did not return any dashboard bundles to open.',
    }
  }
  const label = bundleTypeLabel(kind)
  return {
    variant: 'unavailable',
    title: `${label} bundle unavailable`,
    message: `No ${label.toLowerCase()} bundle is currently available on the local server.`,
  }
}

function serverErrorNotice(kind?: QuickLoadKind): LoaderNotice {
  if (!kind) {
    return {
      variant: 'error',
      title: 'Local bundle server unavailable',
      message: 'The dashboard could not reach the local bundle server. Start it and try again.',
    }
  }
  const label = bundleTypeLabel(kind)
  return {
    variant: 'error',
    title: `${label} quick load failed`,
    message: `The dashboard could not check for the latest ${label.toLowerCase()} bundle because the local bundle server is unavailable.`,
  }
}
