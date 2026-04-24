#!/usr/bin/env python3
"""
Round 3 volatility-smile lab: Frankfurt-style recreation, strike-band flattening, and residual exploitation.

Run from the repo root:
    python r3_vol_smile.py --data-dir data/round3 --out-dir r3_smile_perfect

What this produces:
    01_raw_frankfurt_smile.png
        Closest to the 2nd-place team's published smile method: annualised IV vs m_t with a quadratic fit.

    02_static_strike_bias_flattened_smile.png
        Same data after removing each strike's persistent full-sample IV offset. Presentation only, not trader-safe.

    03_binned_static_adjusted_smile.png
        Cleanest visual explanation: binned median of the strike-bias-flattened smile.

    04_raw_iv_residuals.png
        Raw IV residuals over time.

    05_ewma_price_signal.png
        Past-only EWMA strike-bias fair-price residual. This is the more trader-relevant signal.

    06_ewma_price_z.png
        Past-only z-score of the fair-price residual.

    07_filter_audit.png
        Shows why extreme strikes are excluded from the central smile fit.

    08_z_threshold_forward_diagnostics.png
        Mid-price-only forward mean-reversion sanity check by z-score threshold.

    README_SEND_TO_FRIEND.txt
        Short explanation of what to send and what each plot means.

Important honesty:
    - Plot 01 is the faithful raw recreation of the published Frankfurt-style method.
    - Plots 02/03 are our extra step for this year's more strike-banded VEV data.
    - Plots 05/06/08 are research diagnostics, not fill-aware backtests.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Iterable, Sequence

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

UNDERLYING = "VELVETFRUIT_EXTRACT"
HYDROGEL = "HYDROGEL_PACK"
VOUCHER_PREFIX = "VEV_"
START_TTE_DAYS_BY_DAY = {0: 8.0, 1: 7.0, 2: 6.0}
DEFAULT_DAYS = (0, 1, 2)
ALL_STRIKES = (4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500)
DEFAULT_FIT_STRIKES = (5000, 5100, 5200, 5300, 5400, 5500)
EXPECTED_PRODUCTS = {HYDROGEL, UNDERLYING} | {f"{VOUCHER_PREFIX}{k}" for k in ALL_STRIKES}

try:
    from scipy.special import ndtr as _scipy_ndtr  # type: ignore
except Exception:  # pragma: no cover - scipy is optional
    _scipy_ndtr = None


def parse_int_tuple(raw: str | Sequence[int]) -> tuple[int, ...]:
    if isinstance(raw, (tuple, list)):
        return tuple(int(x) for x in raw)
    return tuple(int(part.strip()) for part in str(raw).split(",") if part.strip())


def parse_float_tuple(raw: str | Sequence[float]) -> tuple[float, ...]:
    if isinstance(raw, (tuple, list)):
        return tuple(float(x) for x in raw)
    return tuple(float(part.strip()) for part in str(raw).split(",") if part.strip())


def normal_cdf_array(x: np.ndarray) -> np.ndarray:
    """Fast vectorised standard-normal CDF.

    Uses scipy.ndtr when present. Otherwise uses a standard Abramowitz-Stegun-style approximation.
    The fallback error is tiny for this visual/research use and avoids requiring scipy.
    """
    x = np.asarray(x, dtype=float)
    if _scipy_ndtr is not None:
        return _scipy_ndtr(x)

    sign = np.where(x < 0.0, -1.0, 1.0)
    z = np.abs(x) / math.sqrt(2.0)
    t = 1.0 / (1.0 + 0.3275911 * z)
    # Approximation to erf(z).
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    erf_approx = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * np.exp(-(z * z))
    erf_signed = sign * erf_approx
    return 0.5 * (1.0 + erf_signed)


def normal_pdf_array(x: np.ndarray) -> np.ndarray:
    return np.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_call_price_array(spot, strike, time_years, sigma, rate: float = 0.0) -> np.ndarray:
    spot = np.asarray(spot, dtype=float)
    strike = np.asarray(strike, dtype=float)
    time_years = np.asarray(time_years, dtype=float)
    sigma = np.asarray(sigma, dtype=float)

    out = np.full(np.broadcast(spot, strike, time_years, sigma).shape, np.nan, dtype=float)
    spot, strike, time_years, sigma = np.broadcast_arrays(spot, strike, time_years, sigma)

    valid = np.isfinite(spot) & np.isfinite(strike) & np.isfinite(time_years) & np.isfinite(sigma) & (spot > 0) & (strike > 0)
    intrinsic = np.maximum(0.0, spot - strike)
    degenerate = valid & ((time_years <= 0) | (sigma <= 0))
    out[degenerate] = intrinsic[degenerate]

    live = valid & (time_years > 0) & (sigma > 0)
    if np.any(live):
        sqrt_t = np.sqrt(time_years[live])
        vol_sqrt_t = sigma[live] * sqrt_t
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            d1 = (np.log(spot[live] / strike[live]) + (rate + 0.5 * sigma[live] ** 2) * time_years[live]) / vol_sqrt_t
            d2 = d1 - vol_sqrt_t
            out[live] = spot[live] * normal_cdf_array(d1) - strike[live] * np.exp(-rate * time_years[live]) * normal_cdf_array(d2)
    return out


def bs_call_vega_array(spot, strike, time_years, sigma) -> np.ndarray:
    spot = np.asarray(spot, dtype=float)
    strike = np.asarray(strike, dtype=float)
    time_years = np.asarray(time_years, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    out = np.zeros(np.broadcast(spot, strike, time_years, sigma).shape, dtype=float)
    spot, strike, time_years, sigma = np.broadcast_arrays(spot, strike, time_years, sigma)
    live = np.isfinite(spot) & np.isfinite(strike) & np.isfinite(time_years) & np.isfinite(sigma) & (spot > 0) & (strike > 0) & (time_years > 0) & (sigma > 0)
    if np.any(live):
        sqrt_t = np.sqrt(time_years[live])
        vol_sqrt_t = sigma[live] * sqrt_t
        with np.errstate(divide="ignore", invalid="ignore"):
            d1 = (np.log(spot[live] / strike[live]) + 0.5 * sigma[live] ** 2 * time_years[live]) / vol_sqrt_t
            out[live] = spot[live] * normal_pdf_array(d1) * sqrt_t
    out[~np.isfinite(out)] = np.nan
    return out


def implied_vol_call_vectorised(price, spot, strike, time_years, rate: float = 0.0, max_vol: float = 5.0, iterations: int = 60) -> np.ndarray:
    """Vectorised bisection inversion for Black-Scholes call IV."""
    price = np.asarray(price, dtype=float)
    spot = np.asarray(spot, dtype=float)
    strike = np.asarray(strike, dtype=float)
    time_years = np.asarray(time_years, dtype=float)
    price, spot, strike, time_years = np.broadcast_arrays(price, spot, strike, time_years)

    iv = np.full(price.shape, np.nan, dtype=float)
    lower = np.maximum(0.0, spot - strike * np.exp(-rate * time_years))
    upper = spot
    valid = (
        np.isfinite(price) & np.isfinite(spot) & np.isfinite(strike) & np.isfinite(time_years)
        & (price >= 0) & (spot > 0) & (strike > 0) & (time_years > 0)
        & (price >= lower - 1e-9) & (price <= upper + 1e-9)
    )
    at_intrinsic = valid & (price <= lower + 1e-9)
    iv[at_intrinsic] = 0.0
    active = valid & ~at_intrinsic
    if not np.any(active):
        return iv

    lo = np.full(price.shape, 1e-9, dtype=float)
    hi = np.full(price.shape, 0.25, dtype=float)

    # Expand upper bound only where needed.
    for _ in range(8):
        model = bs_call_price_array(spot, strike, time_years, hi, rate)
        need = active & (model < price) & (hi < max_vol)
        if not np.any(need):
            break
        hi[need] = np.minimum(max_vol, hi[need] * 2.0)

    model_at_hi = bs_call_price_array(spot, strike, time_years, hi, rate)
    solvable = active & (model_at_hi >= price - 1e-9)
    active = solvable

    for _ in range(iterations):
        mid = 0.5 * (lo + hi)
        model = bs_call_price_array(spot, strike, time_years, mid, rate)
        too_high = active & (model > price)
        too_low = active & ~too_high
        hi[too_high] = mid[too_high]
        lo[too_low] = mid[too_low]

    iv[active] = 0.5 * (lo[active] + hi[active])
    return iv


def robust_polyfit(x: np.ndarray, y: np.ndarray, weights: np.ndarray, method: str) -> np.ndarray:
    mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(weights) & (weights > 0)
    if int(mask.sum()) < 10:
        raise ValueError("Too few valid points for quadratic fit.")
    x = x[mask]
    y = y[mask]
    w = weights[mask]

    if method == "ols":
        return np.polyfit(x, y, 2)
    if method == "weighted":
        return np.polyfit(x, y, 2, w=w)
    if method != "huber":
        raise ValueError(f"Unknown fit method: {method}")

    coeff = np.polyfit(x, y, 2, w=w)
    for _ in range(8):
        residual = y - np.polyval(coeff, x)
        med = np.median(residual)
        mad = np.median(np.abs(residual - med))
        scale = 1.4826 * mad + 1e-12
        huber = np.minimum(1.0, (2.5 * scale) / (np.abs(residual) + 1e-12))
        coeff = np.polyfit(x, y, 2, w=w * huber)
    return coeff


def load_prices(data_dir: Path, days: tuple[int, ...]) -> pd.DataFrame:
    frames = []
    for day in days:
        path = data_dir / f"prices_round_3_day_{day}.csv"
        if not path.exists():
            raise FileNotFoundError(f"Missing price file: {path}")
        frame = pd.read_csv(path, sep=";")
        frame["source_file"] = path.name
        frames.append(frame)
    prices = pd.concat(frames, ignore_index=True)

    required = {
        "day", "timestamp", "product", "bid_price_1", "bid_volume_1", "ask_price_1", "ask_volume_1", "mid_price"
    }
    missing = sorted(required - set(prices.columns))
    if missing:
        raise ValueError(f"Missing required price columns: {missing}")
    return prices


def validate_prices(prices: pd.DataFrame, days: tuple[int, ...]) -> dict:
    out = {"expected_products": sorted(EXPECTED_PRODUCTS), "days": {}, "warnings": []}
    for day in days:
        sub = prices[prices["day"] == day]
        products = set(sub["product"].unique())
        timestamps = np.sort(sub["timestamp"].unique())
        per_ts = sub.groupby("timestamp")["product"].nunique().value_counts().sort_index().to_dict()
        info = {
            "rows": int(len(sub)),
            "timestamp_count": int(len(timestamps)),
            "timestamp_min": int(timestamps[0]) if len(timestamps) else None,
            "timestamp_max": int(timestamps[-1]) if len(timestamps) else None,
            "timestamp_step_100": bool(np.all(np.diff(timestamps) == 100)) if len(timestamps) > 1 else True,
            "products": sorted(products),
            "missing_products": sorted(EXPECTED_PRODUCTS - products),
            "extra_products": sorted(products - EXPECTED_PRODUCTS),
            "duplicate_timestamp_product_rows": int(sub.duplicated(["timestamp", "product"]).sum()),
            "product_count_per_timestamp_distribution": {str(k): int(v) for k, v in per_ts.items()},
        }
        out["days"][str(day)] = info
        if info["rows"] != 120_000:
            out["warnings"].append(f"Day {day}: expected 120,000 rows, got {info['rows']}.")
        if info["timestamp_count"] != 10_000:
            out["warnings"].append(f"Day {day}: expected 10,000 timestamps, got {info['timestamp_count']}.")
        if info["timestamp_min"] != 0 or info["timestamp_max"] != 999900:
            out["warnings"].append(f"Day {day}: unexpected timestamp range {info['timestamp_min']} to {info['timestamp_max']}.")
        if not info["timestamp_step_100"]:
            out["warnings"].append(f"Day {day}: timestamp step is not consistently 100.")
        if info["missing_products"]:
            out["warnings"].append(f"Day {day}: missing products {info['missing_products']}.")
        if info["extra_products"]:
            out["warnings"].append(f"Day {day}: extra products {info['extra_products']}.")
        if info["duplicate_timestamp_product_rows"]:
            out["warnings"].append(f"Day {day}: duplicate timestamp/product rows found.")
    return out


def build_points(prices: pd.DataFrame, rate: float) -> pd.DataFrame:
    prices = prices.copy()
    numeric = ["day", "timestamp", "bid_price_1", "ask_price_1", "bid_volume_1", "ask_volume_1", "mid_price"]
    for col in numeric:
        prices[col] = pd.to_numeric(prices[col], errors="coerce")
    prices["day"] = prices["day"].astype(int)
    prices["timestamp"] = prices["timestamp"].astype(int)

    underlying = prices.loc[prices["product"] == UNDERLYING, ["day", "timestamp", "mid_price"]].rename(columns={"mid_price": "spot"})
    options = prices.loc[prices["product"].str.startswith(VOUCHER_PREFIX, na=False)].copy()
    options["strike"] = options["product"].str.split("_").str[-1].astype(int)
    options = options.rename(columns={"mid_price": "option_mid", "bid_price_1": "bid", "ask_price_1": "ask"})

    df = options.merge(underlying, on=["day", "timestamp"], how="inner", validate="many_to_one")
    df["T_days"] = df["day"].map(START_TTE_DAYS_BY_DAY).astype(float) - df["timestamp"].astype(float) / 1_000_000.0
    df["T"] = df["T_days"] / 365.0
    df["m_t"] = np.log(df["strike"].astype(float) / df["spot"].astype(float)) / np.sqrt(df["T"])
    df["intrinsic"] = np.maximum(0.0, df["spot"] - df["strike"])
    df["extrinsic"] = df["option_mid"] - df["intrinsic"]
    df["spread"] = df["ask"] - df["bid"]
    df["stitched_time"] = df["day"] * 1_000_000 + df["timestamp"]

    df["iv"] = implied_vol_call_vectorised(df["option_mid"].to_numpy(), df["spot"].to_numpy(), df["strike"].to_numpy(), df["T"].to_numpy(), rate=rate)
    df["vega"] = bs_call_vega_array(df["spot"].to_numpy(), df["strike"].to_numpy(), df["T"].to_numpy(), df["iv"].to_numpy())
    return df


def mark_fit_rows(df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    df = df.copy()
    df["is_fit_strike"] = df["strike"].isin(args.fit_strikes)
    df["valid_iv"] = df["iv"].between(args.min_iv, args.max_iv, inclusive="both")
    df["valid_extrinsic"] = df["extrinsic"] >= args.min_extrinsic
    df["valid_vega"] = df["vega"] >= args.min_vega
    df["valid_spread"] = df["spread"] > 0
    df["valid_m"] = np.isfinite(df["m_t"])
    if args.max_abs_m is not None:
        df["valid_m"] &= df["m_t"].abs() <= args.max_abs_m
    df["included_in_fit"] = df["is_fit_strike"] & df["valid_iv"] & df["valid_extrinsic"] & df["valid_vega"] & df["valid_spread"] & df["valid_m"]
    df["fit_reason"] = np.select(
        [
            df["included_in_fit"],
            ~df["is_fit_strike"],
            ~df["valid_iv"],
            ~df["valid_extrinsic"],
            ~df["valid_vega"],
            ~df["valid_spread"],
            ~df["valid_m"],
        ],
        ["included", "strike_not_in_fit_set", "iv_not_invertible_or_out_of_bounds", "low_extrinsic", "low_vega", "bad_spread", "bad_moneyness"],
        default="other",
    )
    return df


def fit_smile(df: pd.DataFrame, y_col: str, method: str) -> np.ndarray:
    clean = df[df["included_in_fit"]]
    if len(clean) < 1000:
        raise ValueError(f"Too few fit rows: {len(clean)}")
    weights = (clean["vega"] / clean["spread"].clip(lower=1.0)).clip(lower=0.05, upper=50.0).to_numpy()
    return robust_polyfit(clean["m_t"].to_numpy(), clean[y_col].to_numpy(), weights, method=method)


def add_models(df: pd.DataFrame, raw_coeff: np.ndarray, adjusted_coeff: np.ndarray, args: argparse.Namespace) -> tuple[pd.DataFrame, dict[int, float]]:
    df = df.copy().sort_values(["strike", "stitched_time"]).reset_index(drop=True)
    df["raw_smile_iv"] = np.polyval(raw_coeff, df["m_t"])
    df["raw_iv_residual"] = df["iv"] - df["raw_smile_iv"]
    static_bias = df[df["included_in_fit"]].groupby("strike")["raw_iv_residual"].median().to_dict()
    static_bias = {int(k): float(v) for k, v in static_bias.items()}
    df["static_strike_bias_iv"] = df["strike"].map(static_bias).fillna(0.0)
    df["static_adjusted_iv"] = df["iv"] - df["static_strike_bias_iv"]
    df["static_adjusted_smile_iv"] = np.polyval(adjusted_coeff, df["m_t"])
    df["static_adjusted_iv_residual"] = df["static_adjusted_iv"] - df["static_adjusted_smile_iv"]

    def past_ewma(series: pd.Series) -> pd.Series:
        return series.shift(1).ewm(span=args.ewma_span, adjust=False, min_periods=args.ewma_min_periods).mean()

    def past_std(series: pd.Series) -> pd.Series:
        return series.shift(1).ewm(span=args.zscore_span, adjust=False, min_periods=args.zscore_min_periods).std(bias=False)

    df["ewma_strike_bias_iv"] = df.groupby("strike", group_keys=False)["raw_iv_residual"].transform(past_ewma).fillna(0.0)
    df["ewma_fair_iv"] = df["raw_smile_iv"] + df["ewma_strike_bias_iv"]
    df["ewma_iv_signal"] = df["raw_iv_residual"] - df["ewma_strike_bias_iv"]

    df["raw_fair_price"] = bs_call_price_array(df["spot"].to_numpy(), df["strike"].to_numpy(), df["T"].to_numpy(), df["raw_smile_iv"].to_numpy(), rate=args.risk_free_rate)
    df["raw_price_deviation"] = df["option_mid"] - df["raw_fair_price"]
    df["ewma_fair_price"] = bs_call_price_array(df["spot"].to_numpy(), df["strike"].to_numpy(), df["T"].to_numpy(), df["ewma_fair_iv"].to_numpy(), rate=args.risk_free_rate)
    df["ewma_price_signal"] = df["option_mid"] - df["ewma_fair_price"]
    df["ewma_price_signal_past_std"] = df.groupby("strike", group_keys=False)["ewma_price_signal"].transform(past_std)
    df["ewma_price_z"] = df["ewma_price_signal"] / df["ewma_price_signal_past_std"].replace(0.0, np.nan)
    return df, static_bias


def add_forward_columns(df: pd.DataFrame, horizons: tuple[int, ...]) -> pd.DataFrame:
    df = df.copy().sort_values(["strike", "stitched_time"]).reset_index(drop=True)
    grouped = df.groupby("strike", group_keys=False)
    for h in horizons:
        df[f"future_mid_h{h}"] = grouped["option_mid"].shift(-h)
        df[f"future_mid_change_h{h}"] = df[f"future_mid_h{h}"] - df["option_mid"]
        df[f"trade_direction_h{h}"] = -np.sign(df["ewma_price_signal"])
        df[f"mid_reversion_pnl_h{h}"] = df[f"trade_direction_h{h}"] * df[f"future_mid_change_h{h}"]
        df[f"mid_reversion_pnl_after_half_spread_h{h}"] = df[f"mid_reversion_pnl_h{h}"] - df["spread"] / 2.0
        df[f"mid_reversion_pnl_after_full_spread_h{h}"] = df[f"mid_reversion_pnl_h{h}"] - df["spread"]
    return df


def safe_float(x) -> float | None:
    try:
        y = float(x)
        if np.isfinite(y):
            return y
    except Exception:
        pass
    return None


def safe_corr(a: pd.Series, b: pd.Series) -> float | None:
    joined = pd.concat([a, b], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(joined) < 3:
        return None
    return safe_float(joined.iloc[:, 0].corr(joined.iloc[:, 1]))


def build_summary(df: pd.DataFrame, validation: dict, raw_coeff: np.ndarray, adjusted_coeff: np.ndarray, static_bias: dict[int, float], args: argparse.Namespace) -> dict:
    clean = df[df["included_in_fit"]]
    by_strike = []
    for strike in sorted(df["strike"].unique()):
        sub = df[df["strike"] == strike]
        fit = sub[sub["included_in_fit"]]
        by_strike.append({
            "strike": int(strike),
            "rows": int(len(sub)),
            "included_rows": int(len(fit)),
            "iv_mean": safe_float(sub["iv"].mean()),
            "iv_p05": safe_float(sub["iv"].quantile(0.05)),
            "iv_p95": safe_float(sub["iv"].quantile(0.95)),
            "m_t_min": safe_float(sub["m_t"].min()),
            "m_t_max": safe_float(sub["m_t"].max()),
            "extrinsic_mean": safe_float(sub["extrinsic"].mean()),
            "spread_mean": safe_float(sub["spread"].mean()),
            "vega_mean": safe_float(sub["vega"].mean()),
            "static_strike_bias_iv": safe_float(static_bias.get(int(strike), 0.0)),
            "raw_price_deviation_mean": safe_float(fit["raw_price_deviation"].mean()) if len(fit) else None,
            "ewma_price_signal_std": safe_float(fit["ewma_price_signal"].std()) if len(fit) else None,
        })

    mean_reversion = []
    for strike in sorted(clean["strike"].unique()):
        sub = clean[clean["strike"] == strike]
        for h in args.forward_horizons:
            mean_reversion.append({
                "strike": int(strike),
                "horizon_ticks": int(h),
                "corr_raw_price_deviation_vs_future_change": safe_corr(sub["raw_price_deviation"], sub[f"future_mid_change_h{h}"]),
                "corr_ewma_price_signal_vs_future_change": safe_corr(sub["ewma_price_signal"], sub[f"future_mid_change_h{h}"]),
                "corr_ewma_price_z_vs_future_change": safe_corr(sub["ewma_price_z"], sub[f"future_mid_change_h{h}"]),
                "interpretation": "negative correlation is directionally consistent with mean reversion",
            })

    ztests = []
    for threshold in args.z_thresholds:
        active_base = clean[np.isfinite(clean["ewma_price_z"]) & (clean["ewma_price_z"].abs() >= threshold)]
        for h in args.forward_horizons:
            active = active_base[np.isfinite(active_base[f"mid_reversion_pnl_h{h}"])]
            if len(active) == 0:
                ztests.append({"z_threshold": float(threshold), "horizon_ticks": int(h), "trades": 0})
                continue
            pnl = active[f"mid_reversion_pnl_h{h}"]
            pnl_half = active[f"mid_reversion_pnl_after_half_spread_h{h}"]
            pnl_full = active[f"mid_reversion_pnl_after_full_spread_h{h}"]
            ztests.append({
                "z_threshold": float(threshold),
                "horizon_ticks": int(h),
                "trades": int(len(active)),
                "mean_mid_pnl": safe_float(pnl.mean()),
                "median_mid_pnl": safe_float(pnl.median()),
                "win_rate_mid": safe_float((pnl > 0).mean()),
                "mean_after_half_spread": safe_float(pnl_half.mean()),
                "mean_after_full_spread": safe_float(pnl_full.mean()),
                "note": "mid-price diagnostic only, not a fill-aware backtest",
            })

    return {
        "what_to_send": {
            "closest_to_2nd_place_published_figure": "01_raw_frankfurt_smile.png",
            "cleanest_visual_after_flattening_lines": "03_binned_static_adjusted_smile.png",
            "exploitation_research": ["05_ewma_price_signal.png", "06_ewma_price_z.png", "08_z_threshold_forward_diagnostics.png"],
        },
        "formulae": {
            "T_days": "start_tte_days_by_day[day] - timestamp / 1_000_000.0",
            "T": "T_days / 365.0",
            "m_t": "log(K / S_t) / sqrt(T)",
            "raw_smile_iv": "a*m_t^2 + b*m_t + c",
            "static_strike_bias_iv": "full-sample median(market_iv - raw_smile_iv) by strike; presentation only",
            "ewma_price_signal": "option_mid - BlackScholesCall(S, K, T, raw_smile_iv + past_only_EWMA_strike_bias)",
        },
        "coefficients": {
            "raw_smile": {"a": float(raw_coeff[0]), "b": float(raw_coeff[1]), "c": float(raw_coeff[2])},
            "static_adjusted_smile": {"a": float(adjusted_coeff[0]), "b": float(adjusted_coeff[1]), "c": float(adjusted_coeff[2])},
        },
        "fit": {
            "method": args.fit_method,
            "fit_strikes": list(map(int, args.fit_strikes)),
            "included_rows": int(df["included_in_fit"].sum()),
            "excluded_rows": int((~df["included_in_fit"]).sum()),
            "fit_reason_counts": {str(k): int(v) for k, v in df["fit_reason"].value_counts().sort_index().to_dict().items()},
        },
        "ewma": {
            "span": args.ewma_span,
            "min_periods": args.ewma_min_periods,
            "zscore_span": args.zscore_span,
            "zscore_min_periods": args.zscore_min_periods,
            "lookahead_safe": True,
            "note": "EWMA and z-score use shift(1), so the current point is not used in its own baseline.",
        },
        "validation": validation,
        "by_strike": by_strike,
        "mean_reversion_by_strike": mean_reversion,
        "z_threshold_forward_tests": ztests,
    }


def write_readme(summary: dict, out_dir: Path) -> None:
    lines = []
    lines.append("Round 3 volatility-smile lab")
    lines.append("=" * 70)
    lines.append("")
    lines.append("Best file to send if he asks for the 2nd-place-style plot:")
    lines.append("  01_raw_frankfurt_smile.png")
    lines.append("")
    lines.append("Best file to send if he asks how to flatten the lines / go further:")
    lines.append("  03_binned_static_adjusted_smile.png")
    lines.append("")
    lines.append("Best files to inspect for exploiting the effect:")
    lines.append("  05_ewma_price_signal.png")
    lines.append("  06_ewma_price_z.png")
    lines.append("  08_z_threshold_forward_diagnostics.png")
    lines.append("")
    lines.append("Core interpretation:")
    lines.append("  Raw smile = published-method recreation.")
    lines.append("  Static strike-bias flattening = cleaner presentation only, not trader-safe.")
    lines.append("  EWMA signal = past-only residual that can be tested/backtested.")
    lines.append("")
    lines.append("Raw smile coefficients iv = a*m_t^2 + b*m_t + c:")
    raw = summary["coefficients"]["raw_smile"]
    lines.append(f"  a = {raw['a']:.12g}")
    lines.append(f"  b = {raw['b']:.12g}")
    lines.append(f"  c = {raw['c']:.12g}")
    lines.append("")
    lines.append("Adjusted presentation smile coefficients:")
    adj = summary["coefficients"]["static_adjusted_smile"]
    lines.append(f"  a = {adj['a']:.12g}")
    lines.append(f"  b = {adj['b']:.12g}")
    lines.append(f"  c = {adj['c']:.12g}")
    lines.append("")
    lines.append("Fit summary:")
    lines.append(f"  method: {summary['fit']['method']}")
    lines.append(f"  fit strikes: {summary['fit']['fit_strikes']}")
    lines.append(f"  included rows: {summary['fit']['included_rows']:,}")
    lines.append(f"  excluded rows: {summary['fit']['excluded_rows']:,}")
    lines.append("  reasons:")
    for key, value in summary["fit"]["fit_reason_counts"].items():
        lines.append(f"    {key}: {value:,}")
    lines.append("")
    lines.append("Per-strike static biases, presentation only:")
    for item in summary["by_strike"]:
        if item["included_rows"]:
            lines.append(f"  {item['strike']}: {item['static_strike_bias_iv']:+.8f}")
    lines.append("")
    lines.append("Mean-reversion diagnostic, EWMA signal vs future mid change:")
    for item in summary["mean_reversion_by_strike"]:
        if item["horizon_ticks"] in (1, 5, 20):
            corr = item["corr_ewma_price_signal_vs_future_change"]
            lines.append(f"  strike={item['strike']} horizon={item['horizon_ticks']}: corr={corr:+.5f}" if corr is not None else f"  strike={item['strike']} horizon={item['horizon_ticks']}: corr=None")
    lines.append("")
    lines.append("Z-threshold mid-price diagnostic:")
    for item in summary["z_threshold_forward_tests"]:
        if item.get("trades", 0):
            lines.append(
                f"  |z|>={item['z_threshold']} h={item['horizon_ticks']}: "
                f"n={item['trades']:,}, mean_mid={item['mean_mid_pnl']:+.5f}, "
                f"win={item['win_rate_mid']:.3f}, after_full_spread={item['mean_after_full_spread']:+.5f}"
            )
    lines.append("")
    if summary["validation"]["warnings"]:
        lines.append("Validation warnings:")
        for warning in summary["validation"]["warnings"]:
            lines.append(f"  - {warning}")
    else:
        lines.append("Validation warnings: none")

def add_curve(ax, coeff: np.ndarray, x_min: float, x_max: float, label: str) -> None:
    xs = np.linspace(x_min, x_max, 500)
    ax.plot(xs, np.polyval(coeff, xs), color="black", linewidth=3, label=label)


def scatter_by_strike(ax, df: pd.DataFrame, x: str, y: str, title: str, ylabel: str, mask: pd.Series | None = None) -> None:
    if mask is not None:
        df = df[mask]
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=[x, y])
    for strike, sub in df.groupby("strike", sort=True):
        ax.scatter(sub[x], sub[y], s=3, alpha=0.35, label=f"strike={int(strike)}")
    ax.set_title(title)
    ax.set_xlabel("m_t = log(K / S_t) / sqrt(T), T in years" if x == "m_t" else x)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.35)
    ax.legend(markerscale=3)


def make_plots(df: pd.DataFrame, raw_coeff: np.ndarray, adjusted_coeff: np.ndarray, summary: dict, out_dir: Path, bins: int) -> None:
    clean = df[df["included_in_fit"]].copy()
    x_min, x_max = float(clean["m_t"].min()), float(clean["m_t"].max())

    fig, ax = plt.subplots(figsize=(14, 8))
    scatter_by_strike(ax, clean, "m_t", "iv", "Raw Frankfurt-style volatility smile: annualised IV vs m_t", "annualised implied volatility")
    add_curve(ax, raw_coeff, x_min, x_max, "fitted parabola")
    ax.legend(markerscale=3)
    fig.tight_layout(); fig.savefig(out_dir / "01_raw_frankfurt_smile.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(14, 8))
    scatter_by_strike(ax, clean, "m_t", "static_adjusted_iv", "Strike-bias-flattened smile: market IV minus full-sample per-strike residual median", "strike-bias-flattened annualised IV")
    add_curve(ax, adjusted_coeff, x_min, x_max, "refit parabola")
    ax.legend(markerscale=3)
    fig.tight_layout(); fig.savefig(out_dir / "02_static_strike_bias_flattened_smile.png", dpi=180); plt.close(fig)

    binned = clean.copy()
    binned["m_bin"] = pd.cut(binned["m_t"], bins=bins)
    b = binned.groupby("m_bin", observed=True).agg(m_t=("m_t", "median"), adjusted_iv=("static_adjusted_iv", "median"), count=("static_adjusted_iv", "size")).reset_index(drop=True)
    b = b[b["count"] >= 10]
    fig, ax = plt.subplots(figsize=(14, 8))
    ax.scatter(b["m_t"], b["adjusted_iv"], s=np.clip(b["count"] / 16.0, 12, 140), alpha=0.75, label="binned median adjusted IV")
    add_curve(ax, adjusted_coeff, x_min, x_max, "refit parabola")
    ax.set_title("Binned median strike-bias-flattened IV")
    ax.set_xlabel("m_t = log(K / S_t) / sqrt(T), T in years")
    ax.set_ylabel("binned median adjusted annualised IV")
    ax.grid(True, alpha=0.35); ax.legend()
    fig.tight_layout(); fig.savefig(out_dir / "03_binned_static_adjusted_smile.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(14, 8))
    for strike, sub in clean.groupby("strike", sort=True):
        ax.scatter(sub["stitched_time"], sub["raw_iv_residual"], s=3, alpha=0.30, label=f"strike={int(strike)}")
    ax.axhline(0, color="black", linewidth=1.5)
    ax.set_title("Raw IV residuals: market IV - global smile IV")
    ax.set_xlabel("stitched time = day * 1,000,000 + timestamp"); ax.set_ylabel("raw IV residual")
    ax.grid(True, alpha=0.35); ax.legend(markerscale=3)
    fig.tight_layout(); fig.savefig(out_dir / "04_raw_iv_residuals.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(14, 8))
    for strike, sub in clean.groupby("strike", sort=True):
        ax.scatter(sub["stitched_time"], sub["ewma_price_signal"], s=3, alpha=0.30, label=f"strike={int(strike)}")
    ax.axhline(0, color="black", linewidth=1.5)
    ax.set_title("Trader-style residual: market mid - past-only EWMA strike-bias fair price")
    ax.set_xlabel("stitched time = day * 1,000,000 + timestamp"); ax.set_ylabel("price signal")
    ax.grid(True, alpha=0.35); ax.legend(markerscale=3)
    fig.tight_layout(); fig.savefig(out_dir / "05_ewma_price_signal.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(14, 8))
    for strike, sub in clean.groupby("strike", sort=True):
        sub = sub[np.isfinite(sub["ewma_price_z"])]
        ax.scatter(sub["stitched_time"], sub["ewma_price_z"], s=3, alpha=0.30, label=f"strike={int(strike)}")
    for level in (-2, -1, 0, 1, 2):
        ax.axhline(level, color="black", linewidth=1.0 if level else 1.5, alpha=0.35 if level else 0.9)
    ax.set_title("Past-only z-score of EWMA price residual")
    ax.set_xlabel("stitched time = day * 1,000,000 + timestamp"); ax.set_ylabel("z-score")
    ax.grid(True, alpha=0.35); ax.legend(markerscale=3)
    fig.tight_layout(); fig.savefig(out_dir / "06_ewma_price_z.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(14, 8))
    excluded = df[~df["included_in_fit"]].replace([np.inf, -np.inf], np.nan).dropna(subset=["m_t", "iv"])
    ax.scatter(excluded["m_t"], excluded["iv"], s=2, alpha=0.16, label="excluded")
    ax.scatter(clean["m_t"], clean["iv"], s=3, alpha=0.35, label="included")
    add_curve(ax, raw_coeff, x_min, x_max, "fitted parabola")
    ax.set_title("Filter audit: central fit set versus excluded extreme/unstable strikes")
    ax.set_xlabel("m_t = log(K / S_t) / sqrt(T), T in years"); ax.set_ylabel("annualised implied volatility")
    ax.grid(True, alpha=0.35); ax.legend()
    fig.tight_layout(); fig.savefig(out_dir / "07_filter_audit.png", dpi=180); plt.close(fig)

    q = pd.DataFrame(summary["z_threshold_forward_tests"])
    if not q.empty and "trades" in q:
        q = q[q["trades"] > 0].copy()
    if not q.empty:
        fig, ax = plt.subplots(figsize=(12, 7))
        labels = [f"|z|>={r.z_threshold:g}\nh={r.horizon_ticks}\nn={int(r.trades)}" for r in q.itertuples(index=False)]
        values = [float(r.mean_mid_pnl) for r in q.itertuples(index=False)]
        wins = [float(r.win_rate_mid) for r in q.itertuples(index=False)]
        pos = np.arange(len(values))
        bars = ax.bar(pos, values)
        ax.axhline(0, color="black", linewidth=1)
        ax.set_xticks(pos); ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.set_title("Mid-price mean-reversion diagnostic by z-threshold")
        ax.set_ylabel("mean mid-price PnL over horizon")
        ax.grid(True, axis="y", alpha=0.35)
        for bar, win_rate in zip(bars, wins):
            y = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, y, f"win {win_rate:.2f}", ha="center", va="bottom" if y >= 0 else "top", fontsize=8)
        fig.tight_layout(); fig.savefig(out_dir / "08_z_threshold_forward_diagnostics.png", dpi=180); plt.close(fig)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Round 3 volatility-smile perfect lab")
    p.add_argument("--data-dir", type=Path, default=Path("data/round3"))
    p.add_argument("--out-dir", type=Path, default=Path("r3_smile_perfect"))
    p.add_argument("--days", type=parse_int_tuple, default=DEFAULT_DAYS)
    p.add_argument("--fit-strikes", type=parse_int_tuple, default=DEFAULT_FIT_STRIKES)
    p.add_argument("--fit-method", choices=("ols", "weighted", "huber"), default="huber")
    p.add_argument("--risk-free-rate", type=float, default=0.0)
    p.add_argument("--min-extrinsic", type=float, default=1.0)
    p.add_argument("--min-vega", type=float, default=1e-6)
    p.add_argument("--min-iv", type=float, default=0.01)
    p.add_argument("--max-iv", type=float, default=3.0)
    p.add_argument("--max-abs-m", type=float, default=None)
    p.add_argument("--ewma-span", type=int, default=150)
    p.add_argument("--ewma-min-periods", type=int, default=20)
    p.add_argument("--zscore-span", type=int, default=300)
    p.add_argument("--zscore-min-periods", type=int, default=50)
    p.add_argument("--forward-horizons", type=parse_int_tuple, default=(1, 5, 20, 50))
    p.add_argument("--z-thresholds", type=parse_float_tuple, default=(1.0, 1.5, 2.0))
    p.add_argument("--bins", type=int, default=90)
    p.add_argument("--max-rows-csv", type=int, default=0, help="0 writes all rows; otherwise writes only this many rows to smile_points_perfect.csv")
    return p


def main() -> int:
    args = build_parser().parse_args()
    args.days = tuple(int(x) for x in args.days)
    args.fit_strikes = tuple(int(x) for x in args.fit_strikes)
    args.forward_horizons = tuple(int(x) for x in args.forward_horizons)
    args.z_thresholds = tuple(float(x) for x in args.z_thresholds)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    prices = load_prices(args.data_dir, args.days)
    validation = validate_prices(prices, args.days)
    points = build_points(prices, args.risk_free_rate)
    points = mark_fit_rows(points, args)

    raw_coeff = fit_smile(points, "iv", args.fit_method)
    tmp = points.copy()
    tmp["raw_smile_iv"] = np.polyval(raw_coeff, tmp["m_t"])
    tmp["raw_iv_residual"] = tmp["iv"] - tmp["raw_smile_iv"]
    static_bias_for_fit = tmp[tmp["included_in_fit"]].groupby("strike")["raw_iv_residual"].median().to_dict()
    tmp["static_adjusted_iv"] = tmp["iv"] - tmp["strike"].map(static_bias_for_fit).fillna(0.0)
    adjusted_coeff = fit_smile(tmp, "static_adjusted_iv", args.fit_method)

    points, static_bias = add_models(points, raw_coeff, adjusted_coeff, args)
    points = add_forward_columns(points, args.forward_horizons)
    summary = build_summary(points, validation, raw_coeff, adjusted_coeff, static_bias, args)

    if args.max_rows_csv and args.max_rows_csv > 0 and len(points) > args.max_rows_csv:
        points.iloc[: args.max_rows_csv].to_csv(args.out_dir / "smile_points_perfect_sample.csv", index=False)
    else:
        points.to_csv(args.out_dir / "smile_points_perfect.csv", index=False)
    with (args.out_dir / "perfect_smile_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    write_readme(summary, args.out_dir)
    make_plots(points, raw_coeff, adjusted_coeff, summary, args.out_dir, args.bins)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
