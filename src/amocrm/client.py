import asyncio
import logging
import os
import re
import secrets
import aiosmtplib
import httpx

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from email.message import EmailMessage
from typing import Literal, Union, Any
from datetime import datetime, timedelta, UTC, timezone
from urllib.parse import urlparse, parse_qs
from playwright.async_api import async_playwright
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from config import AMOCRM_CLIENT_ID, AMOCRM_CLIENT_SECRET, AMOCRM_ACCESS_TOKEN, AMOCRM_LOGIN_EMAIL, AMOCRM_LOGIN_PASSWORD, AMOCRM_REFRESH_TOKEN, AMOCRM_REDIRECT_URI, AMOCRM_BASE_DOMAIN, WORKING_DIR, SMTP_USER, SMTP_PASSWORD, UFA_TZ
from src.database import get_session
from src.database.crud import get_carts_by_date
from src.database.models import Feature
from src.helpers import format_order_for_amocrm, normalize_address_for_cf
from src.tg_methods import normalize_phone

PriceT = Union[int, None, Literal["old", "low", "not_found"]]

class AmoCRMRecoverableError(RuntimeError):
    """Temporary AmoCRM auth/connectivity issue safe to retry later."""

class AsyncAmoCRM:
    def __init__(self,base_domain: str, client_id: str, client_secret: str, redirect_uri: str, access_token: str | None = None, refresh_token: str | None = None):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.base_domain = base_domain
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = datetime.now(UTC) + timedelta(days=1)
        self._refresh_lock = asyncio.Lock()

        self.PIPELINE_ID = 9280278
        self.STATUS_IDS = {"main": 81419122, "check_paid": 75784946, "packaged": 75784942, "package_sent": 76566302, "package_delivered": 76566306, "won": 142}
        self.STATUS_WORDS = {81419122: "Создан", 75784938: "Счет отправлен", 75784946: "Оплачен", 75784942: "Укомплектован", 76566302: "Отправлен", 76566306: "Доставлен", 74461446: "Ожидание ответа", 82756582: "Ожидание ответа", 82657618: "Отменен", 142: "Завершен", 143: "Возврат/отказ"}
        self.CF = {"cdek_tracking_url": 752437, "delivery_cdek": 752921, "consultant_call": 753605, "delivery_yandex": 753603, "tg_nick": 753183, "payment": 753401, "cdek_number": 751951, "city": 752927, "address": 752435, "promo_code": 752923, "delivery_sum": 752929, "ai": 753181}

    @property
    def PAID_STATUS_IDS(self):
        x = list(self.STATUS_IDS.values())
        x.remove(self.STATUS_IDS["main"])
        return x

    async def __request_token(self, grant_type: str, code: str | None = None):
        url = f"https://{self.base_domain}/oauth2/access_token"
        payload = {"client_id": self.client_id, "client_secret": self.client_secret, "redirect_uri": self.redirect_uri, "grant_type": grant_type}
        if grant_type == "authorization_code": payload["code"] = code
        elif grant_type == "refresh_token": payload["refresh_token"] = self.refresh_token

        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(url, json=payload)
            if res.status_code != 200: raise RuntimeError(f"Token request failed: {res.status_code} {res.text}")
            data = res.json()

        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        self.expires_at = datetime.now(UTC) + timedelta(seconds=data["expires_in"])
        self._save_tokens_to_env(self.access_token, self.refresh_token)
        self.logger.info("✅ Tokens successfully updated")
        return data

    async def _get_new_auth_code(self) -> str:
        auth_url = f"https://www.amocrm.ru/oauth?client_id={self.client_id}&redirect_uri={self.redirect_uri}&response_type=code"
        self.logger.warning("🔁 Launching Playwright to get new AUTH_CODE...")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            page = await browser.new_page()
            await page.goto(auth_url)

            try:
                await page.wait_for_selector('input[name="username"]', timeout=5000)
                await page.fill('input[name="username"]', AMOCRM_LOGIN_EMAIL)
                await page.fill('input[name="password"]', AMOCRM_LOGIN_PASSWORD)
                await page.click('button[type="submit"]')
                print("🔐 Logged into AmoCRM")
            except Exception as e: self.logger.info("Already logged in (no login form shown). " + str(e))

            try: await page.wait_for_selector("select.js-accounts-list", timeout=40000)
            except Exception as e: print(await page.content(), e)

            await page.select_option("select.js-accounts-list", value="19843447")
            await page.click("button.js-accept")
            print("✅ Selected Slimpeptide and clicked Разрешить")

            try: await page.wait_for_url("https://elixirpeptides.devsivanschostakov.org/webhooks/amocrm*", timeout=30000)
            except Exception as e: self.logger.info(f"Already logged in (no login form shown)., {page.url, str(e)}")

            url = page.url
            await browser.close()

        code = parse_qs(urlparse(url).query).get("code", [None])[0]
        if not code: raise RuntimeError(f"Failed to extract AUTH_CODE from redirect URL. {url}")
        self.logger.info("✅ Got new AUTH_CODE")
        return code

    def _save_tokens_to_env(self, access_token: str, refresh_token: str):
        path = WORKING_DIR / ".env"
        self.logger.info(f"Saving tokens to {path}")
        lines = []
        if os.path.exists(path):
            with open(path, "r") as f: lines = f.readlines()

        new_lines = []
        found_a, found_r = False, False
        for line in lines:
            if line.startswith("AMOCRM_ACCESS_TOKEN"):
                new_lines.append(f'AMOCRM_ACCESS_TOKEN="{access_token}"\n')
                found_a = True

            elif line.startswith("AMOCRM_REFRESH_TOKEN"):
                new_lines.append(f'AMOCRM_REFRESH_TOKEN="{refresh_token}"\n')
                found_r = True

            else: new_lines.append(line)

        if not found_a: new_lines.append(f'AMOCRM_ACCESS_TOKEN="{access_token}"\n')
        if not found_r: new_lines.append(f'AMOCRM_REFRESH_TOKEN="{refresh_token}"\n')

        with open(path, "w") as f: f.writelines(new_lines)
        self.logger.info("💾 Saved new tokens to .env")

    async def _authorize(self, code: str | None = None):
        if not code: code = await self._get_new_auth_code()
        return await self.__request_token("authorization_code", code)

    async def _refresh(self):
        try:
            return await self.__request_token("refresh_token")
        except Exception as e:
            allow_interactive = os.getenv("AMOCRM_ALLOW_INTERACTIVE_AUTH", "").strip().lower() in {"1", "true", "yes", "on"}
            self.logger.error(f"❌ Refresh failed: {e}")
            if not allow_interactive:
                raise AmoCRMRecoverableError("Refresh token exchange failed and interactive re-auth is disabled") from e
            self.logger.warning("retrying with new AUTH_CODE...")
            try:
                return await self._authorize()
            except Exception as auth_exc:
                raise AmoCRMRecoverableError("Interactive re-auth failed") from auth_exc

    async def _ensure_token_valid(self):
        if self.access_token and datetime.now(UTC) < self.expires_at:
            return
        async with self._refresh_lock:
            if self.access_token and datetime.now(UTC) < self.expires_at:
                return
            await self._refresh()

    async def _request(self, method: str, endpoint: str, **kwargs):
        await self._ensure_token_valid()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.access_token}"
        url = f"https://{self.base_domain}{endpoint}"

        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.request(method, url, headers=headers, **kwargs)
            if res.status_code in [401, 403]:
                self.logger.warning("Access token invalid, refreshing...")
                async with self._refresh_lock:
                    # Another coroutine may refresh first; skip duplicate refresh if token already valid.
                    if not self.access_token or datetime.now(UTC) >= self.expires_at:
                        await self._refresh()
                headers["Authorization"] = f"Bearer {self.access_token}"
                res = await client.request(method, url, headers=headers, **kwargs)

            if res.status_code == 429:
                raise AmoCRMRecoverableError(f"AmoCRM rate limit on {method} {endpoint}")

            res.raise_for_status()
            if res.text.strip(): return res.json()
            return {}

    async def _get(self, endpoint: str, **kwargs): return await self._request("GET", endpoint, **kwargs)
    async def _post(self, endpoint: str, **kwargs): return await self._request("POST", endpoint, **kwargs)
    async def _patch(self, endpoint: str, **kwargs): return await self._request("PATCH", endpoint, **kwargs)
    async def _delete(self, endpoint: str, **kwargs): return await self._request("DELETE", endpoint, **kwargs)

    @staticmethod
    def _contact_custom_fields(phone: str | None, email: str | None) -> list[dict[str, object]]:
        fields: list[dict[str, object]] = []
        if phone:
            fields.append({"field_code": "PHONE", "values": [{"value": phone, "enum_code": "WORK"}]})
        if email:
            fields.append({"field_code": "EMAIL", "values": [{"value": email, "enum_code": "WORK"}]})
        return fields

    async def get_contact(self, contact_id: int) -> dict | None:
        try:
            return await self._get(f"/api/v4/contacts/{contact_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

    async def search_contacts(self, query: str, *, limit: int = 50) -> list[dict]:
        if not query:
            return []
        data = await self._get("/api/v4/contacts", params={"query": query, "limit": limit})
        return (data.get("_embedded") or {}).get("contacts") or []

    async def create_contact(self, *, name: str, phone: str | None, email: str | None) -> dict:
        payload = [{
            "name": name,
            "custom_fields_values": self._contact_custom_fields(phone, email),
        }]
        contacts_res = await self._post("/api/v4/contacts", json=payload)
        return contacts_res["_embedded"]["contacts"][0]

    async def update_contact(self, contact_id: int, *, name: str | None = None, phone: str | None = None, email: str | None = None) -> dict:
        payload: dict[str, object] = {"id": contact_id}
        if name:
            payload["name"] = name
        custom_fields = self._contact_custom_fields(phone, email)
        if custom_fields:
            payload["custom_fields_values"] = custom_fields
        result = await self._patch("/api/v4/contacts", json=[payload])
        contacts = (result.get("_embedded") or {}).get("contacts") or []
        return contacts[0] if contacts else {"id": contact_id}

    async def _refresh_contact_after_update(self, contact_id: int, fallback: dict | None = None) -> dict:
        try:
            refreshed = await self.get_contact(contact_id)
            if refreshed:
                return refreshed
        except Exception as exc:
            self.logger.warning("Contact refresh failed after update | contact_id=%s | error=%s", contact_id, exc)
        return fallback or {"id": contact_id}

    async def find_or_create_contact(self, *, lead_name: str, phone: str | None, email: str | None, contact_id: int | None = None) -> dict:
        normalized_phone = normalize_phone(phone) if phone else None
        normalized_email = email.strip().lower() if email else None

        if contact_id:
            contact = await self.get_contact(contact_id)
            if contact:
                await self.update_contact(contact_id, name=lead_name, phone=normalized_phone, email=normalized_email)
                return await self._refresh_contact_after_update(contact_id, fallback=contact)

        candidates: dict[int, dict] = {}
        queries: list[str] = []
        if normalized_phone:
            queries.append(normalized_phone)
        if phone and phone not in queries:
            queries.append(phone)
        if normalized_email:
            queries.append(normalized_email)

        for query in queries:
            for candidate in await self.search_contacts(query):
                cid = candidate.get("id")
                if cid:
                    candidates[int(cid)] = candidate

        for cid, candidate in candidates.items():
            contact = candidate if candidate.get("custom_fields_values") else await self.get_contact(cid)
            if not contact:
                continue
            candidate_phone = self._extract_phone_from_contact_obj(contact)
            candidate_email = self._extract_email_from_contact_obj(contact)
            if normalized_phone and candidate_phone == normalized_phone:
                await self.update_contact(cid, name=lead_name, phone=normalized_phone, email=normalized_email)
                return await self._refresh_contact_after_update(cid, fallback=contact)
            if normalized_email and candidate_email and candidate_email.lower() == normalized_email:
                await self.update_contact(cid, name=lead_name, phone=normalized_phone, email=normalized_email)
                return await self._refresh_contact_after_update(cid, fallback=contact)

        return await self.create_contact(name=lead_name, phone=normalized_phone, email=normalized_email)

    async def find_lead_by_order_number(self, order_number: str | int) -> dict | None:
        code_str = str(order_number).strip()
        needle = f"№{code_str} "
        rx = re.compile(rf"№{re.escape(code_str)}\s")
        page = 1
        limit = 50
        max_pages = 20

        while page <= max_pages:
            data = await self._get("/api/v4/leads", params={"query": needle, "limit": limit, "page": page})
            leads = (data.get("_embedded") or {}).get("leads") or []
            if not leads:
                return None

            for lead in leads:
                name = lead.get("name") or ""
                if not rx.search(name):
                    continue
                pipeline_id = lead.get("pipeline_id")
                if pipeline_id is not None and pipeline_id != self.PIPELINE_ID:
                    continue
                return lead

            page += 1

        return None

    async def create_lead(self, name: str, status_id: int, price: int | None = None, custom_fields: dict[int, object] | None = None, responsible_user_id: int | None = None):
        body_lead: dict = {"name": name, "pipeline_id": self.PIPELINE_ID, "status_id": status_id}
        if price is not None: body_lead["price"] = price
        if responsible_user_id is not None: body_lead["responsible_user_id"] = responsible_user_id
        if custom_fields:
            cf_list: list[dict] = [{"field_id": field_id, "values": [{"value": str(value)}]} for field_id, value in custom_fields.items() if value is not None]
            if cf_list: body_lead["custom_fields_values"] = cf_list

        payload = [body_lead]
        data = await self._post("/api/v4/leads", json=payload)
        return data["_embedded"]["leads"][0]

    async def add_lead_note(self, lead_id: int, text: str):
        payload = [{"entity_id": lead_id, "note_type": "common", "params": {"text": text}}]
        return await self._post("/api/v4/leads/notes", json=payload)

    async def update_lead_status(self, lead_id: int, status_id: int):
        payload = [{"id": lead_id, "pipeline_id": self.PIPELINE_ID, "status_id": status_id}]
        data = await self._patch("/api/v4/leads", json=payload)
        leads = (data.get("_embedded") or {}).get("leads") or []
        return leads[0] if leads else {"id": lead_id, "status_id": status_id}

    async def create_lead_with_contact_and_note(self, lead_name: str, price: int, address_str: str, phone: str, email: str | None, order_number: str, delivery_service: str, note_text: str, payment_method: str, tg_nick: str | None = '', status_id: int = None, delivery_sum: float | int | Decimal | None = None, promo_code: str | None = None, contact_id: int | None = None):
        lead_custom_fields: dict[int, object] = {}
        if address_str: lead_custom_fields[self.CF["address"]] = address_str
        if tg_nick: lead_custom_fields[self.CF["tg_nick"]] = tg_nick
        if delivery_sum: lead_custom_fields[self.CF["delivery_sum"]] = float(delivery_sum)

        if delivery_service.upper() == "CDEK":
            lead_custom_fields[self.CF["delivery_cdek"]] = "СДЭК"
            lead_custom_fields[self.CF["cdek_number"]] = order_number
            lead_custom_fields[self.CF["cdek_tracking_url"]] = f'https://www.cdek.ru/ru/tracking/?order_id={order_number}'

        elif delivery_service.upper() == "YANDEX": lead_custom_fields[self.CF["delivery_yandex"]] = "Яндекс"

        lead_custom_fields[self.CF["payment"]] = payment_method
        if promo_code: lead_custom_fields[self.CF["promo_code"]] = promo_code

        lead = await self.create_lead(name=f"Заказ №{order_number} с Приложения ТГ", price=int(price), custom_fields=lead_custom_fields, status_id=status_id or self.STATUS_IDS["main"])
        lead_id = lead["id"]

        if contact_id:
            link_payload = [{"to_entity_id": contact_id, "to_entity_type": "contacts"}]
            await self._post(f"/api/v4/leads/{lead_id}/link", json=link_payload)
        await self.add_lead_note(lead_id, note_text)

        return lead

    async def get_main_pipeline_statuses(self) -> dict[str, int]:
        data = await self._get(f"/api/v4/leads/pipelines/{self.PIPELINE_ID}/statuses")
        embedded = data.get("_embedded", {})
        statuses = embedded.get("statuses", [])
        result: dict[str, int] = {}
        for st in statuses:
            name = st.get("name")
            sid = st.get("id")
            if name and sid is not None: result[name] = sid

        return result

    async def get_valid_deal_price_and_email_verification_code_for_ai(self, code: str | int) -> tuple[PriceT, str | None, str | None]:
        code_str = str(code).strip()
        needle = f"№{code_str} "
        rx = re.compile(rf"№{re.escape(code_str)}\s")
        cutoff_ts = int((datetime.now(timezone.utc) - timedelta(days=62)).timestamp())
        page = 1
        limit = 50
        max_pages = 20
        logger = self.logger
        logger.info("deal lookup start | code=%s | needle=%r | cutoff_ts=%s | limit=%s | max_pages=%s", code_str, needle, cutoff_ts, limit, max_pages)
        while page <= max_pages:
            logger.info("deal lookup page start | code=%s | page=%s", code_str, page)
            data = await self._get("/api/v4/leads", params={"query": needle, "limit": limit, "page": page, "with": "contacts"})
            leads = (data.get("_embedded") or {}).get("leads") or []
            logger.info("deal lookup page loaded | code=%s | page=%s | leads_count=%s", code_str, page, len(leads))
            if not leads:
                logger.info("deal lookup no leads on page | code=%s | page=%s -> return not_found", code_str, page)
                return "not_found", None, None
            for idx, lead in enumerate(leads, start=1):
                lead_id = lead.get("id")
                name = lead.get("name") or ""
                status_id = lead.get("status_id")
                created_at = lead.get("created_at")
                raw_price = lead.get("price", None)
                created_ok = isinstance(created_at, (int, float))
                is_fresh = created_ok and created_at >= cutoff_ts
                status_ok = status_id in self.PAID_STATUS_IDS
                regex_ok = bool(rx.search(name))
                logger.info("deal lookup lead inspect | code=%s | page=%s | idx=%s | lead_id=%s | name=%r | status_id=%r | created_at=%r | raw_price=%r | created_ok=%s | is_fresh=%s | status_ok=%s | regex_ok=%s", code_str, page, idx, lead_id, name, status_id, created_at, raw_price, created_ok, is_fresh, status_ok, regex_ok)
                if not created_ok:
                    logger.info("deal lookup skip lead | code=%s | lead_id=%s | reason=created_at_not_numeric", code_str, lead_id)
                    continue
                if created_at < cutoff_ts:
                    logger.info("deal lookup skip lead | code=%s | lead_id=%s | reason=too_old | created_at=%s | cutoff_ts=%s", code_str, lead_id, created_at, cutoff_ts)
                    continue
                if not status_ok:
                    logger.info("deal lookup skip lead | code=%s | lead_id=%s | reason=status_not_paid | status_id=%r | paid_status_ids=%r", code_str, lead_id, status_id, self.PAID_STATUS_IDS)
                    continue
                if not regex_ok:
                    logger.info("deal lookup skip lead | code=%s | lead_id=%s | reason=regex_no_match | name=%r | pattern=%r", code_str, lead_id, name, rx.pattern)
                    continue
                logger.info("deal lookup matched lead | code=%s | lead_id=%s | name=%r", code_str, lead_id, name)
                if not raw_price:
                    logger.info("deal lookup matched lead but no price | code=%s | lead_id=%s -> return old", code_str, lead_id)
                    return "old", None, None
                try:
                    price = int(raw_price)
                except Exception:
                    logger.exception("deal lookup bad price conversion | code=%s | lead_id=%s | raw_price=%r", code_str, lead_id, raw_price)
                    return "old", None, None
                logger.info("deal lookup price parsed | code=%s | lead_id=%s | price=%s", code_str, lead_id, price)
                if price <= 5000:
                    logger.info("deal lookup matched lead but low price | code=%s | lead_id=%s | price=%s -> return low", code_str, lead_id, price)
                    return "low", None, None
                logger.info("deal lookup extracting email | code=%s | lead_id=%s", code_str, lead_id)
                email = await self._extract_lead_email(lead)
                logger.info("deal lookup email extracted | code=%s | lead_id=%s | email=%r", code_str, lead_id, email)
                if not email:
                    logger.info("deal lookup no email | code=%s | lead_id=%s | price=%s -> return price,None,None", code_str, lead_id, price)
                    return price, None, None
                verification_code = self._generate_6_digit_code()
                logger.info("deal lookup verification code generated | code=%s | lead_id=%s | email=%s", code_str, lead_id, email)
                await self._send_verification_code_email(to_email=email, code=verification_code, deal_code=code_str)
                logger.info("deal lookup success | code=%s | lead_id=%s | price=%s | email=%s", code_str, lead_id, price, email)
                return price, email, verification_code
            logger.info("deal lookup page done no match | code=%s | page=%s -> next page", code_str, page)
            page += 1
        logger.info("deal lookup exhausted pages | code=%s | max_pages=%s -> return not_found", code_str, max_pages)
        return "not_found", None, None

    @staticmethod
    def _generate_6_digit_code() -> str: return f"{secrets.randbelow(1_000_000):06d}"

    async def _send_verification_code_email(self, to_email: str, code: str, deal_code: str) -> None:
        from_email = SMTP_USER
        from_name = getattr(self, "GMAIL_FROM_NAME", "ElixirPeptide")

        msg = EmailMessage()
        msg["From"] = f"{from_name} <{from_email}>"
        msg["To"] = to_email
        msg["Subject"] = "Код подтверждения"
        msg.set_content(f"""Здравствуйте!
        
Ваш код подтверждения: {code}    
Заказ: №{deal_code}
Если Вы не запрашивали код — свяжитесь с поддержкой.""")
        await aiosmtplib.send(msg, hostname="smtp.gmail.com", port=587, start_tls=True, username=SMTP_USER, password=SMTP_PASSWORD, timeout=20)

    async def _extract_lead_email(self, lead: dict) -> str | None:
        embedded = lead.get("_embedded") or {}
        contacts = embedded.get("contacts") or lead.get("contacts") or []
        if not isinstance(contacts, list) or not contacts: return None
        ordered = sorted(contacts, key=lambda c: 0 if c.get("is_main") else 1)
        for c in ordered:
            if isinstance(c, dict) and c.get("custom_fields_values"):
                email = self._extract_email_from_contact_obj(c)
                if email: return email

            cid = None
            if isinstance(c, dict): cid = c.get("id") or c.get("contact_id")
            if cid:
                contact = await self._get(f"/api/v4/contacts/{cid}")
                email = self._extract_email_from_contact_obj(contact)
                if email: return email

        return None

    async def get_lead_status(self, deal_code: str | int) -> tuple[str, bool]:
        code_str = str(deal_code).strip()
        needle = f"№{code_str} "
        rx = re.compile(rf"№{re.escape(code_str)}\s")
        page = 1
        limit = 50
        max_pages = 20

        while page <= max_pages:
            data = await self._get("/api/v4/leads", params={"query": needle, "limit": limit, "page": page})
            leads = (data.get("_embedded") or {}).get("leads") or []
            if not leads: return "Не найден", False
            for lead in leads:
                name = lead.get("name") or ""
                if not rx.search(name): continue

                pipeline_id = lead.get("pipeline_id")
                if pipeline_id is not None and pipeline_id != self.PIPELINE_ID: continue

                status_id = lead.get("status_id")
                is_complete = bool(status_id in self.PAID_STATUS_IDS)
                status_name = self.STATUS_WORDS.get(status_id)
                if status_name is None:
                    self.logger.warning("Unknown amoCRM status_id=%s (lead/deal_code=%s)", status_id, deal_code)
                    status_name = f"UNKNOWN({status_id})"

                return status_name, is_complete

            page += 1

        return "Не найден", False

    @staticmethod
    def split_contact_name(name: str | None) -> tuple[str, str]:
        raw = (name or "").strip()
        if not raw:
            return "", ""
        parts = raw.split(maxsplit=1)
        if len(parts) == 1:
            return parts[0], ""
        return parts[0], parts[1]

    @staticmethod
    def contact_payload(contact: dict | None) -> dict[str, object]:
        if not contact:
            return {"contact_id": None, "name": "", "surname": "", "email": "", "phone": ""}
        first_name, surname = AsyncAmoCRM.split_contact_name(contact.get("name"))
        return {
            "contact_id": contact.get("id"),
            "name": first_name,
            "surname": surname,
            "email": AsyncAmoCRM._extract_email_from_contact_obj(contact) or "",
            "phone": AsyncAmoCRM._extract_phone_from_contact_obj(contact) or "",
        }

    @staticmethod
    def _extract_email_from_contact_obj(contact: dict) -> str | None:
        cfs = contact.get("custom_fields_values") or []
        if not isinstance(cfs, list): return None
        for cf in cfs:
            if not isinstance(cf, dict): continue

            code = (cf.get("field_code") or "").upper()
            name = (cf.get("field_name") or "").lower()
            if code == "EMAIL" or "email" in name or "почта" in name:
                values = cf.get("values") or []
                if not isinstance(values, list): continue
                for v in values:
                    val = (v or {}).get("value")
                    if isinstance(val, str) and "@" in val: return val.strip()

        return None

    @staticmethod
    def _extract_phone_from_contact_obj(contact: dict) -> str | None:
        cfs = contact.get("custom_fields_values") or []
        if not isinstance(cfs, list):
            return None
        for cf in cfs:
            if not isinstance(cf, dict):
                continue
            code = (cf.get("field_code") or "").upper()
            name = (cf.get("field_name") or "").lower()
            if code == "PHONE" or "тел" in name or "phone" in name:
                values = cf.get("values") or []
                if not isinstance(values, list):
                    continue
                for v in values:
                    val = (v or {}).get("value")
                    if isinstance(val, str):
                        normalized = normalize_phone(val)
                        if normalized:
                            return normalized
        return None

    @staticmethod
    def _clean_text(value: object) -> str:
        raw = str(value or "").strip()
        return "" if raw.lower() in {"none", "null"} else raw

    @staticmethod
    def _order_payment_label(payment_method: str | None) -> str:
        method = (payment_method or "").strip().lower()
        if method == "sbp":
            return "IntellectMoney"
        if method == "later":
            return "Оплата позже"
        return payment_method or "Не указан"

    @classmethod
    def _full_name_from_contact_info(cls, contact_info: dict[str, Any]) -> str:
        name = cls._clean_text(contact_info.get("name"))
        surname = cls._clean_text(contact_info.get("surname"))
        return " ".join(part for part in [name, surname] if part).strip()

    async def _build_order_snapshot_for_amocrm(self, db, order) -> dict[str, Any]:
        snapshot = deepcopy(order.checkout_snapshot if isinstance(order.checkout_snapshot, dict) else {})

        checkout = snapshot.get("checkout_data")
        if not isinstance(checkout, dict):
            checkout = {}

        raw_items = checkout.get("items")
        items = raw_items if isinstance(raw_items, list) else []
        feature_ids = [str((item or {}).get("featureId") or "").strip() for item in items if isinstance(item, dict) and (item or {}).get("featureId")]
        feature_map: dict[str, Feature] = {}
        if feature_ids:
            result = await db.execute(
                select(Feature).options(selectinload(Feature.product)).where(Feature.onec_id.in_(feature_ids))
            )
            features = result.scalars().all()
            feature_map = {feature.onec_id: feature for feature in features}

        enriched_items: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_data = dict(item)
            fid = str(item_data.get("featureId") or "").strip()
            feature = feature_map.get(fid)
            product_name = self._clean_text(item_data.get("product_name"))
            feature_name = self._clean_text(item_data.get("feature_name"))
            if feature is not None:
                product_name = product_name or self._clean_text(getattr(feature.product, "name", None))
                feature_name = feature_name or self._clean_text(feature.name)

            raw_name = self._clean_text(item_data.get("name"))
            resolved_name = raw_name or product_name or feature_name or "Товар"
            qty = int(item_data.get("qty") or 1)
            price = item_data.get("price")
            if price in (None, "", "None", "null") and feature is not None:
                price = float(feature.price)
            subtotal = item_data.get("subtotal")
            if subtotal in (None, "", "None", "null") and price not in (None, "", "None", "null"):
                subtotal = float(Decimal(str(price)) * qty)

            item_data.update(
                {
                    "name": resolved_name,
                    "product_name": product_name or None,
                    "feature_name": feature_name or None,
                    "qty": qty,
                    "price": price,
                    "subtotal": subtotal,
                }
            )
            enriched_items.append(item_data)

        checkout["items"] = enriched_items
        checkout["total"] = float(order.sum or 0)
        snapshot["checkout_data"] = checkout

        selected_delivery = snapshot.get("selected_delivery")
        if not isinstance(selected_delivery, dict):
            selected_delivery = {}
        if isinstance(order.selected_delivery_payload, dict):
            merged_delivery = deepcopy(order.selected_delivery_payload)
            merged_delivery.update(selected_delivery)
            selected_delivery = merged_delivery
        selected_delivery["delivery_sum"] = float(order.delivery_sum or 0)
        snapshot["selected_delivery"] = selected_delivery

        selected_delivery_service = self._clean_text(snapshot.get("selected_delivery_service")) or self._clean_text(order.selected_delivery_service)
        if not selected_delivery_service and order.delivery_string:
            selected_delivery_service = self._clean_text(str(order.delivery_string).split(":", 1)[0])
        snapshot["selected_delivery_service"] = selected_delivery_service

        snapshot["commentary"] = self._clean_text(snapshot.get("commentary")) or self._clean_text(order.commentary) or "Не указан"
        snapshot["promocode"] = self._clean_text(snapshot.get("promocode")) or self._clean_text(order.promo_code) or "Не указан"
        snapshot["payment_method"] = self._clean_text(snapshot.get("payment_method")) or self._clean_text(order.payment_method)
        snapshot["tg_nick"] = self._clean_text(snapshot.get("tg_nick"))
        snapshot["source"] = self._clean_text(snapshot.get("source")) or "telegram"
        snapshot["order_date"] = order.created_at.isoformat() if order.created_at else None

        contact_info = snapshot.get("contact_info")
        if not isinstance(contact_info, dict):
            contact_info = {}
        contact_info["name"] = self._clean_text(contact_info.get("name"))
        contact_info["surname"] = self._clean_text(contact_info.get("surname"))
        contact_info["phone"] = self._clean_text(contact_info.get("phone")) or self._clean_text(order.phone)
        contact_info["email"] = self._clean_text(contact_info.get("email")) or self._clean_text(order.email)
        snapshot["contact_info"] = contact_info

        return snapshot

    async def ensure_order_has_lead(self, db, order, *, dry_run: bool = False) -> tuple[str, int | None]:
        lead = await self.find_lead_by_order_number(order.id)
        if lead is not None:
            lead_id = int(lead["id"])
            if order.amocrm_lead_id != lead_id:
                order.amocrm_lead_id = lead_id
            return "exists", lead_id

        snapshot = await self._build_order_snapshot_for_amocrm(db, order)
        contact_info = snapshot.get("contact_info") or {}
        selected_delivery = snapshot.get("selected_delivery") or {}
        selected_delivery_service = str(snapshot.get("selected_delivery_service") or order.selected_delivery_service or "").strip()
        address_str = normalize_address_for_cf((selected_delivery or {}).get("address")) or self._clean_text(order.delivery_string) or "Не указан"
        commentary_text = self._clean_text(snapshot.get("commentary")) or "Не указан"
        promo_code = self._clean_text(snapshot.get("promocode")) or "Не указан"
        lead_name = self._full_name_from_contact_info(contact_info) or f"Заказ #{order.id}"
        phone = self._clean_text(contact_info.get("phone")) or self._clean_text(order.phone)
        email = self._clean_text(contact_info.get("email")) or self._clean_text(order.email) or None
        payment_method = self._order_payment_label(self._clean_text(order.payment_method))
        tariff = (
            (selected_delivery or {}).get("deliveryMode")
            or ((selected_delivery or {}).get("tariff") or {}).get("tariff_name")
            or ((selected_delivery or {}).get("tariff") or {}).get("tariff_code")
        )
        note_text = format_order_for_amocrm(
            order.id,
            snapshot,
            selected_delivery_service,
            tariff,
            commentary_text,
            promo_code,
            order.delivery_sum or 0,
        )

        if dry_run:
            self.logger.info("dry-run missing lead | order_id=%s | lead_name=%s", order.id, lead_name)
            return "missing", None

        user = getattr(order, "user", None)
        user_contact_id = getattr(user, "contact_id", None)
        contact = await self.find_or_create_contact(
            lead_name=lead_name,
            phone=phone,
            email=email,
            contact_id=user_contact_id,
        )
        contact_id = contact.get("id") if isinstance(contact, dict) else None
        if user is not None and contact_id and contact_id != user_contact_id:
            user.contact_id = contact_id

        total_with_delivery = (Decimal(str(order.sum or 0)) + Decimal(str(order.delivery_sum or 0))).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
        lead = await self.create_lead_with_contact_and_note(
            lead_name=lead_name,
            price=int(total_with_delivery),
            address_str=address_str,
            phone=phone,
            email=email,
            order_number=str(order.id),
            delivery_service=selected_delivery_service,
            note_text=note_text,
            payment_method=payment_method,
            tg_nick=self._clean_text(snapshot.get("tg_nick")) or None,
            status_id=self.STATUS_IDS["main"],
            delivery_sum=order.delivery_sum,
            promo_code=None if promo_code == "Не указан" else promo_code,
            contact_id=contact_id,
        )
        lead_id = int(lead["id"])
        order.amocrm_lead_id = lead_id
        return "created", lead_id

amocrm = AsyncAmoCRM(base_domain=AMOCRM_BASE_DOMAIN, client_id=AMOCRM_CLIENT_ID, client_secret=AMOCRM_CLIENT_SECRET, redirect_uri=AMOCRM_REDIRECT_URI, access_token=AMOCRM_ACCESS_TOKEN, refresh_token=AMOCRM_REFRESH_TOKEN)
async def fix(days_back: int = 7, dry_run: bool = False):
    async with get_session() as session:
        created = 0
        existing = 0
        failed = 0
        for i in range(days_back):
            target_day = datetime.now(UFA_TZ) - timedelta(days=i)
            orders = await get_carts_by_date(session, target_day)
            amocrm.logger.info("amoCRM backfill day=%s orders=%s", target_day.date().isoformat(), len(orders))
            for order in orders:
                try:
                    result, lead_id = await amocrm.ensure_order_has_lead(session, order, dry_run=dry_run)
                    if result == "created":
                        created += 1
                        amocrm.logger.info("amoCRM backfill created lead | order_id=%s | lead_id=%s", order.id, lead_id)
                    elif result == "exists":
                        existing += 1
                        amocrm.logger.info("amoCRM backfill lead exists | order_id=%s | lead_id=%s", order.id, lead_id)
                    else:
                        amocrm.logger.info("amoCRM backfill dry-run missing lead | order_id=%s", order.id)
                    if not dry_run:
                        await session.commit()
                except Exception:
                    failed += 1
                    await session.rollback()
                    amocrm.logger.exception("amoCRM backfill failed | order_id=%s", order.id)
        amocrm.logger.info(
            "amoCRM backfill finished | days_back=%s | dry_run=%s | created=%s | existing=%s | failed=%s",
            days_back,
            dry_run,
            created,
            existing,
            failed,
        )
