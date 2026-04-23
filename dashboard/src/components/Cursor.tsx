import { useEffect, useRef } from 'react'

const INTERACTIVE_SELECTOR =
  'a, button, [role="button"], input:not([type="checkbox"]):not([type="radio"]):not([disabled]), select, textarea, summary, label[for], [data-interactive="true"], .file-drop'
const TEXT_SELECTOR =
  'input:not([type="checkbox"]):not([type="radio"]):not([type="button"]):not([type="submit"]):not([type="reset"]):not([disabled]), textarea, [contenteditable="true"]'
const CLOSE_SELECTOR = '[data-cursor="close"], [aria-label^="Close"], [aria-label^="Dismiss"]'

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

    const onMove = (event: PointerEvent) => {
      targetX = event.clientX
      targetY = event.clientY
      show()
    }
    const onOver = (event: PointerEvent) => {
      const target = event.target as Element | null
      if (!target) return
      if (target.closest(CLOSE_SELECTOR)) {
        body.dataset.cursorState = 'close'
        return
      }
      if (target.closest(TEXT_SELECTOR)) {
        body.dataset.cursorState = 'text'
        return
      }
      if (target.closest(INTERACTIVE_SELECTOR)) {
        body.dataset.cursorState = 'hover'
        return
      }
      body.dataset.cursorState = 'idle'
    }
    const onDown = () => {
      body.dataset.cursorPressed = 'true'
    }
    const onUp = () => {
      delete body.dataset.cursorPressed
    }
    const onLeaveWindow = (event: PointerEvent) => {
      if (event.relatedTarget == null) hide()
    }
    const onEnterWindow = () => show()
    const onBlur = () => hide()

    window.addEventListener('pointermove', onMove, { passive: true })
    window.addEventListener('pointerover', onOver, { passive: true })
    window.addEventListener('pointerdown', onDown)
    window.addEventListener('pointerup', onUp)
    document.addEventListener('pointerleave', onLeaveWindow)
    document.addEventListener('pointerenter', onEnterWindow)
    window.addEventListener('blur', onBlur)
    raf = window.requestAnimationFrame(step)

    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerover', onOver)
      window.removeEventListener('pointerdown', onDown)
      window.removeEventListener('pointerup', onUp)
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
