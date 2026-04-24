import { useEffect, useRef } from 'react'
import {
  getScrollbarHitAtPoint,
  resolveCursorState,
  type ScrollbarAxis,
} from '../lib/cursor'

export function Cursor() {
  const ringRef = useRef<HTMLDivElement>(null)
  const coreRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (typeof window === 'undefined') return
    if (typeof window.matchMedia !== 'function') return
    const fine = window.matchMedia('(pointer: fine)')
    if (!fine.matches) return

    const ring = ringRef.current
    const core = coreRef.current
    if (!ring || !core) return

    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const body = document.body
    body.classList.add('has-custom-cursor')
    body.dataset.cursorState = 'idle'

    let targetX = window.innerWidth / 2
    let targetY = window.innerHeight / 2
    let ringX = targetX
    let ringY = targetY
    let coreX = targetX
    let coreY = targetY
    let raf = 0
    let visible = false
    let scrollbarMode = false
    let scrollbarAxis: ScrollbarAxis | null = null
    let scrollbarDragAxis: ScrollbarAxis | null = null

    const setCursorPoint = (element: HTMLDivElement, x: number, y: number) => {
      element.style.setProperty('--cursor-x', `${x}px`)
      element.style.setProperty('--cursor-y', `${y}px`)
    }

    const step = () => {
      if (prefersReduced) {
        ringX = targetX
        ringY = targetY
        coreX = targetX
        coreY = targetY
      } else {
        ringX += (targetX - ringX) * 0.32
        ringY += (targetY - ringY) * 0.32
        coreX += (targetX - coreX) * 0.55
        coreY += (targetY - coreY) * 0.55
      }
      setCursorPoint(ring, ringX, ringY)
      setCursorPoint(core, coreX, coreY)
      raf = window.requestAnimationFrame(step)
    }

    const show = () => {
      if (visible) return
      visible = true
      ring.classList.add('is-visible')
      core.classList.add('is-visible')
    }
    const hide = () => {
      if (!visible) return
      visible = false
      ring.classList.remove('is-visible')
      core.classList.remove('is-visible')
    }

    const clearScrollbarMode = () => {
      scrollbarMode = false
      scrollbarAxis = null
      delete body.dataset.cursorAxis
    }

    const updateScrollbarMode = (clientX: number, clientY: number) => {
      targetX = clientX
      targetY = clientY
      const hit = getScrollbarHitAtPoint({ x: clientX, y: clientY })
      const axis = scrollbarDragAxis ?? hit?.axis ?? null

      if (axis) {
        scrollbarMode = true
        scrollbarAxis = axis
        body.dataset.cursorState = 'scroll'
        body.dataset.cursorAxis = axis
        show()
        return true
      }

      clearScrollbarMode()
      return false
    }

    const onMove = (event: PointerEvent) => {
      if (updateScrollbarMode(event.clientX, event.clientY)) return
      clearScrollbarMode()
      body.dataset.cursorState = resolveCursorState(document.elementFromPoint(event.clientX, event.clientY))
      show()
    }
    const onOver = (event: PointerEvent) => {
      if (updateScrollbarMode(event.clientX, event.clientY)) return
      clearScrollbarMode()
      body.dataset.cursorState = resolveCursorState(event.target as Element | null)
    }
    const onDown = (event: PointerEvent) => {
      body.dataset.cursorPressed = 'true'
      if (updateScrollbarMode(event.clientX, event.clientY)) {
        scrollbarDragAxis = scrollbarAxis
        return
      }
    }
    const onUp = (event: PointerEvent) => {
      delete body.dataset.cursorPressed
      scrollbarDragAxis = null
      if (updateScrollbarMode(event.clientX, event.clientY)) return
      clearScrollbarMode()
      body.dataset.cursorState = resolveCursorState(document.elementFromPoint(event.clientX, event.clientY))
      show()
    }
    const onScroll = () => {
      if (scrollbarMode && scrollbarAxis) {
        body.dataset.cursorState = 'scroll'
        body.dataset.cursorAxis = scrollbarAxis
        show()
      }
    }
    const onLeaveWindow = (event: PointerEvent) => {
      if (event.relatedTarget == null) {
        scrollbarDragAxis = null
        clearScrollbarMode()
        hide()
      }
    }
    const onEnterWindow = (event: PointerEvent) => {
      if (updateScrollbarMode(event.clientX, event.clientY)) return
      clearScrollbarMode()
      body.dataset.cursorState = resolveCursorState(document.elementFromPoint(event.clientX, event.clientY))
      show()
    }
    const onBlur = () => {
      scrollbarDragAxis = null
      clearScrollbarMode()
      delete body.dataset.cursorPressed
      body.dataset.cursorState = 'idle'
      hide()
    }

    window.addEventListener('pointermove', onMove, { passive: true })
    window.addEventListener('pointerover', onOver, { passive: true })
    window.addEventListener('pointerdown', onDown)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('scroll', onScroll, true)
    document.addEventListener('pointerleave', onLeaveWindow)
    document.addEventListener('pointerenter', onEnterWindow)
    window.addEventListener('blur', onBlur)
    raf = window.requestAnimationFrame(step)

    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerover', onOver)
      window.removeEventListener('pointerdown', onDown)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('scroll', onScroll, true)
      document.removeEventListener('pointerleave', onLeaveWindow)
      document.removeEventListener('pointerenter', onEnterWindow)
      window.removeEventListener('blur', onBlur)
      window.cancelAnimationFrame(raf)
      body.classList.remove('has-custom-cursor')
      delete body.dataset.cursorState
      delete body.dataset.cursorPressed
      delete body.dataset.cursorAxis
    }
  }, [])

  return (
    <>
      <div ref={ringRef} className="custom-cursor custom-cursor-ring" aria-hidden="true" />
      <div ref={coreRef} className="custom-cursor custom-cursor-core" aria-hidden="true" />
    </>
  )
}
