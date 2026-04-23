export interface AnchorRect {
  left: number
  top: number
  width: number
  height: number
}

export interface FloatingLayerLayout {
  left: number
  top: number
  width: number
  maxHeight: number
  placement: 'above' | 'below'
}

interface LayoutOptions {
  gap: number
  offset: number
  minWidth: number
  minHeight: number
}

const DEFAULT_OPTIONS: LayoutOptions = {
  gap: 16,
  offset: 14,
  minWidth: 320,
  minHeight: 240,
}

export function computeFloatingLayerLayout(
  rect: AnchorRect,
  viewport: { width: number; height: number },
  overrides: Partial<LayoutOptions> = {},
): FloatingLayerLayout {
  const { gap, offset, minWidth, minHeight } = { ...DEFAULT_OPTIONS, ...overrides }
  const maxWidth = Math.max(minWidth, viewport.width - gap * 2)
  const width = clamp(rect.width, minWidth, maxWidth)
  const maxLeft = Math.max(gap, viewport.width - width - gap)
  const left = clamp(rect.left, gap, maxLeft)

  const anchorBottom = rect.top + rect.height
  const spaceBelow = Math.max(0, viewport.height - anchorBottom - offset - gap)
  const spaceAbove = Math.max(0, rect.top - offset - gap)
  const viewportMaxHeight = Math.max(minHeight, viewport.height - gap * 2)
  const placeAbove = spaceBelow < minHeight && spaceAbove > spaceBelow
  const placement = placeAbove ? 'above' : 'below'
  const availableHeight = placement === 'above' ? spaceAbove : spaceBelow
  const maxHeight = Math.min(Math.max(availableHeight, minHeight), viewportMaxHeight)

  const proposedTop = placement === 'above'
    ? rect.top - offset - maxHeight
    : anchorBottom + offset
  const maxTop = Math.max(gap, viewport.height - maxHeight - gap)
  const top = clamp(proposedTop, gap, maxTop)

  return {
    left,
    top,
    width,
    maxHeight,
    placement,
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}
