import type { DashboardPayload, TabId } from '../types'

export type BundleType =
  | 'replay'
  | 'monte_carlo'
  | 'calibration'
  | 'comparison'
  | 'optimization'
  | 'round2_scenarios'
  | 'unknown'

export interface BundleInterpretation {
  type: BundleType
  rawType: string
  label: string
  badge: string
  description: string
  hasReplaySummary: boolean
  hasReplayPath: boolean
  hasMonteCarlo: boolean
  hasCalibration: boolean
  hasComparisonRows: boolean
  hasOptimization: boolean
  hasRound2Rows: boolean
}

export interface TabAvailability {
  supported: boolean
  title: string
  message: string
}

interface AvailabilityOptions {
  comparePayload?: DashboardPayload | null
  sameCompareRun?: boolean
}

const BUNDLE_LABELS: Record<BundleType, string> = {
  replay: 'Replay',
  monte_carlo: 'Monte Carlo',
  calibration: 'Calibration',
  comparison: 'Comparison',
  optimization: 'Optimisation',
  round2_scenarios: 'Round 2 scenario',
  unknown: 'Unknown',
}

const BUNDLE_DESCRIPTIONS: Record<BundleType, string> = {
  replay: 'deterministic replay summary and per-tick series',
  monte_carlo: 'Monte Carlo session statistics, sample paths and fair-value bands',
  calibration: 'live-vs-simulator calibration candidates and diagnostics',
  comparison: 'precomputed trader comparison rows',
  optimization: 'parameter sweep and robustness ranking rows',
  round2_scenarios: 'Round 2 scenario aggregates, MAF sensitivity and ranking diagnostics',
  unknown: 'a schema the dashboard cannot classify confidently',
}

export function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

export function numberOrNull(value: unknown): number | null {
  if (isFiniteNumber(value)) return value
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

export function formatBool(value: boolean | null | undefined): string {
  if (value == null) return 'not available'
  return value ? 'yes' : 'no'
}

function hasRows(value: unknown): boolean {
  return Array.isArray(value) && value.length > 0
}

function normaliseBundleType(value: unknown): BundleType {
  if (typeof value !== 'string') return 'unknown'
  const key = value.trim().toLowerCase().replace(/-/g, '_')
  if (key === 'montecarlo' || key === 'mc') return 'monte_carlo'
  if (key === 'compare') return 'comparison'
  if (key === 'optimisation') return 'optimization'
  if (key === 'optimize' || key === 'optimise') return 'optimization'
  if (key === 'round2' || key === 'round_2' || key === 'round2_scenario') return 'round2_scenarios'
  if (
    key === 'replay' ||
    key === 'monte_carlo' ||
    key === 'calibration' ||
    key === 'comparison' ||
    key === 'optimization' ||
    key === 'round2_scenarios'
  ) {
    return key
  }
  return 'unknown'
}

export function detectBundleType(payload: DashboardPayload | null | undefined): BundleType {
  if (!payload) return 'unknown'

  const explicitType = normaliseBundleType(payload.type)
  if (explicitType !== 'unknown') return explicitType

  if (payload.round2) return 'round2_scenarios'
  if (payload.monteCarlo) return 'monte_carlo'
  if (payload.calibration) return 'calibration'
  if (payload.optimization) return 'optimization'
  if (hasRows(payload.comparison)) return 'comparison'
  if (payload.summary || hasRows(payload.pnlSeries) || hasRows(payload.inventorySeries)) return 'replay'

  const modeType = normaliseBundleType(payload.meta?.mode)
  return modeType === 'unknown' ? 'unknown' : modeType
}

export function interpretBundle(payload: DashboardPayload | null | undefined): BundleInterpretation {
  const type = detectBundleType(payload)
  const comparisonRows = getComparisonRows(payload)
  const hasRound2Rows = hasRows(payload?.round2?.scenarioRows) || hasRows(payload?.round2?.winnerRows)

  return {
    type,
    rawType: typeof payload?.type === 'string' && payload.type.trim() ? payload.type : 'unknown',
    label: BUNDLE_LABELS[type],
    badge: `${BUNDLE_LABELS[type]} bundle`,
    description: BUNDLE_DESCRIPTIONS[type],
    hasReplaySummary: Boolean(payload?.summary),
    hasReplayPath:
      hasRows(payload?.pnlSeries) ||
      hasRows(payload?.inventorySeries) ||
      hasRows(payload?.fairValueSeries) ||
      hasRows(payload?.fills) ||
      hasRows(payload?.orders),
    hasMonteCarlo: Boolean(payload?.monteCarlo?.summary),
    hasCalibration: Boolean(payload?.calibration?.grid?.length || payload?.calibration?.best),
    hasComparisonRows: comparisonRows.length > 0,
    hasOptimization: Boolean(payload?.optimization?.rows?.length),
    hasRound2Rows,
  }
}

export function getComparisonRows(payload: DashboardPayload | null | undefined) {
  if (hasRows(payload?.comparison)) return payload!.comparison!
  if (hasRows(payload?.round2?.scenarioRows)) return payload!.round2!.scenarioRows
  return []
}

export function getTabAvailability(
  payload: DashboardPayload | null | undefined,
  tab: TabId,
  options: AvailabilityOptions = {},
): TabAvailability {
  if (!payload) {
    return {
      supported: false,
      title: 'No bundle loaded',
      message: 'Load a dashboard.json bundle to begin analysis.',
    }
  }

  const bundle = interpretBundle(payload)

  if (tab === 'overview') {
    return {
      supported: true,
      title: 'Overview available',
      message: `${bundle.badge} detected.`,
    }
  }

  if (tab === 'replay') {
    if (bundle.type !== 'replay') {
      return incompatible(
        'This tab requires a replay bundle.',
        `${bundle.badge} contains ${bundle.description}, not top-level replay paths.`,
      )
    }
    if (!bundle.hasReplayPath) {
      return missing('Replay path data is not present in this bundle.', 'The replay tab needs top-level PnL, inventory, fair-value, fill or order series.')
    }
    return available('Replay data available', 'Top-level replay series are present.')
  }

  if (tab === 'montecarlo') {
    if (bundle.type !== 'monte_carlo') {
      return incompatible('This Monte Carlo view requires a monte_carlo bundle.', 'Monte Carlo metrics are not available for this bundle type.')
    }
    if (!bundle.hasMonteCarlo) {
      return missing('Monte Carlo summary is not present in this bundle.', 'The Monte Carlo tab needs the `monteCarlo.summary` object.')
    }
    return available('Monte Carlo data available', 'Session statistics and robustness data are present.')
  }

  if (tab === 'calibration') {
    if (bundle.type !== 'calibration') {
      return incompatible('This tab requires a calibration bundle.', 'Calibration metrics are not available for this bundle type.')
    }
    if (!bundle.hasCalibration) {
      return missing('Calibration data is not present in this bundle.', 'The calibration tab needs grid candidates or a best candidate.')
    }
    return available('Calibration data available', 'Calibration candidates are present.')
  }

  if (tab === 'optimize') {
    if (bundle.type !== 'optimization') {
      return incompatible('This tab requires an optimisation bundle.', 'Optimisation metrics are not available for this bundle type.')
    }
    if (!bundle.hasOptimization) {
      return missing('Optimisation rows are not present in this bundle.', 'The optimisation tab needs parameter sweep rows.')
    }
    return available('Optimisation data available', 'Parameter sweep rows are present.')
  }

  if (tab === 'round2') {
    if (bundle.type !== 'round2_scenarios') {
      return incompatible('This tab requires a round2_scenarios bundle.', `${bundle.badge} contains ${bundle.description}, not scenario aggregates.`)
    }
    if (!bundle.hasRound2Rows) {
      return missing('Round 2 scenario rows are not present in this bundle.', 'The Round 2 tab needs scenario, winner or MAF sensitivity rows.')
    }
    return available('Round 2 scenario data available', 'Scenario aggregates are present.')
  }

  if (tab === 'inspect' || tab === 'osmium' || tab === 'pepper') {
    if (!bundle.hasReplayPath) {
      return incompatible('Replay-style time-series data is not present.', 'Load a replay bundle to inspect per-tick data.')
    }
    return available('Replay-style time-series data available', 'Per-tick rows are present.')
  }

  if (tab === 'compare') {
    if ((bundle.type === 'comparison' || bundle.type === 'round2_scenarios') && bundle.hasComparisonRows) {
      return available('Comparison rows available', 'Precomputed comparison rows are present.')
    }

    if (options.sameCompareRun) {
      return incompatible('Select a different comparison run.', 'The dashboard will not compare a bundle to itself unless a comparison bundle contains explicit rows.')
    }

    const compareBundle = interpretBundle(options.comparePayload)
    if (bundle.hasReplaySummary && compareBundle.hasReplaySummary) {
      return available('Two replay summaries available', 'Side-by-side replay comparison can be rendered.')
    }

    return incompatible(
      'This tab requires comparison data.',
      'Comparison metrics are only available in comparison bundles, compatible scenario diagnostics, or two loaded replay summaries.',
    )
  }

  return incompatible('This tab is not available for this bundle type.', `${bundle.badge} contains ${bundle.description}.`)
}

export function bundleTypeLabel(type: BundleType): string {
  return BUNDLE_LABELS[type]
}

function available(title: string, message: string): TabAvailability {
  return { supported: true, title, message }
}

function incompatible(title: string, message: string): TabAvailability {
  return { supported: false, title, message }
}

function missing(title: string, message: string): TabAvailability {
  return { supported: false, title, message }
}
