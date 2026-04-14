from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import httpx
from fastapi import HTTPException

from config import YANDEX_DELIVERY_BASE_URL, YANDEX_DELIVERY_TOKEN, YANDEX_DELIVERY_WAREHOUSE_ID
from src.helpers import normalize_address_for_cf
from src.services.cdek import client as cdek_client

log = logging.getLogger(__name__)


def resolve_delivery_sum(selected_delivery_service: str, selected_delivery: dict[str, Any]) -> Decimal:
    service = (selected_delivery_service or "").strip().lower()
    if service == "yandex":
        raw = selected_delivery.get("delivery_sum") or selected_delivery.get("price") or 0
        return Decimal(str(raw or 0))
    if service == "cdek":
        raw = ((selected_delivery.get("tariff") or {}).get("delivery_sum")) or 0
        return Decimal(str(raw or 0))
    return Decimal("0")


async def _create_yandex_delivery(snapshot: dict[str, Any], order_number: str) -> tuple[str, str | None]:
    selected_delivery = snapshot.get("selected_delivery") or {}
    address = selected_delivery.get("address") or {}
    commentary_text = snapshot.get("commentary") or "Не указан"
    contact_info = snapshot.get("contact_info") or {}
    promocode = snapshot.get("promocode") or "Не указан"
    total = Decimal(str((snapshot.get("checkout_data") or {}).get("total") or 0))
    delivery_sum = resolve_delivery_sum("yandex", selected_delivery)
    address_str = normalize_address_for_cf(address)

    def _platform_urls(path: str) -> list[str]:
        primary = f"{YANDEX_DELIVERY_BASE_URL}{path}"
        fallback = f"https://b2b-authproxy.taxi.yandex.net{path}"
        if primary == fallback:
            return [primary]
        return [primary, fallback]

    request_create_urls = _platform_urls("/api/b2b/platform/request/create")
    offers_create_urls = _platform_urls("/api/b2b/platform/offers/create")
    offers_confirm_urls = _platform_urls("/api/b2b/platform/offers/confirm")
    headers = {
        "Authorization": f"Bearer {YANDEX_DELIVERY_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Accept-Language": "ru",
    }

    dx_cm, dy_cm, dz_cm = 25, 15, 10
    weight_g = 100
    total_kop = int(total * 100)
    pvz_platform_id = address.get("code")

    if pvz_platform_id:
        destination_node = {
            "type": "platform_station",
            "platform_station": {"platform_id": str(pvz_platform_id)},
        }
        last_mile_policy = "self_pickup"
    else:
        destination_node = {
            "type": "custom_location",
            "custom_location": {"details": {"full_address": address_str}},
        }
        last_mile_policy = "time_interval"

    request_body = {
        "info": {
            "operator_request_id": str(order_number),
            "comment": f"{commentary_text} | promo: {promocode}",
        },
        "source": {
            "platform_station": {"platform_id": str(YANDEX_DELIVERY_WAREHOUSE_ID)},
        },
        "destination": destination_node,
        "items": [
            {
                "count": 1,
                "name": f"Order #{order_number}",
                "article": f"ORDER-{order_number}",
                "billing_details": {
                    "unit_price": total_kop,
                    "assessed_unit_price": total_kop,
                    "nds": -1,
                },
                "physical_dims": {"dx": dx_cm, "dy": dy_cm, "dz": dz_cm},
                "place_barcode": "box-1",
            }
        ],
        "places": [
            {
                "barcode": "box-1",
                "description": f"Box for order #{order_number}",
                "physical_dims": {
                    "dx": dx_cm,
                    "dy": dy_cm,
                    "dz": dz_cm,
                    "weight_gross": weight_g,
                },
            }
        ],
        "billing_info": {"payment_method": "already_paid"},
        "recipient_info": {
            "first_name": (contact_info.get("name") or "Получатель"),
            "last_name": (contact_info.get("surname") or ""),
            "phone": contact_info.get("phone"),
            "email": contact_info.get("email"),
        },
        "last_mile_policy": last_mile_policy,
        "particular_items_refuse": False,
        "forbid_unboxing": False,
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        request_resp = None
        for idx, url in enumerate(request_create_urls):
            request_resp = await client.post(url, params={"send_unix": True}, json=request_body, headers=headers)
            if request_resp.status_code < 400:
                break
            should_retry = idx + 1 < len(request_create_urls) and request_resp.status_code == 404
            if should_retry:
                log.warning("Yandex request/create 404 at %s, retrying fallback host", str(request_resp.request.url))
                continue
            break

        if request_resp and request_resp.status_code < 400:
            yandex_data = request_resp.json()
        elif request_resp and request_resp.status_code == 404:
            offers_resp = None
            for idx, url in enumerate(offers_create_urls):
                offers_resp = await client.post(url, params={"send_unix": True}, json=request_body, headers=headers)
                if offers_resp.status_code < 400:
                    break
                should_retry = idx + 1 < len(offers_create_urls) and offers_resp.status_code == 404
                if should_retry:
                    log.warning("Yandex offers/create 404 at %s, retrying fallback host", str(offers_resp.request.url))
                    continue
                break

            if not offers_resp or offers_resp.status_code >= 400:
                body = offers_resp.text if offers_resp else ""
                raise HTTPException(status_code=502, detail=f"Yandex Delivery offers/create error: {body}")

            offers_data = offers_resp.json()
            offers = offers_data.get("offers") or []
            if not offers:
                raise HTTPException(status_code=502, detail="Yandex Delivery has no offers for this order")

            def _offer_min_unix(offer: dict[str, Any]) -> int:
                try:
                    return int((offer.get("offer_details") or {}).get("delivery_interval", {}).get("min"))
                except Exception:
                    return 10 ** 18

            selected_offer = min(offers, key=_offer_min_unix)
            offer_id = selected_offer.get("offer_id")
            if not offer_id:
                raise HTTPException(status_code=502, detail="Yandex Delivery offer_id missing")

            confirm_resp = None
            for idx, url in enumerate(offers_confirm_urls):
                confirm_resp = await client.post(url, json={"offer_id": str(offer_id)}, headers=headers)
                if confirm_resp.status_code < 400:
                    break
                should_retry = idx + 1 < len(offers_confirm_urls) and confirm_resp.status_code == 404
                if should_retry:
                    log.warning("Yandex offers/confirm 404 at %s, retrying fallback host", str(confirm_resp.request.url))
                    continue
                break

            if not confirm_resp or confirm_resp.status_code >= 400:
                body = confirm_resp.text if confirm_resp else ""
                raise HTTPException(status_code=502, detail=f"Yandex Delivery offers/confirm error: {body}")
            yandex_data = confirm_resp.json()
        else:
            body = request_resp.text if request_resp else ""
            raise HTTPException(status_code=502, detail=f"Yandex Delivery request/create error: {body}")

    return str(delivery_sum), yandex_data.get("request_id")


async def _create_cdek_delivery(snapshot: dict[str, Any], order_number: str) -> tuple[str, str | None]:
    selected_delivery = snapshot.get("selected_delivery") or {}
    delivery_sum = resolve_delivery_sum("cdek", selected_delivery)
    response = await cdek_client.create_order_from_payload(snapshot, order_number, delivery_sum=float(delivery_sum))
    provider_ref = None
    if isinstance(response, dict):
        entity = response.get("entity") or {}
        requests = response.get("requests") or []
        provider_ref = entity.get("uuid") or entity.get("cdek_number")
        if not provider_ref and requests and isinstance(requests[0], dict):
            provider_ref = requests[0].get("request_uuid")
    if not provider_ref:
        provider_ref = f"cdek:{order_number}"
    return str(delivery_sum), str(provider_ref)


async def create_delivery_from_snapshot(snapshot: dict[str, Any], order_number: str) -> tuple[str, str | None]:
    selected_delivery_service = (snapshot.get("selected_delivery_service") or "").strip().lower()
    if selected_delivery_service == "yandex":
        return await _create_yandex_delivery(snapshot, order_number)
    if selected_delivery_service == "cdek":
        return await _create_cdek_delivery(snapshot, order_number)
    raise HTTPException(status_code=400, detail="Unsupported delivery service")
