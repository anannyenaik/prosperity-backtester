import type {
  PnlRow,
  FillRow,
  InventoryRow,
  FairValueRow,
  FairBandPoint,
  SampleRun,
} from '../types'

export const POSITION_LIMIT = 80

export function byProduct<T extends { product: string }>(rows: T[], product: string): T[] {
  return rows.filter((r) => r.product === product)
}

export function downsample<T>(rows: T[], maxPoints = 2000): T[] {
  if (rows.length <= maxPoints) return rows
  const stride = Math.ceil(rows.length / maxPoints)
  const out: T[] = []
  for (let i = 0; i < rows.length; i += stride) out.push(rows[i])
  if (out[out.length - 1] !== rows[rows.length - 1]) out.push(rows[rows.length - 1])
  return out
}

export function applyWindow<T extends { timestamp: number; day: number }>(
  rows: T[],
  window: 'all' | 'start' | 'middle' | 'end',
): T[] {
  if (window === 'all' || rows.length === 0) return rows
  const chunk = Math.max(1, Math.floor(rows.length * 0.2))
  if (window === 'start') return rows.slice(0, chunk)
  if (window === 'end') return rows.slice(-chunk)
  const start = Math.max(0, Math.floor((rows.length - chunk) / 2))
  return rows.slice(start, start + chunk)
}

export function rowsAround<T>(rows: T[], index: number, radius: number): T[] {
  if (!rows.length) return []
  const safeIndex = Math.max(0, Math.min(rows.length - 1, index))
  return rows.slice(Math.max(0, safeIndex - radius), Math.min(rows.length, safeIndex + radius + 1))
}

export function globalTs(row: { timestamp: number; day: number }): number {
  return (row.day + 3) * 1_000_000 + row.timestamp
}

export interface PnlPoint {
  ts: number
  mtm: number
  realised: number
  unrealised: number
  day: number
}

export function buildPnlData(
  rows: PnlRow[],
  product: string,
  window: 'all' | 'start' | 'middle' | 'end' = 'all',
): PnlPoint[] {
  return downsample(applyWindow(byProduct(rows, product), window)).map((r) => ({
    ts: globalTs(r),
    mtm: r.mtm,
    realised: r.realised,
    unrealised: r.unrealised,
    day: r.day,
  }))
}

export function buildPnlDataFromRows(rows: PnlRow[]): PnlPoint[] {
  return downsample(rows).map((r) => ({
    ts: globalTs(r),
    mtm: r.mtm,
    realised: r.realised,
    unrealised: r.unrealised,
    day: r.day,
  }))
}

export interface InventoryPoint {
  ts: number
  position: number
  posRatio: number
  day: number
}

export function buildInventoryData(rows: InventoryRow[], product: string): InventoryPoint[] {
  return downsample(byProduct(rows, product)).map((r) => ({
    ts: globalTs(r),
    position: r.position,
    posRatio: (r.position / POSITION_LIMIT) * 100,
    day: r.day,
  }))
}

export function buildInventoryDataFromRows(rows: InventoryRow[]): InventoryPoint[] {
  return downsample(rows).map((r) => ({
    ts: globalTs(r),
    position: r.position,
    posRatio: (r.position / POSITION_LIMIT) * 100,
    day: r.day,
  }))
}

export interface FairPoint {
  ts: number
  analysis_fair: number | null
  mid: number | null
}

export interface FillPoint {
  ts: number
  price: number
  side: 'buy' | 'sell'
}

export function buildFairFillData(
  fairRows: FairValueRow[],
  fillRows: FillRow[],
  product: string,
): { fair: FairPoint[]; fills: FillPoint[] } {
  const fair = downsample(byProduct(fairRows, product)).map((r) => ({
    ts: globalTs(r as { timestamp: number; day: number }),
    analysis_fair: r.analysis_fair,
    mid: r.mid,
  }))
  const fills = byProduct(fillRows, product).map((r) => ({
    ts: globalTs(r),
    price: r.price,
    side: r.side,
  }))
  return { fair, fills }
}

export function buildFairFillDataFromRows(
  fairRows: FairValueRow[],
  fillRows: FillRow[],
): { fair: FairPoint[]; fills: FillPoint[] } {
  const fair = downsample(fairRows).map((r) => ({
    ts: globalTs(r as { timestamp: number; day: number }),
    analysis_fair: r.analysis_fair,
    mid: r.mid,
  }))
  const fills = fillRows.map((r) => ({
    ts: globalTs(r),
    price: r.price,
    side: r.side,
  }))
  return { fair, fills }
}

export interface HistPoint {
  midpoint: number
  count: number
  label: string
}

export function buildHistogram(values: number[], bins = 40): HistPoint[] {
  if (values.length === 0) return []
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const w = (hi - lo) / bins || 1
  const edges = Array.from({ length: bins + 1 }, (_, i) => lo + i * w)
  const counts = new Array<number>(bins).fill(0)
  for (const v of values) {
    const idx = Math.min(Math.floor((v - lo) / w), bins - 1)
    counts[idx]++
  }
  return edges.slice(0, bins).map((edge, i) => ({
    midpoint: edge + w / 2,
    count: counts[i],
    label: `${edge.toFixed(0)} to ${edges[i + 1].toFixed(0)}`,
  }))
}

export interface BandPoint {
  ts: number
  p10: number
  p25: number
  p50: number
  p75: number
  p90: number
}

export function buildBands(bands: FairBandPoint[]): BandPoint[] {
  return downsample(bands, 800).map((b) => ({
    ts: b.timestamp,
    p10: b.p10,
    p25: b.p25 ?? b.p10,
    p50: b.p50,
    p75: b.p75 ?? b.p90,
    p90: b.p90,
  }))
}

export interface CapStats {
  fracAtCap: number
  nearCapRate: number
  ticksAtCap: number
  total: number
  longCapRate: number
  shortCapRate: number
}

export function computeCapStats(rows: InventoryRow[], product: string): CapStats {
  const filtered = byProduct(rows, product)
  const total = filtered.length
  if (total === 0) {
    return { fracAtCap: 0, nearCapRate: 0, ticksAtCap: 0, total: 0, longCapRate: 0, shortCapRate: 0 }
  }
  const atCap = filtered.filter((r) => Math.abs(r.position) >= POSITION_LIMIT)
  const nearCap = filtered.filter((r) => Math.abs(r.position) >= POSITION_LIMIT * 0.8)
  const longCap = filtered.filter((r) => r.position >= POSITION_LIMIT)
  const shortCap = filtered.filter((r) => r.position <= -POSITION_LIMIT)
  return {
    fracAtCap: atCap.length / total,
    nearCapRate: nearCap.length / total,
    ticksAtCap: atCap.length,
    total,
    longCapRate: longCap.length / total,
    shortCapRate: shortCap.length / total,
  }
}

export function buildSpreadDist(
  orders: Array<{ product: string; distance_to_touch: number | null }>,
  product: string,
) {
  const vals = byProduct(orders, product)
    .map((r) => r.distance_to_touch)
    .filter((v): v is number => v != null)
  return buildHistogram(vals, 30)
}

export function buildMarkoutDist(
  fills: FillRow[],
  key: 'markout_1' | 'markout_5' | 'signed_edge_to_analysis_fair',
): HistPoint[] {
  const vals = fills.map((r) => r[key]).filter((v): v is number => v != null)
  return buildHistogram(vals, 30)
}

export function bestSampleRun(sampleRuns: SampleRun[]): SampleRun | null {
  if (!sampleRuns.length) return null
  return [...sampleRuns].sort((a, b) => (b.summary?.final_pnl ?? 0) - (a.summary?.final_pnl ?? 0))[0]
}

export function worstSampleRun(sampleRuns: SampleRun[]): SampleRun | null {
  if (!sampleRuns.length) return null
  return [...sampleRuns].sort((a, b) => (a.summary?.final_pnl ?? 0) - (b.summary?.final_pnl ?? 0))[0]
}
