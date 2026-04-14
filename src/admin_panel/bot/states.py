from aiogram.fsm.state import State, StatesGroup

class ProductActions(StatesGroup):
    set_product_photo = State()
    set_feature_photo = State()
    set_category = State()
