# Round 3, Hydrogel v2 - TESTING THE WATERS, HYDROGEL ONLY

## IMPORTS ##  ## IMPORTS ##  ## IMPORTS ##  ## IMPORTS ##  ## IMPORTS ##
try:
    from datamodel import OrderDepth, UserId, TradingState, Order
except ImportError:
    from prosperity_backtester.datamodel import OrderDepth, UserId, TradingState, Order
import math
import json

## GENERAL ##  ## GENERAL ##  ## GENERAL ##  ## GENERAL ##  ## GENERAL ##  
POS_LIMITS = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 300,
        "VEV_4500": 300,
        "VEV_5000": 300,
        "VEV_5100": 300,
        "VEV_5200": 300,
        "VEV_5300": 300,
        "VEV_5400": 300,
        "VEV_5500": 300,
        "VEV_6000": 300,
        "VEV_6500": 300
}

PARAMS = {
    "EMA_ALPHA":         0.0002,  # shared alpha for hydrogel EMA, options EMA mean & EMA std
    "INITIAL_HYDRO_EMA": 9991,
    "ZSCORE_ENTRY":      1.5,     # enter when |z| exceeds this threshold
}

HYDRO_PARAMS = {
    "enabled": True,
    "passive_enabled": True,
    "imbalance_enabled": True,
    "spread_lean_enabled": True,
    "spread_shift_enabled": True,
    "large_dev_enabled": True,
    "ema_alpha": 0.0002,
    "fast_ema_alpha": 0.01,
    "warm_start": 9995.0,
    "warm_start_weight": 0.75,
    "warmup_ticks": 300,
    "imb_trigger": 0.20,
    "imb_lean_ticks": 8.0,
    "imb_lean_max": 3.0,
    "spread_bear_lean": 0.50,
    "spread_lean_max": 1.0,
    "target_slope": 3.25,
    "target_max": 190,
    "large_dev": 45.0,
    "large_dev_imb_agree": 38.0,
    "large_dev_conflict": 58.0,
    "spread_shift_dev": 5.0,
    "cross_edge": 1.0,
    "passive_min_edge": 1.5,
    "base_order_size": 8,
    "strong_order_size": 28,
    "passive_order_size": 6,
    "soft_limit": 175,
    "stop_add_level": 195,
    "drift_reduce_ticks": 55.0,
    "drift_fair_threshold": 35.0,
    "drift_fair_blend": 0.50,
    "drift_fair_max": 45.0,
    "mean_shift_guard_ticks": 85.0,
    "mean_shift_guard_blend": 0.75,
    "mean_shift_size_scale": 0.50,
}


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def get_best_bid_ask(order_depth):
    if not order_depth.buy_orders or not order_depth.sell_orders:
        return None, 0, None, 0
    best_bid = max(order_depth.buy_orders)
    best_ask = min(order_depth.sell_orders)
    bid_qty = max(0, int(order_depth.buy_orders.get(best_bid, 0)))
    ask_qty = max(0, abs(int(order_depth.sell_orders.get(best_ask, 0))))
    if bid_qty <= 0 or ask_qty <= 0:
        return None, 0, None, 0
    return best_bid, bid_qty, best_ask, ask_qty


def get_mid(order_depth):
    best_bid, _, best_ask, _ = get_best_bid_ask(order_depth)
    if best_bid is None or best_ask is None:
        return None
    return (best_bid + best_ask) / 2.0


def get_l1_l2_depths(order_depth):
    bid_levels = sorted(order_depth.buy_orders.items(), reverse=True)[:2]
    ask_levels = sorted(order_depth.sell_orders.items())[:2]
    bid_l1_qty = abs(int(bid_levels[0][1])) if len(bid_levels) >= 1 else 0
    bid_l2_qty = abs(int(bid_levels[1][1])) if len(bid_levels) >= 2 else 0
    ask_l1_qty = abs(int(ask_levels[0][1])) if len(ask_levels) >= 1 else 0
    ask_l2_qty = abs(int(ask_levels[1][1])) if len(ask_levels) >= 2 else 0
    return bid_l1_qty, bid_l2_qty, ask_l1_qty, ask_l2_qty


def get_l1_l2_imbalance(order_depth):
    bid_l1_qty, bid_l2_qty, ask_l1_qty, ask_l2_qty = get_l1_l2_depths(order_depth)
    bid_depth = bid_l1_qty + bid_l2_qty
    ask_depth = ask_l1_qty + ask_l2_qty
    return (bid_depth - ask_depth) / max(1, bid_depth + ask_depth)


def safe_order(product, price, qty, expected_pos, limit):
    qty = int(qty)
    if qty > 0:
        qty = min(qty, limit - expected_pos)
    elif qty < 0:
        qty = -min(-qty, limit + expected_pos)
    if qty == 0:
        return None, expected_pos
    return Order(product, int(price), qty), expected_pos + qty


def append_hydro_orders(orders, product, price, qty, expected_pos, limit):
    order, expected_pos = safe_order(product, price, qty, expected_pos, limit)
    if order is not None:
        orders.append(order)
    return expected_pos


def compute_hydro_fair(mid, ema, imbalance, spread, pstate):
    fair = float(ema)
    if HYDRO_PARAMS.get("imbalance_enabled", True):
        lean = clamp(
            imbalance * HYDRO_PARAMS["imb_lean_ticks"],
            -HYDRO_PARAMS["imb_lean_max"],
            HYDRO_PARAMS["imb_lean_max"],
        )
        fair += lean
    if HYDRO_PARAMS.get("spread_lean_enabled", True) and spread > 16:
        fair -= clamp(
            (spread - 16) * HYDRO_PARAMS["spread_bear_lean"],
            0.0,
            HYDRO_PARAMS["spread_lean_max"],
        )
    return fair


def compute_hydro_target(mid, fair, imbalance, position, pstate):
    deviation = mid - fair
    slope = HYDRO_PARAMS["target_slope"]
    trigger = HYDRO_PARAMS["imb_trigger"]
    if abs(imbalance) > trigger:
        if (deviation > 0 and imbalance < 0) or (deviation < 0 and imbalance > 0):
            slope += 0.35
        else:
            slope -= 0.45
    target = -round(slope * deviation)
    return int(clamp(target, -HYDRO_PARAMS["target_max"], HYDRO_PARAMS["target_max"]))


# Historical mean and std computed from days 0-2 (30k ticks each).
# Seed values for the EMA mean and EMA std on the very first tick.
# VEV_6000 and VEV_6500 are excluded — permanently at 0.5, std=0, untradeable.
ZSCORE_PRIORS = {
    "VELVETFRUIT_EXTRACT": {"mean": 5250.0981, "std": 15.6304},
    "VEV_4000":            {"mean": 1250.1098, "std": 15.6472},
    "VEV_4500":            {"mean":  750.1096, "std": 15.6399},
    "VEV_5000":            {"mean":  255.0224, "std": 14.3756},
    "VEV_5100":            {"mean":  166.8054, "std": 12.7426},
    "VEV_5200":            {"mean":   95.5488, "std":  9.6642},
    "VEV_5300":            {"mean":   46.7599, "std":  6.2281},
    "VEV_5400":            {"mean":   15.9519, "std":  3.4292},
    "VEV_5500":            {"mean":    6.6414, "std":  1.7388},
}

class Trader:
    
    ## TRADE HYDROGEL ##     ## TRADE HYDROGEL ##
    def _trade_hydrogel(self, product, order_depth, position, limit, pstate):
        orders = []

        best_bid, bid_quantity, best_ask, ask_quantity = get_best_bid_ask(order_depth)
        mid = get_mid(order_depth)
        tick_count = int(pstate.get("HYDRO_TICK_COUNT", 0) or 0)
        if best_bid is None or best_ask is None or mid is None:
            pstate["HYDRO_TICK_COUNT"] = tick_count
            return orders

        spread = best_ask - best_bid
        imbalance = get_l1_l2_imbalance(order_depth)

        prev_hydro_ema = pstate.get("HYDRO_EMA", None)
        if prev_hydro_ema is None:
            warm_weight = HYDRO_PARAMS["warm_start_weight"]
            prev_hydro_ema = warm_weight * HYDRO_PARAMS["warm_start"] + (1 - warm_weight) * mid
        prev_fast_ema = pstate.get("HYDRO_FAST_EMA", prev_hydro_ema)
        prev_drift_ema = pstate.get("HYDRO_DRIFT_EMA", 0.0)

        alpha = HYDRO_PARAMS["ema_alpha"]
        fast_alpha = HYDRO_PARAMS["fast_ema_alpha"]
        new_hydro_ema = alpha * mid + (1 - alpha) * float(prev_hydro_ema)
        new_fast_ema = fast_alpha * mid + (1 - fast_alpha) * float(prev_fast_ema)
        new_drift_ema = 0.02 * abs(new_fast_ema - new_hydro_ema) + 0.98 * float(prev_drift_ema)

        drift_gap = new_fast_ema - new_hydro_ema
        fair_ema = new_hydro_ema
        if abs(drift_gap) > HYDRO_PARAMS["drift_fair_threshold"]:
            fair_ema += clamp(
                drift_gap * HYDRO_PARAMS["drift_fair_blend"],
                -HYDRO_PARAMS["drift_fair_max"],
                HYDRO_PARAMS["drift_fair_max"],
            )
        mean_shift_guard = abs(new_fast_ema - HYDRO_PARAMS["warm_start"]) > HYDRO_PARAMS["mean_shift_guard_ticks"]
        if mean_shift_guard:
            fair_ema += (new_fast_ema - fair_ema) * HYDRO_PARAMS["mean_shift_guard_blend"]
        fair = compute_hydro_fair(mid, fair_ema, imbalance, spread, pstate)
        target_pos = compute_hydro_target(mid, fair, imbalance, position, pstate)
        deviation = mid - fair

        prev_bid = pstate.get("HYDRO_LAST_BID", pstate.get("HYDRO_BID", None))
        prev_ask = pstate.get("HYDRO_LAST_ASK", pstate.get("HYDRO_ASK", None))

        pstate["HYDRO_EMA"] = new_hydro_ema
        pstate["HYDRO_FAST_EMA"] = new_fast_ema
        pstate["HYDRO_LAST_MID"] = mid
        pstate["HYDRO_LAST_BID"] = best_bid
        pstate["HYDRO_LAST_ASK"] = best_ask
        pstate["HYDRO_BID"] = best_bid
        pstate["HYDRO_ASK"] = best_ask
        pstate["HYDRO_DRIFT_EMA"] = new_drift_ema
        pstate["HYDRO_TICK_COUNT"] = tick_count + 1
        pstate["HYDRO_LAST_IMB"] = imbalance

        if not HYDRO_PARAMS.get("enabled", True):
            return orders

        warmup_scale = 0.60 if tick_count < HYDRO_PARAMS["warmup_ticks"] else 1.0
        drift_scale = 0.50 if new_drift_ema > HYDRO_PARAMS["drift_reduce_ticks"] else 1.0
        mean_shift_scale = HYDRO_PARAMS["mean_shift_size_scale"] if mean_shift_guard else 1.0
        spread_scale = 0.70 if spread < 12 or spread > 18 else 1.0
        size_scale = min(warmup_scale, drift_scale, mean_shift_scale, spread_scale)
        base_size = max(1, int(round(HYDRO_PARAMS["base_order_size"] * size_scale)))
        strong_size = max(1, int(round(HYDRO_PARAMS["strong_order_size"] * size_scale)))
        passive_size = max(1, int(round(HYDRO_PARAMS["passive_order_size"] * size_scale)))
        expected_pos = position

        def may_buy():
            if expected_pos >= HYDRO_PARAMS["stop_add_level"]:
                return False
            if expected_pos >= HYDRO_PARAMS["soft_limit"] and target_pos >= expected_pos:
                return False
            return expected_pos < limit

        def may_sell():
            if expected_pos <= -HYDRO_PARAMS["stop_add_level"]:
                return False
            if expected_pos <= -HYDRO_PARAMS["soft_limit"] and target_pos <= expected_pos:
                return False
            return expected_pos > -limit

        # Strong mean reversion is the only large crossing path.
        if HYDRO_PARAMS.get("large_dev_enabled", True):
            sell_threshold = HYDRO_PARAMS["large_dev_imb_agree"] if imbalance < -HYDRO_PARAMS["imb_trigger"] else HYDRO_PARAMS["large_dev"]
            buy_threshold = HYDRO_PARAMS["large_dev_imb_agree"] if imbalance > HYDRO_PARAMS["imb_trigger"] else HYDRO_PARAMS["large_dev"]
            if imbalance > HYDRO_PARAMS["imb_trigger"]:
                sell_threshold = HYDRO_PARAMS["large_dev_conflict"]
            if imbalance < -HYDRO_PARAMS["imb_trigger"]:
                buy_threshold = HYDRO_PARAMS["large_dev_conflict"]

            if deviation > sell_threshold and may_sell() and best_bid - fair >= HYDRO_PARAMS["cross_edge"]:
                qty_to_target = max(1, expected_pos - target_pos)
                qty = min(bid_quantity, strong_size, qty_to_target)
                expected_pos = append_hydro_orders(orders, product, best_bid, -qty, expected_pos, limit)
            elif deviation < -buy_threshold and may_buy() and fair - best_ask >= HYDRO_PARAMS["cross_edge"]:
                qty_to_target = max(1, target_pos - expected_pos)
                qty = min(ask_quantity, strong_size, qty_to_target)
                expected_pos = append_hydro_orders(orders, product, best_ask, qty, expected_pos, limit)

        # The old narrow-spread shift survives only when it still clears fair edge.
        if HYDRO_PARAMS.get("spread_shift_enabled", True) and prev_bid is not None and prev_ask is not None and spread <= 9:
            bid_shift = abs(best_bid - int(prev_bid))
            ask_shift = abs(best_ask - int(prev_ask))
            buy_spread = sell_spread = False
            if ask_shift > bid_shift + 2:
                buy_spread = True
            elif bid_shift > ask_shift + 2:
                sell_spread = True
            else:
                buy_spread = sell_spread = True

            if sell_spread and deviation > HYDRO_PARAMS["spread_shift_dev"] and may_sell() and best_bid - fair >= HYDRO_PARAMS["cross_edge"]:
                qty = min(bid_quantity, base_size, max(1, expected_pos - target_pos))
                expected_pos = append_hydro_orders(orders, product, best_bid, -qty, expected_pos, limit)
            if buy_spread and deviation < -HYDRO_PARAMS["spread_shift_dev"] and may_buy() and fair - best_ask >= HYDRO_PARAMS["cross_edge"]:
                qty = min(ask_quantity, base_size, max(1, target_pos - expected_pos))
                expected_pos = append_hydro_orders(orders, product, best_ask, qty, expected_pos, limit)

        # L1+L2 imbalance is a small immediate tilt, never a standalone anchor.
        if HYDRO_PARAMS.get("imbalance_enabled", True) and abs(imbalance) > HYDRO_PARAMS["imb_trigger"]:
            if imbalance > 0 and may_buy() and fair - best_ask >= HYDRO_PARAMS["cross_edge"] and deviation < -HYDRO_PARAMS["spread_shift_dev"]:
                qty = min(ask_quantity, base_size, max(1, target_pos - expected_pos))
                expected_pos = append_hydro_orders(orders, product, best_ask, qty, expected_pos, limit)
            elif imbalance < 0 and may_sell() and best_bid - fair >= HYDRO_PARAMS["cross_edge"] and deviation > HYDRO_PARAMS["spread_shift_dev"]:
                qty = min(bid_quantity, base_size, max(1, expected_pos - target_pos))
                expected_pos = append_hydro_orders(orders, product, best_bid, -qty, expected_pos, limit)

        if not HYDRO_PARAMS.get("passive_enabled", True):
            return orders

        # Small inside quotes harvest the normal 16-tick structure without forcing trades.
        fair_inside = best_bid < fair < best_ask
        if fair_inside and spread >= 12:
            buy_price = best_bid + 1
            sell_price = best_ask - 1
            inv_ratio = clamp(expected_pos / max(1, limit), -1.0, 1.0)
            buy_size = passive_size
            sell_size = passive_size
            if inv_ratio > 0:
                buy_size = max(1, int(round(buy_size * (1.0 - inv_ratio))))
                sell_size = int(round(sell_size * (1.0 + 0.5 * inv_ratio)))
            elif inv_ratio < 0:
                sell_size = max(1, int(round(sell_size * (1.0 + inv_ratio))))
                buy_size = int(round(buy_size * (1.0 - 0.5 * inv_ratio)))
            if imbalance > HYDRO_PARAMS["imb_trigger"]:
                buy_size += 1
            elif imbalance < -HYDRO_PARAMS["imb_trigger"]:
                sell_size += 1

            if may_buy() and buy_price < best_ask and fair - buy_price >= HYDRO_PARAMS["passive_min_edge"]:
                expected_pos = append_hydro_orders(orders, product, buy_price, buy_size, expected_pos, limit)
            if may_sell() and sell_price > best_bid and sell_price - fair >= HYDRO_PARAMS["passive_min_edge"]:
                expected_pos = append_hydro_orders(orders, product, sell_price, -sell_size, expected_pos, limit)

        return orders

    ## TRADE Z-SCORE ##     ## TRADE Z-SCORE ##
    def _trade_zscore(self, product, order_depth, position, limit, ema_mean, ema_std):
        """
        Z-score mean reversion using EMA mean and EMA std (alpha = EMA_ALPHA).
        Both are seeded from historical priors on the first tick and updated
        every tick thereafter — no rolling window, just two floats in pstate.

        EMA std tracks the EMA of |deviation| (mean absolute deviation),
        which is robust and sign-symmetric.

        Buys aggressively (hits ask) when z < -ZSCORE_ENTRY.
        Sells aggressively (hits bid) when z > +ZSCORE_ENTRY.
        Returns: (orders, new_ema_mean, new_ema_std)
        """
        orders = []

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders, ema_mean, ema_std

        best_bid    = max(order_depth.buy_orders.keys())
        bid_quantity = order_depth.buy_orders[best_bid]
        best_ask    = min(order_depth.sell_orders.keys())
        ask_quantity = order_depth.sell_orders[best_ask]
        mid = (best_ask + best_bid) / 2.0

        alpha        = PARAMS["EMA_ALPHA"]
        entry_thresh = PARAMS["ZSCORE_ENTRY"]
        prior        = ZSCORE_PRIORS[product]

        # Cold-start: seed from historical priors on the very first tick
        if ema_mean is None:
            ema_mean = prior["mean"]
        if ema_std is None:
            ema_std = prior["std"]

        # Update EMA mean
        new_ema_mean = alpha * mid + (1 - alpha) * ema_mean

        # Update EMA std as EMA of absolute deviation from the current mean
        deviation    = abs(mid - new_ema_mean)
        new_ema_std  = alpha * deviation + (1 - alpha) * ema_std

        # Guard against a degenerate flat series
        if new_ema_std < 1e-8:
            return orders, new_ema_mean, new_ema_std

        z = (mid - new_ema_mean) / new_ema_std

        buy_cap  = limit - position
        sell_cap = limit + position

        if z < -entry_thresh and buy_cap > 0:
            qty = min(-ask_quantity, buy_cap)
            if qty > 0:
                orders.append(Order(product, best_ask, qty))

        elif z > entry_thresh and sell_cap > 0:
            qty = min(bid_quantity, sell_cap)
            if qty > 0:
                orders.append(Order(product, best_bid, -qty))

        return orders, new_ema_mean, new_ema_std

    ## RUN ALGORITHMS ##     ## RUN ALGORITHMS ##
    def run(self, state: TradingState):
        result = {}

        # Load previous data
        pstate: dict = {}
        if state.traderData:
            try:
                pstate = json.loads(state.traderData)
            except Exception:
                pstate = {}

        options = [
            "VELVETFRUIT_EXTRACT",
            "VEV_4000", "VEV_4500", "VEV_5000",
            "VEV_5100", "VEV_5200", "VEV_5300",
            "VEV_5400", "VEV_5500",
            # VEV_6000, VEV_6500 excluded — permanently flat at 0.5, std=0
        ]

        # Run algorithms for all products
        for product, order_depth in state.order_depths.items():
            position = state.position.get(product, 0)
            limit    = POS_LIMITS.get(product, 20)

            if product == "HYDROGEL_PACK":
                orders = self._trade_hydrogel(product, order_depth, position, limit, pstate)

            elif product in options:
                ema_mean = pstate.get(f"ZSCORE_MEAN_{product}", None)
                ema_std  = pstate.get(f"ZSCORE_STD_{product}",  None)
                orders, new_ema_mean, new_ema_std = self._trade_zscore(
                    product, order_depth, position, limit, ema_mean, ema_std
                )
                pstate[f"ZSCORE_MEAN_{product}"] = new_ema_mean
                pstate[f"ZSCORE_STD_{product}"]  = new_ema_std

            else:
                orders = []

            result[product] = orders

        # Return results
        conversions = 0
        return result, conversions, json.dumps(pstate)
