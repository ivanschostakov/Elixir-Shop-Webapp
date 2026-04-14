import aiofiles

from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, Message

from config import IMAGES_DIR
from src.admin_panel.bot import keyboards, states, texts
from src.database import get_session
from src.database.crud import get_product_with_features


async def __handle_product_message(onec_id: str, message: Message, state: FSMContext):
    if not onec_id:
        await message.answer(texts.photo_command_error.replace("username", (await message.bot.get_me()).username))
        return await message.delete()

    await state.update_data(product_onec_id=onec_id)
    await state.set_state(states.ProductActions.set_product_photo)
    async with get_session() as session: product = await get_product_with_features(session, onec_id)
    photo_path = IMAGES_DIR / f"{onec_id}.png"
    if photo_path.exists(): await message.answer_photo(FSInputFile(photo_path), caption=texts.product_caption.replace("name", product.name))
    doses = {feature.onec_id: feature.name for feature in product.features}
    await state.update_data(doses=doses)
    await message.answer(texts.product_main_photo.replace("name", product.name), reply_markup=keyboards.ProductPhotoDoses(doses))
    return await message.delete()


async def __handle_photo(onec_id: str, message: Message, state: FSMContext):
    if not onec_id: return await message.answer("Ошибочка")

    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    file_bytes = await message.bot.download(file)
    file_bytes = file_bytes.getvalue()
    photo_path = IMAGES_DIR / f"{onec_id}.png"
    async with aiofiles.open(photo_path, "wb") as f: await f.write(file_bytes)
    await message.answer("Фото успешно сохранено")
    return await state.clear()
