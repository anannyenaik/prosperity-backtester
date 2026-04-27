from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .metadata import RoundSpec, get_round_spec, products_for_round


PRICE_SCHEMA = [
    "day", "timestamp", "product",
    "bid_price_1", "bid_volume_1", "bid_price_2", "bid_volume_2", "bid_price_3", "bid_volume_3",
    "ask_price_1", "ask_volume_1", "ask_price_2", "ask_volume_2", "ask_price_3", "ask_volume_3",
    "mid_price", "profit_and_loss",
]
TRADE_SCHEMA = ["timestamp", "buyer", "seller", "symbol", "currency", "price", "quantity"]


@dataclass
class TradePrint:
    timestamp: int
    buyer: str
    seller: str
    symbol: str
    price: float
    quantity: int
    synthetic: bool = False


@dataclass
class BookSnapshot:
    timestamp: int
    product: str
    bids: List[Tuple[int, int]]
    asks: List[Tuple[int, int]]
    mid: Optional[float]
    reference_fair: Optional[float] = None
    source_day: Optional[int] = None

    def microprice(self) -> Optional[float]:
        if not self.bids or not self.asks:
            return self.mid
        best_bid, bid_vol = self.bids[0]
        best_ask, ask_vol = self.asks[0]
        total = bid_vol + ask_vol
        if total <= 0:
            return (best_bid + best_ask) / 2.0
        return (best_ask * bid_vol + best_bid * ask_vol) / total


@dataclass
class DayDataset:
    day: int
    timestamps: List[int]
    books_by_timestamp: Dict[int, Dict[str, BookSnapshot]]
    trades_by_timestamp: Dict[int, Dict[str, List[TradePrint]]]
    validation: Dict[str, object] = field(default_factory=dict)
    metadata: Dict[str, object] = field(default_factory=dict)
    round_number: int = 1
    products: Tuple[str, ...] = ()


@dataclass
class ValidationReport:
    price_rows: int
    expected_price_rows: int
    trade_rows: int
    timestamps: int
    expected_timestamps: int
    timestamp_min: int | None
    timestamp_max: int | None
    timestamp_step_ok: bool
    missing_products: Dict[int, List[str]]
    duplicate_book_rows: int
    empty_book_rows: int
    one_sided_book_rows: int
    crossed_book_rows: int
    products_seen: List[str]
    exact_product_match: bool
    products_per_timestamp_expected: int
    trade_rows_unknown_symbol: int
    trade_rows_unknown_timestamp: int
    trade_rows_invalid_currency: int
    trade_rows_invalid_quantity: int
    price_level_parse_errors: int
    volume_parse_errors: int
    zero_price_levels: int
    negative_price_levels: int
    zero_or_negative_price_levels: int
    zero_or_negative_mid_rows: int

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def _parse_int_price(text: str, *, field_name: str, path: Path) -> int:
    value = float(text)
    if not math.isfinite(value) or not value.is_integer():
        raise ValueError(f"{path.name}: {field_name} must be an integer price level, got {text!r}")
    return int(value)


def _parse_positive_volume(text: str, *, field_name: str, path: Path) -> int:
    value = int(float(text))
    magnitude = abs(value)
    if magnitude <= 0:
        raise ValueError(f"{path.name}: {field_name} must be a non-zero volume, got {text!r}")
    return magnitude


def _parse_levels(
    cols: Sequence[str],
    price_idx: Iterable[int],
    vol_idx: Iterable[int],
    *,
    path: Path,
    side: str,
) -> List[Tuple[int, int]]:
    levels: List[Tuple[int, int]] = []
    for level_no, (p_idx, v_idx) in enumerate(zip(price_idx, vol_idx), start=1):
        price_text = cols[p_idx]
        volume_text = cols[v_idx]
        if price_text == "" and volume_text == "":
            continue
        if price_text == "" or volume_text == "":
            raise ValueError(f"{path.name}: incomplete {side} level {level_no}")
        price = _parse_int_price(price_text, field_name=f"{side}_price_{level_no}", path=path)
        volume = _parse_positive_volume(volume_text, field_name=f"{side}_volume_{level_no}", path=path)
        levels.append((price, volume))
    return levels


def _snapshot_issue_counts(snapshot: BookSnapshot) -> tuple[int, int, int]:
    empty = 1 if (not snapshot.bids and not snapshot.asks) else 0
    one_sided = 1 if ((not snapshot.bids) ^ (not snapshot.asks)) else 0
    crossed = 0
    if snapshot.bids and snapshot.asks and snapshot.bids[0][0] >= snapshot.asks[0][0]:
        crossed = 1
    return empty, one_sided, crossed


def _expected_row_count(spec: RoundSpec) -> int:
    return int(spec.ticks_per_day) * len(spec.products)


def _normalise_spec(round_number: int, round_spec: RoundSpec | None) -> RoundSpec:
    return round_spec or get_round_spec(round_number)


def load_round_day(
    data_dir: Path,
    day: int,
    round_number: int = 1,
    *,
    round_spec: RoundSpec | None = None,
) -> DayDataset:
    spec = _normalise_spec(round_number, round_spec)
    products = tuple(spec.products)
    product_set = set(products)
    prices_path = data_dir / f"prices_round_{spec.round_number}_day_{day}.csv"
    trades_path = data_dir / f"trades_round_{spec.round_number}_day_{day}.csv"
    if not prices_path.is_file():
        raise FileNotFoundError(prices_path)

    books_by_timestamp: Dict[int, Dict[str, BookSnapshot]] = {}
    timestamps: List[int] = []
    products_seen = set()
    price_rows = 0
    duplicate_book_rows = 0
    empty_book_rows = 0
    one_sided_book_rows = 0
    crossed_book_rows = 0
    price_level_parse_errors = 0
    volume_parse_errors = 0
    zero_price_levels = 0
    negative_price_levels = 0
    zero_or_negative_price_levels = 0
    zero_or_negative_mid_rows = 0

    with prices_path.open("r", encoding="utf-8") as handle:
        reader = csv.reader(handle, delimiter=";")
        header = next(reader)
        if header != PRICE_SCHEMA:
            raise ValueError(f"Unexpected price schema for {prices_path.name}: {header}")
        for row_index, cols in enumerate(reader, start=2):
            price_rows += 1
            if len(cols) != len(PRICE_SCHEMA):
                raise ValueError(f"{prices_path.name}:{row_index}: expected {len(PRICE_SCHEMA)} columns, got {len(cols)}")
            source_day = int(cols[0])
            if source_day != int(day):
                raise ValueError(f"{prices_path.name}:{row_index}: expected day {day}, got {source_day}")
            ts = int(cols[1])
            product = cols[2]
            products_seen.add(product)
            if ts not in books_by_timestamp:
                books_by_timestamp[ts] = {}
                timestamps.append(ts)
            if product in books_by_timestamp[ts]:
                duplicate_book_rows += 1
            try:
                bids = _parse_levels(cols, (3, 5, 7), (4, 6, 8), path=prices_path, side="bid")
            except ValueError:
                price_level_parse_errors += 1
                raise
            try:
                asks = _parse_levels(cols, (9, 11, 13), (10, 12, 14), path=prices_path, side="ask")
            except ValueError:
                volume_parse_errors += 1
                raise
            mid = float(cols[15]) if cols[15] else None
            if mid is not None and mid <= 0:
                zero_or_negative_mid_rows += 1
            zero_price_levels += sum(1 for price, _volume in (*bids, *asks) if price == 0)
            negative_price_levels += sum(1 for price, _volume in (*bids, *asks) if price < 0)
            zero_or_negative_price_levels = zero_price_levels + negative_price_levels
            snapshot = BookSnapshot(
                timestamp=ts,
                product=product,
                bids=bids,
                asks=asks,
                mid=mid,
                reference_fair=mid,
                source_day=source_day,
            )
            books_by_timestamp[ts][product] = snapshot
            empty_i, one_sided_i, crossed_i = _snapshot_issue_counts(snapshot)
            empty_book_rows += empty_i
            one_sided_book_rows += one_sided_i
            crossed_book_rows += crossed_i

    trades_by_timestamp: Dict[int, Dict[str, List[TradePrint]]] = {}
    trade_rows = 0
    trade_rows_unknown_symbol = 0
    trade_rows_unknown_timestamp = 0
    trade_rows_invalid_currency = 0
    trade_rows_invalid_quantity = 0
    if trades_path.is_file():
        with trades_path.open("r", encoding="utf-8") as handle:
            reader = csv.reader(handle, delimiter=";")
            header = next(reader)
            if header != TRADE_SCHEMA:
                raise ValueError(f"Unexpected trade schema for {trades_path.name}: {header}")
            for row_index, cols in enumerate(reader, start=2):
                trade_rows += 1
                if len(cols) != len(TRADE_SCHEMA):
                    raise ValueError(f"{trades_path.name}:{row_index}: expected {len(TRADE_SCHEMA)} columns, got {len(cols)}")
                ts = int(cols[0])
                symbol = cols[3]
                currency = cols[4]
                price = float(cols[5])
                quantity = int(float(cols[6]))
                if symbol not in product_set:
                    trade_rows_unknown_symbol += 1
                if ts not in books_by_timestamp:
                    trade_rows_unknown_timestamp += 1
                if currency != spec.currency:
                    trade_rows_invalid_currency += 1
                if quantity <= 0:
                    trade_rows_invalid_quantity += 1
                trades_by_timestamp.setdefault(ts, {}).setdefault(symbol, []).append(
                    TradePrint(
                        timestamp=ts,
                        buyer=cols[1],
                        seller=cols[2],
                        symbol=symbol,
                        price=price,
                        quantity=quantity,
                        synthetic=False,
                    )
                )

    timestamps.sort()
    missing_products = {
        ts: [product for product in products if product not in books_by_timestamp[ts]]
        for ts in timestamps
        if any(product not in books_by_timestamp[ts] for product in products)
    }
    timestamp_step_ok = all((b - a) == spec.timestamp_step for a, b in zip(timestamps, timestamps[1:]))

    report = ValidationReport(
        price_rows=price_rows,
        expected_price_rows=_expected_row_count(spec),
        trade_rows=trade_rows,
        timestamps=len(timestamps),
        expected_timestamps=spec.ticks_per_day,
        timestamp_min=min(timestamps) if timestamps else None,
        timestamp_max=max(timestamps) if timestamps else None,
        timestamp_step_ok=timestamp_step_ok,
        missing_products=missing_products,
        duplicate_book_rows=duplicate_book_rows,
        empty_book_rows=empty_book_rows,
        one_sided_book_rows=one_sided_book_rows,
        crossed_book_rows=crossed_book_rows,
        products_seen=sorted(products_seen),
        exact_product_match=sorted(products_seen) == sorted(products),
        products_per_timestamp_expected=len(products),
        trade_rows_unknown_symbol=trade_rows_unknown_symbol,
        trade_rows_unknown_timestamp=trade_rows_unknown_timestamp,
        trade_rows_invalid_currency=trade_rows_invalid_currency,
        trade_rows_invalid_quantity=trade_rows_invalid_quantity,
        price_level_parse_errors=price_level_parse_errors,
        volume_parse_errors=volume_parse_errors,
        zero_price_levels=zero_price_levels,
        negative_price_levels=negative_price_levels,
        zero_or_negative_price_levels=zero_or_negative_price_levels,
        zero_or_negative_mid_rows=zero_or_negative_mid_rows,
    )
    return DayDataset(
        day=day,
        timestamps=timestamps,
        books_by_timestamp=books_by_timestamp,
        trades_by_timestamp=trades_by_timestamp,
        validation=report.to_dict(),
        metadata={
            "source": f"round{spec.round_number}_csv",
            "round": spec.round_number,
            "round_name": spec.name,
            "prices_path": str(prices_path),
            "trades_path": str(trades_path),
            "expected_products": list(products),
            "currency": spec.currency,
        },
        round_number=spec.round_number,
        products=products,
    )


def load_round_dataset(
    data_dir: Path,
    days: Iterable[int],
    round_number: int = 1,
    *,
    round_spec: RoundSpec | None = None,
) -> Dict[int, DayDataset]:
    spec = _normalise_spec(round_number, round_spec)
    return {
        int(day): load_round_day(data_dir, int(day), round_number=spec.round_number, round_spec=spec)
        for day in days
    }


def load_round1_day(data_dir: Path, day: int) -> DayDataset:
    return load_round_day(data_dir, day, round_number=1)


def load_round2_day(data_dir: Path, day: int) -> DayDataset:
    return load_round_day(data_dir, day, round_number=2)


def load_round3_day(data_dir: Path, day: int) -> DayDataset:
    return load_round_day(data_dir, day, round_number=3)


def load_round4_day(data_dir: Path, day: int) -> DayDataset:
    return load_round_day(data_dir, day, round_number=4)


def load_round1_dataset(data_dir: Path, days: Iterable[int] = (-2, -1, 0)) -> Dict[int, DayDataset]:
    return load_round_dataset(data_dir, days, round_number=1)


def load_round2_dataset(data_dir: Path, days: Iterable[int] = (-1, 0, 1)) -> Dict[int, DayDataset]:
    return load_round_dataset(data_dir, days, round_number=2)


def load_round3_dataset(data_dir: Path, days: Iterable[int] = (0, 1, 2)) -> Dict[int, DayDataset]:
    return load_round_dataset(data_dir, days, round_number=3)


def load_round4_dataset(data_dir: Path, days: Iterable[int] = (1, 2, 3)) -> Dict[int, DayDataset]:
    return load_round_dataset(data_dir, days, round_number=4)


def inspect_dataset_days(
    market_days: Sequence[DayDataset],
    *,
    round_number: int,
    round_spec: RoundSpec | None = None,
) -> Dict[str, object]:
    spec = _normalise_spec(round_number, round_spec)
    return {
        "round": spec.round_number,
        "round_name": spec.name,
        "products": list(spec.products),
        "default_days": list(spec.default_days),
        "currency": spec.currency,
        "timestamp_step": spec.timestamp_step,
        "ticks_per_day": spec.ticks_per_day,
        "days": [
            {
                "day": dataset.day,
                "metadata": dict(dataset.metadata),
                "validation": dict(dataset.validation),
            }
            for dataset in market_days
        ],
    }


def product_set_for_round(round_number: int) -> Tuple[str, ...]:
    return tuple(products_for_round(round_number))
