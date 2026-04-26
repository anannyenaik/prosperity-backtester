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
PRIOR_IV = 0.26
MIN_IV = 0.02
MAX_IV = 2.5

HYDROGEL_ANCHOR = 9991.0
HYDROGEL_SOFT_CAP = 60
VOUCHER_SOFT_CAP = 150
VOUCHER_DELTA_SOFT = 135.0
VOUCHER_DELTA_HARD = 175.0
PORTFOLIO_DELTA_SOFT = 150.0
PORTFOLIO_DELTA_HARD = 190.0
VOUCHER_WARMUP_TICKS = 25


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
    hi = 0.35
    while black_scholes_call(s, k, tte, hi) < observed and hi < MAX_IV:
        hi *= 1.7
    if hi >= MAX_IV and black_scholes_call(s, k, tte, hi) < observed:
        return None
    for _ in range(28):
        mid = 0.5 * (lo + hi)
        model = black_scholes_call(s, k, tte, mid)
        if model < observed:
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
    def __init__(self, state: TradingState):
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
        self._trade_vouchers(state, memory, manager, voucher_model)
        self._hedge_velvet(state, memory, manager, mids.get(VELVET), voucher_model)

        self._update_state(memory, voucher_model, mids)
        return manager.orders, 0, json.dumps(memory, separators=(",", ":"))

    def _trade_hydrogel(self, state, memory, manager, mid):
        depth = state.order_depths.get(HYDROGEL)
        if depth is None or mid is None:
            return
        spread = top_spread(depth) or 16.0
        prev_ewma = memory.get("h_ewma")
        slow_ewma = ewma(memory.get("h_slow"), mid, 0.004)
        local_soft_cap = HYDROGEL_SOFT_CAP
        live_ewma = ewma(prev_ewma, mid, 0.025)
        trend_away_from_anchor = (
            (mid > HYDROGEL_ANCHOR and live_ewma > slow_ewma + 2.5)
            or (mid < HYDROGEL_ANCHOR and live_ewma < slow_ewma - 2.5)
        )
        position = manager.position(HYDROGEL)
        fair = 0.62 * HYDROGEL_ANCHOR + 0.28 * live_ewma + 0.10 * mid
        fair -= 0.035 * position

        take_edge = max(3.2, 0.23 * spread)
        max_take = 22 if abs(position) < local_soft_cap else 10
        for ask in sorted(depth.sell_orders):
            if ask > fair - take_edge:
                break
            if trend_away_from_anchor and mid < HYDROGEL_ANCHOR and position >= 0:
                break
            if position >= local_soft_cap and ask >= HYDROGEL_ANCHOR:
                break
            available = -int(depth.sell_orders[ask])
            qty = min(available, max_take)
            if position + qty > local_soft_cap and position >= 0:
                qty = max(0, local_soft_cap - position)
            filled = manager.add(HYDROGEL, ask, qty)
            position += filled
            max_take -= max(0, filled)
            if max_take <= 0:
                break

        position = manager.position(HYDROGEL)
        max_take = 22 if abs(position) < local_soft_cap else 10
        for bid in sorted(depth.buy_orders, reverse=True):
            if bid < fair + take_edge:
                break
            if trend_away_from_anchor and mid > HYDROGEL_ANCHOR and position <= 0:
                break
            if position <= -local_soft_cap and bid <= HYDROGEL_ANCHOR:
                break
            available = int(depth.buy_orders[bid])
            qty = min(available, max_take)
            if position - qty < -local_soft_cap and position <= 0:
                qty = max(0, position + local_soft_cap)
            filled = manager.add(HYDROGEL, bid, -qty)
            position += filled
            max_take -= abs(filled)
            if max_take <= 0:
                break

        bid = best_bid(depth)
        ask = best_ask(depth)
        if bid is None or ask is None:
            return
        quote_size = 8 if abs(manager.position(HYDROGEL)) < local_soft_cap else 4
        passive_edge = max(5.0, 0.35 * spread)
        bid_price = min(bid + 1, math.floor(fair - passive_edge))
        ask_price = max(ask - 1, math.ceil(fair + passive_edge))
        position = manager.position(HYDROGEL)
        if bid_price < ask and position < local_soft_cap:
            manager.add(HYDROGEL, bid_price, quote_size)
        if ask_price > bid and position > -local_soft_cap:
            manager.add(HYDROGEL, ask_price, -quote_size)
        memory["h_slow"] = round(float(slow_ewma), 4)

    def _voucher_model(self, state, memory, mids):
        spot = mids.get(VELVET)
        model = {
            "spot": spot,
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
        for symbol in ACTIVE_VOUCHERS:
            mid = mids.get(symbol)
            iv = implied_vol_call(mid, spot, STRIKES[symbol], FINAL_TTE)
            if iv is not None and MIN_IV <= iv <= MAX_IV:
                iv_by_symbol[symbol] = iv

        all_iv = median(iv_by_symbol.values())
        previous_iv = float(memory.get("iv", PRIOR_IV))
        if all_iv is None:
            centre_iv = previous_iv
        else:
            centre_iv = clamp(0.85 * previous_iv + 0.15 * all_iv, MIN_IV, MAX_IV)
        model["centre_iv"] = centre_iv
        model["valid"] = len(iv_by_symbol) >= 3

        offsets = memory.get("off", {})
        scales = memory.get("sc", {})
        for symbol in ACTIVE_VOUCHERS:
            strike = STRIKES[symbol]
            mids_without_self = [iv for other, iv in iv_by_symbol.items() if other != symbol]
            local_iv = median(mids_without_self)
            if local_iv is None:
                local_iv = centre_iv
            local_iv = clamp(0.60 * centre_iv + 0.40 * local_iv, MIN_IV, MAX_IV)
            base_fair = black_scholes_call(spot, strike, FINAL_TTE, local_iv)
            offset = float(offsets.get(symbol, 0.0))
            fair = base_fair + offset
            mid = mids.get(symbol)
            raw_residual = None if mid is None else float(mid) - base_fair
            signal = None if mid is None else float(mid) - fair
            model["fair"][symbol] = fair
            model["raw_residual"][symbol] = raw_residual
            model["signal"][symbol] = signal
            model["scale"][symbol] = max(0.7, min(4.0, float(scales.get(symbol, 1.2))))
            model["delta"][symbol] = call_delta(spot, strike, FINAL_TTE, local_iv)
        return model

    def _trade_vouchers(self, state, memory, manager, model):
        if not model.get("valid"):
            return
        warm = int(memory.get("tick", 0)) >= VOUCHER_WARMUP_TICKS
        if not warm:
            return

        voucher_delta = self._voucher_delta(manager, model)
        portfolio_delta = voucher_delta + manager.position(VELVET)
        for symbol in ACTIVE_VOUCHERS:
            depth = state.order_depths.get(symbol)
            if depth is None:
                continue
            fair = model["fair"].get(symbol)
            signal = model["signal"].get(symbol)
            delta = float(model["delta"].get(symbol, 0.0))
            scale = float(model["scale"].get(symbol, 1.2))
            if fair is None or signal is None or not math.isfinite(signal):
                continue
            spread = top_spread(depth) or 2.0
            cross_edge = max(0.55, 0.38 * spread + 0.22 * scale)
            passive_edge = max(0.45, 0.25 * spread + 0.15 * scale)
            max_take = self._voucher_take_size(abs(signal), spread)
            position = manager.position(symbol)

            for ask in sorted(depth.sell_orders):
                edge = fair - ask
                if edge < cross_edge:
                    break
                if not self._voucher_risk_allows(portfolio_delta, voucher_delta, delta, 1):
                    break
                available = -int(depth.sell_orders[ask])
                qty = min(available, max_take)
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
            max_take = self._voucher_take_size(abs(signal), spread)
            for bid in sorted(depth.buy_orders, reverse=True):
                edge = bid - fair
                if edge < cross_edge:
                    break
                if not self._voucher_risk_allows(portfolio_delta, voucher_delta, delta, -1):
                    break
                available = int(depth.buy_orders[bid])
                qty = min(available, max_take)
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

            bid = best_bid(depth)
            ask = best_ask(depth)
            if bid is None or ask is None:
                continue
            position = manager.position(symbol)
            quote_qty = 4 if abs(position) < 90 else 2
            bid_price = min(bid + 1, math.floor(fair - passive_edge))
            if bid_price < ask and self._voucher_risk_allows(portfolio_delta, voucher_delta, delta, 1):
                qty = self._cap_voucher_add(symbol, position, quote_qty)
                qty = self._cap_voucher_delta(voucher_delta, portfolio_delta, delta, qty)
                if qty > 0:
                    filled = manager.add(symbol, bid_price, qty)
                    voucher_delta += filled * delta
                    portfolio_delta += filled * delta
            position = manager.position(symbol)
            ask_price = max(ask - 1, math.ceil(fair + passive_edge))
            if ask_price > bid and self._voucher_risk_allows(portfolio_delta, voucher_delta, delta, -1):
                qty = self._cap_voucher_add(symbol, position, -quote_qty)
                qty = self._cap_voucher_delta(voucher_delta, portfolio_delta, delta, qty)
                if qty < 0:
                    filled = manager.add(symbol, ask_price, qty)
                    voucher_delta += filled * delta
                    portfolio_delta += filled * delta

    def _voucher_take_size(self, edge, spread):
        if edge > spread + 2.0:
            return 14
        if edge > spread + 0.8:
            return 9
        return 5

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

        memory["v_ewma"] = ewma(memory.get("v_ewma"), mid, 0.03)

    def _update_state(self, memory, model, mids):
        h_mid = mids.get(HYDROGEL)
        v_mid = mids.get(VELVET)
        memory["h_ewma"] = round(ewma(memory.get("h_ewma"), h_mid, 0.025) or HYDROGEL_ANCHOR, 4)
        memory["h_slow"] = round(ewma(memory.get("h_slow"), h_mid, 0.004) or HYDROGEL_ANCHOR, 4)
        memory["v_ewma"] = round(ewma(memory.get("v_ewma"), v_mid, 0.03) or (v_mid or 5250.0), 4)
        memory["iv"] = round(float(model.get("centre_iv", memory.get("iv", PRIOR_IV))), 6)

        offsets = memory.get("off", {})
        scales = memory.get("sc", {})
        new_offsets = {}
        new_scales = {}
        for symbol in ACTIVE_VOUCHERS:
            raw = model["raw_residual"].get(symbol)
            previous_offset = float(offsets.get(symbol, 0.0))
            if raw is None:
                new_offset = previous_offset
                signal_abs = float(scales.get(symbol, 1.2))
            else:
                new_offset = ewma(previous_offset, raw, 0.035)
                signal_abs = abs(float(raw) - new_offset)
            previous_scale = float(scales.get(symbol, 1.2))
            new_scale = ewma(previous_scale, signal_abs, 0.04)
            new_offsets[symbol] = round(clamp(new_offset, -8.0, 8.0), 5)
            new_scales[symbol] = round(clamp(new_scale, 0.7, 4.0), 5)
        memory["off"] = new_offsets
        memory["sc"] = new_scales
