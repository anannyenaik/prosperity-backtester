import { after, test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import React from 'react'
import TestRenderer from 'react-test-renderer'
import { build } from 'esbuild'

const { create } = TestRenderer

const testDir = path.dirname(fileURLToPath(import.meta.url))
const dashboardRoot = path.resolve(testDir, '..')
const stamp = `${process.pid}-${Date.now()}`
const bridgeModule = path.join(dashboardRoot, `.tmp-nav-bar-entry-${stamp}.mjs`)
const compiledModule = path.join(dashboardRoot, `.tmp-nav-bar-${stamp}.mjs`)

fs.writeFileSync(
  bridgeModule,
  [
    "export { NavBar } from './src/components/NavBar.tsx'",
    "export { useStore } from './src/store.ts'",
  ].join('\n'),
)

await build({
  entryPoints: [bridgeModule],
  bundle: true,
  format: 'esm',
  platform: 'node',
  outfile: compiledModule,
  external: ['react', 'react/jsx-runtime', 'react-test-renderer', 'zustand', 'clsx', 'lucide-react'],
  logLevel: 'silent',
})

const { NavBar, useStore } = await import(pathToFileURL(compiledModule).href)

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

function replayPayload() {
  return {
    type: 'replay',
    meta: {
      schemaVersion: 3,
      runName: 'nav replay',
      traderName: 'fixture_trader',
      mode: 'replay',
      round: 2,
      createdAt: '2026-04-23T20:15:00Z',
      fillModel: { name: 'base' },
      perturbations: {},
      accessScenario: {},
    },
    products: ['ASH_COATED_OSMIUM', 'INTARIAN_PEPPER_ROOT'],
    assumptions: { exact: [], approximate: [] },
    datasetReports: [],
    validation: {},
    summary: {
      final_pnl: 10,
      fill_count: 1,
      order_count: 1,
      limit_breaches: 0,
      max_drawdown: 1,
      final_positions: { ASH_COATED_OSMIUM: 0, INTARIAN_PEPPER_ROOT: 0 },
      per_product: {},
      fair_value: {},
      behaviour: {},
    },
    pnlSeries: [{ day: 0, timestamp: 1, product: 'ASH_COATED_OSMIUM', cash: 0, realised: 0, unrealised: 0, mtm: 0, mark: 1, mid: 1, fair: 1, spread: 1, position: 0 }],
  }
}

function round2Payload() {
  return {
    type: 'round2_scenarios',
    meta: {
      schemaVersion: 3,
      runName: 'nav round2',
      traderName: 'fixture_trader',
      mode: 'round2_scenarios',
      round: 2,
      createdAt: '2026-04-23T20:15:00Z',
      fillModel: { name: 'base' },
      perturbations: {},
      accessScenario: {},
    },
    products: ['ASH_COATED_OSMIUM', 'INTARIAN_PEPPER_ROOT'],
    assumptions: { exact: [], approximate: [] },
    datasetReports: [],
    validation: {},
    round2: {
      scenarioRows: [{ maf: 0, winner: 'candidate' }],
      winnerRows: [{ product: 'ASH_COATED_OSMIUM', winner: 'candidate' }],
    },
  }
}

function textOfNode(node) {
  return node.children
    .map((child) => (typeof child === 'string' ? child : textOfNode(child)))
    .join('')
}

function findNavButton(root, label) {
  const match = root.findAll(
    (node) =>
      node.type === 'button' &&
      typeof node.props.className === 'string' &&
      node.props.className.includes('nav-item') &&
      textOfNode(node).includes(label),
  )[0]
  assert.ok(match, `Expected to find nav button with label containing "${label}"`)
  return match
}

test('Alpha Lab and Round 2 render at the end of the navigation list', () => {
  resetStore()
  const renderer = create(React.createElement(NavBar))
  const navButtons = renderer.root.findAll(
    (node) =>
      node.type === 'button' &&
      typeof node.props.className === 'string' &&
      node.props.className.includes('nav-item'),
  )
  const labels = navButtons.map((node) => textOfNode(node))

  assert.match(labels.at(-2), /Alpha Lab/)
  assert.match(labels.at(-1), /Round 2/)
})

test('unsupported tabs stay visible but render as disabled with no active affordance', () => {
  resetStore()
  useStore.getState().loadRun(replayPayload(), 'nav-replay.json')
  useStore.setState({ activeTab: 'round2' })

  const renderer = create(React.createElement(NavBar))
  const round2Button = findNavButton(renderer.root, 'Round 2')
  const replayButton = findNavButton(renderer.root, 'Replay')

  assert.equal(round2Button.props.disabled, true)
  assert.equal(round2Button.props['aria-disabled'], true)
  assert.equal(round2Button.props.onClick, undefined)
  assert.match(round2Button.props.className, /nav-item--disabled/)
  assert.doesNotMatch(round2Button.props.className, /nav-item--active/)

  assert.equal(replayButton.props.disabled, false)
  assert.equal(typeof replayButton.props.onClick, 'function')
})

test('supported Alpha Lab and Round 2 tabs use the available nav treatment', () => {
  resetStore()
  useStore.getState().loadRun(round2Payload(), 'nav-round2.json')

  const renderer = create(React.createElement(NavBar))
  const alphaButton = findNavButton(renderer.root, 'Alpha Lab')
  const round2Button = findNavButton(renderer.root, 'Round 2')

  for (const button of [alphaButton, round2Button]) {
    assert.equal(button.props.disabled, false)
    assert.equal(button.props['aria-disabled'], undefined)
    assert.match(button.props.className, /nav-item--available/)
    assert.doesNotMatch(button.props.className, /nav-item--disabled/)
  }
})
