import { clsx } from 'clsx'
import {
  Activity,
  BarChart2,
  Circle,
  Cpu,
  GitCompare,
  Leaf,
  Radar,
  Sliders,
  Target,
  X,
} from 'lucide-react'
import type React from 'react'
import { useStore } from '../store'
import type { TabId } from '../types'
import { fmtDate, truncateStr } from '../lib/format'

interface Tab {
  id: TabId
  label: string
  code: string
  icon: React.ReactNode
  group?: 'analysis' | 'product'
}

const TABS: Tab[] = [
  { id: 'overview', label: 'Overview', code: '00', icon: <Activity className="h-3.5 w-3.5" /> },
  { id: 'replay', label: 'Replay', code: '01', icon: <BarChart2 className="h-3.5 w-3.5" /> },
  { id: 'montecarlo', label: 'Monte Carlo', code: '02', icon: <Sliders className="h-3.5 w-3.5" /> },
  { id: 'calibration', label: 'Calibration', code: '03', icon: <Target className="h-3.5 w-3.5" /> },
  { id: 'compare', label: 'Comparison', code: '04', icon: <GitCompare className="h-3.5 w-3.5" /> },
  { id: 'optimize', label: 'Optimisation', code: '05', icon: <Cpu className="h-3.5 w-3.5" /> },
  { id: 'inspect', label: 'Inspect', code: '06', icon: <Radar className="h-3.5 w-3.5" /> },
  { id: 'osmium', label: 'Osmium', code: 'OS', icon: <Circle className="h-3.5 w-3.5" />, group: 'product' },
  { id: 'pepper', label: 'Pepper', code: 'PR', icon: <Leaf className="h-3.5 w-3.5" />, group: 'product' },
]

export function NavBar() {
  const {
    activeTab,
    setActiveTab,
    runs,
    activeRunId,
    compareRunId,
    setActiveRun,
    setCompareRun,
    removeRun,
  } = useStore()

  const activeRun = runs.find((run) => run.id === activeRunId) ?? runs[0]

  return (
    <nav className="fixed left-0 right-0 top-0 z-40 border-b border-border bg-bg/82 backdrop-blur-2xl">
      <div className="mx-auto flex max-w-[1680px] items-start gap-4 px-4 py-4 md:px-7">
        <div className="min-w-[188px] shrink-0">
          <div className="flex items-center gap-3">
            <div className="grid h-9 w-9 place-items-center rounded-lg border border-border-2 bg-accent/10 shadow-glow">
              <div className="h-2.5 w-2.5 rounded-sm bg-accent shadow-glow" />
            </div>
            <div>
              <div className="font-display text-sm font-extrabold uppercase tracking-[0.22em] text-txt">R1MCBT</div>
              <div className="hud-label mt-1 text-muted">Team platform v4</div>
            </div>
          </div>
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex min-h-10 flex-wrap items-center gap-2">
            {runs.length === 0 ? (
              <div className="hud-label text-muted">Awaiting dashboard bundle</div>
            ) : (
              runs.map((run) => {
                const isActive = run.id === activeRunId
                const isCompare = run.id === compareRunId
                return (
                  <button
                    key={run.id}
                    onClick={() => setActiveRun(run.id)}
                    className={clsx(
                      'group inline-flex max-w-[260px] items-center gap-2 rounded-lg border px-3 py-2 text-left transition-all duration-500 ease-observatory',
                      isActive
                        ? 'border-accent/40 bg-accent/12 text-accent shadow-glow'
                        : isCompare
                          ? 'border-accent-2/35 bg-accent-2/10 text-accent-2'
                          : 'border-border bg-white/[0.025] text-muted hover:border-border-2 hover:text-txt',
                    )}
                  >
                    <span className="hud-label rounded bg-white/[0.04] px-1.5 py-1">{isActive ? 'A' : isCompare ? 'B' : run.payload.type?.slice(0, 2) ?? '--'}</span>
                    <span className="min-w-0">
                      <span className="block truncate font-display text-xs font-semibold uppercase tracking-[0.08em]">
                        {truncateStr(run.name, 26)}
                      </span>
                      <span className="hud-label mt-0.5 block text-muted">{run.payload.type ?? 'unknown'}</span>
                    </span>
                    <X
                      className="h-3.5 w-3.5 opacity-35 transition-opacity hover:opacity-100"
                      onClick={(e) => {
                        e.stopPropagation()
                        removeRun(run.id)
                      }}
                    />
                  </button>
                )
              })
            )}

            {runs.length > 1 && (
              <div className="ml-auto flex items-center gap-2">
                <span className="hud-label text-muted">Compare</span>
                <select
                  value={compareRunId ?? ''}
                  onChange={(e) => setCompareRun(e.target.value || null)}
                  className="rounded-lg border border-border bg-surface-2 px-3 py-2 font-mono text-xs text-txt focus:border-accent/45 focus:outline-none"
                >
                  <option value="">None</option>
                  {runs.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          <div className="mt-3 flex items-center gap-1 overflow-x-auto border-t border-border pt-3">
            {TABS.map((tab) => {
              const isActive = activeTab === tab.id
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={clsx(
                    'group flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-xs transition-all duration-500 ease-observatory',
                    isActive
                      ? 'bg-accent/12 text-accent'
                      : 'text-muted hover:bg-white/[0.035] hover:text-txt',
                    tab.group === 'product' && !isActive && 'opacity-75',
                  )}
                >
                  <span className={clsx('hud-label', isActive ? 'text-accent-2' : 'text-steel')}>{tab.code}</span>
                  {tab.icon}
                  <span className="font-display font-semibold uppercase tracking-[0.08em]">{tab.label}</span>
                </button>
              )
            })}
          </div>
        </div>

        <div className="hidden w-[210px] shrink-0 text-right xl:block">
          <div className="hud-label text-muted">Active run</div>
          <div className="mt-2 truncate font-display text-xs font-semibold uppercase tracking-[0.08em] text-txt">
            {activeRun?.payload.meta?.runName ?? 'No run loaded'}
          </div>
          <div className="hud-label mt-2 text-accent-2">{fmtDate(activeRun?.payload.meta?.createdAt)}</div>
        </div>
      </div>
    </nav>
  )
}
