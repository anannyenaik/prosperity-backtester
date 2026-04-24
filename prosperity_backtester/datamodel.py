"""
IMC-Prosperity-compatible datamodel used across Prosperity rounds.

This mirrors the official Prosperity TradingState contract so strategies written
for the live competition run unmodified here.
"""
from __future__ import annotations

import json
from json import JSONEncoder
from typing import Dict, List, Optional

Time = int
Symbol = str
Product = str
Position = int
UserId = str
ObservationValue = int


class Listing:
    def __init__(self, symbol: Symbol, product: Product, denomination: str = "XIRECS"):
        self.symbol = symbol
        self.product = product
        self.denomination = denomination


class ConversionObservation:
    def __init__(self, bidPrice: float, askPrice: float, transportFees: float,
                 exportTariff: float, importTariff: float, sugarPrice: float,
                 sunlightIndex: float):
        self.bidPrice = bidPrice
        self.askPrice = askPrice
        self.transportFees = transportFees
        self.exportTariff = exportTariff
        self.importTariff = importTariff
        self.sugarPrice = sugarPrice
        self.sunlightIndex = sunlightIndex


class Observation:
    def __init__(self,
                 plainValueObservations: Dict[Product, ObservationValue],
                 conversionObservations: Dict[Product, ConversionObservation]):
        self.plainValueObservations = plainValueObservations
        self.conversionObservations = conversionObservations

    def __str__(self) -> str:
        return f"(plain={self.plainValueObservations}, conv_keys={list(self.conversionObservations.keys())})"


class Order:
    def __init__(self, symbol: Symbol, price: int, quantity: int) -> None:
        self.symbol = symbol
        self.price = int(price)
        self.quantity = int(quantity)

    def __repr__(self) -> str:
        return f"({self.symbol}, {self.price}, {self.quantity})"

    __str__ = __repr__


class OrderDepth:
    def __init__(self):
        self.buy_orders: Dict[int, int] = {}   # price -> positive volume
        self.sell_orders: Dict[int, int] = {}  # price -> NEGATIVE volume (Prosperity convention)


class Trade:
    def __init__(self, symbol: Symbol, price: float, quantity: int,
                 buyer: Optional[UserId] = None, seller: Optional[UserId] = None,
                 timestamp: int = 0):
        self.symbol = symbol
        self.price = float(price)
        self.quantity = int(quantity)
        self.buyer = buyer
        self.seller = seller
        self.timestamp = int(timestamp)

    def __repr__(self) -> str:
        return f"({self.symbol}, {self.buyer}<<{self.seller}, {self.price}, {self.quantity}, t={self.timestamp})"

    __str__ = __repr__


class TradingState:
    def __init__(self, traderData: str, timestamp: Time,
                 listings: Dict[Symbol, Listing],
                 order_depths: Dict[Symbol, OrderDepth],
                 own_trades: Dict[Symbol, List[Trade]],
                 market_trades: Dict[Symbol, List[Trade]],
                 position: Dict[Product, Position],
                 observations: Observation):
        self.traderData = traderData
        self.timestamp = timestamp
        self.listings = listings
        self.order_depths = order_depths
        self.own_trades = own_trades
        self.market_trades = market_trades
        self.position = position
        self.observations = observations

    def toJSON(self) -> str:
        return json.dumps(self, default=lambda o: o.__dict__, sort_keys=True)


class ProsperityEncoder(JSONEncoder):
    def default(self, o):
        return o.__dict__
