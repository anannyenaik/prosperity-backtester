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
  const isLanding = runs.length === 0
  const viewportOffset = 'calc(var(--dashboard-nav-height, 156px) + 16px)'
  const mainStyle = {
    paddingTop: viewportOffset,
    minHeight: 'calc(100dvh - (var(--dashboard-nav-height, 156px) + 16px))',
  }

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
      <main className="relative z-10 flex flex-col" style={mainStyle}>
        {isLanding ? (
          <LandingScreen />
        ) : (
          <div className="mx-auto w-full max-w-[1680px] px-4 pb-12 pt-1 md:px-7 md:pt-2">
            <View />
          </div>
        )}
      </main>
    </div>
  )
}

const CAPABILITY_NODES = [
  { icon: <BarChart2 className="h-3.5 w-3.5" />, label: 'Replay', value: 'Path diagnostics' },
  { icon: <Sliders className="h-3.5 w-3.5" />, label: 'Monte Carlo', value: 'Tail risk ranking' },
  { icon: <GitCompare className="h-3.5 w-3.5" />, label: 'Comparison', value: 'Multi-trader' },
  { icon: <Cpu className="h-3.5 w-3.5" />, label: 'Optimisation', value: 'Variant ranking' },
]

function LandingScreen() {
  return (
    <div
      className="mx-auto grid w-full max-w-[1360px] flex-1 items-start gap-4 px-4 pb-3 pt-0 md:px-7 md:pb-4 md:pt-1 lg:grid-cols-[minmax(0,1fr)_minmax(340px,500px)] lg:gap-6 lg:py-2.5 2xl:items-center xl:grid-cols-[minmax(0,1fr)_minmax(360px,520px)] xl:gap-7 xl:py-3.5"
    >
      <section className="flex min-w-0 flex-col justify-center lg:pr-2">
        <div className="hud-label chapter-rule mb-3 text-accent">IMC PROSPERITY / RESEARCH PLATFORM</div>
        <h1 className="font-display max-w-[700px] text-[2.4rem] font-extrabold uppercase leading-[0.9] tracking-normal text-txt md:text-[3.15rem] lg:text-[2.85rem] xl:text-[3.3rem] 2xl:text-[3.55rem]">
          <span className="block">Strategy</span>
          <span className="block">research</span>
          <em className="font-serif mt-1 block text-[0.72em] font-light normal-case leading-[1.05] tracking-normal text-accent-2">decision workspace</em>
        </h1>
        <p className="mt-3.5 max-w-[600px] text-[0.98rem] leading-7 text-txt-soft md:text-base md:leading-7">
          Load replay, Monte Carlo, calibration, comparison, optimisation or scenario bundles to inspect run evidence and drive research decisions.
        </p>

        <div className="motif-strip mt-4 grid max-w-[720px] grid-cols-2 gap-2.5 sm:grid-cols-4">
          {CAPABILITY_NODES.map((item) => (
            <div key={item.label} className="motif-card edge-traced edge-traced--soft rounded-lg px-3 py-3">
              <div className="grid h-9 w-9 place-items-center rounded-lg border border-accent/20 bg-accent/10 text-accent shadow-[0_8px_18px_rgba(0,0,0,0.22)]">
                {item.icon}
              </div>
              <div className="font-display mt-3 text-[0.8rem] font-semibold uppercase tracking-[0.08em] text-txt">
                {item.label}
              </div>
              <div className="mt-1 text-[12px] leading-5 text-muted">{item.value}</div>
            </div>
          ))}
        </div>

        <div className="hud-label mt-4 max-w-[720px] text-muted">
          <span className="text-accent-2">~</span>&nbsp;python -m prosperity_backtester replay &middot; monte-carlo &middot; compare &middot; round2-scenarios
        </div>
      </section>

      <section className="glass-panel edge-traced edge-traced--slow self-start flex w-full min-w-0 flex-col justify-between overflow-visible rounded-lg p-3 md:p-3.5 lg:max-w-[500px] lg:justify-self-end xl:max-w-[520px]">
        <div className="mb-2.5 flex items-start justify-between gap-2.5">
          <div>
            <div className="hud-label text-accent-2">Bundle intake</div>
            <h2 className="font-display mt-0.5 text-[0.98rem] font-bold uppercase tracking-[0.08em]">Load a bundle</h2>
            <div className="mt-1 max-w-[26rem] text-[11px] leading-[1.35] text-muted">
              Drop a local dashboard.json file or open one from the local bundle server.
            </div>
          </div>
          <FolderOpen className="h-5 w-5 text-accent" />
        </div>
        <FileDrop />
        <ServerRunLoader />
      </section>
    </div>
  )
}
