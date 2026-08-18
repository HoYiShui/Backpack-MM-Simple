from types import SimpleNamespace
from unittest.mock import patch

from api import ApiResponse, CancelResult
from strategies.market_maker import MarketMaker


class FlakyCancelClient:
    def __init__(self):
        self.remaining = {"1", "2"}
        self.individual_attempts = {"1": 0, "2": 0}

    @staticmethod
    def is_bot_cloid(_value):
        return True

    def get_open_orders(self, _symbol):
        orders = [SimpleNamespace(order_id=oid, client_order_id=f"bot-{oid}") for oid in sorted(self.remaining)]
        return ApiResponse.ok(orders)

    def cancel_all_orders(self, _symbol):
        return ApiResponse.error("synthetic TLS EOF")

    def cancel_order(self, order_id, _symbol):
        oid = str(order_id)
        self.individual_attempts[oid] += 1
        if oid == "2" and self.individual_attempts[oid] == 1:
            return ApiResponse.error("synthetic transient error")
        self.remaining.discard(oid)
        return ApiResponse.ok(CancelResult(success=True, order_id=oid, cancelled_count=1))


def test_cancel_existing_orders_requeries_and_retries_sequentially():
    maker = MarketMaker.__new__(MarketMaker)
    maker.client = FlakyCancelClient()
    maker.symbol = "BTC"
    maker.orders_cancelled = 0
    maker.active_buy_orders = [object()]
    maker.active_sell_orders = [object()]

    with patch("strategies.market_maker.time.sleep", return_value=None):
        assert maker.cancel_existing_orders()

    assert maker.client.remaining == set()
    assert maker.client.individual_attempts == {"1": 1, "2": 2}
    assert maker.active_buy_orders == []
    assert maker.active_sell_orders == []
