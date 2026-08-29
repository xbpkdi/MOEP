import socket
import threading
import sys
import itertools
import time

import protocol

SERVER_HOST = "127.0.0.1"
SERVER_TCP_PORT = 5000


def log(direction, msg_type, detail=""):
    print(f"[CLIENT] {direction:<5} {msg_type:<20} {detail}")


class ExchangeClient:
    def __init__(self, server_host=SERVER_HOST, server_tcp_port=SERVER_TCP_PORT, on_event=None):
        self.server_addr = (server_host, server_tcp_port)
        self.client_id = None
        self.on_event = on_event

        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_lock = threading.Lock()

        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_sock.bind(("0.0.0.0", 0))

        self.client_order_id_counter = itertools.count(1)
        self.expected_seq = None

    def _emit(self, direction, msg_type, detail="", payload=None):
        log(direction, msg_type, detail)
        if self.on_event:
            try:
                self.on_event({
                    "direction": direction,
                    "msg_type": msg_type,
                    "detail": detail,
                    "payload": payload or {},
                    "ts": time.time(),
                })
            except Exception:
                pass

    def _kv_detail(self, msg):
        skip = {"type", "ts", "bids", "asks", "messages"}
        parts = []
        for key, value in msg.items():
            if key in skip:
                continue
            parts.append(f"{key}={value}")
        return " ".join(parts)

    def connect(self):
        self.tcp_sock.connect(self.server_addr)
        self.tcp_file = self.tcp_sock.makefile("r")

        udp_port = self.udp_sock.getsockname()[1]
        self._send_tcp(protocol.build_message(protocol.MSG_REGISTER, udp_port=udp_port))

        line = self.tcp_file.readline()
        resp = protocol.decode_tcp(line)
        self._emit("RECV", resp["type"], f"status={resp['status_code']} {resp['status_phrase']}", resp)
        if resp["status_code"] != 200:
            raise RuntimeError("Register failed: " + resp.get("reason", ""))
        self.client_id = resp["client_id"]
        print(f"[CLIENT] registered as {self.client_id}, listening UDP on port {udp_port}")

        threading.Thread(target=self._tcp_reader_loop, daemon=True).start()
        threading.Thread(target=self._udp_listener_loop, daemon=True).start()

    def send_new_order(self, side, price, qty):
        client_order_id = f"{self.client_id}-{next(self.client_order_id_counter)}"
        msg = protocol.build_message(
            protocol.MSG_ORDER_NEW, symbol="AAPL",
            client_order_id=client_order_id, side=side, price=price, qty=qty,
        )
        self._send_tcp(msg)
        return client_order_id

    def send_cancel_order(self, client_order_id):
        self._send_tcp(protocol.build_message(protocol.MSG_ORDER_CANCEL, client_order_id=client_order_id))

    def _send_gap_fill_request(self, from_seq, to_seq):
        self._send_tcp(protocol.build_message(protocol.MSG_GAP_FILL_REQUEST, from_seq=from_seq, to_seq=to_seq))

    def _send_tcp(self, msg):
        with self.tcp_lock:
            self.tcp_sock.sendall(protocol.encode_tcp(msg))
        self._emit("SEND", msg["type"], self._kv_detail(msg), msg)

    def _tcp_reader_loop(self):
        for line in self.tcp_file:
            if not line.strip():
                continue
            resp = protocol.decode_tcp(line)
            extra = self._summarize(resp)
            status_text = f"status={resp.get('status_code')} {resp.get('status_phrase', '')}"
            detail = f"{status_text} {extra}".strip()
            self._emit("RECV", resp["type"], detail, resp)

            if resp["type"] == protocol.MSG_GAP_FILL_RESPONSE and resp["status_code"] == 200:
                for missed_msg in resp["messages"]:
                    self._process_market_message(missed_msg, from_gap_fill=True)

    def _summarize(self, resp):
        if resp["type"] == protocol.MSG_ORDER_ACK:
            total = resp.get("filled_qty", 0) + resp.get("remaining_qty", 0)
            return f"order_id={resp.get('order_id')} filled={resp.get('filled_qty')}/{total}"
        return self._kv_detail(resp)

    def _udp_listener_loop(self):
        while True:
            data, _ = self.udp_sock.recvfrom(4096)
            msg = protocol.decode_udp(data)
            self._process_market_message(msg)

    def _process_market_message(self, msg, from_gap_fill=False):
        seq = msg["seq"]
        tag = "GAPFL" if from_gap_fill else "BCAST"
        self._emit(tag, msg["type"], self._format_market_msg(msg), msg)

        if from_gap_fill:
            return

        if self.expected_seq is None:
            self.expected_seq = seq + 1
            return

        if seq == self.expected_seq:
            self.expected_seq += 1
        elif seq > self.expected_seq:
            print(f"[CLIENT] !! sequence gap detected: expected={self.expected_seq}, got={seq} -> requesting gap-fill")
            self._emit(
                "WARN",
                "GAP_DETECTED",
                f"expected=#{self.expected_seq} received=#{seq}",
                {"expected": self.expected_seq, "received": seq},
            )
            self._send_gap_fill_request(self.expected_seq, seq - 1)
            self.expected_seq = seq + 1

    def _format_market_msg(self, msg):
        if msg["type"] == protocol.MSG_MARKET_DATA:
            return f"seq={msg['seq']} bid={msg['best_bid']}x{msg['best_bid_qty']} ask={msg['best_ask']}x{msg['best_ask_qty']}"
        if msg["type"] == protocol.MSG_TRADE:
            return f"seq={msg['seq']} price={msg['price']} qty={msg['qty']}"
        return str(msg)


def interactive_loop(client: ExchangeClient):
    print("คำสั่ง: buy <price> <qty> | sell <price> <qty> | cancel <client_order_id> | quit")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        parts = line.split()
        cmd = parts[0].lower()

        if cmd == "quit":
            break
        elif cmd in ("buy", "sell") and len(parts) == 3:
            client.send_new_order(cmd.upper(), float(parts[1]), int(parts[2]))
        elif cmd == "cancel" and len(parts) == 2:
            client.send_cancel_order(parts[1])
        else:
            print("คำสั่งไม่ถูกต้อง")


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else SERVER_HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else SERVER_TCP_PORT

    client = ExchangeClient(host, port)
    client.connect()
    interactive_loop(client)
