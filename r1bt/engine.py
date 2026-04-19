"""
Core backtesting engine.

Implements the same order-matching semantics as the original Prosperity 4 Rust
simulator:
  - Strategy orders cross bot levels first (maker fills against the resting book)
  - Unfilled strategy orders become passive levels (tagged LevelOwner.STRATEGY)
  - Strategy cannot self-cross (best_ask.owner must be BOT for a buy to cross)
  - Simulated takers sweep the best price regardless of owner; strategy-owned
    levels that get hit update the ledger with the correct sign
  - Position limit (±80 per product): if cumulative long or short orders for a
    product would breach the limit, the entire batch for that product is dropped
    (matches the Rust engine's behavior)
  - MTM: cash + position × latent_fair (NOT mid price - latent is more faithful)

Session structure:
  - Each session runs a configurable number of days (default 3, like round 1)
  - Each day is 10,000 ticks × TIMESTAMP_STEP=100 → timestamp 0..999,900
  - Timestamps across days are offset by 1,000,000 each (matches Prosperity convention)
  - Each new day resets the book but NOT the trader (trader_data persists across
    days within a session, like the live competition)
"""
from __future__ import annotations

import random
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from .datamodel import (
    Listing,
    Observation,
    Order,
    OrderDepth,
    Trade,
    TradingState,
)
from .simulate import (
    BotBook,
    PRODUCTS,
    TICKS_PER_DAY,
    TIMESTAMP_STEP,
    book_to_order_depth,
    build_samplers,
    load_calibration,
    make_book,
    sample_trade_counts,
    sample_trade_quantity,
    simulate_latent_fair,
)


POSITION_LIMIT = 80
DAY_TIMESTAMP_OFFSET = 1_000_000


class LevelOwner(Enum):
    BOT = 0
    STRATEGY = 1


@dataclass
class Level:
    price: int
    quantity: int          # always positive
    owner: LevelOwner


@dataclass
class SimBook:
    """Live order book during a tick - bots + strategy passives, both sides."""
    bids: List[Level] = field(default_factory=list)  # desc by price
    asks: List[Level] = field(default_factory=list)  # asc by price


@dataclass
class Ledger:
    position: int = 0
    cash: float = 0.0


@dataclass
class Fill:
    symbol: str
    price: int
    quantity: int      # positive
    buyer: Optional[str]
    seller: Optional[str]
    timestamp: int


@dataclass
class TickTrace:
    """What we persist per tick for one sample session (dashboard path trace)."""
    timestamp: int
    fair: float
    position: Dict[str, int]
    cash: Dict[str, float]
    mtm: Dict[str, float]


@dataclass
class SessionResult:
    session_id: int
    days: List[int]
    total_pnl: float
    per_product_pnl: Dict[str, float]
    per_product_final_position: Dict[str, int]
    per_product_cash: Dict[str, float]
    # For the "slope / R²" metrics that the dashboard uses
    total_slope_per_step: float
    total_r2: float
    per_product_slope_per_step: Dict[str, float]
    per_product_r2: Dict[str, float]
    # Per-tick traces (only populated when capture_outputs=True)
    traces: Dict[str, List[TickTrace]] = field(default_factory=dict)


# ───────────────────────── book helpers ───────────────────────── #

def _sim_book_from_bot(book: BotBook) -> SimBook:
    return SimBook(
        bids=[Level(p, v, LevelOwner.BOT) for p, v in book.bids],
        asks=[Level(p, v, LevelOwner.BOT) for p, v in book.asks],
    )


def _insert_passive(levels: List[Level], new_level: Level, descending: bool):
    """Merge a strategy passive into the levels, maintaining sort order and
    giving bots priority at the same price."""
    for lev in levels:
        if lev.price == new_level.price and lev.owner == new_level.owner:
            lev.quantity += new_level.quantity
            return
    levels.append(new_level)
    if descending:
        levels.sort(key=lambda L: (-L.price, L.owner.value))
    else:
        levels.sort(key=lambda L: (L.price, L.owner.value))


def _enforce_position_limits(orders_by_product: Dict[str, List[Order]],
                             ledgers: Dict[str, Ledger]) -> Dict[str, List[Order]]:
    """Same semantics as the Rust enforce_strategy_limits: if cumulative long or
    short for a product would breach the ±80 limit, the ENTIRE batch for that
    product is discarded. This matches the live competition's batch-rejection."""
    out = {}
    for product, orders in orders_by_product.items():
        pos = ledgers.get(product, Ledger()).position
        total_buy = sum(o.quantity for o in orders if o.quantity > 0)
        total_sell = sum(-o.quantity for o in orders if o.quantity < 0)
        if pos + total_buy > POSITION_LIMIT or pos - total_sell < -POSITION_LIMIT:
            out[product] = []
        else:
            out[product] = orders
    return out


# ───────────────────────── order execution ───────────────────────── #

def _execute_strategy_orders(product: str, timestamp: int, book: SimBook,
                             ledger: Ledger, orders: List[Order]) -> List[Fill]:
    """Cross eligible orders against the current bot book; insert passives."""
    fills: List[Fill] = []
    passive_bids: Dict[int, int] = {}
    passive_asks: Dict[int, int] = {}

    for order in orders:
        if order.quantity > 0:  # buy
            remaining = order.quantity
            while remaining > 0 and book.asks:
                best = book.asks[0]
                if best.owner != LevelOwner.BOT or best.price > order.price:
                    break
                fq = min(remaining, best.quantity)
                fills.append(Fill(symbol=product, price=best.price, quantity=fq,
                                  buyer="SUBMISSION", seller="BOT", timestamp=timestamp))
                ledger.position += fq
                ledger.cash -= best.price * fq
                remaining -= fq
                best.quantity -= fq
                if best.quantity == 0:
                    book.asks.pop(0)
            if remaining > 0:
                passive_bids[order.price] = passive_bids.get(order.price, 0) + remaining
        elif order.quantity < 0:  # sell
            remaining = -order.quantity
            while remaining > 0 and book.bids:
                best = book.bids[0]
                if best.owner != LevelOwner.BOT or best.price < order.price:
                    break
                fq = min(remaining, best.quantity)
                fills.append(Fill(symbol=product, price=best.price, quantity=fq,
                                  buyer="BOT", seller="SUBMISSION", timestamp=timestamp))
                ledger.position -= fq
                ledger.cash += best.price * fq
                remaining -= fq
                best.quantity -= fq
                if best.quantity == 0:
                    book.bids.pop(0)
            if remaining > 0:
                passive_asks[order.price] = passive_asks.get(order.price, 0) + remaining

    for p, q in passive_bids.items():
        _insert_passive(book.bids, Level(p, q, LevelOwner.STRATEGY), descending=True)
    for p, q in passive_asks.items():
        _insert_passive(book.asks, Level(p, q, LevelOwner.STRATEGY), descending=False)

    return fills


def _execute_taker_trade(product: str, timestamp: int, book: SimBook,
                         ledger: Ledger, market_buy: bool, rng: random.Random,
                         samplers) -> List[Fill]:
    """A simulated market taker sweeps the best price. Strategy-owned levels
    that get hit update the ledger."""
    fills: List[Fill] = []
    side = book.asks if market_buy else book.bids
    avail = sum(L.quantity for L in side)
    if avail <= 0:
        return fills
    remaining = sample_trade_quantity(product, samplers, avail, rng)
    while remaining > 0 and side:
        best = side[0]
        fq = min(remaining, best.quantity)
        if fq <= 0:
            break
        if market_buy:
            if best.owner == LevelOwner.BOT:
                f = Fill(product, best.price, fq, "BOT_TAKER", "BOT_MAKER", timestamp)
            else:  # strategy was a resting ask; taker hits it
                ledger.position -= fq
                ledger.cash += best.price * fq
                f = Fill(product, best.price, fq, "BOT_TAKER", "SUBMISSION", timestamp)
        else:  # market sell
            if best.owner == LevelOwner.BOT:
                f = Fill(product, best.price, fq, "BOT_MAKER", "BOT_TAKER", timestamp)
            else:  # strategy was a resting bid; taker hits it
                ledger.position += fq
                ledger.cash -= best.price * fq
                f = Fill(product, best.price, fq, "SUBMISSION", "BOT_TAKER", timestamp)
        fills.append(f)
        best.quantity -= fq
        remaining -= fq
        if best.quantity == 0:
            side.pop(0)
    return fills


def _fill_involves_strategy(fill: Fill) -> bool:
    return fill.buyer == "SUBMISSION" or fill.seller == "SUBMISSION"


# ───────────────────────── running-linear-fit helper ───────────────────────── #

class RunningFit:
    """Online OLS on (step_index, mtm) - mirrors Rust RunningLinearFit."""
    __slots__ = ("n", "sx", "sy", "sxx", "syy", "sxy")

    def __init__(self):
        self.n = 0.0
        self.sx = 0.0
        self.sy = 0.0
        self.sxx = 0.0
        self.syy = 0.0
        self.sxy = 0.0

    def update(self, x: float, y: float):
        self.n += 1.0
        self.sx += x; self.sy += y
        self.sxx += x * x; self.syy += y * y
        self.sxy += x * y

    def slope_per_step(self) -> float:
        denom = self.n * self.sxx - self.sx * self.sx
        if abs(denom) < 1e-12:
            return 0.0
        return (self.n * self.sxy - self.sx * self.sy) / denom

    def r_squared(self) -> float:
        vx = self.n * self.sxx - self.sx * self.sx
        vy = self.n * self.syy - self.sy * self.sy
        if abs(vx) < 1e-12 or abs(vy) < 1e-12:
            return 0.0
        c = self.n * self.sxy - self.sx * self.sy
        return (c * c) / (vx * vy)


# ───────────────────────── session runner ───────────────────────── #

def _seed_for_session(base_seed: int, session_id: int) -> int:
    # Xorshift-style mix, deterministic + independent streams across sessions
    x = (base_seed ^ (session_id * 0xA24BAED4963EE407)) & 0xFFFFFFFFFFFFFFFF
    x ^= x >> 33
    x = (x * 0xFF51AFD7ED558CCD) & 0xFFFFFFFFFFFFFFFF
    x ^= x >> 33
    return x


def run_session(trader, session_id: int, calib: dict, samplers: dict,
                days: Tuple[int, ...] = (-2, -1, 0),
                base_seed: int = 20260401,
                capture_outputs: bool = False,
                strategy_timeout_s: float = 0.9) -> SessionResult:
    """Run one full session: trader.run(state) is invoked once per tick."""
    rng = random.Random(_seed_for_session(base_seed, session_id))

    # State across the whole session
    ledgers: Dict[str, Ledger] = {p: Ledger() for p in PRODUCTS}
    trader_data = ""
    prev_own_trades: Dict[str, List[Trade]] = {p: [] for p in PRODUCTS}
    prev_market_trades: Dict[str, List[Trade]] = {p: [] for p in PRODUCTS}

    total_fit = RunningFit()
    per_fit = {p: RunningFit() for p in PRODUCTS}
    traces: Dict[str, List[TickTrace]] = {p: [] for p in PRODUCTS} if capture_outputs else {}

    global_step = 0
    final_latent = {p: 10000.0 for p in PRODUCTS}
    # Track the last latent fair per product so each new day starts continuously
    last_latent = {p: None for p in PRODUCTS}

    for day_idx, day in enumerate(days):
        # Latent fair paths for this day, per product - CONTINUOUS across days
        latent_by_product = {
            p: simulate_latent_fair(p, calib, day_idx + 100 * session_id, rng,
                                    continue_from=last_latent[p])
            for p in PRODUCTS
        }
        trade_counts_by_product = {
            p: sample_trade_counts(p, calib, rng) for p in PRODUCTS
        }

        for tick in range(TICKS_PER_DAY):
            timestamp = day_idx * DAY_TIMESTAMP_OFFSET + tick * TIMESTAMP_STEP

            # Build fresh bot book for this tick (per product)
            bot_books = {p: make_book(p, latent_by_product[p][tick], samplers, calib, rng)
                         for p in PRODUCTS}

            # Build TradingState for trader
            order_depths = {p: book_to_order_depth(bot_books[p]) for p in PRODUCTS}
            listings = {p: Listing(p, p, "XIRECS") for p in PRODUCTS}
            positions = {p: ledgers[p].position for p in PRODUCTS}
            state = TradingState(
                traderData=trader_data,
                timestamp=timestamp,
                listings=listings,
                order_depths=order_depths,
                own_trades=prev_own_trades,
                market_trades=prev_market_trades,
                position=positions,
                observations=Observation({}, {}),
            )

            # Run strategy
            t0 = time.time()
            try:
                result = trader.run(state)
            except Exception as e:
                raise RuntimeError(f"Trader raised at t={timestamp}: {e}\n{traceback.format_exc()}")
            elapsed = time.time() - t0
            if elapsed > strategy_timeout_s:
                # In the real comp, strategies that exceed 900ms get dropped for that tick.
                # We log and continue so backtests don't blow up.
                result = ({p: [] for p in PRODUCTS}, 0, trader_data)

            orders_raw, conversions, trader_data = result
            # Normalize: missing products → empty lists
            orders = {p: orders_raw.get(p, []) if orders_raw else [] for p in PRODUCTS}
            orders = _enforce_position_limits(orders, ledgers)

            # Convert bot books → SimBooks for this tick
            live_books = {p: _sim_book_from_bot(bot_books[p]) for p in PRODUCTS}

            own_trades_tick: Dict[str, List[Trade]] = {p: [] for p in PRODUCTS}
            market_trades_tick: Dict[str, List[Trade]] = {p: [] for p in PRODUCTS}

            # 1. Strategy orders cross / rest
            for p in PRODUCTS:
                fills = _execute_strategy_orders(
                    p, timestamp, live_books[p], ledgers[p], orders[p]
                )
                for f in fills:
                    t = Trade(f.symbol, f.price, f.quantity, f.buyer, f.seller, f.timestamp)
                    own_trades_tick[p].append(t)

            # 2. Simulated takers
            for p in PRODUCTS:
                count = trade_counts_by_product[p][tick]
                for _ in range(count):
                    market_buy = rng.random() < calib[p]["trade_buy_prob"]
                    taker_fills = _execute_taker_trade(
                        p, timestamp, live_books[p], ledgers[p],
                        market_buy, rng, samplers
                    )
                    for f in taker_fills:
                        t = Trade(f.symbol, f.price, f.quantity, f.buyer, f.seller, f.timestamp)
                        if _fill_involves_strategy(f):
                            own_trades_tick[p].append(t)
                        else:
                            market_trades_tick[p].append(t)

            # 3. Per-tick MTM + trace
            mtm_total = 0.0
            mtm_per = {}
            for p in PRODUCTS:
                latent = latent_by_product[p][tick]
                final_latent[p] = latent
                mtm_p = ledgers[p].cash + ledgers[p].position * latent
                mtm_per[p] = mtm_p
                mtm_total += mtm_p
                per_fit[p].update(global_step, mtm_p)
                if capture_outputs:
                    traces[p].append(TickTrace(
                        timestamp=timestamp, fair=latent,
                        position={p: ledgers[p].position},
                        cash={p: ledgers[p].cash},
                        mtm={p: mtm_p},
                    ))
            total_fit.update(global_step, mtm_total)
            global_step += 1

            # Shift trades for next tick's state
            prev_own_trades = own_trades_tick
            prev_market_trades = market_trades_tick

        # End of day - remember last latent for continuity
        for p in PRODUCTS:
            last_latent[p] = latent_by_product[p][-1]

    # End of session
    total_pnl = sum(
        ledgers[p].cash + ledgers[p].position * final_latent[p] for p in PRODUCTS
    )
    per_product_pnl = {
        p: ledgers[p].cash + ledgers[p].position * final_latent[p] for p in PRODUCTS
    }
    return SessionResult(
        session_id=session_id,
        days=list(days),
        total_pnl=total_pnl,
        per_product_pnl=per_product_pnl,
        per_product_final_position={p: ledgers[p].position for p in PRODUCTS},
        per_product_cash={p: ledgers[p].cash for p in PRODUCTS},
        total_slope_per_step=total_fit.slope_per_step(),
        total_r2=total_fit.r_squared(),
        per_product_slope_per_step={p: per_fit[p].slope_per_step() for p in PRODUCTS},
        per_product_r2={p: per_fit[p].r_squared() for p in PRODUCTS},
        traces=traces,
    )
