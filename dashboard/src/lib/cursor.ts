const INTERACTIVE_SELECTOR =
  'a, button, [role="button"], input:not([type="checkbox"]):not([type="radio"]):not([disabled]), select, textarea, summary, label[for], [data-interactive="true"], .file-drop'
const TEXT_SELECTOR =
  'input:not([type="checkbox"]):not([type="radio"]):not([type="button"]):not([type="submit"]):not([type="reset"]):not([disabled]), textarea, [contenteditable="true"]'
const CLOSE_SELECTOR = '[data-cursor="close"], [aria-label^="Close"], [aria-label^="Dismiss"]'

export type CursorState = 'idle' | 'hover' | 'close' | 'text'

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
  const verticalThreshold = Math.max(0, viewport.width - scrollbars.vertical - buffer)
  const horizontalThreshold = Math.max(0, viewport.height - scrollbars.horizontal - buffer)
  const onVerticalScrollbar = scrollbars.vertical > 0 && point.x >= verticalThreshold
  const onHorizontalScrollbar = scrollbars.horizontal > 0 && point.y >= horizontalThreshold
  return onVerticalScrollbar || onHorizontalScrollbar
}

export function resolveCursorState(target: Element | null): CursorState {
  if (!target) return 'idle'
  if (target.closest(CLOSE_SELECTOR)) return 'close'
  if (target.closest(TEXT_SELECTOR)) return 'text'
  if (target.closest(INTERACTIVE_SELECTOR)) return 'hover'
  return 'idle'
}
