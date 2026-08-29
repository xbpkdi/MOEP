import socket
import threading
import itertools
import uuid
import sys

import protocol
from order_book import OrderBook

HOST = "0.0.0.0"
TCP_PORT = 5000
SYMBOL = "AAPL"
HISTORY_MAX = 200


def log(direction, msg_type, detail=""):
    print(f"[SERVER] {direction:<5} {msg_type:<20} {detail}")


class ExchangeServer:
    def __init__(self, host=HOST, tcp_port=TCP_PORT):
        self.host = host
        self.tcp_port = tcp_port
        self.order_book = OrderBook(SYMBOL)

        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.clients = {}
        self.clients_lock = threading.Lock()

        self.seq_counter = itertools.count(1)
        self.history = {}
        self.history_lock = threading.Lock()

    def start(self):
        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp_socket.bind((self.host, self.tcp_port))
        tcp_socket.listen()
        print(f"[SERVER] MOEP exchange server listening on {self.host}:{self.tcp_port} (symbol={SYMBOL})")

        try:
            while True:
                conn, addr = tcp_socket.accept()
                thread = threading.Thread(target=self._handle_client, args=(conn, addr), daemon=True)
                thread.start()
        except KeyboardInterrupt:
            print("\n[SERVER] Shutting down.")
        finally:
            tcp_socket.close()

    def _handle_client(self, conn, addr):
        client_id = str(uuid.uuid4())[:8]
        file = conn.makefile("r")

        try:
            for line in file:
                if not line.strip():
                    continue
                try:
                    msg = protocol.decode_tcp(line)
                except Exception:
                    self._send_tcp(conn, protocol.build_response("ERROR", 400, reason="invalid_json"))
                    continue

                log("RECV", msg.get("type", "?"), f"from {addr}")
                self._dispatch(msg, conn, addr, client_id)
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            with self.clients_lock:
                self.clients.pop(client_id, None)
            conn.close()
            print(f"[SERVER] client {client_id} disconnected")

    def _dispatch(self, msg, conn, addr, client_id):
        msg_type = msg.get("type")

        if msg_type == protocol.MSG_REGISTER:
            self._handle_register(msg, conn, addr, client_id)
        elif msg_type == protocol.MSG_ORDER_NEW:
            self._handle_order_new(msg, conn, client_id)
        elif msg_type == protocol.MSG_ORDER_CANCEL:
            self._handle_order_cancel(msg, conn, client_id)
        elif msg_type == protocol.MSG_GAP_FILL_REQUEST:
            self._handle_gap_fill(msg, conn)
        else:
            self._send_tcp(conn, protocol.build_response("ERROR", 400, reason="unknown_message_type"))

    def _handle_register(self, msg, conn, addr, client_id):
        udp_port = msg.get("udp_port")
        if not isinstance(udp_port, int):
            self._send_tcp(conn, protocol.build_response(protocol.MSG_REGISTER_ACK, 400, reason="missing_udp_port"))
            return

        with self.clients_lock:
            self.clients[client_id] = {"udp_addr": (addr[0], udp_port)}

        resp = protocol.build_response(protocol.MSG_REGISTER_ACK, 200, client_id=client_id, symbol=SYMBOL)
        self._send_tcp(conn, resp)
        print(f"[SERVER] client {client_id} registered, udp_addr={(addr[0], udp_port)}")

    def _handle_order_new(self, msg, conn, client_id):
        side = msg.get("side")
        price = msg.get("price")
        qty = msg.get("qty")
        client_order_id = msg.get("client_order_id", "")

        if side not in (protocol.SIDE_BUY, protocol.SIDE_SELL):
            self._send_tcp(conn, protocol.build_response(protocol.MSG_ORDER_ACK, 400, reason="invalid_side"))
            return
        if not isinstance(price, (int, float)) or price <= 0:
            self._send_tcp(conn, protocol.build_response(protocol.MSG_ORDER_ACK, 403, reason="invalid_price"))
            return
        if not isinstance(qty, int) or qty <= 0:
            self._send_tcp(conn, protocol.build_response(protocol.MSG_ORDER_ACK, 403, reason="invalid_qty"))
            return

        order, trades = self.order_book.add_order(client_id, client_order_id, side, price, qty)

        status_map = {"FILLED": 201, "PARTIALLY_FILLED": 202, "RESTING": 200}
        status_code = status_map[order.status]

        resp = protocol.build_response(
            protocol.MSG_ORDER_ACK, status_code,
            order_id=order.order_id,
            client_order_id=client_order_id,
            filled_qty=order.qty - order.remaining_qty,
            remaining_qty=order.remaining_qty,
            trade_count=len(trades),
        )
        self._send_tcp(conn, resp)

        self._broadcast_market_data()
        for trade in trades:
            self._broadcast_trade(trade)

    def _handle_order_cancel(self, msg, conn, client_id):
        client_order_id = msg.get("client_order_id")
        order = self.order_book.cancel_order(client_id, client_order_id)

        if order is None:
            self._send_tcp(conn, protocol.build_response(protocol.MSG_CANCEL_ACK, 404, client_order_id=client_order_id))
            return

        self._send_tcp(conn, protocol.build_response(
            protocol.MSG_CANCEL_ACK, 204, client_order_id=client_order_id, order_id=order.order_id,
        ))
        self._broadcast_market_data()

    def _handle_gap_fill(self, msg, conn):
        from_seq = msg.get("from_seq")
        to_seq = msg.get("to_seq")

        if not isinstance(from_seq, int) or not isinstance(to_seq, int) or from_seq > to_seq:
            self._send_tcp(conn, protocol.build_response(protocol.MSG_GAP_FILL_RESPONSE, 400))
            return

        with self.history_lock:
            missing = [seq for seq in range(from_seq, to_seq + 1) if seq not in self.history]
            if missing:
                self._send_tcp(conn, protocol.build_response(
                    protocol.MSG_GAP_FILL_RESPONSE, 410, missing_seq=missing,
                ))
                return
            messages = [self.history[seq] for seq in range(from_seq, to_seq + 1)]

        self._send_tcp(conn, protocol.build_response(protocol.MSG_GAP_FILL_RESPONSE, 200, messages=messages))

    def _broadcast_market_data(self):
        bid_price, bid_qty, ask_price, ask_qty = self.order_book.best_bid_ask()
        bids, asks = self.order_book.get_top_levels(5)
        seq = next(self.seq_counter)
        msg = protocol.build_message(
            protocol.MSG_MARKET_DATA, seq=seq, symbol=SYMBOL,
            best_bid=bid_price, best_bid_qty=bid_qty,
            best_ask=ask_price, best_ask_qty=ask_qty,
            bids=bids, asks=asks,
        )
        self._store_and_send(seq, msg)

    def _broadcast_trade(self, trade):
        seq = next(self.seq_counter)
        msg = protocol.build_message(
            protocol.MSG_TRADE, seq=seq, symbol=SYMBOL,
            price=trade.price, qty=trade.qty,
            buy_order_id=trade.buy_order_id, sell_order_id=trade.sell_order_id,
            side=trade.aggressor_side,
        )
        self._store_and_send(seq, msg)

    def _store_and_send(self, seq, msg):
        with self.history_lock:
            self.history[seq] = msg
            if len(self.history) > HISTORY_MAX:
                oldest = min(self.history)
                del self.history[oldest]

        with self.clients_lock:
            targets = list(self.clients.values())

        payload = protocol.encode_udp(msg)
        for info in targets:
            try:
                self.udp_socket.sendto(payload, info["udp_addr"])
            except OSError:
                pass

        log("BCAST", msg["type"], f"seq={seq} -> {len(targets)} client(s)")

    def _send_tcp(self, conn, msg):
        conn.sendall(protocol.encode_tcp(msg))
        log("SEND", msg["type"], f"status={msg.get('status_code')} {msg.get('status_phrase', '')}")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else TCP_PORT
    ExchangeServer(tcp_port=port).start()
