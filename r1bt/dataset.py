from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .metadata import PRODUCTS, TIMESTAMP_STEP


@dataclass
class TradePrint:
    timestamp: int
    buyer: str
    seller: str
    symbol: str
    price: int
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


@dataclass
class ValidationReport:
    price_rows: int
    trade_rows: int
    timestamps: int
    missing_products: Dict[int, List[str]]
    timestamp_step_ok: bool
    products_seen: List[str]
    duplicate_book_rows: int
    empty_book_rows: int
    one_sided_book_rows: int
    crossed_book_rows: int
    trade_rows_unknown_symbol: int
    trade_rows_unknown_timestamp: int

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def _parse_levels(cols: List[str], price_idx: Iterable[int], vol_idx: Iterable[int]) -> List[Tuple[int, int]]:
    levels: List[Tuple[int, int]] = []
    for p_idx, v_idx in zip(price_idx, vol_idx):
        if cols[p_idx] == "" or cols[v_idx] == "":
            continue
        levels.append((int(float(cols[p_idx])), abs(int(float(cols[v_idx])))))
    return levels


def _snapshot_issue_counts(snapshot: BookSnapshot) -> tuple[int, int, int]:
    empty = 1 if (not snapshot.bids and not snapshot.asks) else 0
    one_sided = 1 if ((not snapshot.bids) ^ (not snapshot.asks)) else 0
    crossed = 0
    if snapshot.bids and snapshot.asks and snapshot.bids[0][0] >= snapshot.asks[0][0]:
        crossed = 1
    return empty, one_sided, crossed


def load_round1_day(data_dir: Path, day: int) -> DayDataset:
    prices_path = data_dir / f"prices_round_1_day_{day}.csv"
    trades_path = data_dir / f"trades_round_1_day_{day}.csv"
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

    with prices_path.open("r", encoding="utf-8") as handle:
        reader = csv.reader(handle, delimiter=";")
        header = next(reader)
        expected = [
            "day", "timestamp", "product",
            "bid_price_1", "bid_volume_1", "bid_price_2", "bid_volume_2", "bid_price_3", "bid_volume_3",
            "ask_price_1", "ask_volume_1", "ask_price_2", "ask_volume_2", "ask_price_3", "ask_volume_3",
            "mid_price", "profit_and_loss",
        ]
        if header != expected:
            raise ValueError(f"Unexpected price schema for {prices_path.name}: {header}")
        for cols in reader:
            price_rows += 1
            ts = int(cols[1])
            product = cols[2]
            products_seen.add(product)
            if ts not in books_by_timestamp:
                books_by_timestamp[ts] = {}
                timestamps.append(ts)
            if product in books_by_timestamp[ts]:
                duplicate_book_rows += 1
            snapshot = BookSnapshot(
                timestamp=ts,
                product=product,
                bids=_parse_levels(cols, (3, 5, 7), (4, 6, 8)),
                asks=_parse_levels(cols, (9, 11, 13), (10, 12, 14)),
                mid=float(cols[15]) if cols[15] else None,
                reference_fair=float(cols[15]) if cols[15] else None,
                source_day=day,
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
    if trades_path.is_file():
        with trades_path.open("r", encoding="utf-8") as handle:
            reader = csv.reader(handle, delimiter=";")
            header = next(reader)
            expected = ["timestamp", "buyer", "seller", "symbol", "currency", "price", "quantity"]
            if header != expected:
                raise ValueError(f"Unexpected trade schema for {trades_path.name}: {header}")
            for cols in reader:
                trade_rows += 1
                ts = int(cols[0])
                symbol = cols[3]
                if symbol not in PRODUCTS:
                    trade_rows_unknown_symbol += 1
                if ts not in books_by_timestamp:
                    trade_rows_unknown_timestamp += 1
                trades_by_timestamp.setdefault(ts, {}).setdefault(symbol, []).append(
                    TradePrint(
                        timestamp=ts,
                        buyer=cols[1],
                        seller=cols[2],
                        symbol=symbol,
                        price=int(float(cols[5])),
                        quantity=int(cols[6]),
                        synthetic=False,
                    )
                )

    timestamps.sort()
    missing_products = {
        ts: [product for product in PRODUCTS if product not in books_by_timestamp[ts]]
        for ts in timestamps
        if any(product not in books_by_timestamp[ts] for product in PRODUCTS)
    }
    timestamp_step_ok = all((b - a) == TIMESTAMP_STEP for a, b in zip(timestamps, timestamps[1:]))

    report = ValidationReport(
        price_rows=price_rows,
        trade_rows=trade_rows,
        timestamps=len(timestamps),
        missing_products=missing_products,
        timestamp_step_ok=timestamp_step_ok,
        products_seen=sorted(products_seen),
        duplicate_book_rows=duplicate_book_rows,
        empty_book_rows=empty_book_rows,
        one_sided_book_rows=one_sided_book_rows,
        crossed_book_rows=crossed_book_rows,
        trade_rows_unknown_symbol=trade_rows_unknown_symbol,
        trade_rows_unknown_timestamp=trade_rows_unknown_timestamp,
    )
    return DayDataset(
        day=day,
        timestamps=timestamps,
        books_by_timestamp=books_by_timestamp,
        trades_by_timestamp=trades_by_timestamp,
        validation=report.to_dict(),
        metadata={"source": "round1_csv", "prices_path": str(prices_path), "trades_path": str(trades_path)},
    )


def load_round1_dataset(data_dir: Path, days: Iterable[int] = (-2, -1, 0)) -> Dict[int, DayDataset]:
    return {day: load_round1_day(data_dir, int(day)) for day in days}
