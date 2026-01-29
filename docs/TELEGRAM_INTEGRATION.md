# Telegram Integration Development Plan

## Overview

Add Telegram bot integration to provide remote monitoring and control capabilities for the trading bot. This feature enables:
- **Periodic automatic status reports** (configurable interval, default 30 minutes)
- **Manual status checks** via `/status` command
- **Bot control commands** for remote operation

---

## Supported Commands

| Command | Description |
|---------|-------------|
| `/start` | Start or resume trading strategy |
| `/stop` | Graceful shutdown (cancel unfilled orders, save stats, close connections) |
| `/pause` | Pause trading (cancel orders, keep bot running, positions remain open) |
| `/resume` | Resume from paused state |
| `/status` | Display current bot status and statistics |
| `/logs` | Show recent log entries (last 50 lines) |
| `/help` | List all available commands |

---

## Architecture

### Module Structure

```
telegram/
├── __init__.py           # Export TelegramBot class
├── bot.py                # Main TelegramBot class
├── handlers.py           # Command handlers
└── formatter.py          # Status message formatter
```

### Components

#### 1. `telegram/bot.py`
Main Telegram bot class that:
- Initializes python-telegram-bot client
- Manages connection to Telegram API
- Schedules periodic status updates
- Handles message routing to command handlers
- Provides thread-safe interface for trading bot control

Key methods:
```python
class TelegramBot:
    def __init__(self, token, chat_id, trading_bot_instance, update_interval_minutes=30)
    def start(self)              # Start bot and scheduler
    def stop(self)               # Stop bot and scheduler
    def send_message(self, message)  # Send text message to configured chat
    def send_status(self)        # Send formatted status report
    def schedule_status_update(self)  # Schedule periodic status updates
    def set_bot_state(self, state)   # Control trading bot state
    def get_recent_logs(self, lines=50)  # Retrieve recent log entries
```

#### 2. `telegram/handlers.py`
Command handler functions:
- `cmd_start()` - Start/resume trading
- `cmd_stop()` - Graceful shutdown
- `cmd_pause()` - Pause trading
- `cmd_resume()` - Resume from pause
- `cmd_status()` - Request and send current status
- `cmd_logs()` - Send recent log entries
- `cmd_help()` - Show help message

All handlers:
- Verify chat ID (security check)
- Call appropriate methods on trading bot instance
- Send confirmation/response messages

#### 3. `telegram/formatter.py`
Formats status messages to match CLI output style:
- Uses existing `_get_extra_summary_sections()` methods from strategies
- Formats: balances, positions, orders, profit/loss, trading statistics
- Returns clean, readable text message for Telegram

---

## Configuration

### Environment Variables

Add to `config.py`:
```python
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
TELEGRAM_ENABLED = os.getenv('TELEGRAM_ENABLED', '0').strip().lower() in {"1", "true", "yes", "on"}
TELEGRAM_UPDATE_INTERVAL = int(os.getenv('TELEGRAM_UPDATE_INTERVAL', '30'))  # minutes
```

Add to `.env.example`:
```bash
# Telegram Bot Configuration
TELEGRAM_ENABLED=1
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
TELEGRAM_UPDATE_INTERVAL=30  # minutes between automatic status updates
```

### New Dependencies

Add to `requirements.txt`:
```
python-telegram-bot>=20.0
```

---

## Integration with Existing Code

### Strategy Base Class Modifications

**File**: `strategies/market_maker.py`

Add methods:
```python
def get_status_summary(self) -> Dict[str, Any]:
    """Returns dict with all status information for Telegram"""
    return {
        'strategy_type': 'market_maker',
        'symbol': self.symbol,
        'exchange': self.exchange,
        'runtime': datetime.now() - self.session_start_time,
        'balances': self.get_total_balance(),
        'active_orders': {
            'buy': len(self.active_buy_orders),
            'sell': len(self.active_sell_orders)
        },
        'trading_stats': {
            'total_bought': self.total_bought,
            'total_sold': self.total_sold,
            'maker_buy_volume': self.maker_buy_volume,
            'maker_sell_volume': self.maker_sell_volume,
            'taker_buy_volume': self.taker_buy_volume,
            'taker_sell_volume': self.taker_sell_volume,
            'total_quote_volume': self.total_quote_volume,
        },
        'profit': {
            'total': self.total_profit,
            'session': self._calculate_session_profit(),
            'fees': self.total_fees
        },
        'state': self._get_state()
    }

def _get_state(self) -> str:
    """Returns current bot state: RUNNING, PAUSED, or STOPPED"""
    if getattr(self, '_stop_trading', False):
        return 'STOPPED'
    if getattr(self, '_paused', False):
        return 'PAUSED'
    return 'RUNNING'

def pause_trading(self):
    """Pause trading - cancel orders, keep bot running"""
    self._paused = True
    self.cancel_existing_orders()
    logger.info("Trading paused via Telegram command")

def resume_trading(self):
    """Resume from paused state"""
    self._paused = False
    logger.info("Trading resumed via Telegram command")

def stop_trading_gracefully(self):
    """Graceful shutdown - cancel orders, save stats, cleanup"""
    self._stop_flag = True
    self.cancel_existing_orders()
    if self.ws:
        self.ws.close()
    logger.info("Trading stopped gracefully via Telegram command")
```

### Grid Strategy Override

**File**: `strategies/grid_strategy.py`

Override `get_status_summary()` to include grid-specific metrics:
```python
def get_status_summary(self) -> Dict[str, Any]:
    base_summary = super().get_status_summary()
    base_summary.update({
        'grid_stats': {
            'grid_levels': len(self.grid_levels),
            'price_range': f"{self.grid_lower_price:.4f} ~ {self.grid_upper_price:.4f}",
            'grid_mode': self.grid_mode,
            'buy_fills': self.grid_buy_filled_count,
            'sell_fills': self.grid_sell_filled_count,
            'grid_profit': self.grid_profit,
            'active_buy_orders': sum(len(orders) for orders in self.grid_buy_orders_by_price.values()),
            'active_sell_orders': sum(len(orders) for orders in self.grid_sell_orders_by_price.values()),
        }
    })
    return base_summary
```

### Perpetual Strategy Overrides

**File**: `strategies/perp_market_maker.py` and `strategies/perp_grid_strategy.py`

Override `get_status_summary()` to include position and risk metrics.

### Main Entry Point Modifications

**File**: `run.py`

Add:
```python
parser.add_argument('--enable-telegram', action='store_true', help='Enable Telegram bot integration')

# In main() function:
if args.enable_telegram:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram bot token or chat ID not configured. Please set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env file")
        sys.exit(1)

    from telegram.bot import TelegramBot
    telegram_bot = TelegramBot(
        token=TELEGRAM_BOT_TOKEN,
        chat_id=TELEGRAM_CHAT_ID,
        trading_bot_instance=market_maker,
        update_interval_minutes=TELEGRAM_UPDATE_INTERVAL
    )
    telegram_bot.start()
```

Add cleanup on KeyboardInterrupt:
```python
except KeyboardInterrupt:
    logger.info("收到中斷信號，正在退出...")
    if args.enable_telegram:
        telegram_bot.send_message("⚠️ Bot stopped by user (Ctrl+C)")
        telegram_bot.stop()
```

---

## Status Report Format

The status report will mimic the CLI output format:

```
🤖 Trading Bot Status
━━━━━━━━━━━━━━━━━━━━
📊 Strategy: Grid Trading (arithmetic mode)
💎 Symbol: SOL_USDC
🏢 Exchange: Backpack
⏱️ Runtime: 2h 35m

💰 Balances:
  SOL: 125.5000
  USDC: 5,230.7500

📈 Trading Statistics:
  Total Bought: 1,245.3000 SOL
  Total Sold: 1,219.8000 SOL
  Total Profit: +45.3200 USDC
  Total Fees: 12.4500 USDC
  Net Profit: +32.8700 USDC

📦 Grid Stats:
  Grid Levels: 10
  Price Range: 140.00 ~ 160.00
  Grid Mode: arithmetic
  Buy Fills: 23
  Sell Fills: 21
  Grid Profit: +45.32 USDC

📋 Active Orders:
  Buy Orders: 4
  Sell Orders: 5

⏸️ Status: RUNNING
```

For Market Maker strategy:
```
📊 Strategy: Market Making
📈 Order Statistics:
  Maker Buy Volume: 845.2000 SOL
  Maker Sell Volume: 823.1000 SOL
  Taker Buy Volume: 12.5000 SOL
  Taker Sell Volume: 15.3000 SOL
```

---

## Implementation Details

### Threading Model
- Telegram bot runs in a separate daemon thread
- Uses asyncio (python-telegram-bot)
- Thread-safe state changes using `threading.Lock`
- Does not block main trading loop

### Scheduling
- Periodic updates use `asyncio.sleep()`
- Configurable interval via `TELEGRAM_UPDATE_INTERVAL`
- Skips updates if bot is paused or stopped
- Only sends to configured `TELEGRAM_CHAT_ID`

### Security
- **Chat ID verification**: Only accept commands from configured chat ID
- **No sensitive data**: Never send API keys or tokens via Telegram
- **Rate limiting**: Prevent command spam with minimal delay between commands

### Error Handling
- Network errors: Log and retry
- Invalid commands: Send error message back to user
- Trading bot errors: Log and notify user
- Connection loss: Automatic reconnection (handled by python-telegram-bot)

---

## Usage Examples

### Setting Up Telegram Bot

1. Create a Telegram bot via [@BotFather](https://t.me/botfather):
   ```
   /newbot
   MyTradingBot
   ```
   Copy the API token.

2. Get your Chat ID:
   - Send a message to your bot
   - Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
   - Find your `chat.id` in the response

3. Configure environment variables:
   ```bash
   TELEGRAM_ENABLED=1
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   TELEGRAM_CHAT_ID=987654321
   TELEGRAM_UPDATE_INTERVAL=30
   ```

### Running the Bot

**With Telegram enabled**:
```bash
python run.py --exchange backpack --symbol SOL_USDC --strategy grid --auto-price --grid-num 10 --enable-telegram
```

**Telegram commands**:
```
/status    - Get current bot status
/pause     - Pause trading
/resume    - Resume trading
/stop      - Stop trading gracefully
/logs      - Get recent log entries
/help      - Show all available commands
```

---

## Files to Create

1. `telegram/__init__.py` (10 lines)
2. `telegram/bot.py` (~200 lines)
3. `telegram/handlers.py` (~150 lines)
4. `telegram/formatter.py` (~100 lines)

**Total new code**: ~460 lines

---

## Files to Modify

1. `requirements.txt` - Add `python-telegram-bot>=20.0`
2. `config.py` - Add Telegram configuration (~10 lines)
3. `.env.example` - Add example config (~4 lines)
4. `run.py` - Add Telegram integration (~50 lines)
5. `strategies/market_maker.py` - Add status/control methods (~80 lines)
6. `strategies/grid_strategy.py` - Override get_status_summary (~20 lines)
7. `strategies/perp_market_maker.py` - Override get_status_summary (~20 lines)
8. `strategies/perp_grid_strategy.py` - Override get_status_summary (~20 lines)

**Total modifications**: ~304 lines

---

## Testing Plan

1. **Unit Tests**:
   - Test command handlers individually
   - Test status formatting for each strategy type
   - Test state transitions (start/pause/resume/stop)

2. **Integration Tests**:
   - Test concurrent command handling
   - Test periodic status updates
   - Test integration with different strategies (MM, Grid, Perp MM, Perp Grid)

3. **Error Scenarios**:
   - Invalid chat ID
   - Network connection loss
   - Invalid commands
   - Trading bot errors during Telegram commands

4. **End-to-End**:
   - Run full trading session with Telegram enabled
   - Send all commands from Telegram
   - Verify status updates are received
   - Test graceful shutdown

---

## Future Enhancements (Optional)

- Webhook mode instead of polling (better performance)
- Price alerts (notify when price moves significantly)
- Order notifications (alert on large fills)
- Risk alerts (notify when approaching position limits)
- Multi-user support (admin list instead of single chat ID)
- Interactive buttons (instead of text commands)

---

## Notes

- The bot maintains the original design of **not closing positions** when stopped
- `/stop` performs a graceful shutdown with proper cleanup
- `/pause` is for temporary halts without shutting down
- All commands are logged for audit trail
- Telegram integration is **optional** and disabled by default
