from datetime import datetime, timedelta
from typing import Dict, Any


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def format_status(trading_bot) -> str:
    summary = trading_bot.get_status_summary()

    message = f"🤖 Trading Bot Status\n"
    message += f"━━━━━━━━━━━━━━━━━━━━\n"

    strategy_type = summary.get('strategy_type', 'unknown')
    symbol = summary.get('symbol', 'N/A')
    exchange = summary.get('exchange', 'N/A')
    message += f"📊 Strategy: {strategy_type.title()}\n"
    message += f"💎 Symbol: {symbol}\n"
    message += f"🏢 Exchange: {exchange.capitalize()}\n"

    runtime = summary.get('runtime')
    if runtime:
        runtime_str = format_duration(runtime.total_seconds())
        message += f"⏱️ Runtime: {runtime_str}\n"

    message += "\n"

    balances = summary.get('balances')
    if balances:
        message += "💰 Balances:\n"
        for asset, info in balances.items():
            total_all = info.get('total_all', 0)
            message += f"  {asset}: {total_all:.8f}\n"
        message += "\n"

    trading_stats = summary.get('trading_stats')
    if trading_stats:
        message += "📈 Trading Statistics:\n"
        total_bought = trading_stats.get('total_bought', 0)
        total_sold = trading_stats.get('total_sold', 0)
        total_quote_volume = trading_stats.get('total_quote_volume', 0)
        message += f"  Total Bought: {total_bought:.4f}\n"
        message += f"  Total Sold: {total_sold:.4f}\n"
        message += f"  Total Volume: {total_quote_volume:.2f}\n"

        quote_asset = summary.get('quote_asset', 'USDC')
        profit = summary.get('profit', {})
        total_profit = profit.get('total', 0)
        session_profit = profit.get('session', 0)
        total_fees = profit.get('fees', 0)

        message += f"  Total Profit: {total_profit:+.8f} {quote_asset}\n"
        message += f"  Total Fees: {total_fees:.8f} {quote_asset}\n"
        message += f"  Net Profit: {(total_profit - total_fees):+.8f} {quote_asset}\n"
        message += "\n"

    active_orders = summary.get('active_orders')
    if active_orders:
        message += "📋 Active Orders:\n"
        message += f"  Buy Orders: {active_orders.get('buy', 0)}\n"
        message += f"  Sell Orders: {active_orders.get('sell', 0)}\n"
        message += "\n"

    grid_stats = summary.get('grid_stats')
    if grid_stats:
        message += "📦 Grid Stats:\n"
        grid_levels = grid_stats.get('grid_levels', 0)
        price_range = grid_stats.get('price_range', 'N/A')
        grid_mode = grid_stats.get('grid_mode', 'N/A')
        buy_fills = grid_stats.get('buy_fills', 0)
        sell_fills = grid_stats.get('sell_fills', 0)
        grid_profit = grid_stats.get('grid_profit', 0)

        message += f"  Grid Levels: {grid_levels}\n"
        message += f"  Price Range: {price_range}\n"
        message += f"  Grid Mode: {grid_mode}\n"
        message += f"  Buy Fills: {buy_fills}\n"
        message += f"  Sell Fills: {sell_fills}\n"
        quote_asset = summary.get('quote_asset', 'USDC')
        message += f"  Grid Profit: {grid_profit:+.8f} {quote_asset}\n"
        message += "\n"

    state = summary.get('state', 'UNKNOWN')
    state_emoji = {
        'RUNNING': '✅',
        'PAUSED': '⏸️',
        'STOPPED': '⛔'
    }.get(state, '❓')
    message += f"{state_emoji} Status: {state}\n"

    message += f"\n📅 Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    return message


def format_help_message() -> str:
    message = "📚 Available Commands:\n"
    message += "━━━━━━━━━━━━━━━━━━━━\n\n"
    message += "/start   - Start or resume trading strategy\n"
    message += "/stop    - Stop trading gracefully\n"
    message += "/pause   - Pause trading\n"
    message += "/resume  - Resume from pause\n"
    message += "/status  - Get current bot status\n"
    message += "/logs    - Show recent log entries\n"
    message += "/help    - Show this help message\n"
    return message


def format_error_message(error: str) -> str:
    return f"❌ Error: {error}"


def format_success_message(message: str) -> str:
    return f"✅ {message}"


def format_info_message(message: str) -> str:
    return f"ℹ️ {message}"
