from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping


@dataclass(frozen=True)
class ProductMeta:
    symbol: str
    short_name: str
    tick_size: int
    position_limit: int
    style: str
    default_fair: float | None
    notes: tuple[str, ...] = ()
    asset_class: str = "delta1"
    underlying: str | None = None
    strike: int | None = None
    option_type: str | None = None
    include_in_surface_fit: bool | None = None
    diagnostics_group: str | None = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "symbol": self.symbol,
            "short_name": self.short_name,
            "tick_size": self.tick_size,
            "position_limit": self.position_limit,
            "style": self.style,
            "default_fair": self.default_fair,
            "notes": list(self.notes),
            "asset_class": self.asset_class,
            "underlying": self.underlying,
            "strike": self.strike,
            "option_type": self.option_type,
            "include_in_surface_fit": self.include_in_surface_fit,
            "diagnostics_group": self.diagnostics_group,
        }


@dataclass(frozen=True)
class RoundSpec:
    round_number: int
    name: str
    products: tuple[str, ...]
    product_metadata: Mapping[str, ProductMeta]
    default_data_dir: str
    default_days: tuple[int, ...]
    timestamp_step: int
    ticks_per_day: int
    currency: str
    has_round2_access: bool = False
    has_manual_challenge: bool = False
    tte_days_by_historical_day: Mapping[int, int] = field(default_factory=dict)
    final_tte_days: int | None = None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, object]:
        return {
            "round_number": self.round_number,
            "name": self.name,
            "products": list(self.products),
            "product_metadata": {
                symbol: meta.to_dict()
                for symbol, meta in self.product_metadata.items()
            },
            "default_data_dir": self.default_data_dir,
            "default_days": list(self.default_days),
            "timestamp_step": self.timestamp_step,
            "ticks_per_day": self.ticks_per_day,
            "currency": self.currency,
            "has_round2_access": self.has_round2_access,
            "has_manual_challenge": self.has_manual_challenge,
            "tte_days_by_historical_day": {
                int(day): int(days)
                for day, days in self.tte_days_by_historical_day.items()
            },
            "final_tte_days": self.final_tte_days,
            "notes": list(self.notes),
        }


_TIMESTAMP_STEP = 100
_TICKS_PER_DAY = 10_000
_CURRENCY = "XIRECS"


def _voucher_meta(
    strike: int,
    *,
    include_in_surface_fit: bool,
) -> ProductMeta:
    symbol = f"VEV_{strike}"
    stability_note = (
        "Primary surface-fit strike."
        if include_in_surface_fit
        else "Diagnostics only unless a workflow explicitly opts in."
    )
    return ProductMeta(
        symbol=symbol,
        short_name=symbol.replace("VEV_", "V"),
        tick_size=1,
        position_limit=300,
        style="Round 3 call voucher on VELVETFRUIT_EXTRACT",
        default_fair=None,
        notes=(
            "Historical replay should trade the observed voucher book and mark to observed mid.",
            stability_note,
        ),
        asset_class="option",
        underlying="VELVETFRUIT_EXTRACT",
        strike=strike,
        option_type="call",
        include_in_surface_fit=include_in_surface_fit,
        diagnostics_group="voucher",
    )


_ROUND12_PRODUCT_METADATA: Dict[str, ProductMeta] = {
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
        asset_class="delta1",
        diagnostics_group="delta1",
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
        asset_class="delta1",
        diagnostics_group="delta1",
    ),
}

_ROUND3_PRODUCT_METADATA: Dict[str, ProductMeta] = {
    "HYDROGEL_PACK": ProductMeta(
        symbol="HYDROGEL_PACK",
        short_name="HYDROGEL",
        tick_size=1,
        position_limit=200,
        style="independent delta-1 product with wider spreads",
        default_fair=9_960.0,
        notes=(
            "Historical evidence suggests HYDROGEL_PACK is largely independent of VELVETFRUIT_EXTRACT.",
            "Wide-spread liquidity should be stress-tested separately from the voucher chain.",
        ),
        asset_class="delta1",
        diagnostics_group="delta1",
    ),
    "VELVETFRUIT_EXTRACT": ProductMeta(
        symbol="VELVETFRUIT_EXTRACT",
        short_name="VELVET",
        tick_size=1,
        position_limit=200,
        style="Round 3 underlying for the voucher chain",
        default_fair=5_250.0,
        notes=(
            "Underlying for all Round 3 VEV_* vouchers.",
            "Synthetic shocks should propagate through the voucher chain coherently.",
        ),
        asset_class="delta1",
        diagnostics_group="underlying",
    ),
    "VEV_4000": _voucher_meta(4000, include_in_surface_fit=False),
    "VEV_4500": _voucher_meta(4500, include_in_surface_fit=False),
    "VEV_5000": _voucher_meta(5000, include_in_surface_fit=True),
    "VEV_5100": _voucher_meta(5100, include_in_surface_fit=True),
    "VEV_5200": _voucher_meta(5200, include_in_surface_fit=True),
    "VEV_5300": _voucher_meta(5300, include_in_surface_fit=True),
    "VEV_5400": _voucher_meta(5400, include_in_surface_fit=True),
    "VEV_5500": _voucher_meta(5500, include_in_surface_fit=True),
    "VEV_6000": _voucher_meta(6000, include_in_surface_fit=False),
    "VEV_6500": _voucher_meta(6500, include_in_surface_fit=False),
}


ROUND_SPECS: Dict[int, RoundSpec] = {
    1: RoundSpec(
        round_number=1,
        name="Round 1 - Trading groundwork",
        products=tuple(_ROUND12_PRODUCT_METADATA),
        product_metadata=_ROUND12_PRODUCT_METADATA,
        default_data_dir="data/round1",
        default_days=(-2, -1, 0),
        timestamp_step=_TIMESTAMP_STEP,
        ticks_per_day=_TICKS_PER_DAY,
        currency=_CURRENCY,
        notes=(
            "Round 1 and Round 2 share the two-product Osmium and Pepper product set.",
        ),
    ),
    2: RoundSpec(
        round_number=2,
        name="Round 2 - Growing Your Outpost",
        products=tuple(_ROUND12_PRODUCT_METADATA),
        product_metadata=_ROUND12_PRODUCT_METADATA,
        default_data_dir="data/round2",
        default_days=(-1, 0, 1),
        timestamp_step=_TIMESTAMP_STEP,
        ticks_per_day=_TICKS_PER_DAY,
        currency=_CURRENCY,
        has_round2_access=True,
        notes=(
            "Round 2 access and MAF logic is intentionally isolated from other rounds.",
        ),
    ),
    3: RoundSpec(
        round_number=3,
        name="Round 3 - Gloves Off",
        products=tuple(_ROUND3_PRODUCT_METADATA),
        product_metadata=_ROUND3_PRODUCT_METADATA,
        default_data_dir="data/round3",
        default_days=(0, 1, 2),
        timestamp_step=_TIMESTAMP_STEP,
        ticks_per_day=_TICKS_PER_DAY,
        currency=_CURRENCY,
        has_manual_challenge=True,
        tte_days_by_historical_day={0: 8, 1: 7, 2: 6},
        final_tte_days=5,
        notes=(
            "Voucher replay should use observed books and observed mids, not forced exercise.",
            "Option theory is diagnostic and synthetic only unless official rules say otherwise.",
        ),
    ),
}


def get_round_spec(round_number: int) -> RoundSpec:
    try:
        return ROUND_SPECS[int(round_number)]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported round {round_number}. Available rounds: {', '.join(str(key) for key in sorted(ROUND_SPECS))}"
        ) from exc


def products_for_round(round_number: int) -> tuple[str, ...]:
    return get_round_spec(round_number).products


def metadata_for_round(round_number: int) -> Mapping[str, ProductMeta]:
    return get_round_spec(round_number).product_metadata


def product_meta(product: str, round_number: int | None = None) -> ProductMeta:
    spec = get_round_spec(1 if round_number is None else round_number)
    try:
        return spec.product_metadata[product]
    except KeyError as exc:
        raise KeyError(f"Unknown product {product!r} for round {spec.round_number}") from exc


def position_limit_for(product: str, round_number: int | None = None) -> int:
    return int(product_meta(product, round_number).position_limit)


# Legacy aliases for older code paths that still default to the Round 1/2 product set.
PRODUCTS = products_for_round(1)
PRODUCT_METADATA = metadata_for_round(1)
CURRENCY = get_round_spec(1).currency
TIMESTAMP_STEP = get_round_spec(1).timestamp_step
TICKS_PER_DAY = get_round_spec(1).ticks_per_day
DEFAULT_POSITION_LIMIT = max(meta.position_limit for meta in PRODUCT_METADATA.values())
