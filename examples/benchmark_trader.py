from datamodel import Order


class Trader:
    def run(self, state):
        orders = {}
        buy_tick = (state.timestamp // 100) % 2 == 0
        for product, depth in state.order_depths.items():
            product_orders = []
            if buy_tick and depth.sell_orders:
                product_orders.append(Order(product, min(depth.sell_orders), 1))
            elif not buy_tick and depth.buy_orders:
                product_orders.append(Order(product, max(depth.buy_orders), -1))
            orders[product] = product_orders
        return orders, 0, state.traderData
