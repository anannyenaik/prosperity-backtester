export const C = {
  total: '#7de7ff',
  osmium: '#8cb6ff',
  pepper: '#c7ab66',
  realised: '#74d394',
  unrealised: '#ef6b77',
  mid: '#8e958f',
  fair: '#7de7ff',
  fillBuy: '#74d394',
  fillSell: '#ef6b77',
  capLine: '#ef6b77',
  p50: '#7de7ff',
  pBand: 'rgba(125,231,255,0.12)',
  pBandOuter: 'rgba(125,231,255,0.06)',
  mcSession: '#c7ab66',
  optimistic: '#74d394',
  base: '#7de7ff',
  conservative: '#ef6b77',
  neutral: '#8e958f',
  good: '#74d394',
  bad: '#ef6b77',
  warn: '#d6b65a',
  accent: '#7de7ff',
  accentAlpha: 'rgba(125,231,255,0.18)',
} as const

export const GRID = 'rgba(228,219,201,0.09)'
export const AXIS_TEXT = '#8e958f'
export const TOOLTIP_BG = 'rgba(8, 14, 22, 0.96)'
export const TOOLTIP_BORDER = 'rgba(125,231,255,0.18)'

export const FILL_MODEL_COLORS: Record<string, string> = {
  optimistic: C.optimistic,
  base: C.base,
  conservative: C.conservative,
}

export const CHART_MARGINS = { top: 12, right: 20, left: 8, bottom: 8 } as const
export const CHART_HEIGHT = 260
export const CHART_HEIGHT_LG = 320
export const CHART_HEIGHT_SM = 200
