import { after, test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { build } from 'esbuild'

const testDir = path.dirname(fileURLToPath(import.meta.url))
const dashboardRoot = path.resolve(testDir, '..')
const stamp = `${process.pid}-${Date.now()}`
const bridgeModule = path.join(dashboardRoot, `.tmp-workspace-store-entry-${stamp}.mjs`)
const compiledModule = path.join(dashboardRoot, `.tmp-workspace-store-${stamp}.mjs`)

fs.writeFileSync(
  bridgeModule,
  "export { useStore } from './src/store.ts'\n",
)

await build({
  entryPoints: [bridgeModule],
  bundle: true,
  format: 'esm',
  platform: 'node',
  outfile: compiledModule,
  external: ['zustand'],
  logLevel: 'silent',
})

const { useStore } = await import(pathToFileURL(compiledModule).href)

after(() => {
  fs.rmSync(bridgeModule, { force: true })
  fs.rmSync(compiledModule, { force: true })
})

function resetStore() {
  useStore.setState({
    runs: [],
    activeRunId: null,
    compareRunId: null,
    activeTab: 'overview',
    activeProduct: 'ASH_COATED_OSMIUM',
    sampleRunName: null,
    timeWindow: 'all',
    serverRuns: [],
  })
}

function workspacePayload() {
  return {
    type: 'workspace',
    meta: {
      schemaVersion: 3,
      runName: 'integrated workspace',
      traderName: 'workspace',
      mode: 'workspace',
      round: 2,
      createdAt: '2026-04-24T10:00:00Z',
      fillModel: { name: 'workspace' },
      perturbations: {},
      accessScenario: {},
      outputProfile: { profile: 'workspace' },
    },
    products: ['ASH_COATED_OSMIUM', 'INTARIAN_PEPPER_ROOT'],
    assumptions: { exact: [], approximate: [] },
    datasetReports: [],
    validation: {},
    comparison: [
      { trader: 'optimised', final_pnl: 100, gross_pnl_before_maf: 100, maf_cost: 0, max_drawdown: 5, fill_count: 10, order_count: 12, limit_breaches: 0 },
    ],
    comparisonDiagnostics: {
      row_count: 1,
      winner: 'optimised',
      winner_final_pnl: 100,
      scenario_count: 1,
      maf_sensitive_rows: 0,
    },
    workspace: {
      name: 'integrated workspace',
      createdAt: '2026-04-24T10:00:00Z',
      sources: [
        {
          path: 'review/compare/dashboard.json',
          name: 'compare source',
          type: 'comparison',
          sections: ['compare', 'alpha'],
          promotedSections: ['compare', 'alpha'],
        },
      ],
      sections: {
        present: ['overview', 'compare', 'alpha'],
        missing: ['replay', 'montecarlo', 'calibration', 'optimize', 'round2', 'inspect', 'osmium', 'pepper'],
      },
      integrity: {
        status: 'partial',
        promotedBy: {
          compare: 'review/compare/dashboard.json',
          alpha: 'review/compare/dashboard.json',
        },
        shadowedBy: {},
        warnings: [],
      },
    },
  }
}

test('loading one workspace bundle into the store keeps workspace metadata intact', () => {
  resetStore()
  useStore.getState().loadRun(workspacePayload(), 'dashboard.json')

  const activeRun = useStore.getState().getActiveRun()
  assert.ok(activeRun)
  assert.equal(useStore.getState().runs.length, 1)
  assert.equal(activeRun.name, 'integrated workspace')
  assert.equal(activeRun.payload.type, 'workspace')
  assert.equal(activeRun.payload.workspace.name, 'integrated workspace')
  assert.deepEqual(activeRun.payload.workspace.sections.present, ['overview', 'compare', 'alpha'])
})
