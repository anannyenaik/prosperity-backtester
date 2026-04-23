from datamodel import OrderDepth, TradingState, Order
import math
import json


POS_LIMITS = {
    "ASH_COATED_OSMIUM": 80,
    "INTARIAN_PEPPER_ROOT": 80,
}

# Practical Round 2 MAF default.
# Small website grid to test next: 1450, 1500, 1550, 1600.
MAF_BID = 1500

OSMIUM_PARAMS = {
    "alpha": 0.0315,
    "beta": 1.116,
    "gamma": 10001,
    "ask_factor": 1.0007,
    "bid_factor": 0.9993,
    "edge": 1,
    "spread": 16,
    "z_threshold": 1,
    "position_limit": 70,
    "one_sided_offset": 100,
    "wall_clip_threshold": 12,
    # Local uplift knobs for OSMIUM only.
    "strong_take_levels": 2,
    "neutral_take_levels": 2,
    "recycle_position": 45,
}

PEPPER_PARAMS = {
    "spread_gradient": 0.0010586880760,
    "spread_intercept": 0.8694130152902,
    "alpha": 0.2,
    "threshold": 0.9,
    "history_len": 7,
    "direction_len": 15,
    # Teammate insight: PEPPER seems to want more one-sided safety than OSMIUM.
    # Start above 100, with symmetry preserved by default for low-risk tuning.
    "one_sided_buy_offset": 110,
    "one_sided_sell_offset": 110,
    # Early one-sided books are noisier because PEPPER history is still thin.
    "early_one_sided_extra": 2,
    "trend_majority": 0.6,
    "hold_take_fraction": 0.25,
    # Tiny PEPPER continuation-only uplift knobs.
    "strong_trend_majority": 0.8,
    "strong_hold_bonus": 1,
    "strong_recycle_fraction": 0.5,
}


class Trader:
    def bid(self):
        return MAF_BID

    @staticmethod
    def _clamp(x, lo, hi):
        return max(lo, min(hi, x))

    @staticmethod
    def _append_order(orders, product, price, qty):
        qty = int(qty)
        if qty != 0:
            orders.append(Order(product, int(price), qty))

    @staticmethod
    def _regression_slope(values):
        n = len(values)
        if n < 2:
            return 0.0
        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / float(n)
        numerator = 0.0
        denominator = 0.0
        for i, y in enumerate(values):
            dx = i - x_mean
            numerator += dx * (y - y_mean)
            denominator += dx * dx
        return numerator / denominator if denominator else 0.0

    def _book(self, order_depth: OrderDepth):
        bids = sorted(
            [(int(price), int(qty)) for price, qty in order_depth.buy_orders.items() if qty > 0],
            key=lambda x: x[0],
            reverse=True,
        )
        asks = sorted(
            [(int(price), int(-qty)) for price, qty in order_depth.sell_orders.items() if qty < 0],
            key=lambda x: x[0],
        )

        best_bid = bids[0][0] if bids else None
        best_bid_qty = bids[0][1] if bids else 0
        best_ask = asks[0][0] if asks else None
        best_ask_qty = asks[0][1] if asks else 0

        deep_bid = max(bids, key=lambda x: x[1])[0] if bids else None
        deep_ask = max(asks, key=lambda x: x[1])[0] if asks else None

        return {
            "bids": bids,
            "asks": asks,
            "best_bid": best_bid,
            "best_bid_qty": best_bid_qty,
            "best_ask": best_ask,
            "best_ask_qty": best_ask_qty,
            "deep_bid": deep_bid,
            "deep_ask": deep_ask,
            "has_bids": bool(bids),
            "has_asks": bool(asks),
        }

    @staticmethod
    def _safe_bid_price(price, best_ask):
        if price is None:
            return None
        price = int(math.floor(price))
        if best_ask is not None:
            price = min(price, best_ask - 1)
        return price

    @staticmethod
    def _safe_ask_price(price, best_bid):
        if price is None:
            return None
        price = int(math.ceil(price))
        if best_bid is not None:
            price = max(price, best_bid + 1)
        return price

    def _separate_quotes(self, bid_price, ask_price, lean=0):
        if bid_price is not None and ask_price is not None and bid_price >= ask_price:
            if lean > 0:
                ask_price = bid_price + 1
            elif lean < 0:
                bid_price = ask_price - 1
            else:
                ask_price = bid_price + 1
        return bid_price, ask_price

    def _wall_mid(self, book):
        if book["deep_bid"] is None or book["deep_ask"] is None:
            return None
        return (book["deep_bid"] + book["deep_ask"]) / 2.0

    def _top_mid(self, book):
        if book["best_bid"] is None or book["best_ask"] is None:
            return None
        return (book["best_bid"] + book["best_ask"]) / 2.0

    def _take_from_asks(self, orders, product, asks, buy_cap, max_price, max_levels):
        taken = 0
        if buy_cap <= 0 or max_price is None or max_levels <= 0:
            return buy_cap, taken
        levels = 0
        for price, qty in asks:
            if price > max_price or buy_cap <= 0 or levels >= max_levels:
                break
            trade_qty = min(buy_cap, qty)
            self._append_order(orders, product, price, trade_qty)
            buy_cap -= trade_qty
            taken += trade_qty
            levels += 1
        return buy_cap, taken

    def _take_from_bids(self, orders, product, bids, sell_cap, min_price, max_levels):
        taken = 0
        if sell_cap <= 0 or min_price is None or max_levels <= 0:
            return sell_cap, taken
        levels = 0
        for price, qty in bids:
            if price < min_price or sell_cap <= 0 or levels >= max_levels:
                break
            trade_qty = min(sell_cap, qty)
            self._append_order(orders, product, price, -trade_qty)
            sell_cap -= trade_qty
            taken += trade_qty
            levels += 1
        return sell_cap, taken

    def _trade_osmium(self, product, order_depth, pos, limit, prev_wall_mid):
        orders = []
        p = OSMIUM_PARAMS

        alpha = p["alpha"]
        beta = p["beta"]
        mean = p["gamma"]
        ask_fac = p["ask_factor"]
        bid_fac = p["bid_factor"]
        edge = p["edge"]
        z_thresh = p["z_threshold"]
        pos_limit = p["position_limit"]
        one_sided_offset = p["one_sided_offset"]
        wall_clip_threshold = p["wall_clip_threshold"]
        strong_take_levels = p["strong_take_levels"]
        neutral_take_levels = p["neutral_take_levels"]
        recycle_position = p["recycle_position"]

        book = self._book(order_depth)

        wall_mid = mean if prev_wall_mid is None else mean + (1 - alpha) * (prev_wall_mid - mean)
        book_wall_mid = self._wall_mid(book)
        top_mid = self._top_mid(book)
        if book_wall_mid is not None:
            if top_mid is not None and abs(book_wall_mid - top_mid) > wall_clip_threshold:
                wall_mid = top_mid + self._clamp(book_wall_mid - top_mid, -wall_clip_threshold, wall_clip_threshold)
            else:
                wall_mid = book_wall_mid

        best_bid = book["best_bid"]
        bid_quantity = book["best_bid_qty"]
        best_ask = book["best_ask"]
        ask_quantity = book["best_ask_qty"]

        buy_flag = book["has_asks"] and not book["has_bids"]
        sell_flag = book["has_bids"] and not book["has_asks"]

        buy_cap = max(pos_limit - pos, 0)
        sell_cap = max(pos_limit + pos, 0)

        if buy_flag:
            one_sided_buy = round(wall_mid - one_sided_offset + beta + 1)
            one_sided_buy = self._safe_bid_price(one_sided_buy, best_ask)
            if one_sided_buy is not None:
                self._append_order(orders, product, one_sided_buy, limit - pos)
            buy_cap = 0
        elif sell_flag:
            one_sided_sell = round(wall_mid + one_sided_offset - beta - 1)
            one_sided_sell = self._safe_ask_price(one_sided_sell, best_bid)
            if one_sided_sell is not None:
                self._append_order(orders, product, one_sided_sell, -(limit + pos))
            sell_cap = 0

        sensible_buy = math.floor(wall_mid * bid_fac)
        sensible_sell = math.ceil(wall_mid * ask_fac)

        std = beta / math.sqrt(2 * alpha)
        z = (wall_mid - mean) / std if std else 0.0

        if buy_cap == 0 and not buy_flag:
            sell_price = best_bid if best_bid is not None else self._safe_ask_price(sensible_buy, best_bid)
            sell_quantity = min(sell_cap, bid_quantity if best_bid is not None else 5)
            if sell_price is not None:
                self._append_order(orders, product, sell_price, -sell_quantity)

        elif sell_cap == 0 and not sell_flag:
            buy_price = best_ask if best_ask is not None else self._safe_bid_price(sensible_sell, best_ask)
            buy_quantity = min(buy_cap, ask_quantity if best_ask is not None else 5)
            if buy_price is not None:
                self._append_order(orders, product, buy_price, buy_quantity)

        elif z > z_thresh:
            quote_bid = sensible_buy
            quote_ask = sensible_sell

            sweep_floor = wall_mid - (1 if pos > 0 else 0)
            sell_cap, sold_qty = self._take_from_bids(
                orders, product, book["bids"], sell_cap, sweep_floor, strong_take_levels
            )
            if sold_qty == 0 and best_bid is not None:
                quote_bid = best_bid + edge

            if best_ask is not None:
                quote_ask = best_ask - edge

            quote_bid = min(quote_bid, mean - 1)
            quote_bid = self._safe_bid_price(quote_bid, best_ask)
            quote_ask = self._safe_ask_price(quote_ask, best_bid)
            quote_bid, quote_ask = self._separate_quotes(quote_bid, quote_ask, lean=-1)

            if quote_ask is not None:
                self._append_order(orders, product, quote_ask, -sell_cap)
            if quote_bid is not None:
                self._append_order(orders, product, quote_bid, buy_cap)

        elif z < -z_thresh:
            quote_bid = sensible_buy
            quote_ask = sensible_sell

            sweep_ceiling = wall_mid + (1 if pos < 0 else 0)
            buy_cap, bought_qty = self._take_from_asks(
                orders, product, book["asks"], buy_cap, sweep_ceiling, strong_take_levels
            )
            if bought_qty == 0 and best_ask is not None:
                quote_ask = best_ask - edge

            quote_ask = max(quote_ask, mean + 1)
            if best_bid is not None:
                quote_bid = best_bid + edge

            quote_bid = self._safe_bid_price(quote_bid, best_ask)
            quote_ask = self._safe_ask_price(quote_ask, best_bid)
            quote_bid, quote_ask = self._separate_quotes(quote_bid, quote_ask, lean=1)

            if quote_ask is not None:
                self._append_order(orders, product, quote_ask, -sell_cap)
            if quote_bid is not None:
                self._append_order(orders, product, quote_bid, buy_cap)

        else:
            buy_take_threshold = None
            sell_take_threshold = None
            if pos <= -recycle_position:
                buy_take_threshold = wall_mid
            elif pos >= recycle_position:
                sell_take_threshold = wall_mid
            if buy_take_threshold is not None:
                buy_cap, _ = self._take_from_asks(
                    orders, product, book["asks"], buy_cap, buy_take_threshold, neutral_take_levels
                )
            if sell_take_threshold is not None:
                sell_cap, _ = self._take_from_bids(
                    orders, product, book["bids"], sell_cap, sell_take_threshold, neutral_take_levels
                )

            quote_bid = best_bid + 1 if best_bid is not None and best_bid < wall_mid else sensible_buy
            quote_ask = best_ask - 1 if best_ask is not None and best_ask > wall_mid else sensible_sell

            quote_bid = self._safe_bid_price(quote_bid, best_ask)
            quote_ask = self._safe_ask_price(quote_ask, best_bid)
            quote_bid, quote_ask = self._separate_quotes(quote_bid, quote_ask)

            if quote_bid is not None:
                self._append_order(orders, product, quote_bid, buy_cap)
            if quote_ask is not None:
                self._append_order(orders, product, quote_ask, -sell_cap)

        return orders, wall_mid

    def _trade_pepper(self, product, order_depth, pos, limit, prev_mids, slope, directions):
        orders = []
        p = PEPPER_PARAMS
        slope = 0.0 if slope is None else float(slope)
        prev_mids = [] if prev_mids is None else list(prev_mids)
        directions = [] if directions is None else list(directions)

        m = p["spread_gradient"]
        c = p["spread_intercept"]
        thresh = p["threshold"]
        trend_majority = p["trend_majority"]
        one_sided_buy_offset = p["one_sided_buy_offset"]
        one_sided_sell_offset = p["one_sided_sell_offset"]
        early_one_sided_extra = p["early_one_sided_extra"]
        hold_take_fraction = p["hold_take_fraction"]
        strong_trend_majority = p["strong_trend_majority"]
        strong_hold_bonus = p["strong_hold_bonus"]
        strong_recycle_fraction = p["strong_recycle_fraction"]

        book = self._book(order_depth)

        wall_mid = prev_mids[-1] + slope if prev_mids else 14008
        book_wall_mid = self._wall_mid(book)

        best_bid = book["best_bid"]
        bid_quantity = book["best_bid_qty"]
        best_ask = book["best_ask"]
        ask_quantity = book["best_ask_qty"]

        buy_flag = book["has_asks"] and not book["has_bids"]
        sell_flag = book["has_bids"] and not book["has_asks"]

        if book_wall_mid is not None:
            wall_mid = book_wall_mid

        mid_spread = (m * wall_mid + c) / 2.0

        # Preserve current best behaviour: only recalibrate one-sided books early in history.
        if len(prev_mids) < 3:
            if best_ask is not None and best_bid is None:
                wall_mid = best_ask - mid_spread
            elif best_bid is not None and best_ask is None:
                wall_mid = best_bid + mid_spread
            mid_spread = (m * wall_mid + c) / 2.0

        prev_mids.append(wall_mid)
        if len(prev_mids) > p["history_len"]:
            prev_mids.pop(0)

        if len(prev_mids) >= p["history_len"]:
            slope = p["alpha"] * self._regression_slope(prev_mids) + (1 - p["alpha"]) * slope
        else:
            slope = 0.0

        if slope > 0:
            trend = 1
        elif slope < 0:
            trend = -1
        else:
            trend = 0

        directions.append(trend)
        if len(directions) > p["direction_len"]:
            directions.pop(0)

        dir_len = len(directions) if directions else 1
        buy_indicator = directions.count(1) / float(dir_len)
        sell_indicator = directions.count(-1) / float(dir_len)

        buy_cap = max(limit - pos, 0)
        sell_cap = max(limit + pos, 0)

        buy_side_offset = one_sided_buy_offset + (early_one_sided_extra if len(prev_mids) < 3 else 0)
        sell_side_offset = one_sided_sell_offset + (early_one_sided_extra if len(prev_mids) < 3 else 0)

        if buy_flag and buy_cap > 0:
            buy_price = round(wall_mid - buy_side_offset)
            buy_price = self._safe_bid_price(buy_price, best_ask)
            if buy_price is not None:
                self._append_order(orders, product, buy_price, buy_cap)
            buy_cap = 0
        elif sell_flag and sell_cap > 0:
            sell_price = round(wall_mid + sell_side_offset)
            sell_price = self._safe_ask_price(sell_price, best_bid)
            if sell_price is not None:
                self._append_order(orders, product, sell_price, -sell_cap)
            sell_cap = 0

        hold_take_edge = max(1, int(round(mid_spread * hold_take_fraction)))

        strong_buy_cont = buy_indicator >= strong_trend_majority and trend == 1 and slope > 0
        strong_sell_cont = sell_indicator >= strong_trend_majority and trend == -1 and slope < 0

        if buy_indicator >= trend_majority:
            target = limit

            if pos <= thresh * target:
                fair_purchase = math.floor(wall_mid + mid_spread)
                buy_price = min(best_ask, fair_purchase) if best_ask is not None else fair_purchase
                buy_price = self._safe_bid_price(buy_price, None if buy_price == best_ask else best_ask)
                if buy_price is not None:
                    self._append_order(orders, product, buy_price, buy_cap)

            elif pos < target:
                local_take_edge = hold_take_edge + (strong_hold_bonus if strong_buy_cont else 0)
                if best_ask is not None and best_ask <= wall_mid + local_take_edge:
                    buy_quantity = min(buy_cap, ask_quantity)
                    self._append_order(orders, product, best_ask, buy_quantity)
                    buy_cap -= buy_quantity

                post_buy = best_bid + 1 if best_bid is not None and best_bid <= wall_mid - mid_spread else round(wall_mid - mid_spread)
                post_buy = self._safe_bid_price(post_buy, best_ask)
                if post_buy is not None:
                    self._append_order(orders, product, post_buy, buy_cap)

            elif best_ask is not None and best_ask > wall_mid:
                unwind_qty = math.floor(target * (1 - thresh))
                if strong_buy_cont:
                    unwind_qty = max(1, math.floor(unwind_qty * strong_recycle_fraction))
                post_sell = self._safe_ask_price(best_ask - 1, best_bid)
                if post_sell is not None:
                    self._append_order(orders, product, post_sell, -min(sell_cap, unwind_qty))

        elif sell_indicator >= trend_majority:
            target = -limit

            if pos >= thresh * target:
                fair_sale = math.ceil(wall_mid - mid_spread)
                sell_price = max(best_bid, fair_sale) if best_bid is not None else fair_sale
                sell_price = self._safe_ask_price(sell_price, None if sell_price == best_bid else best_bid)
                if sell_price is not None:
                    self._append_order(orders, product, sell_price, -sell_cap)

            elif pos > target:
                local_take_edge = hold_take_edge + (strong_hold_bonus if strong_sell_cont else 0)
                if best_bid is not None and best_bid >= wall_mid - local_take_edge:
                    sell_quantity = min(sell_cap, bid_quantity)
                    self._append_order(orders, product, best_bid, -sell_quantity)
                    sell_cap -= sell_quantity

                post_sell = best_ask - 1 if best_ask is not None and best_ask >= wall_mid + mid_spread else round(wall_mid + mid_spread)
                post_sell = self._safe_ask_price(post_sell, best_bid)
                if post_sell is not None:
                    self._append_order(orders, product, post_sell, -sell_cap)

            elif best_bid is not None and best_bid < wall_mid:
                recycle_qty = math.floor(abs(target) * (1 - thresh))
                if strong_sell_cont:
                    recycle_qty = max(1, math.floor(recycle_qty * strong_recycle_fraction))
                post_buy = self._safe_bid_price(best_bid + 1, best_ask)
                if post_buy is not None:
                    self._append_order(orders, product, post_buy, min(buy_cap, recycle_qty))

        return orders, prev_mids, slope, directions

    def run(self, state: TradingState):
        result = {}
        pstate = {}

        if state.traderData:
            try:
                pstate = json.loads(state.traderData)
            except Exception:
                pstate = {}

        for product, order_depth in state.order_depths.items():
            position = state.position.get(product, 0)
            limit = POS_LIMITS.get(product, 20)

            if product == "ASH_COATED_OSMIUM":
                prev_wall_mid = pstate.get("PREV_OSMIUM_WALL_MID")
                orders, osmium_wall_mid = self._trade_osmium(product, order_depth, position, limit, prev_wall_mid)
                pstate["PREV_OSMIUM_WALL_MID"] = osmium_wall_mid
                result[product] = orders

            elif product == "INTARIAN_PEPPER_ROOT":
                prev_mids = pstate.get("PREV_PEPPER_MIDS")
                prev_slope = pstate.get("PEPPER_SLOPE")
                prev_directions = pstate.get("PEPPER_DIRECTIONS")
                orders, pepper_mids, slope, directions = self._trade_pepper(
                    product, order_depth, position, limit, prev_mids, prev_slope, prev_directions
                )
                pstate["PREV_PEPPER_MIDS"] = pepper_mids
                pstate["PEPPER_SLOPE"] = slope
                pstate["PEPPER_DIRECTIONS"] = directions
                result[product] = orders

            else:
                result[product] = []

        conversions = 0
        return result, conversions, json.dumps(pstate)
