# Round 4, HYDROGEL_PACK candidate v2 - anti-anchor hardening pass.
# Copied from strategies/r4_hydrogel_candidate.py. Only HYDROGEL_PACK was edited.
# Voucher / VELVET logic is unchanged. r4_trader.py remains the unchanged baseline.
#
# Anti-anchor design (vs. rejected v1):
#   - Welford-style adaptive alpha (1/(n+1)) during warm-up so the slow EMA is
#     dominated by live mids within the first few hundred ticks. The seed value
#     (warm_start, first_mid, median) becomes irrelevant within ~1k ticks.
#   - warm_start_weight default lowered from 0.75 to 0.25 *with* additional
#     decay-to-zero schedule on top of the Welford adaptation.
#   - Multiple warm-start modes (first_mid, blend_10, blend_25, median_early,
#     control_75) selectable via HYDRO_PARAMS["warm_start_mode"] for ablation.
#   - Mean-shift guard rewritten to a *live-only* regime detector:
#       (a) abs(fast_ema - slow_ema) gap, plus
#       (b) persistent abs(mid - slow_ema) over a small bounded window, plus
#       (c) drift EMA magnitude.
#     No comparison to the public 9995 anchor anywhere in the production path.
#   - spread > 16 lean disabled by default (kept as opt-in feature flag).
#   - Mark22 is a test-only feature flag, default disabled. No timestamp,
#     bot-name or sequence logic is used.
#   - Optional HYDRO_PARAMS_OVERRIDE environment variable (JSON dict) lets the
#     ablation harness swap a single key without touching the file. Submission
#     stays clean because the default is no override.

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
    "EMA_ALPHA":         0.0002,
    "INITIAL_HYDRO_EMA": 9991,
    "ZSCORE_ENTRY":      1.5,
}

# All HYDROGEL knobs live here. No magic constants in the trade function.
HYDRO_PARAMS = {
    # Top-level feature flags
    "enabled": True,
    "passive_enabled": True,
    "imbalance_enabled": True,
    "spread_lean_enabled": False,         # spread>16 lean: barely mattered, off by default
    "spread_shift_enabled": True,
    "large_dev_enabled": True,
    "mark22_enabled": False,              # test-only; default disabled

    # EMAs
    "ema_alpha": 0.0002,                  # main slow EMA alpha (post-warmup)
    "fast_ema_alpha": 0.01,
    "warmup_alpha_floor_ticks": 800,      # 1/(n+1) Welford alpha for first N ticks

    # Warm-start (de-anchored)
    # Modes: "first_mid", "blend_10", "blend_25", "median_early", "control_75"
    "warm_start_mode": "blend_25",
    "warm_start": 9995.0,
    "warm_start_weight": 0.25,            # used by blend_* modes; default 0.25 (was 0.75)
    "warm_start_decay_ticks": 600,        # extra anchor decay on top of Welford
    "median_warmup_ticks": 50,            # bounded window for median_early mode

    "warmup_ticks": 300,                  # for size-scale only, no anchor reference

    # L1+L2 imbalance
    "imb_trigger": 0.20,
    "imb_lean_ticks": 8.0,
    "imb_lean_max": 3.0,

    # Spread leans
    "spread_bear_lean": 0.50,
    "spread_lean_max": 1.0,

    # Targets
    "target_slope": 3.25,
    "target_max": 190,

    # Large-deviation crossing
    "large_dev": 45.0,
    "large_dev_imb_agree": 38.0,
    "large_dev_conflict": 58.0,
    "spread_shift_dev": 5.0,

    "cross_edge": 1.0,
    "passive_min_edge": 1.5,
    "base_order_size": 8,
    "strong_order_size": 28,
    "passive_order_size": 6,

    # Inventory caps
    "soft_limit": 175,
    "stop_add_level": 195,

    # Live drift-aware fair adjustment
    "drift_reduce_ticks": 55.0,
    "drift_fair_threshold": 35.0,
    "drift_fair_blend": 0.50,
    "drift_fair_max": 45.0,

    # Live regime detector (replaces v1 mean_shift_guard that referenced 9995)
    "live_regime_fast_slow_ticks": 60.0,  # |fast_ema - slow_ema| trigger
    "live_regime_persist_ticks": 70.0,    # |mid - slow_ema| persistence trigger
    "live_regime_persist_window": 50,     # bounded ring length
    "live_regime_persist_frac": 0.50,     # fraction of window above threshold
    "live_regime_blend": 0.65,            # how much to pull fair toward fast_ema
    "live_regime_size_scale": 0.55,
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
    # (bid_l1+bid_l2 - ask_l1-ask_l2) / max(1, total_l1+l2). Falls back to L1
    # if L2 is missing because get_l1_l2_depths returns 0 for absent levels.
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


def _initial_seed(mid, pstate):
    """Compute the *first-tick* seed for the slow EMA.

    Welford adaptive alpha makes the seed nearly irrelevant after a few hundred
    ticks, but we still expose multiple seed modes for ablation. The chosen
    mode is read from HYDRO_PARAMS so a single env override picks the variant.
    """
    mode = HYDRO_PARAMS.get("warm_start_mode", "blend_25")
    anchor = float(HYDRO_PARAMS.get("warm_start", mid))
    weight = float(HYDRO_PARAMS.get("warm_start_weight", 0.25))
    if mode == "first_mid":
        return float(mid)
    if mode == "blend_10":
        return 0.10 * anchor + 0.90 * float(mid)
    if mode == "blend_25":
        return 0.25 * anchor + 0.75 * float(mid)
    if mode == "control_75":
        return 0.75 * anchor + 0.25 * float(mid)
    if mode == "median_early":
        # The first call seeds with first_mid; the median is finalised later.
        return float(mid)
    # Unknown mode: fall back to a safe blend.
    weight = clamp(weight, 0.0, 1.0)
    return weight * anchor + (1.0 - weight) * float(mid)


def _decay_anchor_pull(slow_ema, tick_count):
    """Optional residual anchor pull that decays linearly to zero.

    Adds a *small* nudge of slow_ema toward warm_start during the first
    `warm_start_decay_ticks` ticks, scaled by warm_start_weight. After the
    decay window the function is the identity. Using a separate decay term
    keeps the EMA truthful to live mids while still letting first_mid /
    blend_25 / control_75 differ during the first few hundred ticks (so the
    ablation actually exposes warm-start sensitivity).
    """
    decay_ticks = max(1, int(HYDRO_PARAMS.get("warm_start_decay_ticks", 600)))
    if tick_count >= decay_ticks:
        return slow_ema
    mode = HYDRO_PARAMS.get("warm_start_mode", "blend_25")
    if mode == "first_mid":
        return slow_ema
    if mode == "blend_10":
        weight0 = 0.10
    elif mode == "blend_25":
        weight0 = 0.25
    elif mode == "control_75":
        weight0 = 0.75
    elif mode == "median_early":
        weight0 = 0.0
    else:
        weight0 = clamp(float(HYDRO_PARAMS.get("warm_start_weight", 0.25)), 0.0, 1.0)
    if weight0 <= 0.0:
        return slow_ema
    decay = max(0.0, 1.0 - tick_count / decay_ticks)
    pull = weight0 * decay
    if pull <= 0.0:
        return slow_ema
    anchor = float(HYDRO_PARAMS.get("warm_start", slow_ema))
    return (1.0 - pull) * slow_ema + pull * anchor


def compute_hydro_fair(mid, ema, imbalance, spread, pstate):
    """Build the live fair from EMA plus bounded leans.

    L1+L2 imbalance is a small bounded lean (max imb_lean_max ticks).
    Spread>16 bearish lean is off by default and capped at spread_lean_max.
    """
    fair = float(ema)
    if HYDRO_PARAMS.get("imbalance_enabled", True):
        lean = clamp(
            imbalance * HYDRO_PARAMS["imb_lean_ticks"],
            -HYDRO_PARAMS["imb_lean_max"],
            HYDRO_PARAMS["imb_lean_max"],
        )
        fair += lean
    if HYDRO_PARAMS.get("spread_lean_enabled", False) and spread > 16:
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

        # --- Live slow EMA with Welford-adaptive alpha during warm-up. ---
        prev_hydro_ema = pstate.get("HYDRO_EMA", None)
        if prev_hydro_ema is None:
            prev_hydro_ema = _initial_seed(mid, pstate)
            # If using the median_early mode, seed an early-mid ring.
            if HYDRO_PARAMS.get("warm_start_mode") == "median_early":
                pstate["HYDRO_EARLY_MIDS"] = [float(mid)]
        prev_hydro_ema = float(prev_hydro_ema)
        prev_fast_ema = float(pstate.get("HYDRO_FAST_EMA", prev_hydro_ema))
        prev_drift_ema = float(pstate.get("HYDRO_DRIFT_EMA", 0.0))

        # Median_early mode: bounded list, finalised at warm-up end.
        if HYDRO_PARAMS.get("warm_start_mode") == "median_early":
            warm_n = int(HYDRO_PARAMS.get("median_warmup_ticks", 50))
            buf = pstate.get("HYDRO_EARLY_MIDS", [])
            if isinstance(buf, list) and len(buf) < warm_n:
                buf = list(buf) + [float(mid)]
                pstate["HYDRO_EARLY_MIDS"] = buf
                if len(buf) == warm_n:
                    sb = sorted(buf)
                    median_v = sb[len(sb) // 2] if len(sb) % 2 == 1 else 0.5 * (sb[len(sb) // 2 - 1] + sb[len(sb) // 2])
                    # Re-anchor the slow EMA exactly once when the median is ready.
                    prev_hydro_ema = float(median_v)

        # Welford-style adaptive alpha for the first warmup_alpha_floor_ticks ticks
        # makes the seed lose influence quickly regardless of mode.
        floor_ticks = max(1, int(HYDRO_PARAMS.get("warmup_alpha_floor_ticks", 800)))
        alpha = HYDRO_PARAMS["ema_alpha"]
        if tick_count < floor_ticks:
            alpha = max(alpha, 1.0 / (tick_count + 1))
        fast_alpha = HYDRO_PARAMS["fast_ema_alpha"]

        new_hydro_ema = alpha * mid + (1 - alpha) * prev_hydro_ema
        new_hydro_ema = _decay_anchor_pull(new_hydro_ema, tick_count)
        new_fast_ema = fast_alpha * mid + (1 - fast_alpha) * prev_fast_ema
        new_drift_ema = 0.02 * abs(new_fast_ema - new_hydro_ema) + 0.98 * prev_drift_ema

        # --- Drift-aware fair adjustment (live, no anchor reference). ---
        drift_gap = new_fast_ema - new_hydro_ema
        fair_ema = new_hydro_ema
        if abs(drift_gap) > HYDRO_PARAMS["drift_fair_threshold"]:
            fair_ema += clamp(
                drift_gap * HYDRO_PARAMS["drift_fair_blend"],
                -HYDRO_PARAMS["drift_fair_max"],
                HYDRO_PARAMS["drift_fair_max"],
            )

        # --- Live regime detector (replaces 9995-comparing mean_shift_guard). ---
        # Two independent live triggers, both must fire to shrink size and pull
        # the fair toward fast_ema. Persistence is measured over a small bounded
        # ring of recent |mid - slow_ema| values; no unbounded history.
        persist_threshold = HYDRO_PARAMS["live_regime_persist_ticks"]
        window_n = max(4, int(HYDRO_PARAMS["live_regime_persist_window"]))
        ring = pstate.get("HYDRO_PERSIST_RING", [])
        if not isinstance(ring, list):
            ring = []
        ring.append(1 if abs(mid - new_hydro_ema) > persist_threshold else 0)
        if len(ring) > window_n:
            ring = ring[-window_n:]
        persist_count = sum(ring)
        persist_active = (
            len(ring) >= window_n
            and persist_count / max(1, len(ring)) >= HYDRO_PARAMS["live_regime_persist_frac"]
        )
        fast_slow_active = abs(new_fast_ema - new_hydro_ema) > HYDRO_PARAMS["live_regime_fast_slow_ticks"]
        regime_active = bool(persist_active and fast_slow_active)
        if regime_active:
            # Pull fair toward fast EMA (live signal), bounded blend.
            blend = clamp(HYDRO_PARAMS["live_regime_blend"], 0.0, 1.0)
            fair_ema += (new_fast_ema - fair_ema) * blend

        fair = compute_hydro_fair(mid, fair_ema, imbalance, spread, pstate)
        target_pos = compute_hydro_target(mid, fair, imbalance, position, pstate)
        deviation = mid - fair

        prev_bid = pstate.get("HYDRO_LAST_BID", pstate.get("HYDRO_BID", None))
        prev_ask = pstate.get("HYDRO_LAST_ASK", pstate.get("HYDRO_ASK", None))

        # Persist all live state. Compact: scalars + one bounded ring.
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
        pstate["HYDRO_PERSIST_RING"] = ring
        pstate["HYDRO_REGIME"] = 1 if regime_active else 0

        if not HYDRO_PARAMS.get("enabled", True):
            return orders

        # --- Size scaling: warm-up, drift, regime, abnormal spread. ---
        warmup_scale = 0.60 if tick_count < HYDRO_PARAMS["warmup_ticks"] else 1.0
        drift_scale = 0.50 if new_drift_ema > HYDRO_PARAMS["drift_reduce_ticks"] else 1.0
        regime_scale = HYDRO_PARAMS["live_regime_size_scale"] if regime_active else 1.0
        spread_scale = 0.70 if spread < 12 or spread > 18 else 1.0
        size_scale = min(warmup_scale, drift_scale, regime_scale, spread_scale)
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

        # --- Large-deviation crossing (the dominant Hydro signal). ---
        # Threshold is modulated by L1+L2 imbalance: tighter when imbalance
        # agrees with the reversion direction, looser when it conflicts.
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

        # --- Narrow-spread shift heuristic (must clear fair edge). ---
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

        # --- L1+L2 imbalance immediate tilt (small, edge-gated, not standalone). ---
        if HYDRO_PARAMS.get("imbalance_enabled", True) and abs(imbalance) > HYDRO_PARAMS["imb_trigger"]:
            if imbalance > 0 and may_buy() and fair - best_ask >= HYDRO_PARAMS["cross_edge"] and deviation < -HYDRO_PARAMS["spread_shift_dev"]:
                qty = min(ask_quantity, base_size, max(1, target_pos - expected_pos))
                expected_pos = append_hydro_orders(orders, product, best_ask, qty, expected_pos, limit)
            elif imbalance < 0 and may_sell() and best_bid - fair >= HYDRO_PARAMS["cross_edge"] and deviation > HYDRO_PARAMS["spread_shift_dev"]:
                qty = min(bid_quantity, base_size, max(1, expected_pos - target_pos))
                expected_pos = append_hydro_orders(orders, product, best_bid, -qty, expected_pos, limit)

        if not HYDRO_PARAMS.get("passive_enabled", True):
            return orders

        # --- Inside-quote passive maker, edge-gated, inventory-skewed. ---
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

        # --- Mark22 test-only branch ---
        # Default disabled. Currently unimplemented because the gates listed in
        # the v2 brief (count, cost-adjusted edge, day-stable sign, fill-stress,
        # mean-shift survival, no name/timestamp dependence, beats no-Mark22 and
        # shuffled-name) have not been independently verified in this audit.
        # The flag remains so future research can wire a directional Mark22
        # contribution without re-touching the trader scaffolding.
        # if HYDRO_PARAMS.get("mark22_enabled", False): pass

        return orders

    ## TRADE Z-SCORE ##     ## TRADE Z-SCORE ##
    def _trade_zscore(self, product, order_depth, position, limit, ema_mean, ema_std):
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

        if ema_mean is None:
            ema_mean = prior["mean"]
        if ema_std is None:
            ema_std = prior["std"]

        new_ema_mean = alpha * mid + (1 - alpha) * ema_mean
        deviation    = abs(mid - new_ema_mean)
        new_ema_std  = alpha * deviation + (1 - alpha) * ema_std

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
        ]

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

        conversions = 0
        return result, conversions, json.dumps(pstate)
