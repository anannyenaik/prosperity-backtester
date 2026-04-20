import type {
  BehaviourPerProduct,
  DashboardPayload,
  FairValueRow,
  FillRow,
  InventoryRow,
  PnlRow,
  Product,
  ProductSummary,
  Round2ScenarioRow,
} from '../types'
import { POSITION_LIMIT, PRODUCT_LABELS, PRODUCTS } from '../types'
import { getComparisonRows, interpretBundle, numberOrNull } from './bundles'

export type AlphaClassification = 'public_data' | 'local_bt' | 'website_only' | 'weak_rejected'
export type AlphaBucket = 'active' | 'testing' | 'strong' | 'website' | 'rejected'
export type AlphaAction = 'implement_now' | 'ab_on_website' | 'test_in_backtester' | 'monitor_only' | 'reject'
export type AlphaTone = 'good' | 'bad' | 'warn' | 'neutral' | 'accent'

export const ALPHA_CLASS_LABELS: Record<AlphaClassification, string> = {
  public_data: 'Public-data edge',
  local_bt: 'Local-BT edge',
  website_only: 'Website-only edge',
  weak_rejected: 'Weak / rejected',
}

export const ALPHA_BUCKET_LABELS: Record<AlphaBucket, string> = {
  active: 'Active candidates',
  testing: 'In testing',
  strong: 'Strong evidence',
  website: 'Website-only / unresolved',
  rejected: 'Rejected / weak',
}

export const ALPHA_ACTION_LABELS: Record<AlphaAction, string> = {
  implement_now: 'Implement now',
  ab_on_website: 'A/B on website',
  test_in_backtester: 'Test in backtester',
  monitor_only: 'Monitor only',
  reject: 'Reject',
}

export interface AlphaEvidence {
  label: string
  value: string
  detail?: string
  tone?: AlphaTone
}

export interface AlphaMetric {
  label: string
  value: string
  detail?: string
  tone?: AlphaTone
}

export interface AlphaHypothesis {
  id: string
  name: string
  product: string
  category: string
  classification: AlphaClassification
  bucket: AlphaBucket
  confidence: number | null
  sampleSize: number | null
  support: string
  exploitabilityNow: string
  currentCapture: string
  edgeSize: string
  frequency: string
  robustness: string
  websiteDependency: string
  implementationDifficulty: string
  likelyLeaderboardValue: string
  priorityScore: number
  priorityLabel: 'High' | 'Medium' | 'Low' | 'Reject'
  nextAction: AlphaAction
  nextActionDetail: string
  supportEvidence: AlphaEvidence[]
  againstEvidence: AlphaEvidence[]
}

export interface AlphaProductPanel {
  product: Product
  label: string
  source: string
  metrics: AlphaMetric[]
  conditionRows: ConditionalRow[]
  messages: string[]
}

export interface ConditionalRow {
  state: string
  support: number | null
  mean_residual: number | null
  next_1_mean: number | null
  next_5_mean: number | null
  hit_rate_5: number | null
}

export interface AlphaMafPanel {
  available: boolean
  message: string
  metrics: AlphaMetric[]
  rows: MafEvidenceRow[]
}

export interface MafEvidenceRow {
  scenario: string
  trader: string
  classification: string
  final_pnl: number | null
  access_edge: number | null
  break_even_maf: number | null
  mc_mean: number | null
  mc_p05: number | null
}

export interface RobustnessRow {
  source: string
  classification: string
  support: string
  against: string
  action: string
  tone: AlphaTone
}

export interface NextTestRow {
  rank: number
  action: string
  hypothesis: string
  classification: string
  reason: string
  priority: string
}

export interface AlphaLabData {
  bundleLabel: string
  generatedFrom: string[]
  hypotheses: AlphaHypothesis[]
  buckets: Record<AlphaBucket, AlphaHypothesis[]>
  topCandidates: AlphaHypothesis[]
  productPanels: AlphaProductPanel[]
  mafPanel: AlphaMafPanel
  robustnessRows: RobustnessRow[]
  nextTests: NextTestRow[]
  missingMessages: string[]
}

interface ReplayEvidence {
  source: string
  sampleOnly: boolean
  fairRows: AlphaFairRow[]
  fills: AlphaFillRow[]
  inventory: AlphaInventoryRow[]
  pnl: AlphaPnlRow[]
}

type AlphaFairRow = FairValueRow & { __alphaRun?: string }
type AlphaFillRow = FillRow & { __alphaRun?: string }
type AlphaInventoryRow = InventoryRow & { __alphaRun?: string }
type AlphaPnlRow = PnlRow & { __alphaRun?: string }

interface ResidualStats {
  sampleCount: number
  meanAbsResidual: number | null
  p75AbsResidual: number | null
  hitRate1: number | null
  hitRate5: number | null
  fadeRate5: number | null
  meanAlignedMove1: number | null
  meanAlignedMove5: number | null
  conditionRows: ConditionalRow[]
}

interface ImbalanceStats {
  sampleCount: number
  tailCount: number
  meanAbsImbalance: number | null
  hitRate5: number | null
  meanAlignedMove5: number | null
}

interface MarkoutStats {
  count: number
  qty: number
  markout1: number | null
  markout5: number | null
  positiveRate5: number | null
  edge: number | null
}

interface InventoryStats {
  sampleCount: number
  capUsage: number | null
  nearCapRate: number | null
  atCapRate: number | null
  recycleEfficiency: number | null
  unrealisedShare: number | null
  finalMtm: number | null
  realised: number | null
}

const MIN_SIGNAL_ROWS = 100
const MIN_FILL_ROWS = 10

export function buildAlphaLabData(payload: DashboardPayload, comparePayload?: DashboardPayload | null): AlphaLabData {
  const bundle = interpretBundle(payload)
  const replayEvidence = collectReplayEvidence(payload)
  const hypotheses: AlphaHypothesis[] = []
  const productPanels: AlphaProductPanel[] = []
  const missingMessages: string[] = []

  for (const product of PRODUCTS) {
    const productEvidence = buildProductEvidence(payload, replayEvidence, product)
    productPanels.push(productEvidence.panel)
    hypotheses.push(...productEvidence.hypotheses)
  }

  const maf = buildMafEvidence(payload)
  if (maf.hypothesis) hypotheses.push(maf.hypothesis)

  const mcHypothesis = buildMonteCarloHypothesis(payload)
  if (mcHypothesis) hypotheses.push(mcHypothesis)

  const comparisonHypothesis = buildComparisonHypothesis(payload, comparePayload)
  if (comparisonHypothesis) hypotheses.push(comparisonHypothesis)

  const crossDayHypothesis = buildCrossDayHypothesis(payload)
  if (crossDayHypothesis) hypotheses.push(crossDayHypothesis)

  if (!replayEvidence.fairRows.length && !replayEvidence.fills.length && !payload.monteCarlo && !getComparisonRows(payload).length && !payload.round2) {
    missingMessages.push(`${bundle.badge} does not contain replay, Monte Carlo, comparison or Round 2 evidence for Alpha Lab scoring.`)
  }
  if (!replayEvidence.fairRows.length) {
    missingMessages.push('Replay-compatible fair-value rows are not present, so residual and imbalance hypotheses are unavailable.')
  }
  if (!replayEvidence.fills.length) {
    missingMessages.push('Fill rows are not present, so markout and quote-quality hypotheses are unavailable.')
  }

  const sorted = [...hypotheses].sort((a, b) => b.priorityScore - a.priorityScore)
  const buckets = makeBuckets(sorted)

  return {
    bundleLabel: bundle.badge,
    generatedFrom: evidenceSources(payload, replayEvidence),
    hypotheses: sorted,
    buckets,
    topCandidates: sorted.filter((item) => item.classification !== 'weak_rejected').slice(0, 8),
    productPanels,
    mafPanel: maf.panel,
    robustnessRows: buildRobustnessRows(payload, hypotheses),
    nextTests: buildNextTests(sorted),
    missingMessages,
  }
}

function collectReplayEvidence(payload: DashboardPayload): ReplayEvidence {
  if (
    (payload.fairValueSeries?.length ?? 0) > 0 ||
    (payload.fills?.length ?? 0) > 0 ||
    (payload.inventorySeries?.length ?? 0) > 0 ||
    (payload.pnlSeries?.length ?? 0) > 0
  ) {
    return {
      source: 'Top-level replay rows',
      sampleOnly: false,
      fairRows: tagRows(payload.fairValueSeries ?? [], 'active'),
      fills: tagRows(payload.fills ?? [], 'active'),
      inventory: tagRows(payload.inventorySeries ?? [], 'active'),
      pnl: tagRows(payload.pnlSeries ?? [], 'active'),
    }
  }

  const samples = payload.monteCarlo?.sampleRuns ?? []
  if (samples.length > 0) {
    return {
      source: `MC sample paths (${samples.length} saved)`,
      sampleOnly: true,
      fairRows: samples.flatMap((sample) => tagRows(sample.fairValueSeries ?? [], sample.runName)),
      fills: samples.flatMap((sample) => tagRows(sample.fills ?? [], sample.runName)),
      inventory: samples.flatMap((sample) => tagRows(sample.inventorySeries ?? [], sample.runName)),
      pnl: samples.flatMap((sample) => tagRows(sample.pnlSeries ?? [], sample.runName)),
    }
  }

  return {
    source: 'No replay-compatible rows',
    sampleOnly: false,
    fairRows: [],
    fills: [],
    inventory: [],
    pnl: [],
  }
}

function tagRows<T extends object>(rows: T[], runName: string): Array<T & { __alphaRun: string }> {
  return rows.map((row) => ({ ...row, __alphaRun: runName }))
}

function buildProductEvidence(payload: DashboardPayload, replay: ReplayEvidence, product: Product) {
  const fairRows = replay.fairRows.filter((row) => row.product === product)
  const fills = replay.fills.filter((row) => row.product === product)
  const inventory = replay.inventory.filter((row) => row.product === product)
  const pnl = replay.pnl.filter((row) => row.product === product)
  const behaviour = payload.behaviour?.per_product?.[product] as Partial<BehaviourPerProduct> | undefined
  const productSummary = payload.summary?.per_product?.[product]

  const residual = computeResidualStats(fairRows)
  const imbalance = computeImbalanceStats(fairRows)
  const passive = computeMarkoutStats(fills.filter((fill) => !String(fill.kind ?? '').startsWith('aggressive')))
  const aggressive = computeMarkoutStats(fills.filter((fill) => String(fill.kind ?? '').startsWith('aggressive')))
  const inventoryStats = computeInventoryStats(inventory, pnl, behaviour, productSummary)
  const oneSided = computeOneSidedStats(fairRows)
  const hypotheses: AlphaHypothesis[] = []

  const residualHypothesis = buildResidualHypothesis(product, residual, replay.sampleOnly)
  if (residualHypothesis) hypotheses.push(residualHypothesis)

  if (product === 'INTARIAN_PEPPER_ROOT') {
    const continuation = buildPepperContinuationHypothesis(residual, replay.sampleOnly)
    if (continuation) hypotheses.push(continuation)
  }

  const imbalanceHypothesis = buildImbalanceHypothesis(product, imbalance, replay.sampleOnly)
  if (imbalanceHypothesis) hypotheses.push(imbalanceHypothesis)

  const passiveHypothesis = buildMarkoutHypothesis(product, 'passive', passive, inventoryStats)
  if (passiveHypothesis) hypotheses.push(passiveHypothesis)

  const aggressiveHypothesis = buildMarkoutHypothesis(product, 'aggressive', aggressive, inventoryStats)
  if (aggressiveHypothesis) hypotheses.push(aggressiveHypothesis)

  const inventoryHypothesis = buildInventoryHypothesis(product, inventoryStats)
  if (inventoryHypothesis) hypotheses.push(inventoryHypothesis)

  const oneSidedHypothesis = buildOneSidedHypothesis(product, oneSided, replay.sampleOnly)
  if (oneSidedHypothesis) hypotheses.push(oneSidedHypothesis)

  const panel: AlphaProductPanel = {
    product,
    label: PRODUCT_LABELS[product],
    source: replay.source,
    conditionRows: residual.conditionRows,
    messages: productMessages(replay, fairRows, fills, inventory),
    metrics: [
      metric('Evidence source', replay.source, replay.sampleOnly ? 'Saved MC sample paths, not full MC population' : undefined, replay.sampleOnly ? 'warn' : 'accent'),
      metric('Residual rows', formatInt(residual.sampleCount), 'Rows with analysis fair and mid'),
      metric('Mean abs residual', formatNumber(residual.meanAbsResidual), 'Fair minus mid magnitude', residual.meanAbsResidual == null ? 'neutral' : residual.meanAbsResidual > 1 ? 'accent' : 'neutral'),
      metric('Residual hit +5', formatPct(residual.hitRate5), 'Directional alignment over 5 rows', toneForHitRate(residual.hitRate5)),
      metric('Imbalance rows', formatInt(imbalance.sampleCount), 'Rows with microprice, mid and spread'),
      metric('Imbalance hit +5', formatPct(imbalance.hitRate5), 'Microprice imbalance alignment', toneForHitRate(imbalance.hitRate5)),
      metric('Passive M+5', formatNumber(passive.markout5), `${formatInt(passive.count)} fills`, toneForValue(passive.markout5)),
      metric('Aggressive M+5', formatNumber(aggressive.markout5), `${formatInt(aggressive.count)} fills`, toneForValue(aggressive.markout5)),
      metric('One-sided frequency', formatPct(oneSided.frequency), `${formatInt(oneSided.count)} rows without a full spread`, oneSided.frequency != null && oneSided.frequency > 0.01 ? 'warn' : 'neutral'),
      metric('Near-cap time', formatPct(inventoryStats.nearCapRate), `${formatInt(inventoryStats.sampleCount)} inventory rows`, inventoryStats.nearCapRate != null && inventoryStats.nearCapRate > 0.2 ? 'warn' : 'neutral'),
      metric(product === 'ASH_COATED_OSMIUM' ? 'Recycle efficiency' : 'Unrealised share', product === 'ASH_COATED_OSMIUM' ? formatPct(inventoryStats.recycleEfficiency) : formatPct(inventoryStats.unrealisedShare), 'Derived from fills and replay PnL', 'neutral'),
    ],
  }

  return { panel, hypotheses }
}

function buildResidualHypothesis(product: Product, stats: ResidualStats, sampleOnly: boolean): AlphaHypothesis | null {
  if (stats.sampleCount === 0) return null
  const label = PRODUCT_LABELS[product]
  const hit = stats.hitRate5 ?? stats.hitRate1
  const aligned = stats.meanAlignedMove5 ?? stats.meanAlignedMove1
  const enoughRows = stats.sampleCount >= MIN_SIGNAL_ROWS
  const supported = enoughRows && hit != null && hit >= 0.54 && aligned != null && aligned > 0
  const confidence = confidenceFromHitRate(hit, stats.sampleCount, sampleOnly)
  const classification: AlphaClassification = supported ? 'public_data' : 'weak_rejected'
  const priority = priorityScore({
    classification,
    confidence,
    edge: normaliseAbs(aligned, 0.8),
    frequency: sampleScore(stats.sampleCount, 1000),
    robustness: hit == null ? 0 : Math.max(0, (hit - 0.5) * 8),
    difficulty: 0.35,
  })

  return makeHypothesis({
    id: `${product}-residual-alignment`,
    name: product === 'ASH_COATED_OSMIUM' ? 'OSMIUM anchor residual alignment' : 'PEPPER time-fair residual alignment',
    product: label,
    category: 'latent fair',
    classification,
    confidence,
    sampleSize: stats.sampleCount,
    support: supported ? 'Residual direction has positive next-step alignment.' : 'Residual evidence is below the promotion threshold.',
    exploitabilityNow: supported ? 'Medium, gated quoting or taking can be tested locally' : 'Low until predictive alignment improves',
    currentCapture: 'Not script-bound; compare with fill markouts for capture',
    edgeSize: formatNumber(aligned),
    frequency: formatInt(stats.sampleCount),
    robustness: sampleOnly ? 'Sample-path only' : formatPct(hit),
    websiteDependency: 'None for the public CSV signal',
    implementationDifficulty: 'Medium',
    likelyLeaderboardValue: supported ? 'Medium if it survives replay and MC checks' : 'Low',
    priorityScore: priority,
    nextAction: supported ? 'test_in_backtester' : 'monitor_only',
    nextActionDetail: supported ? 'Add a residual-gated rule and compare against current fills.' : 'Keep as a diagnostic until hit rate and sample support clear the threshold.',
    supportEvidence: [
      evidence('Samples', formatInt(stats.sampleCount), sampleOnly ? 'Saved MC sample rows only' : 'Replay-compatible fair rows'),
      evidence('Hit rate +5', formatPct(stats.hitRate5), 'Fair-minus-mid direction versus later mid move', toneForHitRate(stats.hitRate5)),
      evidence('Mean aligned move +5', formatNumber(stats.meanAlignedMove5), 'Positive means residual direction was paid', toneForValue(stats.meanAlignedMove5)),
    ],
    againstEvidence: [
      ...(enoughRows ? [] : [evidence('Sample warning', formatInt(stats.sampleCount), `Needs at least ${MIN_SIGNAL_ROWS} rows`, 'warn')]),
      ...(hit != null && hit < 0.54 ? [evidence('Noise floor', formatPct(hit), 'Below 54% directional threshold', 'warn')] : []),
      evidence('Fair source', sampleOnly ? 'MC sample' : 'Analysis fair', 'Historical fair can be an inferred diagnostic rather than official hidden fair', 'warn'),
    ],
  })
}

function buildPepperContinuationHypothesis(stats: ResidualStats, sampleOnly: boolean): AlphaHypothesis | null {
  if (stats.sampleCount === 0) return null
  const continuation = stats.hitRate5
  const fade = stats.fadeRate5
  if (continuation == null || fade == null) return null
  const spread = continuation - fade
  const enoughRows = stats.sampleCount >= MIN_SIGNAL_ROWS
  const supported = enoughRows && Math.abs(spread) >= 0.08
  const isContinuation = spread > 0
  const confidence = supported ? clamp(0.5 + Math.abs(spread) * 1.5, 0.52, sampleOnly ? 0.72 : 0.86) : 0.28
  const classification: AlphaClassification = supported ? 'public_data' : 'weak_rejected'
  const priority = priorityScore({
    classification,
    confidence,
    edge: Math.abs(spread) * 4,
    frequency: sampleScore(stats.sampleCount, 1000),
    robustness: Math.abs(spread) * 3,
    difficulty: 0.45,
  })

  return makeHypothesis({
    id: 'pepper-continuation-branch',
    name: isContinuation ? 'PEPPER continuation branch' : 'PEPPER mean-reversion branch',
    product: 'Pepper',
    category: 'regime-specific behaviour',
    classification,
    confidence,
    sampleSize: stats.sampleCount,
    support: supported ? `${isContinuation ? 'Continuation' : 'Mean reversion'} is materially ahead of the opposite branch.` : 'Continuation and fade evidence are too close to separate.',
    exploitabilityNow: supported ? 'Medium, but needs replay gating before implementation' : 'Low',
    currentCapture: 'Check PEPPER aggressive and inventory hypotheses for script capture',
    edgeSize: formatPct(Math.abs(spread)),
    frequency: formatInt(stats.sampleCount),
    robustness: sampleOnly ? 'Sample-path only' : 'Public replay rows',
    websiteDependency: 'None for the public CSV signal',
    implementationDifficulty: 'Medium',
    likelyLeaderboardValue: supported ? 'Medium' : 'Low',
    priorityScore: priority,
    nextAction: supported ? 'test_in_backtester' : 'monitor_only',
    nextActionDetail: supported ? 'A/B continuation and fade gates around the same cap and monetisation rules.' : 'Do not branch PEPPER logic on this yet.',
    supportEvidence: [
      evidence('Continuation hit', formatPct(continuation), 'Residual direction followed by later mid move', toneForHitRate(continuation)),
      evidence('Fade hit', formatPct(fade), 'Opposite direction was paid', toneForHitRate(fade)),
      evidence('Spread', formatPct(spread), 'Continuation minus fade'),
    ],
    againstEvidence: [
      ...(enoughRows ? [] : [evidence('Sample warning', formatInt(stats.sampleCount), `Needs at least ${MIN_SIGNAL_ROWS} rows`, 'warn')]),
      ...(Math.abs(spread) < 0.08 ? [evidence('Separation', formatPct(Math.abs(spread)), 'Below 8 point separation threshold', 'warn')] : []),
      evidence('Fair source', sampleOnly ? 'MC sample' : 'Analysis fair', 'Treat as a test input, not a proven hidden fair', 'warn'),
    ],
  })
}

function buildImbalanceHypothesis(product: Product, stats: ImbalanceStats, sampleOnly: boolean): AlphaHypothesis | null {
  if (stats.sampleCount === 0) return null
  const label = PRODUCT_LABELS[product]
  const enoughRows = stats.sampleCount >= MIN_SIGNAL_ROWS && stats.tailCount >= 20
  const supported = enoughRows && stats.hitRate5 != null && stats.hitRate5 >= 0.54 && (stats.meanAlignedMove5 ?? 0) > 0
  const confidence = confidenceFromHitRate(stats.hitRate5, stats.sampleCount, sampleOnly)
  const classification: AlphaClassification = supported ? 'public_data' : 'weak_rejected'
  const priority = priorityScore({
    classification,
    confidence,
    edge: normaliseAbs(stats.meanAlignedMove5, 0.6),
    frequency: sampleScore(stats.tailCount, 400),
    robustness: stats.hitRate5 == null ? 0 : Math.max(0, (stats.hitRate5 - 0.5) * 8),
    difficulty: 0.25,
  })

  return makeHypothesis({
    id: `${product}-imbalance-proxy`,
    name: `${label} top-of-book imbalance proxy`,
    product: label,
    category: 'imbalance',
    classification,
    confidence,
    sampleSize: stats.sampleCount,
    support: supported ? 'Microprice imbalance has directional follow-through.' : 'Microprice imbalance is not strong enough to promote.',
    exploitabilityNow: supported ? 'Medium, cheap to test as a quote filter' : 'Low',
    currentCapture: 'Not script-bound; inspect fill markouts for capture',
    edgeSize: formatNumber(stats.meanAlignedMove5),
    frequency: `${formatInt(stats.tailCount)} tail rows`,
    robustness: sampleOnly ? 'Sample-path only' : formatPct(stats.hitRate5),
    websiteDependency: 'None for the public CSV signal',
    implementationDifficulty: 'Low',
    likelyLeaderboardValue: supported ? 'Low to medium' : 'Low',
    priorityScore: priority,
    nextAction: supported ? 'test_in_backtester' : 'monitor_only',
    nextActionDetail: supported ? 'Use imbalance as a low-risk gate, not as a standalone signal.' : 'Keep the panel visible, but avoid trading from it alone.',
    supportEvidence: [
      evidence('Rows', formatInt(stats.sampleCount), 'Rows with microprice, mid and spread'),
      evidence('Tail rows', formatInt(stats.tailCount), 'Absolute imbalance proxy above 0.25'),
      evidence('Hit rate +5', formatPct(stats.hitRate5), 'Microprice direction versus later mid move', toneForHitRate(stats.hitRate5)),
    ],
    againstEvidence: [
      ...(enoughRows ? [] : [evidence('Support warning', formatInt(stats.tailCount), 'Needs at least 20 tail rows and 100 total rows', 'warn')]),
      evidence('Proxy limit', 'Microprice only', 'Top book sizes are not exposed directly in the dashboard schema', 'warn'),
    ],
  })
}

function buildMarkoutHypothesis(product: Product, fillType: 'passive' | 'aggressive', stats: MarkoutStats, inventory: InventoryStats): AlphaHypothesis | null {
  if (stats.count === 0) return null
  const label = PRODUCT_LABELS[product]
  const markout = stats.markout5 ?? stats.markout1
  const enoughRows = stats.count >= MIN_FILL_ROWS
  const supported = enoughRows && markout != null && markout > 0
  const rejected = enoughRows && markout != null && markout <= 0
  const classification: AlphaClassification = supported ? 'local_bt' : 'weak_rejected'
  const confidence = supported ? clamp(0.45 + sampleScore(stats.count, 80) * 0.18 + normaliseAbs(markout, 2) * 0.16, 0.45, 0.86) : rejected ? 0.22 : 0.3
  const category = fillType === 'passive' ? 'passive markout' : 'aggressive markout'
  const priority = priorityScore({
    classification,
    confidence,
    edge: normaliseAbs(markout, 2),
    frequency: sampleScore(stats.count, 80),
    robustness: stats.positiveRate5 == null ? 0.2 : Math.max(0, (stats.positiveRate5 - 0.45) * 3),
    difficulty: fillType === 'passive' ? 0.4 : 0.55,
  })

  const productPrefix = product === 'ASH_COATED_OSMIUM' ? 'OSMIUM' : 'PEPPER'
  const name =
    fillType === 'passive'
      ? `${productPrefix} passive quote markout`
      : product === 'ASH_COATED_OSMIUM'
        ? 'OSMIUM stale-quote taking quality'
        : 'PEPPER aggressive fill markout'

  return makeHypothesis({
    id: `${product}-${fillType}-markout`,
    name,
    product: label,
    category,
    classification,
    confidence,
    sampleSize: stats.count,
    support: supported ? `${fillType} fills have positive signed markout.` : `${fillType} markout is weak or adverse.`,
    exploitabilityNow: supported ? 'High if implementation only gates existing orders' : 'Low',
    currentCapture: `${formatNumber(markout)} average M+5 over ${formatInt(stats.count)} fills`,
    edgeSize: formatNumber(markout),
    frequency: `${formatInt(stats.count)} fills / qty ${formatInt(stats.qty)}`,
    robustness: formatPct(stats.positiveRate5),
    websiteDependency: 'Local fill model and queue assumptions apply',
    implementationDifficulty: fillType === 'passive' ? 'Medium' : 'Medium to high',
    likelyLeaderboardValue: supported && stats.count >= 25 ? 'Medium' : 'Low',
    priorityScore: priority,
    nextAction: supported ? 'test_in_backtester' : rejected ? 'reject' : 'monitor_only',
    nextActionDetail: supported
      ? fillType === 'passive'
        ? 'Tighten quote placement around the states with positive markout.'
        : 'Gate taker logic on stale-quote states and compare against current capture.'
      : rejected
        ? 'Do not expand this execution style without a new state filter.'
        : 'Collect more fills before changing execution.',
    supportEvidence: [
      evidence('Average M+5', formatNumber(stats.markout5), 'Signed favourable markout', toneForValue(stats.markout5)),
      evidence('Positive M+5 rate', formatPct(stats.positiveRate5), 'Share of fills with favourable M+5', toneForHitRate(stats.positiveRate5)),
      evidence('Edge to fair', formatNumber(stats.edge), 'Signed edge at fill time', toneForValue(stats.edge)),
    ],
    againstEvidence: [
      ...(enoughRows ? [] : [evidence('Fill sample', formatInt(stats.count), `Needs at least ${MIN_FILL_ROWS} fills`, 'warn')]),
      evidence('Model dependency', 'Local-BT', 'Passive fills and queue priority are approximate', 'warn'),
      ...(inventory.nearCapRate != null && inventory.nearCapRate > 0.25 ? [evidence('Inventory pressure', formatPct(inventory.nearCapRate), 'Markouts may be coupled to cap pressure', 'warn')] : []),
    ],
  })
}

function buildInventoryHypothesis(product: Product, stats: InventoryStats): AlphaHypothesis | null {
  if (stats.sampleCount === 0 && stats.finalMtm == null) return null
  const label = PRODUCT_LABELS[product]

  if (product === 'ASH_COATED_OSMIUM') {
    const recycle = stats.recycleEfficiency
    const supported = recycle != null && recycle >= 0.6 && (stats.finalMtm ?? 0) > 0 && (stats.capUsage ?? 0) < 0.9
    const classification: AlphaClassification = supported ? 'local_bt' : 'weak_rejected'
    const confidence = supported ? clamp(0.45 + recycle * 0.25 + normaliseAbs(stats.finalMtm, 20_000) * 0.12, 0.45, 0.78) : 0.26
    return makeHypothesis({
      id: 'osmium-recycle-efficiency',
      name: 'OSMIUM recycle and neutral-take efficiency',
      product: label,
      category: 'inventory efficiency',
      classification,
      confidence,
      sampleSize: stats.sampleCount || null,
      support: supported ? 'Turnover is balanced and profitable without sitting at cap.' : 'Recycle evidence is not yet compelling.',
      exploitabilityNow: supported ? 'Medium, can tune inventory bands locally' : 'Low',
      currentCapture: `MTM ${formatNumber(stats.finalMtm)} / recycle ${formatPct(recycle)}`,
      edgeSize: formatNumber(stats.finalMtm),
      frequency: formatPct(recycle),
      robustness: 'Replay behaviour only',
      websiteDependency: 'Local fill model applies',
      implementationDifficulty: 'Medium',
      likelyLeaderboardValue: supported ? 'Low to medium' : 'Low',
      priorityScore: priorityScore({
        classification,
        confidence,
        edge: normaliseAbs(stats.finalMtm, 25_000),
        frequency: recycle ?? 0,
        robustness: (stats.capUsage ?? 1) < 0.9 ? 0.8 : 0.2,
        difficulty: 0.45,
      }),
      nextAction: supported ? 'test_in_backtester' : 'monitor_only',
      nextActionDetail: supported ? 'Test tighter neutralisation bands and preserve positive passive states.' : 'Do not spend implementation time until recycle PnL separates.',
      supportEvidence: [
        evidence('Recycle efficiency', formatPct(recycle), 'One minus net fill imbalance over turnover'),
        evidence('Final MTM', formatNumber(stats.finalMtm), 'Product replay capture', toneForValue(stats.finalMtm)),
        evidence('Cap usage', formatPct(stats.capUsage), 'Peak position over limit', stats.capUsage != null && stats.capUsage > 0.9 ? 'warn' : 'neutral'),
      ],
      againstEvidence: [
        evidence('Replay dependency', 'Local-BT', 'Execution quality still depends on local fill assumptions', 'warn'),
        ...(stats.finalMtm != null && stats.finalMtm <= 0 ? [evidence('Capture', formatNumber(stats.finalMtm), 'No positive product capture', 'bad')] : []),
      ],
    })
  }

  const nearCap = stats.nearCapRate ?? stats.capUsage
  const supported = nearCap != null && nearCap >= 0.1 && (stats.finalMtm ?? 0) > 0
  const adverse = nearCap != null && nearCap >= 0.2 && (stats.finalMtm ?? 0) <= 0
  const classification: AlphaClassification = supported ? 'local_bt' : 'weak_rejected'
  const confidence = supported ? clamp(0.45 + nearCap * 0.35 + normaliseAbs(stats.finalMtm, 40_000) * 0.12, 0.45, 0.82) : adverse ? 0.18 : 0.3

  return makeHypothesis({
    id: 'pepper-cap-monetisation',
    name: 'PEPPER cap and monetisation timing',
    product: label,
    category: 'cap usage',
    classification,
    confidence,
    sampleSize: stats.sampleCount || null,
    support: supported ? 'Cap usage is associated with positive replay capture.' : adverse ? 'Cap pressure is not paying in this run.' : 'Cap pressure is limited or unproven.',
    exploitabilityNow: supported ? 'Medium, but needs downside checks' : 'Low',
    currentCapture: `MTM ${formatNumber(stats.finalMtm)} / unrealised ${formatPct(stats.unrealisedShare)}`,
    edgeSize: formatNumber(stats.finalMtm),
    frequency: formatPct(nearCap),
    robustness: 'Replay behaviour only',
    websiteDependency: 'Local fill model applies',
    implementationDifficulty: 'Medium',
    likelyLeaderboardValue: supported ? 'Medium if drawdown stays controlled' : 'Low',
    priorityScore: priorityScore({
      classification,
      confidence,
      edge: normaliseAbs(stats.finalMtm, 40_000),
      frequency: nearCap ?? 0,
      robustness: stats.unrealisedShare != null && stats.unrealisedShare > 0.6 ? 0.35 : 0.65,
      difficulty: 0.55,
    }),
    nextAction: supported ? 'test_in_backtester' : adverse ? 'reject' : 'monitor_only',
    nextActionDetail: supported ? 'A/B earlier monetisation and cap-release rules against current hold logic.' : adverse ? 'Reject more cap loading until markouts or exits improve.' : 'Monitor cap pressure rather than adding inventory.',
    supportEvidence: [
      evidence('Near-cap time', formatPct(stats.nearCapRate), 'Inventory rows at or above 80% of limit', stats.nearCapRate != null && stats.nearCapRate > 0.2 ? 'warn' : 'neutral'),
      evidence('Final MTM', formatNumber(stats.finalMtm), 'Product replay capture', toneForValue(stats.finalMtm)),
      evidence('Unrealised share', formatPct(stats.unrealisedShare), 'Share of product MTM left open at mark', stats.unrealisedShare != null && stats.unrealisedShare > 0.6 ? 'warn' : 'neutral'),
    ],
    againstEvidence: [
      evidence('Replay dependency', 'Local-BT', 'Cap value depends on local fill and final mark assumptions', 'warn'),
      ...(stats.unrealisedShare != null && stats.unrealisedShare > 0.6 ? [evidence('Open inventory', formatPct(stats.unrealisedShare), 'PnL may be timing-sensitive rather than harvested', 'warn')] : []),
    ],
  })
}

function buildOneSidedHypothesis(product: Product, oneSided: { count: number; total: number; frequency: number | null }, sampleOnly: boolean): AlphaHypothesis | null {
  if (oneSided.total === 0) return null
  const label = PRODUCT_LABELS[product]
  const frequency = oneSided.frequency ?? 0
  const supported = oneSided.total >= MIN_SIGNAL_ROWS && oneSided.frequency != null && oneSided.frequency >= 0.01
  const classification: AlphaClassification = supported ? 'public_data' : 'weak_rejected'
  const confidence = supported ? clamp(0.42 + Math.min(0.3, frequency * 6), 0.42, 0.72) : 0.18

  return makeHypothesis({
    id: `${product}-one-sided-state`,
    name: `${label} one-sided state handling`,
    product: label,
    category: 'one-sided state',
    classification,
    confidence,
    sampleSize: oneSided.total,
    support: supported ? 'One-sided public states occur often enough to test a special rule.' : 'One-sided states are too sparse to prioritise.',
    exploitabilityNow: supported ? 'Low to medium, only as a guard or state filter' : 'Low',
    currentCapture: 'Not measured without state-specific fill rows',
    edgeSize: formatPct(oneSided.frequency),
    frequency: `${formatInt(oneSided.count)} rows`,
    robustness: sampleOnly ? 'Sample-path only' : 'Replay rows',
    websiteDependency: 'None for public state detection',
    implementationDifficulty: 'Low',
    likelyLeaderboardValue: supported ? 'Low' : 'Low',
    priorityScore: priorityScore({
      classification,
      confidence,
      edge: oneSided.frequency == null ? 0 : Math.min(1, oneSided.frequency * 8),
      frequency: sampleScore(oneSided.count, 50),
      robustness: sampleOnly ? 0.3 : 0.5,
      difficulty: 0.25,
    }),
    nextAction: supported ? 'test_in_backtester' : 'monitor_only',
    nextActionDetail: supported ? 'Add a guardrail test for one-sided books before any broad logic change.' : 'Keep as a rejection note, not a trading idea.',
    supportEvidence: [
      evidence('One-sided rows', formatInt(oneSided.count), 'Rows without a usable mid or spread'),
      evidence('Frequency', formatPct(oneSided.frequency), 'Share of product fair rows'),
    ],
    againstEvidence: [
      ...(supported ? [] : [evidence('Sparse state', formatPct(oneSided.frequency), 'Below 1% frequency threshold or too few rows', 'warn')]),
      evidence('No state PnL', 'Unavailable', 'Current schema does not attach PnL directly to one-sided states', 'warn'),
    ],
  })
}

function buildMafEvidence(payload: DashboardPayload): { panel: AlphaMafPanel; hypothesis: AlphaHypothesis | null } {
  const rows = getComparisonRows(payload).filter((row) => row.scenario || row.extra_access_enabled != null || row.maf_bid != null) as Round2ScenarioRow[]
  const winnerRows = payload.round2?.winnerRows ?? []
  const accessRows = rows.filter((row) => row.extra_access_enabled || row.contract_won || row.maf_bid != null)
  const breakEvens = accessRows.map((row) => numberOrNull(row.break_even_maf_vs_no_access ?? row.marginal_access_pnl_before_maf)).filter((value): value is number => value != null)
  const positiveBreakEvens = breakEvens.filter((value) => value > 0)
  const bestBreakEven = maxNumber(breakEvens)
  const medianBreakEven = median(breakEvens)
  const rankingShifts = winnerRows.filter((row) => row.ranking_changed_vs_no_access === true).length
  const scenarioCount = new Set(rows.map((row) => row.scenario).filter(Boolean)).size
  const panelRows = accessRows
    .map((row) => ({
      scenario: row.scenario ?? 'default',
      trader: row.trader,
      classification: 'Website-only edge',
      final_pnl: numberOrNull(row.final_pnl),
      access_edge: numberOrNull(row.marginal_access_pnl_before_maf),
      break_even_maf: numberOrNull(row.break_even_maf_vs_no_access),
      mc_mean: numberOrNull(row.mc_mean),
      mc_p05: numberOrNull(row.mc_p05),
    }))
    .sort((a, b) => (b.break_even_maf ?? -Infinity) - (a.break_even_maf ?? -Infinity))
    .slice(0, 16)

  const panel: AlphaMafPanel = {
    available: rows.length > 0,
    message: rows.length
      ? 'Scenario rows are local decision evidence. MAF cutoff and exact extra quote matching remain website-only.'
      : 'No Round 2 scenario or MAF rows are present in this bundle.',
    metrics: [
      metric('Scenario rows', formatInt(rows.length), 'Rows with scenario or access fields'),
      metric('Access rows', formatInt(accessRows.length), 'Rows with extra access or MAF assumptions'),
      metric('Best break-even MAF', formatNumber(bestBreakEven), 'Gross access edge before fee', toneForValue(bestBreakEven)),
      metric('Median break-even MAF', formatNumber(medianBreakEven), 'Across access rows', toneForValue(medianBreakEven)),
      metric('Positive access rows', formatPct(breakEvens.length ? positiveBreakEvens.length / breakEvens.length : null), `${formatInt(positiveBreakEvens.length)} of ${formatInt(breakEvens.length)}`),
      metric('Ranking shifts', formatInt(rankingShifts), 'Winner changed versus no-access baseline', rankingShifts > 0 ? 'warn' : 'neutral'),
    ],
    rows: panelRows,
  }

  if (!rows.length && !payload.meta?.accessScenario?.enabled) {
    return { panel, hypothesis: null }
  }

  const hasScenarioSupport = accessRows.length > 0 && breakEvens.length > 0
  const positiveRate = breakEvens.length ? positiveBreakEvens.length / breakEvens.length : null
  const priority = priorityScore({
    classification: hasScenarioSupport ? 'website_only' : 'weak_rejected',
    confidence: hasScenarioSupport ? clamp(0.3 + (positiveRate ?? 0) * 0.25, 0.3, 0.58) : 0.18,
    edge: normaliseAbs(bestBreakEven, 2000),
    frequency: sampleScore(accessRows.length, 20),
    robustness: rankingShifts > 0 ? 0.35 : 0.55,
    difficulty: 0.75,
  })

  return {
    panel,
    hypothesis: makeHypothesis({
      id: 'maf-access-sensitivity',
      name: 'MAF and extra-access sensitivity',
      product: 'Round 2 access',
      category: 'MAF / access',
      classification: hasScenarioSupport ? 'website_only' : 'weak_rejected',
      confidence: hasScenarioSupport ? clamp(0.3 + (positiveRate ?? 0) * 0.25, 0.3, 0.58) : 0.18,
      sampleSize: accessRows.length || null,
      support: hasScenarioSupport ? 'Local scenario rows estimate access value before MAF.' : 'The bundle has an access assumption but no scenario evidence.',
      exploitabilityNow: hasScenarioSupport && (bestBreakEven ?? 0) > 0 ? 'Blocked by website cutoff uncertainty' : 'Low',
      currentCapture: `Best break-even MAF ${formatNumber(bestBreakEven)}`,
      edgeSize: formatNumber(bestBreakEven),
      frequency: `${formatInt(accessRows.length)} access rows`,
      robustness: `${formatInt(scenarioCount)} scenarios`,
      websiteDependency: 'High: contract cutoff, hidden quote access and matching are unknown',
      implementationDifficulty: 'High',
      likelyLeaderboardValue: hasScenarioSupport && (bestBreakEven ?? 0) > 0 ? 'Potentially high but unresolved' : 'Low',
      priorityScore: priority,
      nextAction: hasScenarioSupport && (bestBreakEven ?? 0) > 0 ? 'ab_on_website' : 'test_in_backtester',
      nextActionDetail: hasScenarioSupport && (bestBreakEven ?? 0) > 0 ? 'Use scenario brackets to choose an A/B MAF bid, not as proof of website edge.' : 'Run a Round 2 scenario grid before bidding.',
      supportEvidence: [
        evidence('Best break-even', formatNumber(bestBreakEven), 'Gross access edge before fee', toneForValue(bestBreakEven)),
        evidence('Positive access rows', formatPct(positiveRate), 'Share of tested access rows with positive edge'),
        evidence('Ranking shifts', formatInt(rankingShifts), 'Scenario winner changed versus baseline', rankingShifts > 0 ? 'warn' : 'neutral'),
      ],
      againstEvidence: [
        evidence('Website dependency', 'High', 'Other teams bids and official extra quote mechanics are unknown', 'warn'),
        ...(breakEvens.length ? [] : [evidence('Scenario evidence', 'Missing', 'No break-even or marginal access rows found', 'bad')]),
      ],
    }),
  }
}

function buildMonteCarloHypothesis(payload: DashboardPayload): AlphaHypothesis | null {
  const summary = payload.monteCarlo?.summary
  if (!summary) return null
  const sessions = numberOrNull(summary.session_count)
  const positiveRate = numberOrNull(summary.positive_rate)
  const p05 = numberOrNull(summary.p05)
  const mean = numberOrNull(summary.mean)
  const supported = (sessions ?? 0) >= 20 && (positiveRate ?? 0) >= 0.6 && (p05 ?? -Infinity) >= 0
  const weak = (sessions ?? 0) < 20 || (p05 != null && p05 < 0)
  const classification: AlphaClassification = supported ? 'local_bt' : 'weak_rejected'
  const confidence = supported ? clamp(0.45 + (positiveRate ?? 0) * 0.25 + normaliseAbs(p05, 20_000) * 0.12, 0.45, 0.84) : weak ? 0.24 : 0.36

  return makeHypothesis({
    id: 'mc-robustness-support',
    name: 'Monte Carlo robustness support',
    product: 'Portfolio',
    category: 'scenario stability',
    classification,
    confidence,
    sampleSize: sessions,
    support: supported ? 'MC distribution supports the current script under local assumptions.' : 'MC downside or sample count is not strong enough.',
    exploitabilityNow: supported ? 'Medium, use as a release gate' : 'Low',
    currentCapture: `Mean ${formatNumber(mean)} / P05 ${formatNumber(p05)}`,
    edgeSize: formatNumber(mean),
    frequency: `${formatInt(sessions)} sessions`,
    robustness: `P05 ${formatNumber(p05)} / positive ${formatPct(positiveRate)}`,
    websiteDependency: 'Local synthetic path assumptions apply',
    implementationDifficulty: 'Low',
    likelyLeaderboardValue: supported ? 'Medium' : 'Low',
    priorityScore: priorityScore({
      classification,
      confidence,
      edge: normaliseAbs(mean, 40_000),
      frequency: sampleScore(sessions ?? 0, 80),
      robustness: p05 == null ? 0 : p05 >= 0 ? 0.9 : 0.25,
      difficulty: 0.2,
    }),
    nextAction: supported ? 'implement_now' : 'test_in_backtester',
    nextActionDetail: supported ? 'Use this as a gate to promote product-level candidates.' : 'Increase MC sessions or reduce downside before promoting.',
    supportEvidence: [
      evidence('Sessions', formatInt(sessions), 'Monte Carlo run count'),
      evidence('Mean', formatNumber(mean), 'Average final PnL', toneForValue(mean)),
      evidence('Positive rate', formatPct(positiveRate), 'Share of sessions above zero', toneForHitRate(positiveRate)),
    ],
    againstEvidence: [
      evidence('P05', formatNumber(p05), 'Downside percentile', p05 != null && p05 < 0 ? 'bad' : 'neutral'),
      evidence('Model boundary', 'Local-BT', 'Synthetic paths and fill assumptions are not website proof', 'warn'),
    ],
  })
}

function buildComparisonHypothesis(payload: DashboardPayload, comparePayload?: DashboardPayload | null): AlphaHypothesis | null {
  const rows = getComparisonRows(payload)
  if (rows.length >= 2) {
    const winner = rows[0]
    const runnerUp = rows[1]
    const gap = delta(winner.final_pnl, runnerUp.final_pnl)
    const supported = gap != null && gap > 0
    const confidence = supported ? clamp(0.35 + normaliseAbs(gap, 10_000) * 0.2 + sampleScore(rows.length, 8) * 0.08, 0.35, 0.68) : 0.24
    const classification: AlphaClassification = supported ? 'local_bt' : 'weak_rejected'
    return makeHypothesis({
      id: 'comparison-capture-delta',
      name: 'Current-vs-baseline capture delta',
      product: 'Portfolio',
      category: 'current script capture',
      classification,
      confidence,
      sampleSize: rows.length,
      support: supported ? 'Comparison rows show a positive gap to the next script.' : 'Comparison rows do not show a usable gap.',
      exploitabilityNow: supported ? 'Medium as a ranking input, not an alpha proof' : 'Low',
      currentCapture: `${winner.trader} leads by ${formatNumber(gap)}`,
      edgeSize: formatNumber(gap),
      frequency: `${formatInt(rows.length)} comparison rows`,
      robustness: 'Single comparison bundle',
      websiteDependency: 'Local replay assumptions apply',
      implementationDifficulty: 'Low',
      likelyLeaderboardValue: supported ? 'Medium if robust elsewhere' : 'Low',
      priorityScore: priorityScore({
        classification,
        confidence,
        edge: normaliseAbs(gap, 10_000),
        frequency: sampleScore(rows.length, 8),
        robustness: 0.35,
        difficulty: 0.15,
      }),
      nextAction: 'test_in_backtester',
      nextActionDetail: 'Use the gap to prioritise MC and scenario tests, not as standalone alpha.',
      supportEvidence: [
        evidence('Winner', String(winner.trader ?? 'not available'), `PnL ${formatNumber(numberOrNull(winner.final_pnl))}`, 'accent'),
        evidence('Gap to second', formatNumber(gap), 'Winner minus runner-up', toneForValue(gap)),
      ],
      againstEvidence: [
        evidence('Interpretation guard', 'Performance', 'This is script capture evidence, not a latent market edge by itself', 'warn'),
      ],
    })
  }

  if (payload.summary && comparePayload?.summary) {
    const gap = delta(payload.summary.final_pnl, comparePayload.summary.final_pnl)
    const supported = gap != null && gap > 0
    const classification: AlphaClassification = supported ? 'local_bt' : 'weak_rejected'
    const confidence = supported ? 0.36 : 0.2
    return makeHypothesis({
      id: 'side-by-side-capture-delta',
      name: 'Loaded replay capture delta',
      product: 'Portfolio',
      category: 'current script capture',
      classification,
      confidence,
      sampleSize: 2,
      support: supported ? 'Active run beats the selected comparison replay.' : 'Active run does not beat the selected comparison replay.',
      exploitabilityNow: 'Low without a generated comparison bundle',
      currentCapture: `Delta ${formatNumber(gap)}`,
      edgeSize: formatNumber(gap),
      frequency: '2 loaded replays',
      robustness: 'Ad hoc side-by-side only',
      websiteDependency: 'Local replay assumptions apply',
      implementationDifficulty: 'Low',
      likelyLeaderboardValue: 'Low until scenario-tested',
      priorityScore: priorityScore({
        classification,
        confidence,
        edge: normaliseAbs(gap, 10_000),
        frequency: 0.2,
        robustness: 0.2,
        difficulty: 0.15,
      }),
      nextAction: 'test_in_backtester',
      nextActionDetail: 'Generate a comparison bundle and MC runs before acting on the delta.',
      supportEvidence: [evidence('Replay delta', formatNumber(gap), 'Active run minus compare run', toneForValue(gap))],
      againstEvidence: [evidence('Support warning', 'Two runs', 'No scenario or MC robustness attached to this delta', 'warn')],
    })
  }

  return null
}

function buildCrossDayHypothesis(payload: DashboardPayload): AlphaHypothesis | null {
  const rows = payload.sessionRows ?? []
  if (rows.length < 2) return null
  const finalPnls = rows.map((row) => numberOrNull((row as Record<string, unknown>).final_pnl)).filter((value): value is number => value != null)
  if (finalPnls.length < 2) return null
  const positiveRate = finalPnls.filter((value) => value > 0).length / finalPnls.length
  const minPnl = Math.min(...finalPnls)
  const meanPnl = mean(finalPnls)
  const supported = positiveRate >= 0.67 && minPnl >= 0
  const classification: AlphaClassification = supported ? 'local_bt' : 'weak_rejected'
  const confidence = supported ? clamp(0.42 + positiveRate * 0.22, 0.42, 0.76) : 0.24

  return makeHypothesis({
    id: 'cross-day-stability',
    name: 'Cross-day replay stability',
    product: 'Portfolio',
    category: 'scenario stability',
    classification,
    confidence,
    sampleSize: finalPnls.length,
    support: supported ? 'Replay PnL is positive across available days.' : 'Replay day outcomes are mixed or sparse.',
    exploitabilityNow: supported ? 'Medium as a release filter' : 'Low',
    currentCapture: `Mean ${formatNumber(meanPnl)} / worst ${formatNumber(minPnl)}`,
    edgeSize: formatNumber(meanPnl),
    frequency: `${formatInt(finalPnls.length)} days`,
    robustness: formatPct(positiveRate),
    websiteDependency: 'Local replay assumptions apply',
    implementationDifficulty: 'Low',
    likelyLeaderboardValue: supported ? 'Medium' : 'Low',
    priorityScore: priorityScore({
      classification,
      confidence,
      edge: normaliseAbs(meanPnl, 30_000),
      frequency: sampleScore(finalPnls.length, 3),
      robustness: minPnl >= 0 ? 0.8 : 0.25,
      difficulty: 0.2,
    }),
    nextAction: supported ? 'implement_now' : 'monitor_only',
    nextActionDetail: supported ? 'Use stable days as a gate for product candidates.' : 'Do not promote candidates that only work on one day.',
    supportEvidence: [
      evidence('Positive days', formatPct(positiveRate), `${formatInt(finalPnls.length)} day rows`, toneForHitRate(positiveRate)),
      evidence('Mean day PnL', formatNumber(meanPnl), 'Session row average', toneForValue(meanPnl)),
    ],
    againstEvidence: [
      evidence('Worst day', formatNumber(minPnl), 'Weakest available day', minPnl < 0 ? 'bad' : 'neutral'),
      evidence('Sample limit', formatInt(finalPnls.length), 'Only generated day rows are available', 'warn'),
    ],
  })
}

function computeResidualStats(rows: AlphaFairRow[]): ResidualStats {
  const groups = groupByRunDay(rows)
  const residuals: number[] = []
  const aligned1: number[] = []
  const aligned5: number[] = []
  const hits1: boolean[] = []
  const hits5: boolean[] = []
  const fades5: boolean[] = []
  const observations: Array<{ residual: number; next1: number | null; next5: number | null; aligned5: boolean | null }> = []

  for (const group of groups) {
    for (let index = 0; index < group.length; index++) {
      const row = group[index]
      const fair = numberOrNull(row.analysis_fair)
      const mid = numberOrNull(row.mid)
      if (fair == null || mid == null) continue
      const residual = fair - mid
      residuals.push(residual)
      const next1 = nextMove(group, index, 1)
      const next5 = nextMove(group, index, 5)
      if (next1 != null && residual !== 0) {
        const value = Math.sign(residual) * next1
        aligned1.push(value)
        hits1.push(value > 0)
      }
      if (next5 != null && residual !== 0) {
        const value = Math.sign(residual) * next5
        aligned5.push(value)
        hits5.push(value > 0)
        fades5.push(value < 0)
      }
      observations.push({
        residual,
        next1,
        next5,
        aligned5: next5 == null || residual === 0 ? null : Math.sign(residual) * next5 > 0,
      })
    }
  }

  const absResiduals = residuals.map(Math.abs)
  const p75Abs = quantile(absResiduals, 0.75)
  return {
    sampleCount: residuals.length,
    meanAbsResidual: mean(absResiduals),
    p75AbsResidual: p75Abs,
    hitRate1: rate(hits1),
    hitRate5: rate(hits5),
    fadeRate5: rate(fades5),
    meanAlignedMove1: mean(aligned1),
    meanAlignedMove5: mean(aligned5),
    conditionRows: buildConditionalRows(observations, p75Abs),
  }
}

function computeImbalanceStats(rows: AlphaFairRow[]): ImbalanceStats {
  const groups = groupByRunDay(rows)
  const values: number[] = []
  const tailValues: number[] = []
  const hits5: boolean[] = []
  const aligned5: number[] = []

  for (const group of groups) {
    for (let index = 0; index < group.length; index++) {
      const row = group[index]
      const micro = numberOrNull(row.microprice)
      const mid = numberOrNull(row.mid)
      const spread = numberOrNull(row.spread)
      if (micro == null || mid == null || spread == null || spread <= 0) continue
      const imbalance = clamp((micro - mid) / (spread / 2), -1, 1)
      values.push(imbalance)
      if (Math.abs(imbalance) >= 0.25) tailValues.push(imbalance)
      const move5 = nextMove(group, index, 5)
      if (move5 != null && imbalance !== 0) {
        const aligned = Math.sign(imbalance) * move5
        aligned5.push(aligned)
        hits5.push(aligned > 0)
      }
    }
  }

  return {
    sampleCount: values.length,
    tailCount: tailValues.length,
    meanAbsImbalance: mean(values.map(Math.abs)),
    hitRate5: rate(hits5),
    meanAlignedMove5: mean(aligned5),
  }
}

function computeMarkoutStats(fills: AlphaFillRow[]): MarkoutStats {
  const markout1 = fills.map((row) => numberOrNull(row.markout_1)).filter((value): value is number => value != null)
  const markout5 = fills.map((row) => numberOrNull(row.markout_5)).filter((value): value is number => value != null)
  const edges = fills.map((row) => numberOrNull(row.signed_edge_to_analysis_fair)).filter((value): value is number => value != null)
  const positive5 = markout5.map((value) => value > 0)
  return {
    count: fills.length,
    qty: fills.reduce((acc, row) => acc + Math.abs(Number(row.quantity) || 0), 0),
    markout1: mean(markout1),
    markout5: mean(markout5),
    positiveRate5: rate(positive5),
    edge: mean(edges),
  }
}

function computeInventoryStats(
  inventoryRows: AlphaInventoryRow[],
  pnlRows: AlphaPnlRow[],
  behaviour: Partial<BehaviourPerProduct> | undefined,
  productSummary: ProductSummary | undefined,
): InventoryStats {
  const positions = inventoryRows.map((row) => numberOrNull(row.position)).filter((value): value is number => value != null)
  const absPositions = positions.map((value) => Math.abs(value))
  const capUsage = numberOrNull(behaviour?.cap_usage_ratio) ?? (absPositions.length ? Math.max(...absPositions) / POSITION_LIMIT : null)
  const nearCapCount = absPositions.filter((value) => value >= POSITION_LIMIT * 0.8).length
  const atCapCount = absPositions.filter((value) => value >= POSITION_LIMIT).length
  const totalBuy = numberOrNull(behaviour?.total_buy_qty)
  const totalSell = numberOrNull(behaviour?.total_sell_qty)
  const turnover = totalBuy != null && totalSell != null ? totalBuy + totalSell : null
  const recycleEfficiency = turnover && turnover > 0 ? 1 - Math.abs((totalBuy ?? 0) - (totalSell ?? 0)) / turnover : null
  const finalMtm = numberOrNull(productSummary?.final_mtm) ?? numberOrNull(behaviour?.final_mtm) ?? numberOrNull(pnlRows[pnlRows.length - 1]?.mtm)
  const realised = numberOrNull(productSummary?.realised) ?? numberOrNull(pnlRows[pnlRows.length - 1]?.realised)
  const unrealised = numberOrNull(productSummary?.unrealised) ?? numberOrNull(pnlRows[pnlRows.length - 1]?.unrealised)
  const unrealisedShare = finalMtm != null && finalMtm !== 0 && unrealised != null ? Math.abs(unrealised) / Math.abs(finalMtm) : null

  return {
    sampleCount: inventoryRows.length,
    capUsage,
    nearCapRate: inventoryRows.length ? nearCapCount / inventoryRows.length : numberOrNull(behaviour?.time_near_cap_ratio),
    atCapRate: inventoryRows.length ? atCapCount / inventoryRows.length : null,
    recycleEfficiency,
    unrealisedShare,
    finalMtm,
    realised,
  }
}

function computeOneSidedStats(rows: AlphaFairRow[]) {
  if (!rows.length) return { count: 0, total: 0, frequency: null }
  const count = rows.filter((row) => numberOrNull(row.mid) == null || numberOrNull(row.spread) == null).length
  return {
    count,
    total: rows.length,
    frequency: count / rows.length,
  }
}

function groupByRunDay(rows: AlphaFairRow[]): AlphaFairRow[][] {
  const groups = new Map<string, AlphaFairRow[]>()
  for (const row of rows) {
    const key = `${row.__alphaRun ?? 'active'}|${row.day}`
    const bucket = groups.get(key)
    if (bucket) bucket.push(row)
    else groups.set(key, [row])
  }
  return [...groups.values()].map((group) => group.sort((a, b) => Number(a.timestamp) - Number(b.timestamp)))
}

function nextMove(group: AlphaFairRow[], index: number, horizon: number): number | null {
  const currentMid = numberOrNull(group[index]?.mid)
  const futureMid = numberOrNull(group[Math.min(group.length - 1, index + horizon)]?.mid)
  if (currentMid == null || futureMid == null || index + horizon >= group.length) return null
  return futureMid - currentMid
}

function buildConditionalRows(
  observations: Array<{ residual: number; next1: number | null; next5: number | null; aligned5: boolean | null }>,
  p75Abs: number | null,
): ConditionalRow[] {
  const buckets = [
    { state: 'Fair above mid', rows: observations.filter((row) => row.residual > 0) },
    { state: 'Fair below mid', rows: observations.filter((row) => row.residual < 0) },
    { state: 'Large positive residual', rows: observations.filter((row) => p75Abs != null && row.residual >= p75Abs) },
    { state: 'Large negative residual', rows: observations.filter((row) => p75Abs != null && row.residual <= -p75Abs) },
  ]

  return buckets
    .filter((bucket) => bucket.rows.length > 0)
    .map((bucket) => ({
      state: bucket.state,
      support: bucket.rows.length,
      mean_residual: mean(bucket.rows.map((row) => row.residual)),
      next_1_mean: mean(bucket.rows.map((row) => row.next1).filter((value): value is number => value != null)),
      next_5_mean: mean(bucket.rows.map((row) => row.next5).filter((value): value is number => value != null)),
      hit_rate_5: rate(bucket.rows.map((row) => row.aligned5).filter((value): value is boolean => value != null)),
    }))
}

function buildRobustnessRows(payload: DashboardPayload, hypotheses: AlphaHypothesis[]): RobustnessRow[] {
  const rows: RobustnessRow[] = []
  const mc = payload.monteCarlo?.summary
  if (mc) {
    rows.push({
      source: 'Monte Carlo',
      classification: 'Local-BT edge',
      support: `Mean ${formatNumber(numberOrNull(mc.mean))}, positive ${formatPct(numberOrNull(mc.positive_rate))}`,
      against: `P05 ${formatNumber(numberOrNull(mc.p05))}, ES05 ${formatNumber(numberOrNull(mc.expected_shortfall_05))}`,
      action: 'Use as robustness gate',
      tone: numberOrNull(mc.p05) != null && Number(mc.p05) >= 0 ? 'good' : 'warn',
    })
  }
  const sessionRows = payload.sessionRows ?? []
  if (sessionRows.length > 1) {
    const pnls = sessionRows.map((row) => numberOrNull((row as Record<string, unknown>).final_pnl)).filter((value): value is number => value != null)
    if (pnls.length > 1) {
      rows.push({
        source: 'Cross-day replay',
        classification: 'Local-BT edge',
        support: `Positive days ${formatPct(pnls.filter((value) => value > 0).length / pnls.length)}`,
        against: `Worst day ${formatNumber(Math.min(...pnls))}`,
        action: 'Reject one-day-only ideas',
        tone: Math.min(...pnls) >= 0 ? 'good' : 'warn',
      })
    }
  }
  const round2 = payload.round2
  if (round2?.winnerRows?.length) {
    const shifts = round2.winnerRows.filter((row) => row.ranking_changed_vs_no_access).length
    rows.push({
      source: 'Round 2 scenarios',
      classification: 'Website-only edge',
      support: `${formatInt(round2.winnerRows.length)} winner rows`,
      against: `${formatInt(shifts)} ranking shifts under access assumptions`,
      action: 'Treat MAF as unresolved until website-tested',
      tone: shifts > 0 ? 'warn' : 'neutral',
    })
  }
  const strongCount = hypotheses.filter((item) => item.bucket === 'strong').length
  rows.push({
    source: 'Hypothesis registry',
    classification: 'Evidence engine',
    support: `${formatInt(strongCount)} strong hypotheses`,
    against: `${formatInt(hypotheses.filter((item) => item.classification === 'weak_rejected').length)} weak or rejected`,
    action: 'Prioritise high evidence score only',
    tone: strongCount > 0 ? 'good' : 'neutral',
  })
  return rows
}

function buildNextTests(hypotheses: AlphaHypothesis[]): NextTestRow[] {
  return hypotheses
    .filter((item) => item.nextAction !== 'monitor_only' || item.priorityScore >= 45)
    .slice(0, 10)
    .map((item, index) => ({
      rank: index + 1,
      action: ALPHA_ACTION_LABELS[item.nextAction],
      hypothesis: item.name,
      classification: ALPHA_CLASS_LABELS[item.classification],
      reason: item.nextActionDetail,
      priority: `${item.priorityLabel} (${Math.round(item.priorityScore)})`,
    }))
}

function makeBuckets(hypotheses: AlphaHypothesis[]): Record<AlphaBucket, AlphaHypothesis[]> {
  return {
    active: hypotheses.filter((item) => item.bucket === 'active'),
    testing: hypotheses.filter((item) => item.bucket === 'testing'),
    strong: hypotheses.filter((item) => item.bucket === 'strong'),
    website: hypotheses.filter((item) => item.bucket === 'website'),
    rejected: hypotheses.filter((item) => item.bucket === 'rejected'),
  }
}

function makeHypothesis(input: Omit<AlphaHypothesis, 'bucket' | 'priorityLabel'>): AlphaHypothesis {
  const bucket = bucketFor(input.classification, input.confidence, input.priorityScore, input.nextAction)
  return {
    ...input,
    bucket,
    priorityLabel: priorityLabel(input.classification, input.priorityScore),
  }
}

function bucketFor(classification: AlphaClassification, confidence: number | null, priorityScoreValue: number, action: AlphaAction): AlphaBucket {
  if (classification === 'weak_rejected' || action === 'reject') return 'rejected'
  if (classification === 'website_only') return 'website'
  if ((confidence ?? 0) >= 0.68 && priorityScoreValue >= 62) return 'strong'
  if (action === 'test_in_backtester') return 'testing'
  return 'active'
}

function priorityLabel(classification: AlphaClassification, score: number): AlphaHypothesis['priorityLabel'] {
  if (classification === 'weak_rejected' || score < 30) return 'Reject'
  if (score >= 68) return 'High'
  if (score >= 48) return 'Medium'
  return 'Low'
}

function priorityScore(input: {
  classification: AlphaClassification
  confidence: number | null
  edge: number
  frequency: number
  robustness: number
  difficulty: number
}): number {
  if (input.classification === 'weak_rejected') {
    return clamp((input.confidence ?? 0.2) * 22 + input.edge * 8 + input.frequency * 6, 5, 34)
  }
  const websitePenalty = input.classification === 'website_only' ? 12 : 0
  const raw =
    (input.confidence ?? 0.35) * 34 +
    clamp(input.edge, 0, 1) * 22 +
    clamp(input.frequency, 0, 1) * 16 +
    clamp(input.robustness, 0, 1) * 18 -
    clamp(input.difficulty, 0, 1) * 10 -
    websitePenalty
  return clamp(raw, 0, 94)
}

function evidence(label: string, value: string, detail?: string, tone: AlphaTone = 'neutral'): AlphaEvidence {
  return { label, value, detail, tone }
}

function metric(label: string, value: string, detail?: string, tone: AlphaTone = 'neutral'): AlphaMetric {
  return { label, value, detail, tone }
}

function productMessages(replay: ReplayEvidence, fairRows: AlphaFairRow[], fills: AlphaFillRow[], inventory: AlphaInventoryRow[]): string[] {
  const messages: string[] = []
  if (!fairRows.length) messages.push('Residual and imbalance evidence require replay-compatible fair-value rows.')
  if (!fills.length) messages.push('Markout evidence requires fill rows with markout fields.')
  if (!inventory.length) messages.push('Cap and inventory efficiency evidence requires inventory rows.')
  if (replay.sampleOnly) messages.push('Metrics are computed from saved Monte Carlo sample paths, not every MC session.')
  return messages
}

function evidenceSources(payload: DashboardPayload, replay: ReplayEvidence): string[] {
  const sources: string[] = []
  if (replay.fairRows.length || replay.fills.length || replay.inventory.length) sources.push(replay.source)
  if (payload.monteCarlo?.summary) sources.push('Monte Carlo summary')
  if (getComparisonRows(payload).length) sources.push('Comparison or scenario rows')
  if (payload.round2?.winnerRows?.length) sources.push('Round 2 winner diagnostics')
  return sources.length ? sources : ['No supported Alpha Lab evidence sections found']
}

function confidenceFromHitRate(hitRate: number | null, sampleCount: number, sampleOnly: boolean): number {
  if (hitRate == null || sampleCount === 0) return 0.2
  const sampleComponent = clamp(Math.log10(sampleCount) / 4, 0, sampleOnly ? 0.5 : 0.68)
  const signalComponent = clamp((hitRate - 0.5) * 3, -0.18, 0.24)
  return clamp(0.32 + sampleComponent + signalComponent - (sampleOnly ? 0.08 : 0), 0.16, sampleOnly ? 0.72 : 0.88)
}

function sampleScore(sampleCount: number, target: number): number {
  if (sampleCount <= 0 || target <= 0) return 0
  return clamp(Math.log10(sampleCount + 1) / Math.log10(target + 1), 0, 1)
}

function normaliseAbs(value: number | null | undefined, scale: number): number {
  if (value == null || !Number.isFinite(value) || scale <= 0) return 0
  return clamp(Math.abs(value) / scale, 0, 1)
}

function toneForValue(value: number | null | undefined): AlphaTone {
  if (value == null || !Number.isFinite(value)) return 'neutral'
  if (value > 0) return 'good'
  if (value < 0) return 'bad'
  return 'neutral'
}

function toneForHitRate(value: number | null | undefined): AlphaTone {
  if (value == null || !Number.isFinite(value)) return 'neutral'
  if (value >= 0.56) return 'good'
  if (value >= 0.52) return 'warn'
  if (value < 0.48) return 'bad'
  return 'neutral'
}

function mean(values: number[]): number | null {
  const clean = values.filter((value) => Number.isFinite(value))
  if (!clean.length) return null
  return clean.reduce((acc, value) => acc + value, 0) / clean.length
}

function median(values: number[]): number | null {
  return quantile(values, 0.5)
}

function quantile(values: number[], q: number): number | null {
  const clean = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b)
  if (!clean.length) return null
  if (clean.length === 1) return clean[0]
  const index = q * (clean.length - 1)
  const lo = Math.floor(index)
  const hi = Math.ceil(index)
  if (lo === hi) return clean[lo]
  const weight = index - lo
  return clean[lo] * (1 - weight) + clean[hi] * weight
}

function rate(values: boolean[]): number | null {
  if (!values.length) return null
  return values.filter(Boolean).length / values.length
}

function maxNumber(values: number[]): number | null {
  const clean = values.filter((value) => Number.isFinite(value))
  return clean.length ? Math.max(...clean) : null
}

function delta(a: unknown, b: unknown): number | null {
  const left = numberOrNull(a)
  const right = numberOrNull(b)
  return left == null || right == null ? null : left - right
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return '-'
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function formatInt(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '-'
  return Math.round(value).toLocaleString(undefined, { maximumFractionDigits: 0 })
}

function formatPct(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return '-'
  return `${(value * 100).toFixed(digits)}%`
}
