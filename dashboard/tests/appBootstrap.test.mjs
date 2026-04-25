import { after, test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import React from 'react'
import TestRenderer from 'react-test-renderer'
import { build } from 'esbuild'

const { act, create } = TestRenderer

const testDir = path.dirname(fileURLToPath(import.meta.url))
const dashboardRoot = path.resolve(testDir, '..')
const stamp = `${process.pid}-${Date.now()}`
const bridgeModule = path.join(dashboardRoot, `.tmp-app-bootstrap-entry-${stamp}.mjs`)
const compiledModule = path.join(dashboardRoot, `.tmp-app-bootstrap-${stamp}.mjs`)

fs.writeFileSync(
  bridgeModule,
  [
    "export { App } from './src/App.tsx'",
    "export { useStore } from './src/store.ts'",
  ].join('\n'),
)

await build({
  entryPoints: [bridgeModule],
  bundle: true,
  format: 'esm',
  platform: 'node',
  outfile: compiledModule,
  external: ['react', 'react/jsx-runtime', 'react-dom', 'react-test-renderer', 'zustand', 'clsx', 'lucide-react', 'recharts'],
  logLevel: 'silent',
})

const { App, useStore } = await import(pathToFileURL(compiledModule).href)

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

function mockFetch(routes) {
  const originalFetch = globalThis.fetch
  const calls = []

  globalThis.fetch = async (input) => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url

    calls.push(url)
    const route = routes[url]
    if (!route) {
      throw new Error(`Unexpected fetch request: ${url}`)
    }

    return {
      ok: route.ok ?? true,
      status: route.status ?? 200,
      async json() {
        return typeof route.json === 'function' ? route.json() : route.json
      },
    }
  }

  return {
    calls,
    restore() {
      if (originalFetch) {
        globalThis.fetch = originalFetch
      } else {
        delete globalThis.fetch
      }
    },
  }
}

function mockWindow(search = '') {
  const originalWindow = globalThis.window
  const location = {
    pathname: '/dashboard',
    search,
    hash: '',
  }
  const historyCalls = []
  const listeners = new Map()
  const windowMock = {
    location,
    history: {
      state: null,
      replaceState(state, _title, url) {
        this.state = state
        const next = new URL(String(url), 'http://dashboard.test')
        location.pathname = next.pathname
        location.search = next.search
        location.hash = next.hash
        historyCalls.push(String(url))
      },
    },
    addEventListener(type, handler) {
      listeners.set(type, handler)
    },
    removeEventListener(type) {
      listeners.delete(type)
    },
  }

  globalThis.window = windowMock

  return {
    historyCalls,
    restore() {
      if (originalWindow) {
        globalThis.window = originalWindow
      } else {
        delete globalThis.window
      }
    },
  }
}

function payload(type = 'replay') {
  return {
    type,
    meta: {
      schemaVersion: 3,
      runName: 'bootstrap replay',
      traderName: 'fixture_trader',
      mode: type,
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
  }
}

function runMeta() {
  return {
    path: 'backtests/2026-04-23_20-15-00_replay/dashboard.json',
    name: '2026-04-23 replay',
    type: 'replay',
    createdAt: '2026-04-23T20:15:00Z',
    finalPnl: 12.5,
    sizeBytes: 12_345,
  }
}

function workspaceRunMeta() {
  return {
    path: 'backtests/2026-04-24_09-00-00_workspace/dashboard.json',
    name: '2026-04-24 workspace',
    type: 'workspace',
    createdAt: '2026-04-24T09:00:00Z',
    finalPnl: null,
    sizeBytes: 54_321,
    workspaceSourceCount: 3,
  }
}

function textOfNode(node) {
  return node.children
    .map((child) => (typeof child === 'string' ? child : textOfNode(child)))
    .join('')
}

function findButton(root, label) {
  const match = root.findAll(
    (node) =>
      node.type === 'button' &&
      (textOfNode(node).includes(label) || node.props['aria-label'] === label),
  )[0]
  assert.ok(match, `Expected to find button with label containing "${label}"`)
  return match
}

async function flushAsyncWork() {
  for (let i = 0; i < 6; i += 1) {
    await Promise.resolve()
  }
}

test('manually closing the last bootstrap-loaded run returns to landing without reloading it', async (t) => {
  resetStore()
  const windowMock = mockWindow('?latest=1')
  const fetchMock = mockFetch({
    '/api/runs': {
      json: [runMeta()],
    },
    '/api/run/backtests%2F2026-04-23_20-15-00_replay%2Fdashboard.json': {
      json: payload(),
    },
  })

  t.after(() => {
    fetchMock.restore()
    windowMock.restore()
    resetStore()
  })

  let renderer
  await act(async () => {
    renderer = create(React.createElement(App))
    await flushAsyncWork()
  })

  assert.deepEqual(fetchMock.calls, [
    '/api/runs',
    '/api/run/backtests%2F2026-04-23_20-15-00_replay%2Fdashboard.json',
  ])
  assert.equal(globalThis.window.location.search, '')
  assert.equal(useStore.getState().runs.length, 1)
  assert.deepEqual(windowMock.historyCalls, ['/dashboard'])

  await act(async () => {
    findButton(renderer.root, 'Close bootstrap replay').props.onClick({ stopPropagation() {} })
    await flushAsyncWork()
  })

  assert.equal(useStore.getState().runs.length, 0)
  assert.equal(globalThis.window.location.search, '')
  assert.deepEqual(fetchMock.calls, [
    '/api/runs',
    '/api/run/backtests%2F2026-04-23_20-15-00_replay%2Fdashboard.json',
  ])
  assert.match(JSON.stringify(renderer.toJSON()), /Bundle intake/)
})

test('bootstrap latestType=workspace opens the latest workspace bundle', async (t) => {
  resetStore()
  const windowMock = mockWindow('?latest=1&latestType=workspace')
  const fetchMock = mockFetch({
    '/api/runs': {
      json: [workspaceRunMeta(), runMeta()],
    },
    '/api/run/backtests%2F2026-04-24_09-00-00_workspace%2Fdashboard.json': {
      json: payload('workspace'),
    },
  })

  t.after(() => {
    fetchMock.restore()
    windowMock.restore()
    resetStore()
  })

  await act(async () => {
    create(React.createElement(App))
    await flushAsyncWork()
  })

  assert.deepEqual(fetchMock.calls, [
    '/api/runs',
    '/api/run/backtests%2F2026-04-24_09-00-00_workspace%2Fdashboard.json',
  ])
  assert.equal(useStore.getState().runs.length, 1)
  assert.equal(useStore.getState().getActiveRun().payload.type, 'workspace')
  assert.equal(globalThis.window.location.search, '')
})

test('landing main uses a viewport-bounded shell under the measured nav', async (t) => {
  resetStore()
  const windowMock = mockWindow()

  t.after(() => {
    windowMock.restore()
    resetStore()
  })

  let renderer
  await act(async () => {
    renderer = create(React.createElement(App))
    await flushAsyncWork()
  })

  const shell = renderer.root.find(
    (node) => node.type === 'div' && node.props['data-layout-shell'] === 'landing',
  )
  const main = renderer.root.findByType('main')
  assert.deepEqual(shell.props.style, {
    height: '100dvh',
    overflow: 'hidden',
  })
  assert.equal(main.props['data-page-state'], 'landing')
  assert.deepEqual(main.props.style, {
    boxSizing: 'border-box',
    height: '100dvh',
    overflow: 'hidden',
    paddingTop: 'var(--dashboard-nav-height, 156px)',
  })
})

test('loaded main keeps the scrollable padded layout', async (t) => {
  resetStore()
  const windowMock = mockWindow()

  useStore.getState().loadRun(payload(), 'fixture.json')

  t.after(() => {
    windowMock.restore()
    resetStore()
  })

  let renderer
  await act(async () => {
    renderer = create(React.createElement(App))
    await flushAsyncWork()
  })

  const shell = renderer.root.find(
    (node) => node.type === 'div' && node.props['data-layout-shell'] === 'loaded',
  )
  const main = renderer.root.findByType('main')
  assert.equal(shell.props.style, undefined)
  assert.equal(main.props['data-page-state'], 'loaded')
  assert.deepEqual(main.props.style, {
    paddingTop: 'calc(var(--dashboard-nav-height, 156px) + 16px)',
    minHeight: 'calc(100dvh - (var(--dashboard-nav-height, 156px) + 16px))',
  })
})
