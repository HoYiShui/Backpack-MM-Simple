from collections import defaultdict
from decimal import Decimal
from types import SimpleNamespace

from api.base_client import TradeInfo
from strategies.perp_grid_strategy import PerpGridStrategy


def bare_strategy():
    strategy = PerpGridStrategy.__new__(PerpGridStrategy)
    strategy.open_long_orders = defaultdict(dict)
    strategy.open_short_orders = defaultdict(dict)
    strategy.close_orders = {}
    strategy.order_alias_map = {}
    strategy.order_aliases_by_primary = {}
    strategy.grid_level_states = defaultdict(
        lambda: {"locked": False, "open_position": 0.0, "close_order_ids": []}
    )
    strategy.pending_close_requests = defaultdict(float)
    strategy.grid_long_filled_count = 0
    strategy.grid_short_filled_count = 0
    strategy.grid_profit = 0.0
    strategy.quote_asset = "USDC"
    strategy.min_order_size = 0.001
    strategy.base_precision = 3
    strategy.order_quantity = 1.0
    strategy.exchange = "hyperliquid"
    strategy.ws = None
    strategy._iteration_id = 2
    strategy._orders_placed_this_iteration = set()
    strategy._manually_cancelled_orders = set()
    strategy.price_offset_cancelled = {}
    strategy.pending_close_orders = []
    strategy.max_close_order_retries = 3
    strategy.client = SimpleNamespace(min_order_notional=Decimal("10"))
    return strategy


def fill(order_id, size):
    return TradeInfo(
        trade_id=f"t-{order_id}-{size}",
        order_id=str(order_id),
        symbol="BTC",
        side="BUY",
        size=Decimal(str(size)),
        price=Decimal("100"),
    )


def test_open_partial_fills_accumulate_exact_close_quantity():
    strategy = bare_strategy()
    strategy._record_open_order("7", 100.0, "Bid", 1.0, aliases=["0xabc"])

    strategy._handle_open_order_filled("7", 100.0, "Bid", 0.4)
    assert strategy.open_long_orders[100.0]["7"]["filled_quantity"] == 0.4
    assert strategy.pending_close_requests[(100.0, "long")] == 0.4
    assert strategy.grid_level_states[100.0]["open_position"] == 0.4

    strategy._handle_open_order_filled("7", 100.0, "Bid", 0.6)
    assert 100.0 not in strategy.open_long_orders
    assert strategy.pending_close_requests[(100.0, "long")] == 1.0
    assert strategy.grid_level_states[100.0]["open_position"] == 1.0


def test_hyperliquid_under_notional_partial_fill_waits_for_accumulation():
    strategy = bare_strategy()
    strategy.min_order_size = 0.00001
    strategy.base_precision = 5
    strategy.pending_close_requests[(64034.0, "long")] = 0.00003
    placed = []
    strategy._place_close_order = lambda *args, **kwargs: placed.append((args, kwargs))

    strategy._flush_close_requests()

    assert placed == []
    assert strategy.pending_close_requests[(64034.0, "long")] == 0.00003

    strategy.pending_close_requests[(64034.0, "long")] += 0.0004
    strategy._flush_close_requests()

    assert placed == [((64034.0, 0.00043, "long"), {"retry_count": 0})]
    assert (64034.0, "long") not in strategy.pending_close_requests


def test_under_notional_retry_returns_to_accumulator():
    strategy = bare_strategy()
    strategy.min_order_size = 0.00001
    strategy.base_precision = 5

    strategy._add_pending_close_order(64034.0, 0.00003, "long", 1)

    assert strategy.pending_close_orders == []
    assert strategy.pending_close_requests[(64034.0, "long")] == 0.00003


def test_close_partial_fills_keep_remaining_order_until_complete():
    strategy = bare_strategy()
    strategy.grid_level_states[100.0] = {
        "locked": True,
        "open_position": 1.0,
        "close_order_ids": ["8"],
    }
    strategy.close_orders["8"] = {
        "open_price": 100.0,
        "quantity": 1.0,
        "filled_quantity": 0.0,
        "position_type": "long",
        "alias_ids": {"8"},
    }
    strategy.order_alias_map["8"] = "8"
    strategy.order_aliases_by_primary["8"] = {"8"}

    strategy._handle_close_order_filled("8", 101.0, "Ask", 0.4)
    assert strategy.close_orders["8"]["filled_quantity"] == 0.4
    assert strategy.grid_level_states[100.0]["open_position"] == 0.6
    assert strategy.grid_profit == 0.4

    strategy._handle_close_order_filled("8", 101.0, "Ask", 0.6)
    assert "8" not in strategy.close_orders
    assert strategy.grid_completed_count == 1
    assert strategy.grid_level_states[100.0]["locked"] is False
    assert strategy.grid_level_states[100.0]["open_position"] == 0.0
    assert strategy.grid_profit == 1.0


def test_disappeared_partially_filled_open_order_only_applies_rest_delta():
    strategy = bare_strategy()
    strategy._record_open_order("7", 100.0, "Bid", 1.0)
    strategy._handle_open_order_filled("7", 100.0, "Bid", 0.25)

    strategy._detect_filled_orders_from_exchange([], [fill("7", 0.25), fill("7", 0.15)])

    assert 100.0 not in strategy.open_long_orders
    assert strategy.pending_close_requests[(100.0, "long")] == 0.4
    assert strategy.grid_level_states[100.0]["open_position"] == 0.4


def test_disappeared_partially_filled_close_retries_only_unfilled_remainder():
    strategy = bare_strategy()
    strategy.grid_level_states[100.0] = {
        "locked": True,
        "open_position": 1.0,
        "close_order_ids": ["8"],
    }
    strategy.close_orders["8"] = {
        "open_price": 100.0,
        "quantity": 1.0,
        "filled_quantity": 0.25,
        "position_type": "long",
        "alias_ids": {"8"},
        "created_iteration": 1,
    }
    strategy.order_alias_map["8"] = "8"
    strategy.order_aliases_by_primary["8"] = {"8"}

    strategy._detect_filled_orders_from_exchange([], [fill("8", 0.25), fill("8", 0.15)])

    assert "8" not in strategy.close_orders
    assert strategy.grid_level_states[100.0]["open_position"] == 0.85
    assert strategy.grid_profit == 0.0
    assert strategy.pending_close_orders == [(100.0, 0.6, "long", 1)]


def test_grid_levels_use_exchange_canonical_directional_prices():
    strategy = bare_strategy()
    strategy.auto_price_range = True
    strategy.price_range_percent = 0.05
    strategy.grid_upper_price = None
    strategy.grid_lower_price = None
    strategy.grid_num = 6
    strategy.grid_mode = "arithmetic"
    strategy.grid_type = "neutral"
    strategy.tick_size = 0.1
    strategy.symbol = "BTC"
    strategy.get_current_price = lambda: 64125.0

    class Client:
        @staticmethod
        def get_ticker(_symbol):
            return SimpleNamespace(
                success=True,
                data=SimpleNamespace(last_price=Decimal("64125")),
                error_message=None,
            )

        @staticmethod
        def normalize_price(_symbol, price, is_buy):
            whole = int(price)
            if not is_buy and price != whole:
                whole += 1
            return Decimal(whole)

    strategy.client = Client()
    assert strategy._initialize_grid_prices()
    assert strategy.grid_levels == [64092.0, 64105.0, 64118.0, 64132.0, 64145.0, 64158.0]


def test_opening_order_quantities_exclude_reduce_only_orders():
    orders = [
        SimpleNamespace(side="BUY", remaining_size=Decimal("0.001"), reduce_only=False),
        SimpleNamespace(side="SELL", remaining_size=Decimal("0.00078"), reduce_only=False),
        SimpleNamespace(side="SELL", remaining_size=Decimal("0.002"), reduce_only=True),
    ]

    assert PerpGridStrategy._opening_order_quantities(orders) == (0.001, 0.00078)
