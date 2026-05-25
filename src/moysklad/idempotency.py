from uuid import NAMESPACE_URL, UUID, uuid5

from config import (
    MOY_SKLAD_COUNTERPARTY_EXTERNAL_CODE_PREFIX,
    MOY_SKLAD_CUSTOMERORDER_EXTERNAL_CODE_PREFIX,
)


def build_counterparty_external_code(*, user_id: int) -> str:
    return f"{MOY_SKLAD_COUNTERPARTY_EXTERNAL_CODE_PREFIX}:{int(user_id)}"


def build_customerorder_external_code(*, order_id: int) -> str:
    return f"{MOY_SKLAD_CUSTOMERORDER_EXTERNAL_CODE_PREFIX}:{int(order_id)}"


def build_sync_id(*, scope: str, key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"elixir-shop:moysklad:{scope}:{key}")
