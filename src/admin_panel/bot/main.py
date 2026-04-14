from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import ADMIN_PANEL_TOKEN
from src.admin_panel.bot.handler import router

bot = Bot(ADMIN_PANEL_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
dp.include_router(router)

async def run_admin_bot():
    await bot.delete_webhook(False)
    await dp.start_polling(bot)
