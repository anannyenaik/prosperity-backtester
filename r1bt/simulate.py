"""
Book and trade generation from calibrated empirical distributions.

This replaces the Rust simulator's make_book/sample_trade logic with a pure-Python
version that draws from the actual histograms measured on round 1 data. We do NOT
try to reverse-engineer exact quote rules (which requires ground-truth FV). Instead,
each tick samples:

  1. A latent fair path: a random walk with the product's measured drift and residual std
  2. A book around that latent fair using the empirical spread and volume distributions
  3. Trade count and side from the empirical trade-activity probabilities

Because the underlying statistics are moment-matched to the actual round 1 data,
aggregate sim behavior (PnL distributions, book shapes, trade rates) should match
the historical data within sampling noise.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .datamodel import OrderDepth


PRODUCTS = ("ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT")
TICKS_PER_DAY = 10_000
TIMESTAMP_STEP = 100


@dataclass
class BotBook:
    """Plain-Python order book used during simulation.

    bids: list of (price, volume) pairs, volume POSITIVE, sorted descending by price
    asks: list of (price, volume) pairs, volume POSITIVE, sorted ascending by price
    """
    bids: List[Tuple[int, int]]
    asks: List[Tuple[int, int]]


# ─────────────────────── calibration loading ─────────────────────── #

_CALIB_CACHE: Optional[dict] = None


def load_calibration(path: Optional[Path] = None) -> dict:
    global _CALIB_CACHE
    if _CALIB_CACHE is not None and path is None:
        return _CALIB_CACHE
    if path is None:
        path = Path(__file__).parent / "calibration.json"
    with open(path, "r", encoding="utf-8") as f:
        calib = json.load(f)

    # Normalize keys: JSON stringified ints back to ints in histogram dicts
    for product in list(calib.keys()):
        pc = calib[product]
        for key in ("outer_spread_counts", "inner_spread_counts",
                    "outer_bid_offset_counts", "outer_ask_offset_counts",
                    "inner_bid_offset_counts", "inner_ask_offset_counts",
                    "outer_bid_vol_counts", "inner_bid_vol_counts",
                    "trade_qty_counts"):
            if key in pc:
                pc[key] = {float(k) if ("offset" in key) else int(k): int(v)
                           for k, v in pc[key].items()}
    _CALIB_CACHE = calib
    return calib


# ─────────────────────── weighted sampling ─────────────────────── #

class _Sampler:
    """Categorical sampler from a {value: count} histogram. Precomputes CDF."""
    def __init__(self, counts: Dict):
        items = sorted(counts.items())
        self.values = [v for v, _ in items]
        self.weights = [c for _, c in items]
        self._cdf = []
        total = 0
        for w in self.weights:
            total += w
            self._cdf.append(total)
        self._total = total

    def draw(self, rng: random.Random):
        r = rng.random() * self._total
        lo, hi = 0, len(self._cdf) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if self._cdf[mid] < r:
                lo = mid + 1
            else:
                hi = mid
        return self.values[lo]


def build_samplers(calib: dict) -> dict:
    """Precompute per-product samplers from the calibration histograms."""
    out = {}
    for product in PRODUCTS:
        pc = calib[product]
        out[product] = {
            "outer_spread": _Sampler(pc["outer_spread_counts"]),
            "inner_spread": _Sampler(pc["inner_spread_counts"]),
            "outer_bid_off": _Sampler(pc["outer_bid_offset_counts"]),
            "outer_ask_off": _Sampler(pc["outer_ask_offset_counts"]),
            "inner_bid_off": _Sampler(pc["inner_bid_offset_counts"]),
            "inner_ask_off": _Sampler(pc["inner_ask_offset_counts"]),
            "outer_bid_vol": _Sampler(pc["outer_bid_vol_counts"]),
            "inner_bid_vol": _Sampler(pc["inner_bid_vol_counts"]),
            "trade_qty": _Sampler(pc["trade_qty_counts"]),
        }
    return out


# ─────────────────────── latent-fair paths ─────────────────────── #

def simulate_latent_fair(product: str, calib: dict, day_index: int,
                         rng: random.Random,
                         continue_from: Optional[float] = None) -> List[float]:
    """Generate a latent fair value path for one day.

    If `continue_from` is provided, the path starts there (preserves continuity
    across days within one session). Otherwise we sample a start from the real
    calibration data - useful when simulating a single standalone day.

    Calibration notes:
      - OSMIUM: observable mid std ≈ 4.7 but autocorr(1) = -0.49 → classic
        bid-ask bounce. The latent fair barely moves (we use kappa=0.15, sigma=0.4,
        stationary std < 1).
      - PEPPER: linear drift ≈ +0.108/tick, residual std ≈ 1.17.

    Returns a list of TICKS_PER_DAY floats.
    """
    pc = calib[product]
    if continue_from is not None:
        start = float(continue_from)
    else:
        starts = pc["start_candidates"]
        start = starts[day_index % len(starts)] if starts else 10000.0

    path = [0.0] * TICKS_PER_DAY
    path[0] = start

    if product == "ASH_COATED_OSMIUM":
        kappa = 0.15
        sigma = float(pc.get("simulation_noise_std", 0.4))
        target = 10000.0
        for i in range(1, TICKS_PER_DAY):
            pull = -kappa * (path[i - 1] - target)
            path[i] = path[i - 1] + pull + sigma * rng.gauss(0.0, 1.0)
    else:  # INTARIAN_PEPPER_ROOT
        drift = pc["drift_per_tick"]
        sigma = float(pc.get("simulation_noise_std", max(0.8, pc["resid_std"] * 0.5)))
        for i in range(1, TICKS_PER_DAY):
            path[i] = path[i - 1] + drift + sigma * rng.gauss(0.0, 1.0)
    return path


# ─────────────────────── book generation ─────────────────────── #

def _nearest_half(x: float) -> float:
    return round(x * 2.0) / 2.0


def make_book(product: str, latent_fair: float, samplers: dict,
              calib: dict, rng: random.Random) -> BotBook:
    """Produce one tick's order book for a product, consistent with empirical stats.

    Strategy: sample spreads from histograms, center them around round(latent_fair),
    then optionally add a Bot 3 inside quote.
    """
    pc = calib[product]
    s = samplers[product]

    # Some fraction of ticks have empty books entirely or one-sided
    # But these are rare (~4%) and strategies handle missing books, so we always
    # generate both sides in sim. (One-sided behavior can be enabled if needed.)
    center = round(latent_fair)

    outer_spread = s["outer_spread"].draw(rng)
    inner_spread = s["inner_spread"].draw(rng)

    # Outer wall: place symmetric around center, widen on mispaced ties
    outer_half = outer_spread // 2
    outer_bid = center - outer_half
    outer_ask = outer_bid + outer_spread

    # Inner wall: must be strictly inside the outer
    inner_half = inner_spread // 2
    inner_bid = center - inner_half
    inner_ask = inner_bid + inner_spread
    # Safety: ensure inner is tighter than outer
    if inner_bid <= outer_bid:
        inner_bid = outer_bid + 1
    if inner_ask >= outer_ask:
        inner_ask = outer_ask - 1
    if inner_ask <= inner_bid:
        # Collapse both into one level
        inner_bid = outer_bid + 1
        inner_ask = outer_ask - 1

    outer_bid_vol = s["outer_bid_vol"].draw(rng)
    outer_ask_vol = s["outer_bid_vol"].draw(rng)  # symmetric in empirical data
    inner_bid_vol = s["inner_bid_vol"].draw(rng)
    inner_ask_vol = s["inner_bid_vol"].draw(rng)

    bids = [(inner_bid, inner_bid_vol), (outer_bid, outer_bid_vol)]
    asks = [(inner_ask, inner_ask_vol), (outer_ask, outer_ask_vol)]

    # Bot 3 inside quote (rare, single-sided only - matches P4 calibration finding)
    bot3_rate = pc["bot3_bid_rate"] + pc["bot3_ask_rate"]
    if rng.random() < bot3_rate:
        bid_share = pc["bot3_bid_rate"] / bot3_rate if bot3_rate > 0 else 0.5
        if rng.random() < bid_share:
            # Bot 3 bid: must strictly improve on the inner bid AND sit below all asks
            offset = rng.choice([-2, -1, 0, 1])
            price = center + offset
            min_ask = min(a[0] for a in asks)
            if price > inner_bid and price < min_ask:
                vol = rng.randint(3, 10)
                bids.append((price, vol))
        else:
            # Bot 3 ask: must strictly improve on the inner ask AND sit above all bids
            offset = rng.choice([-1, 0, 1, 2])
            price = center + offset
            max_bid = max(b[0] for b in bids)
            if price < inner_ask and price > max_bid:
                vol = rng.randint(3, 10)
                asks.append((price, vol))

    # Sort bids desc, asks asc; dedupe by price (merge volumes if same)
    def _normalize(levels, descending):
        agg = {}
        for p, v in levels:
            agg[p] = agg.get(p, 0) + v
        items = sorted(agg.items(), key=lambda x: -x[0] if descending else x[0])
        return items

    bids = _normalize(bids, descending=True)
    asks = _normalize(asks, descending=False)
    return BotBook(bids=bids, asks=asks)


def book_to_order_depth(book: BotBook) -> OrderDepth:
    """Convert internal book to the Prosperity OrderDepth (sell vols negated)."""
    od = OrderDepth()
    for p, v in book.bids:
        od.buy_orders[int(p)] = int(v)
    for p, v in book.asks:
        od.sell_orders[int(p)] = -int(v)
    return od


# ─────────────────────── trade generation ─────────────────────── #

def sample_trade_counts(product: str, calib: dict, rng: random.Random) -> List[int]:
    """Per-tick Bernoulli with a tiny second-trade bump."""
    pc = calib[product]
    base = pc["trade_active_prob"]
    second = pc["second_trade_prob"]
    counts = [0] * TICKS_PER_DAY
    for i in range(TICKS_PER_DAY):
        if rng.random() < base:
            counts[i] = 1
            if second > 0 and rng.random() < second:
                counts[i] += 1
    return counts


def sample_trade_quantity(product: str, samplers: dict, volume_limit: int,
                          rng: random.Random) -> int:
    """Draw a trade size from the empirical histogram, capped at available volume."""
    if volume_limit <= 0:
        return 0
    # Filter sampler on the fly (we don't precompute; qty distributions are tiny)
    s = samplers[product]["trade_qty"]
    # Rejection: draw repeatedly until we get a feasible size
    # (empirical sizes are all ≤ 10, so this is fast)
    for _ in range(8):
        q = s.draw(rng)
        if q <= volume_limit:
            return int(q)
    # Fallback: clip to volume_limit
    return max(1, min(volume_limit, 5))
