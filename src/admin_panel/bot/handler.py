from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InputTextMessageContent, InlineQueryResultArticle, Message, InlineQuery, CallbackQuery, FSInputFile

from config import OWNER_TG_IDS, IMAGES_DIR
from src.admin_panel.bot import texts, keyboards, states
from src.admin_panel.bot.helpers import __handle_product_message, __handle_photo
from src.database import get_session
from src.webapp.routes.search import search_products
from src.database.schemas import TgCategoryCreate
from src.database.crud import create_tg_category, list_tg_categories, get_tg_category_by_id, get_tg_category_by_name, delete_tg_category, add_tg_category_to_product, remove_tg_category_from_product

router = Router()
admin_filter = lambda obj: obj.from_user and obj.from_user.id in OWNER_TG_IDS and obj.chat.type == ChatType.PRIVATE
admin_call_filter = lambda obj: obj.from_user and obj.from_user.id in OWNER_TG_IDS and obj.message.chat.type == ChatType.PRIVATE
admin_inline_filter = lambda obj: obj.from_user and obj.from_user.id in OWNER_TG_IDS

router.message.filter(admin_filter)
router.callback_query.filter(admin_call_filter)
router.inline_query.filter(admin_inline_filter)


@router.message(Command("photo"))
async def handle_photo(message: Message, state: FSMContext):
    onec_id = message.text.removeprefix("/photo").strip()
    await __handle_product_message(onec_id, message, state)


@router.message(lambda message: message.photo, states.ProductActions.set_product_photo)
async def handle_product_photos(message: Message, state: FSMContext):
    state_data = await state.get_data()
    product_onec_id = state_data.get("product_onec_id")
    await __handle_photo(product_onec_id, message, state)


@router.message(lambda message: message.photo, states.ProductActions.set_feature_photo)
async def handle_feature_photo(message: Message, state: FSMContext):
    state_data = await state.get_data()
    feature_onec_id = state_data.get("feature_onec_id")
    await __handle_photo(feature_onec_id, message, state)


@router.message(Command("create_category"))
async def handle_create_category(message: Message):
    name = message.text.removeprefix("/create_category").strip()
    if not name: return await message.answer("Добавьте название: <code>/create_category Название категории</code>")

    async with get_session() as session: category = await create_tg_category(session, TgCategoryCreate(name=name))
    return await message.answer(f"✅ Категория создана: <b>{category.name}</b> (id={category.id})\nТеперь выберите её в /categories")


@router.message(Command("categories"))
async def handle_categories(message: Message):
    async with get_session() as session: categories = await list_tg_categories(session)
    if not categories: return await message.answer("Категорий нет. Создайте: <code>/create_category Название</code>")

    return await message.answer("📦 Выберите категорию:", reply_markup=keyboards.CategoriesKeyboard(categories))


@router.message(Command("delete_category"))
async def handle_delete_category_cmd(message: Message):
    raw = message.text.removeprefix("/delete_category").strip()
    if not raw: return await message.answer("Укажите категорию: <code>/delete_category ID</code> или <code>/delete_category Название</code>")

    async with get_session() as session:
        category = None
        if raw.isdigit(): category = await get_tg_category_by_id(session, int(raw))
        if not category: category = await get_tg_category_by_name(session, raw)
        if not category: return await message.answer("Категория не найдена.")
        await delete_tg_category(session, category)

    return await message.answer(f"🗑️ Категория удалена: <b>{raw}</b>")


@router.message(Command("add_category"))
async def handle_add_category_to_product(message: Message):
    args = message.text.removeprefix("/add_category").strip().split(maxsplit=1)
    if len(args) != 2:
        return await message.answer("Формат: <code>/add_category CATEGORY_ID ONEC_ID_товара</code>")

    category_id = int(args[0])
    product_onec_id = args[1].strip()
    async with get_session() as session:
        await add_tg_category_to_product(session, product_onec_id=product_onec_id, tg_category_id=category_id)
        category = await get_tg_category_by_id(session, category_id)

    return await message.answer(f"✅ Добавлено: <b>{product_onec_id}</b> → <b>{category.name}</b>")


@router.message(Command("remove_category"))
async def handle_remove_category_from_product(message: Message):
    args = message.text.removeprefix("/remove_category").strip().split(maxsplit=1)
    if len(args) != 2: return await message.answer("Формат: <code>/remove_category CATEGORY_ID ONEC_ID_товара</code>")

    category_id = int(args[0])
    product_onec_id = args[1].strip()
    async with get_session() as session:
        await remove_tg_category_from_product(session, product_onec_id=product_onec_id, tg_category_id=category_id)
        category = await get_tg_category_by_id(session, category_id)

    return await message.answer(f"➖ Удалено: <b>{product_onec_id}</b> ⟵ <b>{category.name}</b>")

@router.inline_query(lambda q: q.query.startswith("addcat"))
async def inline_addcat(inline_query: InlineQuery, state: FSMContext):
    st = await state.get_data()
    category_id = st.get("category_id")
    if not category_id: return await inline_query.answer([InlineQueryResultArticle(id="0", title="Сначала выберите категорию", input_message_content=InputTextMessageContent(message_text="/categories"))], cache_time=1)

    query = inline_query.query.removeprefix("addcat").strip()
    if not query: return None

    async with get_session() as db: data = await search_products(db, q=query, page=0, limit=10)
    results = [InlineQueryResultArticle(id=str(idx), title=item["name"], description=", ".join(f["name"] for f in item["features"]), input_message_content=InputTextMessageContent(message_text=f"/add_category {category_id} {item["url"].removeprefix("/product/")}")) for idx, item in enumerate(data["results"], start=1)]
    return await inline_query.answer(results, cache_time=1)


@router.inline_query(lambda q: q.query.startswith("rmcat"))
async def inline_rmcat(inline_query: InlineQuery, state: FSMContext):
    st = await state.get_data()
    category_id = st.get("category_id")
    if not category_id: return await inline_query.answer([InlineQueryResultArticle(id="0", title="Сначала выберите категорию", input_message_content=InputTextMessageContent(message_text="/categories"))], cache_time=1)

    query = inline_query.query.removeprefix("rmcat").strip()
    if not query: return None
    async with get_session() as db: data = await search_products(db, q=query, page=0, limit=10)

    results = [InlineQueryResultArticle(id=str(idx), title=item["name"], description=", ".join(f["name"] for f in item["features"]), input_message_content=InputTextMessageContent(message_text=f"/remove_category {category_id} {item["url"].removeprefix("/product/")}")) for idx, item in enumerate(data["results"], start=1)]
    return await inline_query.answer(results, cache_time=1)


@router.inline_query(lambda inline_query: inline_query.query.startswith("photo"))
async def set_product_photo(inline_query: InlineQuery):
    query = inline_query.query.removeprefix("photo").strip()
    if not query: return None
    async with get_session() as db: data = await search_products(db, q=query, page=0, limit=10)

    results = [InlineQueryResultArticle(id=str(idx), title=item["name"], description=", ".join(f["name"] for f in item["features"]), input_message_content=InputTextMessageContent(message_text=f'/photo {item["url"].removeprefix("/product/")}')) for idx, item in enumerate(data["results"], start=1)]
    return await inline_query.answer(results, cache_time=1)


@router.callback_query()
async def handle_callback(call: CallbackQuery, state: FSMContext):
    raw = call.data or ""
    parts = raw.split(":")
    action = parts[0]
    payload = ":".join(parts[1:])                                             

    if action == "product_photos":
        feature_onec_id = payload
        photo_path = IMAGES_DIR / f"{feature_onec_id}.png"
        if photo_path.exists():
            await call.message.answer_photo(FSInputFile(photo_path), caption=texts.feature_caption)
            await call.message.answer("Нажмите кнопку ниже, чтоб удалить фото для дозировки", reply_markup=keyboards.DeletePhoto(feature_onec_id))

        await state.set_state(states.ProductActions.set_feature_photo)
        await state.update_data(feature_onec_id=feature_onec_id)
        return await call.answer()

    if action == "delete_photo":
        onec_id = payload
        photo_path = IMAGES_DIR / f"{onec_id}.png"
        if photo_path.exists(): photo_path.unlink()
        await call.message.edit_text("Фото успешно удалено", reply_markup=None)
        return await call.answer()

    if action == "categories_list":
        async with get_session() as session: categories = await list_tg_categories(session)
        if not categories: await call.message.edit_text("Категорий нет. Создайте: /create_category Название", reply_markup=None)
        else: await call.message.edit_text("📦 Выберите категорию:", reply_markup=keyboards.CategoriesKeyboard(categories))
        return await call.answer()

    if action == "set_category":
        category_id = int(payload)
        async with get_session() as session:
            categories = await list_tg_categories(session)
            category = await get_tg_category_by_id(session, category_id)

        if not category: return await call.answer("Категория не найдена", show_alert=True)
        await state.set_state(states.ProductActions.set_category)
        await state.set_data({"category_id": category_id, "category_name": category.name})
        await call.message.edit_text(f"✅ Выбрана категория: <b>{category.name}</b> (id={category.id})\nТеперь можно добавлять/убирать товары:", reply_markup=keyboards.SelectedCategoryScreen(categories, category_id))
        return await call.answer()

    if action == "delete_category":
        category_id = int(payload)
        async with get_session() as session:
            category = await get_tg_category_by_id(session, category_id)
            if not category: return await call.answer("Категория не найдена", show_alert=True)
            await delete_tg_category(session, category)

        await call.message.edit_text(f"🗑️ Категория удалена (id={category_id}).", reply_markup=None)
        return await call.answer()

    return await call.answer()
