import time
from client import ExchangeClient


def scenario_basic_match():
    print("\n=== Scenario 1: Basic match (SELL resting อยู่ก่อน แล้ว BUY เข้ามาชนราคาพอดี) ===")
    seller = ExchangeClient()
    seller.connect()
    time.sleep(0.3)

    buyer = ExchangeClient()
    buyer.connect()
    time.sleep(0.3)

    seller.send_new_order("SELL", 150.50, 10)
    time.sleep(0.5)
    buyer.send_new_order("BUY", 150.50, 10)
    time.sleep(0.5)


def scenario_partial_fill():
    print("\n=== Scenario 2: Partial fill (order ที่มาใหม่ขอมากกว่าที่มีอยู่ในตลาด) ===")
    seller = ExchangeClient()
    seller.connect()
    time.sleep(0.3)

    buyer = ExchangeClient()
    buyer.connect()
    time.sleep(0.3)

    seller.send_new_order("SELL", 151.00, 5)
    time.sleep(0.5)
    buyer.send_new_order("BUY", 151.00, 12)
    time.sleep(0.5)


def scenario_reject_invalid_order():
    print("\n=== Scenario 3: Reject invalid order (qty ติดลบ) ===")
    client = ExchangeClient()
    client.connect()
    time.sleep(0.3)
    client.send_new_order("BUY", 150.00, -5)
    time.sleep(0.5)


def scenario_cancel():
    print("\n=== Scenario 4: Cancel order ที่ยัง resting อยู่ ===")
    client = ExchangeClient()
    client.connect()
    time.sleep(0.3)
    coid = client.send_new_order("BUY", 149.00, 3)
    time.sleep(0.5)
    client.send_cancel_order(coid)
    time.sleep(0.5)


def scenario_cancel_not_found():
    print("\n=== Scenario 5: Cancel order ที่ไม่มีอยู่จริง ===")
    client = ExchangeClient()
    client.connect()
    time.sleep(0.3)
    client.send_cancel_order("ไม่มีจริง-999")
    time.sleep(0.5)


if __name__ == "__main__":
    scenario_basic_match()
    scenario_partial_fill()
    scenario_reject_invalid_order()
    scenario_cancel()
    scenario_cancel_not_found()
    print("\nทดสอบครบทุก scenario แล้ว")
