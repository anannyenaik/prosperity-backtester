import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
  type RefObject,
} from 'react'
import {
  AlertTriangle,
  ArrowUpRight,
  Boxes,
  FlaskConical,
  GitCompare,
  History,
  RefreshCw,
  Search,
  Server,
  Sliders,
  Target,
  X,
} from 'lucide-react'
import { clsx } from 'clsx'
import { useStore, type ServerRunMeta } from '../store'
import type { DashboardPayload } from '../types'
import { fmtBytes, fmtDate, fmtNum } from '../lib/format'
import { computeFloatingLayerLayout } from '../lib/floatingLayer'

type RunFilter = 'all' | 'replay' | 'monte_carlo' | 'comparison' | 'calibration' | 'optimization' | 'round2_scenarios'
type QuickLoadKind = Exclude<RunFilter, 'all'>

interface QuickLoadButton {
  type: QuickLoadKind
  label: string
}

interface BrowserState {
  open: boolean
  status: 'list' | 'empty' | 'error' | 'load_error'
  message: string | null
}

interface LoaderNotice {
  variant: 'unavailable' | 'error'
  title: string
  message: string
}

interface LoaderActionButtonProps {
  label: string
  caption?: string
  icon: ReactNode
  onClick: () => void
  disabled: boolean
  tone?: 'primary' | 'secondary'
  indicator?: ReactNode
}

interface QuickLoadChipProps {
  label: string
  caption: string
  icon: ReactNode
  onClick: () => void
  disabled: boolean
  loading: boolean
}

const TYPE_BUTTONS: Array<QuickLoadButton & { caption: string; icon: ReactNode }> = [
  { type: 'replay', label: 'Replay', caption: 'Historical', icon: <History className="h-3.5 w-3.5" /> },
  { type: 'monte_carlo', label: 'Monte Carlo', caption: 'Synthetic paths', icon: <Sliders className="h-3.5 w-3.5" /> },
  { type: 'calibration', label: 'Calibration', caption: 'Model fit', icon: <Target className="h-3.5 w-3.5" /> },
  { type: 'comparison', label: 'Comparison', caption: 'Multi-trader', icon: <GitCompare className="h-3.5 w-3.5" /> },
  { type: 'optimization', label: 'Optimise', caption: 'Variant rank', icon: <FlaskConical className="h-3.5 w-3.5" /> },
  { type: 'round2_scenarios', label: 'Round 2', caption: 'Scenarios', icon: <Boxes className="h-3.5 w-3.5" /> },
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

const DEFAULT_LAYER_STYLE: CSSProperties = {
  left: '16px',
  top: '16px',
  width: 'min(40rem, calc(100vw - 2rem))',
  maxHeight: 'calc(100vh - 2rem)',
}

const useIsomorphicLayoutEffect = typeof window === 'undefined' ? useEffect : useLayoutEffect

export function ServerRunLoader() {
  const { serverRuns, setServerRuns, loadRun } = useStore()
  const rootRef = useRef<HTMLDivElement>(null)
  const [loadingKey, setLoadingKey] = useState<string | null>(null)
  const [browserState, setBrowserState] = useState<BrowserState>({
    open: false,
    status: 'list',
    message: null,
  })
  const [notice, setNotice] = useState<LoaderNotice | null>(null)
  const [filter, setFilter] = useState<RunFilter>('all')

  const layerStyle = useAnchoredLayerStyle(rootRef, browserState.open || notice != null)

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
      if (browserState.open) {
        setNotice(null)
        setBrowserState({
          open: true,
          status: 'load_error',
          message: `The server could not open ${run.name}. Try again or choose another bundle.`,
        })
        return
      }
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
      setNotice(null)
      setFilter('all')
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

  useEffect(() => {
    if (!availableFilters.includes(filter)) {
      setFilter('all')
    }
  }, [availableFilters, filter])

  const loading = loadingKey != null

  return (
    <div ref={rootRef} className="relative mt-1.5 min-w-0">
      <div className="quickload-panel edge-traced edge-traced--panel rounded-[12px] p-2 md:p-2.5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="hud-label text-accent-2">Bundle server</div>
            <div className="mt-0.5 font-display text-[0.8rem] font-semibold uppercase tracking-[0.08em] text-txt">
              Quick load
            </div>
            <div className="mt-1 max-w-[26rem] text-[11px] leading-[1.35] text-muted">
              Open the latest run immediately or browse every served bundle.
            </div>
          </div>
          <div className="quickload-status quickload-status--pill hud-label">
            <span className={clsx('quickload-status__dot', loading && 'is-loading')} aria-hidden="true" />
            {loading ? 'Loading' : 'Ready'}
          </div>
        </div>

        <div className="quickload-primary mt-1.5 grid gap-1 sm:grid-cols-2">
          <LoaderActionButton
            label="Open Latest Bundle"
            icon={loadingKey === 'latest' ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Server className="h-4 w-4" />}
            onClick={() => void loadLatestFromServer()}
            disabled={loadingKey != null}
            tone="primary"
            indicator={<ArrowUpRight className="h-3.5 w-3.5" />}
          />
          <LoaderActionButton
            label={browserState.open ? 'Hide Local Browser' : 'Browse Local Server'}
            icon={
              loadingKey === 'browse' ? (
                <RefreshCw className="h-4 w-4 animate-spin" />
              ) : browserState.open ? (
                <X className="h-4 w-4" />
              ) : (
                <Search className="h-4 w-4" />
              )
            }
            onClick={() => {
              if (browserState.open) {
                setBrowserState((current) => ({ ...current, open: false }))
                return
              }
              void openBrowser()
            }}
            disabled={loadingKey != null}
            indicator={<ArrowUpRight className="h-3.5 w-3.5" />}
          />
        </div>

        <div className="quickload-divider mt-2 flex items-center gap-1.5">
          <span className="hud-label text-muted">Shortcuts</span>
          <span className="quickload-divider__rule" aria-hidden="true" />
        </div>

        <div className="quickload-chips mt-1.5 grid grid-cols-2 gap-1 md:grid-cols-3">
          {TYPE_BUTTONS.map(({ type, label, caption, icon }) => (
            <QuickLoadChip
              key={type}
              label={label}
              caption={caption}
              icon={icon}
              onClick={() => void loadLatestFromServer(type)}
              disabled={loadingKey != null}
              loading={loadingKey === `latest:${type}`}
            />
          ))}
        </div>
      </div>

      {browserState.open && (
        <>
          <button
            type="button"
            aria-label="Close bundle browser"
            onClick={() => setBrowserState((current) => ({ ...current, open: false }))}
            className="fixed inset-0 z-40 cursor-default bg-bg/12 backdrop-blur-[1px]"
          />
          <div
            data-loader-surface="browser"
            role="dialog"
            aria-modal="true"
            aria-label="Bundle browser"
            className="loader-surface fixed z-50"
            style={layerStyle}
          >
            <div className="loader-surface-body flex min-h-0 flex-col">
              <div className="flex items-start justify-between gap-4 border-b border-border bg-white/[0.03] px-4 py-4">
                <div>
                  <div className="hud-label text-accent-2">Bundle browser</div>
                  <div className="mt-2 text-sm text-txt-soft">
                    {browserState.status === 'list'
                      ? `Available bundles (${visibleRuns.length} shown of ${serverRuns.length})`
                      : browserState.status === 'empty'
                        ? 'No dashboard bundles found'
                        : browserState.status === 'load_error'
                          ? 'Bundle load failed'
                          : 'Local bundle server unavailable'}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setBrowserState((current) => ({ ...current, open: false }))}
                  data-cursor="close"
                  className="subtle-button inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs"
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
                <div className="px-4 py-5 text-sm leading-6 text-txt-soft">
                  No dashboard bundles were found under the served directory.
                </div>
              )}

              {(browserState.status === 'error' || browserState.status === 'load_error') && (
                <div className="px-4 py-5 text-sm leading-6 text-txt-soft">
                  {browserState.message}
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {notice && (
        <div
          data-loader-surface="notice"
          role="status"
          aria-live="polite"
          className="loader-surface fixed z-50"
          style={layerStyle}
        >
          <div className="loader-surface-body px-5 py-4">
            <div className="flex items-start gap-4">
              <div
                className={clsx(
                  'mt-0.5 grid h-11 w-11 shrink-0 place-items-center rounded-full border shadow-[0_0_24px_rgba(0,0,0,0.18)]',
                  notice.variant === 'unavailable'
                    ? 'border-warn/35 bg-warn/10 text-warn'
                    : 'border-bad/35 bg-bad/10 text-bad',
                )}
              >
                <AlertTriangle className="h-4 w-4" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="hud-label text-accent-2">
                  {notice.variant === 'unavailable' ? 'Quick load unavailable' : 'Quick load error'}
                </div>
                <div className="mt-2 font-display text-base font-semibold uppercase tracking-[0.08em] text-txt">
                  {notice.title}
                </div>
                <div className="mt-2 max-w-[34rem] text-sm leading-6 text-txt-soft">{notice.message}</div>
                {notice.variant === 'unavailable' && (
                  <button
                    type="button"
                    disabled={loadingKey != null}
                    onClick={() => void openBrowser()}
                    className="signal-button mt-4 inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs"
                  >
                    {loadingKey === 'browse' ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Server className="h-3.5 w-3.5" />}
                    Browse available bundles
                  </button>
                )}
              </div>
              <button
                type="button"
                onClick={() => setNotice(null)}
                data-cursor="close"
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

function LoaderActionButton({
  label,
  caption,
  icon,
  onClick,
  disabled,
  tone = 'secondary',
  indicator,
}: LoaderActionButtonProps) {
  const compact = !caption
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-interactive="true"
      className={clsx(
        'qa-button group loader-action rounded-[11px] text-left',
        compact && 'qa-button--compact',
        tone === 'primary' ? 'qa-button--primary' : 'qa-button--secondary',
      )}
    >
      <span className="qa-button__sheen" aria-hidden="true" />
      <span className="qa-button__edge" aria-hidden="true" />
      <span className="qa-button__content">
        <span className="qa-button__icon" aria-hidden="true">
          {icon}
        </span>
        <span className={clsx('qa-button__body', compact && 'qa-button__body--compact')}>
          <span className="qa-button__label font-display">{label}</span>
          {caption ? <span className="qa-button__caption hud-label">{caption}</span> : null}
        </span>
        <span className="qa-button__meta" aria-hidden="true">
          {indicator && <span className="qa-button__indicator">{indicator}</span>}
        </span>
      </span>
    </button>
  )
}

function QuickLoadChip({ label, caption, icon, onClick, disabled, loading }: QuickLoadChipProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-interactive="true"
      aria-label={`Load latest ${label} bundle`}
      className={clsx('qa-chip group', loading && 'is-loading')}
    >
      <span className="qa-chip__glow" aria-hidden="true" />
      <span className="qa-chip__content">
        <span className="qa-chip__top">
          <span className="qa-chip__icon">
            {loading ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : icon}
          </span>
        </span>
        <span className="qa-chip__label font-display">{label}</span>
        <span className="qa-chip__caption hud-label">{caption}</span>
      </span>
    </button>
  )
}

function useAnchoredLayerStyle(anchorRef: RefObject<HTMLElement>, active: boolean): CSSProperties {
  const [style, setStyle] = useState<CSSProperties>(DEFAULT_LAYER_STYLE)

  useIsomorphicLayoutEffect(() => {
    if (!active || typeof window === 'undefined') return

    let frameId = 0
    const update = () => {
      frameId = 0
      const rect = anchorRef.current?.getBoundingClientRect()
      if (!rect) return

      const layout = computeFloatingLayerLayout(
        {
          left: rect.left,
          top: rect.top,
          width: rect.width,
          height: rect.height,
        },
        {
          width: window.innerWidth,
          height: window.innerHeight,
        },
      )

      setStyle({
        left: `${layout.left}px`,
        top: `${layout.top}px`,
        width: `${layout.width}px`,
        maxHeight: `${layout.maxHeight}px`,
      })
    }

    const scheduleUpdate = () => {
      if (frameId !== 0) return
      frameId = window.requestAnimationFrame(update)
    }

    scheduleUpdate()
    window.addEventListener('resize', scheduleUpdate)
    window.addEventListener('scroll', scheduleUpdate, true)

    const anchor = anchorRef.current
    const observer =
      typeof ResizeObserver !== 'undefined' && anchor
        ? new ResizeObserver(scheduleUpdate)
        : null
    if (observer && anchor) {
      observer.observe(anchor)
    }

    return () => {
      if (frameId !== 0) {
        window.cancelAnimationFrame(frameId)
      }
      window.removeEventListener('resize', scheduleUpdate)
      window.removeEventListener('scroll', scheduleUpdate, true)
      observer?.disconnect()
    }
  }, [active, anchorRef])

  return style
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
    message: `No ${label.toLowerCase()} bundle is currently available on the local server. Browse another bundle or generate a fresh ${label.toLowerCase()} run.`,
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
