import asyncio
import threading
from datetime import datetime
from typing import Optional

from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import TelegramError

from config import TELEGRAM_CHAT_ID, TELEGRAM_UPDATE_INTERVAL
from logger import setup_logger

from .handlers import (
    cmd_start, cmd_stop, cmd_pause, cmd_resume,
    cmd_status, cmd_logs, cmd_help
)
from .formatter import format_success_message, format_info_message

logger = setup_logger("telegram_bot")


class TelegramBot:
    def __init__(self, token: str, chat_id: int, trading_bot_instance, update_interval_minutes: int = 30):
        self.token = token
        self.chat_id = chat_id
        self.trading_bot = trading_bot_instance
        self.update_interval_minutes = update_interval_minutes
        self.application = None
        self.running = False
        self._loop = None
        self._thread = None

        logger.info("TelegramBot initialized")

    def _setup_application(self) -> Application:
        application = Application.builder().token(self.token).build()

        application.bot_data['trading_bot'] = self.trading_bot
        application.bot_data['telegram_bot'] = self

        application.add_handler(CommandHandler("start", cmd_start))
        application.add_handler(CommandHandler("stop", cmd_stop))
        application.add_handler(CommandHandler("pause", cmd_pause))
        application.add_handler(CommandHandler("resume", cmd_resume))
        application.add_handler(CommandHandler("status", cmd_status))
        application.add_handler(CommandHandler("logs", cmd_logs))
        application.add_handler(CommandHandler("help", cmd_help))

        return application

    def _run_application(self):
        self.application = self._setup_application()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            logger.info("Starting Telegram bot polling...")
            loop.run_until_complete(self.application.initialize())
            loop.run_until_complete(self.application.start())
            loop.run_until_complete(self.application.updater.start_polling())

            while self.running:
                loop.run_until_complete(asyncio.sleep(1))

        except Exception as e:
            logger.error(f"Telegram application error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            try:
                loop.run_until_complete(self.application.updater.stop())
                loop.run_until_complete(self.application.shutdown())
            except Exception as e:
                logger.error(f"Error shutting down application: {e}")
            finally:
                loop.close()
                logger.info("Telegram application stopped")

    def start(self):
        if self.running:
            logger.warning("Telegram bot is already running")
            return

        self.running = True

        self._thread = threading.Thread(target=self._run_application, daemon=True)
        self._thread.start()

        logger.info("Telegram bot started in background thread")

        import time
        time.sleep(3)

        self._send_startup_message()

    def _send_startup_message(self):
        try:
            bot = Bot(token=self.token)
            startup_msg = "🚀 Trading Bot Started\n"
            startup_msg += "━━━━━━━━━━━━━━━━━━━━\n"
            startup_msg += f"Symbol: {self.trading_bot.symbol}\n"
            startup_msg += f"Status: Running\n"
            startup_msg += f"Chat ID: {self.chat_id}\n"
            startup_msg += "Use /help for available commands"

            asyncio.run(bot.send_message(chat_id=self.chat_id, text=startup_msg, parse_mode='HTML'))
            logger.info("Startup message sent successfully")
        except Exception as e:
            logger.error(f"Failed to send startup message: {e}")

    async def _send_message_async(self, message: str) -> bool:
        try:
            bot = Bot(token=self.token)
            await bot.send_message(chat_id=self.chat_id, text=message, parse_mode='Markdown')
            await bot.shutdown()
            return True
        except TelegramError as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    def send_message(self, message: str) -> bool:
        if not self.running:
            logger.warning("Cannot send message: bot not running")
            return False

        try:
            bot = Bot(token=self.token)
            asyncio.run(bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML'
            ))
            return True
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return False

    def send_status(self) -> bool:
        try:
            from .formatter import format_status
            status_message = format_status(self.trading_bot)
            return self.send_message(status_message)
        except Exception as e:
            logger.error(f"Error sending status: {e}")
            return False

    async def _schedule_status_update_task(self):
        while self.running:
            try:
                await asyncio.sleep(self.update_interval_minutes * 60)
                if self.running:
                    logger.info("Sending scheduled status update")
                    bot = Bot(token=self.token)
                    await bot.send_message(
                        chat_id=self.chat_id,
                        text=await self._get_status_async(),
                        parse_mode='HTML'
                    )
                    await bot.shutdown()
            except asyncio.CancelledError:
                logger.info("Status update task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in status update loop: {e}")
                await asyncio.sleep(60)

    async def _get_status_async(self) -> str:
        try:
            from .formatter import format_status
            return format_status(self.trading_bot)
        except Exception as e:
            logger.error(f"Error generating status: {e}")
            return f"Error generating status: {e}"

    def schedule_status_update(self):
        if not self.running:
            logger.warning("Cannot schedule status update: bot not running")
            return

        try:
            asyncio.run_coroutine_threadsafe(
                self._schedule_status_update_task(),
                asyncio.get_event_loop()
            )
            logger.info(f"Status updates scheduled every {self.update_interval_minutes} minutes")
        except Exception as e:
            logger.error(f"Error scheduling status update: {e}")

    def get_recent_logs(self, lines: int = 50) -> str:
        log_file = self.trading_bot.logger.handlers[0].baseFilename if hasattr(self.trading_bot.logger, 'handlers') else None

        if not log_file:
            log_file = 'market_maker.log'

        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                all_lines = f.readlines()
                recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
                return ''.join(recent_lines)
        except FileNotFoundError:
            logger.warning(f"Log file not found: {log_file}")
            return "Log file not found"
        except Exception as e:
            logger.error(f"Error reading log file: {e}")
            return f"Error reading log file: {e}"

    def stop(self):
        if not self.running:
            logger.warning("Telegram bot is not running")
            return

        logger.info("Stopping Telegram bot...")
        self.running = False

        logger.info("Telegram bot stopped")

    def __del__(self):
        if self.running:
            self.stop()
