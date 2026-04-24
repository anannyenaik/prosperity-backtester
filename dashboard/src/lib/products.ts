import type { DashboardPayload } from '../types'

const LEGACY_LABELS: Record<string, string> = {
  ASH_COATED_OSMIUM: 'Osmium',
  INTARIAN_PEPPER_ROOT: 'Pepper',
  HYDROGEL_PACK: 'Hydrogel Pack',
  VELVETFRUIT_EXTRACT: 'Velvetfruit Extract',
}

function fallbackLabel(product: string): string {
  if (LEGACY_LABELS[product]) return LEGACY_LABELS[product]
  return product.replace(/_/g, ' ')
}

export function availableProducts(payload: DashboardPayload | null | undefined): string[] {
  if (Array.isArray(payload?.products) && payload.products.length) return payload.products
  const summaryProducts = Object.keys(payload?.summary?.per_product ?? {})
  if (summaryProducts.length) return summaryProducts
  const metadataProducts = Object.keys(payload?.productMetadata ?? {})
  if (metadataProducts.length) return metadataProducts
  return []
}

export function productShortLabel(payload: DashboardPayload | null | undefined, product: string): string {
  const shortName = payload?.productMetadata?.[product]?.short_name
  if (typeof shortName === 'string' && shortName.trim()) return shortName
  return product
}

export function productLabel(payload: DashboardPayload | null | undefined, product: string): string {
  const symbol = payload?.productMetadata?.[product]?.symbol
  if (typeof symbol === 'string' && symbol.trim()) return fallbackLabel(symbol)
  return fallbackLabel(product)
}

export function positionLimit(payload: DashboardPayload | null | undefined, product: string): number {
  const explicit = payload?.positionLimits?.[product]
  if (typeof explicit === 'number' && Number.isFinite(explicit)) return explicit
  const metadataLimit = payload?.productMetadata?.[product]?.position_limit
  if (typeof metadataLimit === 'number' && Number.isFinite(metadataLimit)) return metadataLimit
  return 80
}

export function productGroups(payload: DashboardPayload | null | undefined): Array<{ id: string; label: string; products: string[] }> {
  const groups = new Map<string, { id: string; label: string; products: string[] }>()
  for (const product of availableProducts(payload)) {
    const assetClass = String(payload?.productMetadata?.[product]?.asset_class ?? 'other')
    const diagnosticsGroup = String(payload?.productMetadata?.[product]?.diagnostics_group ?? '')
    const includeInSurface = payload?.productMetadata?.[product]?.include_in_surface_fit
    let groupId = 'other'
    let label = 'Other'
    if (diagnosticsGroup === 'underlying') {
      groupId = 'underlying'
      label = 'Underlying'
    } else if (assetClass === 'option' && includeInSurface === true) {
      groupId = 'surface-fit-vouchers'
      label = 'Surface-fit vouchers'
    } else if (assetClass === 'option') {
      groupId = 'diagnostic-vouchers'
      label = 'Excluded diagnostics'
    } else if (assetClass === 'delta1') {
      groupId = 'delta1'
      label = 'Delta-1'
    }
    if (!groups.has(groupId)) {
      groups.set(groupId, { id: groupId, label, products: [] })
    }
    groups.get(groupId)!.products.push(product)
  }
  const order = ['delta1', 'underlying', 'surface-fit-vouchers', 'diagnostic-vouchers', 'other']
  return Array.from(groups.values()).sort((left, right) => order.indexOf(left.id) - order.indexOf(right.id))
}
