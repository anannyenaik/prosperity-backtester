use anyhow::{bail, Context, Result};
use rand::distributions::{Distribution, WeightedIndex};
use rand::{Rng, SeedableRng};
use rand_chacha::ChaCha8Rng;
use rand_distr::Normal;
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, HashMap};
use std::env;
use std::fs;
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::time::Instant;

const OSMIUM: &str = "ASH_COATED_OSMIUM";
const PEPPER: &str = "INTARIAN_PEPPER_ROOT";
const PRODUCTS: [&str; 2] = [OSMIUM, PEPPER];
const TIMESTAMP_STEP: i32 = 100;

#[derive(Debug, Deserialize)]
struct RustMcConfig {
    run_name: String,
    trader_path: String,
    trader_overrides_path: Option<String>,
    python_bin: String,
    worker_script: String,
    base_seed: u64,
    days: Vec<i32>,
    session_indices: Vec<usize>,
    worker_count: usize,
    tick_count: usize,
    path_bucket_count: usize,
    print_trader_output: bool,
    fill_model: RustFillModelConfig,
    perturbation: RustPerturbationConfig,
    simulation: RustSimulationConfig,
}

#[derive(Debug, Deserialize)]
struct RustSimulationConfig {
    products: HashMap<String, ProductSimulationConfig>,
}

#[derive(Debug, Deserialize, Clone)]
struct ProductSimulationConfig {
    start_candidates: Vec<f64>,
    drift_per_tick: f64,
    simulation_noise_std: f64,
    trade_active_prob: f64,
    second_trade_prob: f64,
    trade_buy_prob: f64,
    bot3_bid_rate: f64,
    bot3_ask_rate: f64,
    outer_spread: IntSamplerConfig,
    inner_spread: IntSamplerConfig,
    outer_bid_vol: IntSamplerConfig,
    inner_bid_vol: IntSamplerConfig,
    trade_qty: IntSamplerConfig,
}

#[derive(Debug, Deserialize, Clone)]
struct IntSamplerConfig {
    values: Vec<i32>,
    weights: Vec<u32>,
}

#[derive(Debug, Deserialize, Clone)]
struct RustFillModelConfig {
    fill_rate_multiplier: f64,
    missed_fill_additive: f64,
    slippage_multiplier: f64,
    products: HashMap<String, ProductFillConfigSet>,
}

#[derive(Debug, Deserialize, Clone)]
struct ProductFillConfigSet {
    normal: RustProductFillConfig,
    thin_depth: RustProductFillConfig,
    wide_spread: RustProductFillConfig,
    one_sided: RustProductFillConfig,
}

#[derive(Debug, Deserialize, Clone)]
struct RustProductFillConfig {
    passive_fill_rate: f64,
    same_price_queue_share: f64,
    queue_pressure: f64,
    missed_fill_probability: f64,
    passive_adverse_selection_ticks: f64,
    aggressive_slippage_ticks: f64,
    aggressive_adverse_selection_ticks: f64,
    size_slippage_threshold: i32,
    size_slippage_rate: f64,
    size_slippage_power: f64,
    max_size_slippage_ticks: f64,
    wide_spread_threshold: Option<i32>,
    thin_depth_threshold: i32,
}

#[derive(Debug, Deserialize)]
struct RustPerturbationConfig {
    passive_fill_scale: f64,
    missed_fill_additive: f64,
    spread_shift_ticks: i32,
    order_book_volume_scale: f64,
    price_noise_std: f64,
    latency_ticks: usize,
    adverse_selection_ticks: f64,
    slippage_multiplier: f64,
    reentry_probability: f64,
    trade_matching_mode: String,
    position_limits: HashMap<String, i32>,
    shock_tick: Option<usize>,
    shock_by_product: HashMap<String, f64>,
}

#[derive(Clone)]
struct WeightedSampler {
    distribution: WeightedIndex<u32>,
    values: Vec<i32>,
}

impl WeightedSampler {
    fn new(config: &IntSamplerConfig) -> Result<Self> {
        let distribution = WeightedIndex::new(config.weights.clone())
            .context("invalid sampler weights")?;
        Ok(Self {
            distribution,
            values: config.values.clone(),
        })
    }

    fn draw(&self, rng: &mut ChaCha8Rng) -> i32 {
        let index = self.distribution.sample(rng);
        self.values[index]
    }
}

#[derive(Clone)]
struct ProductSamplers {
    outer_spread: WeightedSampler,
    inner_spread: WeightedSampler,
    outer_bid_vol: WeightedSampler,
    inner_bid_vol: WeightedSampler,
    trade_qty: WeightedSampler,
}

#[derive(Clone)]
struct PreparedSimulation {
    products: HashMap<String, PreparedProductSimulation>,
}

#[derive(Clone)]
struct PreparedProductSimulation {
    config: ProductSimulationConfig,
    samplers: ProductSamplers,
}

#[derive(Clone, Debug)]
struct TradePrint {
    timestamp: i32,
    buyer: String,
    seller: String,
    symbol: String,
    price: i32,
    quantity: i32,
}

#[derive(Clone, Debug)]
struct Level {
    price: i32,
    quantity: i32,
}

#[derive(Clone, Debug)]
struct BookSnapshot {
    timestamp: i32,
    product: String,
    bids: Vec<Level>,
    asks: Vec<Level>,
    mid: Option<f64>,
    reference_fair: Option<f64>,
}

#[derive(Clone, Debug)]
struct StrategyOrder {
    symbol: String,
    price: i32,
    quantity: i32,
}

#[derive(Clone, Debug, Default)]
struct ProductLedger {
    position: i32,
    cash: f64,
    realised: f64,
    avg_entry_price: f64,
}

impl ProductLedger {
    fn apply_buy(&mut self, price: i32, qty: i32) {
        self.cash -= f64::from(price * qty);
        if qty <= 0 {
            return;
        }
        if self.position >= 0 {
            let total_cost = self.avg_entry_price * f64::from(self.position) + f64::from(price * qty);
            self.position += qty;
            self.avg_entry_price = if self.position == 0 {
                0.0
            } else {
                total_cost / f64::from(self.position)
            };
            return;
        }
        let cover = qty.min(-self.position);
        self.realised += (self.avg_entry_price - f64::from(price)) * f64::from(cover);
        self.position += cover;
        let remaining = qty - cover;
        if self.position == 0 {
            self.avg_entry_price = 0.0;
        }
        if remaining > 0 {
            self.position = remaining;
            self.avg_entry_price = f64::from(price);
        }
    }

    fn apply_sell(&mut self, price: i32, qty: i32) {
        self.cash += f64::from(price * qty);
        if qty <= 0 {
            return;
        }
        if self.position <= 0 {
            let total_abs = self.position.abs();
            let total_value = self.avg_entry_price * f64::from(total_abs) + f64::from(price * qty);
            self.position -= qty;
            self.avg_entry_price = if self.position == 0 {
                0.0
            } else {
                total_value / f64::from(self.position.abs())
            };
            return;
        }
        let close = qty.min(self.position);
        self.realised += (f64::from(price) - self.avg_entry_price) * f64::from(close);
        self.position -= close;
        let remaining = qty - close;
        if self.position == 0 {
            self.avg_entry_price = 0.0;
        }
        if remaining > 0 {
            self.position = -remaining;
            self.avg_entry_price = f64::from(price);
        }
    }

    fn unrealised(&self, mark: Option<f64>) -> f64 {
        match mark {
            None => 0.0,
            Some(_) if self.position == 0 => 0.0,
            Some(mark_value) if self.position > 0 => (mark_value - self.avg_entry_price) * f64::from(self.position),
            Some(mark_value) => (self.avg_entry_price - mark_value) * f64::from(self.position.abs()),
        }
    }

    fn mtm(&self, mark: Option<f64>) -> f64 {
        match mark {
            None => self.realised,
            Some(mark_value) => self.cash + f64::from(self.position) * mark_value,
        }
    }
}

#[derive(Default, Clone)]
struct OrderSchedule {
    pending: BTreeMap<usize, HashMap<String, Vec<StrategyOrder>>>,
}

impl OrderSchedule {
    fn add(&mut self, due_step: usize, orders_by_product: HashMap<String, Vec<StrategyOrder>>) {
        let entry = self.pending.entry(due_step).or_insert_with(HashMap::new);
        for (product, orders) in orders_by_product {
            entry.entry(product).or_insert_with(Vec::new).extend(orders);
        }
    }

    fn pop(&mut self, step: usize) -> HashMap<String, Vec<StrategyOrder>> {
        let mut orders = self.pending.remove(&step).unwrap_or_default();
        for product in PRODUCTS {
            orders.entry(product.to_string()).or_insert_with(Vec::new);
        }
        orders
    }
}

#[derive(Debug, Serialize)]
struct RunOutput {
    backend: String,
    sessions: Vec<SessionPayload>,
    path_bands: HashMap<String, HashMap<String, Vec<PathBandRow>>>,
    profile: HashMap<String, Value>,
}

#[derive(Debug, Serialize, Clone)]
struct SessionPayload {
    run_name: String,
    summary: SummaryPayload,
    session_rows: Vec<DaySummaryPayload>,
}

#[derive(Debug, Serialize, Clone)]
struct SummaryPayload {
    final_pnl: f64,
    gross_pnl_before_maf: f64,
    maf_cost: f64,
    access_scenario: HashMap<String, Value>,
    fill_count: i32,
    order_count: i32,
    limit_breaches: i32,
    max_drawdown: f64,
    final_positions: HashMap<String, i32>,
    per_product: HashMap<String, ProductSummaryPayload>,
    slippage: SlippagePayload,
    fair_value: HashMap<String, Value>,
    behaviour: HashMap<String, Value>,
}

#[derive(Debug, Serialize, Clone)]
struct ProductSummaryPayload {
    cash: f64,
    realised: f64,
    unrealised: f64,
    final_mtm: f64,
    final_position: i32,
    avg_entry_price: f64,
    slippage_cost: f64,
    average_slippage_ticks: f64,
}

#[derive(Debug, Serialize, Clone)]
struct DaySummaryPayload {
    day: i32,
    final_pnl: f64,
    gross_pnl_before_maf: f64,
    maf_cost: f64,
    access_scenario: String,
    osmium_pnl: f64,
    pepper_pnl: f64,
    osmium_position: i32,
    pepper_position: i32,
}

#[derive(Debug, Serialize, Clone)]
struct SlippagePayload {
    total_slippage_cost: f64,
    total_slippage_qty: i32,
    average_slippage_ticks: f64,
    average_size_slippage_ticks: f64,
    per_product: HashMap<String, ProductSlippagePayload>,
}

#[derive(Debug, Serialize, Clone)]
struct ProductSlippagePayload {
    slippage_cost: f64,
    slippage_qty: i32,
    slippage_fill_count: i32,
    average_slippage_ticks: f64,
    average_size_slippage_ticks: f64,
    aggressive_slippage_cost: f64,
    passive_adverse_cost: f64,
}

#[derive(Debug, Serialize, Clone)]
struct PathBandRow {
    day: i32,
    timestamp: i32,
    #[serde(rename = "bucketIndex")]
    bucket_index: usize,
    #[serde(rename = "bucketStartTimestamp")]
    bucket_start_timestamp: i32,
    #[serde(rename = "bucketEndTimestamp")]
    bucket_end_timestamp: i32,
    #[serde(rename = "bucketCount")]
    bucket_count: usize,
    #[serde(rename = "sessionCount")]
    session_count: usize,
    p05: f64,
    p10: f64,
    p25: f64,
    p50: f64,
    p75: f64,
    p90: f64,
    p95: f64,
    min: f64,
    max: f64,
    #[serde(rename = "envelopeMin")]
    envelope_min: f64,
    #[serde(rename = "envelopeMax")]
    envelope_max: f64,
}

#[derive(Clone)]
struct PathMetricRow {
    metric_name: &'static str,
    product: String,
    bucket_index: usize,
    day: i32,
    timestamp: i32,
    bucket_start_timestamp: i32,
    bucket_end_timestamp: i32,
    bucket_count: usize,
    value: f64,
    envelope_min: f64,
    envelope_max: f64,
}

#[derive(Default)]
struct PathBandCollector {
    rows: Vec<PathMetricRow>,
    state: HashMap<(String, i32), BucketState>,
    bucket_index_by_product: HashMap<String, usize>,
}

struct BucketState {
    ranges: Vec<(usize, usize)>,
    row_index: usize,
    bucket_cursor: usize,
    current: Option<BucketAccumulator>,
}

#[derive(Clone)]
struct BucketAccumulator {
    day: i32,
    timestamp: i32,
    product: String,
    bucket_index: usize,
    bucket_start_timestamp: i32,
    bucket_end_timestamp: i32,
    bucket_count: usize,
    analysis_fair_last: Option<f64>,
    analysis_fair_min: Option<f64>,
    analysis_fair_max: Option<f64>,
    mid_last: Option<f64>,
    mid_min: Option<f64>,
    mid_max: Option<f64>,
    inventory_last: f64,
    inventory_min: f64,
    inventory_max: f64,
    pnl_last: f64,
    pnl_min: f64,
    pnl_max: f64,
}

impl PathBandCollector {
    fn new(days: &[i32], tick_count: usize, max_rows_per_product: usize) -> Self {
        let day_count = days.len().max(1);
        let per_day_limit = if max_rows_per_product == 0 {
            tick_count
        } else {
            (max_rows_per_product / day_count).max(1)
        };
        let mut state = HashMap::new();
        for product in PRODUCTS {
            for day in days {
                let ranges = if tick_count <= per_day_limit {
                    (0..tick_count).map(|idx| (idx, idx + 1)).collect()
                } else {
                    path_bucket_ranges(tick_count, per_day_limit)
                };
                state.insert((product.to_string(), *day), BucketState {
                    ranges,
                    row_index: 0,
                    bucket_cursor: 0,
                    current: None,
                });
            }
        }
        let bucket_index_by_product = PRODUCTS
            .iter()
            .map(|product| (product.to_string(), 0usize))
            .collect();
        Self {
            rows: Vec::new(),
            state,
            bucket_index_by_product,
        }
    }

    fn add(
        &mut self,
        day: i32,
        product: &str,
        timestamp: i32,
        analysis_fair: Option<f64>,
        mid: Option<f64>,
        inventory: i32,
        pnl: f64,
    ) {
        let Some(state) = self.state.get_mut(&(product.to_string(), day)) else {
            return;
        };
        if state.bucket_cursor >= state.ranges.len() {
            return;
        }
        let (start, end) = state.ranges[state.bucket_cursor];
        let bucket_index = *self.bucket_index_by_product.get(product).unwrap_or(&0);
        let mut bucket = state.current.clone().unwrap_or_else(|| BucketAccumulator {
            day,
            timestamp,
            product: product.to_string(),
            bucket_index,
            bucket_start_timestamp: timestamp,
            bucket_end_timestamp: timestamp,
            bucket_count: end - start,
            analysis_fair_last: analysis_fair,
            analysis_fair_min: analysis_fair,
            analysis_fair_max: analysis_fair,
            mid_last: mid,
            mid_min: mid,
            mid_max: mid,
            inventory_last: f64::from(inventory),
            inventory_min: f64::from(inventory),
            inventory_max: f64::from(inventory),
            pnl_last: pnl,
            pnl_min: pnl,
            pnl_max: pnl,
        });
        bucket.timestamp = timestamp;
        bucket.bucket_end_timestamp = timestamp;
        bucket.analysis_fair_last = analysis_fair;
        bucket.mid_last = mid;
        bucket.inventory_last = f64::from(inventory);
        bucket.pnl_last = pnl;
        if let Some(value) = analysis_fair {
            bucket.analysis_fair_min = Some(bucket.analysis_fair_min.map_or(value, |current| current.min(value)));
            bucket.analysis_fair_max = Some(bucket.analysis_fair_max.map_or(value, |current| current.max(value)));
        }
        if let Some(value) = mid {
            bucket.mid_min = Some(bucket.mid_min.map_or(value, |current| current.min(value)));
            bucket.mid_max = Some(bucket.mid_max.map_or(value, |current| current.max(value)));
        }
        bucket.inventory_min = bucket.inventory_min.min(f64::from(inventory));
        bucket.inventory_max = bucket.inventory_max.max(f64::from(inventory));
        bucket.pnl_min = bucket.pnl_min.min(pnl);
        bucket.pnl_max = bucket.pnl_max.max(pnl);
        state.row_index += 1;
        if state.row_index >= end {
            if let Some(value) = bucket.analysis_fair_last {
                self.rows.push(PathMetricRow {
                    metric_name: "analysisFair",
                    product: product.to_string(),
                    bucket_index,
                    day,
                    timestamp: bucket.timestamp,
                    bucket_start_timestamp: bucket.bucket_start_timestamp,
                    bucket_end_timestamp: bucket.bucket_end_timestamp,
                    bucket_count: bucket.bucket_count,
                    value,
                    envelope_min: bucket.analysis_fair_min.unwrap_or(value),
                    envelope_max: bucket.analysis_fair_max.unwrap_or(value),
                });
            }
            if let Some(value) = bucket.mid_last {
                self.rows.push(PathMetricRow {
                    metric_name: "mid",
                    product: product.to_string(),
                    bucket_index,
                    day,
                    timestamp: bucket.timestamp,
                    bucket_start_timestamp: bucket.bucket_start_timestamp,
                    bucket_end_timestamp: bucket.bucket_end_timestamp,
                    bucket_count: bucket.bucket_count,
                    value,
                    envelope_min: bucket.mid_min.unwrap_or(value),
                    envelope_max: bucket.mid_max.unwrap_or(value),
                });
            }
            self.rows.push(PathMetricRow {
                metric_name: "inventory",
                product: product.to_string(),
                bucket_index,
                day,
                timestamp: bucket.timestamp,
                bucket_start_timestamp: bucket.bucket_start_timestamp,
                bucket_end_timestamp: bucket.bucket_end_timestamp,
                bucket_count: bucket.bucket_count,
                value: bucket.inventory_last,
                envelope_min: bucket.inventory_min,
                envelope_max: bucket.inventory_max,
            });
            self.rows.push(PathMetricRow {
                metric_name: "pnl",
                product: product.to_string(),
                bucket_index,
                day,
                timestamp: bucket.timestamp,
                bucket_start_timestamp: bucket.bucket_start_timestamp,
                bucket_end_timestamp: bucket.bucket_end_timestamp,
                bucket_count: bucket.bucket_count,
                value: bucket.pnl_last,
                envelope_min: bucket.pnl_min,
                envelope_max: bucket.pnl_max,
            });
            self.bucket_index_by_product
                .entry(product.to_string())
                .and_modify(|value| *value += 1);
            state.bucket_cursor += 1;
            state.current = None;
        } else {
            state.current = Some(bucket);
        }
    }
}

#[derive(Default, Clone)]
struct ProfileTotals {
    market_generation_seconds: f64,
    state_build_seconds: f64,
    trader_seconds: f64,
    execution_seconds: f64,
    path_metrics_seconds: f64,
    postprocess_seconds: f64,
    session_total_seconds: f64,
    session_count: usize,
}

#[derive(Default)]
struct ChunkOutput {
    sessions: Vec<SessionOutput>,
    path_rows: Vec<PathMetricRow>,
    profile: ProfileTotals,
}

#[derive(Clone)]
struct SessionOutput {
    session_index: usize,
    payload: SessionPayload,
}

#[derive(Debug, Serialize)]
struct WorkerTrade {
    symbol: String,
    price: i32,
    quantity: i32,
    buyer: String,
    seller: String,
    timestamp: i32,
}

#[derive(Debug, Serialize)]
struct WorkerOrderDepth {
    buy_orders: HashMap<String, i32>,
    sell_orders: HashMap<String, i32>,
}

#[derive(Debug, Serialize)]
struct WorkerRequest {
    #[serde(rename = "type")]
    request_type: String,
    timestamp: i32,
    trader_data: String,
    order_depths: HashMap<String, WorkerOrderDepth>,
    own_trades: HashMap<String, Vec<WorkerTrade>>,
    market_trades: HashMap<String, Vec<WorkerTrade>>,
    position: HashMap<String, i32>,
}

#[derive(Debug, Deserialize)]
struct WorkerOrder {
    symbol: String,
    price: i32,
    quantity: i32,
}

#[derive(Debug, Deserialize)]
struct WorkerResponse {
    orders: Option<HashMap<String, Vec<WorkerOrder>>>,
    trader_data: Option<String>,
    stdout: Option<String>,
    error: Option<String>,
}

struct StrategyWorker {
    child: Child,
    stdin: BufWriter<ChildStdin>,
    stdout: BufReader<ChildStdout>,
}

impl StrategyWorker {
    fn spawn(config: &RustMcConfig) -> Result<Self> {
        let mut command = Command::new(&config.python_bin);
        command
            .arg(&config.worker_script)
            .arg(&config.trader_path);
        if let Some(path) = &config.trader_overrides_path {
            command.arg(path);
        }
        command.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::inherit());
        let mut child = command.spawn().context("failed to spawn rust strategy worker")?;
        let stdin = BufWriter::new(child.stdin.take().context("missing worker stdin")?);
        let stdout = BufReader::new(child.stdout.take().context("missing worker stdout")?);
        Ok(Self { child, stdin, stdout })
    }

    fn reset(&mut self) -> Result<()> {
        let payload = serde_json::json!({ "type": "reset" });
        self.send_raw(&payload)?;
        let response = self.read_response()?;
        if let Some(error) = response.error {
            bail!("worker reset failed: {error}");
        }
        Ok(())
    }

    fn run(&mut self, request: &WorkerRequest) -> Result<WorkerResponse> {
        self.send_raw(request)?;
        let response = self.read_response()?;
        if let Some(error) = &response.error {
            bail!("worker run failed: {error}");
        }
        Ok(response)
    }

    fn send_raw<T: Serialize>(&mut self, payload: &T) -> Result<()> {
        let text = serde_json::to_string(payload)?;
        self.stdin.write_all(text.as_bytes())?;
        self.stdin.write_all(b"\n")?;
        self.stdin.flush()?;
        Ok(())
    }

    fn read_response(&mut self) -> Result<WorkerResponse> {
        let mut line = String::new();
        let bytes = self.stdout.read_line(&mut line)?;
        if bytes == 0 {
            bail!("worker exited unexpectedly");
        }
        Ok(serde_json::from_str::<WorkerResponse>(line.trim()).context("failed to decode worker response")?)
    }
}

impl Drop for StrategyWorker {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn main() -> Result<()> {
    let mut args = env::args_os().skip(1);
    let config_path = PathBuf::from(args.next().context("usage: prosperity-rust-mc <config.json> <output.json>")?);
    let output_path = PathBuf::from(args.next().context("usage: prosperity-rust-mc <config.json> <output.json>")?);
    let config: RustMcConfig = serde_json::from_slice(&fs::read(&config_path).context("failed to read rust MC config")?)
        .context("failed to decode rust MC config")?;
    if config.print_trader_output {
        bail!("rust backend does not support print_trader_output");
    }
    let prepared = prepare_simulation(&config)?;
    let session_chunks = build_session_chunks(&config.session_indices, config.worker_count);
    let execution_started = Instant::now();
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(config.worker_count.max(1))
        .build()
        .context("failed to build rayon pool")?;
    let chunk_outputs = pool.install(|| {
        session_chunks
            .par_iter()
            .map(|chunk| run_chunk(&config, &prepared, chunk))
            .collect::<Result<Vec<_>>>()
    })?;
    let execution_seconds = execution_started.elapsed().as_secs_f64();

    let mut sessions = Vec::new();
    let mut path_rows = Vec::new();
    let mut profile = ProfileTotals::default();
    for chunk in chunk_outputs {
        sessions.extend(chunk.sessions);
        path_rows.extend(chunk.path_rows);
        profile.market_generation_seconds += chunk.profile.market_generation_seconds;
        profile.state_build_seconds += chunk.profile.state_build_seconds;
        profile.trader_seconds += chunk.profile.trader_seconds;
        profile.execution_seconds += chunk.profile.execution_seconds;
        profile.path_metrics_seconds += chunk.profile.path_metrics_seconds;
        profile.postprocess_seconds += chunk.profile.postprocess_seconds;
        profile.session_total_seconds += chunk.profile.session_total_seconds;
        profile.session_count += chunk.profile.session_count;
    }
    sessions.sort_by_key(|session| session.session_index);
    let path_bands = aggregate_path_bands(&path_rows);

    let mut profile_payload = HashMap::new();
    profile_payload.insert("monte_carlo_backend".to_string(), Value::String("rust".to_string()));
    profile_payload.insert("session_count".to_string(), Value::from(profile.session_count as i64));
    profile_payload.insert("sampled_session_count".to_string(), Value::from(0));
    profile_payload.insert("classic_session_count".to_string(), Value::from(0));
    profile_payload.insert("streaming_session_count".to_string(), Value::from(0));
    profile_payload.insert("rust_session_count".to_string(), Value::from(profile.session_count as i64));
    profile_payload.insert("market_generation_seconds".to_string(), rounded(profile.market_generation_seconds));
    profile_payload.insert("state_build_seconds".to_string(), rounded(profile.state_build_seconds));
    profile_payload.insert("trader_seconds".to_string(), rounded(profile.trader_seconds));
    profile_payload.insert("execution_seconds".to_string(), rounded(profile.execution_seconds));
    profile_payload.insert("path_metrics_seconds".to_string(), rounded(profile.path_metrics_seconds));
    profile_payload.insert("postprocess_seconds".to_string(), rounded(profile.postprocess_seconds));
    profile_payload.insert("session_total_seconds".to_string(), rounded(profile.session_total_seconds));
    profile_payload.insert("session_execution_wall_seconds".to_string(), rounded(execution_seconds));

    let output = RunOutput {
        backend: "rust".to_string(),
        sessions: sessions.into_iter().map(|session| session.payload).collect(),
        path_bands,
        profile: profile_payload,
    };
    fs::write(&output_path, serde_json::to_vec(&output)?).context("failed to write rust MC output")?;
    Ok(())
}

fn rounded(value: f64) -> Value {
    Value::from((value * 1_000_000.0).round() / 1_000_000.0)
}

fn prepare_simulation(config: &RustMcConfig) -> Result<PreparedSimulation> {
    let mut products = HashMap::new();
    for product in PRODUCTS {
        let item = config
            .simulation
            .products
            .get(product)
            .with_context(|| format!("missing simulation config for {product}"))?;
        products.insert(
            product.to_string(),
            PreparedProductSimulation {
                config: item.clone(),
                samplers: ProductSamplers {
                    outer_spread: WeightedSampler::new(&item.outer_spread)?,
                    inner_spread: WeightedSampler::new(&item.inner_spread)?,
                    outer_bid_vol: WeightedSampler::new(&item.outer_bid_vol)?,
                    inner_bid_vol: WeightedSampler::new(&item.inner_bid_vol)?,
                    trade_qty: WeightedSampler::new(&item.trade_qty)?,
                },
            },
        );
    }
    Ok(PreparedSimulation { products })
}

fn build_session_chunks(session_indices: &[usize], worker_count: usize) -> Vec<Vec<usize>> {
    if session_indices.is_empty() {
        return Vec::new();
    }
    if worker_count <= 1 {
        return vec![session_indices.to_vec()];
    }
    let chunk_count = session_indices.len().min(worker_count.max(worker_count * 2));
    let mut groups = vec![Vec::new(); chunk_count];
    for (idx, session_index) in session_indices.iter().enumerate() {
        groups[idx % chunk_count].push(*session_index);
    }
    groups.into_iter().filter(|group| !group.is_empty()).collect()
}

fn run_chunk(config: &RustMcConfig, prepared: &PreparedSimulation, session_indices: &[usize]) -> Result<ChunkOutput> {
    let mut worker = StrategyWorker::spawn(config)?;
    let mut output = ChunkOutput::default();
    for session_index in session_indices {
        worker.reset()?;
        let session = run_session(config, prepared, &mut worker, *session_index)?;
        output.path_rows.extend(session.1);
        output.profile.market_generation_seconds += session.2.market_generation_seconds;
        output.profile.state_build_seconds += session.2.state_build_seconds;
        output.profile.trader_seconds += session.2.trader_seconds;
        output.profile.execution_seconds += session.2.execution_seconds;
        output.profile.path_metrics_seconds += session.2.path_metrics_seconds;
        output.profile.postprocess_seconds += session.2.postprocess_seconds;
        output.profile.session_total_seconds += session.2.session_total_seconds;
        output.profile.session_count += 1;
        output.sessions.push(SessionOutput {
            session_index: *session_index,
            payload: session.0,
        });
    }
    Ok(output)
}

fn run_session(
    config: &RustMcConfig,
    prepared: &PreparedSimulation,
    worker: &mut StrategyWorker,
    session_index: usize,
) -> Result<(SessionPayload, Vec<PathMetricRow>, ProfileTotals)> {
    let started = Instant::now();
    let mut market_rng = ChaCha8Rng::seed_from_u64(config.base_seed + (session_index as u64) * 17);
    let mut execution_rng = ChaCha8Rng::seed_from_u64(config.base_seed + (session_index as u64) * 31);
    let mut ledgers = HashMap::from([
        (OSMIUM.to_string(), ProductLedger::default()),
        (PEPPER.to_string(), ProductLedger::default()),
    ]);
    let mut trader_data = String::new();
    let mut prev_own_trades = empty_trade_map();
    let mut prev_market_trades = empty_trade_map();
    let mut schedule = OrderSchedule::default();
    let mut global_step = 0usize;
    let mut total_fill_count = 0i32;
    let mut total_order_count = 0i32;
    let mut total_limit_breaches = 0i32;
    let mut running_peak = f64::NEG_INFINITY;
    let mut max_drawdown: f64 = 0.0;
    let mut final_marks: HashMap<String, Option<f64>> = PRODUCTS.iter().map(|product| (product.to_string(), None)).collect();
    let mut last_latent: HashMap<String, Option<f64>> = PRODUCTS.iter().map(|product| (product.to_string(), None)).collect();
    let mut session_rows = Vec::new();
    let mut slippage = HashMap::from([
        (OSMIUM.to_string(), ProductSlippagePayload::default()),
        (PEPPER.to_string(), ProductSlippagePayload::default()),
    ]);
    let mut profile = ProfileTotals::default();
    let mut path_collector = PathBandCollector::new(&config.days, config.tick_count, config.path_bucket_count);

    for day in &config.days {
        let generation_started = Instant::now();
        let osmium_latent = simulate_latent_fair(
            OSMIUM,
            prepared.products.get(OSMIUM).unwrap(),
            config.tick_count,
            last_latent.get(OSMIUM).and_then(|value| *value),
            &config.perturbation,
            &mut market_rng,
        )?;
        let pepper_latent = simulate_latent_fair(
            PEPPER,
            prepared.products.get(PEPPER).unwrap(),
            config.tick_count,
            last_latent.get(PEPPER).and_then(|value| *value),
            &config.perturbation,
            &mut market_rng,
        )?;
        let osmium_trade_counts = sample_trade_counts(prepared.products.get(OSMIUM).unwrap(), config.tick_count, &mut market_rng);
        let pepper_trade_counts = sample_trade_counts(prepared.products.get(PEPPER).unwrap(), config.tick_count, &mut market_rng);
        profile.market_generation_seconds += generation_started.elapsed().as_secs_f64();

        let mut day_marks: HashMap<String, Option<f64>> = PRODUCTS.iter().map(|product| (product.to_string(), None)).collect();
        for tick in 0..config.tick_count {
            let timestamp = (tick as i32) * TIMESTAMP_STEP;
            let generation_started = Instant::now();
            let mut tick_snapshots = HashMap::new();
            let mut raw_books = HashMap::new();
            let product_latents = [
                (OSMIUM, osmium_latent[tick], osmium_trade_counts[tick], prepared.products.get(OSMIUM).unwrap()),
                (PEPPER, pepper_latent[tick], pepper_trade_counts[tick], prepared.products.get(PEPPER).unwrap()),
            ];
            let mut trade_counts_lookup = HashMap::new();
            for (product, latent, trade_count, prepared_product) in product_latents {
                let book = make_book(product, latent, prepared_product, &mut market_rng);
                let scaled = scale_snapshot(timestamp, product, latent, &book, &config.perturbation, &mut execution_rng)?;
                tick_snapshots.insert(product.to_string(), scaled);
                raw_books.insert(product.to_string(), book);
                trade_counts_lookup.insert(product.to_string(), trade_count);
                day_marks.insert(product.to_string(), Some(latent));
            }
            profile.market_generation_seconds += generation_started.elapsed().as_secs_f64();

            let state_started = Instant::now();
            let request = WorkerRequest {
                request_type: "run".to_string(),
                timestamp,
                trader_data: trader_data.clone(),
                order_depths: PRODUCTS
                    .iter()
                    .map(|product| {
                        (
                            product.to_string(),
                            to_worker_depth(tick_snapshots.get(*product).unwrap()),
                        )
                    })
                    .collect(),
                own_trades: fills_to_worker_map(&prev_own_trades),
                market_trades: fills_to_worker_map(&prev_market_trades),
                position: ledgers
                    .iter()
                    .map(|(product, ledger)| (product.clone(), ledger.position))
                    .collect(),
            };
            profile.state_build_seconds += state_started.elapsed().as_secs_f64();

            let trader_started = Instant::now();
            let response = worker.run(&request)?;
            profile.trader_seconds += trader_started.elapsed().as_secs_f64();
            trader_data = response.trader_data.unwrap_or_default();
            if let Some(stdout) = response.stdout {
                if !stdout.is_empty() && config.print_trader_output {
                    print!("{stdout}");
                }
            }

            let submitted_orders = normalize_orders(response.orders.unwrap_or_default());
            let due_step = global_step + config.perturbation.latency_ticks;
            schedule.add(due_step, submitted_orders);
            let due_orders = schedule.pop(global_step);

            let execution_started = Instant::now();
            let mut own_trades_tick = empty_trade_map();
            let mut market_trades_tick = empty_trade_map();
            let mut total_mtm_for_tick = 0.0;
            for product in PRODUCTS {
                let snapshot = tick_snapshots.get(product).unwrap().clone();
                let raw_book = raw_books.get(product).unwrap();
                let trades = generate_market_trades(
                    product,
                    timestamp,
                    raw_book,
                    trade_counts_lookup[product],
                    prepared.products.get(product).unwrap(),
                    &mut market_rng,
                );
                let (fills, residual_trades, limit_breach) = execute_order_batch(
                    product,
                    timestamp,
                    snapshot,
                    trades,
                    ledgers.get_mut(product).unwrap(),
                    due_orders.get(product).cloned().unwrap_or_default(),
                    &config.fill_model,
                    &config.perturbation,
                    &mut execution_rng,
                    slippage.get_mut(product).unwrap(),
                );
                total_limit_breaches += limit_breach;
                total_fill_count += fills.len() as i32;
                total_order_count += due_orders.get(product).map(|orders| orders.len()).unwrap_or(0) as i32;
                own_trades_tick.insert(product.to_string(), fills_to_trade_records(product, timestamp, &fills));
                market_trades_tick.insert(product.to_string(), residual_trades.clone());
                let mark = tick_snapshots
                    .get(product)
                    .and_then(|item| item.reference_fair.or(item.mid));
                let product_mtm = ledgers.get(product).unwrap().mtm(mark);
                total_mtm_for_tick += product_mtm;
                let path_started = Instant::now();
                path_collector.add(
                    *day,
                    product,
                    timestamp,
                    tick_snapshots.get(product).unwrap().reference_fair,
                    tick_snapshots.get(product).unwrap().mid,
                    ledgers.get(product).unwrap().position,
                    product_mtm,
                );
                profile.path_metrics_seconds += path_started.elapsed().as_secs_f64();
            }
            profile.execution_seconds += execution_started.elapsed().as_secs_f64();
            prev_own_trades = own_trades_tick;
            prev_market_trades = market_trades_tick;
            global_step += 1;
            running_peak = running_peak.max(total_mtm_for_tick);
            max_drawdown = max_drawdown.max(running_peak - total_mtm_for_tick);
        }

        final_marks.insert(OSMIUM.to_string(), day_marks[OSMIUM]);
        final_marks.insert(PEPPER.to_string(), day_marks[PEPPER]);
        last_latent.insert(OSMIUM.to_string(), day_marks[OSMIUM]);
        last_latent.insert(PEPPER.to_string(), day_marks[PEPPER]);
        let gross_day_pnl = ledgers[OSMIUM].mtm(day_marks[OSMIUM]) + ledgers[PEPPER].mtm(day_marks[PEPPER]);
        session_rows.push(DaySummaryPayload {
            day: *day,
            final_pnl: gross_day_pnl,
            gross_pnl_before_maf: gross_day_pnl,
            maf_cost: 0.0,
            access_scenario: "no_access".to_string(),
            osmium_pnl: ledgers[OSMIUM].mtm(day_marks[OSMIUM]),
            pepper_pnl: ledgers[PEPPER].mtm(day_marks[PEPPER]),
            osmium_position: ledgers[OSMIUM].position,
            pepper_position: ledgers[PEPPER].position,
        });
    }

    let postprocess_started = Instant::now();
    let gross_final_pnl = ledgers[OSMIUM].mtm(final_marks[OSMIUM]) + ledgers[PEPPER].mtm(final_marks[PEPPER]);
    let per_product = PRODUCTS
        .iter()
        .map(|product| {
            let ledger = ledgers.get(*product).unwrap();
            let mark = *final_marks.get(*product).unwrap_or(&None);
            (
                product.to_string(),
                ProductSummaryPayload {
                    cash: ledger.cash,
                    realised: ledger.realised,
                    unrealised: ledger.unrealised(mark),
                    final_mtm: ledger.mtm(mark),
                    final_position: ledger.position,
                    avg_entry_price: ledger.avg_entry_price,
                    slippage_cost: slippage[*product].slippage_cost,
                    average_slippage_ticks: slippage[*product].average_slippage_ticks,
                },
            )
        })
        .collect();
    let slippage_payload = finalise_slippage(&slippage);
    profile.postprocess_seconds += postprocess_started.elapsed().as_secs_f64();
    profile.session_total_seconds += started.elapsed().as_secs_f64();
    let payload = SessionPayload {
        run_name: format!("{}_session_{session_index:04}", config.run_name),
        summary: SummaryPayload {
            final_pnl: gross_final_pnl,
            gross_pnl_before_maf: gross_final_pnl,
            maf_cost: 0.0,
            access_scenario: [
                ("name".to_string(), Value::String("no_access".to_string())),
                ("enabled".to_string(), Value::Bool(false)),
                ("contract_won".to_string(), Value::Bool(false)),
                ("expected_extra_quote_fraction".to_string(), Value::from(0.0_f64)),
                ("maf_cost".to_string(), Value::from(0.0_f64)),
            ]
            .into_iter()
            .collect(),
            fill_count: total_fill_count,
            order_count: total_order_count,
            limit_breaches: total_limit_breaches,
            max_drawdown,
            final_positions: PRODUCTS
                .iter()
                .map(|product| (product.to_string(), ledgers[*product].position))
                .collect(),
            per_product,
            slippage: slippage_payload,
            fair_value: HashMap::new(),
            behaviour: HashMap::new(),
        },
        session_rows,
    };
    Ok((payload, path_collector.rows, profile))
}

fn simulate_latent_fair(
    product: &str,
    prepared: &PreparedProductSimulation,
    tick_count: usize,
    continue_from: Option<f64>,
    perturbation: &RustPerturbationConfig,
    rng: &mut ChaCha8Rng,
) -> Result<Vec<f64>> {
    let mut path = vec![0.0; tick_count];
    let start = continue_from.unwrap_or_else(|| {
        prepared
            .config
            .start_candidates
            .first()
            .copied()
            .unwrap_or(if product == OSMIUM { 10000.0 } else { 12000.0 })
    });
    path[0] = start;
    if product == OSMIUM {
        let normal = Normal::new(0.0, prepared.config.simulation_noise_std.max(0.0)).context("invalid osmium noise")?;
        let target = 10000.0;
        for idx in 1..tick_count {
            let pull = -0.15 * (path[idx - 1] - target);
            path[idx] = path[idx - 1] + pull + normal.sample(rng);
        }
    } else {
        let normal = Normal::new(0.0, prepared.config.simulation_noise_std.max(0.0)).context("invalid pepper noise")?;
        for idx in 1..tick_count {
            path[idx] = path[idx - 1] + prepared.config.drift_per_tick + normal.sample(rng);
        }
    }
    if let Some(shock_tick) = perturbation.shock_tick {
        if let Some(shock) = perturbation.shock_by_product.get(product) {
            if *shock != 0.0 && shock_tick < path.len() {
                for value in path.iter_mut().skip(shock_tick) {
                    *value += *shock;
                }
            }
        }
    }
    Ok(path)
}

fn sample_trade_counts(prepared: &PreparedProductSimulation, tick_count: usize, rng: &mut ChaCha8Rng) -> Vec<usize> {
    let mut counts = vec![0usize; tick_count];
    for idx in 0..tick_count {
        if rng.gen_bool(prepared.config.trade_active_prob.clamp(0.0, 1.0)) {
            counts[idx] = 1;
            if prepared.config.second_trade_prob > 0.0
                && rng.gen_bool(prepared.config.second_trade_prob.clamp(0.0, 1.0))
            {
                counts[idx] += 1;
            }
        }
    }
    counts
}

fn make_book(
    _product: &str,
    latent_fair: f64,
    prepared: &PreparedProductSimulation,
    rng: &mut ChaCha8Rng,
) -> VecLevelsBook {
    let center = latent_fair.round() as i32;
    let outer_spread = prepared.samplers.outer_spread.draw(rng);
    let inner_spread = prepared.samplers.inner_spread.draw(rng);
    let outer_half = outer_spread / 2;
    let outer_bid = center - outer_half;
    let outer_ask = outer_bid + outer_spread;
    let inner_half = inner_spread / 2;
    let mut inner_bid = center - inner_half;
    let mut inner_ask = inner_bid + inner_spread;
    if inner_bid <= outer_bid {
        inner_bid = outer_bid + 1;
    }
    if inner_ask >= outer_ask {
        inner_ask = outer_ask - 1;
    }
    if inner_ask <= inner_bid {
        inner_bid = outer_bid + 1;
        inner_ask = outer_ask - 1;
    }

    let outer_bid_vol = prepared.samplers.outer_bid_vol.draw(rng);
    let outer_ask_vol = prepared.samplers.outer_bid_vol.draw(rng);
    let inner_bid_vol = prepared.samplers.inner_bid_vol.draw(rng);
    let inner_ask_vol = prepared.samplers.inner_bid_vol.draw(rng);

    let mut bids = vec![
        Level { price: inner_bid, quantity: inner_bid_vol },
        Level { price: outer_bid, quantity: outer_bid_vol },
    ];
    let mut asks = vec![
        Level { price: inner_ask, quantity: inner_ask_vol },
        Level { price: outer_ask, quantity: outer_ask_vol },
    ];

    let bot3_rate = prepared.config.bot3_bid_rate + prepared.config.bot3_ask_rate;
    if bot3_rate > 0.0 && rng.gen_bool(bot3_rate.clamp(0.0, 1.0)) {
        let bid_share = if bot3_rate <= 0.0 {
            0.5
        } else {
            prepared.config.bot3_bid_rate / bot3_rate
        };
        if rng.gen_bool(bid_share.clamp(0.0, 1.0)) {
            let offset = [-2, -1, 0, 1][rng.gen_range(0..4)];
            let price = center + offset;
            let min_ask = asks.iter().map(|level| level.price).min().unwrap_or(inner_ask);
            if price > inner_bid && price < min_ask {
                bids.push(Level {
                    price,
                    quantity: rng.gen_range(3..=10),
                });
            }
        } else {
            let offset = [-1, 0, 1, 2][rng.gen_range(0..4)];
            let price = center + offset;
            let max_bid = bids.iter().map(|level| level.price).max().unwrap_or(inner_bid);
            if price < inner_ask && price > max_bid {
                asks.push(Level {
                    price,
                    quantity: rng.gen_range(3..=10),
                });
            }
        }
    }

    normalize_levels(&mut bids, true);
    normalize_levels(&mut asks, false);
    VecLevelsBook { bids, asks }
}

#[derive(Clone)]
struct VecLevelsBook {
    bids: Vec<Level>,
    asks: Vec<Level>,
}

fn normalize_levels(levels: &mut Vec<Level>, descending: bool) {
    let mut combined = HashMap::new();
    for level in levels.drain(..) {
        *combined.entry(level.price).or_insert(0) += level.quantity;
    }
    let mut normalized: Vec<Level> = combined
        .into_iter()
        .map(|(price, quantity)| Level { price, quantity })
        .collect();
    normalized.sort_by_key(|level| if descending { -level.price } else { level.price });
    *levels = normalized;
}

fn scale_snapshot(
    timestamp: i32,
    product: &str,
    latent_fair: f64,
    book: &VecLevelsBook,
    perturbation: &RustPerturbationConfig,
    rng: &mut ChaCha8Rng,
) -> Result<BookSnapshot> {
    let noise = if perturbation.price_noise_std > 0.0 {
        Some(Normal::new(0.0, perturbation.price_noise_std).context("invalid price noise")?)
    } else {
        None
    };
    let mut bids = scale_levels(&book.bids, true, perturbation, noise.as_ref(), rng);
    let mut asks = scale_levels(&book.asks, false, perturbation, noise.as_ref(), rng);
    normalize_levels(&mut bids, true);
    normalize_levels(&mut asks, false);
    let mid = if !bids.is_empty() && !asks.is_empty() {
        Some((f64::from(bids[0].price) + f64::from(asks[0].price)) / 2.0)
    } else {
        None
    };
    let reference_fair = if let Some(normal) = noise.as_ref() {
        Some(latent_fair + normal.sample(rng))
    } else {
        Some(latent_fair)
    };
    Ok(BookSnapshot {
        timestamp,
        product: product.to_string(),
        bids,
        asks,
        mid,
        reference_fair,
    })
}

fn scale_levels(
    levels: &[Level],
    is_bid: bool,
    perturbation: &RustPerturbationConfig,
    noise: Option<&Normal<f64>>,
    rng: &mut ChaCha8Rng,
) -> Vec<Level> {
    let mut output = Vec::new();
    for level in levels {
        let shifted = if is_bid {
            level.price - perturbation.spread_shift_ticks
        } else {
            level.price + perturbation.spread_shift_ticks
        };
        let noisy = if let Some(distribution) = noise {
            shifted + distribution.sample(rng).round() as i32
        } else {
            shifted
        };
        let scaled_volume = (f64::from(level.quantity) * perturbation.order_book_volume_scale).round() as i32;
        if scaled_volume > 0 {
            output.push(Level {
                price: noisy,
                quantity: scaled_volume,
            });
        }
    }
    output
}

fn generate_market_trades(
    product: &str,
    timestamp: i32,
    book: &VecLevelsBook,
    count: usize,
    prepared: &PreparedProductSimulation,
    rng: &mut ChaCha8Rng,
) -> Vec<TradePrint> {
    let mut trades = Vec::new();
    for _ in 0..count {
        let market_buy = rng.gen_bool(prepared.config.trade_buy_prob.clamp(0.0, 1.0));
        let levels = if market_buy { &book.asks } else { &book.bids };
        if levels.is_empty() {
            continue;
        }
        let volume_limit: i32 = levels.iter().map(|level| level.quantity).sum();
        let quantity = sample_trade_quantity(&prepared.samplers.trade_qty, volume_limit, rng);
        if quantity <= 0 {
            continue;
        }
        trades.push(TradePrint {
            timestamp,
            buyer: if market_buy { "BOT_TAKER".to_string() } else { String::new() },
            seller: if market_buy { String::new() } else { "BOT_TAKER".to_string() },
            symbol: product.to_string(),
            price: levels[0].price,
            quantity,
        });
    }
    trades
}

fn sample_trade_quantity(sampler: &WeightedSampler, volume_limit: i32, rng: &mut ChaCha8Rng) -> i32 {
    if volume_limit <= 0 {
        return 0;
    }
    for _ in 0..8 {
        let quantity = sampler.draw(rng);
        if quantity <= volume_limit {
            return quantity.max(1);
        }
    }
    volume_limit.clamp(1, 5)
}

fn to_worker_depth(snapshot: &BookSnapshot) -> WorkerOrderDepth {
    WorkerOrderDepth {
        buy_orders: snapshot
            .bids
            .iter()
            .map(|level| (level.price.to_string(), level.quantity))
            .collect(),
        sell_orders: snapshot
            .asks
            .iter()
            .map(|level| (level.price.to_string(), -level.quantity))
            .collect(),
    }
}

fn normalize_orders(raw: HashMap<String, Vec<WorkerOrder>>) -> HashMap<String, Vec<StrategyOrder>> {
    let mut output: HashMap<String, Vec<StrategyOrder>> = PRODUCTS
        .iter()
        .map(|product| (product.to_string(), Vec::new()))
        .collect();
    for (product, orders) in raw {
        output.insert(
            product.clone(),
            orders
                .into_iter()
                .map(|order| StrategyOrder {
                    symbol: order.symbol,
                    price: order.price,
                    quantity: order.quantity,
                })
                .collect(),
        );
    }
    output
}

fn execute_order_batch(
    product: &str,
    timestamp: i32,
    snapshot: BookSnapshot,
    trades: Vec<TradePrint>,
    ledger: &mut ProductLedger,
    orders: Vec<StrategyOrder>,
    fill_model: &RustFillModelConfig,
    perturbation: &RustPerturbationConfig,
    rng: &mut ChaCha8Rng,
    slippage: &mut ProductSlippagePayload,
) -> (Vec<TradePrint>, Vec<TradePrint>, i32) {
    let position_limit = *perturbation.position_limits.get(product).unwrap_or(&80);
    let total_buy: i32 = orders.iter().map(|order| order.quantity.max(0)).sum();
    let total_sell: i32 = orders.iter().map(|order| (-order.quantity).max(0)).sum();
    if ledger.position + total_buy > position_limit || ledger.position - total_sell < -position_limit {
        return (Vec::new(), trades, 1);
    }

    let config_set = fill_model.products.get(product).unwrap();
    let product_config = regime_config(product, &snapshot.bids, &snapshot.asks, config_set);
    let mut bids = snapshot.bids.clone();
    let mut asks = snapshot.asks.clone();
    let mut fills = Vec::new();
    let mut passive_candidates = Vec::new();

    for order in orders {
        if order.quantity == 0 {
            continue;
        }
        if order.quantity > 0 {
            let mut remaining = order.quantity;
            while remaining > 0 && !asks.is_empty() && asks[0].price <= order.price {
                let fill_qty = remaining.min(asks[0].quantity);
                let size_slippage = size_slippage_ticks(&product_config, fill_qty);
                let flat_slippage = product_config.aggressive_slippage_ticks + product_config.aggressive_adverse_selection_ticks;
                let total_slippage = ((flat_slippage + size_slippage)
                    * fill_model.slippage_multiplier
                    * perturbation.slippage_multiplier)
                    .round() as i32;
                let exec_price = asks[0].price + total_slippage;
                ledger.apply_buy(exec_price, fill_qty);
                record_slippage(slippage, fill_qty, f64::from(total_slippage), size_slippage, true);
                fills.push(TradePrint {
                    timestamp,
                    buyer: "SUBMISSION".to_string(),
                    seller: "BOT".to_string(),
                    symbol: product.to_string(),
                    price: exec_price,
                    quantity: fill_qty,
                });
                remaining -= fill_qty;
                asks[0].quantity -= fill_qty;
                if asks[0].quantity <= 0 {
                    asks.remove(0);
                }
            }
            if remaining > 0 && rng.gen_bool(perturbation.reentry_probability.clamp(0.0, 1.0)) {
                passive_candidates.push(StrategyOrder {
                    symbol: order.symbol,
                    price: order.price,
                    quantity: remaining,
                });
            }
        } else {
            let mut remaining = -order.quantity;
            while remaining > 0 && !bids.is_empty() && bids[0].price >= order.price {
                let fill_qty = remaining.min(bids[0].quantity);
                let size_slippage = size_slippage_ticks(&product_config, fill_qty);
                let flat_slippage = product_config.aggressive_slippage_ticks + product_config.aggressive_adverse_selection_ticks;
                let total_slippage = ((flat_slippage + size_slippage)
                    * fill_model.slippage_multiplier
                    * perturbation.slippage_multiplier)
                    .round() as i32;
                let exec_price = bids[0].price - total_slippage;
                ledger.apply_sell(exec_price, fill_qty);
                record_slippage(slippage, fill_qty, f64::from(total_slippage), size_slippage, true);
                fills.push(TradePrint {
                    timestamp,
                    buyer: "BOT".to_string(),
                    seller: "SUBMISSION".to_string(),
                    symbol: product.to_string(),
                    price: exec_price,
                    quantity: fill_qty,
                });
                remaining -= fill_qty;
                bids[0].quantity -= fill_qty;
                if bids[0].quantity <= 0 {
                    bids.remove(0);
                }
            }
            if remaining > 0 && rng.gen_bool(perturbation.reentry_probability.clamp(0.0, 1.0)) {
                passive_candidates.push(StrategyOrder {
                    symbol: order.symbol,
                    price: order.price,
                    quantity: -remaining,
                });
            }
        }
    }

    passive_candidates.sort_by_key(|order| {
        if order.quantity > 0 {
            (-order.price, -order.quantity)
        } else {
            (order.price, order.quantity)
        }
    });
    let passive_snapshot = BookSnapshot {
        timestamp: snapshot.timestamp,
        product: snapshot.product.clone(),
        bids,
        asks,
        mid: snapshot.mid,
        reference_fair: snapshot.reference_fair,
    };
    let mut working_trades = trades;
    for order in passive_candidates {
        consume_passive_trades(
            product,
            timestamp,
            &order,
            &passive_snapshot,
            &mut working_trades,
            ledger,
            fill_model,
            perturbation,
            &product_config,
            rng,
            &mut fills,
            slippage,
        );
    }
    let residual_trades = working_trades.into_iter().filter(|trade| trade.quantity > 0).collect();
    (fills, residual_trades, 0)
}

fn regime_config(
    product: &str,
    bids: &[Level],
    asks: &[Level],
    configs: &ProductFillConfigSet,
) -> RustProductFillConfig {
    if bids.is_empty() || asks.is_empty() {
        return configs.one_sided.clone();
    }
    let top_depth = bids[0].quantity + asks[0].quantity;
    if top_depth <= configs.normal.thin_depth_threshold {
        return configs.thin_depth.clone();
    }
    let spread = asks[0].price - bids[0].price;
    let wide_threshold = configs
        .normal
        .wide_spread_threshold
        .unwrap_or(if product == OSMIUM { 20 } else { 18 });
    if spread >= wide_threshold {
        return configs.wide_spread.clone();
    }
    configs.normal.clone()
}

fn size_slippage_ticks(config: &RustProductFillConfig, quantity: i32) -> f64 {
    let excess = (quantity - config.size_slippage_threshold).max(0) as f64;
    if excess <= 0.0 || config.size_slippage_rate <= 0.0 {
        return 0.0;
    }
    let ticks = config.size_slippage_rate * excess.powf(config.size_slippage_power.max(0.1));
    ticks.min(config.max_size_slippage_ticks)
}

fn consume_passive_trades(
    product: &str,
    timestamp: i32,
    order: &StrategyOrder,
    snapshot: &BookSnapshot,
    trades: &mut [TradePrint],
    ledger: &mut ProductLedger,
    fill_model: &RustFillModelConfig,
    perturbation: &RustPerturbationConfig,
    product_config: &RustProductFillConfig,
    rng: &mut ChaCha8Rng,
    fills: &mut Vec<TradePrint>,
    slippage: &mut ProductSlippagePayload,
) {
    let side_buy = order.quantity > 0;
    let remaining_qty = order.quantity.abs();
    if remaining_qty <= 0 {
        return;
    }
    let trade_matching_mode = perturbation.trade_matching_mode.as_str();
    if trade_matching_mode == "none" {
        return;
    }
    let effective_fill_rate = product_config.passive_fill_rate * fill_model.fill_rate_multiplier * perturbation.passive_fill_scale;
    let effective_miss_prob = (product_config.missed_fill_probability
        + fill_model.missed_fill_additive
        + perturbation.missed_fill_additive)
        .clamp(0.0, 1.0);
    if effective_fill_rate <= 0.0 || rng.gen_bool(effective_miss_prob) {
        return;
    }

    let (better_depth, same_depth, adverse_ticks, execution_price, eligible_volume) = if side_buy {
        let better_depth: i32 = snapshot.bids.iter().filter(|level| level.price > order.price).map(|level| level.quantity).sum();
        let same_depth: i32 = snapshot.bids.iter().filter(|level| level.price == order.price).map(|level| level.quantity).sum();
        let eligible_volume: i32 = trades
            .iter()
            .filter(|trade| {
                trade.seller == "BOT_TAKER"
                    && trade.quantity > 0
                    && if trade_matching_mode == "all" {
                        trade.price <= order.price
                    } else {
                        trade.price < order.price
                    }
            })
            .map(|trade| trade.quantity)
            .sum();
        let adverse_ticks = product_config.passive_adverse_selection_ticks + perturbation.adverse_selection_ticks;
        let execution_price = order.price + adverse_ticks.round() as i32;
        (better_depth, same_depth, adverse_ticks, execution_price, eligible_volume)
    } else {
        let better_depth: i32 = snapshot.asks.iter().filter(|level| level.price < order.price).map(|level| level.quantity).sum();
        let same_depth: i32 = snapshot.asks.iter().filter(|level| level.price == order.price).map(|level| level.quantity).sum();
        let eligible_volume: i32 = trades
            .iter()
            .filter(|trade| {
                trade.buyer == "BOT_TAKER"
                    && trade.quantity > 0
                    && if trade_matching_mode == "all" {
                        trade.price >= order.price
                    } else {
                        trade.price > order.price
                    }
            })
            .map(|trade| trade.quantity)
            .sum();
        let adverse_ticks = product_config.passive_adverse_selection_ticks + perturbation.adverse_selection_ticks;
        let execution_price = order.price - adverse_ticks.round() as i32;
        (better_depth, same_depth, adverse_ticks, execution_price, eligible_volume)
    };

    if eligible_volume <= 0 {
        return;
    }
    let same_side_depth = f64::from(better_depth) + product_config.same_price_queue_share * f64::from(same_depth);
    let queue_factor = f64::from(remaining_qty) / (1.0f64).max(f64::from(remaining_qty) + product_config.queue_pressure * same_side_depth);
    let target = (f64::from(eligible_volume) * effective_fill_rate * queue_factor).round() as i32;
    let target = target.min(remaining_qty).max(0);
    if target <= 0 {
        return;
    }

    let mut filled = 0;
    for trade in trades.iter_mut() {
        if filled >= target {
            break;
        }
        let eligible = if side_buy {
            trade.seller == "BOT_TAKER"
                && trade.quantity > 0
                && if trade_matching_mode == "all" {
                    trade.price <= order.price
                } else {
                    trade.price < order.price
                }
        } else {
            trade.buyer == "BOT_TAKER"
                && trade.quantity > 0
                && if trade_matching_mode == "all" {
                    trade.price >= order.price
                } else {
                    trade.price > order.price
                }
        };
        if !eligible {
            continue;
        }
        let take = (target - filled).min(trade.quantity);
        if take <= 0 {
            continue;
        }
        trade.quantity -= take;
        filled += take;
        if side_buy {
            ledger.apply_buy(execution_price, take);
            fills.push(TradePrint {
                timestamp,
                buyer: "SUBMISSION".to_string(),
                seller: "BOT".to_string(),
                symbol: product.to_string(),
                price: execution_price,
                quantity: take,
            });
        } else {
            ledger.apply_sell(execution_price, take);
            fills.push(TradePrint {
                timestamp,
                buyer: "BOT".to_string(),
                seller: "SUBMISSION".to_string(),
                symbol: product.to_string(),
                price: execution_price,
                quantity: take,
            });
        }
        record_slippage(slippage, take, adverse_ticks, 0.0, false);
    }
}

fn record_slippage(
    slippage: &mut ProductSlippagePayload,
    quantity: i32,
    slip_ticks: f64,
    size_slippage_ticks: f64,
    aggressive: bool,
) {
    slippage.slippage_cost += slip_ticks * f64::from(quantity);
    slippage.slippage_qty += quantity;
    slippage.slippage_fill_count += 1;
    if slippage.slippage_qty > 0 {
        slippage.average_slippage_ticks = slippage.slippage_cost / f64::from(slippage.slippage_qty);
    }
    slippage.average_size_slippage_ticks += size_slippage_ticks * f64::from(quantity);
    if aggressive {
        slippage.aggressive_slippage_cost += slip_ticks * f64::from(quantity);
    } else {
        slippage.passive_adverse_cost += slip_ticks * f64::from(quantity);
    }
}

impl Default for ProductSlippagePayload {
    fn default() -> Self {
        Self {
            slippage_cost: 0.0,
            slippage_qty: 0,
            slippage_fill_count: 0,
            average_slippage_ticks: 0.0,
            average_size_slippage_ticks: 0.0,
            aggressive_slippage_cost: 0.0,
            passive_adverse_cost: 0.0,
        }
    }
}

fn finalise_slippage(slippage: &HashMap<String, ProductSlippagePayload>) -> SlippagePayload {
    let total_qty: i32 = slippage.values().map(|item| item.slippage_qty).sum();
    let total_cost: f64 = slippage.values().map(|item| item.slippage_cost).sum();
    let total_size_cost: f64 = slippage
        .values()
        .map(|item| item.average_size_slippage_ticks * f64::from(item.slippage_qty))
        .sum();
    let mut per_product = HashMap::new();
    for (product, item) in slippage {
        let average_size = if item.slippage_qty > 0 {
            item.average_size_slippage_ticks / f64::from(item.slippage_qty)
        } else {
            0.0
        };
        per_product.insert(
            product.clone(),
            ProductSlippagePayload {
                average_size_slippage_ticks: average_size,
                ..item.clone()
            },
        );
    }
    SlippagePayload {
        total_slippage_cost: total_cost,
        total_slippage_qty: total_qty,
        average_slippage_ticks: if total_qty > 0 {
            total_cost / f64::from(total_qty)
        } else {
            0.0
        },
        average_size_slippage_ticks: if total_qty > 0 {
            total_size_cost / f64::from(total_qty)
        } else {
            0.0
        },
        per_product,
    }
}

fn empty_trade_map() -> HashMap<String, Vec<TradePrint>> {
    PRODUCTS
        .iter()
        .map(|product| (product.to_string(), Vec::new()))
        .collect()
}

fn fills_to_trade_records(product: &str, timestamp: i32, fills: &[TradePrint]) -> Vec<TradePrint> {
    fills
        .iter()
        .filter(|fill| fill.symbol == product)
        .map(|fill| TradePrint {
            timestamp,
            buyer: fill.buyer.clone(),
            seller: fill.seller.clone(),
            symbol: fill.symbol.clone(),
            price: fill.price,
            quantity: fill.quantity,
        })
        .collect()
}

fn fills_to_worker_map(source: &HashMap<String, Vec<TradePrint>>) -> HashMap<String, Vec<WorkerTrade>> {
    source
        .iter()
        .map(|(product, trades)| {
            (
                product.clone(),
                trades
                    .iter()
                    .map(|trade| WorkerTrade {
                        symbol: trade.symbol.clone(),
                        price: trade.price,
                        quantity: trade.quantity,
                        buyer: trade.buyer.clone(),
                        seller: trade.seller.clone(),
                        timestamp: trade.timestamp,
                    })
                    .collect(),
            )
        })
        .collect()
}

fn aggregate_path_bands(path_rows: &[PathMetricRow]) -> HashMap<String, HashMap<String, Vec<PathBandRow>>> {
    let mut grouped: HashMap<(String, String, usize), Vec<&PathMetricRow>> = HashMap::new();
    for row in path_rows {
        grouped
            .entry((row.metric_name.to_string(), row.product.clone(), row.bucket_index))
            .or_default()
            .push(row);
    }
    let mut output: HashMap<String, HashMap<String, Vec<PathBandRow>>> = HashMap::new();
    for metric in ["analysisFair", "mid", "inventory", "pnl"] {
        output.insert(metric.to_string(), PRODUCTS.iter().map(|product| (product.to_string(), Vec::new())).collect());
    }
    let mut keys: Vec<_> = grouped.keys().cloned().collect();
    keys.sort();
    for (metric_name, product, bucket_index) in keys {
        let rows = grouped.get(&(metric_name.clone(), product.clone(), bucket_index)).unwrap();
        let mut values: Vec<f64> = rows.iter().map(|row| row.value).collect();
        values.sort_by(|left, right| left.partial_cmp(right).unwrap());
        let envelope_min = rows.iter().map(|row| row.envelope_min).fold(f64::INFINITY, f64::min);
        let envelope_max = rows.iter().map(|row| row.envelope_max).fold(f64::NEG_INFINITY, f64::max);
        let first = rows[0];
        output
            .get_mut(&metric_name)
            .unwrap()
            .get_mut(&product)
            .unwrap()
            .push(PathBandRow {
                day: first.day,
                timestamp: first.timestamp,
                bucket_index,
                bucket_start_timestamp: first.bucket_start_timestamp,
                bucket_end_timestamp: first.bucket_end_timestamp,
                bucket_count: first.bucket_count,
                session_count: values.len(),
                p05: quantile(&values, 0.05),
                p10: quantile(&values, 0.10),
                p25: quantile(&values, 0.25),
                p50: quantile(&values, 0.50),
                p75: quantile(&values, 0.75),
                p90: quantile(&values, 0.90),
                p95: quantile(&values, 0.95),
                min: *values.first().unwrap(),
                max: *values.last().unwrap(),
                envelope_min,
                envelope_max,
            });
    }
    output
}

fn quantile(values: &[f64], q: f64) -> f64 {
    if values.len() == 1 {
        return values[0];
    }
    let index = q * (values.len() - 1) as f64;
    let lo = index.floor() as usize;
    let hi = index.ceil() as usize;
    if lo == hi {
        values[lo]
    } else {
        let weight = index - lo as f64;
        values[lo] * (1.0 - weight) + values[hi] * weight
    }
}

fn path_bucket_ranges(length: usize, bucket_count: usize) -> Vec<(usize, usize)> {
    let bucket_count = bucket_count.max(1).min(length.max(1));
    let mut ranges = Vec::new();
    let mut start = 0usize;
    for bucket in 0..bucket_count {
        let end = (((bucket + 1) as f64 * length as f64) / bucket_count as f64).round() as usize;
        let end = end.max(start + 1).min(length);
        ranges.push((start, end));
        start = end;
    }
    ranges
}
