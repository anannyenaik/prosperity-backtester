from __future__ import annotations

import io
import json
import sys
import traceback
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:  # pragma: no cover - exercised through subprocess execution
    package_dir = Path(__file__).resolve().parent
    parent_dir = package_dir.parent
    sys.path = [str(parent_dir)] + [entry for entry in sys.path if Path(entry).resolve() != package_dir]
    from prosperity_backtester.datamodel import Listing, Observation, OrderDepth, Trade, TradingState
    from prosperity_backtester.metadata import CURRENCY
    from prosperity_backtester.trader_adapter import TraderLoadError, install_datamodel_aliases, load_trader_module
else:
    from .datamodel import Listing, Observation, OrderDepth, Trade, TradingState
    from .metadata import CURRENCY
    from .trader_adapter import TraderLoadError, install_datamodel_aliases, load_trader_module


def _load_trader(trader_path: Path, overrides: dict[str, object] | None):
    module = load_trader_module(trader_path, module_overrides=overrides)
    try:
        trader = module.Trader()
    except Exception as exc:  # pragma: no cover - exercised through the Rust worker
        raise TraderLoadError(f"Trader() construction failed for {trader_path}: {exc}") from exc
    if not callable(getattr(trader, "run", None)):
        raise TraderLoadError(f"Trader instance does not define callable run(state): {trader_path}")
    return trader


def _build_order_depth(payload: dict[str, Any]) -> OrderDepth:
    depth = OrderDepth()
    depth.buy_orders = {int(price): int(qty) for price, qty in payload.get("buy_orders", {}).items()}
    depth.sell_orders = {int(price): int(qty) for price, qty in payload.get("sell_orders", {}).items()}
    return depth


def _build_trade(payload: dict[str, Any]) -> Trade:
    return Trade(
        payload["symbol"],
        int(payload["price"]),
        int(payload["quantity"]),
        payload.get("buyer"),
        payload.get("seller"),
        int(payload["timestamp"]),
    )


def _build_state(payload: dict[str, Any]) -> TradingState:
    products = sorted(str(product) for product in payload.get("order_depths", {}))
    listings = {product: Listing(product, product, CURRENCY) for product in products}
    order_depths = {
        product: _build_order_depth(depth)
        for product, depth in payload.get("order_depths", {}).items()
    }
    own_trades = {
        product: [_build_trade(trade) for trade in payload.get("own_trades", {}).get(product, [])]
        for product in products
    }
    market_trades = {
        product: [_build_trade(trade) for trade in payload.get("market_trades", {}).get(product, [])]
        for product in products
    }
    position = {
        product: int(size)
        for product, size in payload.get("position", {}).items()
    }
    return TradingState(
        traderData=str(payload.get("trader_data", "")),
        timestamp=int(payload["timestamp"]),
        listings=listings,
        order_depths=order_depths,
        own_trades=own_trades,
        market_trades=market_trades,
        position=position,
        observations=Observation({}, {}),
    )


def _serialise_orders(orders: dict[str, list[Any]] | None) -> dict[str, list[dict[str, int | str]]]:
    if not orders:
        return {}
    payload: dict[str, list[dict[str, int | str]]] = {}
    for product, values in orders.items():
        payload[str(product)] = [
            {
                "symbol": str(order.symbol),
                "price": int(order.price),
                "quantity": int(order.quantity),
            }
            for order in values
        ]
    return payload


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    if len(argv) not in {1, 2}:
        print(json.dumps({"error": "usage: rust_strategy_worker.py <trader_file.py> [overrides.json]"}), flush=True)
        return 1

    trader_path = Path(argv[0]).resolve()
    overrides: dict[str, object] | None = None
    if len(argv) == 2:
        overrides_path = Path(argv[1]).resolve()
        overrides_payload = json.loads(overrides_path.read_text(encoding="utf-8"))
        if overrides_payload not in (None, {}) and not isinstance(overrides_payload, dict):
            raise TraderLoadError(f"Override file must contain a JSON object: {overrides_path}")
        overrides = overrides_payload or None

    install_datamodel_aliases()
    trader = _load_trader(trader_path, overrides)

    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        request = json.loads(raw_line)
        request_type = str(request.get("type", "run"))
        try:
            if request_type == "reset":
                trader = _load_trader(trader_path, overrides)
                response = {"ok": True}
            elif request_type == "run":
                state = _build_state(request)
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    result = trader.run(state)
                if not isinstance(result, tuple) or len(result) != 3:
                    raise RuntimeError(f"Trader returned unexpected result: {result!r}")
                orders, conversions, trader_data = result
                response = {
                    "orders": _serialise_orders(orders),
                    "conversions": int(conversions),
                    "trader_data": trader_data,
                    "stdout": stdout.getvalue(),
                }
            else:
                response = {"error": f"unsupported request type {request_type}"}
        except Exception:
            response = {"error": traceback.format_exc()}
        print(json.dumps(response, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess tests
    raise SystemExit(main())
