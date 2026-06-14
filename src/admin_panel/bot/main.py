import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage

from config import ADMIN_PANEL_TOKEN
from src.admin_panel.bot.handler import router

logger = logging.getLogger(__name__)
telegram_proxy_url = (os.getenv("TELEGRAM_PROXY_URL") or "").strip() or None
session = AiohttpSession(proxy=telegram_proxy_url) if telegram_proxy_url else None
bot = Bot(ADMIN_PANEL_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
dp.include_router(router)

async def _delete_webhook_with_retries() -> None:
    for attempt in range(1, 4):
        try:
            await bot.delete_webhook(False, request_timeout=20)
            return
        except TelegramNetworkError:
            logger.warning("Admin bot delete_webhook timed out; retrying attempt=%s", attempt, exc_info=True)
            if attempt == 3:
                raise
            await asyncio.sleep(3 * attempt)

async def run_admin_bot():
    if telegram_proxy_url:
        logger.info("Admin bot using Telegram proxy: %s", telegram_proxy_url)
    await _delete_webhook_with_retries()
    await dp.start_polling(bot)
