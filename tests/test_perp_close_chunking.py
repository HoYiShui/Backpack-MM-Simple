from decimal import Decimal
from types import SimpleNamespace

from api import ApiResponse
from strategies.perp_market_maker import PerpetualMarketMaker


def bare_maker(position=0.002, price=64000.0, max_notional=100):
    maker = PerpetualMarketMaker.__new__(PerpetualMarketMaker)
    maker.min_order_size = 0.00001
    maker.base_precision = 5
    maker.client = SimpleNamespace(max_order_notional=Decimal(str(max_notional)))
    maker.get_net_position = lambda: position
    maker.get_current_price = lambda: price
    maker._update_position_state = lambda: None
    return maker


def test_market_close_is_split_without_under_notional_tail():
    maker = bare_maker()
    submitted = []

    def submit(**kwargs):
        submitted.append(kwargs)
        return ApiResponse.ok(SimpleNamespace(order_id=str(len(submitted))))

    maker.open_position = submit

    assert maker.close_position(order_type="Market")
    assert [item["quantity"] for item in submitted] == [0.001, 0.001]
    assert all(item["reduce_only"] for item in submitted)
    assert all(item["side"] == "Ask" for item in submitted)


def test_market_close_below_cap_stays_single_order():
    maker = bare_maker(position=-0.001)
    submitted = []
    maker.open_position = lambda **kwargs: submitted.append(kwargs) or ApiResponse.ok(SimpleNamespace())

    assert maker.close_position(order_type="Market")
    assert [item["quantity"] for item in submitted] == [0.001]
    assert submitted[0]["side"] == "Bid"
