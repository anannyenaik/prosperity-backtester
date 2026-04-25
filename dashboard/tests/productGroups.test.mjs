import { after, test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { build } from 'esbuild'

const testDir = path.dirname(fileURLToPath(import.meta.url))
const dashboardRoot = path.resolve(testDir, '..')
const compiledModule = path.join(os.tmpdir(), `prosperity-products-${process.pid}-${Date.now()}.mjs`)

await build({
  entryPoints: [path.join(dashboardRoot, 'src', 'lib', 'products.ts')],
  bundle: true,
  format: 'esm',
  platform: 'node',
  outfile: compiledModule,
  logLevel: 'silent',
})

const { availableProducts, productGroups } = await import(pathToFileURL(compiledModule).href)

after(() => {
  fs.rmSync(compiledModule, { force: true })
})

const round3Products = [
  'HYDROGEL_PACK',
  'VELVETFRUIT_EXTRACT',
  'VEV_4000',
  'VEV_4500',
  'VEV_5000',
  'VEV_5100',
  'VEV_5200',
  'VEV_5300',
  'VEV_5400',
  'VEV_5500',
  'VEV_6000',
  'VEV_6500',
]

function meta(symbol, assetClass, diagnosticsGroup, includeInSurfaceFit = false) {
  return {
    symbol,
    asset_class: assetClass,
    diagnostics_group: diagnosticsGroup,
    include_in_surface_fit: includeInSurfaceFit,
  }
}

test('Round 3 product groups keep all 12 products visible without truncation', () => {
  const payload = {
    products: round3Products,
    productMetadata: {
      HYDROGEL_PACK: meta('HYDROGEL_PACK', 'delta1', 'delta1'),
      VELVETFRUIT_EXTRACT: meta('VELVETFRUIT_EXTRACT', 'delta1', 'underlying'),
      VEV_4000: meta('VEV_4000', 'option', 'diagnostic_excluded'),
      VEV_4500: meta('VEV_4500', 'option', 'diagnostic_excluded'),
      VEV_5000: meta('VEV_5000', 'option', 'surface_fit', true),
      VEV_5100: meta('VEV_5100', 'option', 'surface_fit', true),
      VEV_5200: meta('VEV_5200', 'option', 'surface_fit', true),
      VEV_5300: meta('VEV_5300', 'option', 'surface_fit', true),
      VEV_5400: meta('VEV_5400', 'option', 'surface_fit', true),
      VEV_5500: meta('VEV_5500', 'option', 'surface_fit', true),
      VEV_6000: meta('VEV_6000', 'option', 'diagnostic_excluded'),
      VEV_6500: meta('VEV_6500', 'option', 'diagnostic_excluded'),
    },
  }

  const groups = productGroups(payload)
  const flattened = groups.flatMap((group) => group.products)

  assert.deepEqual(availableProducts(payload), round3Products)
  assert.equal(flattened.length, round3Products.length)
  assert.deepEqual([...flattened].sort(), [...round3Products].sort())
  assert.deepEqual(groups.map((group) => group.label), [
    'Delta-1',
    'Underlying',
    'Surface-fit vouchers',
    'Diagnostic vouchers',
  ])
  assert.deepEqual(groups.find((group) => group.id === 'surface-fit-vouchers').products, [
    'VEV_5000',
    'VEV_5100',
    'VEV_5200',
    'VEV_5300',
    'VEV_5400',
    'VEV_5500',
  ])
  assert.deepEqual(groups.find((group) => group.id === 'diagnostic-vouchers').products, [
    'VEV_4000',
    'VEV_4500',
    'VEV_6000',
    'VEV_6500',
  ])
})
