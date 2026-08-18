"""Hyperliquid perpetuals adapter built on the official Python SDK.

The adapter deliberately keeps signing and wire encoding inside the SDK.  It
also namespaces every bot order with a 16-byte ``cloid`` so cleanup never
touches manual orders or orders created by another program.
"""
from __future__ import annotations

import asyncio
import hashlib
import itertools
import time
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Any, Dict, List, Optional, Tuple

from eth_account import Account
from hyperliquid.api import API
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants
from hyperliquid.utils.types import Cloid

from .base_client import (
    ApiResponse,
    BaseExchangeClient,
    BalanceInfo,
    BatchOrderResult,
    CancelResult,
    CollateralInfo,
    KlineInfo,
    MarketInfo,
    OrderBookInfo,
    OrderBookLevel,
    OrderInfo,
    OrderResult,
    PositionInfo,
    TickerInfo,
    TradeInfo,
)


BOT_CLOID_MAGIC = "42504d47"  # ASCII: BPMG (Backpack-MM grid)
MIN_ORDER_NOTIONAL = Decimal("10")


class HyperliquidClient(BaseExchangeClient):
    """Synchronous Hyperliquid adapter matching ``BaseExchangeClient``'s API."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.account_address = str(self.config.get("account_address") or "").strip()
        self.signer_private_key = str(
            self.config.get("signer_private_key") or self.config.get("private_key") or ""
        ).strip()
        self.signer_address = str(self.config.get("signer_address") or "").strip()
        self.vault_address = str(self.config.get("vault_address") or "").strip() or None
        self.base_url = str(self.config.get("base_url") or constants.TESTNET_API_URL).rstrip("/")
        self.timeout = float(self.config.get("timeout", 10.0))
        self.allow_orders = bool(self.config.get("allow_orders", False))
        self.allow_mainnet = bool(self.config.get("allow_mainnet", False))
        self.max_order_notional = Decimal(str(self.config.get("max_order_notional", "100")))
        # Opening orders use this floor. HyperCore accepts a reduce-only order
        # that closes the remaining position below the floor; the strategy can
        # still use this value to accumulate routine partial-fill dust.
        self.min_order_notional = MIN_ORDER_NOTIONAL
        self.max_active_orders = int(self.config.get("max_active_orders", 30))
        self.max_position = Decimal(str(self.config.get("max_position", "0")))

        if not self.account_address or not self.account_address.startswith("0x"):
            raise ValueError("Hyperliquid account_address 缺失或格式無效")
        if self.base_url == constants.MAINNET_API_URL.rstrip("/") and not self.allow_mainnet:
            raise ValueError("Hyperliquid Mainnet 默認禁用；本項目只允許顯式解鎖")
        if self.base_url != constants.TESTNET_API_URL.rstrip("/") and not self.allow_mainnet:
            raise ValueError("未知 Hyperliquid endpoint；未顯式允許 Mainnet")

        bootstrap = API(self.base_url, timeout=self.timeout)
        meta = self._retry(lambda: bootstrap.post("/info", {"type": "meta"}), "meta")
        spot_meta = self._retry(lambda: bootstrap.post("/info", {"type": "spotMeta"}), "spotMeta")
        self.info = Info(
            self.base_url,
            skip_ws=True,
            timeout=self.timeout,
            meta=meta,
            spot_meta=spot_meta,
        )
        self.wallet = None
        self.exchange = None
        if self.signer_private_key:
            self.wallet = Account.from_key(self.signer_private_key)
            if self.signer_address and self.wallet.address.lower() != self.signer_address.lower():
                raise ValueError("Hyperliquid signer address 與 private key 不匹配")
            self.exchange = Exchange(
                self.wallet,
                self.base_url,
                meta=meta,
                spot_meta=spot_meta,
                account_address=self.account_address,
                vault_address=self.vault_address,
                timeout=self.timeout,
            )

        self._meta: Optional[Dict[str, Any]] = meta
        self._asset_contexts: Dict[str, Dict[str, Any]] = {}
        # In-memory evidence map used by the Testnet validator. It contains no
        # secret material and links venue oid -> bot cloid for this process.
        self.order_identity_registry: Dict[str, str] = {}
        session_seed = f"{self.account_address}:{time.time_ns()}".encode()
        self._session_id = hashlib.sha256(session_seed).hexdigest()[:8]
        self._cloid_counter = itertools.count(1)

    @staticmethod
    def _retry(call, label: str, attempts: int = 3):
        last_error = None
        for attempt in range(attempts):
            try:
                return call()
            except Exception as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(0.25 * (2 ** attempt))
        raise RuntimeError(f"Hyperliquid {label} 在 {attempts} 次嘗試後失敗: {last_error}") from last_error

    async def connect(self) -> None:
        await asyncio.sleep(0)

    async def disconnect(self) -> None:
        await asyncio.sleep(0)

    def get_exchange_name(self) -> str:
        return "Hyperliquid"

    def make_request(
        self,
        method: str,
        endpoint: str,
        api_key=None,
        secret_key=None,
        instruction=None,
        params=None,
        data=None,
        retry_count: int = 3,
    ) -> Dict:
        """Compatibility shim; signed actions must go through the official SDK."""
        if method.upper() != "POST" or endpoint not in ("/info", "info"):
            return {"error": "Hyperliquid raw/signed requests are disabled; use SDK methods"}
        try:
            return self.info.post("/info", data or params or {})
        except Exception as exc:
            return {"error": str(exc)}

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        value = str(symbol or "").strip().upper()
        for suffix in ("_USDC_PERP", "-USDC-PERP", "_USDC", "-USDC", "/USDC"):
            if value.endswith(suffix):
                value = value[: -len(suffix)]
                break
        return value

    def _load_meta(self, refresh: bool = False) -> Dict[str, Any]:
        if self._meta is None or refresh or not self._asset_contexts:
            meta, contexts = self._retry(
                self.info.meta_and_asset_ctxs,
                "metaAndAssetCtxs",
            )
            self._meta = meta
            self._asset_contexts = {
                asset.get("name", ""): context
                for asset, context in zip(meta.get("universe", []), contexts)
            }
        return self._meta

    def _asset(self, symbol: str) -> Dict[str, Any]:
        coin = self.normalize_symbol(symbol)
        meta = self._load_meta()
        for asset in meta.get("universe", []):
            if asset.get("name") == coin:
                return asset
        raise ValueError(f"Hyperliquid 不存在永續市場: {symbol}")

    def _new_cloid(self, client_id: Optional[str] = None) -> Cloid:
        if client_id:
            digest = hashlib.sha256(str(client_id).encode()).hexdigest()[:24]
        else:
            sequence = next(self._cloid_counter)
            digest = f"{self._session_id}{sequence:016x}"[-24:]
        return Cloid.from_str(f"0x{BOT_CLOID_MAGIC}{digest}")

    @staticmethod
    def is_bot_cloid(value: Optional[str]) -> bool:
        return bool(value and str(value).lower().startswith(f"0x{BOT_CLOID_MAGIC.lower()}"))

    @staticmethod
    def _decimal(value: Any, default: str = "0") -> Decimal:
        try:
            return Decimal(str(value))
        except Exception:
            return Decimal(default)

    def normalize_size(self, symbol: str, size: Any) -> Decimal:
        precision = int(self._asset(symbol).get("szDecimals", 0))
        quantum = Decimal(1).scaleb(-precision)
        return self._decimal(size).copy_abs().quantize(quantum, rounding=ROUND_DOWN)

    def normalize_price(self, symbol: str, price: Any, is_buy: bool) -> Decimal:
        """Apply Hyperliquid's 5-significant-figure and decimal-place rules."""
        value = self._decimal(price).copy_abs()
        if value <= 0:
            raise ValueError("price 必須大於 0")
        sz_decimals = int(self._asset(symbol).get("szDecimals", 0))
        max_decimals = max(0, 6 - sz_decimals)
        quantum_exp = max(-max_decimals, value.adjusted() - 4)
        quantum = Decimal(1).scaleb(quantum_exp)
        rounding = ROUND_DOWN if is_buy else ROUND_UP
        return value.quantize(quantum, rounding=rounding)

    def _ensure_can_trade(self) -> None:
        if not self.allow_orders:
            raise PermissionError("Testnet 下單未解鎖；請使用 --confirm-live-testnet")
        if self.exchange is None:
            raise PermissionError("缺少 Hyperliquid signer private key")

    def _validate_order_risk(
        self,
        symbol: str,
        size: Decimal,
        price: Decimal,
        reduce_only: bool = False,
    ) -> None:
        notional = size * price
        if not reduce_only and notional < MIN_ORDER_NOTIONAL:
            raise ValueError(f"訂單名義價值 {notional} 小於 Hyperliquid 最低要求 $10")
        if self.max_order_notional > 0 and notional > self.max_order_notional:
            raise ValueError(
                f"訂單名義價值 {notional} 超過本地上限 {self.max_order_notional} USDC"
            )
        active = self.get_open_orders(symbol)
        if active.success and len(active.data or []) >= self.max_active_orders:
            raise ValueError(f"活躍訂單數已達本地上限 {self.max_active_orders}")

    def _validate_projected_exposure(self, prepared: List[Tuple[Dict[str, Any], Cloid, Decimal, Decimal]]) -> None:
        """Conservatively include current position and every live opening order."""
        if self.max_position <= 0 or not prepared:
            return
        coin = prepared[0][0]["symbol"]
        positions = self.get_positions(coin)
        if not positions.success:
            raise ValueError(f"無法驗證當前倉位，拒絕下單: {positions.error_message}")
        signed_position = Decimal("0")
        if positions.data:
            pos = positions.data[0]
            signed_position = pos.size if pos.side == "LONG" else -pos.size

        open_response = self.get_open_orders(coin)
        if not open_response.success:
            raise ValueError(f"無法驗證活躍訂單，拒絕下單: {open_response.error_message}")
        opening_buys = Decimal("0")
        opening_sells = Decimal("0")
        for order in open_response.data or []:
            if order.reduce_only:
                continue
            if str(order.side).upper() in ("BUY", "BID"):
                opening_buys += order.remaining_size
            else:
                opening_sells += order.remaining_size
        for details, _cloid, size, _price in prepared:
            if details.get("reduceOnly"):
                continue
            if details["side"] == "Bid":
                opening_buys += size
            else:
                opening_sells += size
        projected_long = signed_position + opening_buys
        projected_short = signed_position - opening_sells
        if projected_long > self.max_position:
            raise ValueError(
                f"最壞多頭敞口 {projected_long} 超過 max_position {self.max_position}"
            )
        if projected_short < -self.max_position:
            raise ValueError(
                f"最壞空頭敞口 {abs(projected_short)} 超過 max_position {self.max_position}"
            )

    @staticmethod
    def _extract_statuses(response: Any) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        if not isinstance(response, dict):
            return None, f"無效 SDK 響應: {type(response).__name__}"
        if response.get("status") != "ok":
            return None, str(response.get("response") or response.get("error") or response)
        try:
            statuses = response["response"]["data"]["statuses"]
        except (KeyError, TypeError):
            return None, f"SDK 響應缺少 statuses: {response}"
        return statuses, None

    def _order_result(
        self,
        details: Dict[str, Any],
        status: Dict[str, Any],
        cloid: Cloid,
        price: Decimal,
        size: Decimal,
    ) -> OrderResult:
        if "resting" in status:
            payload = status["resting"]
            order_status = "OPEN"
            filled = Decimal("0")
        elif "filled" in status:
            payload = status["filled"]
            order_status = "FILLED"
            filled = self._decimal(payload.get("totalSz"), str(size))
            price = self._decimal(payload.get("avgPx"), str(price))
        else:
            payload = status
            order_status = "ACCEPTED"
            filled = Decimal("0")
        order_id = str(payload.get("oid")) if payload.get("oid") is not None else None
        cloid_raw = cloid.to_raw()
        if order_id:
            self.order_identity_registry[order_id] = cloid_raw
        return OrderResult(
            success=True,
            order_id=order_id,
            client_order_id=cloid_raw,
            symbol=str(details.get("symbol")),
            side=str(details.get("side")),
            order_type=str(details.get("orderType")),
            size=size,
            price=price,
            filled_size=filled,
            status=order_status,
            created_at=int(time.time() * 1000),
            raw=status,
        )

    def _prepare_order(self, details: Dict[str, Any]) -> Tuple[Dict[str, Any], Cloid, Decimal, Decimal]:
        coin = self.normalize_symbol(str(details.get("symbol") or ""))
        is_buy = str(details.get("side") or "").upper() in ("B", "BID", "BUY", "LONG")
        size = self.normalize_size(coin, details.get("quantity") or details.get("size"))
        if size <= 0:
            raise ValueError("訂單數量經精度處理後為 0")

        order_type = str(details.get("orderType") or "Limit").capitalize()
        if order_type == "Limit":
            price = self.normalize_price(coin, details.get("price"), is_buy=is_buy)
        elif order_type == "Market":
            mids = self._retry(self.info.all_mids, "allMids")
            price = self.normalize_price(coin, mids.get(coin), is_buy=is_buy)
        else:
            raise ValueError(f"不支持的訂單類型: {order_type}")

        self._validate_order_risk(
            coin,
            size,
            price,
            reduce_only=bool(details.get("reduceOnly", False)),
        )
        cloid = self._new_cloid(details.get("clientId") or details.get("client_order_id"))
        normalized = dict(details)
        normalized.update(
            {
                "symbol": coin,
                "side": "Bid" if is_buy else "Ask",
                "orderType": order_type,
                "quantity": str(size),
                "price": str(price),
                "reduceOnly": bool(details.get("reduceOnly", False)),
            }
        )
        return normalized, cloid, size, price

    def execute_order(self, order_details: Dict[str, Any]) -> ApiResponse:
        try:
            self._ensure_can_trade()
            details, cloid, size, price = self._prepare_order(order_details)
            self._validate_projected_exposure([(details, cloid, size, price)])
            is_buy = details["side"] == "Bid"
            if details["orderType"] == "Market":
                if details.get("reduceOnly"):
                    response = self.exchange.market_close(
                        details["symbol"],
                        sz=float(size),
                        px=float(price),
                        slippage=float(self.config.get("market_slippage", 0.01)),
                        cloid=cloid,
                    )
                else:
                    response = self.exchange.market_open(
                        details["symbol"],
                        is_buy,
                        float(size),
                        px=float(price),
                        slippage=float(self.config.get("market_slippage", 0.01)),
                        cloid=cloid,
                    )
            else:
                tif_raw = str(details.get("timeInForce") or "GTC").upper()
                tif = "Alo" if details.get("postOnly") else {"GTC": "Gtc", "IOC": "Ioc", "ALO": "Alo"}.get(tif_raw, "Gtc")
                response = self.exchange.order(
                    details["symbol"],
                    is_buy,
                    float(size),
                    float(price),
                    {"limit": {"tif": tif}},
                    reduce_only=bool(details.get("reduceOnly", False)),
                    cloid=cloid,
                )
            statuses, error = self._extract_statuses(response)
            if error or not statuses:
                return ApiResponse.error(error or "Hyperliquid 未返回訂單狀態", raw=response)
            status = statuses[0]
            if "error" in status:
                return ApiResponse.error(str(status["error"]), raw=response)
            result = self._order_result(details, status, cloid, price, size)
            return ApiResponse.ok(result, raw=response)
        except Exception as exc:
            return ApiResponse.error(str(exc))

    def execute_order_batch(self, orders_details: List[Dict[str, Any]]) -> ApiResponse:
        if not orders_details:
            return ApiResponse.error("訂單列表為空")
        try:
            self._ensure_can_trade()
            prepared = [self._prepare_order(order) for order in orders_details]
            current_orders = self.get_open_orders(prepared[0][0]["symbol"])
            if not current_orders.success:
                return current_orders
            if len(current_orders.data or []) + len(prepared) > self.max_active_orders:
                return ApiResponse.error(
                    f"批量下單後活躍訂單將超過本地上限 {self.max_active_orders}"
                )
            self._validate_projected_exposure(prepared)
            if any(item[0]["orderType"] != "Limit" for item in prepared):
                return super().execute_order_batch(orders_details)  # pragma: no cover
            requests = []
            for details, cloid, size, price in prepared:
                tif_raw = str(details.get("timeInForce") or "GTC").upper()
                tif = "Alo" if details.get("postOnly") else {"GTC": "Gtc", "IOC": "Ioc", "ALO": "Alo"}.get(tif_raw, "Gtc")
                requests.append(
                    {
                        "coin": details["symbol"],
                        "is_buy": details["side"] == "Bid",
                        "sz": float(size),
                        "limit_px": float(price),
                        "order_type": {"limit": {"tif": tif}},
                        "reduce_only": bool(details.get("reduceOnly", False)),
                        "cloid": cloid,
                    }
                )
            response = self.exchange.bulk_orders(requests)
            statuses, error = self._extract_statuses(response)
            if error or statuses is None:
                return ApiResponse.error(error or "批量訂單無狀態", raw=response)

            successes: List[OrderResult] = []
            errors: List[str] = []
            for item, status in zip(prepared, statuses):
                details, cloid, size, price = item
                if "error" in status:
                    errors.append(str(status["error"]))
                    continue
                successes.append(self._order_result(details, status, cloid, price, size))
            batch = BatchOrderResult(
                success=bool(successes),
                orders=successes,
                failed_count=len(errors),
                errors=errors,
                raw=response,
            )
            if successes:
                return ApiResponse.ok(batch, raw=response)
            return ApiResponse.error("批量下單全部失敗", raw=response)
        except Exception as exc:
            return ApiResponse.error(str(exc))

    def get_open_orders(self, symbol: Optional[str] = None) -> ApiResponse:
        try:
            coin = self.normalize_symbol(symbol) if symbol else None
            raw_orders = self._retry(
                lambda: self.info.frontend_open_orders(self.account_address),
                "frontendOpenOrders",
            )
            orders: List[OrderInfo] = []
            for raw in raw_orders:
                if coin and raw.get("coin") != coin:
                    continue
                size = self._decimal(raw.get("sz"))
                original = self._decimal(raw.get("origSz"), str(size))
                side = "BUY" if raw.get("side") == "B" else "SELL"
                tif = str(raw.get("tif") or "")
                orders.append(
                    OrderInfo(
                        order_id=str(raw.get("oid")),
                        client_order_id=raw.get("cloid"),
                        symbol=str(raw.get("coin")),
                        side=side,
                        order_type=str(raw.get("orderType") or "Limit").upper(),
                        size=original,
                        price=self._decimal(raw.get("limitPx")),
                        status="OPEN",
                        filled_size=max(Decimal("0"), original - size),
                        remaining_size=size,
                        created_at=raw.get("timestamp"),
                        updated_at=raw.get("timestamp"),
                        time_in_force=tif,
                        post_only=tif.lower() == "alo",
                        reduce_only=bool(raw.get("reduceOnly", False)),
                        raw=raw,
                    )
                )
            return ApiResponse.ok(orders, raw=raw_orders)
        except Exception as exc:
            return ApiResponse.error(str(exc))

    def _owned_open_order(self, order_id: str, symbol: Optional[str]) -> Optional[OrderInfo]:
        response = self.get_open_orders(symbol)
        if not response.success:
            return None
        for order in response.data or []:
            if str(order.order_id) == str(order_id) or str(order.client_order_id) == str(order_id):
                return order if self.is_bot_cloid(order.client_order_id) else None
        return None

    def cancel_order(self, order_id: str, symbol: str) -> ApiResponse:
        try:
            self._ensure_can_trade()
            coin = self.normalize_symbol(symbol)
            owned = self._owned_open_order(str(order_id), coin)
            if owned is None:
                return ApiResponse.error("拒絕撤銷：訂單不存在或不是本 bot 的 cloid 命名空間")
            if str(order_id).startswith("0x"):
                response = self.exchange.cancel_by_cloid(coin, Cloid.from_str(str(order_id)))
            else:
                response = self.exchange.cancel(coin, int(owned.order_id))
            statuses, error = self._extract_statuses(response)
            if error or not statuses:
                return ApiResponse.error(error or "撤單無狀態", raw=response)
            status = statuses[0]
            if "error" in status:
                return ApiResponse.error(str(status["error"]), raw=response)
            return ApiResponse.ok(
                CancelResult(success=True, order_id=str(owned.order_id), cancelled_count=1, raw=response),
                raw=response,
            )
        except Exception as exc:
            return ApiResponse.error(str(exc))

    def cancel_all_orders(self, symbol: str) -> ApiResponse:
        try:
            self._ensure_can_trade()
            open_response = self.get_open_orders(symbol)
            if not open_response.success:
                return open_response
            owned = [o for o in (open_response.data or []) if self.is_bot_cloid(o.client_order_id)]
            if not owned:
                return ApiResponse.ok(CancelResult(success=True, cancelled_count=0))
            requests = [{"coin": self.normalize_symbol(symbol), "oid": int(o.order_id)} for o in owned]
            response = self.exchange.bulk_cancel(requests)
            statuses, error = self._extract_statuses(response)
            if error or statuses is None:
                return ApiResponse.error(error or "批量撤單無狀態", raw=response)
            failures = [str(s.get("error")) for s in statuses if isinstance(s, dict) and "error" in s]
            cancelled = len(statuses) - len(failures)
            if failures and cancelled == 0:
                return ApiResponse.error("; ".join(failures), raw=response)
            return ApiResponse.ok(
                CancelResult(success=True, cancelled_count=cancelled, raw=response), raw=response
            )
        except Exception as exc:
            return ApiResponse.error(str(exc))

    def get_markets(self) -> ApiResponse:
        try:
            meta = self._load_meta()
            markets = [self._market_info(asset) for asset in meta.get("universe", [])]
            return ApiResponse.ok(markets, raw=meta)
        except Exception as exc:
            return ApiResponse.error(str(exc))

    def _market_info(self, asset: Dict[str, Any]) -> MarketInfo:
        precision = int(asset.get("szDecimals", 0))
        return MarketInfo(
            symbol=str(asset.get("name")),
            base_asset=str(asset.get("name")),
            quote_asset="USDC",
            market_type="PERP",
            status="ONLINE",
            min_order_size=Decimal(1).scaleb(-precision),
            tick_size=Decimal(1).scaleb(-max(0, 6 - precision)),
            step_size=Decimal(1).scaleb(-precision),
            base_precision=precision,
            quote_precision=max(0, 6 - precision),
            min_notional=MIN_ORDER_NOTIONAL,
            raw=asset,
        )

    def get_market_limits(self, symbol: str) -> ApiResponse:
        try:
            return ApiResponse.ok(self._market_info(self._asset(symbol)))
        except Exception as exc:
            return ApiResponse.error(str(exc))

    def get_order_book(self, symbol: str, limit: int = 20) -> ApiResponse:
        try:
            coin = self.normalize_symbol(symbol)
            raw = self._retry(lambda: self.info.l2_snapshot(coin), "l2Book")
            levels = raw.get("levels") or [[], []]
            bids = [OrderBookLevel(self._decimal(x.get("px")), self._decimal(x.get("sz"))) for x in levels[0][:limit]]
            asks = [OrderBookLevel(self._decimal(x.get("px")), self._decimal(x.get("sz"))) for x in levels[1][:limit]]
            return ApiResponse.ok(
                OrderBookInfo(symbol=coin, bids=bids, asks=asks, timestamp=raw.get("time"), raw=raw),
                raw=raw,
            )
        except Exception as exc:
            return ApiResponse.error(str(exc))

    def get_ticker(self, symbol: str) -> ApiResponse:
        try:
            coin = self.normalize_symbol(symbol)
            self._load_meta()
            book_response = self.get_order_book(coin, limit=1)
            if not book_response.success:
                return book_response
            book = book_response.data
            mids = self._retry(self.info.all_mids, "allMids")
            context = self._asset_contexts.get(coin) or {}
            ticker = TickerInfo(
                symbol=coin,
                last_price=self._decimal(mids.get(coin)) if mids.get(coin) else None,
                bid_price=book.best_bid.price if book.best_bid else None,
                ask_price=book.best_ask.price if book.best_ask else None,
                bid_size=book.best_bid.quantity if book.best_bid else None,
                ask_size=book.best_ask.quantity if book.best_ask else None,
                mark_price=self._decimal(context.get("markPx")) if context.get("markPx") else None,
                index_price=self._decimal(context.get("oraclePx")) if context.get("oraclePx") else None,
                volume_24h=self._decimal(context.get("dayNtlVlm")) if context.get("dayNtlVlm") else None,
                open_interest=self._decimal(context.get("openInterest")) if context.get("openInterest") else None,
                funding_rate=self._decimal(context.get("funding")) if context.get("funding") else None,
                timestamp=book.timestamp,
                raw={"book": book.raw, "context": context},
            )
            return ApiResponse.ok(ticker, raw=ticker.raw)
        except Exception as exc:
            return ApiResponse.error(str(exc))

    def get_balance(self) -> ApiResponse:
        try:
            raw = self._retry(
                lambda: self.info.spot_user_state(self.account_address),
                "spotClearinghouseState",
            )
            balances = []
            for item in raw.get("balances") or []:
                total = self._decimal(item.get("total"))
                locked = self._decimal(item.get("hold"))
                balances.append(
                    BalanceInfo(
                        asset=str(item.get("coin")),
                        available=max(Decimal("0"), total - locked),
                        locked=locked,
                        total=total,
                        raw=item,
                    )
                )
            return ApiResponse.ok(balances, raw=raw)
        except Exception as exc:
            return ApiResponse.error(str(exc))

    def get_collateral(self, subaccount_id: Optional[str] = None) -> ApiResponse:
        try:
            spot = self._retry(
                lambda: self.info.spot_user_state(self.account_address),
                "spotClearinghouseState",
            )
            state = self._retry(
                lambda: self.info.user_state(self.account_address),
                "clearinghouseState",
            )
            usdc = next((x for x in (spot.get("balances") or []) if x.get("coin") == "USDC"), {})
            total = self._decimal(usdc.get("total"))
            hold = self._decimal(usdc.get("hold"))
            margin = state.get("marginSummary") or {}
            item = CollateralInfo(
                asset="USDC",
                total_collateral=total,
                free_collateral=max(Decimal("0"), total - hold),
                initial_margin=self._decimal(margin.get("totalMarginUsed")),
                account_value=total,
                unrealized_pnl=sum(
                    (self._decimal(p.get("position", {}).get("unrealizedPnl")) for p in state.get("assetPositions") or []),
                    Decimal("0"),
                ),
                raw={"spot": usdc, "marginSummary": margin},
            )
            return ApiResponse.ok([item], raw=item.raw)
        except Exception as exc:
            return ApiResponse.error(str(exc))

    def get_positions(self, symbol: Optional[str] = None) -> ApiResponse:
        try:
            coin = self.normalize_symbol(symbol) if symbol else None
            raw = self._retry(
                lambda: self.info.user_state(self.account_address),
                "clearinghouseState",
            )
            positions = []
            for wrapper in raw.get("assetPositions") or []:
                item = wrapper.get("position") or {}
                if coin and item.get("coin") != coin:
                    continue
                signed_size = self._decimal(item.get("szi"))
                if signed_size == 0:
                    continue
                leverage = item.get("leverage") or {}
                positions.append(
                    PositionInfo(
                        symbol=str(item.get("coin")),
                        side="LONG" if signed_size > 0 else "SHORT",
                        size=abs(signed_size),
                        entry_price=self._decimal(item.get("entryPx")) if item.get("entryPx") else None,
                        mark_price=self._decimal((self._asset_contexts.get(str(item.get("coin"))) or {}).get("markPx")) if self._asset_contexts.get(str(item.get("coin"))) else None,
                        liquidation_price=self._decimal(item.get("liquidationPx")) if item.get("liquidationPx") else None,
                        unrealized_pnl=self._decimal(item.get("unrealizedPnl")),
                        margin=self._decimal(item.get("marginUsed")),
                        leverage=self._decimal(leverage.get("value")) if leverage.get("value") is not None else None,
                        margin_mode=str(leverage.get("type") or "cross").upper(),
                        raw=wrapper,
                    )
                )
            return ApiResponse.ok(positions, raw=raw)
        except Exception as exc:
            return ApiResponse.error(str(exc))

    def get_fill_history(self, symbol: Optional[str] = None, limit: int = 100) -> ApiResponse:
        try:
            coin = self.normalize_symbol(symbol) if symbol else None
            raw_fills = self._retry(
                lambda: self.info.user_fills(self.account_address),
                "userFills",
            )
            fills = []
            for raw in raw_fills:
                if coin and raw.get("coin") != coin:
                    continue
                timestamp = int(raw.get("time") or 0)
                tid = str(raw.get("tid"))
                fills.append(
                    TradeInfo(
                        trade_id=f"{timestamp}:{raw.get('coin')}:{tid}",
                        order_id=str(raw.get("oid")) if raw.get("oid") is not None else None,
                        symbol=str(raw.get("coin")),
                        side="BUY" if raw.get("side") == "B" else "SELL",
                        size=self._decimal(raw.get("sz")),
                        price=self._decimal(raw.get("px")),
                        fee=self._decimal(raw.get("fee")),
                        fee_asset=raw.get("feeToken") or "USDC",
                        timestamp=timestamp,
                        is_maker=not bool(raw.get("crossed", False)),
                        raw=raw,
                    )
                )
                if len(fills) >= limit:
                    break
            return ApiResponse.ok(fills, raw=raw_fills)
        except Exception as exc:
            return ApiResponse.error(str(exc))

    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 100) -> ApiResponse:
        try:
            coin = self.normalize_symbol(symbol)
            end = int(time.time() * 1000)
            interval_ms = {
                "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
                "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000,
                "4h": 14_400_000, "8h": 28_800_000, "12h": 43_200_000,
                "1d": 86_400_000,
            }.get(interval, 3_600_000)
            raw = self._retry(
                lambda: self.info.candles_snapshot(coin, interval, end - interval_ms * limit, end),
                "candleSnapshot",
            )
            candles = [
                KlineInfo(
                    open_time=int(x.get("t")), close_time=int(x.get("T")),
                    open_price=self._decimal(x.get("o")), high_price=self._decimal(x.get("h")),
                    low_price=self._decimal(x.get("l")), close_price=self._decimal(x.get("c")),
                    volume=self._decimal(x.get("v")), trades_count=int(x.get("n") or 0), raw=x,
                )
                for x in raw[-limit:]
            ]
            return ApiResponse.ok(candles, raw=raw)
        except Exception as exc:
            return ApiResponse.error(str(exc))
