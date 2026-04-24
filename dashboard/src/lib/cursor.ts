const INTERACTIVE_SELECTOR =
  'a, button, [role="button"], input:not([type="checkbox"]):not([type="radio"]):not([disabled]), select, textarea, summary, label[for], [data-interactive="true"], .file-drop'
const TEXT_SELECTOR =
  'input:not([type="checkbox"]):not([type="radio"]):not([type="button"]):not([type="submit"]):not([type="reset"]):not([disabled]), textarea, [contenteditable="true"]'
const CLOSE_SELECTOR = '[data-cursor="close"], [aria-label^="Close"], [aria-label^="Dismiss"]'

export type CursorState = 'idle' | 'hover' | 'close' | 'text' | 'scroll'
export type ScrollbarAxis = 'x' | 'y'

export interface RectLike {
  left: number
  top: number
  right: number
  bottom: number
}

export interface ElementScrollbarBox {
  rect: RectLike
  clientWidth: number
  clientHeight: number
  offsetWidth: number
  offsetHeight: number
  scrollWidth: number
  scrollHeight: number
  borderTop: number
  borderRight: number
  borderBottom: number
  borderLeft: number
  forcedHorizontal?: number
  forcedVertical?: number
}

export interface ScrollbarHit {
  axis: ScrollbarAxis
  element: HTMLElement | null
  kind: 'viewport' | 'element'
}

const SCROLLABLE_OVERFLOW = new Set(['auto', 'scroll', 'overlay'])

export interface ScrollbarMetrics {
  vertical: number
  horizontal: number
}

export function measureViewportScrollbars(
  viewportWidth: number,
  viewportHeight: number,
  clientWidth: number,
  clientHeight: number,
): ScrollbarMetrics {
  return {
    vertical: Math.max(viewportWidth - clientWidth, 0),
    horizontal: Math.max(viewportHeight - clientHeight, 0),
  }
}

export function isPointNearViewportScrollbar(
  point: { x: number; y: number },
  viewport: { width: number; height: number },
  scrollbars: ScrollbarMetrics,
  buffer = 2,
): boolean {
  return getViewportScrollbarAxis(point, viewport, scrollbars, buffer) != null
}

export function getViewportScrollbarAxis(
  point: { x: number; y: number },
  viewport: { width: number; height: number },
  scrollbars: ScrollbarMetrics,
  buffer = 2,
): ScrollbarAxis | null {
  const verticalThreshold = Math.max(0, viewport.width - scrollbars.vertical - buffer)
  const horizontalThreshold = Math.max(0, viewport.height - scrollbars.horizontal - buffer)
  const onVerticalScrollbar = scrollbars.vertical > 0 && point.x >= verticalThreshold
  const onHorizontalScrollbar = scrollbars.horizontal > 0 && point.y >= horizontalThreshold
  if (onVerticalScrollbar) return 'y'
  if (onHorizontalScrollbar) return 'x'
  return null
}

export function measureElementScrollbars(box: ElementScrollbarBox): ScrollbarMetrics {
  const vertical = Math.max(box.offsetWidth - box.clientWidth - box.borderLeft - box.borderRight, 0)
  const horizontal = Math.max(box.offsetHeight - box.clientHeight - box.borderTop - box.borderBottom, 0)
  return {
    vertical: vertical || Math.max(box.forcedVertical ?? 0, 0),
    horizontal: horizontal || Math.max(box.forcedHorizontal ?? 0, 0),
  }
}

export function getElementScrollbarAxis(
  point: { x: number; y: number },
  box: ElementScrollbarBox,
  buffer = 2,
): ScrollbarAxis | null {
  const scrollbars = measureElementScrollbars(box)
  const canScrollY = box.scrollHeight > box.clientHeight + 1 && scrollbars.vertical > 0
  const canScrollX = box.scrollWidth > box.clientWidth + 1 && scrollbars.horizontal > 0
  if (!canScrollX && !canScrollY) return null

  const innerLeft = box.rect.left + box.borderLeft
  const innerRight = box.rect.right - box.borderRight
  const innerTop = box.rect.top + box.borderTop
  const innerBottom = box.rect.bottom - box.borderBottom

  if (canScrollY) {
    const verticalStart = innerRight - scrollbars.vertical - buffer
    const verticalBottom = innerBottom - (canScrollX ? scrollbars.horizontal : 0)
    if (point.x >= verticalStart && point.x <= innerRight + buffer && point.y >= innerTop && point.y <= verticalBottom + buffer) {
      return 'y'
    }
  }

  if (canScrollX) {
    const horizontalStart = innerBottom - scrollbars.horizontal - buffer
    const horizontalRight = innerRight - (canScrollY ? scrollbars.vertical : 0)
    if (point.y >= horizontalStart && point.y <= innerBottom + buffer && point.x >= innerLeft && point.x <= horizontalRight + buffer) {
      return 'x'
    }
  }

  return null
}

export function getScrollbarHitAtPoint(
  point: { x: number; y: number },
  doc: Document = document,
): ScrollbarHit | null {
  if (typeof window === 'undefined') return null

  const viewport = { width: window.innerWidth, height: window.innerHeight }
  const viewportScrollbars = measureViewportScrollbars(
    viewport.width,
    viewport.height,
    doc.documentElement.clientWidth,
    doc.documentElement.clientHeight,
  )
  const viewportAxis = getViewportScrollbarAxis(point, viewport, viewportScrollbars)
  if (viewportAxis) {
    return { axis: viewportAxis, element: null, kind: 'viewport' }
  }

  for (const element of getScrollbarCandidates(doc, point)) {
    const explicitAxis = getExplicitScrollCursorAxis(element)
    if (explicitAxis) {
      return {
        axis: explicitAxis,
        element: isHtmlElement(element) ? element : null,
        kind: 'element',
      }
    }

    if (!isHtmlElement(element)) continue
    if (element === doc.body || element === doc.documentElement) continue

    const hintedAxis = getHintedScrollbarAxis(element)
    const style = window.getComputedStyle(element)
    const overflowX = normaliseOverflow(style.overflowX, style.overflow)
    const overflowY = normaliseOverflow(style.overflowY, style.overflow)
    if (!hintedAxis && !SCROLLABLE_OVERFLOW.has(overflowX) && !SCROLLABLE_OVERFLOW.has(overflowY)) {
      continue
    }

    const hintedSize = getHintedScrollbarSize(element)
    const axis = getElementScrollbarAxis(point, {
      rect: element.getBoundingClientRect(),
      clientWidth: element.clientWidth,
      clientHeight: element.clientHeight,
      offsetWidth: element.offsetWidth,
      offsetHeight: element.offsetHeight,
      scrollWidth: element.scrollWidth,
      scrollHeight: element.scrollHeight,
      borderTop: readPixels(style.borderTopWidth),
      borderRight: readPixels(style.borderRightWidth),
      borderBottom: readPixels(style.borderBottomWidth),
      borderLeft: readPixels(style.borderLeftWidth),
      forcedHorizontal: hintedAxis === 'x' ? hintedSize ?? undefined : undefined,
      forcedVertical: hintedAxis === 'y' ? hintedSize ?? undefined : undefined,
    })
    if (!axis) continue
    if (hintedAxis && axis !== hintedAxis) continue
    return { axis, element, kind: 'element' }
  }

  return null
}

export function resolveCursorState(target: Element | null): CursorState {
  if (!target) return 'idle'
  if (target.closest(CLOSE_SELECTOR)) return 'close'
  if (target.closest(TEXT_SELECTOR)) return 'text'
  if (target.closest(INTERACTIVE_SELECTOR)) return 'hover'
  return 'idle'
}

export function getExplicitScrollCursorAxis(target: Element | null): ScrollbarAxis | null {
  const candidate = target?.closest?.('[data-scroll-cursor-axis]')
  const axis = candidate?.getAttribute('data-scroll-cursor-axis')
  return axis === 'x' || axis === 'y' ? axis : null
}

function getScrollbarCandidates(doc: Document, point: { x: number; y: number }): Element[] {
  const fromPoint =
    typeof doc.elementsFromPoint === 'function'
      ? doc.elementsFromPoint(point.x, point.y)
      : [doc.elementFromPoint(point.x, point.y)].filter(Boolean) as Element[]
  const hinted = Array.from(doc.querySelectorAll('[data-scrollbar-axis]'))
  const seen = new Set<Element>()
  const candidates: Element[] = []
  for (const element of [...fromPoint, ...hinted]) {
    if (seen.has(element)) continue
    seen.add(element)
    candidates.push(element)
  }
  return candidates
}

function getHintedScrollbarAxis(element: Element): ScrollbarAxis | null {
  const axis = element.getAttribute('data-scrollbar-axis')
  return axis === 'x' || axis === 'y' ? axis : null
}

function getHintedScrollbarSize(element: Element): number | null {
  const value = Number(element.getAttribute('data-scrollbar-size'))
  return Number.isFinite(value) && value > 0 ? value : null
}

function normaliseOverflow(value: string, fallback: string): string {
  return value === 'visible' ? fallback : value
}

function readPixels(value: string): number {
  const parsed = Number.parseFloat(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function isHtmlElement(element: Element): element is HTMLElement {
  return typeof HTMLElement !== 'undefined' && element instanceof HTMLElement
}
