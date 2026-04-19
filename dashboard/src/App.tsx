import type React from 'react'
import { Database, FolderOpen, Radar, Server } from 'lucide-react'
import { useStore } from './store'
import { NavBar } from './components/NavBar'
import { FileDrop } from './components/FileDrop'
import { ServerRunLoader } from './components/ServerRunLoader'
import { Overview } from './views/Overview'
import { Replay } from './views/Replay'
import { MonteCarlo } from './views/MonteCarlo'
import { Calibration } from './views/Calibration'
import { Comparison } from './views/Comparison'
import { Optimization } from './views/Optimization'
import { OsmiumDive } from './views/OsmiumDive'
import { PepperDive } from './views/PepperDive'
import { Inspect } from './views/Inspect'
import type { TabId } from './types'

const VIEWS: Record<TabId, React.ComponentType> = {
  overview: Overview,
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
  const { runs, activeTab } = useStore()
  const View = VIEWS[activeTab] ?? Overview

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
    <div className="mx-auto grid min-h-[calc(100vh-132px)] w-full max-w-[1380px] items-center gap-8 px-4 pb-12 md:px-7 lg:grid-cols-[minmax(0,1fr)_minmax(360px,0.82fr)]">
      <section className="min-w-0">
        <div className="hud-label chapter-rule mb-5 text-accent">R1MCBT V4 / SIGNAL OBSERVATORY</div>
        <h1 className="font-display max-w-[780px] text-[3rem] font-extrabold uppercase leading-[0.9] tracking-normal text-txt md:text-[4.8rem]">
          <span className="block">Round 1</span>
          <span className="block">research</span>
          <em className="font-serif block font-light normal-case tracking-normal text-accent-2">command deck</em>
        </h1>
        <p className="mt-6 max-w-2xl text-xl leading-9 text-txt-soft">
          Load replay, Monte Carlo, calibration, comparison or optimisation bundles and inspect the run as a trading lab instrument.
        </p>

        <div className="mt-8 grid max-w-3xl grid-cols-1 gap-3 sm:grid-cols-3">
          {[
            { icon: <Radar className="h-4 w-4" />, label: 'Replay', value: 'Path diagnostics' },
            { icon: <Database className="h-4 w-4" />, label: 'Monte Carlo', value: 'Robustness bands' },
            { icon: <Server className="h-4 w-4" />, label: 'Calibration', value: 'Live mismatch' },
          ].map((item) => (
            <div key={item.label} className="glass-panel rounded-lg px-4 py-4">
              <div className="mb-3 text-accent">{item.icon}</div>
              <div className="hud-label text-muted">{item.label}</div>
              <div className="font-display mt-2 text-sm font-semibold uppercase tracking-[0.08em] text-txt">{item.value}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="glass-panel rounded-lg p-5">
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
          python -m r1bt replay / monte-carlo / calibrate / optimize
        </div>
      </section>
    </div>
  )
}
