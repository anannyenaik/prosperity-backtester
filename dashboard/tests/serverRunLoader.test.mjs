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
const compiledModule = path.join(dashboardRoot, `.tmp-server-run-loader-${process.pid}-${Date.now()}.mjs`)

await build({
  entryPoints: [path.join(dashboardRoot, 'src', 'components', 'ServerRunLoader.tsx')],
  bundle: true,
  format: 'esm',
  platform: 'node',
  outfile: compiledModule,
  external: ['react', 'react/jsx-runtime', 'react-test-renderer', 'zustand', 'clsx', 'lucide-react'],
  logLevel: 'silent',
})

const { ServerRunLoader } = await import(pathToFileURL(compiledModule).href)

after(() => {
  fs.rmSync(compiledModule, { force: true })
})

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
    if (route instanceof Error) {
      throw route
    }
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

function runMeta(overrides = {}) {
  return {
    path: 'backtests/2026-04-23_20-15-00_replay/dashboard.json',
    name: '2026-04-23 replay',
    type: 'replay',
    createdAt: '2026-04-23T20:15:00Z',
    finalPnl: 12.5,
    sizeBytes: 12_345,
    ...overrides,
  }
}

function payload(type = 'replay') {
  return {
    type,
    meta: {
      schemaVersion: 3,
      runName: `${type}_fixture`,
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

function textOfNode(node) {
  return node.children
    .map((child) => (typeof child === 'string' ? child : textOfNode(child)))
    .join('')
}

function findButton(root, label) {
  const match = root.findAll((node) => node.type === 'button' && textOfNode(node).includes(label))[0]
  assert.ok(match, `Expected to find button with label containing "${label}"`)
  return match
}

test('browse local server opens a floating overlay instead of an in-flow panel', async (t) => {
  const fetchMock = mockFetch({
    '/api/runs': {
      json: [
        runMeta(),
        runMeta({
          path: 'backtests/2026-04-23_20-10-00_comparison/dashboard.json',
          name: '2026-04-23 compare',
          type: 'comparison',
        }),
      ],
    },
  })
  t.after(() => fetchMock.restore())

  let renderer
  await act(async () => {
    renderer = create(React.createElement(ServerRunLoader))
  })

  await act(async () => {
    await findButton(renderer.root, 'Browse local server').props.onClick()
  })

  const floatingRoots = renderer.root.findAll(
    (node) =>
      typeof node.props.className === 'string' &&
      node.props.className.includes('absolute left-0 right-0 top-full z-30 mt-3 pointer-events-none'),
  )

  assert.equal(floatingRoots.length, 1)
  assert.match(JSON.stringify(renderer.toJSON()), /Bundle browser/)
  assert.match(JSON.stringify(renderer.toJSON()), /Available bundles/)
})

test('missing quick-loads show an explicit unavailable notice instead of failing silently', async (t) => {
  const fetchMock = mockFetch({
    '/api/runs': {
      json: [
        runMeta(),
        runMeta({
          path: 'backtests/2026-04-23_20-10-00_calibration/dashboard.json',
          name: '2026-04-23 calibration',
          type: 'calibration',
        }),
      ],
    },
  })
  t.after(() => fetchMock.restore())

  let renderer
  await act(async () => {
    renderer = create(React.createElement(ServerRunLoader))
  })

  await act(async () => {
    await findButton(renderer.root, 'Latest MC').props.onClick()
  })

  const rendered = JSON.stringify(renderer.toJSON())
  assert.match(rendered, /Quick load unavailable/)
  assert.match(rendered, /Monte Carlo bundle unavailable/)
  assert.match(rendered, /No monte carlo bundle is currently available on the local server\./i)
  assert.doesNotMatch(rendered, /Available bundles/)
})

test('matching quick-loads still fetch and load the selected bundle', async (t) => {
  const compareRun = runMeta({
    path: 'backtests/2026-04-23_20-05-00_compare/dashboard.json',
    name: '2026-04-23 compare',
    type: 'comparison',
  })
  const fetchMock = mockFetch({
    '/api/runs': {
      json: [runMeta(), compareRun],
    },
    '/api/run/backtests%2F2026-04-23_20-05-00_compare%2Fdashboard.json': {
      json: payload('comparison'),
    },
  })
  t.after(() => fetchMock.restore())

  let renderer
  await act(async () => {
    renderer = create(React.createElement(ServerRunLoader))
  })

  await act(async () => {
    await findButton(renderer.root, 'Latest compare').props.onClick()
  })

  assert.deepEqual(fetchMock.calls, [
    '/api/runs',
    '/api/run/backtests%2F2026-04-23_20-05-00_compare%2Fdashboard.json',
  ])
})
