#!/usr/bin/env python3
"""Run a bounded Hyperliquid Testnet grid and write secret-free evidence."""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from config import (
    HYPERLIQUID_ACCOUNT_ADDRESS,
    HYPERLIQUID_REST_URL,
    HYPERLIQUID_SIGNER_ADDRESS,
    HYPERLIQUID_SIGNER_PRIVATE_KEY,
    HYPERLIQUID_VAULT_ADDRESS,
    HYPERLIQUID_WS_URL,
)
from strategies.perp_grid_strategy import PerpGridStrategy


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=600)
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--symbol", default="BTC")
    parser.add_argument("--quantity", type=float, default=0.0002)
    parser.add_argument("--grid-num", type=int, default=6)
    parser.add_argument("--price-range", type=float, default=0.05)
    parser.add_argument("--max-position", type=float, default=0.001)
    parser.add_argument("--output-dir", default="artifacts")
    args = parser.parse_args()
    if not 600 <= args.duration <= 1200:
        parser.error("duration must be between 600 and 1200 seconds")
    return args


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def main() -> int:
    args = parse_args()
    cfg = {
        "account_address": HYPERLIQUID_ACCOUNT_ADDRESS,
        "signer_address": HYPERLIQUID_SIGNER_ADDRESS,
        "signer_private_key": HYPERLIQUID_SIGNER_PRIVATE_KEY,
        "vault_address": HYPERLIQUID_VAULT_ADDRESS,
        "base_url": HYPERLIQUID_REST_URL,
        "ws_url": HYPERLIQUID_WS_URL,
        "allow_orders": True,
        "allow_mainnet": False,
        "max_position": args.max_position,
        "close_on_exit": True,
    }
    strategy = PerpGridStrategy(
        api_key=HYPERLIQUID_ACCOUNT_ADDRESS,
        secret_key=HYPERLIQUID_SIGNER_PRIVATE_KEY,
        symbol=args.symbol,
        auto_price_range=True,
        price_range_percent=args.price_range,
        grid_num=args.grid_num,
        order_quantity=args.quantity,
        grid_type="neutral",
        target_position=0.0,
        max_position=args.max_position,
        position_threshold=args.quantity,
        exchange="hyperliquid",
        exchange_config=cfg,
        enable_database=False,
    )

    initial_positions = strategy.client.get_positions(args.symbol)
    if not initial_positions.success:
        raise RuntimeError(initial_positions.error_message)
    if initial_positions.data:
        raise RuntimeError("validation requires a flat starting position")

    started_ms = int(time.time() * 1000)
    strategy.run(duration_seconds=args.duration, interval_seconds=args.interval)
    ended_ms = int(time.time() * 1000)
    time.sleep(2)

    open_orders = strategy.client.get_open_orders(args.symbol)
    positions = strategy.client.get_positions(args.symbol)
    fills_response = strategy.client.get_fill_history(args.symbol, limit=2000)
    if not (open_orders.success and positions.success and fills_response.success):
        raise RuntimeError(
            f"final query failed: orders={open_orders.error_message}; "
            f"positions={positions.error_message}; fills={fills_response.error_message}"
        )

    registry = strategy.client.order_identity_registry
    evidence_fills = []
    for fill in fills_response.data or []:
        if not fill.timestamp or not (started_ms <= fill.timestamp <= ended_ms + 15_000):
            continue
        oid = str(fill.order_id)
        cloid = registry.get(oid)
        if not cloid:
            continue
        raw = fill.raw or {}
        evidence_fills.append(
            {
                "timestamp_ms": fill.timestamp,
                "timestamp_utc": iso(fill.timestamp),
                "symbol": fill.symbol,
                "side": fill.side,
                "size": str(fill.size),
                "price": str(fill.price),
                "fee": str(fill.fee or 0),
                "maker": fill.is_maker,
                "oid": oid,
                "cloid": cloid,
                "tid": raw.get("tid"),
                "hash": raw.get("hash"),
                "direction": raw.get("dir"),
                "closed_pnl": raw.get("closedPnl"),
            }
        )

    bot_open_orders = [
        order for order in (open_orders.data or [])
        if strategy.client.is_bot_cloid(order.client_order_id)
    ]
    report = {
        "schema": "hyperliquid-testnet-grid-validation-v1",
        "network": "testnet",
        "account_address": HYPERLIQUID_ACCOUNT_ADDRESS,
        "symbol": args.symbol,
        "started_ms": started_ms,
        "started_utc": iso(started_ms),
        "ended_ms": ended_ms,
        "ended_utc": iso(ended_ms),
        "runtime_seconds": round((ended_ms - started_ms) / 1000, 3),
        "parameters": {
            "duration": args.duration,
            "interval": args.interval,
            "quantity": args.quantity,
            "grid_num": args.grid_num,
            "price_range_percent": args.price_range,
            "max_position": args.max_position,
            "close_on_exit": True,
        },
        "checks": {
            "runtime_at_least_10_minutes": ended_ms - started_ms >= 600_000,
            "bot_open_orders_after_cleanup": len(bot_open_orders),
            "positions_after_cleanup": len(positions.data or []),
            "evidence_fill_count": len(evidence_fills),
            "unique_hash_count": len({x["hash"] for x in evidence_fills if x["hash"]}),
            "unique_tid_count": len({(x["timestamp_ms"], x["symbol"], x["tid"]) for x in evidence_fills}),
            "sides": sorted({x["side"] for x in evidence_fills}),
            "directions": sorted({str(x["direction"]) for x in evidence_fills}),
        },
        "fills": evidence_fills,
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"hyperliquid-testnet-{started_ms}.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"evidence": str(output), **report["checks"]}, ensure_ascii=False))

    clean = not bot_open_orders and not positions.data
    return 0 if clean else 2


if __name__ == "__main__":
    raise SystemExit(main())
