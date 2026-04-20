from __future__ import annotations

import csv
import json
import statistics
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .metadata import PRODUCTS


LevelList = Sequence[Tuple[int, int]]


def _bounded(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    data = sorted(float(value) for value in values)
    if len(data) == 1:
        return data[0]
    idx = q * (len(data) - 1)
    lo = int(idx)
    hi = min(len(data) - 1, lo + 1)
    weight = idx - lo
    return data[lo] * (1.0 - weight) + data[hi] * weight


@dataclass(frozen=True)
class ProductFillConfig:
    passive_fill_rate: float
    same_price_queue_share: float
    queue_pressure: float
    missed_fill_probability: float
    passive_adverse_selection_ticks: float = 0.0
    aggressive_slippage_ticks: float = 0.0
    aggressive_adverse_selection_ticks: float = 0.0
    size_slippage_threshold: int = 8
    size_slippage_rate: float = 0.0
    size_slippage_power: float = 1.0
    max_size_slippage_ticks: float = 4.0
    wide_spread_threshold: int | None = None
    thin_depth_threshold: int = 8
    regime_overrides: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def with_regime(self, regime: str) -> "ProductFillConfig":
        override = self.regime_overrides.get(regime)
        if not override:
            return self
        valid = set(ProductFillConfig.__dataclass_fields__) - {"regime_overrides"}
        cleaned = {key: value for key, value in override.items() if key in valid}
        return replace(self, **cleaned)

    def size_slippage_ticks(self, quantity: int) -> float:
        excess = max(0, int(quantity) - int(self.size_slippage_threshold))
        if excess <= 0 or self.size_slippage_rate <= 0.0:
            return 0.0
        ticks = self.size_slippage_rate * (excess ** max(0.1, float(self.size_slippage_power)))
        return min(float(self.max_size_slippage_ticks), ticks)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FillModel:
    name: str
    passive_fill_rate: float
    same_price_queue_share: float
    queue_pressure: float
    missed_fill_probability: float
    adverse_selection_ticks: float
    aggressive_slippage_ticks: float = 0.0
    aggressive_adverse_selection_ticks: float = 0.0
    slippage_multiplier: float = 1.0
    fill_rate_multiplier: float = 1.0
    missed_fill_additive: float = 0.0
    product_overrides: Dict[str, ProductFillConfig] = field(default_factory=dict)
    metadata: Dict[str, object] = field(default_factory=dict)

    def base_product_config(self) -> ProductFillConfig:
        return ProductFillConfig(
            passive_fill_rate=self.passive_fill_rate,
            same_price_queue_share=self.same_price_queue_share,
            queue_pressure=self.queue_pressure,
            missed_fill_probability=self.missed_fill_probability,
            passive_adverse_selection_ticks=self.adverse_selection_ticks,
            aggressive_slippage_ticks=self.aggressive_slippage_ticks,
            aggressive_adverse_selection_ticks=self.aggressive_adverse_selection_ticks,
        )

    def config_for(
        self,
        product: str,
        bids: LevelList | None = None,
        asks: LevelList | None = None,
    ) -> tuple[ProductFillConfig, str]:
        config = self.product_overrides.get(product, self.base_product_config())
        regime = liquidity_regime_from_levels(product, bids or [], asks or [], config)
        return config.with_regime(regime), regime

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "passive_fill_rate": self.passive_fill_rate,
            "same_price_queue_share": self.same_price_queue_share,
            "queue_pressure": self.queue_pressure,
            "missed_fill_probability": self.missed_fill_probability,
            "adverse_selection_ticks": self.adverse_selection_ticks,
            "aggressive_slippage_ticks": self.aggressive_slippage_ticks,
            "aggressive_adverse_selection_ticks": self.aggressive_adverse_selection_ticks,
            "slippage_multiplier": self.slippage_multiplier,
            "fill_rate_multiplier": self.fill_rate_multiplier,
            "missed_fill_additive": self.missed_fill_additive,
            "product_overrides": {
                product: config.to_dict()
                for product, config in self.product_overrides.items()
            },
            "metadata": dict(self.metadata),
        }


def liquidity_regime_from_levels(
    product: str,
    bids: LevelList,
    asks: LevelList,
    config: ProductFillConfig | None = None,
) -> str:
    if not bids or not asks:
        return "one_sided"
    config = config or ProductFillConfig(0.65, 0.60, 0.85, 0.03)
    top_depth = int(bids[0][1]) + int(asks[0][1])
    if top_depth <= int(config.thin_depth_threshold):
        return "thin_depth"
    spread = int(asks[0][0]) - int(bids[0][0])
    threshold = config.wide_spread_threshold
    if threshold is None:
        threshold = 20 if product == "ASH_COATED_OSMIUM" else 18
    if spread >= int(threshold):
        return "wide_spread"
    return "normal"


def _product_config(**kwargs: object) -> ProductFillConfig:
    return ProductFillConfig(**kwargs)


_EMPIRICAL_BASE_OVERRIDES: Dict[str, ProductFillConfig] = {
    "ASH_COATED_OSMIUM": _product_config(
        passive_fill_rate=0.62,
        same_price_queue_share=0.65,
        queue_pressure=0.90,
        missed_fill_probability=0.04,
        passive_adverse_selection_ticks=0.0,
        aggressive_slippage_ticks=0.0,
        aggressive_adverse_selection_ticks=0.0,
        size_slippage_threshold=10,
        size_slippage_rate=0.08,
        size_slippage_power=1.0,
        max_size_slippage_ticks=3.0,
        wide_spread_threshold=20,
        thin_depth_threshold=8,
        regime_overrides={
            "wide_spread": {"passive_fill_rate": 0.55, "queue_pressure": 1.05},
            "thin_depth": {"passive_fill_rate": 0.48, "missed_fill_probability": 0.08},
        },
    ),
    "INTARIAN_PEPPER_ROOT": _product_config(
        passive_fill_rate=0.55,
        same_price_queue_share=0.70,
        queue_pressure=1.05,
        missed_fill_probability=0.06,
        passive_adverse_selection_ticks=0.0,
        aggressive_slippage_ticks=0.0,
        aggressive_adverse_selection_ticks=0.5,
        size_slippage_threshold=8,
        size_slippage_rate=0.12,
        size_slippage_power=1.0,
        max_size_slippage_ticks=4.0,
        wide_spread_threshold=18,
        thin_depth_threshold=8,
        regime_overrides={
            "wide_spread": {"passive_fill_rate": 0.50, "queue_pressure": 1.15},
            "thin_depth": {"passive_fill_rate": 0.42, "missed_fill_probability": 0.10},
        },
    ),
}

_EMPIRICAL_OPTIMISTIC_OVERRIDES: Dict[str, ProductFillConfig] = {
    product: replace(
        config,
        passive_fill_rate=_bounded(config.passive_fill_rate + 0.10, 0.0, 1.0),
        missed_fill_probability=max(0.0, config.missed_fill_probability - 0.03),
        queue_pressure=max(0.0, config.queue_pressure - 0.20),
    )
    for product, config in _EMPIRICAL_BASE_OVERRIDES.items()
}

_EMPIRICAL_CONSERVATIVE_OVERRIDES: Dict[str, ProductFillConfig] = {
    product: replace(
        config,
        passive_fill_rate=_bounded(config.passive_fill_rate - 0.12, 0.0, 1.0),
        missed_fill_probability=min(1.0, config.missed_fill_probability + 0.06),
        queue_pressure=config.queue_pressure + 0.25,
        passive_adverse_selection_ticks=1.0,
        aggressive_slippage_ticks=1.0,
        aggressive_adverse_selection_ticks=1.0,
    )
    for product, config in _EMPIRICAL_BASE_OVERRIDES.items()
}

_SLIPPAGE_STRESS_OVERRIDES: Dict[str, ProductFillConfig] = {
    product: replace(
        config,
        size_slippage_rate=config.size_slippage_rate * 1.8,
        max_size_slippage_ticks=config.max_size_slippage_ticks + 2.0,
    )
    for product, config in _EMPIRICAL_CONSERVATIVE_OVERRIDES.items()
}

_LOW_FILL_QUALITY_OVERRIDES: Dict[str, ProductFillConfig] = {
    product: replace(
        config,
        passive_fill_rate=max(0.20, config.passive_fill_rate - 0.10),
        missed_fill_probability=min(1.0, config.missed_fill_probability + 0.05),
    )
    for product, config in _EMPIRICAL_CONSERVATIVE_OVERRIDES.items()
}


FILL_MODELS: Dict[str, FillModel] = {
    "optimistic": FillModel(
        name="optimistic",
        passive_fill_rate=1.00,
        same_price_queue_share=0.00,
        queue_pressure=0.00,
        missed_fill_probability=0.00,
        adverse_selection_ticks=0,
        metadata={"class": "assumption", "quality": "optimistic"},
    ),
    "base": FillModel(
        name="base",
        passive_fill_rate=0.65,
        same_price_queue_share=0.60,
        queue_pressure=0.85,
        missed_fill_probability=0.03,
        adverse_selection_ticks=0,
        metadata={"class": "assumption", "quality": "legacy_base"},
    ),
    "conservative": FillModel(
        name="conservative",
        passive_fill_rate=0.35,
        same_price_queue_share=1.00,
        queue_pressure=1.25,
        missed_fill_probability=0.10,
        adverse_selection_ticks=1,
        aggressive_slippage_ticks=1,
        aggressive_adverse_selection_ticks=1,
        slippage_multiplier=1.0,
        metadata={"class": "assumption", "quality": "conservative"},
    ),
    "empirical_baseline": FillModel(
        name="empirical_baseline",
        passive_fill_rate=0.60,
        same_price_queue_share=0.65,
        queue_pressure=0.95,
        missed_fill_probability=0.05,
        adverse_selection_ticks=0,
        aggressive_slippage_ticks=0,
        aggressive_adverse_selection_ticks=0,
        product_overrides=_EMPIRICAL_BASE_OVERRIDES,
        metadata={
            "class": "empirical_assumption",
            "source": "live-export review notes plus R1 book/trade calibration",
            "caveat": "Passive opportunity denominator is not visible, so rates remain calibrated assumptions.",
        },
    ),
    "empirical_optimistic": FillModel(
        name="empirical_optimistic",
        passive_fill_rate=0.68,
        same_price_queue_share=0.45,
        queue_pressure=0.75,
        missed_fill_probability=0.02,
        adverse_selection_ticks=0,
        product_overrides=_EMPIRICAL_OPTIMISTIC_OVERRIDES,
        metadata={"class": "scenario_override", "quality": "optimistic_empirical_band"},
    ),
    "empirical_conservative": FillModel(
        name="empirical_conservative",
        passive_fill_rate=0.48,
        same_price_queue_share=0.85,
        queue_pressure=1.20,
        missed_fill_probability=0.10,
        adverse_selection_ticks=1,
        aggressive_slippage_ticks=1,
        aggressive_adverse_selection_ticks=1,
        product_overrides=_EMPIRICAL_CONSERVATIVE_OVERRIDES,
        metadata={"class": "scenario_override", "quality": "conservative_empirical_band"},
    ),
    "slippage_stress": FillModel(
        name="slippage_stress",
        passive_fill_rate=0.50,
        same_price_queue_share=0.85,
        queue_pressure=1.15,
        missed_fill_probability=0.08,
        adverse_selection_ticks=1,
        aggressive_slippage_ticks=1,
        aggressive_adverse_selection_ticks=1,
        slippage_multiplier=1.75,
        product_overrides=_SLIPPAGE_STRESS_OVERRIDES,
        metadata={"class": "stress", "quality": "harsher_slippage"},
    ),
    "low_fill_quality": FillModel(
        name="low_fill_quality",
        passive_fill_rate=0.38,
        same_price_queue_share=1.00,
        queue_pressure=1.35,
        missed_fill_probability=0.14,
        adverse_selection_ticks=1,
        aggressive_slippage_ticks=1,
        aggressive_adverse_selection_ticks=1,
        slippage_multiplier=1.25,
        product_overrides=_LOW_FILL_QUALITY_OVERRIDES,
        metadata={"class": "stress", "quality": "lower_fill_quality"},
    ),
}


def _coerce_product_config(data: Mapping[str, object]) -> ProductFillConfig:
    valid = set(ProductFillConfig.__dataclass_fields__)
    cleaned = {key: value for key, value in dict(data).items() if key in valid}
    return ProductFillConfig(**cleaned)


def _model_from_dict(name: str, data: Mapping[str, object]) -> FillModel:
    base_name = str(data.get("base", "base"))
    base = FILL_MODELS.get(base_name)
    if base is None:
        raise KeyError(f"Unknown base fill model in config: {base_name}")
    fields = {
        "name": name,
        "passive_fill_rate": base.passive_fill_rate,
        "same_price_queue_share": base.same_price_queue_share,
        "queue_pressure": base.queue_pressure,
        "missed_fill_probability": base.missed_fill_probability,
        "adverse_selection_ticks": base.adverse_selection_ticks,
        "aggressive_slippage_ticks": base.aggressive_slippage_ticks,
        "aggressive_adverse_selection_ticks": base.aggressive_adverse_selection_ticks,
        "slippage_multiplier": base.slippage_multiplier,
        "fill_rate_multiplier": base.fill_rate_multiplier,
        "missed_fill_additive": base.missed_fill_additive,
        "product_overrides": dict(base.product_overrides),
        "metadata": dict(base.metadata),
    }
    scalar_fields = set(FillModel.__dataclass_fields__) - {"name", "product_overrides", "metadata"}
    for key in scalar_fields:
        if key in data:
            fields[key] = data[key]
    product_data = data.get("products") or data.get("product_overrides") or {}
    if isinstance(product_data, Mapping):
        overrides = dict(fields["product_overrides"])
        for product, raw_config in product_data.items():
            if isinstance(raw_config, Mapping):
                starting = overrides.get(str(product), base.base_product_config())
                merged = {**starting.to_dict(), **dict(raw_config)}
                overrides[str(product)] = _coerce_product_config(merged)
        fields["product_overrides"] = overrides
    metadata = data.get("metadata")
    if isinstance(metadata, Mapping):
        fields["metadata"] = {**fields["metadata"], **dict(metadata)}
    return FillModel(**fields)


def load_fill_models_from_config(path: Path) -> Dict[str, FillModel]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_profiles = payload.get("profiles", payload)
    if not isinstance(raw_profiles, Mapping):
        raise ValueError(f"Fill config must contain a profiles object: {path}")
    profiles: Dict[str, FillModel] = {}
    for name, raw in raw_profiles.items():
        if isinstance(raw, Mapping):
            profiles[str(name)] = _model_from_dict(str(name), raw)
    return profiles


def resolve_fill_model(name: Optional[str] = None, config_path: Path | str | None = None) -> FillModel:
    models = dict(FILL_MODELS)
    if config_path is not None:
        models.update(load_fill_models_from_config(Path(config_path)))
    if not name:
        return models["empirical_baseline"] if "empirical_baseline" in models else models["base"]
    if name not in models:
        raise KeyError(f"Unknown fill model: {name}. Available: {', '.join(sorted(models))}")
    return models[name]


def _write_rows_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    headers: List[str] = []
    for row in rows:
        for key in row:
            if key not in headers:
                headers.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _submission_side(trade) -> str | None:
    if trade.buyer == "SUBMISSION":
        return "buy"
    if trade.seller == "SUBMISSION":
        return "sell"
    return None


def _classify_trade_role(side: str, price: int, bids: LevelList, asks: LevelList) -> str:
    if side == "buy" and asks and price >= int(asks[0][0]):
        return "aggressive"
    if side == "sell" and bids and price <= int(bids[0][0]):
        return "aggressive"
    return "passive"


def derive_empirical_fill_profile(
    live_export_paths: Iterable[Path],
    output_dir: Path,
    profile_name: str = "empirical_live",
) -> Dict[str, object]:
    from .live_export import load_live_export

    output_dir.mkdir(parents=True, exist_ok=True)
    fill_rows: List[Dict[str, object]] = []
    export_paths = [Path(path).resolve() for path in live_export_paths]
    for export_path in export_paths:
        export = load_live_export(export_path)
        own_trades = getattr(export, "own_trade_history", None) or [
            trade for trade in export.trade_history if _submission_side(trade) is not None
        ]
        for trade in own_trades:
            side = _submission_side(trade)
            if side is None:
                continue
            snapshot = export.day_dataset.books_by_timestamp.get(int(trade.timestamp), {}).get(trade.symbol)
            bids = snapshot.bids if snapshot else []
            asks = snapshot.asks if snapshot else []
            mid = snapshot.mid if snapshot else None
            config = FILL_MODELS["empirical_baseline"].config_for(trade.symbol, bids, asks)[0]
            regime = liquidity_regime_from_levels(trade.symbol, bids, asks, config)
            role = _classify_trade_role(side, int(trade.price), bids, asks)
            best_bid = bids[0][0] if bids else None
            best_ask = asks[0][0] if asks else None
            if side == "buy":
                signed_edge_to_mid = None if mid is None else float(mid) - float(trade.price)
                distance_to_touch = None if best_ask is None else int(best_ask) - int(trade.price)
            else:
                signed_edge_to_mid = None if mid is None else float(trade.price) - float(mid)
                distance_to_touch = None if best_bid is None else int(trade.price) - int(best_bid)
            spread = None if best_bid is None or best_ask is None else int(best_ask) - int(best_bid)
            fill_rows.append({
                "export_path": str(export_path),
                "submission_id": export.submission_id,
                "timestamp": int(trade.timestamp),
                "product": trade.symbol,
                "side": side,
                "price": int(trade.price),
                "quantity": int(trade.quantity),
                "role": role,
                "regime": regime,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "mid": mid,
                "spread": spread,
                "signed_edge_to_mid": signed_edge_to_mid,
                "distance_to_touch": distance_to_touch,
            })

    summary_rows: List[Dict[str, object]] = []
    product_configs: Dict[str, ProductFillConfig] = {}
    for product in PRODUCTS:
        rows = [row for row in fill_rows if row["product"] == product]
        quantities = [float(row["quantity"]) for row in rows]
        passive_rows = [row for row in rows if row["role"] == "passive"]
        aggressive_rows = [row for row in rows if row["role"] == "aggressive"]
        spreads = [float(row["spread"]) for row in rows if row.get("spread") is not None]
        signed_edges = [float(row["signed_edge_to_mid"]) for row in rows if row.get("signed_edge_to_mid") is not None]
        passive_share = len(passive_rows) / len(rows) if rows else 0.5
        q75 = _quantile(quantities, 0.75) or 8.0
        passive_fill_rate = _bounded(0.40 + passive_share * 0.28, 0.25, 0.78)
        missed_probability = _bounded(0.11 - passive_share * 0.07, 0.02, 0.14)
        queue_pressure = _bounded(1.15 - passive_share * 0.35, 0.70, 1.35)
        base_config = FILL_MODELS["empirical_baseline"].product_overrides[product]
        product_configs[product] = replace(
            base_config,
            passive_fill_rate=passive_fill_rate,
            queue_pressure=queue_pressure,
            missed_fill_probability=missed_probability,
            size_slippage_threshold=max(3, int(round(q75))),
        )
        role_counts = Counter(str(row["role"]) for row in rows)
        regime_counts = Counter(str(row["regime"]) for row in rows)
        side_counts = Counter(str(row["side"]) for row in rows)
        summary_rows.append({
            "product": product,
            "own_fill_count": len(rows),
            "own_fill_qty": int(sum(quantities)),
            "passive_count": role_counts.get("passive", 0),
            "aggressive_count": role_counts.get("aggressive", 0),
            "passive_share": passive_share,
            "buy_count": side_counts.get("buy", 0),
            "sell_count": side_counts.get("sell", 0),
            "normal_regime_count": regime_counts.get("normal", 0),
            "wide_spread_count": regime_counts.get("wide_spread", 0),
            "thin_depth_count": regime_counts.get("thin_depth", 0),
            "mean_quantity": _mean(quantities),
            "p75_quantity": q75,
            "mean_spread": _mean(spreads),
            "mean_signed_edge_to_mid": _mean(signed_edges),
            "derived_passive_fill_rate": product_configs[product].passive_fill_rate,
            "derived_queue_pressure": product_configs[product].queue_pressure,
            "derived_missed_fill_probability": product_configs[product].missed_fill_probability,
        })

    profile_model = FillModel(
        name=profile_name,
        passive_fill_rate=0.60,
        same_price_queue_share=0.65,
        queue_pressure=0.95,
        missed_fill_probability=0.05,
        adverse_selection_ticks=0.0,
        product_overrides=product_configs,
        metadata={
            "class": "empirical_live_export",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_exports": [str(path) for path in export_paths],
            "caveat": "Live exports expose realised fills, not rejected passive opportunities.",
        },
    )
    artefact = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "profile_name": profile_name,
        "source_exports": [str(path) for path in export_paths],
        "row_count": len(fill_rows),
        "summary": summary_rows,
        "profiles": {
            profile_name: {
                "base": "empirical_baseline",
                "metadata": profile_model.metadata,
                "products": {
                    product: config.to_dict()
                    for product, config in profile_model.product_overrides.items()
                },
            }
        },
        "assumptions": {
            "empirical": [
                "Own fills are filtered to tradeHistory rows where SUBMISSION is buyer or seller.",
                "Aggressive/passive labels are inferred from the visible touch at the fill timestamp.",
                "Spreads, offsets, size distribution and regimes are measured directly from the export.",
            ],
            "unknown": [
                "Rejected passive orders are not present, so passive fill probability still needs live-vs-sim calibration.",
                "Website queue priority and hidden matching effects are not observable.",
            ],
        },
    }
    (output_dir / "empirical_fill_profile.json").write_text(json.dumps(artefact, indent=2), encoding="utf-8")
    _write_rows_csv(output_dir / "empirical_fill_rows.csv", fill_rows)
    _write_rows_csv(output_dir / "empirical_fill_summary.csv", summary_rows)
    return artefact
