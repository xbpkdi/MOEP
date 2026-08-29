import sys
import time

from flask import Flask, render_template
from flask_socketio import SocketIO

from client import ExchangeClient

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

exchange_client = None


def push_client_event(event):
    socketio.emit("log_event", event)
    msg_type = event.get("msg_type")
    payload = event.get("payload") or {}
    if msg_type == "MARKET_DATA":
        socketio.emit("book_update", payload)
    elif msg_type == "TRADE":
        socketio.emit("trade", payload)
    elif msg_type == "GAP_DETECTED":
        socketio.emit("gap_alert", payload)


@app.route("/")
def dashboard_page():
    return render_template("index.html")


@socketio.on("submit_order")
def handle_submit_order(data):
    if exchange_client is None:
        return {"ok": False, "reason": "client_not_ready"}
    side = str(data.get("side", "")).upper()
    try:
        price = float(data.get("price"))
        qty = int(data.get("qty"))
    except (TypeError, ValueError):
        return {"ok": False, "reason": "invalid_input"}
    if side not in ("BUY", "SELL"):
        return {"ok": False, "reason": "invalid_side"}
    client_order_id = exchange_client.send_new_order(side, price, qty)
    return {"ok": True, "client_order_id": client_order_id}


def start_exchange_client(host, port):
    global exchange_client
    client = ExchangeClient(host, port, on_event=push_client_event)
    for attempt in range(20):
        try:
            client.connect()
            exchange_client = client
            print(f"[WEB] connected to MOEP server at {host}:{port}")
            return
        except OSError:
            print(f"[WEB] waiting for MOEP server {host}:{port} ({attempt + 1}/20)")
            time.sleep(0.5)
    print("[WEB] could not connect to MOEP server — start server.py first")
    sys.exit(1)


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
    web_port = int(sys.argv[3]) if len(sys.argv) > 3 else 8080
    start_exchange_client(host, port)
    socketio.run(app, host="127.0.0.1", port=web_port, allow_unsafe_werkzeug=True)
