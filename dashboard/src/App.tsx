import React, { startTransition, useEffect } from 'react'
import { BarChart2, Cpu, FolderOpen, GitCompare, Sliders } from 'lucide-react'
import { useStore, type ServerRunMeta } from './store'
import { NavBar } from './components/NavBar'
import { FileDrop } from './components/FileDrop'
import { ServerRunLoader } from './components/ServerRunLoader'
import { Cursor } from './components/Cursor'
import { Overview } from './views/Overview'
import { AlphaLab } from './views/AlphaLab'
import { Round2 } from './views/Round2'
import { Replay } from './views/Replay'
import { MonteCarlo } from './views/MonteCarlo'
import { Calibration } from './views/Calibration'
import { Comparison } from './views/Comparison'
import { Optimization } from './views/Optimization'
import { OsmiumDive } from './views/OsmiumDive'
import { PepperDive } from './views/PepperDive'
import { Inspect } from './views/Inspect'
import type { DashboardPayload, TabId } from './types'
import { clearBootstrapQueryParams, normaliseBootstrapRunType, readBootstrapRequest } from './lib/bootstrap'

const VIEWS: Record<TabId, React.ComponentType> = {
  overview: Overview,
  alpha: AlphaLab,
  round2: Round2,
  replay: Replay,
  montecarlo: MonteCarlo,
  calibration: Calibration,
  compare: Comparison,
  optimize: Optimization,
  inspect: Inspect,
  osmium: OsmiumDive,
  pepper: PepperDive,
}

export function App() {
  const { runs, activeTab, loadRun, setServerRuns } = useStore()
  const View = VIEWS[activeTab] ?? Overview

  useEffect(() => {
    if (typeof window === 'undefined') return

    const bootstrapRequest = readBootstrapRequest(window.location.search)
    if (runs.length > 0) {
      if (bootstrapRequest) {
        clearBootstrapQueryParams()
      }
      return
    }
    if (!bootstrapRequest) return

    let cancelled = false
    startTransition(() => {
      void (async () => {
        try {
          const runsRes = await fetch('/api/runs')
          if (!runsRes.ok) return
          const serverRuns = (await runsRes.json()) as ServerRunMeta[]
          if (cancelled) return
          setServerRuns(serverRuns)
          const targetRun = bootstrapRequest.requestedRun
            ? serverRuns.find((run) => run.path === bootstrapRequest.requestedRun)
            : serverRuns.find((run) => normaliseBootstrapRunType(run.type) === bootstrapRequest.latestType) ?? serverRuns[0]
          if (!targetRun) return
          const runRes = await fetch(`/api/run/${encodeURIComponent(targetRun.path)}`)
          if (!runRes.ok) return
          const payload = (await runRes.json()) as DashboardPayload
          if (!cancelled) {
            clearBootstrapQueryParams()
            loadRun(payload, targetRun.name)
          }
        } catch {
          // Ignore server bootstrap failures and leave the manual loader available.
        }
      })()
    })

    return () => {
      cancelled = true
    }
  }, [loadRun, runs.length, setServerRuns])

  return (
    <div className="min-h-screen text-txt">
      <Cursor />
      <div className="app-atmosphere" aria-hidden="true" />
      <NavBar />
      <main className="relative z-10 min-h-screen pt-[116px]">
        {runs.length === 0 ? (
          <LandingScreen />
        ) : (
          <div className="mx-auto w-full max-w-[1680px] px-4 pb-12 md:px-7">
            <View />
          </div>
        )}
      </main>
    </div>
  )
}

const CAPABILITY_NODES = [
  { icon: <BarChart2 className="h-3.5 w-3.5" />, code: '01', label: 'Replay', value: 'Path diagnostics' },
  { icon: <Sliders className="h-3.5 w-3.5" />, code: '02', label: 'Monte Carlo', value: 'Tail risk ranking' },
  { icon: <GitCompare className="h-3.5 w-3.5" />, code: '04', label: 'Comparison', value: 'Multi-trader' },
  { icon: <Cpu className="h-3.5 w-3.5" />, code: '05', label: 'Optimisation', value: 'Variant ranking' },
]

function LandingScreen() {
  return (
    <div className="mx-auto grid w-full max-w-[1380px] items-center gap-7 px-4 pb-8 pt-5 md:px-7 md:pb-9 md:pt-6 lg:min-h-[calc(100vh-116px)] lg:grid-cols-[minmax(0,0.98fr)_minmax(380px,0.78fr)] lg:items-stretch lg:gap-10 xl:gap-12">
      <section className="flex min-w-0 flex-col justify-center lg:pr-2">
        <div className="hud-label chapter-rule mb-3 text-accent">IMC PROSPERITY / RESEARCH PLATFORM</div>
        <h1 className="font-display max-w-[720px] text-[2.6rem] font-extrabold uppercase leading-[0.9] tracking-normal text-txt md:text-[3.45rem] lg:text-[3rem] xl:text-[3.6rem] 2xl:text-[3.8rem]">
          <span className="block">Strategy</span>
          <span className="block">research</span>
          <em className="font-serif mt-1 block text-[0.72em] font-light normal-case leading-[1.05] tracking-normal text-accent-2">decision workspace</em>
        </h1>
        <p className="mt-5 max-w-[620px] text-base leading-7 text-txt-soft md:text-lg md:leading-8">
          Load replay, Monte Carlo, calibration, comparison, optimisation or scenario bundles to inspect run evidence and drive research decisions.
        </p>

        <div className="motif-strip mt-6 grid max-w-[720px] grid-cols-2 gap-2.5 sm:grid-cols-4">
          {CAPABILITY_NODES.map((item) => (
            <div key={item.label} className="motif-card rounded-lg px-3 py-3">
              <div className="flex items-center justify-between">
                <span className="text-accent">{item.icon}</span>
                <span className="hud-label text-steel">{item.code}</span>
              </div>
              <div className="font-display mt-3 text-[0.82rem] font-semibold uppercase tracking-[0.1em] text-txt">
                {item.label}
              </div>
              <div className="hud-label mt-1 text-muted">{item.value}</div>
            </div>
          ))}
        </div>

        <div className="hud-label mt-6 max-w-[720px] text-muted">
          <span className="text-accent-2">~</span>&nbsp;python -m prosperity_backtester replay &middot; monte-carlo &middot; compare &middot; round2-scenarios
        </div>
      </section>

      <section className="glass-panel edge-traced edge-traced--slow flex w-full flex-col justify-between overflow-visible rounded-lg p-4 md:p-5 lg:max-w-[590px] lg:justify-self-end lg:self-stretch">
        <div className="mb-3 flex items-start justify-between gap-4 border-b border-border pb-3">
          <div>
            <div className="hud-label text-accent-2">Bundle intake</div>
            <h2 className="font-display mt-1.5 text-lg font-bold uppercase tracking-[0.08em]">Load a run</h2>
          </div>
          <FolderOpen className="h-5 w-5 text-accent" />
        </div>
        <FileDrop />
        <ServerRunLoader />
      </section>
    </div>
  )
}
