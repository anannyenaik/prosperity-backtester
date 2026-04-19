from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ProductMeta:
    symbol: str
    short_name: str
    tick_size: int
    position_limit: int
    style: str
    default_fair: float
    notes: tuple[str, ...]


PRODUCTS = ("ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT")
CURRENCY = "XIRECS"
TIMESTAMP_STEP = 100
TICKS_PER_DAY = 10_000
DEFAULT_POSITION_LIMIT = 80


PRODUCT_METADATA: Dict[str, ProductMeta] = {
    "ASH_COATED_OSMIUM": ProductMeta(
        symbol="ASH_COATED_OSMIUM",
        short_name="OSMIUM",
        tick_size=1,
        position_limit=80,
        style="stable additive / spread capture",
        default_fair=10_000.0,
        notes=(
            "Observed book is usually wide with low latent fair movement.",
            "Replay diagnostics should focus on fill capture, quote placement and inventory skew.",
        ),
    ),
    "INTARIAN_PEPPER_ROOT": ProductMeta(
        symbol="INTARIAN_PEPPER_ROOT",
        short_name="PEPPER",
        tick_size=1,
        position_limit=80,
        style="directional drift engine",
        default_fair=12_000.0,
        notes=(
            "Research value is dominated by directional entry quality, inventory usage and exit assumptions.",
            "Simulator perturbations should emphasise drift sensitivity and adverse selection around near-cap inventory.",
        ),
    ),
}
