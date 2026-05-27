import asyncio
import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

import httpx

from config import (
    MOY_SKLAD_BASE_URL,
    MOY_SKLAD_ORDER_POSITION_VAT,
    MOY_SKLAD_ORDER_POSITION_VAT_ENABLED,
    MOY_SKLAD_TIMEOUT_SECONDS,
    MOY_SKLAD_TOKEN,
    UFA_TZ,
)

logger = logging.getLogger(__name__)
MOY_SKLAD_API_BASE_URL = (str(MOY_SKLAD_BASE_URL or "").strip() or "https://api.moysklad.ru/api/remap/1.2").rstrip("/")

# Attribute IDs from the reference backend integration.
CUSTOMER_ORDER_ATTR_IDS: dict[str, str] = {
    "payment_method": "a47a457d-13e4-11f1-0a80-15c80013f10c",
    "delivery_method": "a47a4700-13e4-11f1-0a80-15c80013f10d",
    "promo_code": "a47a48ae-13e4-11f1-0a80-15c80013f10f",
    "delivery_cost": "a47a4973-13e4-11f1-0a80-15c80013f110",
    "responsible": "a47a4a52-13e4-11f1-0a80-15c80013f111",
    "counterparty_group": "a47a4b57-13e4-11f1-0a80-15c80013f112",
    "deal_link": "a0194a8b-13e7-11f1-0a80-11510020f72d",
    "created_by_widget": "a031e3b6-13e7-11f1-0a80-11510020f734",
    "client_waybill_link": "c559d1f5-537f-11f1-0a80-1b730010ddf0",
    "tracking_number": "c559d4c6-537f-11f1-0a80-1b730010ddf1",
    "site_order_link": "c559d71a-537f-11f1-0a80-1b730010ddf2",
    "delivery_tracking": "6dfc7b81-55c3-11f1-0a80-08cf000a4f89",
}
CUSTOMER_ORDER_CUSTOMENTITY_ATTR_KEYS = frozenset(("payment_method", "delivery_method", "responsible", "counterparty_group"))


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def normalize_email(value: str | None) -> str | None:
    normalized = optional_str(value)
    return normalized.lower() if normalized else None


def normalize_phone(value: str | None) -> str | None:
    normalized = optional_str(value)
    if not normalized:
        return None
    return "".join(ch for ch in normalized if ch.isdigit() or ch == "+")


def coerce_uuid(value: Any) -> UUID | None:
    normalized = optional_str(value)
    if not normalized:
        return None
    try:
        return UUID(normalized)
    except Exception:
        pass

    if "/" in normalized:
        tail = normalized.rstrip("/").rsplit("/", 1)[-1]
        try:
            return UUID(tail)
        except Exception:
            return None
    return None


def entity_ref(row: dict[str, Any]) -> dict[str, Any]:
    meta = row.get("meta") if isinstance(row, dict) else None
    if not isinstance(meta, dict):
        raise RuntimeError("MoySklad entity row is missing meta")
    return {"meta": meta}


def moysklad_money(amount: Decimal) -> int:
    quantized = Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int((quantized * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class MoySkladOrderClient:
    def __init__(
        self,
        token: str | None = MOY_SKLAD_TOKEN,
        base_url: str | None = MOY_SKLAD_BASE_URL,
        timeout: int = MOY_SKLAD_TIMEOUT_SECONDS,
    ) -> None:
        self._token = optional_str(token) or ""
        self._base_url = (optional_str(base_url) or MOY_SKLAD_API_BASE_URL).rstrip("/")
        self._timeout = max(int(timeout), 1)
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    def is_configured(self) -> bool:
        return bool(self._token and self._base_url)

    @property
    def base_url(self) -> str:
        return self._base_url.rstrip("/")

    def entity_href(self, entity_type: str, entity_id: UUID | str) -> str:
        return f"{self.base_url}/entity/{entity_type}/{entity_id}"

    @staticmethod
    def _meta_payload(*, href: str, entity_type: str) -> dict[str, Any]:
        return {"meta": {"href": href, "type": entity_type, "mediaType": "application/json"}}

    @staticmethod
    def _money_to_minor(value: Decimal) -> int:
        return moysklad_money(value)

    @staticmethod
    def _format_moment(moment: datetime) -> str:
        normalized = moment if moment.tzinfo is not None else moment.replace(tzinfo=UFA_TZ)
        return normalized.astimezone(UFA_TZ).strftime("%Y-%m-%d %H:%M:%S")

    async def client(self) -> httpx.AsyncClient:
        if not self.is_configured():
            raise RuntimeError("MoySklad integration is not configured")
        if self._client and not self._client.is_closed:
            return self._client

        async with self._lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    base_url=self._base_url,
                    timeout=httpx.Timeout(self._timeout),
                    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/json;charset=utf-8",
                        "Content-Type": "application/json;charset=utf-8",
                        "Accept-Encoding": "gzip",
                    },
                )
            return self._client

    async def get_page(self, path: str, *, limit: int = 100, offset: int = 0, **params: Any) -> dict[str, Any]:
        http_client = await self.client()
        response = await http_client.get(path, params={**params, "limit": limit, "offset": offset})
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    async def get_all(self, path: str, **params: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            data = await self.get_page(path, offset=offset, **params)
            batch = data.get("rows", [])
            if not isinstance(batch, list):
                break
            rows.extend(row for row in batch if isinstance(row, dict))
            if len(batch) < 100:
                break
            offset += 100
        return rows

    async def _get_entity_by_id(self, entity_type: str, entity_id: UUID) -> dict[str, Any] | None:
        http_client = await self.client()
        try:
            response = await http_client.get(f"/entity/{entity_type}/{entity_id}")
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

        data = response.json()
        return data if isinstance(data, dict) else None

    async def _find_entity_by_external_code(self, entity_type: str, external_code: str) -> dict[str, Any] | None:
        rows: list[dict[str, Any]] = []
        try:
            filtered = await self.get_page(f"/entity/{entity_type}", limit=100, filter=f"externalCode={external_code}")
            candidate_rows = filtered.get("rows")
            if isinstance(candidate_rows, list):
                rows.extend(row for row in candidate_rows if isinstance(row, dict))
        except httpx.HTTPStatusError as exc:
            logger.debug("MoySklad %s filter lookup failed: %s", entity_type, exc)

        if not rows:
            try:
                searched = await self.get_page(f"/entity/{entity_type}", limit=100, search=external_code)
                candidate_rows = searched.get("rows")
                if isinstance(candidate_rows, list):
                    rows.extend(row for row in candidate_rows if isinstance(row, dict))
            except httpx.HTTPStatusError as exc:
                logger.debug("MoySklad %s search lookup failed: %s", entity_type, exc)

        for row in rows:
            if optional_str(row.get("externalCode")) == external_code:
                return row
        return None

    async def _find_counterparty(self, search: str) -> dict[str, Any] | None:
        normalized = optional_str(search)
        if not normalized:
            return None
        data = await self.get_page("/entity/counterparty", limit=100, search=normalized)
        rows = data.get("rows")
        if not isinstance(rows, list):
            return None
        for row in rows:
            if isinstance(row, dict) and optional_str(row.get("externalCode")) == normalized:
                return row
        for row in rows:
            if not isinstance(row, dict):
                continue
            if optional_str(row.get("name")) == normalized:
                return row
        return next((row for row in rows if isinstance(row, dict)), None)

    async def _create_entity(self, entity_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        http_client = await self.client()
        response = await http_client.post(f"/entity/{entity_type}", json=payload)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"MoySklad returned invalid {entity_type} create response")
        return data

    async def _update_entity(self, entity_type: str, entity_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
        http_client = await self.client()
        response = await http_client.put(f"/entity/{entity_type}/{entity_id}", json=payload)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"MoySklad returned invalid {entity_type} update response")
        return data

    async def get_stores(self) -> list[dict[str, Any]]:
        return await self.get_all("/entity/store")

    async def get_countries(self) -> list[dict[str, Any]]:
        return await self.get_all("/entity/country")

    async def get_saleschannels(self) -> list[dict[str, Any]]:
        return await self.get_all("/entity/saleschannel")

    async def get_customerorder_metadata(self) -> dict[str, Any]:
        http_client = await self.client()
        response = await http_client.get("/entity/customerorder/metadata")
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    async def get_customerorder_states(self) -> list[dict[str, Any]]:
        states = (await self.get_customerorder_metadata()).get("states")
        if not isinstance(states, list):
            return []
        return [row for row in states if isinstance(row, dict)]

    async def get_invoiceout_metadata(self) -> dict[str, Any]:
        http_client = await self.client()
        response = await http_client.get("/entity/invoiceout/metadata")
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    async def get_invoiceout_states(self) -> list[dict[str, Any]]:
        states = (await self.get_invoiceout_metadata()).get("states")
        if not isinstance(states, list):
            return []
        return [row for row in states if isinstance(row, dict)]

    @staticmethod
    def _find_named_row(rows: list[dict[str, Any]], *names: str) -> dict[str, Any] | None:
        normalized_names = [name.casefold() for name in (optional_str(raw) for raw in names) if name]
        if not normalized_names:
            return None
        matched: dict[str, dict[str, Any]] = {}
        for row in rows:
            row_name = optional_str(row.get("name"))
            if not row_name:
                continue
            key = row_name.casefold()
            if key in normalized_names and key not in matched:
                matched[key] = row
        for key in normalized_names:
            row = matched.get(key)
            if row is not None:
                return row
        return None

    async def find_store_by_name(self, *names: str) -> dict[str, Any] | None:
        return self._find_named_row(await self.get_stores(), *names)

    async def find_customerorder_state_by_name(self, *names: str) -> dict[str, Any] | None:
        return self._find_named_row(await self.get_customerorder_states(), *names)

    async def find_invoiceout_state_by_name(self, *names: str) -> dict[str, Any] | None:
        return self._find_named_row(await self.get_invoiceout_states(), *names)

    async def get_customerorder_attribute_metadata(self, *, limit: int = 1000) -> list[dict[str, Any]]:
        data = await self.get_page("/entity/customerorder/metadata/attributes", limit=limit)
        rows = data.get("rows")
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)]

    async def _existing_customerorder_attr_keys(self) -> set[str]:
        rows = await self.get_customerorder_attribute_metadata(limit=1000)
        by_id = {optional_str(row.get("id")) for row in rows if isinstance(row, dict)}
        keys: set[str] = set()
        for key, attr_id in CUSTOMER_ORDER_ATTR_IDS.items():
            if attr_id in by_id:
                keys.add(key)
        return keys

    async def get_customerorder_customentity_values(self, attr_key: str, *, limit: int = 1000) -> list[dict[str, Any]]:
        attr_id = CUSTOMER_ORDER_ATTR_IDS.get(attr_key)
        if not attr_id:
            return []
        attr_row = next((row for row in await self.get_customerorder_attribute_metadata(limit=limit) if optional_str(row.get("id")) == attr_id), None)
        if not isinstance(attr_row, dict):
            return []
        custom_entity_meta = attr_row.get("customEntityMeta")
        custom_entity_href = optional_str(custom_entity_meta.get("href")) if isinstance(custom_entity_meta, dict) else None
        if not custom_entity_href:
            return []
        custom_entity_id = custom_entity_href.rstrip("/").rsplit("/", 1)[-1]
        return await self.get_all(f"/entity/customentity/{custom_entity_id}")

    async def find_customerorder_customentity_value(self, attr_key: str, *names: str) -> dict[str, Any] | None:
        return self._find_named_row(await self.get_customerorder_customentity_values(attr_key), *names)

    async def find_country_by_name_or_code(self, *values: str) -> dict[str, Any] | None:
        normalized_names = [name.casefold() for name in (optional_str(raw) for raw in values) if name]
        normalized_codes = [code.upper() for code in (optional_str(raw) for raw in values) if code]
        if not normalized_names and not normalized_codes:
            return None

        countries = await self.get_countries()
        for row in countries:
            code = optional_str(row.get("code"))
            if code and code.upper() in normalized_codes:
                return row

        for row in countries:
            row_name = optional_str(row.get("name"))
            if row_name and row_name.casefold() in normalized_names:
                return row

        return None

    async def find_region_by_name(self, name: str, *, country_id: UUID | None = None) -> dict[str, Any] | None:
        normalized_name = optional_str(name)
        if not normalized_name:
            return None

        data = await self.get_page("/entity/region", limit=200, search=normalized_name)
        rows = data.get("rows")
        if not isinstance(rows, list):
            return None

        normalized_key = normalized_name.casefold()
        candidate_rows = [row for row in rows if isinstance(row, dict)]
        if country_id is not None:
            filtered: list[dict[str, Any]] = []
            for row in candidate_rows:
                country_row = row.get("country")
                country_meta = country_row.get("meta") if isinstance(country_row, dict) else None
                country_href = optional_str(country_meta.get("href")) if isinstance(country_meta, dict) else None
                row_country_id = coerce_uuid(country_href.rsplit("/", 1)[-1]) if country_href else None
                if row_country_id == country_id:
                    filtered.append(row)
            if filtered:
                candidate_rows = filtered

        exact_match = next(
            (
                row
                for row in candidate_rows
                if optional_str(row.get("name")) and optional_str(row.get("name")).casefold() == normalized_key
            ),
            None,
        )
        if exact_match is not None:
            return exact_match
        return candidate_rows[0] if candidate_rows else None

    @staticmethod
    def _attr_meta(attr_key: str) -> dict[str, Any]:
        attr_id = CUSTOMER_ORDER_ATTR_IDS.get(attr_key)
        if not attr_id:
            raise KeyError(f"Unknown customer order attribute key: {attr_key}")
        return {
            "meta": {
                "href": f"{MOY_SKLAD_API_BASE_URL}/entity/customerorder/metadata/attributes/{attr_id}",
                "type": "attributemetadata",
                "mediaType": "application/json",
            }
        }

    @classmethod
    def _order_attr(cls, attr_key: str, value: Any) -> dict[str, Any]:
        payload = cls._attr_meta(attr_key)
        payload["value"] = value
        return payload

    @classmethod
    def _custom_order_attr(cls, attr_key: str, value_href: str) -> dict[str, Any]:
        href = optional_str(value_href)
        if not href:
            raise ValueError(f"Customer order customentity attribute {attr_key} expects a non-empty href")
        return cls._order_attr(
            attr_key,
            {
                "meta": {
                    "href": href,
                    "type": "customentity",
                    "mediaType": "application/json",
                }
            },
        )

    async def build_customerorder_attributes(self, *, values: dict[str, Any] | None = None, custom_refs: dict[str, str] | None = None) -> list[dict[str, Any]]:
        attrs: list[dict[str, Any]] = []
        existing_keys = await self._existing_customerorder_attr_keys()

        for attr_key, href in (custom_refs or {}).items():
            if attr_key not in CUSTOMER_ORDER_CUSTOMENTITY_ATTR_KEYS:
                continue
            if attr_key not in existing_keys:
                continue
            if not optional_str(href):
                continue
            attrs.append(self._custom_order_attr(attr_key, href))

        for attr_key, value in (values or {}).items():
            if value is None or attr_key in CUSTOMER_ORDER_CUSTOMENTITY_ATTR_KEYS:
                continue
            if attr_key not in existing_keys:
                continue
            attrs.append(self._order_attr(attr_key, value))
        return attrs

    def build_customerorder_payload(
        self,
        *,
        organization: dict[str, Any],
        agent: dict[str, Any],
        positions: list[dict[str, Any]],
        description: str | None = None,
        shipment_address: str | None = None,
        shipment_address_full: dict[str, Any] | None = None,
        attributes: list[dict[str, Any]] | None = None,
        store: dict[str, Any] | None = None,
        state: dict[str, Any] | None = None,
        sales_channel: dict[str, Any] | None = None,
        owner: dict[str, Any] | None = None,
        external_code: str | None = None,
        sync_id: UUID | None = None,
        moment: datetime | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"organization": entity_ref(organization), "agent": entity_ref(agent), "positions": positions}
        if store is not None:
            payload["store"] = entity_ref(store)
        if state is not None:
            payload["state"] = entity_ref(state)
        if sales_channel is not None:
            payload["salesChannel"] = entity_ref(sales_channel)
        if owner is not None:
            payload["owner"] = entity_ref(owner)
        normalized_description = optional_str(description)
        if normalized_description:
            payload["description"] = normalized_description
        normalized_shipment_address = optional_str(shipment_address)
        if normalized_shipment_address:
            payload["shipmentAddress"] = normalized_shipment_address
        if isinstance(shipment_address_full, dict) and shipment_address_full:
            payload["shipmentAddressFull"] = shipment_address_full
        if attributes:
            payload["attributes"] = attributes
        normalized_external_code = optional_str(external_code)
        if normalized_external_code:
            payload["externalCode"] = normalized_external_code
        if sync_id is not None:
            payload["syncId"] = str(sync_id)
        if moment is not None:
            payload["moment"] = self._format_moment(moment)
        return payload

    def build_invoiceout_payload(
        self,
        *,
        name: str,
        organization: dict[str, Any],
        agent: dict[str, Any],
        positions: list[dict[str, Any]],
        customer_order: dict[str, Any] | None = None,
        description: str | None = None,
        store: dict[str, Any] | None = None,
        state: dict[str, Any] | None = None,
        sales_channel: dict[str, Any] | None = None,
        owner: dict[str, Any] | None = None,
        external_code: str | None = None,
        sync_id: UUID | None = None,
        moment: datetime | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": name, "organization": entity_ref(organization), "agent": entity_ref(agent), "positions": positions}
        if customer_order is not None:
            payload["customerOrder"] = entity_ref(customer_order)
        if store is not None:
            payload["store"] = entity_ref(store)
        if state is not None:
            payload["state"] = entity_ref(state)
        if sales_channel is not None:
            payload["salesChannel"] = entity_ref(sales_channel)
        if owner is not None:
            payload["owner"] = entity_ref(owner)
        normalized_description = optional_str(description)
        if normalized_description:
            payload["description"] = normalized_description
        normalized_external_code = optional_str(external_code)
        if normalized_external_code:
            payload["externalCode"] = normalized_external_code
        if sync_id is not None:
            payload["syncId"] = str(sync_id)
        if moment is not None:
            payload["moment"] = self._format_moment(moment)
        return payload

    def build_customerorder_position(
        self,
        *,
        assortment_entity_type: str,
        assortment_id: UUID,
        quantity: int,
        unit_price: Decimal,
        discount: Decimal | None = None,
    ) -> dict[str, Any]:
        position = {
            "assortment": self._meta_payload(
                href=self.entity_href(assortment_entity_type, assortment_id),
                entity_type=assortment_entity_type,
            ),
            "quantity": int(quantity),
            "price": self._money_to_minor(unit_price),
        }
        if MOY_SKLAD_ORDER_POSITION_VAT_ENABLED:
            try:
                vat_raw = Decimal(str(MOY_SKLAD_ORDER_POSITION_VAT if MOY_SKLAD_ORDER_POSITION_VAT is not None else 3))
            except Exception:
                vat_raw = Decimal("3")
            normalized_vat = max(Decimal("0.00"), min(Decimal("100.00"), vat_raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)))
            position["vatEnabled"] = True
            position["vat"] = int(normalized_vat) if normalized_vat == normalized_vat.to_integral() else float(normalized_vat)
        if discount is not None:
            normalized_discount = max(Decimal("0.00"), min(Decimal("100.00"), Decimal(discount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)))
            if normalized_discount > Decimal("0.00"):
                position["discount"] = float(normalized_discount)
        return position

    async def get_or_create_counterparty(
        self,
        *,
        existing_counterparty_id: UUID | None,
        external_code: str,
        sync_id: UUID,
        name: str,
        email: str | None,
        phone: str | None,
        actual_address: str | None,
    ) -> dict[str, Any]:
        normalized_external_code = optional_str(external_code)
        if not normalized_external_code:
            raise ValueError("Counterparty external_code is required")

        counterparty_data = await self._get_entity_by_id("counterparty", existing_counterparty_id) if existing_counterparty_id is not None else None
        if counterparty_data is None:
            counterparty_data = await self._find_entity_by_external_code("counterparty", normalized_external_code)
        if counterparty_data is None:
            counterparty_data = await self._find_counterparty(normalized_external_code)

        payload: dict[str, Any] = {"name": name, "externalCode": normalized_external_code, "companyType": "individual"}
        normalized_email = normalize_email(email)
        normalized_phone = normalize_phone(phone)
        normalized_address = optional_str(actual_address)
        if normalized_email:
            payload["email"] = normalized_email
        if normalized_phone:
            payload["phone"] = normalized_phone
        if normalized_address:
            payload["actualAddress"] = normalized_address

        if counterparty_data is None:
            payload["syncId"] = str(sync_id)
            return await self._create_entity("counterparty", payload)

        counterparty_id = coerce_uuid(counterparty_data.get("id"))
        if counterparty_id is None:
            raise RuntimeError("MoySklad counterparty response is missing a valid id")
        await self._update_entity("counterparty", counterparty_id, payload)
        return counterparty_data

    async def resolve_or_sync_counterparty(
        self,
        *,
        existing_counterparty_id: UUID | None,
        external_code: str,
        sync_id: UUID,
        name: str,
        email: str | None,
        phone: str | None,
        actual_address: str | None,
    ) -> tuple[UUID, bool]:
        normalized_external_code = optional_str(external_code) or ""
        existing = await self._get_entity_by_id("counterparty", existing_counterparty_id) if existing_counterparty_id is not None else None
        if existing is None:
            existing = await self._find_entity_by_external_code("counterparty", normalized_external_code)
        if existing is None:
            existing = await self._find_counterparty(normalized_external_code)
        created = existing is None
        counterparty_data = await self.get_or_create_counterparty(
            existing_counterparty_id=existing_counterparty_id,
            external_code=normalized_external_code,
            sync_id=sync_id,
            name=name,
            email=email,
            phone=phone,
            actual_address=actual_address,
        )
        counterparty_id = coerce_uuid(counterparty_data.get("id"))
        if counterparty_id is None:
            raise RuntimeError("MoySklad counterparty response is missing a valid id")
        return counterparty_id, created

    async def create_customer_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        http_client = await self.client()
        try:
            response = await http_client.post("/entity/customerorder", json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            body = exc.response.text if exc.response is not None else ""
            logger.error("MoySklad customerorder create failed status=%s body=%s external_code=%s", status_code, body[:4000], payload.get("externalCode"))
            raise
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("MoySklad returned invalid customerorder create response")
        return data

    async def create_invoiceout(self, payload: dict[str, Any]) -> dict[str, Any]:
        http_client = await self.client()
        try:
            response = await http_client.post("/entity/invoiceout", json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            body = exc.response.text if exc.response is not None else ""
            logger.error("MoySklad invoiceout create failed status=%s body=%s external_code=%s", status_code, body[:4000], payload.get("externalCode"))
            raise
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("MoySklad returned invalid invoiceout create response")
        return data

    async def get_customer_order(self, order_id: UUID | str, expand: bool = False) -> dict[str, Any] | None:
        http_client = await self.client()
        params = {"expand": "positions.assortment"} if expand else None
        try:
            response = await http_client.get(f"/entity/customerorder/{order_id}", params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        data = response.json()
        return data if isinstance(data, dict) else None

    async def get_invoiceout(self, invoiceout_id: UUID | str, expand: bool = False) -> dict[str, Any] | None:
        http_client = await self.client()
        params = {"expand": "positions.assortment"} if expand else None
        try:
            response = await http_client.get(f"/entity/invoiceout/{invoiceout_id}", params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        data = response.json()
        return data if isinstance(data, dict) else None

    async def update_customer_order_state(self, order_id: UUID | str, state: dict[str, Any]) -> dict[str, Any]:
        normalized_order_id = coerce_uuid(order_id)
        if normalized_order_id is None:
            raise ValueError("Invalid MoySklad customerorder id")
        return await self._update_entity("customerorder", normalized_order_id, {"state": entity_ref(state)})

    async def update_invoiceout_state(self, invoiceout_id: UUID | str, state: dict[str, Any]) -> dict[str, Any]:
        normalized_invoiceout_id = coerce_uuid(invoiceout_id)
        if normalized_invoiceout_id is None:
            raise ValueError("Invalid MoySklad invoiceout id")
        return await self._update_entity("invoiceout", normalized_invoiceout_id, {"state": entity_ref(state)})

    async def resolve_or_sync_customerorder(
        self,
        *,
        existing_customerorder_id: UUID | None,
        external_code: str,
        sync_id: UUID,
        organization_id: UUID,
        counterparty_id: UUID,
        positions: list[dict[str, Any]],
        moment: datetime,
        description: str | None,
        shipment_address: str | None = None,
        shipment_address_full: dict[str, Any] | None = None,
        attributes: list[dict[str, Any]] | None = None,
        store: dict[str, Any] | None = None,
        state: dict[str, Any] | None = None,
        sales_channel: dict[str, Any] | None = None,
        owner: dict[str, Any] | None = None,
    ) -> tuple[UUID, bool]:
        customerorder_data = await self.get_customer_order(existing_customerorder_id) if existing_customerorder_id is not None else None
        if customerorder_data is None:
            customerorder_data = await self._find_entity_by_external_code("customerorder", external_code)
        if customerorder_data is not None:
            customerorder_id = coerce_uuid(customerorder_data.get("id"))
            if customerorder_id is None:
                raise RuntimeError("MoySklad customerorder response is missing a valid id")
            return customerorder_id, False

        organization_row = {"meta": {"href": self.entity_href("organization", organization_id), "type": "organization", "mediaType": "application/json"}}
        agent_row = {"meta": {"href": self.entity_href("counterparty", counterparty_id), "type": "counterparty", "mediaType": "application/json"}}
        payload = self.build_customerorder_payload(
            organization=organization_row,
            agent=agent_row,
            positions=positions,
            moment=moment,
            description=description,
            external_code=external_code,
            sync_id=sync_id,
            shipment_address=shipment_address,
            shipment_address_full=shipment_address_full,
            attributes=attributes,
            store=store,
            state=state,
            sales_channel=sales_channel,
            owner=owner,
        )
        customerorder_data = await self.create_customer_order(payload)

        customerorder_id = coerce_uuid(customerorder_data.get("id"))
        if customerorder_id is None:
            raise RuntimeError("MoySklad customerorder response is missing a valid id")

        return customerorder_id, True

    async def find_invoiceout_by_external_code(self, external_code: str) -> dict[str, Any] | None:
        normalized_external_code = optional_str(external_code)
        if not normalized_external_code:
            return None
        return await self._find_entity_by_external_code("invoiceout", normalized_external_code)

    async def resolve_or_sync_invoiceout(
        self,
        *,
        existing_invoiceout_id: UUID | None = None,
        external_code: str,
        sync_id: UUID,
        name: str,
        organization_id: UUID,
        counterparty_id: UUID,
        positions: list[dict[str, Any]],
        customerorder_id: UUID | None = None,
        moment: datetime | None = None,
        description: str | None = None,
        store: dict[str, Any] | None = None,
        state: dict[str, Any] | None = None,
        sales_channel: dict[str, Any] | None = None,
        owner: dict[str, Any] | None = None,
    ) -> tuple[UUID, bool]:
        invoiceout_data = await self.get_invoiceout(existing_invoiceout_id) if existing_invoiceout_id is not None else None
        if invoiceout_data is None:
            invoiceout_data = await self.find_invoiceout_by_external_code(external_code)
        if invoiceout_data is not None:
            invoiceout_id = coerce_uuid(invoiceout_data.get("id"))
            if invoiceout_id is None:
                raise RuntimeError("MoySklad invoiceout response is missing a valid id")
            return invoiceout_id, False

        organization_row = {"meta": {"href": self.entity_href("organization", organization_id), "type": "organization", "mediaType": "application/json"}}
        agent_row = {"meta": {"href": self.entity_href("counterparty", counterparty_id), "type": "counterparty", "mediaType": "application/json"}}
        customer_order_row = {"meta": {"href": self.entity_href("customerorder", customerorder_id), "type": "customerorder", "mediaType": "application/json"}} if customerorder_id is not None else None
        payload = self.build_invoiceout_payload(
            name=name,
            organization=organization_row,
            agent=agent_row,
            positions=positions,
            customer_order=customer_order_row,
            moment=moment,
            description=description,
            external_code=external_code,
            sync_id=sync_id,
            store=store,
            state=state,
            sales_channel=sales_channel,
            owner=owner,
        )
        invoiceout_data = await self.create_invoiceout(payload)
        invoiceout_id = coerce_uuid(invoiceout_data.get("id"))
        if invoiceout_id is None:
            raise RuntimeError("MoySklad invoiceout response is missing a valid id")
        return invoiceout_id, True

    async def aclose(self) -> None:
        async with self._lock:
            if self._client and not self._client.is_closed:
                await self._client.aclose()
            self._client = None


moysklad_order_client = MoySkladOrderClient()


def get_moysklad_order_client() -> MoySkladOrderClient:
    return moysklad_order_client
