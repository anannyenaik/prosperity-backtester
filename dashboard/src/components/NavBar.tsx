import { clsx } from 'clsx'
import {
  Activity,
  ArrowUpRight,
  BarChart2,
  Circle,
  Cpu,
  FlaskConical,
  GitCompare,
  Leaf,
  Radar,
  Sliders,
  Target,
  X,
} from 'lucide-react'
import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useStore } from '../store'
import type { TabId } from '../types'
import { fmtDate, truncateStr } from '../lib/format'
import { clearBootstrapQueryParams } from '../lib/bootstrap'
import { getTabAvailability, interpretBundle } from '../lib/bundles'
import { BrandMark } from './BrandMark'

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
  { id: 'alpha', label: 'Alpha Lab', code: 'AL', icon: <FlaskConical className="h-3.5 w-3.5" /> },
  { id: 'round2', label: 'Round 2', code: 'R2', icon: <Target className="h-3.5 w-3.5" /> },
]

const useIsomorphicLayoutEffect = typeof window === 'undefined' ? useEffect : useLayoutEffect

interface NavScrollState {
  dragging: boolean
  thumbOffset: number
  thumbWidth: number
  visible: boolean
}

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
  const navRef = useRef<HTMLElement>(null)
  const railRef = useRef<HTMLDivElement>(null)
  const railTrackRef = useRef<HTMLDivElement>(null)
  const railThumbRef = useRef<HTMLDivElement>(null)
  const railDragRef = useRef<{ startScrollLeft: number; startX: number } | null>(null)
  const [navScrollState, setNavScrollState] = useState<NavScrollState>({
    dragging: false,
    thumbOffset: 0,
    thumbWidth: 0,
    visible: false,
  })

  const activeRun = runs.find((run) => run.id === activeRunId) ?? runs[0]
  const compareRun = runs.find((run) => run.id === compareRunId) ?? null
  const activeBundle = activeRun ? interpretBundle(activeRun.payload) : null

  useIsomorphicLayoutEffect(() => {
    if (typeof window === 'undefined') return
    if (typeof document === 'undefined') return

    const root = document.documentElement
    let frameId = 0

    const updateHeight = () => {
      frameId = 0
      const height = navRef.current?.getBoundingClientRect().height
      if (!height) return
      root.style.setProperty('--dashboard-nav-height', `${Math.ceil(height)}px`)
    }

    const scheduleUpdate = () => {
      if (frameId !== 0) return
      frameId = window.requestAnimationFrame(updateHeight)
    }

    scheduleUpdate()
    window.addEventListener('resize', scheduleUpdate)

    const nav = navRef.current
    const observer =
      typeof ResizeObserver !== 'undefined' && nav
        ? new ResizeObserver(scheduleUpdate)
        : null

    if (observer && nav) {
      observer.observe(nav)
    }

    return () => {
      if (frameId !== 0) {
        window.cancelAnimationFrame(frameId)
      }
      window.removeEventListener('resize', scheduleUpdate)
      observer?.disconnect()
      root.style.removeProperty('--dashboard-nav-height')
    }
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return

    const rail = railRef.current
    if (!rail) return

    let frameId = 0

    const updateScrollState = () => {
      frameId = 0
      const clientWidth = rail.clientWidth
      const scrollWidth = rail.scrollWidth
      const maxScrollLeft = Math.max(scrollWidth - clientWidth, 0)

      if (maxScrollLeft <= 1 || clientWidth <= 0) {
        setNavScrollState((current) => (
          current.visible || current.thumbOffset !== 0 || current.thumbWidth !== 0
            ? { ...current, thumbOffset: 0, thumbWidth: 0, visible: false }
            : current
        ))
        return
      }

      const thumbWidth = clamp(clientWidth * (clientWidth / scrollWidth), 56, clientWidth)
      const maxThumbOffset = Math.max(clientWidth - thumbWidth, 0)
      const thumbOffset = maxScrollLeft > 0 ? (rail.scrollLeft / maxScrollLeft) * maxThumbOffset : 0

      setNavScrollState((current) => (
        current.visible === true &&
        Math.abs(current.thumbWidth - thumbWidth) < 0.5 &&
        Math.abs(current.thumbOffset - thumbOffset) < 0.5
          ? current
          : { ...current, thumbOffset, thumbWidth, visible: true }
      ))
    }

    const scheduleUpdate = () => {
      if (frameId !== 0) return
      frameId = window.requestAnimationFrame(updateScrollState)
    }

    scheduleUpdate()
    rail.addEventListener('scroll', scheduleUpdate, { passive: true })
    window.addEventListener('resize', scheduleUpdate)

    const observer =
      typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver(scheduleUpdate)
        : null

    observer?.observe(rail)
    if (navRef.current) {
      observer?.observe(navRef.current)
    }

    return () => {
      if (frameId !== 0) {
        window.cancelAnimationFrame(frameId)
      }
      rail.removeEventListener('scroll', scheduleUpdate)
      window.removeEventListener('resize', scheduleUpdate)
      observer?.disconnect()
    }
  }, [activeRunId, compareRunId, runs.length])

  useEffect(() => {
    if (typeof window === 'undefined') return

    const onPointerMove = (event: PointerEvent) => {
      const drag = railDragRef.current
      const rail = railRef.current
      const track = railTrackRef.current

      if (!drag || !rail || !track) return

      const maxScrollLeft = Math.max(rail.scrollWidth - rail.clientWidth, 0)
      const maxThumbOffset = Math.max(track.clientWidth - navScrollState.thumbWidth, 1)
      if (maxScrollLeft <= 0) return

      const deltaRatio = (event.clientX - drag.startX) / maxThumbOffset
      rail.scrollLeft = clamp(drag.startScrollLeft + deltaRatio * maxScrollLeft, 0, maxScrollLeft)
    }

    const stopDragging = () => {
      if (!railDragRef.current) return
      railDragRef.current = null
      setNavScrollState((current) => (current.dragging ? { ...current, dragging: false } : current))
    }

    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', stopDragging)
    window.addEventListener('pointercancel', stopDragging)
    window.addEventListener('blur', stopDragging)

    return () => {
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', stopDragging)
      window.removeEventListener('pointercancel', stopDragging)
      window.removeEventListener('blur', stopDragging)
    }
  }, [navScrollState.thumbWidth])

  const scrollRailToPointer = (clientX: number) => {
    const rail = railRef.current
    const track = railTrackRef.current

    if (!rail || !track) return

    const maxScrollLeft = Math.max(rail.scrollWidth - rail.clientWidth, 0)
    if (maxScrollLeft <= 0) return

    const rect = track.getBoundingClientRect()
    const maxThumbOffset = Math.max(rect.width - navScrollState.thumbWidth, 1)
    const targetOffset = clamp(clientX - rect.left - navScrollState.thumbWidth / 2, 0, maxThumbOffset)
    rail.scrollLeft = (targetOffset / maxThumbOffset) * maxScrollLeft
  }

  const onRailTrackPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!navScrollState.visible) return
    if ((event.target as Element | null)?.closest('.nav-scrollbar__thumb')) return
    event.preventDefault()
    scrollRailToPointer(event.clientX)
  }

  const onRailThumbPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!navScrollState.visible) return

    const rail = railRef.current
    const thumb = railThumbRef.current

    if (!rail || !thumb) return

    event.preventDefault()
    event.stopPropagation()
    railDragRef.current = {
      startScrollLeft: rail.scrollLeft,
      startX: event.clientX,
    }
    thumb.setPointerCapture?.(event.pointerId)
    setNavScrollState((current) => (current.dragging ? current : { ...current, dragging: true }))
  }

  return (
    <nav
      ref={navRef}
      className="fixed left-0 right-0 top-0 z-40 border-b border-border bg-bg/82 backdrop-blur-2xl"
    >
      <div className="mx-auto flex max-w-[1680px] items-start gap-4 px-4 py-3 md:px-7">
        <div className="min-w-[196px] shrink-0">
          <div className="flex items-center gap-3">
            <BrandMark size={40} />
            <div>
              <div className="font-display text-sm font-extrabold uppercase tracking-[0.22em] text-txt">Prosperity Lab</div>
              <div className="hud-label mt-1 text-muted">Research platform</div>
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
                  <div
                    key={run.id}
                    className={clsx(
                      'group flex max-w-[280px] items-center gap-1 rounded-lg border pr-1 transition-all duration-500 ease-observatory',
                      isActive
                        ? 'border-accent/40 bg-accent/12 text-accent shadow-glow'
                        : isCompare
                          ? 'border-accent-2/35 bg-accent-2/10 text-accent-2'
                          : 'border-border bg-white/[0.025] text-muted hover:border-border-2 hover:text-txt',
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => setActiveRun(run.id)}
                      className="flex min-w-0 flex-1 items-center gap-2 rounded-[inherit] px-3 py-2 text-left"
                    >
                      <span className="hud-label rounded bg-white/[0.04] px-1.5 py-1">{isActive ? 'A' : isCompare ? 'B' : run.payload.type?.slice(0, 2) ?? '--'}</span>
                      <span className="min-w-0">
                        <span className="block truncate font-display text-xs font-semibold uppercase tracking-[0.08em]">
                          {truncateStr(run.name, 26)}
                        </span>
                        <span className="hud-label mt-0.5 block text-muted">{run.payload.type ?? 'unknown'}</span>
                      </span>
                    </button>
                    <button
                      type="button"
                      aria-label={`Close ${run.name}`}
                      data-cursor="close"
                      className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-current opacity-70 transition-colors hover:bg-white/[0.06] hover:text-txt hover:opacity-100"
                      onClick={(e) => {
                        e.stopPropagation()
                        if (runs.length === 1) {
                          clearBootstrapQueryParams()
                        }
                        removeRun(run.id)
                      }}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
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
                  <option value="">No compare run</option>
                  {runs.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          <div className="nav-rail-shell mt-2 border-t border-border/85 pt-2.5">
            <div
              ref={railRef}
              className="nav-rail flex items-center gap-1.5 overflow-x-auto"
            >
              {TABS.map((tab) => {
                const availability = getTabAvailability(activeRun?.payload, tab.id, {
                  comparePayload: compareRun?.payload,
                  sameCompareRun: Boolean(activeRun && compareRun && activeRun.id === compareRun.id),
                })
                const isAvailable = availability.supported
                const isDisabled = !availability.supported
                const isActive = activeTab === tab.id && !isDisabled
                return (
                  <button
                    key={tab.id}
                    type="button"
                    disabled={isDisabled}
                    aria-disabled={isDisabled || undefined}
                    aria-current={isActive ? 'page' : undefined}
                    onClick={isDisabled ? undefined : () => setActiveTab(tab.id)}
                    title={availability.supported ? availability.message : availability.title}
                    className={clsx(
                      'nav-item group shrink-0 rounded-[10px] text-xs',
                      isAvailable && 'nav-item--available',
                      isActive ? 'nav-item--active text-accent' : isDisabled ? 'nav-item--disabled text-muted' : 'nav-item--idle text-muted',
                      tab.group === 'product' && !isActive && !isDisabled && 'opacity-75',
                    )}
                  >
                    <span className="nav-item__sheen" aria-hidden="true" />
                    <span className="nav-item__edge" aria-hidden="true" />
                    <span className="nav-item__content">
                      <span className="nav-item__iconbox" aria-hidden="true">
                        <span className="nav-item__icon">{tab.icon}</span>
                      </span>
                      <span className="nav-item__copy">
                        <span className={clsx('nav-item__code hud-label', isActive ? 'text-accent-2' : 'text-steel')}>{tab.code}</span>
                        <span className="nav-item__label font-display font-semibold uppercase tracking-[0.08em]">{tab.label}</span>
                      </span>
                      {runs.length > 0 && (
                        <span className="nav-item__meta" aria-hidden="true">
                          {isDisabled ? (
                            <span className="nav-item__dot h-1.5 w-1.5 rounded-full bg-warn/80" />
                          ) : (
                            <span className="nav-item__indicator">
                              <ArrowUpRight className="h-3.5 w-3.5" />
                            </span>
                          )}
                        </span>
                      )}
                    </span>
                  </button>
                )
              })}
            </div>

            <div
              ref={railTrackRef}
              aria-hidden="true"
              className={clsx('nav-scrollbar', !navScrollState.visible && 'nav-scrollbar--hidden')}
              data-scroll-cursor-axis={navScrollState.visible ? 'x' : undefined}
              onPointerDown={onRailTrackPointerDown}
            >
              <div
                ref={railThumbRef}
                className={clsx('nav-scrollbar__thumb', navScrollState.dragging && 'is-dragging')}
                data-scroll-cursor-axis={navScrollState.visible ? 'x' : undefined}
                onPointerDown={onRailThumbPointerDown}
                style={{
                  transform: `translateX(${navScrollState.thumbOffset}px)`,
                  width: `${navScrollState.thumbWidth}px`,
                }}
              >
                <span className="nav-scrollbar__thumb-sheen" aria-hidden="true" />
              </div>
            </div>
          </div>
        </div>

        <div className="hidden w-[210px] shrink-0 text-right xl:block">
          <div className="hud-label text-muted">Active run</div>
          <div className="mt-2 truncate font-display text-xs font-semibold uppercase tracking-[0.08em] text-txt">
            {activeRun?.payload.meta?.runName ?? 'No run loaded'}
          </div>
          <div className="hud-label mt-2 text-accent-2">{activeBundle?.badge ?? 'No bundle loaded'}</div>
          <div className="hud-label mt-2 text-muted">{fmtDate(activeRun?.payload.meta?.createdAt)}</div>
        </div>
      </div>
    </nav>
  )
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}
