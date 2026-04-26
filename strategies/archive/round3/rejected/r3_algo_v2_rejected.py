from __future__ import annotations

import json
import math

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from prosperity_backtester.datamodel import Order, OrderDepth, TradingState


HYDROGEL = "HYDROGEL_PACK"
VELVET = "VELVETFRUIT_EXTRACT"
ACTIVE_VOUCHERS = ("VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500")
DISABLED_VOUCHERS = ("VEV_4000", "VEV_4500", "VEV_6000", "VEV_6500")
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

LIMITS = {
    HYDROGEL: 200,
    VELVET: 200,
    "VEV_4000": 300,
    "VEV_4500": 300,
    "VEV_5000": 300,
    "VEV_5100": 300,
    "VEV_5200": 300,
    "VEV_5300": 300,
    "VEV_5400": 300,
    "VEV_5500": 300,
    "VEV_6000": 300,
    "VEV_6500": 300,
}

FINAL_TTE = 5.0 / 365.0
BASE_IV = 0.239
IV_CORRECTION_CLIP = 0.020
MIN_IV = 0.05
MAX_IV = 1.0
PER_STRIKE_OFFSETS = {
    "VEV_5000": -0.005,
    "VEV_5100": -0.003,
    "VEV_5200": 0.003,
    "VEV_5300": 0.007,
    "VEV_5400": -0.011,
    "VEV_5500": 0.005,
}

HYDROGEL_ANCHOR = 9991.0
HYDROGEL_SOFT_CAP = 100
HYDROGEL_FAST_ALPHA = 0.025
HYDROGEL_SLOW_ALPHA = 0.0002
HYDROGEL_W_ANCHOR = 0.40
HYDROGEL_W_SLOW = 0.50
HYDROGEL_W_MID = 0.10

VOUCHER_SOFT_CAP = 120
VOUCHER_DELTA_SOFT = 100.0
VOUCHER_DELTA_HARD = 160.0
PORTFOLIO_DELTA_SOFT = 90.0
PORTFOLIO_DELTA_HARD = 140.0
VOUCHER_WARMUP_TICKS = 25


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def best_bid(depth):
    return max(depth.buy_orders) if depth and depth.buy_orders else None


def best_ask(depth):
    return min(depth.sell_orders) if depth and depth.sell_orders else None


def simple_mid(depth):
    bid = best_bid(depth)
    ask = best_ask(depth)
    if bid is None or ask is None:
        return None
    return 0.5 * (bid + ask)


def top_spread(depth):
    bid = best_bid(depth)
    ask = best_ask(depth)
    if bid is None or ask is None:
        return None
    return max(1.0, float(ask - bid))


def median(values):
    clean = sorted(float(v) for v in values if v is not None and math.isfinite(float(v)))
    if not clean:
        return None
    n = len(clean)
    mid = n // 2
    if n % 2:
        return clean[mid]
    return 0.5 * (clean[mid - 1] + clean[mid])


def normal_cdf(value):
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


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
    if observed < 0.0 or s <= 0.0 or k <= 0.0:
        return None
    intrinsic = max(0.0, s - k)
    if observed < intrinsic - 1e-7 or observed > s + 1e-7:
        return None
    if observed <= intrinsic + 1e-7:
        return 0.0
    lo = MIN_IV
    hi = 0.4
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


def load_memory(raw):
    if not raw:
        return {}
    try:
        memory = json.loads(raw)
        return memory if isinstance(memory, dict) else {}
    except Exception:
        return {}


def ewma(previous, value, alpha):
    if value is None or not math.isfinite(float(value)):
        return previous
    if previous is None:
        return float(value)
    return (1.0 - alpha) * float(previous) + alpha * float(value)


class OrderManager:
    def __init__(self, state):
        self.state = state
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

        manager = OrderManager(state)
        mids = {product: simple_mid(depth) for product, depth in state.order_depths.items()}

        memory["tick"] = int(memory.get("tick", 0)) + 1
        memory["last_ts"] = int(state.timestamp)

        self._trade_hydrogel(state, memory, manager, mids.get(HYDROGEL))

        voucher_model = self._voucher_model(state, memory, mids)
        self._trade_vouchers_passive(state, memory, manager, voucher_model)
        self._hedge_velvet(state, memory, manager, mids.get(VELVET), voucher_model)

        self._update_state(memory, voucher_model, mids)
        return manager.orders, 0, json.dumps(memory, separators=(",", ":"))

    def _trade_hydrogel(self, state, memory, manager, mid):
        depth = state.order_depths.get(HYDROGEL)
        if depth is None or mid is None:
            return
        spread = top_spread(depth) or 16.0

        live_ewma = ewma(memory.get("h_ewma"), mid, HYDROGEL_FAST_ALPHA)
        slow_seed = memory.get("h_slow")
        if slow_seed is None:
            slow_seed = HYDROGEL_ANCHOR
        slow_ewma = ewma(slow_seed, mid, HYDROGEL_SLOW_ALPHA)

        position = manager.position(HYDROGEL)
        soft = HYDROGEL_SOFT_CAP

        fair = HYDROGEL_W_ANCHOR * HYDROGEL_ANCHOR + HYDROGEL_W_SLOW * float(slow_ewma) + HYDROGEL_W_MID * mid
        skew_strength = 0.04 + 0.04 * (abs(position) / max(1, soft))
        fair -= skew_strength * position

        live_for_trend = live_ewma if live_ewma is not None else mid
        trend_away = (
            (mid > fair + 3.0 and live_for_trend > float(slow_ewma) + 2.0)
            or (mid < fair - 3.0 and live_for_trend < float(slow_ewma) - 2.0)
        )

        take_edge = max(3.0, 0.22 * spread)
        max_take = 24 if abs(position) < soft * 0.7 else (12 if abs(position) < soft else 6)

        for ask in sorted(depth.sell_orders):
            if ask > fair - take_edge:
                break
            if trend_away and mid < fair and position >= 0:
                break
            if position >= soft and ask >= fair:
                break
            available = -int(depth.sell_orders[ask])
            qty = min(available, max_take)
            if position + qty > soft and position >= 0:
                qty = max(0, soft - position)
            filled = manager.add(HYDROGEL, ask, qty)
            position += filled
            max_take -= max(0, filled)
            if max_take <= 0:
                break

        position = manager.position(HYDROGEL)
        max_take = 24 if abs(position) < soft * 0.7 else (12 if abs(position) < soft else 6)
        for bid in sorted(depth.buy_orders, reverse=True):
            if bid < fair + take_edge:
                break
            if trend_away and mid > fair and position <= 0:
                break
            if position <= -soft and bid <= fair:
                break
            available = int(depth.buy_orders[bid])
            qty = min(available, max_take)
            if position - qty < -soft and position <= 0:
                qty = max(0, position + soft)
            filled = manager.add(HYDROGEL, bid, -qty)
            position += filled
            max_take -= abs(filled)
            if max_take <= 0:
                break

        bid = best_bid(depth)
        ask = best_ask(depth)
        if bid is None or ask is None:
            return
        passive_edge = max(4.0, 0.30 * spread)
        position = manager.position(HYDROGEL)
        quote_size = 8 if abs(position) < soft * 0.6 else (4 if abs(position) < soft else 2)
        bid_price = min(bid + 1, math.floor(fair - passive_edge))
        ask_price = max(ask - 1, math.ceil(fair + passive_edge))
        if bid_price < ask and position < soft:
            manager.add(HYDROGEL, bid_price, quote_size)
        if ask_price > bid and position > -soft:
            manager.add(HYDROGEL, ask_price, -quote_size)

    def _voucher_model(self, state, memory, mids):
        spot = mids.get(VELVET)
        model = {
            "spot": spot,
            "fair": {},
            "delta": {},
            "iv_correction": float(memory.get("iv_corr", 0.0)),
            "valid": False,
        }
        if spot is None:
            return model

        observed_residuals = []
        per_symbol_observed_iv = {}
        for symbol in ACTIVE_VOUCHERS:
            mid = mids.get(symbol)
            iv_obs = implied_vol_call(mid, spot, STRIKES[symbol], FINAL_TTE)
            if iv_obs is None:
                continue
            base_with_offset = BASE_IV + PER_STRIKE_OFFSETS.get(symbol, 0.0)
            observed_residuals.append(iv_obs - base_with_offset)
            per_symbol_observed_iv[symbol] = iv_obs

        live_residual = median(observed_residuals)
        previous_correction = float(memory.get("iv_corr", 0.0))
        if live_residual is None:
            new_correction = previous_correction
        else:
            new_correction = ewma(previous_correction, live_residual, 0.05)
        new_correction = clamp(new_correction, -IV_CORRECTION_CLIP, IV_CORRECTION_CLIP)
        model["iv_correction"] = new_correction
        model["valid"] = len(per_symbol_observed_iv) >= 3

        for symbol in ACTIVE_VOUCHERS:
            strike = STRIKES[symbol]
            sigma = clamp(BASE_IV + PER_STRIKE_OFFSETS.get(symbol, 0.0) + new_correction, MIN_IV, MAX_IV)
            fair = black_scholes_call(spot, strike, FINAL_TTE, sigma)
            model["fair"][symbol] = fair
            model["delta"][symbol] = call_delta(spot, strike, FINAL_TTE, sigma)
        return model

    def _trade_vouchers_passive(self, state, memory, manager, model):
        if not model.get("valid"):
            return
        if int(memory.get("tick", 0)) < VOUCHER_WARMUP_TICKS:
            return

        voucher_delta = self._voucher_delta(manager, model)
        portfolio_delta = voucher_delta + manager.position(VELVET)

        for symbol in ACTIVE_VOUCHERS:
            depth = state.order_depths.get(symbol)
            if depth is None:
                continue
            fair = model["fair"].get(symbol)
            delta = float(model["delta"].get(symbol, 0.0))
            if fair is None or not math.isfinite(fair):
                continue
            bid = best_bid(depth)
            ask = best_ask(depth)
            if bid is None or ask is None:
                continue
            spread = max(1.0, float(ask - bid))
            position = manager.position(symbol)

            cross_edge = max(1.10, 0.55 * spread)
            passive_edge = max(0.55, 0.30 * spread)
            base_take = 6 if abs(position) < VOUCHER_SOFT_CAP * 0.5 else (3 if abs(position) < VOUCHER_SOFT_CAP else 0)

            if base_take > 0:
                max_take = base_take
                for ask_px in sorted(depth.sell_orders):
                    edge = fair - ask_px
                    if edge < cross_edge:
                        break
                    if not self._voucher_risk_allows(portfolio_delta, voucher_delta, delta, 1):
                        break
                    available = -int(depth.sell_orders[ask_px])
                    qty = min(available, max_take)
                    qty = self._cap_voucher_add(symbol, position, qty)
                    qty = self._cap_voucher_delta(voucher_delta, portfolio_delta, delta, qty)
                    if qty <= 0:
                        break
                    filled = manager.add(symbol, ask_px, qty)
                    position += filled
                    voucher_delta += filled * delta
                    portfolio_delta += filled * delta
                    max_take -= filled
                    if max_take <= 0:
                        break

                position = manager.position(symbol)
                max_take = base_take
                for bid_px in sorted(depth.buy_orders, reverse=True):
                    edge = bid_px - fair
                    if edge < cross_edge:
                        break
                    if not self._voucher_risk_allows(portfolio_delta, voucher_delta, delta, -1):
                        break
                    available = int(depth.buy_orders[bid_px])
                    qty = min(available, max_take)
                    qty = self._cap_voucher_add(symbol, position, -qty)
                    qty = self._cap_voucher_delta(voucher_delta, portfolio_delta, delta, qty)
                    if qty >= 0:
                        break
                    filled = manager.add(symbol, bid_px, qty)
                    position += filled
                    voucher_delta += filled * delta
                    portfolio_delta += filled * delta
                    max_take -= abs(filled)
                    if max_take <= 0:
                        break

            position = manager.position(symbol)
            quote_qty = 3 if abs(position) < VOUCHER_SOFT_CAP * 0.6 else (1 if abs(position) < VOUCHER_SOFT_CAP else 0)
            bid_price = min(bid + 1, int(math.floor(fair - passive_edge)))
            ask_price = max(ask - 1, int(math.ceil(fair + passive_edge)))

            if quote_qty > 0 and bid_price < ask and bid_price >= 1:
                if self._voucher_risk_allows(portfolio_delta, voucher_delta, delta, 1):
                    qty = self._cap_voucher_add(symbol, position, quote_qty)
                    qty = self._cap_voucher_delta(voucher_delta, portfolio_delta, delta, qty)
                    if qty > 0:
                        filled = manager.add(symbol, bid_price, qty)
                        voucher_delta += filled * delta
                        portfolio_delta += filled * delta

            position = manager.position(symbol)
            if quote_qty > 0 and ask_price > bid:
                if self._voucher_risk_allows(portfolio_delta, voucher_delta, delta, -1):
                    qty = self._cap_voucher_add(symbol, position, -quote_qty)
                    qty = self._cap_voucher_delta(voucher_delta, portfolio_delta, delta, qty)
                    if qty < 0:
                        filled = manager.add(symbol, ask_price, qty)
                        voucher_delta += filled * delta
                        portfolio_delta += filled * delta

    def _cap_voucher_add(self, symbol, position, desired):
        if desired == 0:
            return 0
        limit = min(LIMITS[symbol], VOUCHER_SOFT_CAP)
        if desired > 0 and position >= 0:
            return max(0, min(desired, limit - position))
        if desired < 0 and position <= 0:
            return -max(0, min(-desired, limit + position))
        return desired

    def _voucher_delta(self, manager, model):
        total = 0.0
        for symbol in ACTIVE_VOUCHERS:
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
        if abs(voucher_delta) > VOUCHER_DELTA_SOFT and abs(voucher_delta + change) > abs(voucher_delta):
            return 0
        max_qty = abs(desired)
        if abs(voucher_delta + change) > VOUCHER_DELTA_HARD and abs(voucher_delta + change) > abs(voucher_delta):
            remaining = max(0.0, VOUCHER_DELTA_HARD - abs(voucher_delta))
            max_qty = min(max_qty, int(remaining / abs(change_per_lot)))
        if abs(portfolio_delta + change) > PORTFOLIO_DELTA_HARD and abs(portfolio_delta + change) > abs(portfolio_delta):
            remaining = max(0.0, PORTFOLIO_DELTA_HARD - abs(portfolio_delta))
            max_qty = min(max_qty, int(remaining / abs(change_per_lot)))
        if max_qty <= 0:
            return 0
        return max_qty if desired > 0 else -max_qty

    def _hedge_velvet(self, state, memory, manager, mid, model):
        depth = state.order_depths.get(VELVET)
        if depth is None or mid is None:
            return
        if not model.get("valid"):
            return
        spread = top_spread(depth) or 6.0
        voucher_delta = self._voucher_delta(manager, model)
        net_delta = manager.position(VELVET) + voucher_delta

        if abs(net_delta) < PORTFOLIO_DELTA_SOFT:
            return
        if spread > 6.0 and abs(net_delta) < PORTFOLIO_DELTA_HARD:
            return

        if abs(net_delta) >= PORTFOLIO_DELTA_HARD:
            target_residual = math.copysign(PORTFOLIO_DELTA_SOFT * 0.5, net_delta)
        else:
            target_residual = math.copysign(PORTFOLIO_DELTA_SOFT * 0.7, net_delta)
        desired = int(round(target_residual - net_delta))
        max_hedge = 24 if abs(net_delta) > PORTFOLIO_DELTA_HARD else 12
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
        v_mid = mids.get(VELVET)
        memory["h_ewma"] = round(ewma(memory.get("h_ewma"), h_mid, HYDROGEL_FAST_ALPHA) or HYDROGEL_ANCHOR, 4)
        memory["h_slow"] = round(ewma(memory.get("h_slow"), h_mid, HYDROGEL_SLOW_ALPHA) or HYDROGEL_ANCHOR, 4)
        memory["v_ewma"] = round(ewma(memory.get("v_ewma"), v_mid, 0.03) or (v_mid or 5250.0), 4)
        memory["iv_corr"] = round(float(model.get("iv_correction", 0.0)), 6)
