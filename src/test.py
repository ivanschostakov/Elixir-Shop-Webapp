import asyncio
import datetime

from config import TELETHON_PHONE, TELETHON_PASSWORD, NEW_BOT_TOKEN, PROFESSOR_BOT_TOKEN, DOSE_BOT_TOKEN
from src.database import get_session
from src.database.crud import get_users
from src.tg_methods import client as tg_client

BOT_NAMES = {
    PROFESSOR_BOT_TOKEN: "@ProfessorOfPeptidesbot",
    DOSE_BOT_TOKEN: "@Peptideexpertbot",
    NEW_BOT_TOKEN: "@elixirpeptidebot",
}

async def main():
    async with get_session() as db: users = await get_users(db)
    await tg_client.start(TELETHON_PHONE, TELETHON_PASSWORD)
    for bot_token in [NEW_BOT_TOKEN, PROFESSOR_BOT_TOKEN, DOSE_BOT_TOKEN]:
        messages = []
        async for message in tg_client.iter_messages((BOT_NAMES[bot_token]), offset_date=datetime.date.today(), reverse=True):
            print(message.id, message.text)
            if "send_all" in message.text: break

asyncio.run(main())
