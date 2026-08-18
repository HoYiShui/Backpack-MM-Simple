"""Hyperliquid public/private WebSocket adapter."""
from __future__ import annotations

import json
import threading
import time
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from api.hyperliquid_client import HyperliquidClient
from .base_ws_client import (
    BaseWebSocketClient,
    WSConnectionConfig,
    WSFillData,
    WSOrderBookData,
    WSOrderUpdateData,
    WSTickerData,
)


class HyperliquidWebSocket(BaseWebSocketClient):
    def __init__(
        self,
        account_address: str,
        symbol: str,
        rest_client: HyperliquidClient,
        ws_url: str = "wss://api.hyperliquid-testnet.xyz/ws",
        on_message_callback=None,
        auto_reconnect: bool = True,
    ):
        self.account_address = account_address
        self.coin = HyperliquidClient.normalize_symbol(symbol)
        self.rest_client = rest_client
        config = WSConnectionConfig(
            ws_url=ws_url,
            auto_reconnect=auto_reconnect,
            reconnect_delay=1.0,
            max_reconnect_delay=30.0,
            max_reconnect_attempts=5,
            heartbeat_interval=30,
            ping_interval=20,
            ping_timeout=10,
        )
        super().__init__(config, self.coin, on_message_callback)

    def get_exchange_name(self) -> str:
        return "Hyperliquid"

    def _create_auth_message(self) -> Optional[Dict[str, Any]]:
        return None

    def _subscription(self, channel: str) -> Dict[str, Any]:
        if channel in ("bbo", "l2Book"):
            return {"type": channel, "coin": self.coin}
        if channel in ("orderUpdates", "userFills"):
            return {"type": channel, "user": self.account_address}
        raise ValueError(f"未知 Hyperliquid WebSocket 頻道: {channel}")

    def _create_subscribe_message(self, channel: str, is_private: bool = False) -> Dict[str, Any]:
        return {"method": "subscribe", "subscription": self._subscription(channel)}

    def _create_unsubscribe_message(self, channel: str) -> Dict[str, Any]:
        return {"method": "unsubscribe", "subscription": self._subscription(channel)}

    def _parse_message(self, raw_message: str) -> Optional[Tuple[str, Any]]:
        try:
            message = json.loads(raw_message)
        except (TypeError, json.JSONDecodeError):
            return None
        self.last_heartbeat = time.time()
        channel = str(message.get("channel") or "")
        if not channel or channel == "subscriptionResponse":
            return None
        return channel, message

    def _get_ticker_channel(self) -> str:
        return "bbo"

    def _get_depth_channel(self) -> str:
        return "l2Book"

    def _get_order_update_channel(self) -> str:
        return "orderUpdates"

    @staticmethod
    def _payload(data: Any) -> Tuple[str, Any]:
        if isinstance(data, dict) and "channel" in data:
            return str(data.get("channel") or ""), data.get("data")
        return "", data

    def _handle_ticker_message(self, data: Any) -> Optional[WSTickerData]:
        channel, payload = self._payload(data)
        if channel and channel != "bbo":
            return None
        if not isinstance(payload, dict):
            return None
        bbo = payload.get("bbo") or [None, None]
        bid = self._safe_decimal((bbo[0] or {}).get("px")) if len(bbo) > 0 else None
        ask = self._safe_decimal((bbo[1] or {}).get("px")) if len(bbo) > 1 else None
        last = (bid + ask) / 2 if bid is not None and ask is not None else bid or ask
        return WSTickerData(
            symbol=str(payload.get("coin") or self.coin),
            bid_price=bid,
            ask_price=ask,
            last_price=last,
            timestamp=payload.get("time"),
        )

    def _handle_depth_message(self, data: Any) -> Optional[WSOrderBookData]:
        channel, payload = self._payload(data)
        if channel and channel != "l2Book":
            return None
        if not isinstance(payload, dict):
            return None
        levels = payload.get("levels") or [[], []]
        bids = self._coerce_orderbook_levels(levels[0] if len(levels) > 0 else [])
        asks = self._coerce_orderbook_levels(levels[1] if len(levels) > 1 else [])
        return WSOrderBookData(
            symbol=str(payload.get("coin") or self.coin),
            bids=bids,
            asks=asks,
            timestamp=payload.get("time"),
        )

    def _handle_order_update_message(self, data: Any) -> Optional[WSOrderUpdateData]:
        channel, payload = self._payload(data)
        if channel and channel != "orderUpdates":
            return None
        if isinstance(payload, list):
            payload = payload[0] if payload else None
        if not isinstance(payload, dict):
            return None
        order = payload.get("order") or payload
        status_raw = str(payload.get("status") or "open")
        remaining = self._safe_decimal(order.get("sz")) or Decimal("0")
        original = self._safe_decimal(order.get("origSz")) or remaining
        status_lower = status_raw.lower()
        if status_lower == "filled":
            status = "FILLED"
        elif status_lower == "open" and remaining < original:
            status = "PARTIALLY_FILLED"
        elif status_lower == "open":
            status = "NEW"
        elif "cancel" in status_lower or "reject" in status_lower:
            status = "CANCELLED"
        else:
            status = status_raw.upper()
        return WSOrderUpdateData(
            symbol=str(order.get("coin") or self.coin),
            order_id=str(order.get("oid")),
            side="BUY" if order.get("side") == "B" else "SELL",
            order_type="LIMIT",
            status=status,
            price=self._safe_decimal(order.get("limitPx")),
            quantity=original,
            filled_quantity=max(Decimal("0"), original - remaining),
            remaining_quantity=remaining,
            timestamp=payload.get("statusTimestamp") or order.get("timestamp"),
        )

    def _handle_fill_message(self, data: Any) -> Optional[WSFillData]:
        channel, payload = self._payload(data)
        if channel and channel != "userFills":
            return None
        if not isinstance(payload, dict) or payload.get("isSnapshot"):
            return None
        fills = payload.get("fills") or []
        if not fills:
            return None
        fill = fills[0]
        timestamp = int(fill.get("time") or 0)
        coin = str(fill.get("coin") or self.coin)
        fill_id = f"{timestamp}:{coin}:{fill.get('tid')}"
        return WSFillData(
            symbol=coin,
            fill_id=fill_id,
            order_id=str(fill.get("oid")),
            side="BUY" if fill.get("side") == "B" else "SELL",
            price=self._safe_decimal(fill.get("px")) or Decimal("0"),
            quantity=self._safe_decimal(fill.get("sz")) or Decimal("0"),
            fee=self._safe_decimal(fill.get("fee")) or Decimal("0"),
            fee_asset=fill.get("feeToken") or "USDC",
            is_maker=not bool(fill.get("crossed", False)),
            timestamp=timestamp,
        )

    def _get_rest_client(self) -> HyperliquidClient:
        return self.rest_client

    def subscribe_order_updates(self) -> bool:
        ok = True
        for channel in ("orderUpdates", "userFills"):
            if channel in self.subscriptions:
                continue
            ok = self._subscribe(channel, is_private=True) and ok
        return ok

    def _subscribe(self, channel: str, is_private: bool = False) -> bool:
        """Make reconnect/startup subscription calls idempotent.

        ``MarketMaker`` performs a compatibility subscription pass after the
        base WebSocket's ``on_open`` callback. Hyperliquid otherwise receives
        duplicate bbo/l2Book subscriptions and emits every event twice.
        """
        if channel in self.subscriptions:
            return True
        return super()._subscribe(channel, is_private=is_private)

    def _on_open(self, ws_app):
        super()._on_open(ws_app)
        self.subscribe_order_updates()

    def _on_error(self, ws_app, error):
        """Retry failures that happen during the reconnect TLS handshake.

        The base client retries established connections that later close, but
        a fresh socket can fail before ``connected`` ever becomes true. The
        Testnet endpoint occasionally produces a transient TLS EOF in exactly
        that phase, so keep REST fallback active and schedule another bounded
        reconnect attempt.
        """
        super()._on_error(ws_app, error)
        if self.running and self.config.auto_reconnect and not self.reconnecting:
            threading.Thread(target=self._trigger_reconnect, daemon=True).start()

    def _on_message(self, ws_app, message: str):
        """Fan out batched fill/order messages so no partial fill is dropped."""
        try:
            parsed = json.loads(message)
        except (TypeError, json.JSONDecodeError):
            return super()._on_message(ws_app, message)
        self.last_heartbeat = time.time()
        channel = parsed.get("channel")
        payload = parsed.get("data")
        if channel == "userFills" and isinstance(payload, dict):
            if payload.get("isSnapshot"):
                return
            for fill in payload.get("fills") or []:
                wrapped = {
                    "channel": "userFills",
                    "data": {**payload, "fills": [fill], "isSnapshot": False},
                }
                if self.on_message_callback:
                    self.on_message_callback("userFills", wrapped)
            return
        if channel == "orderUpdates" and isinstance(payload, list):
            for update in payload:
                wrapped = {"channel": "orderUpdates", "data": update}
                if self.on_message_callback:
                    self.on_message_callback("orderUpdates", wrapped)
            return
        super()._on_message(ws_app, message)
