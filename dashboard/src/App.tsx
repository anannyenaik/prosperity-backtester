import React, { startTransition, useEffect } from 'react'
import { Database, FolderOpen, Radar, Server } from 'lucide-react'
import { useStore, type ServerRunMeta } from './store'
import { NavBar } from './components/NavBar'
import { FileDrop } from './components/FileDrop'
import { ServerRunLoader } from './components/ServerRunLoader'
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
    const params = new URLSearchParams(window.location.search)
    const requestedRun = params.get('run')
    const loadLatest = params.get('latest') === '1'
    if (runs.length > 0 || (!requestedRun && !loadLatest)) return

    let cancelled = false
    startTransition(() => {
      void (async () => {
        try {
          const runsRes = await fetch('/api/runs')
          if (!runsRes.ok) return
          const serverRuns = (await runsRes.json()) as ServerRunMeta[]
          if (cancelled) return
          setServerRuns(serverRuns)
          const targetRun = requestedRun
            ? serverRuns.find((run) => run.path === requestedRun)
            : serverRuns[0]
          if (!targetRun) return
          const runRes = await fetch(`/api/run/${encodeURIComponent(targetRun.path)}`)
          if (!runRes.ok) return
          const payload = (await runRes.json()) as DashboardPayload
          if (!cancelled) {
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
      <div className="app-atmosphere" aria-hidden="true" />
      <NavBar />
      <main className="relative z-10 min-h-screen pt-[132px]">
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

function LandingScreen() {
  return (
    <div className="mx-auto grid min-h-[calc(100vh-132px)] w-full max-w-[1380px] items-center gap-8 px-4 py-10 md:px-7 md:py-12 lg:grid-cols-[minmax(0,0.98fr)_minmax(380px,0.78fr)] lg:items-stretch lg:gap-12 xl:gap-14">
      <section className="flex min-w-0 flex-col justify-center lg:pr-4">
        <div className="hud-label chapter-rule mb-4 text-accent">PROSPERITY RESEARCH / ROUND 2</div>
        <h1 className="font-display max-w-[760px] text-[2.9rem] font-extrabold uppercase leading-[0.88] tracking-normal text-txt md:text-[4.15rem] lg:text-[3.55rem] xl:text-[4.4rem] 2xl:text-[4.5rem]">
          <span className="block">Round 2</span>
          <span className="block">research</span>
          <em className="font-serif block text-[0.74em] font-light normal-case leading-none tracking-normal text-accent-2">decision workspace</em>
        </h1>
        <p className="mt-7 max-w-[640px] text-lg leading-8 text-txt-soft md:text-xl md:leading-9">
          Load replay, Monte Carlo, calibration, comparison, optimisation or MAF scenario bundles and inspect the run evidence.
        </p>

        <div className="mt-9 grid max-w-[700px] grid-cols-1 gap-3 sm:grid-cols-3">
          {[
            { icon: <Radar className="h-4 w-4" />, label: 'Replay', value: 'Path diagnostics' },
            { icon: <Database className="h-4 w-4" />, label: 'MAF', value: 'Access scenarios' },
            { icon: <Server className="h-4 w-4" />, label: 'Monte Carlo', value: 'Robust ranking' },
          ].map((item) => (
            <div key={item.label} className="glass-panel rounded-lg px-4 py-4">
              <div className="mb-3 text-accent">{item.icon}</div>
              <div className="hud-label text-muted">{item.label}</div>
              <div className="font-display mt-2 text-sm font-semibold uppercase tracking-[0.08em] text-txt">{item.value}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="glass-panel flex w-full flex-col justify-between rounded-lg p-5 lg:max-w-[590px] lg:justify-self-end lg:self-stretch">
        <div className="mb-4 flex items-start justify-between gap-4 border-b border-border pb-4">
          <div>
            <div className="hud-label text-accent-2">Bundle intake</div>
            <h2 className="font-display mt-2 text-xl font-bold uppercase tracking-[0.08em]">Load a run</h2>
          </div>
          <FolderOpen className="h-5 w-5 text-accent" />
        </div>
        <FileDrop />
        <ServerRunLoader />
        <div className="hud-label mt-5 border-t border-border pt-4 text-muted">
          python -m prosperity_backtester replay / monte-carlo / compare / round2-scenarios
        </div>
      </section>
    </div>
  )
}
