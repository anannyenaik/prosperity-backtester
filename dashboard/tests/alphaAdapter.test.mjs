import { after, test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { build } from 'esbuild'

const testDir = path.dirname(fileURLToPath(import.meta.url))
const dashboardRoot = path.resolve(testDir, '..')
const compiledModule = path.join(os.tmpdir(), `prosperity-alpha-${process.pid}-${Date.now()}.mjs`)

await build({
  entryPoints: [path.join(dashboardRoot, 'src', 'lib', 'alpha.ts')],
  bundle: true,
  format: 'esm',
  platform: 'node',
  outfile: compiledModule,
  logLevel: 'silent',
})

const { buildAlphaLabData } = await import(pathToFileURL(compiledModule).href)

after(() => {
  fs.rmSync(compiledModule, { force: true })
})

const products = ['ASH_COATED_OSMIUM', 'INTARIAN_PEPPER_ROOT']

function basePayload(type = 'replay') {
  return {
    type,
    meta: {
      schemaVersion: 3,
      runName: `${type}_fixture`,
      traderName: 'fixture_trader',
      mode: type,
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

function replayPayloadWithEvidence() {
  const fairValueSeries = []
  const fills = []
  const inventorySeries = []
  const pnlSeries = []
  for (const product of products) {
    const base = product === 'ASH_COATED_OSMIUM' ? 10000 : 12000
    for (let i = 0; i < 160; i++) {
      const residual = i % 4 < 2 ? 1.2 : -1.2
      const mid = base + i * 0.2
      fairValueSeries.push({
        day: 0,
        timestamp: i,
        product,
        analysis_fair: mid + residual,
        mid,
        microprice: mid + residual * 0.5,
        spread: 2,
      })
      inventorySeries.push({
        day: 0,
        timestamp: i,
        product,
        position: product === 'INTARIAN_PEPPER_ROOT' && i > 120 ? 68 : 8,
        avg_entry_price: base,
        mid,
        fair: mid + residual,
      })
      pnlSeries.push({
        day: 0,
        timestamp: i,
        product,
        cash: 0,
        realised: i,
        unrealised: i / 2,
        mtm: product === 'ASH_COATED_OSMIUM' ? 5000 + i : 10000 + i,
        mark: mid,
        mid,
        fair: mid + residual,
        spread: 2,
        position: product === 'INTARIAN_PEPPER_ROOT' && i > 120 ? 68 : 8,
      })
    }
    for (let i = 0; i < 20; i++) {
      fills.push({
        day: 0,
        timestamp: i,
        product,
        side: i % 2 ? 'sell' : 'buy',
        price: base,
        quantity: 2,
        kind: i % 2 ? 'passive_approx' : 'aggressive_visible',
        exact: i % 2 === 0,
        source_trade_price: base,
        mid: base,
        reference_fair: base,
        best_bid: base - 1,
        best_ask: base + 1,
        markout_1: 1,
        markout_5: 2,
        analysis_fair: base + 1,
        signed_edge_to_analysis_fair: 1,
      })
    }
  }
  return {
    ...basePayload('replay'),
    summary: {
      final_pnl: 15000,
      fill_count: fills.length,
      order_count: 100,
      limit_breaches: 0,
      max_drawdown: 100,
      final_positions: { ASH_COATED_OSMIUM: 8, INTARIAN_PEPPER_ROOT: 68 },
      per_product: {
        ASH_COATED_OSMIUM: { cash: 0, realised: 4000, unrealised: 1000, final_mtm: 5000, final_position: 8, avg_entry_price: 10000 },
        INTARIAN_PEPPER_ROOT: { cash: 0, realised: 7000, unrealised: 3000, final_mtm: 10000, final_position: 68, avg_entry_price: 12000 },
      },
      fair_value: {},
      behaviour: {},
    },
    fairValueSeries,
    fills,
    inventorySeries,
    pnlSeries,
    behaviour: {
      per_product: {
        ASH_COATED_OSMIUM: { cap_usage_ratio: 0.1, total_buy_qty: 20, total_sell_qty: 20, total_fills: 20, passive_fill_count: 10, aggressive_fill_count: 10, average_fill_markout_1: 1, average_fill_markout_5: 2, peak_abs_position: 8 },
        INTARIAN_PEPPER_ROOT: { cap_usage_ratio: 0.85, time_near_cap_ratio: 0.25, total_buy_qty: 30, total_sell_qty: 10, total_fills: 20, passive_fill_count: 10, aggressive_fill_count: 10, average_fill_markout_1: 1, average_fill_markout_5: 2, peak_abs_position: 68 },
      },
      summary: { dominant_risk_product: 'INTARIAN_PEPPER_ROOT', dominant_turnover_product: 'ASH_COATED_OSMIUM' },
    },
  }
}

function round2Payload() {
  const scenarioRows = [
    { scenario: 'no_access', trader: 'current', round: 2, final_pnl: 1000, gross_pnl_before_maf: 1000, maf_cost: 0, maf_bid: 0, contract_won: false, extra_access_enabled: false, expected_extra_quote_fraction: 0, max_drawdown: 20, fill_count: 10, limit_breaches: 0 },
    { scenario: 'access_base_maf_500', trader: 'current', round: 2, final_pnl: 1700, gross_pnl_before_maf: 2200, maf_cost: 500, maf_bid: 500, contract_won: true, extra_access_enabled: true, expected_extra_quote_fraction: 0.1875, marginal_access_pnl_before_maf: 1200, break_even_maf_vs_no_access: 1200, max_drawdown: 20, fill_count: 12, limit_breaches: 0, mc_mean: 1600, mc_p05: 900 },
  ]
  return {
    ...basePayload('round2_scenarios'),
    comparison: scenarioRows,
    round2: {
      scenarioRows,
      winnerRows: [{ scenario: 'access_base_maf_500', winner: 'current', winner_final_pnl: 1700, gap_to_second: null, ranking_changed_vs_no_access: false }],
      pairwiseRows: [],
      mafSensitivityRows: scenarioRows.slice(1),
      assumptionRegistry: { grounded: [], configurable: [], unknown: [] },
    },
  }
}

test('builds classified hypotheses from replay evidence without fake missing zeros', () => {
  const alpha = buildAlphaLabData(replayPayloadWithEvidence())
  assert.ok(alpha.hypotheses.length > 0)
  assert.ok(alpha.hypotheses.some((item) => item.classification === 'local_bt'))
  assert.ok(alpha.hypotheses.some((item) => item.classification === 'public_data' || item.classification === 'weak_rejected'))
  assert.equal(alpha.mafPanel.available, false)
  assert.match(alpha.missingMessages.join('\n'), /Replay-compatible fair-value rows|Fill rows|^$/)
})

test('keeps MAF access hypotheses website-only', () => {
  const alpha = buildAlphaLabData(round2Payload())
  const maf = alpha.hypotheses.find((item) => item.id === 'maf-access-sensitivity')
  assert.ok(maf)
  assert.equal(maf.classification, 'website_only')
  assert.equal(alpha.mafPanel.available, true)
  assert.equal(alpha.mafPanel.rows[0].break_even_maf, 1200)
})
