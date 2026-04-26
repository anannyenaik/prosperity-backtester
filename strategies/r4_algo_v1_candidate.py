from __future__ import annotations

import json
import math

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from prosperity_backtester.datamodel import Order, OrderDepth, TradingState


HYDROGEL = "HYDROGEL_PACK"
VELVET = "VELVETFRUIT_EXTRACT"
DEEP_ITM = ("VEV_4000", "VEV_4500")
CENTRAL_VOUCHERS = ("VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500")
FAR_OTM = ("VEV_6000", "VEV_6500")
ALL_VOUCHERS = DEEP_ITM + CENTRAL_VOUCHERS + FAR_OTM
STRIKES = {
    "VEV_4000": 4000,
    "VEV_4500": 4500,
    "VEV_5000": 5000,
    "VEV_5100": 5100,
    "VEV_5200": 5200,
    "VEV_5300": 5300,
    "VEV_5400": 5400,
    "VEV_5500": 5500,
    "VEV_6000": 6000,
    "VEV_6500": 6500,
}
LIMITS = {HYDROGEL: 200, VELVET: 200, **{symbol: 300 for symbol in ALL_VOUCHERS}}

CONFIG = {
    "use_counterparties": True,
    "use_velvet_names": True,
    "use_option_names": True,
    "use_hydrogel_names": False,
    "use_deep_itm": True,
    "crossing_aggression": "base",
    "hydrogel_soft_cap": 60,
    "fill_stress_profile": "base",
    "counterparty_strength": 1.0,
}

FINAL_TTE = 4.0 / 365.0
PRIOR_IV = 0.26
MIN_IV = 0.02
MAX_IV = 2.5
STATE_VERSION = "r4v1"

HYDROGEL_PRIOR = 9991.0
HYDROGEL_SLOW_ALPHA = 0.00025
HYDROGEL_MED_ALPHA = 0.003
HYDROGEL_FAST_ALPHA = 0.025
HYDROGEL_WARMUP_TICKS = 350

VOUCHER_SOFT_CAP = 145
DEEP_ITM_SOFT_CAP = 45
VOUCHER_DELTA_SOFT = 135.0
VOUCHER_DELTA_HARD = 175.0
PORTFOLIO_DELTA_SOFT = 150.0
PORTFOLIO_DELTA_HARD = 190.0
VOUCHER_WARMUP_TICKS = 25

VELVET_NAME_EDGE = {
    ("Mark 67", "buy"): 0.85,
    ("Mark 67", "sell"): 0.35,
    ("Mark 55", "buy"): 0.25,
    ("Mark 55", "sell"): 0.05,
    ("Mark 49", "buy"): -0.25,
    ("Mark 49", "sell"): -0.45,
    ("Mark 14", "buy"): -0.25,
    ("Mark 14", "sell"): -0.35,
}

OPTION_NAME_EDGE = {
    ("Mark 01", "buy"): -0.12,
    ("Mark 22", "sell"): -0.12,
}


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def best_bid(depth: OrderDepth):
    return max(depth.buy_orders) if depth and depth.buy_orders else None


def best_ask(depth: OrderDepth):
    return min(depth.sell_orders) if depth and depth.sell_orders else None


def simple_mid(depth: OrderDepth):
    bid = best_bid(depth)
    ask = best_ask(depth)
    if bid is None or ask is None:
        return None
    return 0.5 * (bid + ask)


def top_spread(depth: OrderDepth):
    bid = best_bid(depth)
    ask = best_ask(depth)
    if bid is None or ask is None:
        return None
    return max(1.0, float(ask - bid))


def median(values):
    clean = sorted(float(value) for value in values if value is not None and math.isfinite(float(value)))
    if not clean:
        return None
    mid = len(clean) // 2
    if len(clean) % 2:
        return clean[mid]
    return 0.5 * (clean[mid - 1] + clean[mid])


def normal_cdf(value):
    return 0.5 * (1.0 + math.erf(float(value) / math.sqrt(2.0)))


def black_scholes_call(spot, strike, tte, volatility):
    s = float(spot)
    k = float(strike)
    t = max(0.0, float(tte))
    sigma = max(0.0, float(volatility))
    if not math.isfinite(s) or not math.isfinite(k) or s <= 0.0 or k <= 0.0:
        return 0.0
    intrinsic = max(0.0, s - k)
    if t <= 0.0 or sigma <= 1e-10:
        return intrinsic
    vol_time = sigma * math.sqrt(t)
    if vol_time <= 1e-10:
        return intrinsic
    d1 = (math.log(s / k) + 0.5 * sigma * sigma * t) / vol_time
    d2 = d1 - vol_time
    return max(0.0, s * normal_cdf(d1) - k * normal_cdf(d2))


def call_delta(spot, strike, tte, volatility):
    s = float(spot)
    k = float(strike)
    t = max(0.0, float(tte))
    sigma = max(0.0, float(volatility))
    if not math.isfinite(s) or not math.isfinite(k) or s <= 0.0 or k <= 0.0:
        return 0.0
    if t <= 0.0 or sigma <= 1e-10:
        return 1.0 if s > k else 0.0
    vol_time = sigma * math.sqrt(t)
    if vol_time <= 1e-10:
        return 1.0 if s > k else 0.0
    d1 = (math.log(s / k) + 0.5 * sigma * sigma * t) / vol_time
    return normal_cdf(d1)


def implied_vol_call(price, spot, strike, tte):
    if price is None or spot is None:
        return None
    observed = float(price)
    s = float(spot)
    k = float(strike)
    if not math.isfinite(observed) or not math.isfinite(s) or not math.isfinite(k):
        return None
    intrinsic = max(0.0, s - k)
    if observed < intrinsic - 1e-7 or observed > s + 1e-7 or s <= 0.0 or k <= 0.0:
        return None
    if observed <= intrinsic + 1e-7:
        return 0.0
    lo = MIN_IV
    hi = 0.35
    while black_scholes_call(s, k, tte, hi) < observed and hi < MAX_IV:
        hi *= 1.7
    if hi >= MAX_IV and black_scholes_call(s, k, tte, hi) < observed:
        return None
    for _ in range(28):
        mid = 0.5 * (lo + hi)
        if black_scholes_call(s, k, tte, mid) < observed:
            lo = mid
        else:
            hi = mid
    return clamp(0.5 * (lo + hi), MIN_IV, MAX_IV)


def ewma(previous, value, alpha):
    if value is None or not math.isfinite(float(value)):
        return previous
    if previous is None:
        return float(value)
    return (1.0 - alpha) * float(previous) + alpha * float(value)


def load_memory(raw):
    if not raw:
        return {}
    try:
        memory = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(memory, dict) or memory.get("v") != STATE_VERSION:
        return {}
    return memory


class OrderManager:
    def __init__(self, state: TradingState):
        self.orders = {}
        self.projected = {product: int(position) for product, position in state.position.items()}

    def position(self, product):
        return int(self.projected.get(product, 0))

    def add(self, product, price, quantity):
        quantity = int(quantity)
        if quantity == 0:
            return 0
        limit = LIMITS.get(product)
        if limit is None:
            return 0
        current = self.projected.get(product, 0)
        if quantity > 0:
            quantity = min(quantity, limit - current)
        else:
            quantity = -min(-quantity, limit + current)
        if quantity == 0:
            return 0
        self.projected[product] = current + quantity
        self.orders.setdefault(product, []).append(Order(product, int(round(price)), quantity))
        return quantity


class Trader:
    def run(self, state: TradingState):
        memory = load_memory(state.traderData)
        if int(state.timestamp) < int(memory.get("last_ts", -1)):
            memory = {}
        memory["v"] = STATE_VERSION
        memory["tick"] = int(memory.get("tick", 0)) + 1
        memory["last_ts"] = int(state.timestamp)

        self._observe_counterparties(state, memory)
        manager = OrderManager(state)
        mids = {product: simple_mid(depth) for product, depth in state.order_depths.items()}

        self._trade_hydrogel(state, memory, manager, mids.get(HYDROGEL))
        voucher_model = self._voucher_model(memory, mids)
        self._trade_velvet_flow(state, memory, manager, mids.get(VELVET), voucher_model)
        self._trade_vouchers(state, memory, manager, voucher_model)
        self._hedge_velvet(state, manager, mids.get(VELVET), voucher_model)
        self._update_state(memory, voucher_model, mids)
        return manager.orders, 0, json.dumps(memory, separators=(",", ":"))

    def _observe_counterparties(self, state, memory):
        memory["vel_sig"] = 0.62 * float(memory.get("vel_sig", 0.0))
        option_signal = memory.get("opt_sig", {})
        if not isinstance(option_signal, dict):
            option_signal = {}
        option_signal = {symbol: 0.55 * float(value) for symbol, value in option_signal.items()}
        if not CONFIG.get("use_counterparties", True):
            memory["vel_sig"] = 0.0
            memory["opt_sig"] = {}
            return
        strength = float(CONFIG.get("counterparty_strength", 1.0))
        if CONFIG.get("use_velvet_names", True):
            for trade in state.market_trades.get(VELVET, []):
                if trade.buyer:
                    memory["vel_sig"] += strength * VELVET_NAME_EDGE.get((str(trade.buyer), "buy"), 0.0)
                if trade.seller:
                    memory["vel_sig"] -= strength * VELVET_NAME_EDGE.get((str(trade.seller), "sell"), 0.0)
        memory["vel_sig"] = clamp(float(memory.get("vel_sig", 0.0)), -1.0, 1.0)
        if CONFIG.get("use_option_names", True):
            for symbol in ALL_VOUCHERS:
                for trade in state.market_trades.get(symbol, []):
                    signal = float(option_signal.get(symbol, 0.0))
                    if trade.buyer:
                        signal += strength * OPTION_NAME_EDGE.get((str(trade.buyer), "buy"), 0.0)
                    if trade.seller:
                        signal -= strength * OPTION_NAME_EDGE.get((str(trade.seller), "sell"), 0.0)
                    option_signal[symbol] = clamp(signal, -0.35, 0.35)
        memory["opt_sig"] = {symbol: round(value, 5) for symbol, value in option_signal.items() if abs(value) > 0.01}

    def _hydrogel_fair(self, memory, mid):
        slow = ewma(memory.get("h_slow"), mid, HYDROGEL_SLOW_ALPHA)
        medium = ewma(memory.get("h_med"), mid, HYDROGEL_MED_ALPHA)
        fast = ewma(memory.get("h_fast"), mid, HYDROGEL_FAST_ALPHA)
        if slow is None:
            slow = float(mid if mid is not None else HYDROGEL_PRIOR)
        if medium is None:
            medium = float(mid if mid is not None else slow)
        if fast is None:
            fast = float(mid if mid is not None else medium)
        fair = 0.70 * slow + 0.22 * medium + 0.08 * fast
        return fair, slow, medium, fast

    def _trade_hydrogel(self, state, memory, manager, mid):
        depth = state.order_depths.get(HYDROGEL)
        if depth is None or mid is None:
            return
        spread = top_spread(depth) or 16.0
        fair, slow, medium, fast = self._hydrogel_fair(memory, mid)
        position = manager.position(HYDROGEL)
        tick = int(memory.get("tick", 0))
        warm = clamp(tick / float(HYDROGEL_WARMUP_TICKS), 0.0, 1.0)
        trend_gap = abs(float(fast) - float(slow))
        medium_gap = abs(float(medium) - float(slow))
        instability = min(1.0, trend_gap / 12.0 + medium_gap / 35.0)
        size_scale = clamp((0.35 + 0.65 * warm) * (1.0 - 0.45 * instability), 0.25, 1.0)
        soft_cap = max(25, int(round(float(CONFIG.get("hydrogel_soft_cap", 60)) * size_scale)))
        cap_ratio = min(1.0, abs(position) / max(1.0, float(soft_cap)))
        fair -= (0.045 + 0.035 * cap_ratio) * position
        uncertainty_edge = min(4.0, 0.35 * trend_gap + 0.05 * medium_gap)
        take_edge = max(3.7, 0.30 * spread) + uncertainty_edge
        max_take = max(4, int(round(18 * size_scale))) if abs(position) < soft_cap else max(2, int(round(7 * size_scale)))

        trend = float(fast) - float(slow)
        block_buy = trend < -10.0 and position >= 0
        block_sell = trend > 10.0 and position <= 0
        for ask in sorted(depth.sell_orders):
            if ask > fair - take_edge or block_buy:
                break
            available = -int(depth.sell_orders[ask])
            qty = min(available, max_take)
            if position >= 0:
                qty = min(qty, max(0, soft_cap - position))
            filled = manager.add(HYDROGEL, ask, qty)
            position += filled
            max_take -= max(0, filled)
            if max_take <= 0:
                break

        position = manager.position(HYDROGEL)
        max_take = max(4, int(round(18 * size_scale))) if abs(position) < soft_cap else max(2, int(round(7 * size_scale)))
        for bid in sorted(depth.buy_orders, reverse=True):
            if bid < fair + take_edge or block_sell:
                break
            available = int(depth.buy_orders[bid])
            qty = min(available, max_take)
            if position <= 0:
                qty = min(qty, max(0, position + soft_cap))
            filled = manager.add(HYDROGEL, bid, -qty)
            position += filled
            max_take -= abs(filled)
            if max_take <= 0:
                break

        bid = best_bid(depth)
        ask = best_ask(depth)
        if bid is None or ask is None:
            return
        quote_size = max(1, int(round(6 * size_scale))) if abs(manager.position(HYDROGEL)) < soft_cap else 1
        passive_edge = max(5.4, 0.40 * spread) + 0.5 * uncertainty_edge
        bid_price = min(bid + 1, math.floor(fair - passive_edge))
        ask_price = max(ask - 1, math.ceil(fair + passive_edge))
        position = manager.position(HYDROGEL)
        if bid_price < ask and position < soft_cap and not block_buy:
            manager.add(HYDROGEL, bid_price, quote_size)
        if ask_price > bid and position > -soft_cap and not block_sell:
            manager.add(HYDROGEL, ask_price, -quote_size)

    def _voucher_model(self, memory, mids):
        spot = mids.get(VELVET)
        velvet_lean = float(memory.get("vel_sig", 0.0)) if CONFIG.get("use_counterparties", True) and CONFIG.get("use_velvet_names", True) else 0.0
        model = {
            "spot": spot,
            "pricing_spot": None if spot is None else float(spot) + velvet_lean,
            "centre_iv": float(memory.get("iv", PRIOR_IV)),
            "fair": {},
            "raw_residual": {},
            "signal": {},
            "scale": {},
            "delta": {},
            "valid": False,
        }
        if spot is None:
            return model
        iv_by_symbol = {}
        for symbol in CENTRAL_VOUCHERS:
            mid = mids.get(symbol)
            iv = implied_vol_call(mid, spot, STRIKES[symbol], FINAL_TTE)
            if iv is not None and MIN_IV <= iv <= MAX_IV:
                iv_by_symbol[symbol] = iv
        all_iv = median(iv_by_symbol.values())
        previous_iv = float(memory.get("iv", PRIOR_IV))
        centre_iv = previous_iv if all_iv is None else clamp(0.88 * previous_iv + 0.12 * all_iv, MIN_IV, MAX_IV)
        model["centre_iv"] = centre_iv
        model["valid"] = len(iv_by_symbol) >= 3

        offsets = memory.get("off", {})
        scales = memory.get("sc", {})
        for symbol in DEEP_ITM + CENTRAL_VOUCHERS:
            strike = STRIKES[symbol]
            mids_without_self = [iv for other, iv in iv_by_symbol.items() if other != symbol]
            local_iv = median(mids_without_self)
            if local_iv is None:
                local_iv = centre_iv
            local_iv = clamp(0.65 * centre_iv + 0.35 * local_iv, MIN_IV, MAX_IV)
            pricing_spot = model["pricing_spot"] if model["pricing_spot"] is not None else spot
            base_fair = black_scholes_call(pricing_spot, strike, FINAL_TTE, local_iv)
            raw_mid = mids.get(symbol)
            raw_base = black_scholes_call(spot, strike, FINAL_TTE, local_iv)
            raw_residual = None if raw_mid is None else float(raw_mid) - raw_base
            offset = float(offsets.get(symbol, 0.0))
            opt_sig = 0.0
            if CONFIG.get("use_counterparties", True) and CONFIG.get("use_option_names", True):
                opt_sig = float(memory.get("opt_sig", {}).get(symbol, 0.0))
            fair = base_fair + offset + opt_sig
            signal = None if raw_mid is None else float(raw_mid) - fair
            model["fair"][symbol] = fair
            model["raw_residual"][symbol] = raw_residual
            model["signal"][symbol] = signal
            model["scale"][symbol] = max(0.7, min(4.0, float(scales.get(symbol, 1.2))))
            model["delta"][symbol] = call_delta(pricing_spot, strike, FINAL_TTE, local_iv)
        return model

    def _aggression_multiplier(self):
        profile = str(CONFIG.get("crossing_aggression", "base"))
        if profile == "wide":
            return 1.35
        if profile == "tight":
            return 0.85
        return 1.0

    def _trade_vouchers(self, state, memory, manager, model):
        if not model.get("valid") or int(memory.get("tick", 0)) < VOUCHER_WARMUP_TICKS:
            return
        voucher_delta = self._voucher_delta(manager, model)
        portfolio_delta = voucher_delta + manager.position(VELVET)
        symbols = list(CENTRAL_VOUCHERS)
        if CONFIG.get("use_deep_itm", True):
            symbols = list(DEEP_ITM) + symbols
        mult = self._aggression_multiplier()
        for symbol in symbols:
            depth = state.order_depths.get(symbol)
            fair = model["fair"].get(symbol)
            signal = model["signal"].get(symbol)
            delta = float(model["delta"].get(symbol, 0.0))
            scale = float(model["scale"].get(symbol, 1.2))
            if depth is None or fair is None or signal is None or not math.isfinite(signal):
                continue
            spread = top_spread(depth) or 2.0
            is_deep = symbol in DEEP_ITM
            cross_edge = max(0.60, 0.42 * spread + 0.25 * scale) * mult
            passive_edge = max(0.52, 0.30 * spread + 0.16 * scale) * mult
            if is_deep:
                cross_edge += max(2.0, 0.65 * spread)
                passive_edge += 3.0
            max_take = self._voucher_take_size(abs(signal), spread, is_deep)
            position = manager.position(symbol)
            for ask in sorted(depth.sell_orders):
                edge = fair - ask
                if edge < cross_edge:
                    break
                if not self._voucher_risk_allows(portfolio_delta, voucher_delta, delta, 1):
                    break
                qty = min(-int(depth.sell_orders[ask]), max_take)
                qty = self._cap_voucher_add(symbol, position, qty)
                qty = self._cap_voucher_delta(voucher_delta, portfolio_delta, delta, qty)
                if qty <= 0:
                    break
                filled = manager.add(symbol, ask, qty)
                position += filled
                voucher_delta += filled * delta
                portfolio_delta += filled * delta
                max_take -= filled
                if max_take <= 0:
                    break

            position = manager.position(symbol)
            max_take = self._voucher_take_size(abs(signal), spread, is_deep)
            for bid in sorted(depth.buy_orders, reverse=True):
                edge = bid - fair
                if edge < cross_edge:
                    break
                if not self._voucher_risk_allows(portfolio_delta, voucher_delta, delta, -1):
                    break
                qty = min(int(depth.buy_orders[bid]), max_take)
                qty = self._cap_voucher_add(symbol, position, -qty)
                qty = self._cap_voucher_delta(voucher_delta, portfolio_delta, delta, qty)
                if qty >= 0:
                    break
                filled = manager.add(symbol, bid, qty)
                position += filled
                voucher_delta += filled * delta
                portfolio_delta += filled * delta
                max_take -= abs(filled)
                if max_take <= 0:
                    break

            if is_deep:
                continue
            bid = best_bid(depth)
            ask = best_ask(depth)
            if bid is None or ask is None:
                continue
            position = manager.position(symbol)
            quote_qty = 4 if abs(position) < 90 else 2
            bid_price = min(bid + 1, math.floor(fair - passive_edge))
            if bid_price < ask and self._voucher_risk_allows(portfolio_delta, voucher_delta, delta, 1):
                qty = self._cap_voucher_delta(voucher_delta, portfolio_delta, delta, self._cap_voucher_add(symbol, position, quote_qty))
                if qty > 0:
                    filled = manager.add(symbol, bid_price, qty)
                    voucher_delta += filled * delta
                    portfolio_delta += filled * delta
            position = manager.position(symbol)
            ask_price = max(ask - 1, math.ceil(fair + passive_edge))
            if ask_price > bid and self._voucher_risk_allows(portfolio_delta, voucher_delta, delta, -1):
                qty = self._cap_voucher_delta(voucher_delta, portfolio_delta, delta, self._cap_voucher_add(symbol, position, -quote_qty))
                if qty < 0:
                    filled = manager.add(symbol, ask_price, qty)
                    voucher_delta += filled * delta
                    portfolio_delta += filled * delta

    def _trade_velvet_flow(self, state, memory, manager, mid, model):
        if not CONFIG.get("use_counterparties", True) or not CONFIG.get("use_velvet_names", True):
            return
        depth = state.order_depths.get(VELVET)
        if depth is None or mid is None:
            return
        signal = float(memory.get("vel_sig", 0.0))
        if abs(signal) < 0.55:
            return
        spread = top_spread(depth) or 6.0
        fair = float(mid) + signal - 0.030 * manager.position(VELVET)
        edge = max(2.6, 0.55 * spread)
        max_qty = 5
        position = manager.position(VELVET)
        if signal > 0:
            for ask in sorted(depth.sell_orders):
                if ask > fair - edge or position >= 70:
                    break
                filled = manager.add(VELVET, ask, min(-int(depth.sell_orders[ask]), max_qty, 70 - position))
                position += filled
                max_qty -= filled
                if max_qty <= 0:
                    break
        else:
            for bid in sorted(depth.buy_orders, reverse=True):
                if bid < fair + edge or position <= -70:
                    break
                qty = min(int(depth.buy_orders[bid]), max_qty, position + 70)
                filled = manager.add(VELVET, bid, -qty)
                position += filled
                max_qty -= abs(filled)
                if max_qty <= 0:
                    break

    def _voucher_take_size(self, edge, spread, is_deep):
        if is_deep:
            return 3 if edge > spread + 4.0 else 1
        if edge > spread + 2.0:
            return 12
        if edge > spread + 0.8:
            return 8
        return 4

    def _cap_voucher_add(self, symbol, position, desired):
        if desired == 0:
            return 0
        limit = min(LIMITS[symbol], DEEP_ITM_SOFT_CAP if symbol in DEEP_ITM else VOUCHER_SOFT_CAP)
        if desired > 0 and position >= 0:
            return max(0, min(desired, limit - position))
        if desired < 0 and position <= 0:
            return -max(0, min(-desired, limit + position))
        return desired

    def _voucher_delta(self, manager, model):
        total = 0.0
        for symbol in DEEP_ITM + CENTRAL_VOUCHERS:
            total += manager.position(symbol) * float(model["delta"].get(symbol, 0.0))
        return total

    def _voucher_risk_allows(self, portfolio_delta, voucher_delta, option_delta, side):
        added_delta = side * float(option_delta)
        new_voucher_delta = voucher_delta + added_delta
        if abs(new_voucher_delta) > VOUCHER_DELTA_HARD and abs(new_voucher_delta) > abs(voucher_delta):
            return False
        if abs(voucher_delta) > VOUCHER_DELTA_SOFT and abs(new_voucher_delta) > abs(voucher_delta):
            return False
        new_portfolio_delta = portfolio_delta + added_delta
        if abs(new_portfolio_delta) > PORTFOLIO_DELTA_HARD and abs(new_portfolio_delta) > abs(portfolio_delta):
            return False
        return True

    def _cap_voucher_delta(self, voucher_delta, portfolio_delta, option_delta, desired):
        desired = int(desired)
        if desired == 0:
            return 0
        change_per_lot = float(option_delta)
        if abs(change_per_lot) <= 1e-9:
            return desired
        change = desired * change_per_lot
        max_qty = abs(desired)
        if abs(voucher_delta) > VOUCHER_DELTA_SOFT and abs(voucher_delta + change) > abs(voucher_delta):
            return 0
        if abs(voucher_delta + change) > VOUCHER_DELTA_HARD and abs(voucher_delta + change) > abs(voucher_delta):
            remaining = max(0.0, VOUCHER_DELTA_HARD - abs(voucher_delta))
            max_qty = min(max_qty, int(remaining / abs(change_per_lot)))
        if abs(portfolio_delta + change) > PORTFOLIO_DELTA_HARD and abs(portfolio_delta + change) > abs(portfolio_delta):
            remaining = max(0.0, PORTFOLIO_DELTA_HARD - abs(portfolio_delta))
            max_qty = min(max_qty, int(remaining / abs(change_per_lot)))
        if max_qty <= 0:
            return 0
        return max_qty if desired > 0 else -max_qty

    def _hedge_velvet(self, state, manager, mid, model):
        depth = state.order_depths.get(VELVET)
        if depth is None or mid is None:
            return
        spread = top_spread(depth) or 6.0
        voucher_delta = self._voucher_delta(manager, model)
        net_delta = manager.position(VELVET) + voucher_delta
        if abs(net_delta) < PORTFOLIO_DELTA_SOFT:
            return
        if spread > 6.5 and abs(net_delta) < PORTFOLIO_DELTA_HARD:
            return
        hedge_target = 20.0 if net_delta > 0 else -20.0
        desired = int(round(hedge_target - net_delta))
        max_hedge = 24 if abs(net_delta) > 95 else 14
        desired = int(clamp(desired, -max_hedge, max_hedge))
        if desired > 0:
            ask = best_ask(depth)
            if ask is not None:
                manager.add(VELVET, ask, desired)
        elif desired < 0:
            bid = best_bid(depth)
            if bid is not None:
                manager.add(VELVET, bid, desired)

    def _update_state(self, memory, model, mids):
        h_mid = mids.get(HYDROGEL)
        if h_mid is not None:
            memory["h_slow"] = round(ewma(memory.get("h_slow"), h_mid, HYDROGEL_SLOW_ALPHA), 4)
            memory["h_med"] = round(ewma(memory.get("h_med"), h_mid, HYDROGEL_MED_ALPHA), 4)
            memory["h_fast"] = round(ewma(memory.get("h_fast"), h_mid, HYDROGEL_FAST_ALPHA), 4)
        else:
            memory["h_slow"] = round(float(memory.get("h_slow", HYDROGEL_PRIOR)), 4)
            memory["h_med"] = round(float(memory.get("h_med", memory["h_slow"])), 4)
            memory["h_fast"] = round(float(memory.get("h_fast", memory["h_med"])), 4)
        v_mid = mids.get(VELVET)
        memory["v_ewma"] = round(ewma(memory.get("v_ewma"), v_mid, 0.03) or (v_mid or 5250.0), 4)
        memory["iv"] = round(float(model.get("centre_iv", memory.get("iv", PRIOR_IV))), 6)

        offsets = memory.get("off", {})
        scales = memory.get("sc", {})
        new_offsets = {}
        new_scales = {}
        for symbol in DEEP_ITM + CENTRAL_VOUCHERS:
            raw = model["raw_residual"].get(symbol)
            previous_offset = float(offsets.get(symbol, 0.0))
            if raw is None:
                new_offset = previous_offset
                signal_abs = float(scales.get(symbol, 1.2))
            else:
                alpha = 0.018 if symbol in DEEP_ITM else 0.035
                new_offset = ewma(previous_offset, raw, alpha)
                signal_abs = abs(float(raw) - new_offset)
            previous_scale = float(scales.get(symbol, 1.2))
            new_scale = ewma(previous_scale, signal_abs, 0.04)
            clip = 4.0 if symbol in DEEP_ITM else 7.0
            new_offsets[symbol] = round(clamp(new_offset, -clip, clip), 5)
            new_scales[symbol] = round(clamp(new_scale, 0.7, 4.0), 5)
        memory["off"] = new_offsets
        memory["sc"] = new_scales
