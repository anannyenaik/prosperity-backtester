import { after, test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { build } from 'esbuild'

const testDir = path.dirname(fileURLToPath(import.meta.url))
const dashboardRoot = path.resolve(testDir, '..')
const compiledModule = path.join(os.tmpdir(), `prosperity-bundles-${process.pid}-${Date.now()}.mjs`)

await build({
  entryPoints: [path.join(dashboardRoot, 'src', 'lib', 'bundles.ts')],
  bundle: true,
  format: 'esm',
  platform: 'node',
  outfile: compiledModule,
  logLevel: 'silent',
})

const {
  detectBundleType,
  getComparisonRows,
  getTabAvailability,
  interpretBundle,
  normaliseDashboardPayload,
  numberOrNull,
} = await import(pathToFileURL(compiledModule).href)

after(() => {
  fs.rmSync(compiledModule, { force: true })
})

const products = ['ASH_COATED_OSMIUM', 'INTARIAN_PEPPER_ROOT']

function basePayload(type, mode = type) {
  return {
    type,
    meta: {
      schemaVersion: 3,
      runName: `${type}_fixture`,
      traderName: 'fixture_trader',
      mode,
      round: 2,
      fillModel: { name: 'base' },
      perturbations: {},
      accessScenario: {},
      createdAt: '2026-04-20T00:00:00Z',
    },
    products,
    assumptions: { exact: [], approximate: [] },
    datasetReports: [],
    validation: {},
  }
}

function replayPayload() {
  return {
    ...basePayload('replay'),
    summary: {
      final_pnl: 123,
      fill_count: 2,
      order_count: 3,
      limit_breaches: 0,
      max_drawdown: 4,
      final_positions: { ASH_COATED_OSMIUM: 1, INTARIAN_PEPPER_ROOT: 0 },
      per_product: {
        ASH_COATED_OSMIUM: { cash: 0, realised: 10, unrealised: 2, final_mtm: 12, final_position: 1, avg_entry_price: 10000 },
      },
      fair_value: {},
      behaviour: {},
    },
    pnlSeries: [{ day: 0, timestamp: 100, product: 'ASH_COATED_OSMIUM', cash: 0, realised: 10, unrealised: 2, mtm: 12, mark: 1, mid: 1, fair: 1, spread: 1, position: 1 }],
    inventorySeries: [{ day: 0, timestamp: 100, product: 'ASH_COATED_OSMIUM', position: 1, avg_entry_price: 10000, mid: 1, fair: 1 }],
    fairValueSeries: [{ day: 0, timestamp: 100, product: 'ASH_COATED_OSMIUM', analysis_fair: 1, mid: 1 }],
    fills: [{ day: 0, timestamp: 100, product: 'ASH_COATED_OSMIUM', side: 'buy', price: 1, quantity: 1, kind: 'aggressive_visible', exact: true, source_trade_price: 1, mid: 1, reference_fair: 1, best_bid: 1, best_ask: 2, markout_1: 1, markout_5: 1, analysis_fair: 1, signed_edge_to_analysis_fair: 1 }],
  }
}

function monteCarloPayload() {
  return {
    ...basePayload('monte_carlo'),
    monteCarlo: {
      summary: {
        session_count: 32,
        mean: 10,
        std: 2,
        p05: -5,
        p50: 11,
        p95: 18,
        expected_shortfall_05: -8,
        min: -9,
        max: 22,
        positive_rate: 0.7,
        mean_max_drawdown: 3,
        max_limit_breaches: 0,
        per_product: {},
      },
      sessions: [{ run_name: 'mc_001', trader_name: 'fixture_trader', mode: 'monte_carlo', final_pnl: 10, fill_count: 1, limit_breaches: 0, days: [0], per_product: {}, fill_model: {}, perturbations: {}, fair_value_summary: {}, behaviour_summary: {} }],
      sampleRuns: [],
      fairValueBands: { analysisFair: {}, mid: {} },
    },
  }
}

function comparisonPayload() {
  return {
    ...basePayload('comparison', 'replay'),
    comparison: [
      { trader: 'plus_offset110', final_pnl: 247719, gross_pnl_before_maf: 247719, maf_cost: 0, max_drawdown: 100, fill_count: 625, order_count: 89926, limit_breaches: 0, pepper_cap_usage: 1, pepper_markout_5: -3.7 },
      { trader: 'r2_algo_v2', final_pnl: 243779, gross_pnl_before_maf: 243779, maf_cost: 0, max_drawdown: 110, fill_count: 163, order_count: 91768, limit_breaches: 0, pepper_cap_usage: 1, pepper_markout_5: -4.1 },
    ],
    comparisonDiagnostics: {
      row_count: 2,
      winner: 'plus_offset110',
      winner_final_pnl: 247719,
      gap_to_second: 3940,
      scenario_count: 1,
      maf_sensitive_rows: 0,
    },
  }
}

function round2Payload() {
  const scenarioRows = [
    { scenario: 'access_base_maf_0', trader: 'plus_offset110', round: 2, final_pnl: 248278, gross_pnl_before_maf: 248278, maf_cost: 0, maf_bid: 0, contract_won: true, extra_access_enabled: true, expected_extra_quote_fraction: 0.1875, marginal_access_pnl_before_maf: 559, break_even_maf_vs_no_access: 559, max_drawdown: 100, fill_count: 627, limit_breaches: 0 },
  ]
  return {
    ...basePayload('round2_scenarios', 'replay+monte_carlo'),
    comparison: scenarioRows,
    round2: {
      scenarioRows,
      winnerRows: [{ scenario: 'access_base_maf_0', winner: 'plus_offset110', winner_final_pnl: 248278, gap_to_second: null, ranking_changed_vs_no_access: false }],
      pairwiseRows: [],
      mafSensitivityRows: scenarioRows,
      assumptionRegistry: { grounded: [], configurable: [], unknown: [] },
    },
    comparisonDiagnostics: { row_count: 1, winner: 'plus_offset110', winner_final_pnl: 248278, scenario_count: 1, maf_sensitive_rows: 0 },
  }
}

test('detects each supported bundle type from explicit metadata', () => {
  assert.equal(detectBundleType(replayPayload()), 'replay')
  assert.equal(detectBundleType(monteCarloPayload()), 'monte_carlo')
  assert.equal(detectBundleType(comparisonPayload()), 'comparison')
  assert.equal(detectBundleType(round2Payload()), 'round2_scenarios')
  assert.equal(detectBundleType({ ...basePayload('calibration'), calibration: { grid: [{ score: 1 }], best: { score: 1 }, diagnostics: { candidate_count: 1 } } }), 'calibration')
  assert.equal(detectBundleType({ ...basePayload('optimisation'), optimization: { rows: [{ variant: 'a', score: 1 }], diagnostics: { variant_count: 1 } } }), 'optimization')
})

test('replay bundle supports replay tabs and blocks Monte Carlo without fake zeros', () => {
  const replay = replayPayload()
  assert.equal(getTabAvailability(replay, 'replay').supported, true)
  assert.equal(getTabAvailability(replay, 'alpha').supported, true)
  const mcAvailability = getTabAvailability(replay, 'montecarlo')
  assert.equal(mcAvailability.supported, false)
  assert.match(mcAvailability.message, /not available for this bundle type/)
  assert.doesNotMatch(mcAvailability.message, /0(?:\.00)?/)
})

test('Monte Carlo bundle supports MC tab and does not pretend replay data exists', () => {
  const mc = monteCarloPayload()
  assert.equal(getTabAvailability(mc, 'montecarlo').supported, true)
  assert.equal(getTabAvailability(mc, 'alpha').supported, true)
  assert.equal(interpretBundle(mc).hasReplaySummary, false)
  const replayAvailability = getTabAvailability(mc, 'replay')
  assert.equal(replayAvailability.supported, false)
  assert.match(replayAvailability.title, /requires a replay bundle/)
})

test('Round 2 scenario bundle supports Round 2 and compatible comparison diagnostics only', () => {
  const scenario = round2Payload()
  assert.equal(getTabAvailability(scenario, 'round2').supported, true)
  assert.equal(getTabAvailability(scenario, 'alpha').supported, true)
  assert.equal(getTabAvailability(scenario, 'compare').supported, true)
  assert.equal(getTabAvailability(scenario, 'inspect').supported, false)
  assert.match(getTabAvailability(scenario, 'inspect').message, /Load a replay bundle/)
})

test('comparison bundle exposes real comparison rows instead of self-vs-self zeros', () => {
  const comparison = comparisonPayload()
  const rows = getComparisonRows(comparison)
  assert.equal(getTabAvailability(comparison, 'compare').supported, true)
  assert.equal(rows.length, 2)
  assert.equal(rows[0].trader, 'plus_offset110')
  assert.equal(rows[0].final_pnl, 247719)
})

test('ad hoc comparison requires two distinct replay summaries', () => {
  const replay = replayPayload()
  const same = getTabAvailability(replay, 'compare', { comparePayload: replay, sameCompareRun: true })
  assert.equal(same.supported, false)
  assert.match(same.title, /different comparison run/)

  const otherReplay = replayPayload()
  otherReplay.meta.runName = 'other_replay'
  otherReplay.summary.final_pnl = 321
  assert.equal(getTabAvailability(replay, 'compare', { comparePayload: otherReplay }).supported, true)
})

test('missing numeric values stay missing rather than becoming zero', () => {
  assert.equal(numberOrNull(undefined), null)
  assert.equal(numberOrNull(null), null)
  assert.equal(numberOrNull(0), 0)
})

test('normalises compact row-table sections on load', () => {
  const payload = monteCarloPayload()
  payload.monteCarlo.sessions = {
    encoding: 'row_table_v1',
    columns: ['run_name', 'final_pnl', 'fill_count', 'limit_breaches'],
    rows: [['mc_001', 10, 1, 0]],
  }
  payload.monteCarlo.sampleRuns = [{
    runName: 'mc_001',
    summary: { final_pnl: 10, fill_count: 1, order_count: 1, limit_breaches: 0, max_drawdown: 1, final_positions: {}, per_product: {}, fair_value: {}, behaviour: {} },
    inventorySeries: {
      encoding: 'row_table_v1',
      columns: ['day', 'timestamp', 'product', 'position', 'avg_entry_price', 'mid', 'fair'],
      rows: [[0, 100, 'ASH_COATED_OSMIUM', 1, 10000, 10000, 10000]],
    },
    pnlSeries: [],
    fills: [],
    orderIntent: [],
    fairValueSeries: [],
    behaviour: { per_product: {}, summary: {} },
    behaviourSeries: [],
  }]

  const normalised = normaliseDashboardPayload(payload)

  assert.equal(Array.isArray(normalised.monteCarlo.sessions), true)
  assert.equal(normalised.monteCarlo.sessions[0].run_name, 'mc_001')
  assert.equal(Array.isArray(normalised.monteCarlo.sampleRuns[0].inventorySeries), true)
  assert.equal(normalised.monteCarlo.sampleRuns[0].inventorySeries[0].product, 'ASH_COATED_OSMIUM')
})
