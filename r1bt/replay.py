"""
Historical replay: play a trader through the REAL CSV data from data/round1/.

This is the equivalent of `prosperity3bt runner.py`. It does NOT use the sim
engine; instead it feeds the trader the exact book snapshots from the CSVs, and
matches orders against (a) the book, then (b) the historical trades.

Use this to validate that a strategy that works in Monte Carlo also works on the
actual historical data (and vice versa).
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .datamodel import (
    Listing, Observation, Order, OrderDepth, Trade, TradingState,
)
from .engine import POSITION_LIMIT, Ledger, _fill_involves_strategy
from .simulate import PRODUCTS, TIMESTAMP_STEP


@dataclass
class ReplayResult:
    day: int
    final_pnl: float
    per_product_pnl: Dict[str, float]
    per_product_final_position: Dict[str, int]
    per_tick_pnl: List[Tuple[int, str, float]]      # (timestamp, product, mtm)
    fills: List[Trade]
    limit_breaches: int


def _load_day(data_dir: Path, day: int):
    prices = []
    with open(data_dir / f"prices_round_1_day_{day}.csv", encoding="utf-8") as f:
        header = f.readline()
        for line in f:
            cols = line.rstrip("\n").split(";")
            row = {
                "day": int(cols[0]),
                "timestamp": int(cols[1]),
                "product": cols[2],
                "bid_prices": [int(cols[i]) for i in (3, 5, 7) if cols[i] != ""],
                "bid_volumes": [int(cols[i]) for i in (4, 6, 8) if cols[i] != ""],
                "ask_prices": [int(cols[i]) for i in (9, 11, 13) if cols[i] != ""],
                "ask_volumes": [int(cols[i]) for i in (10, 12, 14) if cols[i] != ""],
                "mid_price": float(cols[15]) if cols[15] else 0.0,
            }
            prices.append(row)

    trades = []
    tp = data_dir / f"trades_round_1_day_{day}.csv"
    if tp.is_file():
        with open(tp, encoding="utf-8") as f:
            header = f.readline()
            for line in f:
                cols = line.rstrip("\n").split(";")
                if len(cols) < 7:
                    continue
                trades.append({
                    "timestamp": int(cols[0]),
                    "buyer": cols[1],
                    "seller": cols[2],
                    "symbol": cols[3],
                    "price": int(float(cols[5])),
                    "quantity": int(cols[6]),
                })

    prices_by_ts: Dict[int, Dict[str, dict]] = defaultdict(dict)
    for p in prices:
        prices_by_ts[p["timestamp"]][p["product"]] = p
    trades_by_ts: Dict[int, Dict[str, List[dict]]] = defaultdict(lambda: defaultdict(list))
    for t in trades:
        trades_by_ts[t["timestamp"]][t["symbol"]].append(t)

    return prices_by_ts, trades_by_ts


def run_replay(trader, day: int, data_dir: Optional[Path] = None) -> ReplayResult:
    data_dir = data_dir or (Path(__file__).parent.parent / "data" / "round1")
    prices_by_ts, trades_by_ts = _load_day(data_dir, day)

    ledgers = {p: Ledger() for p in PRODUCTS}
    trader_data = ""
    prev_own_trades: Dict[str, List[Trade]] = {p: [] for p in PRODUCTS}
    prev_market_trades: Dict[str, List[Trade]] = {p: [] for p in PRODUCTS}

    per_tick_pnl: List[Tuple[int, str, float]] = []
    all_fills: List[Trade] = []
    limit_breaches = 0

    timestamps = sorted(prices_by_ts.keys())
    for ts in timestamps:
        # Build the state
        od = {}
        for p in PRODUCTS:
            row = prices_by_ts[ts].get(p)
            depth = OrderDepth()
            if row:
                for px, vol in zip(row["bid_prices"], row["bid_volumes"]):
                    depth.buy_orders[px] = vol
                for px, vol in zip(row["ask_prices"], row["ask_volumes"]):
                    depth.sell_orders[px] = -vol
            od[p] = depth

        listings = {p: Listing(p, p, "XIRECS") for p in PRODUCTS}
        state = TradingState(
            traderData=trader_data, timestamp=ts,
            listings=listings, order_depths=od,
            own_trades=prev_own_trades, market_trades=prev_market_trades,
            position={p: ledgers[p].position for p in PRODUCTS},
            observations=Observation({}, {}),
        )

        orders_raw, conversions, trader_data = trader.run(state)
        orders = {p: orders_raw.get(p, []) if orders_raw else [] for p in PRODUCTS}

        own_trades_tick: Dict[str, List[Trade]] = {p: [] for p in PRODUCTS}
        market_trades_tick: Dict[str, List[Trade]] = {p: [] for p in PRODUCTS}

        for p in PRODUCTS:
            pos = ledgers[p].position
            total_buy = sum(o.quantity for o in orders[p] if o.quantity > 0)
            total_sell = sum(-o.quantity for o in orders[p] if o.quantity < 0)
            if pos + total_buy > POSITION_LIMIT or pos - total_sell < -POSITION_LIMIT:
                limit_breaches += 1
                continue

            depth = od[p]
            hist_tr = trades_by_ts.get(ts, {}).get(p, [])
            # First, match vs book
            for order in orders[p]:
                if order.quantity > 0:
                    # Cross asks
                    for ask_px in sorted(list(depth.sell_orders.keys())):
                        if ask_px > order.price:
                            break
                        avail = abs(depth.sell_orders[ask_px])
                        fq = min(order.quantity, avail)
                        if fq <= 0:
                            continue
                        tr = Trade(p, ask_px, fq, "SUBMISSION", "", ts)
                        own_trades_tick[p].append(tr)
                        all_fills.append(tr)
                        ledgers[p].position += fq
                        ledgers[p].cash -= ask_px * fq
                        new_vol = depth.sell_orders[ask_px] + fq
                        if new_vol == 0:
                            depth.sell_orders.pop(ask_px)
                        else:
                            depth.sell_orders[ask_px] = new_vol
                        order.quantity -= fq
                        if order.quantity == 0:
                            break

                    # Then try to match against historical trades (price ≤ order.price)
                    for htr in hist_tr:
                        if order.quantity <= 0:
                            break
                        if htr["price"] > order.price:
                            continue
                        avail = htr["quantity"]
                        if avail <= 0:
                            continue
                        fq = min(order.quantity, avail)
                        tr = Trade(p, order.price, fq, "SUBMISSION", htr["seller"] or "", ts)
                        own_trades_tick[p].append(tr)
                        all_fills.append(tr)
                        ledgers[p].position += fq
                        ledgers[p].cash -= order.price * fq
                        htr["quantity"] -= fq
                        order.quantity -= fq

                elif order.quantity < 0:
                    # Cross bids
                    for bid_px in sorted(list(depth.buy_orders.keys()), reverse=True):
                        if bid_px < order.price:
                            break
                        avail = depth.buy_orders[bid_px]
                        fq = min(-order.quantity, avail)
                        if fq <= 0:
                            continue
                        tr = Trade(p, bid_px, fq, "", "SUBMISSION", ts)
                        own_trades_tick[p].append(tr)
                        all_fills.append(tr)
                        ledgers[p].position -= fq
                        ledgers[p].cash += bid_px * fq
                        depth.buy_orders[bid_px] -= fq
                        if depth.buy_orders[bid_px] == 0:
                            depth.buy_orders.pop(bid_px)
                        order.quantity += fq
                        if order.quantity == 0:
                            break
                    for htr in hist_tr:
                        if order.quantity >= 0:
                            break
                        if htr["price"] < order.price:
                            continue
                        avail = htr["quantity"]
                        if avail <= 0:
                            continue
                        fq = min(-order.quantity, avail)
                        tr = Trade(p, order.price, fq, htr["buyer"] or "", "SUBMISSION", ts)
                        own_trades_tick[p].append(tr)
                        all_fills.append(tr)
                        ledgers[p].position -= fq
                        ledgers[p].cash += order.price * fq
                        htr["quantity"] -= fq
                        order.quantity += fq

        # Remaining historical trades become market_trades for next tick
        for p in PRODUCTS:
            for htr in trades_by_ts.get(ts, {}).get(p, []):
                if htr["quantity"] > 0:
                    market_trades_tick[p].append(Trade(
                        p, htr["price"], htr["quantity"],
                        htr["buyer"], htr["seller"], ts,
                    ))

        # MTM at mid
        for p in PRODUCTS:
            row = prices_by_ts[ts].get(p)
            mid = row["mid_price"] if row and row["mid_price"] > 0 else 0.0
            if mid > 0:
                m = ledgers[p].cash + ledgers[p].position * mid
                per_tick_pnl.append((ts, p, m))

        prev_own_trades = own_trades_tick
        prev_market_trades = market_trades_tick

    # Final PnL at last observed mid for each product
    last_row_by_product = {}
    for ts in timestamps[::-1]:
        for p in PRODUCTS:
            if p in last_row_by_product:
                continue
            row = prices_by_ts[ts].get(p)
            if row and row["mid_price"] > 0:
                last_row_by_product[p] = row["mid_price"]
        if len(last_row_by_product) == len(PRODUCTS):
            break

    per_product_pnl = {}
    for p in PRODUCTS:
        mid = last_row_by_product.get(p, 10000.0)
        per_product_pnl[p] = ledgers[p].cash + ledgers[p].position * mid

    return ReplayResult(
        day=day, final_pnl=sum(per_product_pnl.values()),
        per_product_pnl=per_product_pnl,
        per_product_final_position={p: ledgers[p].position for p in PRODUCTS},
        per_tick_pnl=per_tick_pnl, fills=all_fills, limit_breaches=limit_breaches,
    )
