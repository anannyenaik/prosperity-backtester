import json
import math
from datamodel import Order, TradingState


POSITION_LIMITS = {
    "ASH_COATED_OSMIUM": 80,
    "INTARIAN_PEPPER_ROOT": 80,
}

PARAMS = {
    "ASH_COATED_OSMIUM": {
        "fallback_fair": 10000.0,
        "anchor_alpha": 0.02,
        "microprice_weight": 0.75,
        "take_edge": 2.0,
        "quote_half_spread": 4.0,
        "base_order_size": 16,
        "inventory_skew_per_unit": 0.10,
        "second_level_gap": 2,
        "second_level_size": 8,
        "third_level_gap": 4,
        "third_level_size": 4,
        "one_sided_size": 10,
    },
    "INTARIAN_PEPPER_ROOT": {
        "fallback_intercept": 12000.0,
        "trend_slope": 0.001,
        "intercept_alpha": 0.01,
        "take_buy_offset_below_target": 1.5,
        "take_buy_offset_above_target": 0.5,
        "take_buy_offset_near_cap": -0.5,
        "target_inventory": 78,
        "sell_start_inventory": 80,
        "recycle_inventory": 74,
        "recycle_edge": 20.0,
        "recycle_size": 4,
        "recycle_cooldown": 1500,
        "recycle_spread_min": 6,
        "base_buy_size": 28,
        "base_buy_size_over_target": 16,
        "second_buy_size": 14,
        "third_buy_size": 8,
        "one_sided_buy_size": 22,
        "one_sided_second_buy_size": 10,
    },
}


class Trader:
    def run(self, state: TradingState):
        saved = self._load_state(getattr(state, "traderData", ""))
        timestamp = getattr(state, "timestamp", 0)

        if isinstance(saved.get("last_timestamp"), int) and timestamp < saved["last_timestamp"]:
            saved = {}

        result = {}
        for product in POSITION_LIMITS:
            depth = state.order_depths.get(product)
            if depth is None:
                continue

            position = state.position.get(product, 0)
            fair = self._compute_fair(product, depth, timestamp, saved)

            if product == "ASH_COATED_OSMIUM":
                result[product] = self._build_osmium_orders(depth, fair, position)
            else:
                mid = self._mid_price(depth)
                self._update_pepper_state(mid, saved)
                result[product] = self._build_pepper_orders(depth, fair, position, timestamp, saved)

        saved["last_timestamp"] = timestamp
        trader_data = json.dumps(saved, separators=(",", ":"))
        return result, 0, trader_data

    def _load_state(self, raw):
        if not raw:
            return {}
        try:
            loaded = json.loads(raw)
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            return {}

    def _book_levels(self, depth):
        buy_orders = getattr(depth, "buy_orders", {}) or {}
        sell_orders = getattr(depth, "sell_orders", {}) or {}

        bids = sorted(
            [(int(price), int(volume)) for price, volume in buy_orders.items() if volume and volume > 0],
            key=lambda x: -x[0],
        )
        asks = sorted(
            [(int(price), int(-volume)) for price, volume in sell_orders.items() if volume and volume < 0],
            key=lambda x: x[0],
        )
        return bids, asks

    def _top_of_book(self, depth):
        bids, asks = self._book_levels(depth)
        best_bid, bid_volume = bids[0] if bids else (None, 0)
        best_ask, ask_volume = asks[0] if asks else (None, 0)
        return best_bid, best_ask, bid_volume, ask_volume

    def _mid_price(self, depth):
        best_bid, best_ask, _, _ = self._top_of_book(depth)
        if best_bid is not None and best_ask is not None:
            return (best_bid + best_ask) / 2.0
        if best_bid is not None:
            return float(best_bid)
        if best_ask is not None:
            return float(best_ask)
        return None

    def _microprice(self, depth):
        best_bid, best_ask, bid_volume, ask_volume = self._top_of_book(depth)
        if best_bid is None or best_ask is None:
            return None
        total = bid_volume + ask_volume
        if total <= 0:
            return (best_bid + best_ask) / 2.0
        return (best_ask * bid_volume + best_bid * ask_volume) / total

    def _compute_fair(self, product, depth, timestamp, saved):
        mid = self._mid_price(depth)

        if product == "ASH_COATED_OSMIUM":
            params = PARAMS[product]
            anchor = saved.get("osmium_anchor")
            if not isinstance(anchor, (int, float)):
                anchor = mid if mid is not None else params["fallback_fair"]
            if mid is not None:
                anchor = (1.0 - params["anchor_alpha"]) * float(anchor) + params["anchor_alpha"] * mid
            saved["osmium_anchor"] = anchor

            micro = self._microprice(depth)
            if micro is None:
                return float(anchor)
            return params["microprice_weight"] * micro + (1.0 - params["microprice_weight"]) * float(anchor)

        params = PARAMS[product]
        slope = params["trend_slope"]
        intercept = saved.get("pepper_intercept")
        if not isinstance(intercept, (int, float)):
            intercept = mid - slope * timestamp if mid is not None else params["fallback_intercept"]

        if mid is not None:
            observed_intercept = mid - slope * timestamp
            intercept = (1.0 - params["intercept_alpha"]) * float(intercept) + params["intercept_alpha"] * observed_intercept

        saved["pepper_intercept"] = intercept
        return float(intercept) + slope * timestamp

    def _update_pepper_state(self, mid, saved):
        if mid is None:
            return
        peak = saved.get("pepper_peak_mid")
        if not isinstance(peak, (int, float)) or mid > peak:
            peak = mid
        saved["pepper_peak_mid"] = peak
        saved["pepper_last_mid"] = mid

    def _remaining_buy(self, product, position):
        return max(0, POSITION_LIMITS[product] - position)

    def _remaining_sell(self, product, position):
        return max(0, POSITION_LIMITS[product] + position)

    def _append_buy(self, orders, product, price, quantity, position):
        qty = min(max(0, int(quantity)), self._remaining_buy(product, position))
        if qty > 0:
            orders.append(Order(product, int(price), qty))
            position += qty
        return position

    def _append_sell(self, orders, product, price, quantity, position):
        qty = min(max(0, int(quantity)), self._remaining_sell(product, position))
        if qty > 0:
            orders.append(Order(product, int(price), -qty))
            position -= qty
        return position

    def _build_osmium_orders(self, depth, fair, position):
        params = PARAMS["ASH_COATED_OSMIUM"]
        bids, asks = self._book_levels(depth)
        orders = []
        working_position = position

        for ask_price, ask_volume in asks:
            if ask_price > fair - params["take_edge"]:
                break
            working_position = self._append_buy(orders, "ASH_COATED_OSMIUM", ask_price, ask_volume, working_position)

        for bid_price, bid_volume in bids:
            if bid_price < fair + params["take_edge"]:
                break
            working_position = self._append_sell(orders, "ASH_COATED_OSMIUM", bid_price, bid_volume, working_position)

        best_bid, best_ask, _, _ = self._top_of_book(depth)
        skewed_fair = fair - params["inventory_skew_per_unit"] * working_position

        if best_bid is not None and best_ask is not None:
            raw_buy = int(math.floor(skewed_fair - params["quote_half_spread"]))
            raw_sell = int(math.ceil(skewed_fair + params["quote_half_spread"]))

            buy_quote = min(raw_buy, best_bid + 1, best_ask - 1)
            sell_quote = max(raw_sell, best_ask - 1, best_bid + 1)

            if buy_quote >= sell_quote:
                buy_quote = min(int(math.floor(skewed_fair - 1)), best_ask - 1)
                sell_quote = max(int(math.ceil(skewed_fair + 1)), best_bid + 1)

            if buy_quote >= sell_quote:
                return orders

            inventory_ratio = working_position / float(POSITION_LIMITS["ASH_COATED_OSMIUM"])
            buy_size = int(round(params["base_order_size"] * max(0.0, 1.0 - inventory_ratio)))
            sell_size = int(round(params["base_order_size"] * max(0.0, 1.0 + inventory_ratio)))

            working_position = self._append_buy(orders, "ASH_COATED_OSMIUM", buy_quote, buy_size, working_position)
            working_position = self._append_sell(orders, "ASH_COATED_OSMIUM", sell_quote, sell_size, working_position)

            spread = best_ask - best_bid
            if spread >= 8:
                second_buy_quote = max(best_bid, buy_quote - params["second_level_gap"])
                if second_buy_quote < sell_quote:
                    second_buy_size = max(0, int(round(params["second_level_size"] * max(0.0, 1.0 - inventory_ratio))))
                    working_position = self._append_buy(orders, "ASH_COATED_OSMIUM", second_buy_quote, second_buy_size, working_position)

                second_sell_quote = min(best_ask, sell_quote + params["second_level_gap"])
                if second_sell_quote > buy_quote:
                    second_sell_size = max(0, int(round(params["second_level_size"] * max(0.0, 1.0 + inventory_ratio))))
                    working_position = self._append_sell(orders, "ASH_COATED_OSMIUM", second_sell_quote, second_sell_size, working_position)

            if spread >= 12:
                third_buy_quote = max(best_bid, buy_quote - params["third_level_gap"])
                if third_buy_quote < sell_quote:
                    third_buy_size = max(0, int(round(params["third_level_size"] * max(0.0, 1.0 - inventory_ratio))))
                    working_position = self._append_buy(orders, "ASH_COATED_OSMIUM", third_buy_quote, third_buy_size, working_position)

                third_sell_quote = min(best_ask, sell_quote + params["third_level_gap"])
                if third_sell_quote > buy_quote:
                    third_sell_size = max(0, int(round(params["third_level_size"] * max(0.0, 1.0 + inventory_ratio))))
                    working_position = self._append_sell(orders, "ASH_COATED_OSMIUM", third_sell_quote, third_sell_size, working_position)

            return orders

        if best_ask is not None:
            buy_quote = min(best_ask - 1, int(math.floor(skewed_fair - params["quote_half_spread"])))
            if buy_quote >= 1:
                working_position = self._append_buy(orders, "ASH_COATED_OSMIUM", buy_quote, params["one_sided_size"], working_position)
            return orders

        if best_bid is not None:
            sell_quote = max(best_bid + 1, int(math.ceil(skewed_fair + params["quote_half_spread"])))
            working_position = self._append_sell(orders, "ASH_COATED_OSMIUM", sell_quote, params["one_sided_size"], working_position)
        return orders

    def _pepper_buy_threshold(self, fair, position):
        params = PARAMS["INTARIAN_PEPPER_ROOT"]
        if position < params["target_inventory"]:
            return fair + params["take_buy_offset_below_target"]
        if position < params["sell_start_inventory"]:
            return fair + params["take_buy_offset_above_target"]
        return fair + params["take_buy_offset_near_cap"]

    def _build_pepper_orders(self, depth, fair, position, timestamp, saved):
        params = PARAMS["INTARIAN_PEPPER_ROOT"]
        bids, asks = self._book_levels(depth)
        orders = []
        working_position = position

        buy_threshold = self._pepper_buy_threshold(fair, working_position)
        for ask_price, ask_volume in asks:
            if ask_price > buy_threshold:
                break
            working_position = self._append_buy(orders, "INTARIAN_PEPPER_ROOT", ask_price, ask_volume, working_position)

        best_bid, best_ask, best_bid_volume, _ = self._top_of_book(depth)
        spread = (best_ask - best_bid) if best_bid is not None and best_ask is not None else None

        last_recycle_ts = saved.get("pepper_last_recycle_ts")
        can_recycle = not isinstance(last_recycle_ts, int) or (timestamp - last_recycle_ts) >= params["recycle_cooldown"]
        recycle_mode = (
            best_bid is not None
            and working_position >= 79
            and can_recycle
            and best_bid >= fair + params["recycle_edge"]
            and (spread is None or spread >= params["recycle_spread_min"])
        )

        if recycle_mode:
            recycle_qty = min(best_bid_volume, params["recycle_size"], max(0, working_position - params["recycle_inventory"]))
            if recycle_qty > 0:
                working_position = self._append_sell(orders, "INTARIAN_PEPPER_ROOT", best_bid, recycle_qty, working_position)
                saved["pepper_last_recycle_ts"] = timestamp

        if best_bid is not None and best_ask is not None:
            buy_quote = best_bid + 1 if best_bid + 1 < best_ask else best_bid
            gap = max(0, params["target_inventory"] - working_position)
            if working_position < params["target_inventory"]:
                buy_size = min(params["base_buy_size"] + gap // 3, gap)
            elif working_position < params["sell_start_inventory"]:
                buy_size = min(params["base_buy_size_over_target"], params["sell_start_inventory"] - working_position)
            else:
                buy_size = 0

            if buy_size > 0:
                working_position = self._append_buy(orders, "INTARIAN_PEPPER_ROOT", buy_quote, buy_size, working_position)

            if spread >= 4 and working_position < params["target_inventory"]:
                second_buy_quote = max(best_bid, buy_quote - 2)
                if second_buy_quote < best_ask and second_buy_quote < buy_quote:
                    gap = max(0, params["target_inventory"] - working_position)
                    second_buy_size = min(params["second_buy_size"] + gap // 8, gap)
                    working_position = self._append_buy(orders, "INTARIAN_PEPPER_ROOT", second_buy_quote, second_buy_size, working_position)

            if spread >= 8 and working_position < params["target_inventory"] - 4:
                third_buy_quote = max(best_bid, buy_quote - 4)
                if third_buy_quote < best_ask and third_buy_quote < buy_quote - 1:
                    gap = max(0, params["target_inventory"] - working_position)
                    third_buy_size = min(params["third_buy_size"] + gap // 10, gap)
                    working_position = self._append_buy(orders, "INTARIAN_PEPPER_ROOT", third_buy_quote, third_buy_size, working_position)
            return orders

        if best_ask is not None:
            if working_position < params["sell_start_inventory"]:
                buy_quote = int(best_ask - 1)
                buy_size = params["one_sided_buy_size"] if working_position < params["target_inventory"] else params["base_buy_size_over_target"]
                working_position = self._append_buy(orders, "INTARIAN_PEPPER_ROOT", buy_quote, buy_size, working_position)

                if working_position < params["target_inventory"] and buy_quote - 2 >= 1:
                    second_buy_quote = buy_quote - 2
                    second_buy_size = min(params["one_sided_second_buy_size"], max(0, params["target_inventory"] - working_position))
                    working_position = self._append_buy(orders, "INTARIAN_PEPPER_ROOT", second_buy_quote, second_buy_size, working_position)
            return orders

        if best_bid is not None:
            if working_position < params["sell_start_inventory"]:
                buy_quote = int(best_bid + 1)
                buy_size = params["base_buy_size_over_target"] if working_position >= params["target_inventory"] else params["one_sided_buy_size"]
                working_position = self._append_buy(orders, "INTARIAN_PEPPER_ROOT", buy_quote, buy_size, working_position)
            return orders

        return orders
