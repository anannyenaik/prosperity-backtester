"""
Dashboard bundle builder.

Takes a list of SessionResults from the engine and produces:
  1. dashboard.json - aggregate statistics, histograms, top/bottom sessions
  2. sample_paths/*.json - per-tick traces for the sample-session runs
  3. session_summary.csv - machine-readable per-session row

The JSON schema matches (a subset of) the original Prosperity 4 dashboard so the
same visualizer logic can read both.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any, Dict, List

from .engine import SessionResult
from .simulate import PRODUCTS


# ──────────────────────── statistical helpers ──────────────────────── #

def quantile(values: List[float], q: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    idx = (len(s) - 1) * q
    lo, hi = math.floor(idx), math.ceil(idx)
    if lo == hi:
        return s[lo]
    w = idx - lo
    return s[lo] * (1.0 - w) + s[hi] * w


def sample_std(v: List[float]) -> float:
    if len(v) < 2:
        return 0.0
    return statistics.stdev(v)


def downside_deviation(v: List[float]) -> float:
    ds = [min(x, 0.0) ** 2 for x in v]
    if not ds:
        return 0.0
    return math.sqrt(sum(ds) / len(ds))


def skewness(v: List[float]) -> float:
    if len(v) < 3:
        return 0.0
    m = statistics.fmean(v)
    s = sample_std(v)
    if s == 0:
        return 0.0
    return sum(((x - m) / s) ** 3 for x in v) / len(v)


def correlation(a: List[float], b: List[float]) -> float:
    if len(a) != len(b) or len(a) < 2:
        return 0.0
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    sa, sb = sample_std(a), sample_std(b)
    if sa == 0 or sb == 0:
        return 0.0
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (len(a) - 1)
    return cov / (sa * sb)


def summarize_distribution(values: List[float]) -> Dict[str, float]:
    if not values:
        return {}
    mean = statistics.fmean(values)
    std = sample_std(values)
    down = downside_deviation(values)
    q01 = quantile(values, 0.01)
    q05 = quantile(values, 0.05)
    tail5 = [v for v in values if v <= q05] or [min(values)]
    tail1 = [v for v in values if v <= q01] or [min(values)]
    ci = 1.96 * std / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return {
        "count": float(len(values)),
        "mean": mean,
        "std": std,
        "min": min(values),
        "p01": q01, "p05": q05,
        "p10": quantile(values, 0.10),
        "p25": quantile(values, 0.25),
        "p50": quantile(values, 0.50),
        "p75": quantile(values, 0.75),
        "p90": quantile(values, 0.90),
        "p95": quantile(values, 0.95),
        "p99": quantile(values, 0.99),
        "max": max(values),
        "positiveRate": sum(1 for x in values if x > 0) / len(values),
        "negativeRate": sum(1 for x in values if x < 0) / len(values),
        "zeroRate": sum(1 for x in values if x == 0) / len(values),
        "var95": q05,
        "cvar95": statistics.fmean(tail5),
        "var99": q01,
        "cvar99": statistics.fmean(tail1),
        "meanConfidenceLow95": mean - ci,
        "meanConfidenceHigh95": mean + ci,
        "sharpeLike": mean / std if std > 0 else 0.0,
        "sortinoLike": mean / down if down > 0 else 0.0,
        "skewness": skewness(values),
    }


def histogram(values: List[float], bins: int = 40) -> Dict[str, List[float]]:
    if not values:
        return {"binEdges": [], "counts": []}
    lo, hi = min(values), max(values)
    if lo == hi:
        lo -= 0.5; hi += 0.5
    w = (hi - lo) / bins
    edges = [lo + i * w for i in range(bins + 1)]
    counts = [0] * bins
    for v in values:
        idx = min(int((v - lo) / w), bins - 1)
        counts[idx] += 1
    return {"binEdges": edges, "counts": counts}


def normal_pdf(x: float, mu: float, sigma: float) -> float:
    if sigma <= 0:
        return 0.0
    z = (x - mu) / sigma
    return math.exp(-0.5 * z * z) / (sigma * math.sqrt(2.0 * math.pi))


def normal_fit(values: List[float], bins: int = 40, points: int = 200) -> Dict[str, Any]:
    if not values:
        return {"mean": 0, "std": 0, "r2": 0, "line": []}
    h = histogram(values, bins)
    mu = statistics.fmean(values)
    sigma = sample_std(values)
    edges = h["binEdges"]
    counts = h["counts"]
    if len(edges) < 2:
        return {"mean": mu, "std": sigma, "r2": 0, "line": []}
    bw = float(edges[1] - edges[0])
    centers = [(edges[i] + edges[i + 1]) / 2.0 for i in range(len(counts))]
    expected = [normal_pdf(c, mu, sigma) * len(values) * bw for c in centers]
    # R² vs expected
    amean = statistics.fmean(counts)
    sst = sum((c - amean) ** 2 for c in counts)
    sse = sum((a - b) ** 2 for a, b in zip(counts, expected))
    r2 = 0.0 if sst <= 1e-12 else max(0.0, 1.0 - sse / sst)
    lo, hi = float(edges[0]), float(edges[-1])
    line = []
    for i in range(points):
        x = lo + (hi - lo) * i / (points - 1)
        y = normal_pdf(x, mu, sigma) * len(values) * bw
        line.append([x, y])
    return {"mean": mu, "std": sigma, "r2": r2, "line": line}


def linear_regression(x: List[float], y: List[float]) -> Dict[str, Any]:
    if len(x) != len(y) or len(x) < 2:
        return {"slope": 0.0, "intercept": 0.0, "r2": 0.0, "correlation": 0.0,
                "line": [], "diagnosis": "insufficient data"}
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sxx = sum((v - mx) ** 2 for v in x)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    slope = sxy / sxx if sxx > 1e-12 else 0.0
    intercept = my - slope * mx
    c = correlation(x, y)
    r2 = c * c
    xmin, xmax = min(x), max(x)
    line = [[xmin, intercept + slope * xmin], [xmax, intercept + slope * xmax]]
    strength = abs(c)
    if strength < 0.1: diag = "no meaningful correlation"
    elif strength < 0.3: diag = "weak correlation"
    elif strength < 0.6: diag = "moderate correlation"
    else: diag = "strong correlation"
    return {"slope": slope, "intercept": intercept, "r2": r2, "correlation": c,
            "line": line, "diagnosis": diag}


# ──────────────────────── dashboard builder ──────────────────────── #

def build_dashboard(results: List[SessionResult], algorithm_path: str,
                    meta: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregate session results into the dashboard JSON format."""
    total_pnls = [r.total_pnl for r in results]
    osmium_pnls = [r.per_product_pnl["ASH_COATED_OSMIUM"] for r in results]
    pepper_pnls = [r.per_product_pnl["INTARIAN_PEPPER_ROOT"] for r in results]
    osmium_pos = [float(r.per_product_final_position["ASH_COATED_OSMIUM"]) for r in results]
    pepper_pos = [float(r.per_product_final_position["INTARIAN_PEPPER_ROOT"]) for r in results]
    osmium_cash = [r.per_product_cash["ASH_COATED_OSMIUM"] for r in results]
    pepper_cash = [r.per_product_cash["INTARIAN_PEPPER_ROOT"] for r in results]

    total_slope = [r.total_slope_per_step for r in results]
    total_r2 = [r.total_r2 for r in results]
    osmium_slope = [r.per_product_slope_per_step["ASH_COATED_OSMIUM"] for r in results]
    osmium_r2 = [r.per_product_r2["ASH_COATED_OSMIUM"] for r in results]
    pepper_slope = [r.per_product_slope_per_step["INTARIAN_PEPPER_ROOT"] for r in results]
    pepper_r2 = [r.per_product_r2["INTARIAN_PEPPER_ROOT"] for r in results]

    # Ranked sessions (stored as plain-dict rows for the dashboard)
    rows = []
    for r in results:
        rows.append({
            "sessionId": r.session_id,
            "totalPnl": r.total_pnl,
            "osmiumPnl": r.per_product_pnl["ASH_COATED_OSMIUM"],
            "pepperPnl": r.per_product_pnl["INTARIAN_PEPPER_ROOT"],
            "osmiumPosition": r.per_product_final_position["ASH_COATED_OSMIUM"],
            "pepperPosition": r.per_product_final_position["INTARIAN_PEPPER_ROOT"],
            "osmiumCash": r.per_product_cash["ASH_COATED_OSMIUM"],
            "pepperCash": r.per_product_cash["INTARIAN_PEPPER_ROOT"],
            "totalSlopePerStep": r.total_slope_per_step,
            "totalR2": r.total_r2,
        })
    top = sorted(rows, key=lambda r: r["totalPnl"], reverse=True)[:10]
    bottom = sorted(rows, key=lambda r: r["totalPnl"])[:10]

    return {
        "kind": "round1_monte_carlo_dashboard",
        "meta": {
            "algorithmPath": str(algorithm_path),
            "sessionCount": len(results),
            **meta,
        },
        "overall": {
            "totalPnl": summarize_distribution(total_pnls),
            "osmiumPnl": summarize_distribution(osmium_pnls),
            "pepperPnl": summarize_distribution(pepper_pnls),
            "osmiumPepperCorrelation": correlation(osmium_pnls, pepper_pnls),
        },
        "trendFits": {
            "TOTAL": {
                "profitability": summarize_distribution(total_slope),
                "stability": summarize_distribution(total_r2),
            },
            "ASH_COATED_OSMIUM": {
                "profitability": summarize_distribution(osmium_slope),
                "stability": summarize_distribution(osmium_r2),
            },
            "INTARIAN_PEPPER_ROOT": {
                "profitability": summarize_distribution(pepper_slope),
                "stability": summarize_distribution(pepper_r2),
            },
        },
        "normalFits": {
            "totalPnl": normal_fit(total_pnls),
            "osmiumPnl": normal_fit(osmium_pnls),
            "pepperPnl": normal_fit(pepper_pnls),
        },
        "scatterFit": linear_regression(osmium_pnls, pepper_pnls),
        "generatorModel": {
            "ASH_COATED_OSMIUM": {
                "name": "Stationary Latent Fair",
                "formula": "x_{t+1} = x_t - κ·(x_t - 10000) + ε_t",
                "notes": ["Mean-reverting toward 10000",
                          "Bot quotes centered on round(x_t) with empirical spreads"],
            },
            "INTARIAN_PEPPER_ROOT": {
                "name": "Linear Drift + Noise",
                "formula": "x_{t+1} = x_t + μ + ε_t,  μ ≈ +0.108/tick",
                "notes": ["Deterministic upward drift across all observed days",
                          "Small residual noise (σ ≈ 1.2)"],
            },
        },
        "products": {
            "ASH_COATED_OSMIUM": {
                "pnl": summarize_distribution(osmium_pnls),
                "finalPosition": summarize_distribution(osmium_pos),
                "cash": summarize_distribution(osmium_cash),
            },
            "INTARIAN_PEPPER_ROOT": {
                "pnl": summarize_distribution(pepper_pnls),
                "finalPosition": summarize_distribution(pepper_pos),
                "cash": summarize_distribution(pepper_cash),
            },
        },
        "histograms": {
            "totalPnl": histogram(total_pnls),
            "osmiumPnl": histogram(osmium_pnls),
            "pepperPnl": histogram(pepper_pnls),
            "totalProfitability": histogram(total_slope),
            "totalStability": histogram(total_r2),
            "osmiumProfitability": histogram(osmium_slope),
            "osmiumStability": histogram(osmium_r2),
            "pepperProfitability": histogram(pepper_slope),
            "pepperStability": histogram(pepper_r2),
        },
        "sessions": rows,
        "topSessions": top,
        "bottomSessions": bottom,
    }


def write_session_summary_csv(path: Path, results: List[SessionResult]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "session_id", "total_pnl",
            "osmium_pnl", "pepper_pnl",
            "osmium_position", "pepper_position",
            "osmium_cash", "pepper_cash",
            "total_slope_per_step", "total_r2",
            "osmium_slope_per_step", "osmium_r2",
            "pepper_slope_per_step", "pepper_r2",
        ])
        for r in results:
            w.writerow([
                r.session_id, f"{r.total_pnl:.4f}",
                f"{r.per_product_pnl['ASH_COATED_OSMIUM']:.4f}",
                f"{r.per_product_pnl['INTARIAN_PEPPER_ROOT']:.4f}",
                r.per_product_final_position["ASH_COATED_OSMIUM"],
                r.per_product_final_position["INTARIAN_PEPPER_ROOT"],
                f"{r.per_product_cash['ASH_COATED_OSMIUM']:.4f}",
                f"{r.per_product_cash['INTARIAN_PEPPER_ROOT']:.4f}",
                f"{r.total_slope_per_step:.6f}", f"{r.total_r2:.6f}",
                f"{r.per_product_slope_per_step['ASH_COATED_OSMIUM']:.6f}",
                f"{r.per_product_r2['ASH_COATED_OSMIUM']:.6f}",
                f"{r.per_product_slope_per_step['INTARIAN_PEPPER_ROOT']:.6f}",
                f"{r.per_product_r2['INTARIAN_PEPPER_ROOT']:.6f}",
            ])


def write_sample_paths(dir_path: Path, results: List[SessionResult],
                       max_points: int = 1500):
    """Persist per-tick traces for sample sessions (downsampled)."""
    dir_path.mkdir(parents=True, exist_ok=True)

    for r in results:
        if not r.traces:
            continue
        session_out: Dict[str, Any] = {"sessionId": r.session_id, "products": {}, "total": {}}
        timestamps = None
        total_mtm = None
        for p, trace_list in r.traces.items():
            n = len(trace_list)
            if n == 0:
                continue
            # Downsample evenly
            stride = max(1, n // max_points)
            indices = list(range(0, n, stride))
            if indices[-1] != n - 1:
                indices.append(n - 1)
            ts = [trace_list[i].timestamp for i in indices]
            fair = [trace_list[i].fair for i in indices]
            pos = [trace_list[i].position[p] for i in indices]
            cash = [trace_list[i].cash[p] for i in indices]
            mtm = [trace_list[i].mtm[p] for i in indices]
            session_out["products"][p] = {
                "timestamps": ts, "fair": fair, "position": pos, "cash": cash, "mtmPnl": mtm,
            }
            if timestamps is None:
                timestamps = ts
                total_mtm = mtm.copy()
            else:
                for i, v in enumerate(mtm):
                    if i < len(total_mtm):
                        total_mtm[i] += v
        if timestamps is not None:
            session_out["total"] = {"timestamps": timestamps, "mtmPnl": total_mtm}
        with open(dir_path / f"session_{r.session_id:05d}.json", "w", encoding="utf-8") as f:
            json.dump(session_out, f, separators=(",", ":"))
