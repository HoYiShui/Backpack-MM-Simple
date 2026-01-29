from telegram import Update
from telegram.ext import ContextTypes
from logger import setup_logger

logger = setup_logger("telegram_handlers")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info(f"Received /start command from user {update.effective_user.id}")
    trading_bot = context.bot_data.get('trading_bot')
    if not trading_bot:
        logger.warning("Trading bot not found in bot_data")
        await update.message.reply_text("❌ Trading bot not initialized")
        return

    try:
        trading_bot.resume_trading()
        await update.message.reply_text("✅ Trading resumed/started")
        logger.info("Telegram /start command executed successfully")
    except Exception as e:
        logger.error(f"Error executing /start: {e}")
        await update.message.reply_text(f"❌ Failed to start: {e}")


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    trading_bot = context.bot_data.get('trading_bot')
    if not trading_bot:
        return

    try:
        trading_bot.stop_trading_gracefully()
        await update.message.reply_text("✅ Trading stopped gracefully")
        logger.info("Telegram /stop command executed")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to stop: {e}")
        logger.error(f"Error executing /stop: {e}")


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    trading_bot = context.bot_data.get('trading_bot')
    if not trading_bot:
        return

    try:
        trading_bot.pause_trading()
        await update.message.reply_text("✅ Trading paused")
        logger.info("Telegram /pause command executed")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to pause: {e}")
        logger.error(f"Error executing /pause: {e}")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    trading_bot = context.bot_data.get('trading_bot')
    if not trading_bot:
        return

    try:
        trading_bot.resume_trading()
        await update.message.reply_text("✅ Trading resumed")
        logger.info("Telegram /resume command executed")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to resume: {e}")
        logger.error(f"Error executing /resume: {e}")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info(f"Received /status command from user {update.effective_user.id}")
    trading_bot = context.bot_data.get('trading_bot')
    if not trading_bot:
        logger.warning("Trading bot not found in bot_data")
        await update.message.reply_text("❌ Trading bot not initialized")
        return

    try:
        from telegram_bot.formatter import format_status
        status_message = format_status(trading_bot)
        await update.message.reply_text(status_message)
        logger.info("Telegram /status command executed successfully")
    except Exception as e:
        logger.error(f"Error executing /status: {e}")
        await update.message.reply_text(f"❌ Failed to get status: {e}")

async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    trading_bot = context.bot_data.get('trading_bot')
    if not trading_bot:
        return

    try:
        telegram_bot = context.bot_data.get('telegram_bot')
        if telegram_bot:
            logs = telegram_bot.get_recent_logs(lines=50)
            if logs:
                message = "📋 Recent Logs (last 50 lines):\n"
                message += "━━━━━━━━━━━━━━━━━━━━\n"
                message += "```\n"
                message += logs
                message += "```"

                if len(message) > 4096:
                    message = message[:4090] + "...\n```"

                await update.message.reply_text(message, parse_mode='Markdown')
            else:
                await update.message.reply_text("ℹ️ No logs available")
        logger.info("Telegram /logs command executed")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to get logs: {e}")
        logger.error(f"Error executing /logs: {e}")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info(f"Received /help command from user {update.effective_user.id}")
    try:
        from telegram_bot.formatter import format_help_message
        help_message = format_help_message()
        await update.message.reply_text(help_message)
        logger.info("Telegram /help command executed successfully")
    except Exception as e:
        logger.error(f"Error executing /help: {e}")
        await update.message.reply_text(f"❌ Failed to show help: {e}")
