import logging
from collections import defaultdict
from datetime import datetime
from types import SimpleNamespace

from rich.console import Console

from tui.app import render_dashboard
from tui.events import RecentEventHandler, tui_logging
from tui.snapshot import SnapshotReader


class FakeStrategy:
    exchange = "hyperliquid"
    symbol = "BTC"
    grid_type = "neutral"
    session_start_time = datetime.now()
    session_fees = 0.6443
    session_maker_buy_volume = 0.023
    session_maker_sell_volume = 0.015
    session_taker_buy_volume = 0.001
    session_taker_sell_volume = 0.009
    session_buy_trades = [(63_000.0, 0.024)]
    session_sell_trades = [(63_100.0, 0.024)]
    total_bought = 0.024
    total_sold = 0.024
    grid_profit = 1.8858
    max_position = 0.075
    grid_lower_price = 60_676.0
    grid_upper_price = 67_063.0
    grid_levels = [60_676.0, 60_718.0, 60_761.0]
    grid_completed_count = 24
    grid_level_states = defaultdict(dict, {60_676.0: {"locked": True}})
    open_long_orders = {60_676.0: {"1": {}}}
    open_short_orders = {67_063.0: {"2": {}, "3": {}}}
    close_orders = {"4": {}}
    pending_close_orders = [(63_000.0, 0.00099, "long", 1)]
    pending_close_requests = {(63_100.0, "short"): 0.0005}
    active_buy_orders = [object(), object()]
    active_sell_orders = [object(), object(), object()]
    session_quote_volume = 3_031.25
    trades_executed = 50
    ws = SimpleNamespace(
        last_price=63_912.0,
        last_ticker_update=1_787_050_888.0,
        last_depth_update=1_787_050_889.0,
        is_connected=lambda: True,
    )

    @staticmethod
    def _calculate_session_profit():
        return 2.9926


def test_snapshot_maps_existing_strategy_state_without_network_calls():
    events = RecentEventHandler()
    events.handle(logging.makeLogRecord({"levelno": logging.INFO, "msg": "網格利潤實現: 0.0426 USDC"}))
    reader = SnapshotReader(FakeStrategy(), events)
    reader.set_collateral(800.0)

    snapshot = reader.read()

    assert snapshot.net_profit == 2.3483
    assert snapshot.maker_ratio == 0.038 / 0.048
    assert snapshot.grid_spacing_min == 42.0
    assert snapshot.grid_spacing_max == 43.0
    assert snapshot.open_long_orders == 1
    assert snapshot.open_short_orders == 2
    assert snapshot.pending_close_quantity == 0.00149
    assert snapshot.active_orders == 5
    assert snapshot.events[0][2].startswith("網格利潤實現")


def test_dashboard_contains_the_current_cli_metrics():
    reader = SnapshotReader(FakeStrategy(), RecentEventHandler())
    reader.set_collateral(800.0)
    console = Console(width=100, record=True)
    console.print(render_dashboard(reader.read()))
    output = console.export_text()

    assert "Hyperliquid Testnet · BTC · Neutral Grid" in output
    assert "淨利潤" in output
    assert "+2.3483 USDC" in output
    assert "42–43 USDC" in output
    assert "HyperCore 總單數" in output
    assert "Ctrl+C 安全退出" in output


def test_tui_logging_preserves_file_handlers_and_restores_console(tmp_path):
    logger = logging.getLogger("test_tui_logging")
    logger.handlers.clear()
    logger.propagate = False
    console = logging.StreamHandler()
    file_handler = logging.FileHandler(tmp_path / "events.log", encoding="utf-8")
    logger.addHandler(console)
    logger.addHandler(file_handler)
    capture = RecentEventHandler()

    with tui_logging(capture):
        assert console not in logger.handlers
        assert file_handler in logger.handlers
        logger.warning("WebSocket 暫時中斷")

    assert console in logger.handlers
    assert file_handler in logger.handlers
    assert capture.tail()[0][2] == "WebSocket 暫時中斷"
    logger.handlers.clear()
    file_handler.close()
