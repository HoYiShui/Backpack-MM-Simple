"""Read-only strategy snapshots for terminal presentation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional, Tuple


@dataclass(frozen=True)
class DashboardSnapshot:
    exchange: str
    symbol: str
    grid_type: str
    runtime_seconds: int
    ws_connected: bool
    last_price: float
    last_update: Optional[datetime]
    net_profit: float
    grid_profit: float
    realized_pnl: float
    fees: float
    maker_ratio: float
    net_position: float
    actual_leverage: Optional[float]
    max_position: float
    collateral: Optional[float]
    pending_close_quantity: float
    grid_lower: Optional[float]
    grid_upper: Optional[float]
    grid_spacing_min: Optional[float]
    grid_spacing_max: Optional[float]
    completed_grids: int
    locked_grids: int
    open_long_orders: int
    open_short_orders: int
    close_orders: int
    pending_retries: int
    active_orders: int
    bought: float
    sold: float
    quote_volume: float
    maker_volume: float
    taker_volume: float
    trades: int
    events: List[Tuple[datetime, int, str]] = field(default_factory=list)


def _nested_order_count(value: Any) -> int:
    try:
        return sum(len(orders) for orders in list(value.values()))
    except (AttributeError, RuntimeError, TypeError):
        return 0


def _grid_spacing(levels: Any) -> Tuple[Optional[float], Optional[float]]:
    try:
        copied = sorted(float(level) for level in list(levels))
    except (RuntimeError, TypeError, ValueError):
        return None, None
    gaps = [right - left for left, right in zip(copied, copied[1:]) if right > left]
    return (min(gaps), max(gaps)) if gaps else (None, None)


class SnapshotReader:
    """Build snapshots from already-cached strategy/WS state only."""

    def __init__(self, strategy: Any, event_handler: Any) -> None:
        self.strategy = strategy
        self.event_handler = event_handler
        self.collateral: Optional[float] = None

    def set_collateral(self, value: Optional[float]) -> None:
        self.collateral = value

    def read(self) -> DashboardSnapshot:
        strategy = self.strategy
        ws = getattr(strategy, "ws", None)
        ws_connected = bool(ws and ws.is_connected())
        last_price = float(getattr(ws, "last_price", 0.0) or 0.0)
        last_update_raw = max(
            float(getattr(ws, "last_ticker_update", 0.0) or 0.0),
            float(getattr(ws, "last_depth_update", 0.0) or 0.0),
        ) if ws else 0.0
        last_update = datetime.fromtimestamp(last_update_raw) if last_update_raw else None

        try:
            session_realized = float(strategy._calculate_session_profit())
        except Exception:
            session_realized = 0.0
        fees = float(getattr(strategy, "session_fees", 0.0) or 0.0)
        maker_volume = float(getattr(strategy, "session_maker_buy_volume", 0.0) or 0.0) + float(
            getattr(strategy, "session_maker_sell_volume", 0.0) or 0.0
        )
        taker_volume = float(getattr(strategy, "session_taker_buy_volume", 0.0) or 0.0) + float(
            getattr(strategy, "session_taker_sell_volume", 0.0) or 0.0
        )
        total_liquidity_volume = maker_volume + taker_volume
        maker_ratio = maker_volume / total_liquidity_volume if total_liquidity_volume else 0.0

        bought = sum(float(quantity) for _, quantity in list(getattr(strategy, "session_buy_trades", [])))
        sold = sum(float(quantity) for _, quantity in list(getattr(strategy, "session_sell_trades", [])))
        fill_derived_position = float(getattr(strategy, "total_bought", 0.0) or 0.0) - float(
            getattr(strategy, "total_sold", 0.0) or 0.0
        )
        # PerpGridStrategy refreshes this value from the venue during each
        # reconciliation pass, so prefer it to a fill-derived estimate.
        net_position = float(getattr(strategy, "last_position_snapshot", fill_derived_position) or 0.0)
        leverage = None
        if self.collateral and last_price:
            leverage = abs(net_position) * last_price / self.collateral

        levels = getattr(strategy, "grid_levels", [])
        spacing_min, spacing_max = _grid_spacing(levels)
        try:
            locked = sum(
                1 for state in list(getattr(strategy, "grid_level_states", {}).values())
                if state.get("locked", False)
            )
        except (AttributeError, RuntimeError):
            locked = 0

        pending = list(getattr(strategy, "pending_close_orders", []))
        pending_requests = getattr(strategy, "pending_close_requests", {})
        pending_quantity = sum(float(item[1]) for item in pending if len(item) > 1)
        try:
            pending_quantity += sum(float(value) for value in list(pending_requests.values()))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

        open_long = _nested_order_count(getattr(strategy, "open_long_orders", {}))
        open_short = _nested_order_count(getattr(strategy, "open_short_orders", {}))
        close_orders = len(getattr(strategy, "close_orders", {}))
        active_orders = len(getattr(strategy, "active_buy_orders", [])) + len(
            getattr(strategy, "active_sell_orders", [])
        )

        start = getattr(strategy, "session_start_time", datetime.now())
        runtime_seconds = max(0, int((datetime.now() - start).total_seconds()))
        return DashboardSnapshot(
            exchange=str(getattr(strategy, "exchange", "exchange")),
            symbol=str(getattr(strategy, "symbol", "?")),
            grid_type=str(getattr(strategy, "grid_type", "grid")),
            runtime_seconds=runtime_seconds,
            ws_connected=ws_connected,
            last_price=last_price,
            last_update=last_update,
            net_profit=session_realized - fees,
            grid_profit=float(getattr(strategy, "grid_profit", 0.0) or 0.0),
            realized_pnl=session_realized,
            fees=fees,
            maker_ratio=maker_ratio,
            net_position=net_position,
            actual_leverage=leverage,
            max_position=float(getattr(strategy, "max_position", 0.0) or 0.0),
            collateral=self.collateral,
            pending_close_quantity=pending_quantity,
            grid_lower=getattr(strategy, "grid_lower_price", None),
            grid_upper=getattr(strategy, "grid_upper_price", None),
            grid_spacing_min=spacing_min,
            grid_spacing_max=spacing_max,
            completed_grids=int(getattr(strategy, "grid_completed_count", 0) or 0),
            locked_grids=locked,
            open_long_orders=open_long,
            open_short_orders=open_short,
            close_orders=close_orders,
            pending_retries=len(pending),
            active_orders=active_orders,
            bought=bought,
            sold=sold,
            quote_volume=float(getattr(strategy, "session_quote_volume", 0.0) or 0.0),
            maker_volume=maker_volume,
            taker_volume=taker_volume,
            trades=int(getattr(strategy, "trades_executed", 0) or 0),
            events=self.event_handler.tail(3),
        )
