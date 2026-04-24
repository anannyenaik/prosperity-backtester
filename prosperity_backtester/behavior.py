from __future__ import annotations

import statistics
from typing import Dict, List, Mapping, Sequence

from .metadata import PRODUCTS, PRODUCT_METADATA, ProductMeta


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def build_behaviour_series(
    *,
    orders: Sequence[Dict[str, object]],
    fills: Sequence[Dict[str, object]],
    inventory_series: Sequence[Dict[str, object]],
    pnl_series: Sequence[Dict[str, object]],
    fair_value_series: Sequence[Dict[str, object]],
    products: Sequence[str] = PRODUCTS,
    product_metadata: Mapping[str, ProductMeta] = PRODUCT_METADATA,
) -> List[Dict[str, object]]:
    order_counts: Dict[tuple[int, str, int], Dict[str, int]] = {}
    fill_counts: Dict[tuple[int, str, int], Dict[str, int]] = {}
    fair_lookup = {(int(row["day"]), str(row["product"]), int(row["timestamp"])): row for row in fair_value_series}
    pnl_lookup = {(int(row["day"]), str(row["product"]), int(row["timestamp"])): row for row in pnl_series}

    for row in orders:
        key = (int(row["day"]), str(row["product"]), int(row["timestamp"]))
        bucket = order_counts.setdefault(key, {
            "order_count": 0,
            "aggressive_order_count": 0,
            "passive_order_count": 0,
            "buy_order_qty": 0,
            "sell_order_qty": 0,
        })
        qty = int(row.get("submitted_quantity", 0))
        bucket["order_count"] += 1
        if row.get("order_role") == "aggressive":
            bucket["aggressive_order_count"] += 1
        else:
            bucket["passive_order_count"] += 1
        if qty > 0:
            bucket["buy_order_qty"] += qty
        elif qty < 0:
            bucket["sell_order_qty"] += abs(qty)

    for row in fills:
        key = (int(row["day"]), str(row["product"]), int(row["timestamp"]))
        bucket = fill_counts.setdefault(key, {
            "fill_count": 0,
            "aggressive_fill_count": 0,
            "passive_fill_count": 0,
            "buy_fill_qty": 0,
            "sell_fill_qty": 0,
        })
        qty = abs(int(row.get("quantity", 0)))
        bucket["fill_count"] += 1
        if str(row.get("kind", "")).startswith("aggressive"):
            bucket["aggressive_fill_count"] += 1
        else:
            bucket["passive_fill_count"] += 1
        if row.get("side") == "buy":
            bucket["buy_fill_qty"] += qty
        elif row.get("side") == "sell":
            bucket["sell_fill_qty"] += qty

    rows: List[Dict[str, object]] = []
    for inv_row in inventory_series:
        key = (int(inv_row["day"]), str(inv_row["product"]), int(inv_row["timestamp"]))
        fair_row = fair_lookup.get(key, {})
        pnl_row = pnl_lookup.get(key, {})
        orders_row = order_counts.get(key, {})
        fills_row = fill_counts.get(key, {})
        product = str(inv_row["product"])
        limit = product_metadata[product].position_limit
        position = int(inv_row.get("position", 0))
        analysis_fair = fair_row.get("analysis_fair")
        mid = fair_row.get("mid")
        rows.append({
            "day": key[0],
            "product": product,
            "timestamp": key[2],
            "position": position,
            "position_ratio": position / limit if limit else 0.0,
            "abs_position_ratio": abs(position) / limit if limit else 0.0,
            "order_count": orders_row.get("order_count", 0),
            "aggressive_order_count": orders_row.get("aggressive_order_count", 0),
            "passive_order_count": orders_row.get("passive_order_count", 0),
            "fill_count": fills_row.get("fill_count", 0),
            "aggressive_fill_count": fills_row.get("aggressive_fill_count", 0),
            "passive_fill_count": fills_row.get("passive_fill_count", 0),
            "buy_order_qty": orders_row.get("buy_order_qty", 0),
            "sell_order_qty": orders_row.get("sell_order_qty", 0),
            "buy_fill_qty": fills_row.get("buy_fill_qty", 0),
            "sell_fill_qty": fills_row.get("sell_fill_qty", 0),
            "net_fill_qty": fills_row.get("buy_fill_qty", 0) - fills_row.get("sell_fill_qty", 0),
            "analysis_fair": analysis_fair,
            "mid": mid,
            "fair_minus_mid": None if analysis_fair is None or mid is None else float(analysis_fair) - float(mid),
            "realised": pnl_row.get("realised"),
            "unrealised": pnl_row.get("unrealised"),
            "mtm": pnl_row.get("mtm"),
            "spread": pnl_row.get("spread"),
        })
    return rows


def analyse_behaviour(
    *,
    orders: Sequence[Dict[str, object]],
    fills: Sequence[Dict[str, object]],
    inventory_series: Sequence[Dict[str, object]],
    pnl_series: Sequence[Dict[str, object]],
    fair_value_series: Sequence[Dict[str, object]],
    products: Sequence[str] = PRODUCTS,
    product_metadata: Mapping[str, ProductMeta] = PRODUCT_METADATA,
    include_series: bool = True,
) -> Dict[str, object]:
    per_product: Dict[str, Dict[str, object]] = {}
    behaviour_series = (
        build_behaviour_series(
            orders=orders,
            fills=fills,
            inventory_series=inventory_series,
            pnl_series=pnl_series,
            fair_value_series=fair_value_series,
            products=products,
            product_metadata=product_metadata,
        )
        if include_series
        else []
    )

    for product in products:
        product_orders = [row for row in orders if row.get("product") == product]
        product_fills = [row for row in fills if row.get("product") == product]
        product_inventory = [row for row in inventory_series if row.get("product") == product]
        product_pnl = [row for row in pnl_series if row.get("product") == product]
        product_behaviour = [row for row in behaviour_series if row.get("product") == product]
        position_limit = product_metadata[product].position_limit

        total_order_qty = sum(abs(int(row.get("submitted_quantity", 0))) for row in product_orders)
        total_fill_qty = sum(abs(int(row.get("quantity", 0))) for row in product_fills)
        aggressive_fill_qty = sum(abs(int(row.get("quantity", 0))) for row in product_fills if str(row.get("kind", "")).startswith("aggressive"))
        passive_fill_qty = sum(abs(int(row.get("quantity", 0))) for row in product_fills if not str(row.get("kind", "")).startswith("aggressive"))
        aggressive_fill_count = sum(1 for row in product_fills if str(row.get("kind", "")).startswith("aggressive"))
        passive_fill_count = sum(1 for row in product_fills if not str(row.get("kind", "")).startswith("aggressive"))
        buy_order_qty = sum(max(0, int(row.get("submitted_quantity", 0))) for row in product_orders)
        sell_order_qty = sum(max(0, -int(row.get("submitted_quantity", 0))) for row in product_orders)
        buy_fill_qty = sum(int(row.get("quantity", 0)) for row in product_fills if row.get("side") == "buy")
        sell_fill_qty = sum(int(row.get("quantity", 0)) for row in product_fills if row.get("side") == "sell")
        inventory_abs = [abs(int(row.get("position", 0))) for row in product_inventory]
        near_cap = [row for row in product_inventory if abs(int(row.get("position", 0))) >= 0.9 * position_limit]
        spreads = [float(row.get("spread")) for row in product_pnl if row.get("spread") is not None]
        fair_edges = []
        fill_edges = []
        signed_order_qty = 0
        signed_fill_qty = 0
        aggressive_order_count = 0
        passive_order_count = 0
        quote_distances = []
        fill_markout_1 = []
        fill_markout_5 = []

        for row in product_orders:
            qty = int(row.get("submitted_quantity", 0))
            signed_order_qty += qty
            if row.get("order_role") == "aggressive":
                aggressive_order_count += 1
            else:
                passive_order_count += 1
            edge = row.get("signed_edge_to_analysis_fair")
            if edge is not None:
                fair_edges.append(float(edge))
            distance = row.get("distance_to_touch")
            if distance is not None:
                quote_distances.append(float(distance))

        for row in product_fills:
            qty = int(row.get("quantity", 0))
            signed_fill_qty += qty if row.get("side") == "buy" else -qty
            edge = row.get("signed_edge_to_analysis_fair")
            if edge is not None:
                fill_edges.append(float(edge))
            if row.get("markout_1") is not None:
                fill_markout_1.append(float(row["markout_1"]))
            if row.get("markout_5") is not None:
                fill_markout_5.append(float(row["markout_5"]))

        mtm = [float(row.get("mtm", 0.0)) for row in product_pnl]
        realised = [float(row.get("realised", 0.0)) for row in product_pnl]
        unrealised = [float(row.get("unrealised", 0.0)) for row in product_pnl]
        pnl_jumps = []
        for prev, cur in zip(product_pnl, product_pnl[1:]):
            pnl_jumps.append({
                "timestamp": int(cur["timestamp"]),
                "day": int(cur["day"]),
                "mtm_change": float(cur.get("mtm", 0.0)) - float(prev.get("mtm", 0.0)),
                "position": int(cur.get("position", 0)) if "position" in cur else None,
            })
        pnl_jumps.sort(key=lambda row: abs(row["mtm_change"]), reverse=True)

        running_peak = float("-inf")
        max_drawdown = 0.0
        for value in mtm:
            running_peak = max(running_peak, value)
            max_drawdown = max(max_drawdown, running_peak - value)

        regime_counts = {"up": 0, "flat": 0, "down": 0}
        for row in fair_value_series:
            if row.get("product") != product:
                continue
            slope = float(row.get("trend_slope_per_tick") or 0.0)
            if slope > 0.0005:
                regime_counts["up"] += 1
            elif slope < -0.0005:
                regime_counts["down"] += 1
            else:
                regime_counts["flat"] += 1

        if include_series:
            position_ratios = [float(row.get("abs_position_ratio", 0.0)) for row in product_behaviour]
            order_bursts = [int(row.get("order_count", 0)) for row in product_behaviour]
            fill_bursts = [int(row.get("fill_count", 0)) for row in product_behaviour]
        else:
            position_ratios = [
                abs(int(row.get("position", 0))) / position_limit
                for row in product_inventory
            ]
            order_count_by_tick: Dict[tuple[int, int], int] = {}
            for row in product_orders:
                key = (int(row["day"]), int(row["timestamp"]))
                order_count_by_tick[key] = order_count_by_tick.get(key, 0) + 1
            fill_count_by_tick: Dict[tuple[int, int], int] = {}
            for row in product_fills:
                key = (int(row["day"]), int(row["timestamp"]))
                fill_count_by_tick[key] = fill_count_by_tick.get(key, 0) + 1
            order_bursts = list(order_count_by_tick.values())
            fill_bursts = list(fill_count_by_tick.values())

        per_product[product] = {
            "order_count": len(product_orders),
            "fill_count": len(product_fills),
            "total_orders": len(product_orders),
            "total_fills": len(product_fills),
            "aggressive_order_count": aggressive_order_count,
            "passive_order_count": passive_order_count,
            "aggressive_fill_count": aggressive_fill_count,
            "passive_fill_count": passive_fill_count,
            "turnover_qty": total_fill_qty,
            "total_order_qty": total_order_qty,
            "total_fill_qty": total_fill_qty,
            "total_buy_qty": buy_fill_qty,
            "total_sell_qty": sell_fill_qty,
            "buy_order_qty": buy_order_qty,
            "sell_order_qty": sell_order_qty,
            "buy_fill_qty": buy_fill_qty,
            "sell_fill_qty": sell_fill_qty,
            "order_to_fill_ratio": None if total_order_qty == 0 else total_fill_qty / total_order_qty,
            "aggressive_fill_share": None if total_fill_qty == 0 else aggressive_fill_qty / total_fill_qty,
            "passive_fill_share": None if total_fill_qty == 0 else passive_fill_qty / total_fill_qty,
            "aggressive_order_share": None if not product_orders else aggressive_order_count / len(product_orders),
            "average_signed_order_edge_to_fair": _mean(fair_edges),
            "average_signed_fill_edge_to_fair": _mean(fill_edges),
            "average_fill_markout_1": _mean(fill_markout_1),
            "average_fill_markout_5": _mean(fill_markout_5),
            "average_distance_to_touch": _mean(quote_distances),
            "mean_spread": _mean(spreads),
            "mean_realised": _mean(realised),
            "mean_unrealised": _mean(unrealised),
            "peak_abs_position": max(inventory_abs) if inventory_abs else 0,
            "cap_usage_ratio": (max(inventory_abs) / position_limit) if inventory_abs else 0.0,
            "mean_abs_position_ratio": _mean(position_ratios),
            "time_near_cap_ratio": (len(near_cap) / len(product_inventory)) if product_inventory else 0.0,
            "signed_order_qty": signed_order_qty,
            "signed_fill_qty": signed_fill_qty,
            "final_mtm": mtm[-1] if mtm else 0.0,
            "max_drawdown": max_drawdown,
            "max_orders_per_tick": max(order_bursts) if order_bursts else 0,
            "max_fills_per_tick": max(fill_bursts) if fill_bursts else 0,
            "regime_counts": regime_counts,
            "largest_mtm_swings": pnl_jumps[:8],
        }

    return {
        "per_product": per_product,
        "series": behaviour_series,
        "summary": {
            "products": list(products),
            "dominant_risk_product": max(products, key=lambda p: per_product[p]["cap_usage_ratio"] if p in per_product else 0.0),
            "dominant_turnover_product": max(products, key=lambda p: per_product[p]["turnover_qty"] if p in per_product else 0.0),
        },
    }
