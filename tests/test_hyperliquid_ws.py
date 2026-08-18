import json
from decimal import Decimal

from strategies.market_maker import MarketMaker
from ws_client.hyperliquid_ws_client import HyperliquidWebSocket


class DummyRest:
    pass


def make_ws(callback=None):
    return HyperliquidWebSocket(
        account_address="0x" + "22" * 20,
        symbol="BTC_USDC",
        rest_client=DummyRest(),
        on_message_callback=callback,
    )


def test_subscription_messages_use_account_and_coin():
    ws = make_ws()
    assert ws._create_subscribe_message("bbo") == {
        "method": "subscribe",
        "subscription": {"type": "bbo", "coin": "BTC"},
    }
    assert ws._create_subscribe_message("userFills", True)["subscription"]["user"].startswith("0x")


def test_bbo_and_book_parsing():
    ws = make_ws()
    ticker = ws._handle_ticker_message(
        {"channel": "bbo", "data": {"coin": "BTC", "time": 1, "bbo": [{"px": "10", "sz": "1"}, {"px": "12", "sz": "2"}]}}
    )
    assert ticker.bid_price == Decimal("10")
    assert ticker.ask_price == Decimal("12")
    assert ticker.last_price == Decimal("11")

    book = ws._handle_depth_message(
        {"channel": "l2Book", "data": {"coin": "BTC", "time": 2, "levels": [[{"px": "10", "sz": "1"}], [{"px": "12", "sz": "2"}]]}}
    )
    assert book.bids == [(Decimal("10"), Decimal("1"))]
    assert book.asks == [(Decimal("12"), Decimal("2"))]


def test_snapshot_fills_are_ignored():
    ws = make_ws()
    assert ws._handle_fill_message(
        {"channel": "userFills", "data": {"isSnapshot": True, "fills": [{"tid": 1}]}}
    ) is None


def test_batched_partial_fills_are_fanned_out():
    received = []
    ws = make_ws(lambda stream, data: received.append((stream, data)))
    fills = [
        {"coin": "BTC", "px": "10", "sz": "0.5", "side": "B", "time": 1, "oid": 7, "tid": 11, "fee": "0", "crossed": False},
        {"coin": "BTC", "px": "10", "sz": "0.5", "side": "B", "time": 1, "oid": 7, "tid": 12, "fee": "0", "crossed": False},
    ]
    ws._on_message(None, json.dumps({"channel": "userFills", "data": {"isSnapshot": False, "fills": fills}}))
    assert len(received) == 2
    parsed = [ws._handle_fill_message(item[1]) for item in received]
    assert [item.fill_id for item in parsed] == ["1:BTC:11", "1:BTC:12"]
    assert sum((item.quantity for item in parsed), Decimal("0")) == Decimal("1.0")


def test_order_update_maps_partial_and_cancelled():
    ws = make_ws()
    partial = ws._handle_order_update_message(
        {"channel": "orderUpdates", "data": {"status": "open", "statusTimestamp": 2, "order": {"coin": "BTC", "side": "B", "limitPx": "10", "sz": "0.5", "origSz": "1", "oid": 7}}}
    )
    assert partial.status == "PARTIALLY_FILLED"
    assert partial.filled_quantity == Decimal("0.5")

    cancelled = ws._handle_order_update_message(
        {"channel": "orderUpdates", "data": {"status": "canceled", "order": {"coin": "BTC", "side": "A", "limitPx": "10", "sz": "1", "origSz": "1", "oid": 8}}}
    )
    assert cancelled.status == "CANCELLED"


def test_market_maker_does_not_double_count_hyperliquid_order_update():
    class Parser:
        def _handle_fill_message(self, _data):
            return None

        def _handle_order_update_message(self, _data):
            return type(
                "Update",
                (),
                {
                    "status": "FILLED",
                    "order_id": "7",
                    "filled_quantity": Decimal("1"),
                    "quantity": Decimal("1"),
                    "price": Decimal("100"),
                    "side": "BUY",
                },
            )()

    maker = MarketMaker.__new__(MarketMaker)
    maker.exchange = "hyperliquid"
    maker.ws = Parser()
    maker.private_ws = None

    def fail_if_called(**_kwargs):
        raise AssertionError("orderUpdates must not be counted as fills")

    maker._process_order_fill_event = fail_if_called
    maker.on_ws_message("orderUpdates", {})
