"""
Round 1 trader for ASH_COATED_OSMIUM and INTARIAN_PEPPER_ROOT.

Calibration-driven strategies:
  - OSMIUM: mean-revert around a stationary fair of 10000.
  - PEPPER: ride the +0.108/tick drift (confirmed across all 3 days).

Order-sizing invariant (avoids the +/-80 batch-drop penalty):
  Per product we track `long_head` (remaining capacity to buy) and `short_head`
  (remaining capacity to sell) across all phases. Every new order's size is
  capped by the appropriate head. This guarantees the engine's batch limit
  check always passes.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from prosperity_backtester.datamodel import Order, OrderDepth, TradingState


OSMIUM = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"
POS_LIMIT = 80


def _best_bid_ask(depth: OrderDepth):
    return (max(depth.buy_orders) if depth.buy_orders else None,
            min(depth.sell_orders) if depth.sell_orders else None)


# OSMIUM strategy

class OsmiumTrader:
    FAIR = 10_000          # calibrated mean across 3 days
    TAKE_MARGIN = 0        # take any ask <= 10000 / bid >= 10000
    MAKE_OFFSET = 4        # quote at 9996 / 10004, inside bot inner spread around 12
    MAKE_SIZE = 20
    MAX_TAKE = 30
    SKEW_POS_THRESHOLD = 40

    def decide(self, depth: Optional[OrderDepth], position: int) -> List[Order]:
        if depth is None:
            return []
        out: List[Order] = []
        fair = self.FAIR
        long_head = POS_LIMIT - position
        short_head = POS_LIMIT + position

        # Take asks.
        budget = min(self.MAX_TAKE, long_head)
        for ask_px in sorted(depth.sell_orders):
            if budget <= 0 or ask_px > fair + self.TAKE_MARGIN:
                break
            vol = -depth.sell_orders[ask_px]
            q = min(vol, budget)
            if q > 0:
                out.append(Order(OSMIUM, int(ask_px), q))
                long_head -= q
                budget -= q

        # Take bids.
        budget = min(self.MAX_TAKE, short_head)
        for bid_px in sorted(depth.buy_orders, reverse=True):
            if budget <= 0 or bid_px < fair - self.TAKE_MARGIN:
                break
            vol = depth.buy_orders[bid_px]
            q = min(vol, budget)
            if q > 0:
                out.append(Order(OSMIUM, int(bid_px), -q))
                short_head -= q
                budget -= q

        # Make.
        best_bid, best_ask = _best_bid_ask(depth)
        bid_px = fair - self.MAKE_OFFSET
        ask_px = fair + self.MAKE_OFFSET
        if best_bid is not None and bid_px <= best_bid:
            bid_px = best_bid + 1
        if best_ask is not None and ask_px >= best_ask:
            ask_px = best_ask - 1
        if bid_px >= ask_px:  # safety
            bid_px = fair - self.MAKE_OFFSET
            ask_px = fair + self.MAKE_OFFSET

        bid_size = self.MAKE_SIZE if position < self.SKEW_POS_THRESHOLD else 0
        ask_size = self.MAKE_SIZE if position > -self.SKEW_POS_THRESHOLD else 0
        bid_size = min(bid_size, long_head)
        ask_size = min(ask_size, short_head)

        if bid_size > 0:
            out.append(Order(OSMIUM, int(bid_px), bid_size))
        if ask_size > 0:
            out.append(Order(OSMIUM, int(ask_px), -ask_size))
        return out


# PEPPER strategy

class PepperTrader:
    DRIFT_PER_TICK = 0.108
    TAKE_BUFFER = 3           # take asks up to fair + 3
    MAKE_BID_OFFSET = 5
    MAKE_ASK_OFFSET = 4
    MAKE_BID_SIZE = 25
    MAX_TAKE = 30
    OFFLOAD_POS = 55

    def fair_value(self, state: TradingState, memory: dict, depth: Optional[OrderDepth]) -> float:
        ts = state.timestamp
        last_ts = memory.get("pep_ts")
        last_fair = memory.get("pep_fair")

        wall_center = None
        if depth is not None and depth.buy_orders and depth.sell_orders:
            wall_center = (min(depth.buy_orders) + max(depth.sell_orders)) / 2.0

        if last_ts is None or last_fair is None:
            fair = wall_center if wall_center is not None else 10000.0
        else:
            ticks_elapsed = max(0, (ts - last_ts) / 100.0)
            projected = last_fair + self.DRIFT_PER_TICK * ticks_elapsed
            if wall_center is not None:
                fair = 0.5 * projected + 0.5 * wall_center
            else:
                fair = projected

        memory["pep_ts"] = ts
        memory["pep_fair"] = fair
        return fair

    def decide(self, depth: Optional[OrderDepth], position: int, fair: float) -> List[Order]:
        if depth is None:
            return []
        out: List[Order] = []
        long_head = POS_LIMIT - position
        short_head = POS_LIMIT + position

        # Take asks for aggressive accumulation.
        budget = min(self.MAX_TAKE, long_head)
        for ask_px in sorted(depth.sell_orders):
            if budget <= 0 or ask_px > fair + self.TAKE_BUFFER:
                break
            vol = -depth.sell_orders[ask_px]
            q = min(vol, budget)
            if q > 0:
                out.append(Order(PEPPER, int(ask_px), q))
                long_head -= q
                budget -= q

        live_pos = position + ((POS_LIMIT - position) - long_head)

        # Offload when overweight.
        if live_pos > self.OFFLOAD_POS:
            budget = min(self.MAX_TAKE, short_head)
            min_sell_price = fair + 2
            for bid_px in sorted(depth.buy_orders, reverse=True):
                if budget <= 0 or bid_px < min_sell_price:
                    break
                vol = depth.buy_orders[bid_px]
                q = min(vol, budget, max(0, live_pos - self.OFFLOAD_POS + 5))
                if q > 0:
                    out.append(Order(PEPPER, int(bid_px), -q))
                    short_head -= q
                    budget -= q
                    live_pos -= q

        # Make bid. The drift walks into this.
        best_bid, best_ask = _best_bid_ask(depth)
        bid_px = int(fair - self.MAKE_BID_OFFSET)
        if best_bid is not None and bid_px <= best_bid:
            bid_px = best_bid + 1
        bid_size = min(self.MAKE_BID_SIZE, long_head)
        if bid_size > 0:
            out.append(Order(PEPPER, bid_px, bid_size))
            long_head -= bid_size

        # Make ask only when offloading is needed.
        if live_pos > self.OFFLOAD_POS:
            ask_px = int(fair + self.MAKE_ASK_OFFSET)
            if best_ask is not None and ask_px >= best_ask:
                ask_px = best_ask - 1
            ask_size = min(10, short_head, max(0, live_pos - self.OFFLOAD_POS))
            if ask_size > 0:
                out.append(Order(PEPPER, ask_px, -ask_size))

        return out


# Trader public API

class Trader:
    def __init__(self):
        self.osmium = OsmiumTrader()
        self.pepper = PepperTrader()

    def run(self, state: TradingState):
        try:
            memory = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            memory = {}

        results: Dict[str, List[Order]] = {}

        osm_pos = state.position.get(OSMIUM, 0)
        osm_depth = state.order_depths.get(OSMIUM)
        results[OSMIUM] = self.osmium.decide(osm_depth, osm_pos)

        pep_pos = state.position.get(PEPPER, 0)
        pep_depth = state.order_depths.get(PEPPER)
        pep_fair = self.pepper.fair_value(state, memory, pep_depth)
        results[PEPPER] = self.pepper.decide(pep_depth, pep_pos, pep_fair)

        return results, 0, json.dumps(memory)
