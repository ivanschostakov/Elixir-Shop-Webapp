from __future__ import annotations

import logging
from typing import Any

import httpx

from config import GEOCODE_API_KEY, GEOCODE_API_URL

log = logging.getLogger(__name__)

COUNTRY_NAMES: dict[str, str] = {
    "RU": "Россия",
    "BY": "Беларусь",
    "KZ": "Казахстан",
    "AZ": "Азербайджан",
    "MD": "Молдова",
    "AM": "Армения",
    "UZ": "Узбекистан",
    "KG": "Кыргызстан",
    "GE": "Грузия",
    "MN": "Монголия",
    "CN": "Китай",
    "JP": "Япония",
    "RS": "Сербия",
    "IL": "Израиль",
    "AE": "ОАЭ",
    "IN": "Индия",
    "BD": "Бангладеш",
    "VN": "Вьетнам",
    "TH": "Таиланд",
    "ID": "Индонезия",
    "US": "США",
}


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _parse_address_component(address: dict[str, Any], kinds: set[str]) -> str | None:
    components = address.get("Components")
    if not isinstance(components, list):
        return None

    for component in components:
        if not isinstance(component, dict):
            continue
        if component.get("kind") not in kinds:
            continue
        name = component.get("name")
        if isinstance(name, str):
            normalized = name.strip()
            if normalized:
                return normalized
    return None


def _country_name_from_code(country_code: Any) -> str | None:
    normalized_country_code = optional_str(country_code)
    if not normalized_country_code:
        return None
    return COUNTRY_NAMES.get(normalized_country_code.upper())


def _geocode_query(address_payload: dict[str, Any]) -> str | None:
    latitude = address_payload.get("latitude")
    longitude = address_payload.get("longitude")
    if isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
        return f"{float(longitude):.6f},{float(latitude):.6f}"

    return (
        optional_str(address_payload.get("full_address"))
        or optional_str(address_payload.get("formatted"))
        or optional_str(address_payload.get("address"))
    )


async def geocode(address: str, *, lang: str = "ru_RU", results: int = 1) -> dict[str, Any] | None:
    if not optional_str(GEOCODE_API_URL) or not optional_str(GEOCODE_API_KEY):
        return None

    params: dict[str, Any] = {
        "apikey": GEOCODE_API_KEY,
        "geocode": address,
        "format": "json",
        "lang": lang,
        "results": results,
    }

    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(str(GEOCODE_API_URL), params=params)
        response.raise_for_status()
        raw_data = response.json()

    if not isinstance(raw_data, dict):
        return None

    collection = raw_data.get("response", {}).get("GeoObjectCollection", {})
    members = collection.get("featureMember", [])
    if not members:
        return None

    geo_object = members[0].get("GeoObject", {})
    meta = geo_object.get("metaDataProperty", {}).get("GeocoderMetaData", {})
    address_data = meta.get("Address", {}) or {}

    return {
        "country": _parse_address_component(address_data, {"country"}),
        "city": _parse_address_component(address_data, {"locality"})
        or _parse_address_component(address_data, {"province"})
        or _parse_address_component(address_data, {"area"})
        or _parse_address_component(address_data, {"district"}),
        "region": _parse_address_component(address_data, {"province"})
        or _parse_address_component(address_data, {"area"})
        or _parse_address_component(address_data, {"district"}),
        "street": _parse_address_component(address_data, {"street"}),
        "house": _parse_address_component(address_data, {"house"}),
        "country_code": optional_str(address_data.get("country_code")),
        "postal_code": optional_str(address_data.get("postal_code")),
    }


async def enrich_delivery_address_payload(address_payload: dict[str, Any]) -> None:
    if not isinstance(address_payload, dict):
        return

    country_name = optional_str(address_payload.get("country")) or _country_name_from_code(address_payload.get("country_code"))
    if country_name:
        address_payload["country"] = country_name

    if all(optional_str(address_payload.get(field_name)) for field_name in ("city", "postal_code", "street", "house", "region")):
        return

    query = _geocode_query(address_payload)
    if not query:
        return

    try:
        geocode_result = await geocode(address=query, lang="ru_RU", results=1)
    except Exception:
        log.warning("Failed to geocode delivery address payload query=%s", query, exc_info=True)
        return

    if not geocode_result:
        return

    if optional_str(address_payload.get("city")) is None and geocode_result.get("city"):
        address_payload["city"] = geocode_result["city"]
    if optional_str(address_payload.get("postal_code")) is None and geocode_result.get("postal_code"):
        address_payload["postal_code"] = geocode_result["postal_code"]
    if optional_str(address_payload.get("country_code")) is None and geocode_result.get("country_code"):
        address_payload["country_code"] = geocode_result["country_code"]
    if optional_str(address_payload.get("country")) is None and geocode_result.get("country"):
        address_payload["country"] = geocode_result["country"]
    if optional_str(address_payload.get("region")) is None and geocode_result.get("region"):
        address_payload["region"] = geocode_result["region"]
    if optional_str(address_payload.get("street")) is None and geocode_result.get("street"):
        address_payload["street"] = geocode_result["street"]
    if optional_str(address_payload.get("house")) is None and geocode_result.get("house"):
        address_payload["house"] = geocode_result["house"]
