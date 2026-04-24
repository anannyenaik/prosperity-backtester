from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Sequence

from .dataset import BookSnapshot, DayDataset, TradePrint
from .metadata import ProductMeta, RoundSpec, get_round_spec


ROUND3 = get_round_spec(3)
ROUND3_UNDERLYING = "VELVETFRUIT_EXTRACT"
ROUND3_HYDROGEL = "HYDROGEL_PACK"
ROUND3_VOUCHERS = tuple(
    product
    for product, meta in ROUND3.product_metadata.items()
    if meta.asset_class == "option"
)
ROUND3_SURFACE_FIT_VOUCHERS = tuple(
    product
    for product, meta in ROUND3.product_metadata.items()
    if meta.asset_class == "option" and bool(meta.include_in_surface_fit)
)


def round3_spec() -> RoundSpec:
    return ROUND3


def is_round3_voucher(symbol: str) -> bool:
    return str(symbol) in ROUND3_VOUCHERS


def parse_voucher_symbol(symbol: str) -> int:
    text = str(symbol).strip().upper()
    if not text.startswith("VEV_"):
        raise ValueError(f"{symbol!r} is not a Round 3 voucher symbol")
    suffix = text.split("_", 1)[1]
    if not suffix.isdigit():
        raise ValueError(f"{symbol!r} does not contain a numeric strike suffix")
    strike = int(suffix)
    if text not in ROUND3_VOUCHERS:
        raise ValueError(f"{symbol!r} is not part of the official Round 3 voucher set")
    return strike


def voucher_strike_map() -> Dict[str, int]:
    return {
        symbol: parse_voucher_symbol(symbol)
        for symbol in ROUND3_VOUCHERS
    }


def option_metadata(symbol: str, *, round_spec: RoundSpec | None = None) -> ProductMeta:
    spec = round_spec or ROUND3
    meta = spec.product_metadata.get(symbol)
    if meta is None or meta.asset_class != "option":
        raise KeyError(f"{symbol!r} is not an option product in round {spec.round_number}")
    return meta


def historical_tte_days(day: int, *, round_spec: RoundSpec | None = None) -> int:
    spec = round_spec or ROUND3
    if int(day) not in spec.tte_days_by_historical_day:
        raise KeyError(f"No historical TTE mapping for day {day} in round {spec.round_number}")
    return int(spec.tte_days_by_historical_day[int(day)])


def final_tte_days(*, round_spec: RoundSpec | None = None) -> int:
    spec = round_spec or ROUND3
    if spec.final_tte_days is None:
        raise ValueError(f"Round {spec.round_number} does not define a final TTE")
    return int(spec.final_tte_days)


def tte_years(days: float) -> float:
    return max(0.0, float(days)) / 365.0


def normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(float(value) / math.sqrt(2.0)))


def normal_pdf(value: float) -> float:
    return math.exp(-0.5 * float(value) * float(value)) / math.sqrt(2.0 * math.pi)


def intrinsic_value(spot: float, strike: float, option_type: str = "call") -> float:
    if option_type != "call":
        raise ValueError(f"Unsupported option type {option_type!r}")
    if not math.isfinite(float(spot)) or not math.isfinite(float(strike)):
        return 0.0
    return max(0.0, float(spot) - float(strike))


def time_value(price: float | None, spot: float | None, strike: float, option_type: str = "call") -> float | None:
    if price is None or spot is None:
        return None
    if not math.isfinite(float(price)) or not math.isfinite(float(spot)):
        return None
    return max(0.0, float(price) - intrinsic_value(float(spot), float(strike), option_type=option_type))


def moneyness(spot: float | None, strike: float) -> float | None:
    if spot is None or not math.isfinite(float(spot)) or float(strike) <= 0:
        return None
    return float(spot) / float(strike)


def black_scholes_call_price(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    volatility: float,
    *,
    rate: float = 0.0,
) -> float:
    s = float(spot)
    k = float(strike)
    t = max(0.0, float(time_to_expiry_years))
    sigma = max(0.0, float(volatility))
    r = float(rate)
    if not math.isfinite(s) or not math.isfinite(k) or not math.isfinite(t) or not math.isfinite(sigma):
        return 0.0
    if s <= 0.0 or k <= 0.0:
        return 0.0
    if t <= 0.0 or sigma <= 1e-12:
        return intrinsic_value(s, k)
    sqrt_t = math.sqrt(t)
    denom = sigma * sqrt_t
    if denom <= 1e-12:
        return intrinsic_value(s, k)
    d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / denom
    d2 = d1 - denom
    discounted_strike = k * math.exp(-r * t)
    return max(0.0, s * normal_cdf(d1) - discounted_strike * normal_cdf(d2))


def call_delta(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    volatility: float,
    *,
    rate: float = 0.0,
) -> float | None:
    s = float(spot)
    k = float(strike)
    t = max(0.0, float(time_to_expiry_years))
    sigma = max(0.0, float(volatility))
    if s <= 0.0 or k <= 0.0 or t <= 0.0 or sigma <= 1e-12:
        if not math.isfinite(s) or not math.isfinite(k):
            return None
        return 1.0 if s > k else 0.0
    denom = sigma * math.sqrt(t)
    if denom <= 1e-12:
        return 1.0 if s > k else 0.0
    d1 = (math.log(s / k) + (float(rate) + 0.5 * sigma * sigma) * t) / denom
    return normal_cdf(d1)


def call_gamma(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    volatility: float,
    *,
    rate: float = 0.0,
) -> float | None:
    s = float(spot)
    k = float(strike)
    t = max(0.0, float(time_to_expiry_years))
    sigma = max(0.0, float(volatility))
    if not math.isfinite(s) or not math.isfinite(k) or s <= 0.0 or k <= 0.0:
        return None
    if t <= 0.0 or sigma <= 1e-12:
        return 0.0
    denom = sigma * math.sqrt(t)
    if denom <= 1e-12:
        return 0.0
    d1 = (math.log(s / k) + (float(rate) + 0.5 * sigma * sigma) * t) / denom
    return normal_pdf(d1) / (s * denom)


def call_vega(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    volatility: float,
    *,
    rate: float = 0.0,
) -> float | None:
    s = float(spot)
    k = float(strike)
    t = max(0.0, float(time_to_expiry_years))
    sigma = max(0.0, float(volatility))
    if not math.isfinite(s) or not math.isfinite(k) or s <= 0.0 or k <= 0.0:
        return None
    if t <= 0.0 or sigma <= 1e-12:
        return 0.0
    denom = sigma * math.sqrt(t)
    if denom <= 1e-12:
        return 0.0
    d1 = (math.log(s / k) + (float(rate) + 0.5 * sigma * sigma) * t) / denom
    return s * normal_pdf(d1) * math.sqrt(t)


def implied_vol_bisection(
    price: float | None,
    spot: float | None,
    strike: float,
    time_to_expiry_years: float,
    *,
    rate: float = 0.0,
    low: float = 1e-6,
    high: float = 6.0,
    tol: float = 1e-6,
    max_iter: int = 128,
) -> float | None:
    if price is None or spot is None:
        return None
    observed = float(price)
    s = float(spot)
    k = float(strike)
    t = max(0.0, float(time_to_expiry_years))
    if not math.isfinite(observed) or not math.isfinite(s) or not math.isfinite(k) or not math.isfinite(t):
        return None
    if observed < 0.0 or s <= 0.0 or k <= 0.0:
        return None
    intrinsic = intrinsic_value(s, k)
    max_price = s
    if observed < intrinsic - 1e-9 or observed > max_price + 1e-9:
        return None
    if t <= 0.0:
        return 0.0 if abs(observed - intrinsic) <= tol else None
    if observed <= max(0.0, intrinsic) + tol:
        return 0.0
    lower = max(1e-8, float(low))
    upper = max(lower * 2.0, float(high))
    low_price = black_scholes_call_price(s, k, t, lower, rate=rate)
    high_price = black_scholes_call_price(s, k, t, upper, rate=rate)
    expand_count = 0
    while high_price < observed and expand_count < 12:
        upper *= 2.0
        high_price = black_scholes_call_price(s, k, t, upper, rate=rate)
        expand_count += 1
    if high_price < observed:
        return None
    for _ in range(max(1, int(max_iter))):
        mid = 0.5 * (lower + upper)
        mid_price = black_scholes_call_price(s, k, t, mid, rate=rate)
        if abs(mid_price - observed) <= tol:
            return mid
        if mid_price < observed:
            lower = mid
        else:
            upper = mid
    return 0.5 * (lower + upper)


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    idx = max(0.0, min(1.0, float(q))) * (len(ordered) - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return ordered[lo]
    weight = idx - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return statistics.median(float(value) for value in values)


def _std(values: Sequence[float]) -> float | None:
    return statistics.pstdev(values) if len(values) > 1 else 0.0 if values else None


def _snapshot_spread(snapshot) -> float | None:
    if snapshot is None or not snapshot.bids or not snapshot.asks:
        return None
    return float(snapshot.asks[0][0] - snapshot.bids[0][0])


def _snapshot_depth(snapshot) -> tuple[int | None, int | None]:
    if snapshot is None:
        return None, None
    top = None
    if snapshot.bids and snapshot.asks:
        top = int(snapshot.bids[0][1]) + int(snapshot.asks[0][1])
    total = sum(int(volume) for _price, volume in snapshot.bids) + sum(int(volume) for _price, volume in snapshot.asks)
    return top, total


def _surface_x(strike: float) -> float:
    return (float(strike) - 5_250.0) / 100.0


def _fit_surface_from_points(points: Sequence[tuple[float, float]]) -> tuple[float, float] | None:
    clean = [
        (_surface_x(strike), float(iv))
        for strike, iv in points
        if math.isfinite(float(strike)) and math.isfinite(float(iv)) and float(iv) > 0.0
    ]
    if not clean:
        return None
    if len(clean) == 1:
        return float(clean[0][1]), 0.0
    slopes: List[float] = []
    for left_index, (left_x, left_y) in enumerate(clean):
        for right_x, right_y in clean[left_index + 1:]:
            denom = right_x - left_x
            if abs(denom) <= 1e-12:
                continue
            slopes.append((right_y - left_y) / denom)
    slope = statistics.median(slopes) if slopes else 0.0
    slope = max(-1.0, min(1.0, float(slope)))
    intercept = statistics.median(y - slope * x for x, y in clean)
    return float(intercept), float(slope)


def _surface_iv_for_strike(surface: tuple[float, float], strike: float) -> float:
    intercept, slope = surface
    return max(1e-4, min(6.0, float(intercept) + float(slope) * _surface_x(strike)))


def _correlation(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    left_var = sum((value - left_mean) ** 2 for value in left)
    right_var = sum((value - right_mean) ** 2 for value in right)
    denom = math.sqrt(left_var * right_var)
    if denom <= 1e-12:
        return None
    cov = sum((l_value - left_mean) * (r_value - right_mean) for l_value, r_value in zip(left, right))
    return cov / denom


def _beta(x_values: Sequence[float], y_values: Sequence[float]) -> float | None:
    if len(x_values) < 2 or len(x_values) != len(y_values):
        return None
    x_mean = statistics.fmean(x_values)
    y_mean = statistics.fmean(y_values)
    variance = sum((value - x_mean) ** 2 for value in x_values)
    if variance <= 1e-12:
        return None
    covariance = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))
    return covariance / variance


def _residual_zscores(values: Sequence[float]) -> List[float]:
    if not values:
        return []
    centre = statistics.median(values)
    deviations = [abs(value - centre) for value in values]
    mad = statistics.median(deviations)
    if mad <= 1e-12:
        std = statistics.pstdev(values) if len(values) > 1 else 0.0
        if std <= 1e-12:
            return [0.0 for _value in values]
        return [(value - centre) / std for value in values]
    scale = 1.4826 * mad
    return [(value - centre) / scale for value in values]


def _sample_timestamps(timestamps: Sequence[int], *, max_count: int = 12) -> set[int]:
    if not timestamps:
        return set()
    if len(timestamps) <= max_count:
        return set(int(timestamp) for timestamp in timestamps)
    return {
        int(timestamps[round(index * (len(timestamps) - 1) / (max_count - 1))])
        for index in range(max_count)
    }


def _strike_warnings(meta: ProductMeta, mids: Sequence[float], valid_ivs: Sequence[float]) -> List[str]:
    warnings: List[str] = []
    if meta.symbol in {"VEV_4000", "VEV_4500"}:
        warnings.append("Deep ITM voucher with tiny time value. Implied vol is often unstable.")
    if meta.symbol in {"VEV_6000", "VEV_6500"}:
        warnings.append("Far OTM voucher is often pinned near 0.5 mid. Implied vol is mechanically inflated.")
    if mids and max(mids) <= 1.0:
        warnings.append("Voucher mid is pinned at tiny prices for most observations.")
    if len(valid_ivs) < max(10, len(mids) // 20):
        warnings.append("Few valid IV points survived filtering.")
    if meta.include_in_surface_fit is False:
        warnings.append("Excluded from the default global surface fit.")
    return warnings


@dataclass(frozen=True)
class VoucherDiagnostics:
    product: str
    strike: int
    tte_days: int
    average_mid: float | None
    average_spread: float | None
    average_intrinsic: float | None
    average_time_value: float | None
    average_moneyness: float | None
    iv_mean: float | None
    iv_median: float | None
    iv_p05: float | None
    iv_p95: float | None
    iv_std: float | None
    fitted_iv_mean: float | None
    model_fair_mean: float | None
    residual_mean: float | None
    residual_median: float | None
    residual_p05: float | None
    residual_p95: float | None
    residual_std: float | None
    residual_abs_z_p95: float | None
    delta_mean: float | None
    gamma_mean: float | None
    vega_mean: float | None
    average_top_depth: float | None
    average_total_depth: float | None
    move_beta_to_underlying: float | None
    valid_iv_count: int
    observation_count: int
    include_in_surface_fit: bool
    fit_reason: str
    warnings: tuple[str, ...]

    def to_dict(self) -> Dict[str, object]:
        return {
            "product": self.product,
            "strike": self.strike,
            "tte_days": self.tte_days,
            "average_mid": self.average_mid,
            "average_spread": self.average_spread,
            "average_intrinsic": self.average_intrinsic,
            "average_time_value": self.average_time_value,
            "average_moneyness": self.average_moneyness,
            "iv_mean": self.iv_mean,
            "iv_median": self.iv_median,
            "iv_p05": self.iv_p05,
            "iv_p95": self.iv_p95,
            "iv_std": self.iv_std,
            "fitted_iv_mean": self.fitted_iv_mean,
            "model_fair_mean": self.model_fair_mean,
            "residual_mean": self.residual_mean,
            "residual_median": self.residual_median,
            "residual_p05": self.residual_p05,
            "residual_p95": self.residual_p95,
            "residual_std": self.residual_std,
            "residual_abs_z_p95": self.residual_abs_z_p95,
            "delta_mean": self.delta_mean,
            "gamma_mean": self.gamma_mean,
            "vega_mean": self.vega_mean,
            "average_top_depth": self.average_top_depth,
            "average_total_depth": self.average_total_depth,
            "move_beta_to_underlying": self.move_beta_to_underlying,
            "valid_iv_count": self.valid_iv_count,
            "observation_count": self.observation_count,
            "include_in_surface_fit": self.include_in_surface_fit,
            "fit_reason": self.fit_reason,
            "warnings": list(self.warnings),
        }


def compute_option_diagnostics(
    market_days: Sequence[DayDataset],
    *,
    round_spec: RoundSpec | None = None,
) -> Dict[str, object]:
    spec = round_spec or ROUND3
    if spec.round_number != 3:
        return {"days": []}
    days_payload: List[Dict[str, object]] = []
    for day_dataset in market_days:
        try:
            tte_days_value = historical_tte_days(day_dataset.day, round_spec=spec)
        except KeyError:
            tte_days_value = final_tte_days(round_spec=spec)
        t_years = tte_years(tte_days_value)
        sample_timestamps = _sample_timestamps(day_dataset.timestamps)
        stats: Dict[str, Dict[str, List[float]]] = {
            symbol: {
                "mids": [],
                "spreads": [],
                "top_depths": [],
                "total_depths": [],
                "intrinsic": [],
                "time_value": [],
                "moneyness": [],
                "ivs": [],
                "fitted_ivs": [],
                "model_fairs": [],
                "residuals": [],
                "deltas": [],
                "gammas": [],
                "vegas": [],
                "underlying_moves": [],
                "voucher_moves": [],
            }
            for symbol in ROUND3_VOUCHERS
        }
        iv_by_timestamp: Dict[int, Dict[str, float]] = {}
        included_day_ivs: Dict[int, List[float]] = {}
        previous_underlying_mid: float | None = None
        previous_hydrogel_mid: float | None = None
        previous_voucher_mid: Dict[str, float | None] = {symbol: None for symbol in ROUND3_VOUCHERS}
        hydrogel_moves: List[float] = []
        underlying_moves_for_hydrogel: List[float] = []

        for timestamp in day_dataset.timestamps:
            snapshots = day_dataset.books_by_timestamp.get(timestamp, {})
            underlying_snapshot = snapshots.get(ROUND3_UNDERLYING)
            hydrogel_snapshot = snapshots.get(ROUND3_HYDROGEL)
            underlying_mid = None if underlying_snapshot is None else underlying_snapshot.mid
            hydrogel_mid = None if hydrogel_snapshot is None else hydrogel_snapshot.mid
            underlying_move = None if underlying_mid is None or previous_underlying_mid is None else float(underlying_mid) - previous_underlying_mid
            if (
                underlying_mid is not None
                and hydrogel_mid is not None
                and previous_underlying_mid is not None
                and previous_hydrogel_mid is not None
            ):
                underlying_moves_for_hydrogel.append(float(underlying_mid) - previous_underlying_mid)
                hydrogel_moves.append(float(hydrogel_mid) - previous_hydrogel_mid)

            if underlying_mid is None:
                if hydrogel_mid is not None:
                    previous_hydrogel_mid = float(hydrogel_mid)
                continue
            timestamp_ivs: Dict[str, float] = {}
            for symbol in ROUND3_VOUCHERS:
                meta = option_metadata(symbol, round_spec=spec)
                strike = float(meta.strike or parse_voucher_symbol(symbol))
                option_snapshot = snapshots.get(symbol)
                if option_snapshot is None:
                    continue
                spread = _snapshot_spread(option_snapshot)
                if spread is not None:
                    stats[symbol]["spreads"].append(spread)
                top_depth, total_depth = _snapshot_depth(option_snapshot)
                if top_depth is not None:
                    stats[symbol]["top_depths"].append(float(top_depth))
                if total_depth is not None:
                    stats[symbol]["total_depths"].append(float(total_depth))
                if option_snapshot.mid is None:
                    continue
                option_mid = float(option_snapshot.mid)
                stats[symbol]["mids"].append(option_mid)
                previous_mid = previous_voucher_mid.get(symbol)
                if previous_mid is not None and underlying_move is not None:
                    stats[symbol]["underlying_moves"].append(underlying_move)
                    stats[symbol]["voucher_moves"].append(option_mid - previous_mid)
                previous_voucher_mid[symbol] = option_mid
                intrinsic = intrinsic_value(float(underlying_mid), strike)
                time_val = time_value(option_mid, float(underlying_mid), strike)
                money = moneyness(float(underlying_mid), strike)
                stats[symbol]["intrinsic"].append(intrinsic)
                if time_val is not None:
                    stats[symbol]["time_value"].append(time_val)
                if money is not None:
                    stats[symbol]["moneyness"].append(money)
                iv = implied_vol_bisection(option_mid, float(underlying_mid), strike, t_years)
                if iv is None:
                    continue
                stats[symbol]["ivs"].append(iv)
                timestamp_ivs[symbol] = iv
                if meta.include_in_surface_fit:
                    included_day_ivs.setdefault(int(strike), []).append(iv)
            if timestamp_ivs:
                iv_by_timestamp[timestamp] = timestamp_ivs
            previous_underlying_mid = float(underlying_mid)
            if hydrogel_mid is not None:
                previous_hydrogel_mid = float(hydrogel_mid)

        fallback_points = [
            (float(strike), float(statistics.median(values)))
            for strike, values in sorted(included_day_ivs.items())
            if values
        ]
        day_fallback_surface = _fit_surface_from_points(fallback_points) or (0.25, 0.0)
        previous_surface: tuple[float, float] | None = None
        fit_source_counts = {"direct": 0, "previous": 0, "day_median": 0}
        included_point_counts: List[float] = []
        chain_samples: List[Dict[str, object]] = []
        residual_index_by_key: Dict[tuple[int, str], int] = {}

        for timestamp in day_dataset.timestamps:
            snapshots = day_dataset.books_by_timestamp.get(timestamp, {})
            underlying_snapshot = snapshots.get(ROUND3_UNDERLYING)
            if underlying_snapshot is None or underlying_snapshot.mid is None:
                continue
            spot = float(underlying_snapshot.mid)
            timestamp_ivs = iv_by_timestamp.get(timestamp, {})
            fit_points = [
                (float(option_metadata(symbol, round_spec=spec).strike or parse_voucher_symbol(symbol)), iv)
                for symbol, iv in timestamp_ivs.items()
                if option_metadata(symbol, round_spec=spec).include_in_surface_fit
            ]
            included_point_counts.append(float(len(fit_points)))
            surface = _fit_surface_from_points(fit_points)
            if surface is not None and len(fit_points) >= 2:
                fit_source = "direct"
                previous_surface = surface
            elif previous_surface is not None:
                surface = previous_surface
                fit_source = "previous"
            else:
                surface = day_fallback_surface
                fit_source = "day_median"
                previous_surface = surface
            fit_source_counts[fit_source] = fit_source_counts.get(fit_source, 0) + 1

            for symbol in ROUND3_VOUCHERS:
                meta = option_metadata(symbol, round_spec=spec)
                strike = float(meta.strike or parse_voucher_symbol(symbol))
                option_snapshot = snapshots.get(symbol)
                if option_snapshot is None or option_snapshot.mid is None:
                    continue
                fitted_iv = _surface_iv_for_strike(surface, strike)
                model_fair = black_scholes_call_price(spot, strike, t_years, fitted_iv)
                residual = float(option_snapshot.mid) - model_fair
                delta = call_delta(spot, strike, t_years, fitted_iv)
                gamma = call_gamma(spot, strike, t_years, fitted_iv)
                vega = call_vega(spot, strike, t_years, fitted_iv)
                residual_index_by_key[(timestamp, symbol)] = len(stats[symbol]["residuals"])
                stats[symbol]["fitted_ivs"].append(fitted_iv)
                stats[symbol]["model_fairs"].append(model_fair)
                stats[symbol]["residuals"].append(residual)
                if delta is not None:
                    stats[symbol]["deltas"].append(delta)
                if gamma is not None:
                    stats[symbol]["gammas"].append(gamma)
                if vega is not None:
                    stats[symbol]["vegas"].append(vega)
                if timestamp in sample_timestamps:
                    spread = _snapshot_spread(option_snapshot)
                    top_depth, total_depth = _snapshot_depth(option_snapshot)
                    intrinsic = intrinsic_value(spot, strike)
                    tv = time_value(float(option_snapshot.mid), spot, strike)
                    raw_iv = timestamp_ivs.get(symbol)
                    chain_samples.append({
                        "day": day_dataset.day,
                        "timestamp": timestamp,
                        "underlying_mid": spot,
                        "product": symbol,
                        "strike": int(strike),
                        "mid": float(option_snapshot.mid),
                        "intrinsic": intrinsic,
                        "time_value": tv,
                        "moneyness": moneyness(spot, strike),
                        "implied_vol": raw_iv,
                        "fitted_iv": fitted_iv,
                        "model_fair": model_fair,
                        "delta": delta,
                        "gamma": gamma,
                        "vega": vega,
                        "residual": residual,
                        "bid_ask_spread": spread,
                        "top_depth": top_depth,
                        "total_depth": total_depth,
                        "include_in_surface_fit": bool(meta.include_in_surface_fit),
                        "fit_source": fit_source,
                        "fit_reason": "primary_surface_strike" if meta.include_in_surface_fit else "excluded_diagnostic_strike",
                    })

        residual_zscores_by_symbol = {
            symbol: _residual_zscores(values["residuals"])
            for symbol, values in stats.items()
        }
        for row in chain_samples:
            symbol = str(row["product"])
            idx = residual_index_by_key.get((int(row["timestamp"]), symbol), -1)
            zscores = residual_zscores_by_symbol.get(symbol, [])
            row["residual_zscore"] = zscores[idx] if 0 <= idx < len(zscores) else None

        voucher_rows: List[Dict[str, object]] = []
        for symbol in ROUND3_VOUCHERS:
            meta = option_metadata(symbol, round_spec=spec)
            strikes = float(meta.strike or parse_voucher_symbol(symbol))
            values = stats[symbol]
            abs_zscores = [abs(value) for value in residual_zscores_by_symbol.get(symbol, [])]
            diagnostics = VoucherDiagnostics(
                product=symbol,
                strike=int(strikes),
                tte_days=int(tte_days_value),
                average_mid=_mean(values["mids"]),
                average_spread=_mean(values["spreads"]),
                average_intrinsic=_mean(values["intrinsic"]),
                average_time_value=_mean(values["time_value"]),
                average_moneyness=_mean(values["moneyness"]),
                iv_mean=_mean(values["ivs"]),
                iv_median=_median(values["ivs"]),
                iv_p05=_quantile(values["ivs"], 0.05),
                iv_p95=_quantile(values["ivs"], 0.95),
                iv_std=_std(values["ivs"]),
                fitted_iv_mean=_mean(values["fitted_ivs"]),
                model_fair_mean=_mean(values["model_fairs"]),
                residual_mean=_mean(values["residuals"]),
                residual_median=_median(values["residuals"]),
                residual_p05=_quantile(values["residuals"], 0.05),
                residual_p95=_quantile(values["residuals"], 0.95),
                residual_std=_std(values["residuals"]),
                residual_abs_z_p95=_quantile(abs_zscores, 0.95),
                delta_mean=_mean(values["deltas"]),
                gamma_mean=_mean(values["gammas"]),
                vega_mean=_mean(values["vegas"]),
                average_top_depth=_mean(values["top_depths"]),
                average_total_depth=_mean(values["total_depths"]),
                move_beta_to_underlying=_beta(values["underlying_moves"], values["voucher_moves"]),
                valid_iv_count=len(values["ivs"]),
                observation_count=len(values["mids"]),
                include_in_surface_fit=bool(meta.include_in_surface_fit),
                fit_reason="primary_surface_strike" if meta.include_in_surface_fit else "excluded_diagnostic_strike",
                warnings=tuple(_strike_warnings(meta, values["mids"], values["ivs"])),
            )
            voucher_rows.append(diagnostics.to_dict())
        excluded = [row["product"] for row in voucher_rows if not row["include_in_surface_fit"]]
        included = [row["product"] for row in voucher_rows if row["include_in_surface_fit"]]
        included_residuals = [
            float(residual)
            for row in voucher_rows
            if row["include_in_surface_fit"]
            for residual in stats[str(row["product"])]["residuals"]
        ]
        days_payload.append(
            {
                "day": day_dataset.day,
                "tte_days": tte_days_value,
                "vouchers": voucher_rows,
                "chain_samples": chain_samples,
                "underlying_hydrogel_move_correlation": _correlation(underlying_moves_for_hydrogel, hydrogel_moves),
                "surface_fit_quality": {
                    "fit_source_counts": fit_source_counts,
                    "median_included_points_per_timestamp": _median(included_point_counts),
                    "mean_abs_included_residual": _mean([abs(value) for value in included_residuals]),
                    "fallback_surface": {
                        "intercept": day_fallback_surface[0],
                        "slope_per_100_strike": day_fallback_surface[1],
                    },
                    "warnings": [
                        "Per-timestamp surfaces use a robust linear Theil-Sen fit across primary strikes.",
                        "Fallbacks reuse the previous fit, then the per-day median surface if needed.",
                    ],
                },
                "surface_fit_policy": {
                    "included": included,
                    "excluded": excluded,
                    "notes": [
                        "Default surface fit centres on VEV_5000 through VEV_5500.",
                        "Deep ITM and pinned far OTM strikes are excluded by default.",
                    ],
                },
            }
        )
    return {
        "round": 3,
        "underlying": ROUND3_UNDERLYING,
        "days": days_payload,
        "final_tte_days": final_tte_days(round_spec=spec),
        "surface_fit_vouchers": list(ROUND3_SURFACE_FIT_VOUCHERS),
    }


def _surface_from_option_diagnostics(diagnostics: Mapping[str, object]) -> Dict[int, float]:
    by_strike: Dict[int, List[float]] = {}
    for day_row in diagnostics.get("days", []):
        if not isinstance(day_row, Mapping):
            continue
        for voucher in day_row.get("vouchers", []):
            if not isinstance(voucher, Mapping) or not voucher.get("include_in_surface_fit"):
                continue
            strike = voucher.get("strike")
            iv_value = voucher.get("iv_median") if voucher.get("iv_median") is not None else voucher.get("iv_mean")
            if strike is None or iv_value is None:
                continue
            by_strike.setdefault(int(strike), []).append(float(iv_value))
    surface = {
        strike: statistics.median(values)
        for strike, values in by_strike.items()
        if values
    }
    if not surface:
        surface = {parse_voucher_symbol(symbol): 0.25 for symbol in ROUND3_SURFACE_FIT_VOUCHERS}
    for symbol in ROUND3_VOUCHERS:
        strike = parse_voucher_symbol(symbol)
        if strike in surface:
            continue
        nearest = min(surface, key=lambda candidate: abs(candidate - strike))
        surface[strike] = float(surface[nearest])
    return dict(sorted(surface.items()))


def robust_surface_iv_by_strike(
    market_days: Sequence[DayDataset],
    *,
    round_spec: RoundSpec | None = None,
) -> Dict[int, float]:
    spec = round_spec or ROUND3
    diagnostics = compute_option_diagnostics(market_days, round_spec=spec)
    return _surface_from_option_diagnostics(diagnostics)


@dataclass(frozen=True)
class BookTemplate:
    spread: int
    bid_price_offsets: tuple[int, ...]
    bid_volumes: tuple[int, ...]
    ask_price_offsets: tuple[int, ...]
    ask_volumes: tuple[int, ...]


@dataclass(frozen=True)
class Delta1Calibration:
    start_candidates: tuple[float, ...]
    step_changes: tuple[float, ...]
    book_templates: tuple[BookTemplate, ...]
    trade_active_prob: float
    second_trade_prob: float
    trade_quantities: tuple[int, ...]


@dataclass(frozen=True)
class VoucherCalibration:
    symbol: str
    strike: int
    base_iv: float
    residuals: tuple[float, ...]
    book_templates: tuple[BookTemplate, ...]
    trade_active_prob: float
    second_trade_prob: float
    trade_quantities: tuple[int, ...]


@dataclass(frozen=True)
class Round3SyntheticContext:
    round_spec: RoundSpec
    tick_count: int
    hydrogel: Delta1Calibration
    underlying: Delta1Calibration
    vouchers: Dict[str, VoucherCalibration]
    surface_iv_by_strike: Dict[int, float]
    option_diagnostics: Dict[str, object]


def _build_book_template(snapshot: BookSnapshot) -> BookTemplate | None:
    if not snapshot.bids or not snapshot.asks:
        return None
    best_bid = int(snapshot.bids[0][0])
    best_ask = int(snapshot.asks[0][0])
    spread = int(best_ask - best_bid)
    if spread <= 0:
        return None
    return BookTemplate(
        spread=spread,
        bid_price_offsets=tuple(best_bid - int(price) for price, _volume in snapshot.bids[:3]),
        bid_volumes=tuple(int(volume) for _price, volume in snapshot.bids[:3]),
        ask_price_offsets=tuple(int(price) - best_ask for price, _volume in snapshot.asks[:3]),
        ask_volumes=tuple(int(volume) for _price, volume in snapshot.asks[:3]),
    )


def _trade_stats(market_days: Sequence[DayDataset], symbol: str, tick_count: int) -> tuple[float, float, tuple[int, ...]]:
    counts: List[int] = []
    quantities: List[int] = []
    for day_dataset in market_days:
        for timestamp in day_dataset.timestamps[:tick_count]:
            trades = list(day_dataset.trades_by_timestamp.get(timestamp, {}).get(symbol, []))
            count = len(trades)
            counts.append(count)
            for trade in trades:
                if int(trade.quantity) > 0:
                    quantities.append(int(trade.quantity))
    if not counts:
        return 0.0, 0.0, (1, 2, 3)
    active = sum(1 for count in counts if count > 0)
    second = sum(1 for count in counts if count > 1)
    active_prob = active / len(counts)
    second_prob = 0.0 if active == 0 else second / active
    if not quantities:
        quantities = [1, 2, 3]
    return active_prob, second_prob, tuple(quantities)


def _delta1_calibration(market_days: Sequence[DayDataset], symbol: str, tick_count: int, fallback_start: float) -> Delta1Calibration:
    starts: List[float] = []
    changes: List[float] = []
    templates: List[BookTemplate] = []
    for day_dataset in market_days:
        previous_mid: float | None = None
        for timestamp in day_dataset.timestamps[:tick_count]:
            snapshot = day_dataset.books_by_timestamp.get(timestamp, {}).get(symbol)
            if snapshot is None:
                continue
            template = _build_book_template(snapshot)
            if template is not None:
                templates.append(template)
            if snapshot.mid is None:
                continue
            current_mid = float(snapshot.mid)
            if previous_mid is None:
                starts.append(current_mid)
            else:
                changes.append(current_mid - previous_mid)
            previous_mid = current_mid
    active_prob, second_prob, quantities = _trade_stats(market_days, symbol, tick_count)
    if not starts:
        starts = [float(fallback_start)]
    if not changes:
        changes = [0.0]
    if not templates:
        templates = [BookTemplate(spread=2, bid_price_offsets=(0,), bid_volumes=(10,), ask_price_offsets=(0,), ask_volumes=(10,))]
    return Delta1Calibration(
        start_candidates=tuple(starts),
        step_changes=tuple(changes),
        book_templates=tuple(templates),
        trade_active_prob=active_prob,
        second_trade_prob=second_prob,
        trade_quantities=quantities,
    )


def _voucher_calibration(
    market_days: Sequence[DayDataset],
    symbol: str,
    strike: int,
    surface_iv_by_strike: Mapping[int, float],
    tick_count: int,
) -> VoucherCalibration:
    templates: List[BookTemplate] = []
    residuals: List[float] = []
    for day_dataset in market_days:
        tte = historical_tte_days(day_dataset.day)
        t_years = tte_years(tte)
        for timestamp in day_dataset.timestamps[:tick_count]:
            option_snapshot = day_dataset.books_by_timestamp.get(timestamp, {}).get(symbol)
            underlying_snapshot = day_dataset.books_by_timestamp.get(timestamp, {}).get(ROUND3_UNDERLYING)
            if option_snapshot is None:
                continue
            template = _build_book_template(option_snapshot)
            if template is not None:
                templates.append(template)
            if option_snapshot.mid is None or underlying_snapshot is None or underlying_snapshot.mid is None:
                continue
            model_mid = black_scholes_call_price(
                float(underlying_snapshot.mid),
                float(strike),
                t_years,
                float(surface_iv_by_strike.get(strike, 0.25)),
            )
            residuals.append(float(option_snapshot.mid) - model_mid)
    active_prob, second_prob, quantities = _trade_stats(market_days, symbol, tick_count)
    if not templates:
        templates = [BookTemplate(spread=1, bid_price_offsets=(0,), bid_volumes=(10,), ask_price_offsets=(0,), ask_volumes=(10,))]
    if not residuals:
        residuals = [0.0]
    return VoucherCalibration(
        symbol=symbol,
        strike=int(strike),
        base_iv=float(surface_iv_by_strike.get(strike, 0.25)),
        residuals=tuple(residuals),
        book_templates=tuple(templates),
        trade_active_prob=active_prob,
        second_trade_prob=second_prob,
        trade_quantities=quantities,
    )


def prepare_round3_synthetic_context(
    market_days: Sequence[DayDataset],
    *,
    round_spec: RoundSpec | None = None,
    tick_count: int | None = None,
) -> Round3SyntheticContext:
    spec = round_spec or ROUND3
    effective_tick_count = spec.ticks_per_day if tick_count is None else max(1, int(tick_count))
    diagnostics = compute_option_diagnostics(market_days, round_spec=spec)
    surface = _surface_from_option_diagnostics(diagnostics)
    hydrogel = _delta1_calibration(market_days, ROUND3_HYDROGEL, effective_tick_count, fallback_start=9_960.0)
    underlying = _delta1_calibration(market_days, ROUND3_UNDERLYING, effective_tick_count, fallback_start=5_250.0)
    vouchers = {
        symbol: _voucher_calibration(
            market_days,
            symbol,
            parse_voucher_symbol(symbol),
            surface,
            effective_tick_count,
        )
        for symbol in ROUND3_VOUCHERS
    }
    return Round3SyntheticContext(
        round_spec=spec,
        tick_count=effective_tick_count,
        hydrogel=hydrogel,
        underlying=underlying,
        vouchers=vouchers,
        surface_iv_by_strike=surface,
        option_diagnostics=diagnostics,
    )


def _sample_trade_count(active_prob: float, second_prob: float, rng: random.Random) -> int:
    if rng.random() >= max(0.0, min(1.0, float(active_prob))):
        return 0
    count = 1
    if rng.random() < max(0.0, min(1.0, float(second_prob))):
        count += 1
    return count


def _sample_delta_path(
    calibration: Delta1Calibration,
    *,
    rng: random.Random,
    tick_count: int,
    start: float | None = None,
    shock_tick: int | None = None,
    shock_amount: float = 0.0,
    vol_scale: float = 1.0,
) -> List[float]:
    chosen_start = float(start if start is not None else rng.choice(calibration.start_candidates))
    mean_change = statistics.fmean(calibration.step_changes) if calibration.step_changes else 0.0
    path = [0.0] * tick_count
    path[0] = max(0.0, chosen_start)
    for index in range(1, tick_count):
        sampled = float(rng.choice(calibration.step_changes))
        delta = mean_change + (sampled - mean_change) * max(0.0, float(vol_scale))
        path[index] = max(0.0, path[index - 1] + delta)
    if shock_tick is not None and shock_amount != 0.0:
        start_index = max(0, min(tick_count, int(shock_tick)))
        for index in range(start_index, tick_count):
            path[index] = max(0.0, path[index] + float(shock_amount))
    return path


def _aggregate_levels(levels: Sequence[tuple[int, int]], *, descending: bool) -> List[tuple[int, int]]:
    aggregated: Dict[int, int] = {}
    for price, volume in levels:
        if volume <= 0:
            continue
        aggregated[int(price)] = aggregated.get(int(price), 0) + int(volume)
    return sorted(aggregated.items(), key=lambda item: -item[0] if descending else item[0])[:3]


def build_book_from_template(
    mid: float,
    template: BookTemplate,
    *,
    liquidity_scale: float = 1.0,
    spread_shift_ticks: int = 0,
) -> tuple[List[tuple[int, int]], List[tuple[int, int]], float]:
    spread = max(1, int(template.spread) + int(spread_shift_ticks))
    best_bid = int(math.floor(float(mid) - spread / 2.0))
    best_bid = max(0, best_bid)
    best_ask = max(best_bid + 1, best_bid + spread)
    bids = _aggregate_levels(
        [
            (best_bid - int(offset), max(1, int(round(int(volume) * max(0.0, float(liquidity_scale))))))
            for offset, volume in zip(template.bid_price_offsets, template.bid_volumes)
        ],
        descending=True,
    )
    asks = _aggregate_levels(
        [
            (best_ask + int(offset), max(1, int(round(int(volume) * max(0.0, float(liquidity_scale))))))
            for offset, volume in zip(template.ask_price_offsets, template.ask_volumes)
        ],
        descending=False,
    )
    realised_mid = (bids[0][0] + asks[0][0]) / 2.0 if bids and asks else float(mid)
    return bids, asks, realised_mid


def _sample_trade_price_and_qty(
    bids: Sequence[tuple[int, int]],
    asks: Sequence[tuple[int, int]],
    trade_quantities: Sequence[int],
    rng: random.Random,
) -> tuple[bool, float, int] | None:
    market_buy = rng.random() < 0.5
    levels = asks if market_buy else bids
    if not levels:
        return None
    price = float(levels[0][0])
    volume_limit = sum(int(volume) for _price, volume in levels)
    quantity = max(1, min(int(rng.choice(tuple(trade_quantities))), volume_limit))
    return market_buy, price, quantity


def _adjusted_option_iv(
    base_iv: float,
    *,
    spot: float,
    strike: float,
    vol_shift: float,
    vol_scale: float,
    skew_shift: float,
) -> float:
    moneyness_shift = 0.0 if spot <= 0 else (float(strike) - float(spot)) / max(float(spot), 1.0)
    shifted = (float(base_iv) + float(vol_shift) + float(skew_shift) * moneyness_shift) * max(0.0, float(vol_scale))
    return max(1e-4, shifted)


def synthetic_tte_days(day: int, session_day_index: int, *, round_spec: RoundSpec | None = None) -> int:
    spec = round_spec or ROUND3
    mapped = spec.tte_days_by_historical_day.get(int(day))
    if mapped is not None:
        return int(mapped)
    base = final_tte_days(round_spec=spec)
    return max(0, int(base) - int(session_day_index))


def generate_round3_day(
    *,
    context: Round3SyntheticContext,
    day: int,
    session_day_index: int,
    market_rng: random.Random,
    perturbation,
    last_hydrogel: float | None = None,
    last_underlying: float | None = None,
) -> tuple[DayDataset, float, float]:
    tick_count = int(context.tick_count)
    timestamps = [tick * context.round_spec.timestamp_step for tick in range(tick_count)]
    hydrogel_path = _sample_delta_path(
        context.hydrogel,
        rng=market_rng,
        tick_count=tick_count,
        start=last_hydrogel,
        shock_tick=perturbation.shock_tick,
        shock_amount=perturbation.hydrogel_shock,
    )
    underlying_path = _sample_delta_path(
        context.underlying,
        rng=market_rng,
        tick_count=tick_count,
        start=last_underlying,
        shock_tick=perturbation.shock_tick,
        shock_amount=perturbation.underlying_shock,
        vol_scale=max(0.0, float(getattr(perturbation, "vol_scale", 1.0))),
    )
    t_years = tte_years(synthetic_tte_days(day, session_day_index, round_spec=context.round_spec))
    books_by_timestamp: Dict[int, Dict[str, BookSnapshot]] = {}
    trades_by_timestamp: Dict[int, Dict[str, List[TradePrint]]] = {}
    for tick, timestamp in enumerate(timestamps):
        per_product: Dict[str, BookSnapshot] = {}
        tick_trades: Dict[str, List[TradePrint]] = {}

        hydrogel_template = market_rng.choice(context.hydrogel.book_templates)
        hydrogel_bids, hydrogel_asks, hydrogel_mid = build_book_from_template(
            hydrogel_path[tick],
            hydrogel_template,
            liquidity_scale=float(getattr(perturbation, "hydrogel_liquidity_scale", 1.0)),
            spread_shift_ticks=int(getattr(perturbation, "spread_shift_ticks", 0)),
        )
        per_product[ROUND3_HYDROGEL] = BookSnapshot(
            timestamp=timestamp,
            product=ROUND3_HYDROGEL,
            bids=hydrogel_bids,
            asks=hydrogel_asks,
            mid=hydrogel_mid,
            reference_fair=hydrogel_path[tick],
            source_day=int(day),
        )
        hydrogel_trade_count = _sample_trade_count(
            context.hydrogel.trade_active_prob,
            context.hydrogel.second_trade_prob,
            market_rng,
        )
        for _ in range(hydrogel_trade_count):
            sampled = _sample_trade_price_and_qty(
                hydrogel_bids,
                hydrogel_asks,
                context.hydrogel.trade_quantities,
                market_rng,
            )
            if sampled is None:
                continue
            market_buy, trade_price, quantity = sampled
            tick_trades.setdefault(ROUND3_HYDROGEL, []).append(
                TradePrint(
                    timestamp=timestamp,
                    buyer="BOT_TAKER" if market_buy else "",
                    seller="" if market_buy else "BOT_TAKER",
                    symbol=ROUND3_HYDROGEL,
                    price=trade_price,
                    quantity=quantity,
                    synthetic=True,
                )
            )

        underlying_template = market_rng.choice(context.underlying.book_templates)
        underlying_bids, underlying_asks, underlying_mid = build_book_from_template(
            underlying_path[tick],
            underlying_template,
            liquidity_scale=float(getattr(perturbation, "underlying_liquidity_scale", 1.0)),
            spread_shift_ticks=int(getattr(perturbation, "spread_shift_ticks", 0)),
        )
        per_product[ROUND3_UNDERLYING] = BookSnapshot(
            timestamp=timestamp,
            product=ROUND3_UNDERLYING,
            bids=underlying_bids,
            asks=underlying_asks,
            mid=underlying_mid,
            reference_fair=underlying_path[tick],
            source_day=int(day),
        )
        underlying_trade_count = _sample_trade_count(
            context.underlying.trade_active_prob,
            context.underlying.second_trade_prob,
            market_rng,
        )
        for _ in range(underlying_trade_count):
            sampled = _sample_trade_price_and_qty(
                underlying_bids,
                underlying_asks,
                context.underlying.trade_quantities,
                market_rng,
            )
            if sampled is None:
                continue
            market_buy, trade_price, quantity = sampled
            tick_trades.setdefault(ROUND3_UNDERLYING, []).append(
                TradePrint(
                    timestamp=timestamp,
                    buyer="BOT_TAKER" if market_buy else "",
                    seller="" if market_buy else "BOT_TAKER",
                    symbol=ROUND3_UNDERLYING,
                    price=trade_price,
                    quantity=quantity,
                    synthetic=True,
                )
            )

        for symbol in ROUND3_VOUCHERS:
            calibration = context.vouchers[symbol]
            adjusted_iv = _adjusted_option_iv(
                calibration.base_iv,
                spot=underlying_path[tick],
                strike=calibration.strike,
                vol_shift=float(getattr(perturbation, "vol_shift", 0.0)),
                vol_scale=float(getattr(perturbation, "vol_scale", 1.0)),
                skew_shift=float(getattr(perturbation, "skew_shift", 0.0)),
            )
            theoretical_mid = black_scholes_call_price(
                underlying_path[tick],
                calibration.strike,
                t_years,
                adjusted_iv,
            )
            residual = float(market_rng.choice(calibration.residuals))
            target_mid = max(
                0.0,
                theoretical_mid + residual * max(0.0, float(getattr(perturbation, "option_residual_noise_scale", 1.0))),
            )
            template = market_rng.choice(calibration.book_templates)
            bids, asks, realised_mid = build_book_from_template(
                target_mid,
                template,
                liquidity_scale=float(getattr(perturbation, "option_liquidity_scale", 1.0)),
                spread_shift_ticks=int(getattr(perturbation, "voucher_spread_shift_ticks", 0)),
            )
            per_product[symbol] = BookSnapshot(
                timestamp=timestamp,
                product=symbol,
                bids=bids,
                asks=asks,
                mid=realised_mid,
                reference_fair=target_mid,
                source_day=int(day),
            )
            trade_count = _sample_trade_count(
                calibration.trade_active_prob,
                calibration.second_trade_prob,
                market_rng,
            )
            for _ in range(trade_count):
                sampled = _sample_trade_price_and_qty(
                    bids,
                    asks,
                    calibration.trade_quantities,
                    market_rng,
                )
                if sampled is None:
                    continue
                market_buy, trade_price, quantity = sampled
                tick_trades.setdefault(symbol, []).append(
                    TradePrint(
                        timestamp=timestamp,
                        buyer="BOT_TAKER" if market_buy else "",
                        seller="" if market_buy else "BOT_TAKER",
                        symbol=symbol,
                        price=trade_price,
                        quantity=quantity,
                        synthetic=True,
                    )
                )

        books_by_timestamp[timestamp] = per_product
        if tick_trades:
            trades_by_timestamp[timestamp] = tick_trades

    return (
        DayDataset(
            day=int(day),
            timestamps=timestamps,
            books_by_timestamp=books_by_timestamp,
            trades_by_timestamp=trades_by_timestamp,
            validation={
                "timestamps": len(timestamps),
                "source": "synthetic_round3",
                "price_rows": len(timestamps) * len(context.round_spec.products),
                "trade_rows": sum(len(trades) for by_product in trades_by_timestamp.values() for trades in by_product.values()),
            },
            metadata={
                "source": "synthetic_round3",
                "round": context.round_spec.round_number,
                "surface_iv_by_strike": dict(context.surface_iv_by_strike),
            },
            round_number=context.round_spec.round_number,
            products=tuple(context.round_spec.products),
        ),
        hydrogel_path[-1],
        underlying_path[-1],
    )
