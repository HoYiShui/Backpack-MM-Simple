from decimal import Decimal
from unittest.mock import patch

import pytest

from api.hyperliquid_client import BOT_CLOID_MAGIC, HyperliquidClient


TEST_KEY = "0x" + "11" * 32


class FakeInfo:
    def __init__(self, *args, **kwargs):
        self.orders = []
        self.fills = []

    def meta_and_asset_ctxs(self):
        return (
            {"universe": [{"name": "BTC", "szDecimals": 5, "maxLeverage": 40}]},
            [{"markPx": "32804", "oraclePx": "32800", "dayNtlVlm": "1000"}],
        )

    def frontend_open_orders(self, address):
        return list(self.orders)

    def open_orders(self, address):
        return list(self.orders)

    def all_mids(self):
        return {"BTC": "32804"}

    def l2_snapshot(self, coin):
        return {
            "coin": coin,
            "time": 1234,
            "levels": [
                [{"px": "32803", "sz": "1", "n": 1}],
                [{"px": "32805", "sz": "2", "n": 1}],
            ],
        }

    def spot_user_state(self, address):
        return {"balances": [{"coin": "USDC", "total": "999", "hold": "1.5"}]}

    def user_state(self, address):
        return {
            "marginSummary": {"totalMarginUsed": "1.5"},
            "assetPositions": [],
        }

    def user_fills(self, address):
        return list(self.fills)

    def candles_snapshot(self, coin, interval, start, end):
        return []

    def post(self, endpoint, payload):
        return {"ok": True}


class FakeAPI:
    def __init__(self, *args, **kwargs):
        pass

    def post(self, endpoint, payload):
        if payload.get("type") == "meta":
            return {"universe": [{"name": "BTC", "szDecimals": 5, "maxLeverage": 40}]}
        if payload.get("type") == "spotMeta":
            return {"tokens": [], "universe": []}
        return {}


class FakeExchange:
    def __init__(self, *args, **kwargs):
        self.calls = []

    def order(self, *args, **kwargs):
        self.calls.append(("order", args, kwargs))
        return {
            "status": "ok",
            "response": {"data": {"statuses": [{"resting": {"oid": 101}}]}},
        }

    def bulk_orders(self, requests):
        self.calls.append(("bulk_orders", requests, {}))
        return {
            "status": "ok",
            "response": {
                "data": {
                    "statuses": [
                        {"resting": {"oid": 201}},
                        {"error": "synthetic rejection"},
                    ]
                }
            },
        }

    def cancel(self, coin, oid):
        self.calls.append(("cancel", (coin, oid), {}))
        return {"status": "ok", "response": {"data": {"statuses": ["success"]}}}

    def bulk_cancel(self, requests):
        self.calls.append(("bulk_cancel", requests, {}))
        return {
            "status": "ok",
            "response": {"data": {"statuses": ["success" for _ in requests]}},
        }

    def market_close(self, *args, **kwargs):
        self.calls.append(("market_close", args, kwargs))
        return {
            "status": "ok",
            "response": {"data": {"statuses": [{"filled": {"oid": 301, "totalSz": str(kwargs["sz"]), "avgPx": "32804"}}]}},
        }


@pytest.fixture
def client():
    with patch("api.hyperliquid_client.API", FakeAPI), patch("api.hyperliquid_client.Info", FakeInfo), patch(
        "api.hyperliquid_client.Exchange", FakeExchange
    ):
        yield HyperliquidClient(
            {
                "account_address": "0x" + "22" * 20,
                "signer_private_key": TEST_KEY,
                "base_url": "https://api.hyperliquid-testnet.xyz",
                "allow_orders": True,
                "max_order_notional": "1000",
            }
        )


def test_mainnet_is_rejected_by_default():
    with pytest.raises(ValueError, match="Mainnet"):
        HyperliquidClient(
            {
                "account_address": "0x" + "22" * 20,
                "base_url": "https://api.hyperliquid.xyz",
            }
        )


def test_hyperliquid_precision_is_side_directed(client):
    assert client.normalize_size("BTC_USDC", "0.001239") == Decimal("0.00123")
    assert client.normalize_price("BTC", "32804.9", is_buy=True) == Decimal("32804")
    assert client.normalize_price("BTC", "32804.1", is_buy=False) == Decimal("32805")


def test_cloid_is_namespaced_and_client_id_is_idempotent(client):
    first = client._new_cloid("grid:BTC:1:buy").to_raw()
    second = client._new_cloid("grid:BTC:1:buy").to_raw()
    assert first == second
    assert first.startswith(f"0x{BOT_CLOID_MAGIC}")
    assert len(first) == 34


def test_limit_order_uses_alo_and_returns_oid_and_cloid(client):
    response = client.execute_order(
        {
            "symbol": "BTC_USDC",
            "side": "Bid",
            "quantity": "0.001",
            "price": "32804.9",
            "orderType": "Limit",
            "postOnly": True,
            "clientId": "grid:BTC:1:buy",
        }
    )
    assert response.success
    assert response.data.order_id == "101"
    assert response.data.price == Decimal("32804")
    assert HyperliquidClient.is_bot_cloid(response.data.client_order_id)
    call = client.exchange.calls[-1]
    assert call[0] == "order"
    assert call[1][4] == {"limit": {"tif": "Alo"}}
    assert "builder" not in call[2]


def test_reduce_only_full_close_can_be_below_minimum_notional(client):
    close = client.execute_order(
        {
            "symbol": "BTC",
            "side": "Ask",
            "quantity": "0.00004",
            "orderType": "Market",
            "reduceOnly": True,
        }
    )
    opening = client.execute_order(
        {
            "symbol": "BTC",
            "side": "Bid",
            "quantity": "0.00004",
            "orderType": "Market",
            "reduceOnly": False,
        }
    )

    assert close.success
    assert not opening.success
    assert "最低要求" in opening.error_message


def test_batch_preserves_partial_success(client):
    response = client.execute_order_batch(
        [
            {"symbol": "BTC", "side": "Bid", "quantity": "0.001", "price": "32000", "postOnly": True},
            {"symbol": "BTC", "side": "Ask", "quantity": "0.001", "price": "34000", "postOnly": True},
        ]
    )
    assert response.success
    assert [order.order_id for order in response.data.orders] == ["201"]
    assert response.data.failed_count == 1


def test_projected_open_order_exposure_is_bounded(client):
    client.max_position = Decimal("0.001")
    response = client.execute_order_batch(
        [
            {"symbol": "BTC", "side": "Bid", "quantity": "0.001", "price": "32000"},
            {"symbol": "BTC", "side": "Bid", "quantity": "0.001", "price": "31900"},
        ]
    )
    assert not response.success
    assert "max_position" in response.error_message


def test_manual_order_cannot_be_cancelled(client):
    client.info.orders = [
        {
            "coin": "BTC", "side": "B", "limitPx": "32000", "sz": "0.001",
            "origSz": "0.001", "oid": 999, "cloid": None, "timestamp": 1,
            "reduceOnly": False, "orderType": "Limit", "tif": "Gtc",
        }
    ]
    response = client.cancel_order("999", "BTC")
    assert not response.success
    assert not client.exchange.calls


def test_cancel_all_only_cancels_bot_orders(client):
    bot_cloid = client._new_cloid().to_raw()
    base = {
        "coin": "BTC", "side": "B", "limitPx": "32000", "sz": "0.001",
        "origSz": "0.001", "timestamp": 1, "reduceOnly": False,
        "orderType": "Limit", "tif": "Gtc",
    }
    client.info.orders = [
        {**base, "oid": 1, "cloid": bot_cloid},
        {**base, "oid": 2, "cloid": None},
    ]
    response = client.cancel_all_orders("BTC")
    assert response.success
    assert response.data.cancelled_count == 1
    assert client.exchange.calls[-1][1] == [{"coin": "BTC", "oid": 1}]


def test_unified_balance_and_fill_evidence_mapping(client):
    collateral = client.get_collateral()
    assert collateral.success
    assert collateral.data[0].total_collateral == Decimal("999")
    assert collateral.data[0].free_collateral == Decimal("997.5")

    client.info.fills = [
        {
            "coin": "BTC", "px": "32804", "sz": "0.001", "side": "B",
            "time": 123456, "oid": 7, "tid": 42, "fee": "0.01",
            "feeToken": "USDC", "crossed": False, "hash": "0xabc",
        }
    ]
    fills = client.get_fill_history("BTC")
    assert fills.success
    assert fills.data[0].trade_id == "123456:BTC:42"
    assert fills.data[0].raw["hash"] == "0xabc"
    assert fills.data[0].is_maker is True


def test_live_orders_require_explicit_gate():
    with patch("api.hyperliquid_client.API", FakeAPI), patch("api.hyperliquid_client.Info", FakeInfo), patch(
        "api.hyperliquid_client.Exchange", FakeExchange
    ):
        read_only = HyperliquidClient(
            {
                "account_address": "0x" + "22" * 20,
                "signer_private_key": TEST_KEY,
                "base_url": "https://api.hyperliquid-testnet.xyz",
            }
        )
    response = read_only.execute_order(
        {"symbol": "BTC", "side": "Bid", "quantity": "0.001", "price": "32000"}
    )
    assert not response.success
    assert "confirm-live-testnet" in response.error_message
