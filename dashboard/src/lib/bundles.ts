import type { DashboardPayload, TabId } from '../types'

export type BundleType =
  | 'replay'
  | 'monte_carlo'
  | 'calibration'
  | 'comparison'
  | 'optimization'
  | 'round2_scenarios'
  | 'workspace'
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
  isWorkspace: boolean
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
  workspace: 'Workspace',
  unknown: 'Unknown',
}

const BUNDLE_DESCRIPTIONS: Record<BundleType, string> = {
  replay: 'deterministic replay summary, fills and replay-path evidence',
  monte_carlo: 'Monte Carlo session statistics, all-session path bands and sample runs',
  calibration: 'live-vs-simulator calibration candidates and diagnostics',
  comparison: 'precomputed trader comparison rows',
  optimization: 'parameter sweep and robustness ranking rows',
  round2_scenarios: 'Round 2 scenario aggregates, MAF sensitivity and ranking diagnostics',
  workspace: 'an all-in-one research workspace composed of child bundles',
  unknown: 'a schema the dashboard cannot classify confidently',
}

const ROW_TABLE_ENCODING = 'row_table_v1'
const TOP_LEVEL_SERIES_KEYS = [
  'orders',
  'orderIntent',
  'fills',
  'inventorySeries',
  'pnlSeries',
  'fairValueSeries',
  'behaviourSeries',
] as const
const SAMPLE_RUN_SERIES_KEYS = [
  'inventorySeries',
  'pnlSeries',
  'fills',
  'orderIntent',
  'fairValueSeries',
  'behaviourSeries',
] as const

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

function isRowTable(value: unknown): value is { encoding: string; columns: string[]; rows: unknown[][] } {
  return Boolean(
    value &&
      typeof value === 'object' &&
      (value as Record<string, unknown>).encoding === ROW_TABLE_ENCODING &&
      Array.isArray((value as Record<string, unknown>).columns) &&
      Array.isArray((value as Record<string, unknown>).rows),
  )
}

function expandRowTable(value: unknown): unknown {
  if (!isRowTable(value)) return value
  const columns = value.columns.map((column) => String(column))
  return value.rows.map((row) =>
    Object.fromEntries(columns.map((column, index) => [column, Array.isArray(row) ? row[index] : null])),
  )
}

function expandTableLeaves(value: unknown): unknown {
  if (isRowTable(value)) return expandRowTable(value)
  if (!value || typeof value !== 'object' || Array.isArray(value)) return value
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([key, child]) => [key, expandTableLeaves(child)]),
  )
}

function expandSeriesField<T extends object, K extends keyof T>(target: T, key: K): void {
  target[key] = expandRowTable(target[key]) as T[K]
}

export function normaliseDashboardPayload(payload: DashboardPayload): DashboardPayload {
  const normalised: DashboardPayload = { ...payload }
  for (const key of TOP_LEVEL_SERIES_KEYS) {
    expandSeriesField(normalised, key)
  }
  if (!payload.monteCarlo) return normalised
  const monteCarlo = { ...payload.monteCarlo }
  expandSeriesField(monteCarlo, 'sessions')
  monteCarlo.sampleRuns = (monteCarlo.sampleRuns ?? []).map((sample) => {
    const expanded = { ...sample }
    for (const key of SAMPLE_RUN_SERIES_KEYS) {
      expandSeriesField(expanded, key)
    }
    return expanded
  })
  if (monteCarlo.pathBands) {
    monteCarlo.pathBands = expandTableLeaves(monteCarlo.pathBands) as typeof monteCarlo.pathBands
  }
  if (monteCarlo.fairValueBands) {
    monteCarlo.fairValueBands = expandTableLeaves(monteCarlo.fairValueBands) as typeof monteCarlo.fairValueBands
  }
  normalised.monteCarlo = monteCarlo
  return normalised
}

function normaliseBundleType(value: unknown): BundleType {
  if (typeof value !== 'string') return 'unknown'
  const key = value.trim().toLowerCase().replace(/-/g, '_')
  if (key === 'montecarlo' || key === 'mc') return 'monte_carlo'
  if (key === 'compare') return 'comparison'
  if (key === 'optimisation') return 'optimization'
  if (key === 'optimize' || key === 'optimise') return 'optimization'
  if (key === 'round2' || key === 'round_2' || key === 'round2_scenario') return 'round2_scenarios'
  if (key === 'research_workspace' || key === 'all_in_one' || key === 'all_in_one_bundle') return 'workspace'
  if (
    key === 'replay' ||
    key === 'monte_carlo' ||
    key === 'calibration' ||
    key === 'comparison' ||
    key === 'optimization' ||
    key === 'round2_scenarios' ||
    key === 'workspace'
  ) {
    return key
  }
  return 'unknown'
}

function hasWorkspaceMeta(payload: DashboardPayload | null | undefined): boolean {
  const ws = payload?.workspace
  return Boolean(ws && Array.isArray(ws.sources) && ws.sources.length > 0)
}

export function detectBundleType(payload: DashboardPayload | null | undefined): BundleType {
  if (!payload) return 'unknown'

  const explicitType = normaliseBundleType(payload.type)
  if (explicitType === 'workspace') return 'workspace'
  if (hasWorkspaceMeta(payload)) return 'workspace'
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
  const isWorkspace = type === 'workspace'
  const badge = isWorkspace ? 'Workspace' : `${BUNDLE_LABELS[type]} bundle`

  return {
    type,
    rawType: typeof payload?.type === 'string' && payload.type.trim() ? payload.type : 'unknown',
    label: BUNDLE_LABELS[type],
    badge,
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
    isWorkspace,
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

  if (tab === 'alpha') {
    const hasEvidence =
      bundle.hasReplaySummary ||
      bundle.hasReplayPath ||
      bundle.hasMonteCarlo ||
      bundle.hasComparisonRows ||
      bundle.hasRound2Rows
    if (hasEvidence) {
      return available('Alpha Lab evidence available', 'Alpha Lab will classify only the evidence present in this bundle.')
    }
    return incompatible(
      'Alpha Lab evidence is not present.',
      `${bundle.badge} does not contain replay, Monte Carlo, comparison or Round 2 rows for hypothesis scoring.`,
    )
  }

  if (tab === 'replay') {
    if (bundle.isWorkspace) {
      return bundle.hasReplayPath
        ? available('Replay data available', 'Top-level replay series are present in this workspace.')
        : missing('Replay data is not included in this workspace.', 'No replay child bundle contributed top-level series to this workspace.')
    }
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
    if (bundle.isWorkspace) {
      return bundle.hasMonteCarlo
        ? available('Monte Carlo data available', 'Monte Carlo data is present in this workspace.')
        : missing('Monte Carlo data is not included in this workspace.', 'No Monte Carlo child bundle contributed a `monteCarlo.summary` to this workspace.')
    }
    if (bundle.type !== 'monte_carlo') {
      return incompatible('This Monte Carlo view requires a monte_carlo bundle.', 'Monte Carlo metrics are not available for this bundle type.')
    }
    if (!bundle.hasMonteCarlo) {
      return missing('Monte Carlo summary is not present in this bundle.', 'The Monte Carlo tab needs the `monteCarlo.summary` object.')
    }
    return available('Monte Carlo data available', 'Session statistics and robustness data are present.')
  }

  if (tab === 'calibration') {
    if (bundle.isWorkspace) {
      return bundle.hasCalibration
        ? available('Calibration data available', 'Calibration candidates are present in this workspace.')
        : missing('Calibration data is not included in this workspace.', 'No calibration child bundle contributed grid or best-candidate data to this workspace.')
    }
    if (bundle.type !== 'calibration') {
      return incompatible('This tab requires a calibration bundle.', 'Calibration metrics are not available for this bundle type.')
    }
    if (!bundle.hasCalibration) {
      return missing('Calibration data is not present in this bundle.', 'The calibration tab needs grid candidates or a best candidate.')
    }
    return available('Calibration data available', 'Calibration candidates are present.')
  }

  if (tab === 'optimize') {
    if (bundle.isWorkspace) {
      return bundle.hasOptimization
        ? available('Optimisation data available', 'Parameter sweep rows are present in this workspace.')
        : missing('Optimisation data is not included in this workspace.', 'No optimisation child bundle contributed sweep rows to this workspace.')
    }
    if (bundle.type !== 'optimization') {
      return incompatible('This tab requires an optimisation bundle.', 'Optimisation metrics are not available for this bundle type.')
    }
    if (!bundle.hasOptimization) {
      return missing('Optimisation rows are not present in this bundle.', 'The optimisation tab needs parameter sweep rows.')
    }
    return available('Optimisation data available', 'Parameter sweep rows are present.')
  }

  if (tab === 'round2') {
    if (bundle.isWorkspace) {
      return bundle.hasRound2Rows
        ? available('Round 2 scenario data available', 'Round 2 scenario aggregates are present in this workspace.')
        : missing('Round 2 scenario data is not included in this workspace.', 'No Round 2 child bundle contributed scenario or winner rows to this workspace.')
    }
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
      if (bundle.isWorkspace) {
        return missing('Replay-style time-series data is not included in this workspace.', 'Add a replay child bundle to inspect per-tick data here.')
      }
      return incompatible('Replay-style time-series data is not present.', 'Load a replay bundle to inspect per-tick data.')
    }
    return available('Replay-style time-series data available', 'Per-tick rows are present.')
  }

  if (tab === 'compare') {
    if (bundle.isWorkspace) {
      return bundle.hasComparisonRows
        ? available('Comparison rows available', 'Precomputed comparison rows are present in this workspace.')
        : missing('Comparison data is not included in this workspace.', 'No comparison or scenario child bundle contributed comparison rows to this workspace.')
    }
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
