const BOOTSTRAP_QUERY_KEYS = ['run', 'latest', 'latestType'] as const

export interface BootstrapRequest {
  requestedRun: string | null
  latestType: string | null
}

export function readBootstrapRequest(search: string): BootstrapRequest | null {
  const params = new URLSearchParams(search)
  const requestedRun = params.get('run')
  const loadLatest = params.get('latest') === '1'
  const latestType = normaliseBootstrapRunType(params.get('latestType'))

  if (!requestedRun && !loadLatest && !latestType) {
    return null
  }

  return {
    requestedRun,
    latestType,
  }
}

export function clearBootstrapQueryParams(
  locationLike = typeof window !== 'undefined' ? window.location : null,
  historyLike = typeof window !== 'undefined' ? window.history : null,
): boolean {
  if (!locationLike || !historyLike) {
    return false
  }

  const params = new URLSearchParams(locationLike.search)
  const hadBootstrapParams = BOOTSTRAP_QUERY_KEYS.some((key) => params.has(key))
  if (!hadBootstrapParams) {
    return false
  }

  for (const key of BOOTSTRAP_QUERY_KEYS) {
    params.delete(key)
  }

  const nextSearch = params.toString()
  const nextUrl = `${locationLike.pathname}${nextSearch ? `?${nextSearch}` : ''}${locationLike.hash ?? ''}`
  historyLike.replaceState(historyLike.state ?? null, '', nextUrl)
  return true
}

export function normaliseBootstrapRunType(value: string | null): string | null {
  if (!value) return null
  return {
    replay: 'replay',
    mc: 'monte_carlo',
    montecarlo: 'monte_carlo',
    'monte-carlo': 'monte_carlo',
    monte_carlo: 'monte_carlo',
    compare: 'comparison',
    comparison: 'comparison',
    calibrate: 'calibration',
    calibration: 'calibration',
    optimize: 'optimization',
    optimise: 'optimization',
    optimization: 'optimization',
    optimisation: 'optimization',
    round2: 'round2_scenarios',
    'round2-scenarios': 'round2_scenarios',
    round2_scenarios: 'round2_scenarios',
    'scenario-compare': 'scenario_compare',
    scenario_compare: 'scenario_compare',
  }[value.toLowerCase()] ?? null
}
