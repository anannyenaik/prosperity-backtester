"""Baseline trader: dumb market maker around hardcoded fair values.

Run to see how much PnL the empirical edges contribute vs. a naive baseline.
"""
from __future__ import annotations

from typing import Dict, List

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from prosperity_backtester.datamodel import Order, OrderDepth, TradingState


class Trader:
    """Naive: buy below fair, sell above fair, hardcoded fair per product.

    OSMIUM fair = 10000 (calibrated).
    PEPPER fair = 11500 (midpoint across 3 days; WILL LOSE MONEY because it
    ignores the drift - use trader.py for the real strategy).
    """

    FAIR = {"ASH_COATED_OSMIUM": 10_000, "INTARIAN_PEPPER_ROOT": 11_500}

    def run(self, state: TradingState):
        out: Dict[str, List[Order]] = {}
        for p, depth in state.order_depths.items():
            fair = self.FAIR.get(p, 10_000)
            orders: List[Order] = []
            if depth.sell_orders:
                best_ask = min(depth.sell_orders)
                if best_ask < fair:
                    orders.append(Order(p, best_ask, -depth.sell_orders[best_ask]))
            if depth.buy_orders:
                best_bid = max(depth.buy_orders)
                if best_bid > fair:
                    orders.append(Order(p, best_bid, -depth.buy_orders[best_bid]))
            out[p] = orders
        return out, 0, ""
