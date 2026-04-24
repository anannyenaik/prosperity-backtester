from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .dataset import BookSnapshot, DayDataset
from .metadata import PRODUCT_METADATA, PRODUCTS, ProductMeta, RoundSpec, get_round_spec
from .round3 import ROUND3_HYDROGEL, ROUND3_UNDERLYING


@dataclass
class FairRow:
    day: int
    timestamp: int
    product: str
    mid: Optional[float]
    microprice: Optional[float]
    reference_fair: Optional[float]
    inferred_fair: Optional[float]
    analysis_fair: Optional[float]
    fair_method: str
    fair_is_exact: bool
    spread: Optional[float]
    fair_minus_mid: Optional[float]
    fair_minus_micro: Optional[float]
    trend_slope_per_tick: Optional[float]

    def to_dict(self) -> Dict[str, object]:
        return {
            "day": self.day,
            "timestamp": self.timestamp,
            "product": self.product,
            "mid": self.mid,
            "microprice": self.microprice,
            "reference_fair": self.reference_fair,
            "inferred_fair": self.inferred_fair,
            "analysis_fair": self.analysis_fair,
            "fair_method": self.fair_method,
            "fair_is_exact": self.fair_is_exact,
            "spread": self.spread,
            "fair_minus_mid": self.fair_minus_mid,
            "fair_minus_micro": self.fair_minus_micro,
            "trend_slope_per_tick": self.trend_slope_per_tick,
        }


class OnlineEwma:
    def __init__(self, alpha: float, initial: Optional[float] = None):
        self.alpha = alpha
        self.value = initial

    def update(self, value: Optional[float]) -> Optional[float]:
        if value is None:
            return self.value
        if self.value is None:
            self.value = float(value)
        else:
            self.value = (1.0 - self.alpha) * float(self.value) + self.alpha * float(value)
        return self.value


def _spread(snapshot: BookSnapshot) -> Optional[float]:
    if snapshot.bids and snapshot.asks:
        return float(snapshot.asks[0][0] - snapshot.bids[0][0])
    return None


def _micro(snapshot: BookSnapshot) -> Optional[float]:
    return snapshot.microprice()


def _linear_fit(points: Sequence[Tuple[int, float]]) -> Tuple[float, float]:
    if not points:
        return 0.0, 0.0
    if len(points) == 1:
        return 0.0, points[0][1]
    xs = [float(ts) for ts, _ in points]
    ys = [float(v) for _, v in points]
    x_mean = statistics.fmean(xs)
    y_mean = statistics.fmean(ys)
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom <= 1e-12:
        return 0.0, y_mean
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denom
    intercept = y_mean - slope * x_mean
    return slope, intercept


def infer_day_fair_rows(
    day_dataset: DayDataset,
    *,
    products: Sequence[str] = PRODUCTS,
    product_metadata: Mapping[str, ProductMeta] = PRODUCT_METADATA,
    round_spec: RoundSpec | None = None,
) -> List[Dict[str, object]]:
    rows: List[FairRow] = []
    source = str(day_dataset.metadata.get("source", ""))
    exact_reference = source == "synthetic"
    round_spec = round_spec or get_round_spec(day_dataset.round_number or 1)

    for product in products:
        meta = product_metadata[product]
        snapshots = [(ts, day_dataset.books_by_timestamp[ts].get(product)) for ts in day_dataset.timestamps]
        valid_mids = [(ts, snap.mid) for ts, snap in snapshots if snap is not None and snap.mid is not None]
        slope, intercept = _linear_fit([(ts, float(mid)) for ts, mid in valid_mids])
        osmium_anchor = OnlineEwma(alpha=0.02, initial=meta.default_fair)
        pepper_intercept = OnlineEwma(alpha=0.01)
        underlying_anchor = OnlineEwma(alpha=0.04, initial=meta.default_fair)

        for ts, snapshot in snapshots:
            if snapshot is None:
                continue
            mid = snapshot.mid
            microprice = _micro(snapshot)
            ref = snapshot.reference_fair
            if round_spec.round_number == 3 and meta.asset_class == "option":
                inferred = mid if mid is not None else microprice if microprice is not None else ref
                fair_method = "exact_latent" if exact_reference and ref is not None else "observed_mid"
                analysis_fair = ref if exact_reference and ref is not None else inferred
                trend = 0.0
            elif round_spec.round_number == 3 and product == ROUND3_HYDROGEL:
                anchor_input = microprice if microprice is not None else mid
                anchor = osmium_anchor.update(anchor_input)
                inferred = anchor if anchor is not None else ref
                fair_method = "exact_latent" if exact_reference and ref is not None else "hydrogel_anchor_microprice"
                analysis_fair = ref if exact_reference and ref is not None else inferred
                trend = 0.0
            elif round_spec.round_number == 3 and product == ROUND3_UNDERLYING:
                observed = None
                if microprice is not None and mid is not None:
                    observed = 0.6 * microprice + 0.4 * mid
                else:
                    observed = microprice if microprice is not None else mid
                inferred = underlying_anchor.update(observed)
                fair_method = "exact_latent" if exact_reference and ref is not None else "underlying_mid_micro_ewma"
                analysis_fair = ref if exact_reference and ref is not None else inferred
                trend = slope
            elif product == "ASH_COATED_OSMIUM":
                anchor_input = mid if mid is not None else microprice
                anchor = osmium_anchor.update(anchor_input)
                inferred = None
                if microprice is not None and anchor is not None:
                    inferred = 0.75 * microprice + 0.25 * anchor
                else:
                    inferred = anchor if anchor is not None else ref
                fair_method = "exact_latent" if exact_reference and ref is not None else "osmium_anchor_microprice"
                analysis_fair = ref if exact_reference and ref is not None else inferred
                trend = 0.0
            else:
                if valid_mids:
                    observed_intercept = None if mid is None else float(mid) - slope * ts
                    smoothed_intercept = pepper_intercept.update(observed_intercept)
                    inferred = None if smoothed_intercept is None else smoothed_intercept + slope * ts
                else:
                    inferred = ref if ref is not None else meta.default_fair
                fair_method = "exact_latent" if exact_reference and ref is not None else "pepper_trend_fit"
                analysis_fair = ref if exact_reference and ref is not None else inferred
                trend = slope
            rows.append(
                FairRow(
                    day=day_dataset.day,
                    timestamp=ts,
                    product=product,
                    mid=mid,
                    microprice=microprice,
                    reference_fair=ref,
                    inferred_fair=inferred,
                    analysis_fair=analysis_fair,
                    fair_method=fair_method,
                    fair_is_exact=bool(exact_reference and ref is not None),
                    spread=_spread(snapshot),
                    fair_minus_mid=None if analysis_fair is None or mid is None else float(analysis_fair) - float(mid),
                    fair_minus_micro=None if analysis_fair is None or microprice is None else float(analysis_fair) - float(microprice),
                    trend_slope_per_tick=trend,
                ).to_dict()
            )
    return rows


def infer_market_fair_rows(
    market_days: Sequence[DayDataset],
    *,
    products: Sequence[str] = PRODUCTS,
    product_metadata: Mapping[str, ProductMeta] = PRODUCT_METADATA,
    round_spec: RoundSpec | None = None,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for day in market_days:
        rows.extend(
            infer_day_fair_rows(
                day,
                products=products,
                product_metadata=product_metadata,
                round_spec=round_spec,
            )
        )
    return rows


def summarize_fair_rows(rows: Sequence[Dict[str, object]], *, products: Sequence[str] = PRODUCTS) -> Dict[str, object]:
    per_product: Dict[str, Dict[str, object]] = {}
    for product in products:
        product_rows = [row for row in rows if row["product"] == product]
        if not product_rows:
            continue
        valid_mid = [abs(float(row["fair_minus_mid"])) for row in product_rows if row.get("fair_minus_mid") is not None]
        valid_micro = [abs(float(row["fair_minus_micro"])) for row in product_rows if row.get("fair_minus_micro") is not None]
        spread_rows = [float(row["spread"]) for row in product_rows if row.get("spread") is not None]
        exact_share = sum(1 for row in product_rows if row.get("fair_is_exact")) / len(product_rows)
        methods = sorted({str(row["fair_method"]) for row in product_rows})
        per_product[product] = {
            "rows": len(product_rows),
            "mean_abs_fair_minus_mid": statistics.fmean(valid_mid) if valid_mid else None,
            "mean_abs_fair_minus_micro": statistics.fmean(valid_micro) if valid_micro else None,
            "mean_spread": statistics.fmean(spread_rows) if spread_rows else None,
            "exact_share": exact_share,
            "methods": methods,
            "trend_slope_per_tick": product_rows[0].get("trend_slope_per_tick"),
        }
    return {"per_product": per_product}


def build_fair_lookup(rows: Sequence[Dict[str, object]]) -> Dict[tuple[int, str, int], Dict[str, object]]:
    return {(int(row["day"]), str(row["product"]), int(row["timestamp"])): row for row in rows}


def fair_path_bands(
    sample_runs: Sequence[Dict[str, object]],
    key: str,
    *,
    products: Sequence[str] = PRODUCTS,
) -> Dict[str, List[Dict[str, object]]]:
    bands: Dict[str, List[Dict[str, object]]] = {product: [] for product in products}
    for product in products:
        product_runs = []
        for run in sample_runs:
            rows = [row for row in run.get("fairValueSeries", []) if row.get("product") == product and row.get(key) is not None]
            if rows:
                product_runs.append(rows)
        if not product_runs:
            continue
        by_ts: Dict[int, List[float]] = {}
        for rows in product_runs:
            for row in rows:
                by_ts.setdefault(int(row["timestamp"]), []).append(float(row[key]))
        for ts in sorted(by_ts):
            vals = sorted(by_ts[ts])
            if not vals:
                continue
            def q(qv: float) -> float:
                if len(vals) == 1:
                    return vals[0]
                idx = qv * (len(vals) - 1)
                lo = int(idx)
                hi = min(len(vals) - 1, lo + 1)
                w = idx - lo
                return vals[lo] * (1.0 - w) + vals[hi] * w
            bands[product].append({
                "timestamp": ts,
                "p10": q(0.10),
                "p25": q(0.25),
                "p50": q(0.50),
                "p75": q(0.75),
                "p90": q(0.90),
                "min": vals[0],
                "max": vals[-1],
            })
    return bands
