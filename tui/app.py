"""Textual application for the first, read-only trading dashboard."""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Optional

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Static

from .events import RecentEventHandler, tui_logging
from .snapshot import DashboardSnapshot, SnapshotReader


def _number(value: Optional[float], decimals: int = 4) -> str:
    if value is None:
        return "--"
    return f"{value:,.{decimals}f}"


def _price(value: Optional[float]) -> str:
    if not value:
        return "--"
    decimals = 0 if abs(value) >= 1_000 else 4
    return _number(value, decimals)


def _spacing(value: Optional[float]) -> str:
    if value is None:
        return "--"
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.4f}".rstrip("0").rstrip(".")


def _quantity(value: float, asset: str) -> str:
    return f"{value:,.5f} {asset}"


def _duration(seconds: int) -> str:
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _signed(value: float, asset: str) -> Text:
    color = "green" if value >= 0 else "red"
    return Text(f"{value:+,.4f} {asset}", style=f"bold {color}")


def _kv_table(rows: list[tuple[str, RenderableType]]) -> Table:
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(style="dim", ratio=2)
    table.add_column(justify="right", ratio=3)
    for label, value in rows:
        table.add_row(label, value)
    return table


def _two_column(left_title: str, left: Table, right_title: str, right: Table) -> Table:
    section = Table.grid(expand=True, padding=(0, 2))
    section.add_column(ratio=1)
    section.add_column(ratio=1)
    section.add_row(
        Panel(left, title=left_title, title_align="center", border_style="bright_black", padding=(0, 1)),
        Panel(right, title=right_title, title_align="center", border_style="bright_black", padding=(0, 1)),
    )
    return section


def render_dashboard(snapshot: DashboardSnapshot, stopping: bool = False) -> Panel:
    base = snapshot.symbol.split("_")[0].split("-")[0]
    quote = "USDC"
    exchange = snapshot.exchange.replace("hyperliquid", "Hyperliquid Testnet").title()
    grid_type = snapshot.grid_type.capitalize()

    connection = Text("● 已連接", style="bold green") if snapshot.ws_connected else Text("● 未連接", style="bold red")
    status = Table.grid(expand=True)
    status.add_column(ratio=2)
    status.add_column(justify="center", ratio=2)
    status.add_column(justify="center", ratio=2)
    status.add_column(justify="right", ratio=2)
    update = snapshot.last_update.strftime("%H:%M:%S") if snapshot.last_update else "--:--:--"
    status.add_row(
        Text.assemble("WS ", connection),
        f"最新價 {_price(snapshot.last_price)}",
        f"更新 {update}",
        Text("正在安全退出…", style="bold yellow") if stopping else Text("Ctrl+C 安全退出", style="dim"),
    )

    profit = _kv_table([
        ("淨利潤", _signed(snapshot.net_profit, quote)),
        ("網格毛利潤", _signed(snapshot.grid_profit, quote)),
        ("已實現盈虧", _signed(snapshot.realized_pnl, quote)),
        ("手續費", Text(f"-{abs(snapshot.fees):,.4f} {quote}", style="red")),
        ("Maker 占比", f"{snapshot.maker_ratio * 100:,.1f}%"),
    ])
    risk = _kv_table([
        ("淨倉位", _quantity(snapshot.net_position, base)),
        ("實際槓桿", "--" if snapshot.actual_leverage is None else f"{snapshot.actual_leverage:.2f}x"),
        ("最大倉位", _quantity(snapshot.max_position, base)),
        ("保證金", "--" if snapshot.collateral is None else f"{snapshot.collateral:,.2f} {quote}"),
        ("待平倉量", _quantity(snapshot.pending_close_quantity, base)),
    ])

    if snapshot.grid_spacing_min is None:
        spacing = "--"
    elif abs((snapshot.grid_spacing_max or 0) - snapshot.grid_spacing_min) < 1e-9:
        spacing = f"{_spacing(snapshot.grid_spacing_min)} {quote}"
    else:
        spacing = f"{_spacing(snapshot.grid_spacing_min)}–{_spacing(snapshot.grid_spacing_max)} {quote}"
    grid = _kv_table([
        ("範圍", f"{_price(snapshot.grid_lower)} ── {_price(snapshot.grid_upper)}"),
        ("當前價格", _price(snapshot.last_price)),
        ("網格間距", spacing),
        ("已完成網格", str(snapshot.completed_grids)),
        ("鎖定網格", str(snapshot.locked_grids)),
    ])
    orders = _kv_table([
        ("開多單", str(snapshot.open_long_orders)),
        ("開空單", str(snapshot.open_short_orders)),
        ("平倉單", str(snapshot.close_orders)),
        ("待重試", str(snapshot.pending_retries)),
        ("HyperCore 總單數", str(snapshot.active_orders)),
    ])

    fills = Table.grid(expand=True, padding=(0, 1))
    fills.add_column(justify="center", ratio=1)
    fills.add_column(justify="center", ratio=1)
    fills.add_column(justify="center", ratio=2)
    fills.add_row(
        f"買入 {_quantity(snapshot.bought, base)}",
        f"賣出 {_quantity(snapshot.sold, base)}",
        f"成交額 {snapshot.quote_volume:,.2f} {quote}",
    )
    fills.add_row(
        f"Maker {_quantity(snapshot.maker_volume, base)}",
        f"Taker {_quantity(snapshot.taker_volume, base)}",
        f"成交 {snapshot.trades} 次",
    )

    event_lines = []
    if snapshot.events:
        for timestamp, level, message in snapshot.events:
            style = "red" if level >= logging.ERROR else "yellow" if level >= logging.WARNING else "cyan"
            event_lines.append(Text(f"{timestamp:%H:%M:%S} {message}", style=style, overflow="ellipsis", no_wrap=True))
    else:
        event_lines.append(Text("等待成交或策略事件…", style="dim"))
    while len(event_lines) < 3:
        event_lines.append(Text(""))

    body = Group(
        status,
        Rule(style="bright_black"),
        _two_column("收益", profit, "風險與倉位", risk),
        _two_column("網格", grid, "訂單", orders),
        Panel(fills, title="成交", title_align="center", border_style="bright_black", padding=(0, 1)),
        Panel(Group(*event_lines), title="最近事件", title_align="center", border_style="bright_black", padding=(0, 1)),
    )
    title = f"{exchange} · {snapshot.symbol} · {grid_type} Grid ── 運行 {_duration(snapshot.runtime_seconds)}"
    return Panel(body, title=title, title_align="left", border_style="cyan", padding=(0, 1))


class TradingDashboardApp(App[None]):
    TITLE = "Grid Trading Dashboard"
    CSS = """
    Screen {
        background: #101419;
        align: center middle;
    }
    #dashboard {
        width: 96%;
        max-width: 110;
        height: auto;
        max-height: 100%;
    }
    """
    BINDINGS = [
        Binding("ctrl+c", "request_stop", "安全退出", show=False, priority=True),
        Binding("q", "request_stop", "安全退出", show=False),
    ]

    def __init__(self, strategy: Any, duration_seconds: int, interval_seconds: int, events: RecentEventHandler) -> None:
        super().__init__()
        self.strategy = strategy
        self.duration_seconds = duration_seconds
        self.interval_seconds = interval_seconds
        self.reader = SnapshotReader(strategy, events)
        self._bot_thread: Optional[threading.Thread] = None
        self._balance_thread: Optional[threading.Thread] = None
        self._background_stop = threading.Event()
        self._bot_exception: Optional[BaseException] = None
        self._stopping = False

    def compose(self) -> ComposeResult:
        yield Static(id="dashboard")

    def on_mount(self) -> None:
        self._bot_thread = threading.Thread(target=self._run_strategy, name="trading-strategy", daemon=True)
        self._balance_thread = threading.Thread(target=self._sample_collateral, name="tui-collateral", daemon=True)
        self._bot_thread.start()
        self._balance_thread.start()
        self.set_interval(0.5, self._refresh_dashboard)
        self._refresh_dashboard()

    def _run_strategy(self) -> None:
        try:
            self.strategy.run(self.duration_seconds, self.interval_seconds)
        except BaseException as exc:
            self._bot_exception = exc

    def _sample_collateral(self) -> None:
        while not self._background_stop.is_set():
            try:
                response = self.strategy.client.get_collateral()
                if response.success and response.data:
                    item = response.data[0] if isinstance(response.data, list) else response.data
                    raw = getattr(item, "raw", None)
                    margin_summary = raw.get("marginSummary", {}) if isinstance(raw, dict) else {}
                    value = margin_summary.get("accountValue")
                    if value is None:
                        value = getattr(item, "account_value", None)
                    if value is None:
                        value = getattr(item, "total_collateral", None)
                    self.reader.set_collateral(float(value) if value is not None else None)
            except Exception:
                pass
            self._background_stop.wait(30.0)

    def _refresh_dashboard(self) -> None:
        snapshot = self.reader.read()
        self.query_one("#dashboard", Static).update(render_dashboard(snapshot, self._stopping))
        if self._bot_thread and not self._bot_thread.is_alive():
            self._background_stop.set()
            self.exit()

    def action_request_stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        self.strategy.stop()
        self._refresh_dashboard()

    def on_unmount(self) -> None:
        self._background_stop.set()
        if self._bot_thread and self._bot_thread.is_alive():
            self.strategy.stop()


def run_tui(strategy: Any, duration_seconds: int, interval_seconds: int) -> None:
    """Run the dashboard and surface strategy failures after terminal restore."""
    events = RecentEventHandler()
    app = TradingDashboardApp(strategy, duration_seconds, interval_seconds, events)
    try:
        with tui_logging(events):
            app.run(mouse=False)
    finally:
        # Do not leave a daemonized trading loop behind if Textual itself is
        # interrupted. The strategy's original finally block owns cancel,
        # optional close-on-exit, WebSocket and database cleanup.
        app._background_stop.set()
        if app._bot_thread and app._bot_thread.is_alive():
            strategy.stop()
            while app._bot_thread.is_alive():
                app._bot_thread.join(timeout=0.25)
    if app._bot_exception is not None:
        raise app._bot_exception
