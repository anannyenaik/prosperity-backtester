import { after, test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { build } from 'esbuild'

const testDir = path.dirname(fileURLToPath(import.meta.url))
const dashboardRoot = path.resolve(testDir, '..')
const stamp = `${process.pid}-${Date.now()}`
const bridgeModule = path.join(dashboardRoot, `.tmp-landing-interactions-entry-${stamp}.mjs`)
const compiledModule = path.join(dashboardRoot, `.tmp-landing-interactions-${stamp}.mjs`)

fs.writeFileSync(
  bridgeModule,
  [
    "export { computeFloatingLayerLayout } from './src/lib/floatingLayer.ts'",
    "export { measureViewportScrollbars, isPointNearViewportScrollbar, measureElementScrollbars, getElementScrollbarAxis } from './src/lib/cursor.ts'",
  ].join('\n'),
)

await build({
  entryPoints: [bridgeModule],
  bundle: true,
  format: 'esm',
  platform: 'node',
  outfile: compiledModule,
  logLevel: 'silent',
})

const {
  computeFloatingLayerLayout,
  measureViewportScrollbars,
  isPointNearViewportScrollbar,
  measureElementScrollbars,
  getElementScrollbarAxis,
} = await import(pathToFileURL(compiledModule).href)

after(() => {
  fs.rmSync(bridgeModule, { force: true })
  fs.rmSync(compiledModule, { force: true })
})

test('floating browser layers stay below the anchor when there is room', () => {
  const layout = computeFloatingLayerLayout(
    { left: 960, top: 180, width: 420, height: 180 },
    { width: 1440, height: 900 },
  )

  assert.equal(layout.placement, 'below')
  assert.equal(layout.top, 374)
  assert.equal(layout.width, 420)
  assert.ok(layout.maxHeight >= 240)
})

test('floating browser layers flip above the anchor when opening below would fall off-screen', () => {
  const layout = computeFloatingLayerLayout(
    { left: 920, top: 520, width: 420, height: 180 },
    { width: 1366, height: 768 },
  )

  assert.equal(layout.placement, 'above')
  assert.equal(layout.top, 16)
  assert.ok(layout.maxHeight <= 490)
  assert.ok(layout.top + layout.maxHeight <= 506)
})

test('scrollbar hit-testing treats the viewport gutter as native scrollbar space', () => {
  const scrollbars = measureViewportScrollbars(1366, 768, 1350, 752)

  assert.deepEqual(scrollbars, { vertical: 16, horizontal: 16 })
  assert.equal(
    isPointNearViewportScrollbar({ x: 1349, y: 280 }, { width: 1366, height: 768 }, scrollbars),
    true,
  )
  assert.equal(
    isPointNearViewportScrollbar({ x: 700, y: 751 }, { width: 1366, height: 768 }, scrollbars),
    true,
  )
  assert.equal(
    isPointNearViewportScrollbar({ x: 700, y: 400 }, { width: 1366, height: 768 }, scrollbars),
    false,
  )
})

test('element scrollbar hit-testing recognises the horizontal nav rail scrollbar', () => {
  const rail = {
    rect: { left: 120, top: 48, right: 820, bottom: 104 },
    clientWidth: 700,
    clientHeight: 44,
    offsetWidth: 700,
    offsetHeight: 56,
    scrollWidth: 1040,
    scrollHeight: 44,
    borderTop: 0,
    borderRight: 0,
    borderBottom: 0,
    borderLeft: 0,
  }

  assert.deepEqual(measureElementScrollbars(rail), { vertical: 0, horizontal: 12 })
  assert.equal(getElementScrollbarAxis({ x: 420, y: 98 }, rail), 'x')
  assert.equal(getElementScrollbarAxis({ x: 420, y: 78 }, rail), null)
})
