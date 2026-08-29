import json
import time

PROTOCOL_NAME = "MOEP/1.0"

MSG_REGISTER = "REGISTER"
MSG_ORDER_NEW = "ORDER_NEW"
MSG_ORDER_CANCEL = "ORDER_CANCEL"
MSG_GAP_FILL_REQUEST = "GAP_FILL_REQUEST"

MSG_REGISTER_ACK = "REGISTER_ACK"
MSG_ORDER_ACK = "ORDER_ACK"
MSG_CANCEL_ACK = "CANCEL_ACK"
MSG_GAP_FILL_RESPONSE = "GAP_FILL_RESPONSE"

MSG_MARKET_DATA = "MARKET_DATA"
MSG_TRADE = "TRADE"

SIDE_BUY = "BUY"
SIDE_SELL = "SELL"

STATUS_CODES = {
    200: "OK",
    201: "MATCHED",
    202: "PARTIAL_FILL",
    204: "CANCELLED",
    400: "BAD_REQUEST",
    403: "REJECTED",
    404: "NOT_FOUND",
    410: "GONE",
    500: "INTERNAL_ERROR",
}


def status_phrase(code: int) -> str:
    return STATUS_CODES.get(code, "UNKNOWN_STATUS")


def build_message(msg_type: str, **fields) -> dict:
    msg = {"type": msg_type, "ts": time.time()}
    msg.update(fields)
    return msg


def build_response(msg_type: str, status_code: int, **fields) -> dict:
    msg = build_message(msg_type, status_code=status_code, status_phrase=status_phrase(status_code))
    msg.update(fields)
    return msg


def encode_tcp(msg: dict) -> bytes:
    return (json.dumps(msg) + "\n").encode("utf-8")


def decode_tcp(line: str) -> dict:
    return json.loads(line.strip())


def encode_udp(msg: dict) -> bytes:
    return json.dumps(msg).encode("utf-8")


def decode_udp(data: bytes) -> dict:
    return json.loads(data.decode("utf-8"))
