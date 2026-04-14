from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def ProductPhotoDoses(doses: dict[str, str]) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=name, callback_data=f"product_photos:{onec_id}") for onec_id, name in doses.items()]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def DeletePhoto(onec_id: str) -> InlineKeyboardMarkup: return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🗑️ Удалить фото", callback_data=f"delete_photo:{onec_id}")]])
def CategoryButton(category_id: int, name: str) -> InlineKeyboardButton: return InlineKeyboardButton(text=name, callback_data=f"set_category:{category_id}")
def CategoriesKeyboard(categories, per_row: int = 2) -> InlineKeyboardMarkup:
    buttons = [CategoryButton(c.id, c.name) for c in categories]
    rows = [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def CategoryActions(category_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить товар", switch_inline_query_current_chat="addcat "),
         InlineKeyboardButton(text="➖ Убрать товар", switch_inline_query_current_chat="rmcat ")],
        [InlineKeyboardButton(text="🗑️ Удалить категорию", callback_data=f"delete_category:{category_id}")],
        [InlineKeyboardButton(text="📦 Список категорий", callback_data="categories_list")],
    ])

def SelectedCategoryScreen(categories, selected_id: int) -> InlineKeyboardMarkup:
    """
    Shows:
      - other categories as quick switch
      - actions for current category
    """
    other = [c for c in categories if c.id != selected_id]
    kb_other = CategoriesKeyboard(other).inline_keyboard if other else []
    kb_actions = CategoryActions(selected_id).inline_keyboard
    return InlineKeyboardMarkup(inline_keyboard=kb_other + kb_actions)