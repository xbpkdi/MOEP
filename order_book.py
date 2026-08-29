import heapq
import itertools
import threading
import time
from dataclasses import dataclass, field

STATUS_RESTING = "RESTING"
STATUS_PARTIALLY_FILLED = "PARTIALLY_FILLED"
STATUS_FILLED = "FILLED"
STATUS_CANCELLED = "CANCELLED"


@dataclass
class Order:
    order_id: int
    client_id: str
    client_order_id: str
    symbol: str
    side: str
    price: float
    qty: int
    remaining_qty: int
    status: str = STATUS_RESTING
    timestamp: float = field(default_factory=time.time)


@dataclass
class Trade:
    trade_id: int
    symbol: str
    price: float
    qty: int
    buy_order_id: int
    sell_order_id: int
    timestamp: float = field(default_factory=time.time)
    aggressor_side: str = ""


class OrderBook:

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.orders: dict = {}
        self.buy_heap: list = []
        self.sell_heap: list = []
        self._lock = threading.Lock()
        self._order_id_counter = itertools.count(1)
        self._trade_id_counter = itertools.count(1)
        self._seq_counter = itertools.count(1)

    def add_order(self, client_id: str, client_order_id: str, side: str, price: float, qty: int):
        with self._lock:
            order_id = next(self._order_id_counter)
            order = Order(
                order_id=order_id,
                client_id=client_id,
                client_order_id=client_order_id,
                symbol=self.symbol,
                side=side,
                price=price,
                qty=qty,
                remaining_qty=qty,
            )
            self.orders[order_id] = order

            trades = self._match(order)

            if order.remaining_qty > 0:
                seq = next(self._seq_counter)
                if side == "BUY":
                    heapq.heappush(self.buy_heap, (-price, seq, order_id))
                else:
                    heapq.heappush(self.sell_heap, (price, seq, order_id))

            return order, trades

    def _match(self, incoming: Order):
        trades = []
        opposite_heap = self.sell_heap if incoming.side == "BUY" else self.buy_heap

        while incoming.remaining_qty > 0 and opposite_heap:
            top_price_key, _, top_order_id = opposite_heap[0]
            resting = self.orders.get(top_order_id)

            if resting is None or resting.status == STATUS_CANCELLED or resting.remaining_qty <= 0:
                heapq.heappop(opposite_heap)
                continue

            resting_price = resting.price
            if incoming.side == "BUY" and incoming.price < resting_price:
                break
            if incoming.side == "SELL" and incoming.price > resting_price:
                break

            heapq.heappop(opposite_heap)

            trade_qty = min(incoming.remaining_qty, resting.remaining_qty)
            trade_id = next(self._trade_id_counter)
            buy_id = incoming.order_id if incoming.side == "BUY" else resting.order_id
            sell_id = resting.order_id if incoming.side == "BUY" else incoming.order_id

            trade = Trade(
                trade_id=trade_id,
                symbol=self.symbol,
                price=resting_price,
                qty=trade_qty,
                buy_order_id=buy_id,
                sell_order_id=sell_id,
                aggressor_side=incoming.side,
            )
            trades.append(trade)

            incoming.remaining_qty -= trade_qty
            resting.remaining_qty -= trade_qty
            resting.status = STATUS_FILLED if resting.remaining_qty == 0 else STATUS_PARTIALLY_FILLED

            if resting.remaining_qty > 0:
                heapq.heappush(opposite_heap, (top_price_key, next(self._seq_counter), resting.order_id))

        if incoming.remaining_qty == 0:
            incoming.status = STATUS_FILLED
        elif incoming.remaining_qty < incoming.qty:
            incoming.status = STATUS_PARTIALLY_FILLED
        else:
            incoming.status = STATUS_RESTING

        return trades

    def cancel_order(self, client_id: str, client_order_id: str):
        with self._lock:
            for order in self.orders.values():
                if (order.client_id == client_id
                        and order.client_order_id == client_order_id
                        and order.status in (STATUS_RESTING, STATUS_PARTIALLY_FILLED)):
                    order.status = STATUS_CANCELLED
                    return order
            return None

    def best_bid_ask(self):
        with self._lock:
            bid = self._peek_valid(self.buy_heap)
            ask = self._peek_valid(self.sell_heap)
            bid_price = -bid[0] if bid else None
            bid_qty = self.orders[bid[2]].remaining_qty if bid else None
            ask_price = ask[0] if ask else None
            ask_qty = self.orders[ask[2]].remaining_qty if ask else None
            return bid_price, bid_qty, ask_price, ask_qty

    def _peek_valid(self, heap):
        while heap:
            item = heap[0]
            order = self.orders.get(item[2])
            if order is None or order.status == STATUS_CANCELLED or order.remaining_qty <= 0:
                heapq.heappop(heap)
                continue
            return item
        return None

    def get_top_levels(self, n=5):
        with self._lock:
            bid_qty_by_price = {}
            for _key, _seq, order_id in self.buy_heap:
                order = self.orders.get(order_id)
                if order is None or order.status == STATUS_CANCELLED or order.remaining_qty <= 0:
                    continue
                bid_qty_by_price[order.price] = bid_qty_by_price.get(order.price, 0) + order.remaining_qty

            ask_qty_by_price = {}
            for _key, _seq, order_id in self.sell_heap:
                order = self.orders.get(order_id)
                if order is None or order.status == STATUS_CANCELLED or order.remaining_qty <= 0:
                    continue
                ask_qty_by_price[order.price] = ask_qty_by_price.get(order.price, 0) + order.remaining_qty

            bid_levels = sorted(bid_qty_by_price.items(), key=lambda item: item[0], reverse=True)[:n]
            ask_levels = sorted(ask_qty_by_price.items(), key=lambda item: item[0])[:n]
            bids = [{"price": price, "qty": qty} for price, qty in bid_levels]
            asks = [{"price": price, "qty": qty} for price, qty in ask_levels]
            return bids, asks
