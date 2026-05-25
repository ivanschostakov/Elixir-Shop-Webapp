from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import AMOCRM_BASE_DOMAIN, MOY_SKLAD_ORDER_SYNC_ENABLED, MOY_SKLAD_ORGANIZATION_ID, MOY_SKLAD_SALES_CHANNEL_HREF
from src.database.crud import get_cart_by_id, update_cart, update_user
from src.database.models import Cart, Feature, User
from src.database.schemas import CartUpdate, UserUpdate
from src.helpers import normalize_address_for_cf

from .idempotency import (
    build_counterparty_external_code,
    build_customerorder_external_code,
    build_sync_id,
)
from .order_client import (
    MoySkladOrderClient,
    coerce_uuid,
    get_moysklad_order_client,
    optional_str,
)

log = logging.getLogger(__name__)
MOY_SKLAD_REQUIRED_STORE_NAME = "Основной склад"
MOY_SKLAD_STATE_NEW_ORDER = "Новый заказ"
MOY_SKLAD_STATE_INVOICE_SENT = "Счет отправлен"
MOY_SKLAD_STATE_INVOICE_PAID = "Счет оплачен"
MOY_SKLAD_INVOICEOUT_STATE_PAID = "Оплачен"
MOY_SKLAD_PAYMENT_LATER = "СБП через менеджера"
MOY_SKLAD_PAYMENT_INTELLECT = "IntellectMoney"
MOY_SKLAD_DEFAULT_DELIVERY_METHOD_NAMES = {"CDEK": "СДЭК", "YANDEX": "Яндекс.Доставка"}
COUNTRY_NAMES: dict[str, str] = {
    "RU": "Россия",
    "KZ": "Казахстан",
    "BY": "Беларусь",
    "AM": "Армения",
}

_STREET_HINT_RE = re.compile(r"\b(ул\.?|улиц|пр-?кт|просп|пер\.?|переул|бул\.?|бульв|наб\.?|набереж|ш\.?|шоссе|проезд|пр-д|пл\.?|площадь|аллея|тупик)\b", re.IGNORECASE)
_HOUSE_RE = re.compile(r"\b(?:д\.?|дом)\s*([0-9A-Za-zА-Яа-я/-]+(?:\s*(?:к(?:орп)?\.?|стр\.?|с)\s*[0-9A-Za-zА-Яа-я/-]+)?)", re.IGNORECASE)
_APARTMENT_RE = re.compile(r"\b(?:кв\.?|квартира|ап\.?|apartment|офис|оф\.?)\s*([0-9A-Za-zА-Яа-я/-]+)", re.IGNORECASE)
_REGION_HINT_RE = re.compile(r"\b(обл\.?|область|край|респ\.?|республика|автономный округ|ао)\b", re.IGNORECASE)
_BUILDING_HINT_RE = re.compile(r"\b(корп\.?|корпус|стр\.?|строение|лит\.?)\b", re.IGNORECASE)


def _extract_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _lower_optional_str(value: Any) -> str | None:
    normalized = optional_str(value)
    return normalized.lower() if normalized else None


def _full_name(user: User, cart: Cart) -> str:
    snapshot = _extract_dict(cart.checkout_snapshot)
    contact_info = _extract_dict(snapshot.get("contact_info"))
    parts = [optional_str(contact_info.get("name")), optional_str(contact_info.get("surname"))]
    full_name = " ".join(part for part in parts if part)
    if full_name:
        return full_name

    email = _counterparty_email(user, cart)
    if email:
        return email
    return f"User {user.tg_id}"


def _counterparty_email(user: User, cart: Cart) -> str | None:
    snapshot = _extract_dict(cart.checkout_snapshot)
    contact_info = _extract_dict(snapshot.get("contact_info"))
    email = optional_str(contact_info.get("email"))
    if email:
        return email
    return optional_str(getattr(user, "email", None)) or optional_str(cart.email)


def _counterparty_phone(user: User, cart: Cart) -> str | None:
    snapshot = _extract_dict(cart.checkout_snapshot)
    contact_info = _extract_dict(snapshot.get("contact_info"))
    phone = optional_str(contact_info.get("phone"))
    if phone:
        return phone
    return optional_str(user.tg_phone) or optional_str(cart.phone)


def _counterparty_address(cart: Cart) -> str | None:
    selected_delivery = _extract_dict(cart.selected_delivery_payload)
    address = normalize_address_for_cf(selected_delivery.get("address"))
    if address:
        return address
    return optional_str(cart.delivery_string)


def _configured_organization_id():
    configured_id = coerce_uuid(MOY_SKLAD_ORGANIZATION_ID)
    if configured_id is None and optional_str(MOY_SKLAD_ORGANIZATION_ID):
        log.warning("MOY_SKLAD_ORGANIZATION_ID is not a valid UUID: %s", MOY_SKLAD_ORGANIZATION_ID)
    return configured_id


def _snapshot_items(cart: Cart) -> list[dict[str, Any]]:
    checkout_data = _extract_dict(_extract_dict(cart.checkout_snapshot).get("checkout_data"))
    items = checkout_data.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    return []


def _snapshot_price_map(cart: Cart) -> dict[tuple[str, str], Decimal]:
    prices: dict[tuple[str, str], Decimal] = {}
    for item in _snapshot_items(cart):
        product_id = optional_str(item.get("id")) or ""
        feature_id = optional_str(item.get("featureId")) or ""
        if not product_id or not feature_id:
            continue
        raw_price = item.get("price")
        if raw_price is None:
            raw_price = item.get("subtotal")
            qty = int(item.get("qty") or 1)
            if qty > 0:
                raw_price = Decimal(str(raw_price or 0)) / Decimal(str(qty))
        try:
            price = Decimal(str(raw_price or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except Exception:
            price = Decimal("0.00")
        prices[(product_id, feature_id)] = price
    return prices


async def _load_feature_prices(session: AsyncSession, *, feature_ids: list[str]) -> dict[str, Decimal]:
    normalized_ids = [feature_id for feature_id in {optional_str(fid) for fid in feature_ids} if feature_id]
    if not normalized_ids:
        return {}
    rows = (
        await session.execute(
            select(Feature.onec_id, Feature.price).where(Feature.onec_id.in_(normalized_ids))
        )
    ).all()
    return {str(onec_id): Decimal(str(price or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) for onec_id, price in rows}


def _order_positions_discount_percent(cart: Cart) -> Decimal:
    items = _snapshot_items(cart)
    subtotal = Decimal("0.00")
    for item in items:
        try:
            line_subtotal = Decimal(str(item.get("subtotal") or 0))
        except Exception:
            line_subtotal = Decimal("0.00")
        if line_subtotal <= 0:
            try:
                price = Decimal(str(item.get("price") or 0))
                qty = Decimal(str(item.get("qty") or 0))
                line_subtotal = price * qty
            except Exception:
                line_subtotal = Decimal("0.00")
        subtotal += line_subtotal

    if subtotal <= Decimal("0.00"):
        return Decimal("0.00")

    checkout_data = _extract_dict(_extract_dict(cart.checkout_snapshot).get("checkout_data"))
    try:
        total_after = Decimal(str(checkout_data.get("total") or cart.sum or 0))
    except Exception:
        total_after = Decimal(str(cart.sum or 0))

    if total_after <= Decimal("0.00") or total_after >= subtotal:
        return Decimal("0.00")

    discount_amount = subtotal - total_after
    discount_pct = ((discount_amount * Decimal("100.00")) / subtotal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return max(Decimal("0.00"), min(Decimal("100.00"), discount_pct))


async def _build_customerorder_positions(
    session: AsyncSession,
    *,
    moysklad_client: MoySkladOrderClient,
    cart: Cart,
) -> tuple[list[dict[str, Any]], list[str]]:
    positions: list[dict[str, Any]] = []
    missing_feature_ids: list[str] = []
    discount_percent = _order_positions_discount_percent(cart)
    snapshot_prices = _snapshot_price_map(cart)

    all_feature_ids = [optional_str(item.feature_onec_id) or "" for item in (cart.items or [])]
    fallback_feature_prices = await _load_feature_prices(session, feature_ids=all_feature_ids)

    for item in (cart.items or []):
        product_raw = optional_str(item.product_onec_id)
        feature_raw = optional_str(item.feature_onec_id)
        if not product_raw or not feature_raw:
            missing_feature_ids.append(feature_raw or "unknown")
            continue

        product_id = coerce_uuid(product_raw)
        if product_id is None:
            missing_feature_ids.append(feature_raw)
            continue

        synthetic_id = f"{product_raw}__synthetic"
        if feature_raw == synthetic_id:
            assortment_entity_type = "product"
            assortment_id = product_id
        else:
            variant_id = coerce_uuid(feature_raw)
            if variant_id is None:
                missing_feature_ids.append(feature_raw)
                continue
            assortment_entity_type = "variant"
            assortment_id = variant_id

        price = snapshot_prices.get((product_raw, feature_raw))
        if price is None:
            price = fallback_feature_prices.get(feature_raw)
        if price is None:
            price = Decimal("0.00")

        positions.append(
            moysklad_client.build_customerorder_position(
                assortment_entity_type=assortment_entity_type,
                assortment_id=assortment_id,
                quantity=int(item.quantity or 0),
                unit_price=price,
                discount=discount_percent,
            )
        )

    return positions, missing_feature_ids


def _build_order_description(cart: Cart) -> str:
    comment = optional_str(cart.commentary)
    if comment:
        return f"{cart.id}. {comment}"
    return str(cart.id)


def _delivery_cost_value(cart: Cart) -> str:
    return f"{Decimal(str(cart.delivery_sum or 0)):.2f}"


def _moysklad_order_data(cart: Cart) -> dict[str, Any]:
    return _extract_dict(_extract_dict(cart.checkout_snapshot).get("moysklad"))


def _href(value: Any) -> str | None:
    normalized = optional_str(value)
    if not normalized or not normalized.startswith(("http://", "https://")):
        return None
    return normalized


def _order_payment_method_name(cart: Cart) -> str | None:
    return MOY_SKLAD_PAYMENT_LATER if _lower_optional_str(cart.payment_method) == "later" else MOY_SKLAD_PAYMENT_INTELLECT


def _is_intellectmoney_payment(cart: Cart) -> bool:
    payment_method = _lower_optional_str(cart.payment_method)
    payment_provider = _lower_optional_str(cart.payment_provider)
    return payment_method == "sbp" or payment_provider == "intellectmoney"


def _invoiceout_external_code(order_id: int) -> str:
    return f"{build_customerorder_external_code(order_id=order_id)}:invoiceout"


def _invoiceout_name(cart: Cart) -> str:
    return f"Счет по заказу {cart.id}"


def _order_state_name(cart: Cart) -> str:
    _ = cart
    return MOY_SKLAD_STATE_NEW_ORDER


def _order_delivery_method_name(cart: Cart) -> str | None:
    selected_delivery_service = optional_str(cart.selected_delivery_service)
    if not selected_delivery_service:
        return None
    return MOY_SKLAD_DEFAULT_DELIVERY_METHOD_NAMES.get(selected_delivery_service.upper())


async def _moysklad_custom_attr_refs(moysklad_client: MoySkladOrderClient, cart: Cart) -> dict[str, str]:
    refs: dict[str, str] = {}
    payment_method_name = _order_payment_method_name(cart)
    if payment_method_name:
        payment_method = await moysklad_client.find_customerorder_customentity_value("payment_method", payment_method_name)
        payment_method_href = _href((payment_method or {}).get("meta", {}).get("href"))
        if payment_method_href:
            refs["payment_method"] = payment_method_href

    delivery_method_name = _order_delivery_method_name(cart)
    if delivery_method_name:
        delivery_method = await moysklad_client.find_customerorder_customentity_value("delivery_method", delivery_method_name)
        delivery_method_href = _href((delivery_method or {}).get("meta", {}).get("href"))
        if delivery_method_href:
            refs["delivery_method"] = delivery_method_href
    return refs


def _amocrm_lead_link(cart: Cart) -> str | None:
    lead_id = optional_str(cart.amocrm_lead_id)
    domain = optional_str(AMOCRM_BASE_DOMAIN)
    if not lead_id or not domain:
        return None
    normalized_domain = domain.replace("https://", "").replace("http://", "").strip("/")
    if not normalized_domain:
        return None
    return f"https://{normalized_domain}/leads/detail/{lead_id}"


def _moysklad_attr_values(cart: Cart) -> dict[str, Any]:
    data = _moysklad_order_data(cart)
    raw_values = _extract_dict(data.get("attributes"))
    values: dict[str, Any] = {
        "delivery_cost": optional_str(raw_values.get("delivery_cost")) or _delivery_cost_value(cart),
        "created_by_widget": False,
    }

    promo_code = optional_str(raw_values.get("promo_code")) or optional_str(data.get("promo_code")) or optional_str(cart.promo_code)
    if promo_code:
        values["promo_code"] = promo_code

    deal_link = _amocrm_lead_link(cart) or optional_str(raw_values.get("deal_link")) or optional_str(data.get("deal_link"))
    if deal_link:
        values["deal_link"] = deal_link

    for key in ("client_waybill_link", "tracking_number", "site_order_link", "delivery_tracking"):
        value = optional_str(raw_values.get(key)) or optional_str(data.get(key))
        if value:
            values[key] = value

    return values


def _maybe_meta_row(value: Any, *, entity_type: str) -> dict[str, Any] | None:
    if isinstance(value, dict) and isinstance(value.get("meta"), dict):
        return {"meta": value["meta"]}
    if isinstance(value, dict):
        href = optional_str(value.get("href"))
        if href:
            return {"meta": {"href": href, "type": optional_str(value.get("type")) or entity_type, "mediaType": "application/json"}}
    href = optional_str(value)
    if not href:
        return None
    return {"meta": {"href": href, "type": entity_type, "mediaType": "application/json"}}


async def _resolve_customerorder_refs(moysklad_client: MoySkladOrderClient, cart: Cart) -> dict[str, dict[str, Any] | None]:
    store = _maybe_meta_row(await moysklad_client.find_store_by_name(MOY_SKLAD_REQUIRED_STORE_NAME), entity_type="store")
    state = _maybe_meta_row(await moysklad_client.find_customerorder_state_by_name(_order_state_name(cart)), entity_type="state")
    sales_channel = _maybe_meta_row(MOY_SKLAD_SALES_CHANNEL_HREF, entity_type="saleschannel")
    return {"store": store, "state": state, "sales_channel": sales_channel}


def _shipment_address(cart: Cart) -> str | None:
    selected_delivery = _extract_dict(cart.selected_delivery_payload)
    address = _extract_dict(selected_delivery.get("address"))
    full = optional_str(address.get("full_address")) or optional_str(address.get("formatted")) or optional_str(address.get("address"))
    if full:
        return full
    normalized = normalize_address_for_cf(address)
    if normalized:
        return normalized
    return optional_str(cart.delivery_string)


def _address_segments(full: str) -> list[str]:
    return [segment.strip() for segment in full.split(",") if optional_str(segment)]


def _extract_street(full: str) -> str | None:
    for segment in _address_segments(full):
        if _STREET_HINT_RE.search(segment):
            return segment
    return None


def _extract_house(full: str, *, street: str | None = None) -> str | None:
    explicit = _HOUSE_RE.search(full)
    if explicit:
        return optional_str(explicit.group(1))

    segments = _address_segments(full)
    if not segments:
        return None
    if street is None:
        street = _extract_street(full)
    if not street:
        return None

    for index, segment in enumerate(segments):
        if segment != street:
            continue
        if index + 1 >= len(segments):
            return None
        next_segment = segments[index + 1]
        if not re.fullmatch(r"[0-9A-Za-zА-Яа-я/-]+", next_segment):
            return None
        if index + 2 < len(segments) and _BUILDING_HINT_RE.search(segments[index + 2]):
            return f"{next_segment}, {segments[index + 2]}"
        return next_segment
    return None


def _extract_apartment(full: str) -> str | None:
    apartment = _APARTMENT_RE.search(full)
    if apartment:
        return optional_str(apartment.group(1))
    return None


def _extract_region(full: str) -> str | None:
    for segment in _address_segments(full):
        if _REGION_HINT_RE.search(segment):
            return segment
    return None


def _country_name_from_payload(country_name: Any, country_code: Any) -> str | None:
    normalized_name = optional_str(country_name)
    if normalized_name:
        return normalized_name
    normalized_code = optional_str(country_code)
    if not normalized_code:
        return None
    return COUNTRY_NAMES.get(normalized_code.upper())


async def _shipment_address_full(cart: Cart, *, moysklad_client: MoySkladOrderClient) -> dict[str, Any] | None:
    payload = _extract_dict(cart.selected_delivery_payload)
    address = _extract_dict(payload.get("address"))
    full = optional_str(address.get("full_address")) or optional_str(address.get("formatted")) or optional_str(address.get("address")) or _shipment_address(cart)
    if not full:
        return None

    result: dict[str, Any] = {}
    city = optional_str(address.get("city"))
    postal = optional_str(address.get("postal_code"))
    details = optional_str(address.get("details"))
    street = optional_str(address.get("street")) or _extract_street(full)
    house = optional_str(address.get("house")) or _extract_house(full, street=street)
    apartment = optional_str(address.get("apartment")) or _extract_apartment(full)
    region_name = optional_str(address.get("region")) or _extract_region(full)
    country_code = optional_str(address.get("country_code"))
    country_name = _country_name_from_payload(address.get("country"), country_code)
    country_row = await moysklad_client.find_country_by_name_or_code(country_code or "", country_name or "")

    if city:
        result["city"] = city
    if postal:
        result["postalCode"] = postal
    if details:
        result["comment"] = details
    if street:
        result["street"] = street
    if house:
        result["house"] = house
    if apartment:
        result["apartment"] = apartment
    if country_row and isinstance(country_row.get("meta"), dict):
        result["country"] = {"meta": country_row["meta"]}
    if region_name:
        country_id = coerce_uuid(country_row.get("id")) if country_row is not None else None
        region_row = await moysklad_client.find_region_by_name(region_name, country_id=country_id)
        if region_row and isinstance(region_row.get("meta"), dict):
            result["region"] = {"meta": region_row["meta"]}

    has_structured_location = any(result.get(field_name) for field_name in ("city", "postalCode", "street", "house", "apartment"))
    if not has_structured_location:
        result["addInfo"] = full
    return result


async def sync_moysklad_customerorder_state(cart: Cart, *, state_name: str) -> bool:
    normalized_state_name = optional_str(state_name)
    if not MOY_SKLAD_ORDER_SYNC_ENABLED or not normalized_state_name:
        return False

    moysklad_client = get_moysklad_order_client()
    if not moysklad_client.is_configured():
        return False

    try:
        state = await moysklad_client.find_customerorder_state_by_name(normalized_state_name)
        if state is None:
            log.warning("Skipping MoySklad customerorder state sync because state not found state_name=%s cart_id=%s", normalized_state_name, cart.id)
            return False

        customerorder_id = coerce_uuid(getattr(cart, "moysklad_customerorder_id", None))
        current_order = await moysklad_client.get_customer_order(customerorder_id) if customerorder_id is not None else None
        if current_order is None:
            current_order = await moysklad_client._find_entity_by_external_code(
                "customerorder",
                build_customerorder_external_code(order_id=cart.id),
            )

        if not isinstance(current_order, dict):
            log.warning("Skipping MoySklad customerorder state sync because customerorder not found cart_id=%s", cart.id)
            return False

        current_state = current_order.get("state") if isinstance(current_order, dict) else None
        current_meta = current_state.get("meta") if isinstance(current_state, dict) else None
        current_state_href = _href(current_meta.get("href")) if isinstance(current_meta, dict) else None
        target_state_href = _href((state.get("meta") or {}).get("href"))
        if current_state_href and target_state_href and current_state_href == target_state_href:
            return False

        order_id = coerce_uuid(current_order.get("id"))
        if order_id is None:
            log.warning("Skipping MoySklad customerorder state sync because customerorder id invalid cart_id=%s", cart.id)
            return False

        await moysklad_client.update_customer_order_state(order_id, state)
        return True
    except Exception:
        log.exception("MoySklad customerorder state sync failed cart_id=%s state_name=%s", cart.id, normalized_state_name)
        return False


async def sync_moysklad_invoiceout_state(cart: Cart, *, state_name: str) -> bool:
    normalized_state_name = optional_str(state_name)
    if not MOY_SKLAD_ORDER_SYNC_ENABLED or not normalized_state_name:
        return False
    if not _is_intellectmoney_payment(cart):
        return False

    moysklad_client = get_moysklad_order_client()
    if not moysklad_client.is_configured():
        return False

    try:
        invoiceout = None
        invoiceout_id = coerce_uuid(getattr(cart, "moysklad_invoiceout_id", None))
        if invoiceout_id is not None:
            invoiceout = await moysklad_client.get_invoiceout(invoiceout_id)
        if invoiceout is None:
            invoiceout = await moysklad_client.find_invoiceout_by_external_code(_invoiceout_external_code(cart.id))
        if invoiceout is None:
            log.warning("Skipping MoySklad invoiceout state sync because invoiceout not found cart_id=%s state_name=%s", cart.id, normalized_state_name)
            return False

        invoiceout_id = coerce_uuid(invoiceout.get("id"))
        if invoiceout_id is None:
            log.warning("Skipping MoySklad invoiceout state sync because invoiceout id invalid cart_id=%s", cart.id)
            return False

        state = await moysklad_client.find_invoiceout_state_by_name(normalized_state_name)
        if state is None:
            log.warning("Skipping MoySklad invoiceout state sync because state not found state_name=%s cart_id=%s", normalized_state_name, cart.id)
            return False

        current_state = invoiceout.get("state") if isinstance(invoiceout, dict) else None
        current_meta = current_state.get("meta") if isinstance(current_state, dict) else None
        current_state_href = _href(current_meta.get("href")) if isinstance(current_meta, dict) else None
        target_state_href = _href((state.get("meta") or {}).get("href"))
        if current_state_href and target_state_href and current_state_href == target_state_href:
            return False

        await moysklad_client.update_invoiceout_state(invoiceout_id, state)
        return True
    except Exception:
        log.exception("MoySklad invoiceout state sync failed cart_id=%s state_name=%s", cart.id, normalized_state_name)
        return False


async def sync_cart_to_moysklad(session: AsyncSession, *, cart: Cart, user: User) -> dict[str, Any]:
    if not MOY_SKLAD_ORDER_SYNC_ENABLED:
        return {"enabled": False, "skipped_reason": "disabled"}

    moysklad_client = get_moysklad_order_client()
    if not moysklad_client.is_configured():
        return {"enabled": True, "skipped_reason": "client_not_configured"}

    cart = await get_cart_by_id(session, cart.id) or cart
    if not cart.items:
        return {"enabled": True, "skipped_reason": "empty_order"}

    organization_id = _configured_organization_id()
    if organization_id is None:
        return {"enabled": True, "skipped_reason": "organization_not_configured"}

    counterparty_external_code = build_counterparty_external_code(user_id=user.tg_id)
    counterparty_sync_id = build_sync_id(scope="counterparty", key=counterparty_external_code)
    existing_counterparty_id = coerce_uuid(getattr(user, "moysklad_counterparty_id", None))
    counterparty_id, _ = await moysklad_client.resolve_or_sync_counterparty(
        existing_counterparty_id=existing_counterparty_id,
        external_code=counterparty_external_code,
        sync_id=counterparty_sync_id,
        name=_full_name(user, cart),
        email=_counterparty_email(user, cart),
        phone=_counterparty_phone(user, cart),
        actual_address=_counterparty_address(cart),
    )

    if optional_str(getattr(user, "moysklad_counterparty_id", None)) != str(counterparty_id):
        updated_user = await update_user(session, user.tg_id, UserUpdate(moysklad_counterparty_id=str(counterparty_id)))
        if updated_user is not None:
            user = updated_user

    positions, missing_variant_ids = await _build_customerorder_positions(
        session,
        moysklad_client=moysklad_client,
        cart=cart,
    )
    if missing_variant_ids:
        unique_missing = sorted(set(missing_variant_ids))
        log.warning("Skipping MoySklad order sync because assortment refs are missing for features=%s cart_id=%s", unique_missing, cart.id)
        return {"enabled": True, "skipped_reason": "missing_assortment_refs"}

    if not positions:
        return {"enabled": True, "skipped_reason": "empty_positions"}

    customerorder_external_code = build_customerorder_external_code(order_id=cart.id)
    customerorder_sync_id = build_sync_id(scope="customerorder", key=customerorder_external_code)
    refs = await _resolve_customerorder_refs(moysklad_client, cart)
    if refs["store"] is None:
        return {"enabled": True, "skipped_reason": "store_not_configured"}
    if refs["state"] is None:
        return {"enabled": True, "skipped_reason": "state_not_configured"}
    if refs["sales_channel"] is None:
        return {"enabled": True, "skipped_reason": "sales_channel_not_configured"}

    attributes = await moysklad_client.build_customerorder_attributes(
        values=_moysklad_attr_values(cart),
        custom_refs=await _moysklad_custom_attr_refs(moysklad_client, cart),
    )
    existing_customerorder_id = coerce_uuid(getattr(cart, "moysklad_customerorder_id", None))
    customerorder_id, _ = await moysklad_client.resolve_or_sync_customerorder(
        existing_customerorder_id=existing_customerorder_id,
        external_code=customerorder_external_code,
        sync_id=customerorder_sync_id,
        organization_id=organization_id,
        counterparty_id=counterparty_id,
        positions=positions,
        moment=cart.created_at or datetime.now(timezone.utc),
        description=_build_order_description(cart),
        shipment_address=_shipment_address(cart),
        shipment_address_full=await _shipment_address_full(cart, moysklad_client=moysklad_client),
        attributes=attributes,
        store=refs["store"],
        state=refs["state"],
        sales_channel=refs["sales_channel"],
    )

    invoiceout_id = None
    if _is_intellectmoney_payment(cart):
        invoiceout_external_code = _invoiceout_external_code(cart.id)
        invoiceout_sync_id = build_sync_id(scope="invoiceout", key=invoiceout_external_code)
        invoiceout_id, _ = await moysklad_client.resolve_or_sync_invoiceout(
            existing_invoiceout_id=coerce_uuid(getattr(cart, "moysklad_invoiceout_id", None)),
            external_code=invoiceout_external_code,
            sync_id=invoiceout_sync_id,
            name=_invoiceout_name(cart),
            organization_id=organization_id,
            counterparty_id=counterparty_id,
            positions=positions,
            customerorder_id=customerorder_id,
            moment=cart.created_at or datetime.now(timezone.utc),
            description=_build_order_description(cart),
            store=refs["store"],
            sales_channel=refs["sales_channel"],
        )

    patch: dict[str, Any] = {}
    if optional_str(getattr(cart, "moysklad_customerorder_id", None)) != str(customerorder_id):
        patch["moysklad_customerorder_id"] = str(customerorder_id)
    if invoiceout_id is not None and optional_str(getattr(cart, "moysklad_invoiceout_id", None)) != str(invoiceout_id):
        patch["moysklad_invoiceout_id"] = str(invoiceout_id)
    if patch:
        cart = await update_cart(session, cart.id, CartUpdate(**patch))

    return {
        "enabled": True,
        "customerorder_id": str(customerorder_id),
        "invoiceout_id": str(invoiceout_id) if invoiceout_id is not None else None,
    }


async def sync_cart_to_moysklad_safe(session: AsyncSession, *, cart: Cart, user: User) -> dict[str, Any]:
    try:
        return await sync_cart_to_moysklad(session, cart=cart, user=user)
    except Exception:
        cart_id = cart.id
        user_id = user.tg_id
        requires_rollback = not session.is_active
        if requires_rollback:
            try:
                await session.rollback()
            except Exception:
                log.exception("MoySklad rollback after sync failure also failed cart_id=%s user_id=%s", cart_id, user_id)
        log.exception("MoySklad order sync failed cart_id=%s user_id=%s rollback=%s", cart_id, user_id, requires_rollback)
        return {"enabled": MOY_SKLAD_ORDER_SYNC_ENABLED, "skipped_reason": "sync_error"}
