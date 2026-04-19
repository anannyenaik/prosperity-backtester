// Core dashboard payload types

export interface Meta {
  schemaVersion: number
  runName: string
  traderName: string
  mode: string
  fillModel: FillModelInfo
  perturbations: Record<string, number>
  createdAt: string
}

export interface FillModelInfo {
  name: string
  passive_fill_rate: number
  same_price_queue_share: number
  queue_pressure: number
  missed_fill_probability: number
  adverse_selection_ticks: number
  aggressive_slippage_ticks: number
}

export interface Assumptions {
  exact: string[]
  approximate: string[]
}

export interface DatasetReport {
  day: number
  metadata: Record<string, unknown>
  validation: {
    timestamps?: number
    issue_score?: number
    missing_products?: Record<string, unknown>
    crossed_book_rows?: number
    one_sided_book_rows?: number
    duplicate_book_rows?: number
    source?: string
  }
}

// Per-product / summary

export interface ProductSummary {
  cash: number
  realised: number
  unrealised: number
  final_mtm: number
  final_position: number
  avg_entry_price: number
}

export interface Summary {
  final_pnl: number
  fill_count: number
  order_count: number
  limit_breaches: number
  max_drawdown: number
  final_positions: Record<string, number>
  per_product: Record<string, ProductSummary>
  fair_value: Record<string, unknown>
  behaviour: Record<string, unknown>
}

// Series rows

export interface OrderRow {
  timestamp: number
  product: string
  submitted_price: number
  submitted_quantity: number
  position_before: number
  fill_model: string
  latency_ticks: number
  day: number
  best_bid: number | null
  best_ask: number | null
  mid: number | null
  reference_fair: number | null
  order_role: string
  distance_to_touch: number | null
  analysis_fair: number | null
  signed_edge_to_analysis_fair: number | null
}

export interface FillRow {
  timestamp: number
  product: string
  side: 'buy' | 'sell'
  price: number
  quantity: number
  kind: 'aggressive_visible' | 'passive_approx'
  exact: boolean
  source_trade_price: number
  day: number
  mid: number | null
  reference_fair: number | null
  best_bid: number | null
  best_ask: number | null
  markout_1: number | null
  markout_5: number | null
  analysis_fair: number | null
  signed_edge_to_analysis_fair: number | null
}

export interface PnlRow {
  timestamp: number
  product: string
  cash: number
  realised: number
  unrealised: number
  mtm: number
  mark: number
  mid: number | null
  fair: number | null
  spread: number | null
  position: number
  day: number
}

export interface InventoryRow {
  timestamp: number
  product: string
  position: number
  avg_entry_price: number
  mid: number | null
  fair: number | null
  day: number
}

export interface FairValueRow {
  day: number
  product: string
  timestamp: number
  analysis_fair: number | null
  mid: number | null
  [key: string]: unknown
}

export interface BehaviourRow {
  timestamp: number
  product: string
  day: number
  order_count: number
  fill_count: number
  net_fill_qty: number
  aggressive_fill_count: number
  passive_fill_count: number
  abs_position_ratio: number
  buy_order_qty: number
  sell_order_qty: number
  buy_fill_qty: number
  sell_fill_qty: number
}

// Behaviour summaries

export interface BehaviourPerProduct {
  cap_usage_ratio: number
  peak_abs_position: number
  average_fill_markout_5: number | null
  average_fill_markout_1: number | null
  total_fills: number
  passive_fill_count: number
  aggressive_fill_count: number
  total_buy_qty: number
  total_sell_qty: number
  [key: string]: unknown
}

export interface BehaviourData {
  per_product: Record<string, BehaviourPerProduct>
  summary: {
    dominant_risk_product: string
    dominant_turnover_product: string
  }
  series?: BehaviourRow[]
}

// Monte Carlo

export interface McSessionSummary {
  session_count: number
  mean: number
  std: number
  p05: number
  p50: number
  p95: number
  expected_shortfall_05: number
  min: number
  max: number
  positive_rate: number
  mean_max_drawdown: number
  max_limit_breaches: number
  per_product: Record<string, { mean: number; min: number; max: number }>
}

export interface FairBandPoint {
  timestamp: number
  p10: number
  p25: number
  p50: number
  p75: number
  p90: number
}

export interface McSession {
  run_name: string
  trader_name: string
  mode: string
  final_pnl: number
  fill_count: number
  limit_breaches: number
  days: number[]
  per_product: Record<string, { final_mtm: number }>
  fill_model: Record<string, unknown>
  perturbations: Record<string, unknown>
  fair_value_summary: Record<string, unknown>
  behaviour_summary: Record<string, unknown>
}

export interface SampleRun {
  runName: string
  summary: Summary
  inventorySeries: InventoryRow[]
  pnlSeries: PnlRow[]
  fills: FillRow[]
  fairValueSeries: FairValueRow[]
  behaviour: BehaviourData
  behaviourSeries: BehaviourRow[]
}

export interface MonteCarloData {
  summary: McSessionSummary
  sessions: McSession[]
  sampleRuns: SampleRun[]
  fairValueBands: {
    analysisFair: Record<string, FairBandPoint[]>
    mid: Record<string, FairBandPoint[]>
  }
}

// Calibration

export interface CalibrationCandidate {
  fill_model: string
  passive_fill_scale: number
  adverse_selection_ticks: number
  latency_ticks: number
  missed_fill_additive: number
  score: number
  profit_error: number
  path_rmse: number
  position_l1_error: number
  osmium_pnl_error: number | null
  osmium_path_rmse: number | null
  pepper_pnl_error: number | null
  pepper_path_rmse: number | null
  fill_count_error: number | null
  dominant_error_source: string | null
}

export interface CalibrationData {
  grid: CalibrationCandidate[]
  best: Partial<CalibrationCandidate>
  diagnostics: {
    candidate_count: number
    by_fill_model: Record<string, {
      candidate_count: number
      best_score: number | null
      mean_score: number | null
      mean_profit_error: number | null
      mean_path_rmse: number | null
    }>
    profit_bias_counts: Record<string, number>
    fill_bias_counts: Record<string, number>
    per_product: Record<string, {
      mean_abs_pnl_error: number | null
      mean_path_rmse: number | null
      best_path_rmse: number | null
    }>
  }
}

// Optimisation

export interface OptimizationRow {
  variant: string
  score: number
  replay_final_pnl: number
  mc_p05: number
  mc_expected_shortfall_05: number
  mc_std: number
  mc_mean_drawdown: number
}

export interface OptimizationData {
  rows: OptimizationRow[]
  diagnostics: {
    variant_count: number
    best_score_variant: string
    best_replay_variant: string
    best_downside_variant: string
    most_stable_variant: string
    score_gap_to_second: number | null
    frontier: OptimizationRow[]
  }
}

// Comparison

export interface ComparisonRow {
  trader: string
  final_pnl: number
  max_drawdown: number
  fill_count: number
  limit_breaches: number
  pepper_cap_usage: number | null
  pepper_markout_5: number | null
  [key: string]: unknown
}

// Top-level payload

export interface DashboardPayload {
  type: string
  meta: Meta
  products: string[]
  assumptions: Assumptions
  datasetReports: DatasetReport[]
  validation: Record<string, unknown>
  summary?: Summary
  orders?: OrderRow[]
  fills?: FillRow[]
  inventorySeries?: InventoryRow[]
  pnlSeries?: PnlRow[]
  fairValueSeries?: FairValueRow[]
  fairValueSummary?: Record<string, unknown>
  behaviour?: BehaviourData
  behaviourSeries?: BehaviourRow[]
  sessionRows?: unknown[]
  monteCarlo?: MonteCarloData
  comparison?: ComparisonRow[]
  comparisonDiagnostics?: Record<string, unknown>
  calibration?: CalibrationData
  optimization?: OptimizationData
}

// App-level

export interface LoadedRun {
  id: string
  name: string
  fileName: string
  payload: DashboardPayload
}

export type Product = 'ASH_COATED_OSMIUM' | 'INTARIAN_PEPPER_ROOT'
export const PRODUCTS: Product[] = ['ASH_COATED_OSMIUM', 'INTARIAN_PEPPER_ROOT']
export const PRODUCT_LABELS: Record<Product, string> = {
  ASH_COATED_OSMIUM: 'Osmium',
  INTARIAN_PEPPER_ROOT: 'Pepper',
}
export const POSITION_LIMIT = 80

export type TabId =
  | 'overview'
  | 'replay'
  | 'montecarlo'
  | 'calibration'
  | 'compare'
  | 'optimize'
  | 'inspect'
  | 'osmium'
  | 'pepper'
