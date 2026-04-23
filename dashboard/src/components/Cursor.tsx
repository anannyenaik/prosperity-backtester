import { useEffect, useRef } from 'react'
import {
  isPointNearViewportScrollbar,
  measureViewportScrollbars,
  resolveCursorState,
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
      ring.style.transform = `translate3d(${ringX}px, ${ringY}px, 0) translate(-50%, -50%)`
      core.style.transform = `translate3d(${coreX}px, ${coreY}px, 0) translate(-50%, -50%)`
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

    const updateScrollbarMode = (clientX: number, clientY: number) => {
      const scrollbars = measureViewportScrollbars(
        window.innerWidth,
        window.innerHeight,
        document.documentElement.clientWidth,
        document.documentElement.clientHeight,
      )
      const nextScrollbarMode = isPointNearViewportScrollbar(
        { x: clientX, y: clientY },
        { width: window.innerWidth, height: window.innerHeight },
        scrollbars,
      )

      if (nextScrollbarMode) {
        scrollbarMode = true
        body.dataset.cursorState = 'idle'
        delete body.dataset.cursorPressed
        hide()
        return true
      }

      scrollbarMode = false
      return false
    }

    const onMove = (event: PointerEvent) => {
      if (updateScrollbarMode(event.clientX, event.clientY)) return
      targetX = event.clientX
      targetY = event.clientY
      body.dataset.cursorState = resolveCursorState(document.elementFromPoint(event.clientX, event.clientY))
      show()
    }
    const onOver = (event: PointerEvent) => {
      if (updateScrollbarMode(event.clientX, event.clientY)) return
      body.dataset.cursorState = resolveCursorState(event.target as Element | null)
    }
    const onDown = (event: PointerEvent) => {
      if (updateScrollbarMode(event.clientX, event.clientY)) return
      body.dataset.cursorPressed = 'true'
    }
    const onUp = (event: PointerEvent) => {
      delete body.dataset.cursorPressed
      if (updateScrollbarMode(event.clientX, event.clientY)) return
      body.dataset.cursorState = resolveCursorState(document.elementFromPoint(event.clientX, event.clientY))
      show()
    }
    const onScroll = () => {
      if (body.dataset.cursorPressed !== 'true') return
      scrollbarMode = true
      body.dataset.cursorState = 'idle'
      hide()
    }
    const onLeaveWindow = (event: PointerEvent) => {
      if (event.relatedTarget == null) {
        scrollbarMode = false
        hide()
      }
    }
    const onEnterWindow = (event: PointerEvent) => {
      if (updateScrollbarMode(event.clientX, event.clientY)) return
      body.dataset.cursorState = resolveCursorState(document.elementFromPoint(event.clientX, event.clientY))
      show()
    }
    const onBlur = () => {
      scrollbarMode = false
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
    }
  }, [])

  return (
    <>
      <div ref={ringRef} className="custom-cursor custom-cursor-ring" aria-hidden="true" />
      <div ref={coreRef} className="custom-cursor custom-cursor-core" aria-hidden="true" />
    </>
  )
}
