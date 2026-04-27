from __future__ import annotations

import csv
import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence

from .dataset import DayDataset, load_round_dataset
from .metadata import get_round_spec


EXPECTED_R4_TRADE_ROWS = {1: 1407, 2: 1333, 3: 1541}


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    idx = max(0.0, min(1.0, float(q))) * (len(ordered) - 1)
    lo = int(idx)
    hi = min(len(ordered) - 1, lo + 1)
    weight = idx - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def _summary(values: Sequence[float]) -> Dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "p05": None, "p50": None, "mean": None, "p95": None, "max": None}
    return {
        "count": len(values),
        "min": min(values),
        "p05": _quantile(values, 0.05),
        "p50": _quantile(values, 0.50),
        "mean": statistics.fmean(values),
        "p95": _quantile(values, 0.95),
        "max": max(values),
    }


def _file_hashes(data_dir: Path, days: Sequence[int]) -> Dict[str, Dict[str, object]]:
    spec = get_round_spec(4)
    hashes: Dict[str, Dict[str, object]] = {}
    for day in days:
        for kind in ("prices", "trades"):
            path = data_dir / f"{kind}_round_{spec.round_number}_day_{int(day)}.csv"
            if not path.is_file():
                hashes[path.name] = {"exists": False}
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            hashes[path.name] = {"exists": True, "size_bytes": path.stat().st_size, "sha256": digest}
    return hashes


def _combined_hash(file_hashes: Mapping[str, Mapping[str, object]]) -> str:
    h = hashlib.sha256()
    for name in sorted(file_hashes):
        row = file_hashes[name]
        h.update(name.encode("utf-8"))
        h.update(str(row.get("sha256", "missing")).encode("utf-8"))
    return h.hexdigest()


def _trade_counterparties(day_dataset: DayDataset) -> tuple[Dict[str, object], List[Dict[str, object]]]:
    day_names = set()
    by_product: Dict[str, Dict[str, object]] = {}
    rows: List[Dict[str, object]] = []
    for timestamp in day_dataset.timestamps:
        for product, trades in day_dataset.trades_by_timestamp.get(timestamp, {}).items():
            bucket = by_product.setdefault(
                product,
                {
                    "trade_rows": 0,
                    "counterparties": set(),
                    "buyers": {},
                    "sellers": {},
                },
            )
            for trade in trades:
                bucket["trade_rows"] = int(bucket["trade_rows"]) + 1
                for field_name in ("buyer", "seller"):
                    name = str(getattr(trade, field_name) or "")
                    if not name:
                        continue
                    day_names.add(name)
                    bucket["counterparties"].add(name)
                    counts = bucket[f"{field_name}s"]
                    counts[name] = int(counts.get(name, 0)) + 1
    for product in sorted(by_product):
        bucket = by_product[product]
        rows.append(
            {
                "day": day_dataset.day,
                "product": product,
                "trade_rows": bucket["trade_rows"],
                "counterparties": ",".join(sorted(bucket["counterparties"])),
                "buyer_counts": json.dumps(bucket["buyers"], sort_keys=True),
                "seller_counts": json.dumps(bucket["sellers"], sort_keys=True),
            }
        )
    return {
        "counterparties": sorted(day_names),
        "counterparty_count": len(day_names),
        "by_product": {
            product: {
                "trade_rows": int(bucket["trade_rows"]),
                "counterparties": sorted(bucket["counterparties"]),
                "buyer_counts": dict(sorted(bucket["buyers"].items())),
                "seller_counts": dict(sorted(bucket["sellers"].items())),
            }
            for product, bucket in sorted(by_product.items())
        },
    }, rows


def _spread_depth_rows(day_dataset: DayDataset) -> tuple[Dict[str, object], List[Dict[str, object]]]:
    spread_by_product: Dict[str, List[float]] = {product: [] for product in day_dataset.products}
    bid_depth_by_product: Dict[str, List[float]] = {product: [] for product in day_dataset.products}
    ask_depth_by_product: Dict[str, List[float]] = {product: [] for product in day_dataset.products}
    total_depth_by_product: Dict[str, List[float]] = {product: [] for product in day_dataset.products}
    for timestamp in day_dataset.timestamps:
        for product, snapshot in day_dataset.books_by_timestamp.get(timestamp, {}).items():
            if snapshot.bids and snapshot.asks:
                spread_by_product.setdefault(product, []).append(float(snapshot.asks[0][0] - snapshot.bids[0][0]))
            bid_depth = sum(volume for _price, volume in snapshot.bids)
            ask_depth = sum(volume for _price, volume in snapshot.asks)
            bid_depth_by_product.setdefault(product, []).append(float(bid_depth))
            ask_depth_by_product.setdefault(product, []).append(float(ask_depth))
            total_depth_by_product.setdefault(product, []).append(float(bid_depth + ask_depth))

    rows: List[Dict[str, object]] = []
    by_product: Dict[str, object] = {}
    for product in sorted(day_dataset.products):
        product_payload = {
            "spread": _summary(spread_by_product.get(product, [])),
            "bid_depth": _summary(bid_depth_by_product.get(product, [])),
            "ask_depth": _summary(ask_depth_by_product.get(product, [])),
            "total_depth": _summary(total_depth_by_product.get(product, [])),
        }
        by_product[product] = product_payload
        for metric, summary in product_payload.items():
            rows.append({"day": day_dataset.day, "product": product, "metric": metric, **summary})
    day_payload = {
        "spread": _summary([value for values in spread_by_product.values() for value in values]),
        "bid_depth": _summary([value for values in bid_depth_by_product.values() for value in values]),
        "ask_depth": _summary([value for values in ask_depth_by_product.values() for value in values]),
        "total_depth": _summary([value for values in total_depth_by_product.values() for value in values]),
        "by_product": by_product,
    }
    return day_payload, rows


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: List[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(str(key))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _status_for_day(day_dataset: DayDataset) -> tuple[str, List[str]]:
    spec = get_round_spec(4)
    validation = dict(day_dataset.validation)
    issues: List[str] = []
    expected_trade_rows = EXPECTED_R4_TRADE_ROWS.get(int(day_dataset.day))
    if validation.get("price_rows") != spec.ticks_per_day * len(spec.products):
        issues.append("price row count mismatch")
    if expected_trade_rows is not None and validation.get("trade_rows") != expected_trade_rows:
        issues.append("trade row count mismatch")
    if validation.get("timestamps") != spec.ticks_per_day:
        issues.append("timestamp count mismatch")
    if validation.get("timestamp_min") != 0 or validation.get("timestamp_max") != 999900:
        issues.append("timestamp range mismatch")
    if not validation.get("timestamp_step_ok"):
        issues.append("timestamp step mismatch")
    if validation.get("products_seen") != list(spec.products):
        issues.append("product set mismatch")
    for field_name in (
        "duplicate_book_rows",
        "crossed_book_rows",
        "trade_rows_unknown_symbol",
        "trade_rows_unknown_timestamp",
        "trade_rows_invalid_currency",
        "trade_rows_invalid_quantity",
        "negative_price_levels",
        "zero_or_negative_mid_rows",
    ):
        if int(validation.get(field_name) or 0) != 0:
            issues.append(f"{field_name}={validation.get(field_name)}")
    if validation.get("missing_products"):
        issues.append(f"missing timestamp-product rows={len(validation.get('missing_products') or {})}")
    return ("pass" if not issues else "fail"), issues


def render_manifest_markdown(report: Mapping[str, object]) -> str:
    lines = [
        "# Round 4 Data Manifest",
        "",
        f"- Generated at: `{report.get('generated_at')}`",
        f"- Data hash: `{report.get('data_hash')}`",
        f"- Status: **{report.get('status')}**",
        "",
        "| Day | Status | Price rows | Trade rows | Timestamps | Issues |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for day in report.get("days", []):
        issues = ", ".join(day.get("issues") or [])
        lines.append(
            f"| {day.get('day')} | {day.get('status')} | {day.get('price_rows')} | "
            f"{day.get('trade_rows')} | {day.get('timestamps')} | {issues} |"
        )
    lines.extend(
        [
            "",
            "Notes:",
            "- Buyer and seller fields are retained as counterparty metadata.",
            "- Counterparty names are not treated as aggressor-side proof.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def build_round4_manifest(
    *,
    data_dir: Path,
    output_dir: Path,
    days: Iterable[int] = (1, 2, 3),
    permissive: bool = False,
) -> Dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    spec = get_round_spec(4)
    day_tuple = tuple(int(day) for day in days)
    generated_at = datetime.now(timezone.utc).isoformat()
    file_hashes = _file_hashes(data_dir, day_tuple)
    try:
        dataset_map = load_round_dataset(data_dir, day_tuple, round_number=4, round_spec=spec)
    except Exception as exc:
        report = {
            "generated_at": generated_at,
            "status": "fail",
            "schema_status": "permissive_error_recorded" if permissive else "strict_error",
            "error": str(exc),
            "round": 4,
            "data_dir": str(data_dir),
            "days_requested": list(day_tuple),
            "file_hashes": file_hashes,
            "data_hash": _combined_hash(file_hashes),
        }
        (output_dir / "manifest_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (output_dir / "manifest_report.md").write_text(render_manifest_markdown(report), encoding="utf-8")
        if permissive:
            return report
        raise

    day_reports: List[Dict[str, object]] = []
    spread_rows: List[Dict[str, object]] = []
    counterparty_rows: List[Dict[str, object]] = []
    all_issues: List[str] = []
    for day in day_tuple:
        day_dataset = dataset_map[day]
        status, issues = _status_for_day(day_dataset)
        all_issues.extend(f"day {day}: {issue}" for issue in issues)
        validation = dict(day_dataset.validation)
        counterparties, product_counterparty_rows = _trade_counterparties(day_dataset)
        spread_depth, product_spread_rows = _spread_depth_rows(day_dataset)
        counterparty_rows.extend(product_counterparty_rows)
        spread_rows.extend(product_spread_rows)
        day_reports.append(
            {
                "day": day,
                "status": status,
                "issues": issues,
                "products_present": validation.get("products_seen"),
                "expected_products": list(spec.products),
                "timestamps": validation.get("timestamps"),
                "price_rows": validation.get("price_rows"),
                "trade_rows": validation.get("trade_rows"),
                "counterparties": counterparties,
                "missing_timestamp_product_rows": len(validation.get("missing_products") or {}),
                "duplicate_timestamp_product_rows": validation.get("duplicate_book_rows"),
                "crossed_book_rows": validation.get("crossed_book_rows"),
                "empty_book_rows": validation.get("empty_book_rows"),
                "one_sided_book_rows": validation.get("one_sided_book_rows"),
                "zero_or_negative_price_levels": validation.get("zero_or_negative_price_levels"),
                "zero_price_levels": validation.get("zero_price_levels"),
                "negative_price_levels": validation.get("negative_price_levels"),
                "zero_or_negative_mid_rows": validation.get("zero_or_negative_mid_rows"),
                "trade_rows_unknown_symbol": validation.get("trade_rows_unknown_symbol"),
                "trade_rows_unknown_timestamp": validation.get("trade_rows_unknown_timestamp"),
                "trade_rows_invalid_currency": validation.get("trade_rows_invalid_currency"),
                "trade_rows_invalid_quantity": validation.get("trade_rows_invalid_quantity"),
                "spread_depth_summary": spread_depth,
            }
        )

    report = {
        "generated_at": generated_at,
        "status": "pass" if not all_issues else "fail",
        "round": 4,
        "round_name": spec.name,
        "data_dir": str(data_dir),
        "days_present": list(day_tuple),
        "products_expected": list(spec.products),
        "position_limits": {product: meta.position_limit for product, meta in spec.product_metadata.items()},
        "currency": spec.currency,
        "timestamp_step": spec.timestamp_step,
        "ticks_per_day": spec.ticks_per_day,
        "expected_trade_rows": EXPECTED_R4_TRADE_ROWS,
        "days": day_reports,
        "file_hashes": file_hashes,
        "data_hash": _combined_hash(file_hashes),
        "schema_status": "strict",
        "permissive": bool(permissive),
        "issues": all_issues,
        "artefacts": {
            "json": "manifest_report.json",
            "markdown": "manifest_report.md",
            "spread_depth_csv": "spread_depth_summary.csv",
            "counterparty_csv": "counterparties_by_product.csv",
        },
    }
    (output_dir / "manifest_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (output_dir / "manifest_report.md").write_text(render_manifest_markdown(report), encoding="utf-8")
    _write_csv(output_dir / "spread_depth_summary.csv", spread_rows)
    _write_csv(output_dir / "counterparties_by_product.csv", counterparty_rows)
    return report
