from __future__ import annotations

import hashlib
import json
import logging
from decimal import Decimal
from typing import Any

import httpx

from config import (
    INTELLECTMONEY_API_BASE,
    INTELLECTMONEY_BEARER_TOKEN,
    INTELLECTMONEY_SECRET_KEY,
    INTELLECTMONEY_SHOP_ID,
    INTELLECTMONEY_SIGN_SECRET_KEY,
)


class IntellectMoneyError(RuntimeError):
    pass


class AsyncIntellectMoney:
    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.api_base = INTELLECTMONEY_API_BASE.rstrip("/")
        self.bearer_token = INTELLECTMONEY_BEARER_TOKEN or ""
        self.secret_key = INTELLECTMONEY_SECRET_KEY or ""
        self.sign_secret_key = INTELLECTMONEY_SIGN_SECRET_KEY or ""
        self.shop_id = INTELLECTMONEY_SHOP_ID

    @staticmethod
    def _as_str(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, Decimal):
            return f"{value:.2f}"
        return str(value)

    @classmethod
    def _sha256_signature(cls, *parts: Any) -> str:
        raw = "::".join(cls._as_str(part) for part in parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def _md5_hash(cls, *parts: Any) -> str:
        raw = "::".join(cls._as_str(part) for part in parts)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def amount(value: Decimal | float | int | str) -> str:
        return f"{Decimal(str(value)):.2f}"

    def _ensure_config(self) -> None:
        missing = []
        if not self.shop_id:
            missing.append("INTELLECTMONEY_SHOP_ID")
        if not self.bearer_token:
            missing.append("INTELLECTMONEY_BEARER_TOKEN")
        if not self.secret_key:
            missing.append("INTELLECTMONEY_SECRET_KEY")
        if not self.sign_secret_key:
            missing.append("INTELLECTMONEY_SIGN_SECRET_KEY")
        if missing:
            raise IntellectMoneyError(f"Missing IntellectMoney config: {', '.join(missing)}")

    def _headers(self, *sign_parts: Any) -> dict[str, str]:
        self._ensure_config()
        return {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Bearer {self.bearer_token}",
            "Sign": self._sha256_signature(*sign_parts, self.sign_secret_key),
        }

    def _hash_secrets(self) -> list[str]:
        secrets: list[str] = []
        for candidate in (self.secret_key, self.sign_secret_key):
            candidate = str(candidate or "").strip()
            if candidate and candidate not in secrets:
                secrets.append(candidate)
        return secrets

    async def _post_form(self, path: str, form_data: dict[str, Any], *sign_parts: Any) -> dict[str, Any]:
        headers = self._headers(*sign_parts)
        print("IntellectMoney request", {"path": path, "form_data": form_data})
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{self.api_base}{path}", data=form_data, headers=headers)
        response.raise_for_status()
        data = response.json()
        operation = data.get("OperationState") or {}
        if int(operation.get("Code") or 0) != 0:
            raise IntellectMoneyError(str(operation.get("Desc") or "IntellectMoney operation failed"))
        result = data.get("Result") or {}
        if isinstance(result, dict):
            state = result.get("State") or {}
            state_code_raw = state.get("Code")
            if state_code_raw not in (None, ""):
                try:
                    state_code = int(state_code_raw)
                except (TypeError, ValueError):
                    state_code = None
                if state_code not in (None, 0, 1):
                    desc = str(state.get("Desc") or "IntellectMoney request failed")
                    error_source = str(state.get("ErrorSourceParam") or "").strip()
                    if error_source:
                        desc = f"{desc} (param: {error_source})"
                    raise IntellectMoneyError(desc)
        return data

    @staticmethod
    def _is_hash_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return "param: hash" in text or '"hash"' in text

    async def create_invoice(
        self,
        *,
        order_id: str,
        service_name: str,
        amount_rub: Decimal | float | int | str,
        user_name: str,
        email: str,
        success_url: str,
        fail_url: str,
        back_url: str,
        result_url: str,
        preference: str = "Sbp",
    ) -> dict[str, Any]:
        amount_str = self.amount(amount_rub)
        base_form = {
            "EshopId": self.shop_id,
            "OrderId": order_id,
            "ServiceName": service_name,
            "RecipientAmount": amount_str,
            "RecipientCurrency": "RUB",
            "UserName": user_name,
            "Email": email,
            "SuccessUrl": success_url,
            "FailUrl": fail_url,
            "BackUrl": back_url,
            "ResultUrl": result_url,
            "Preference": preference,
        }
        last_exc: Exception | None = None
        hash_secrets = self._hash_secrets()
        for idx, hash_secret in enumerate(hash_secrets):
            form = dict(base_form)
            form["Hash"] = self._md5_hash(
                self.shop_id,
                order_id,
                service_name,
                amount_str,
                "RUB",
                user_name,
                email,
                success_url,
                fail_url,
                back_url,
                result_url,
                "",
                "",
                preference,
                hash_secret,
            )
            try:
                return await self._post_form(
                    "/merchant/createInvoice",
                    form,
                    self.shop_id,
                    order_id,
                    service_name,
                    amount_str,
                    "RUB",
                    user_name,
                    email,
                    success_url,
                    fail_url,
                    back_url,
                    result_url,
                    "",
                    "",
                    preference,
                )
            except IntellectMoneyError as exc:
                last_exc = exc
                if idx + 1 >= len(hash_secrets) or not self._is_hash_error(exc):
                    raise
                self.logger.warning("Retrying createInvoice with alternate IntellectMoney hash secret")
        assert last_exc is not None
        raise last_exc

    async def sbp_payment(
        self,
        *,
        invoice_id: str,
        success_url: str,
        fail_url: str,
        ip_address: str,
        additional_params: str = "",
    ) -> dict[str, Any]:
        base_form = {
            "EshopId": self.shop_id,
            "InvoiceId": invoice_id,
            "SuccessUrl": success_url,
            "FailUrl": fail_url,
            "AdditionalParams": additional_params,
            "IpAddress": ip_address,
        }
        last_exc: Exception | None = None
        hash_secrets = self._hash_secrets()
        for idx, hash_secret in enumerate(hash_secrets):
            form = dict(base_form)
            form["Hash"] = self._md5_hash(
                self.shop_id,
                invoice_id,
                success_url,
                fail_url,
                additional_params,
                ip_address,
                hash_secret,
            )
            try:
                return await self._post_form(
                    "/merchant/sbpPayment",
                    form,
                    self.shop_id,
                    invoice_id,
                    success_url,
                    fail_url,
                    additional_params,
                    ip_address,
                )
            except IntellectMoneyError as exc:
                last_exc = exc
                if idx + 1 >= len(hash_secrets) or not self._is_hash_error(exc):
                    raise
                self.logger.warning("Retrying sbpPayment with alternate IntellectMoney hash secret")
        assert last_exc is not None
        raise last_exc

    async def get_bank_card_payment_state(self, *, invoice_id: str) -> dict[str, Any]:
        base_form = {
            "EshopId": self.shop_id,
            "InvoiceId": invoice_id,
        }
        last_exc: Exception | None = None
        hash_secrets = self._hash_secrets()
        for idx, hash_secret in enumerate(hash_secrets):
            form = dict(base_form)
            form["Hash"] = self._md5_hash(self.shop_id, invoice_id, hash_secret)
            try:
                return await self._post_form(
                    "/merchant/getBankCardPaymentState",
                    form,
                    self.shop_id,
                    invoice_id,
                )
            except IntellectMoneyError as exc:
                last_exc = exc
                if idx + 1 >= len(hash_secrets) or not self._is_hash_error(exc):
                    raise
                self.logger.warning("Retrying getBankCardPaymentState with alternate IntellectMoney hash secret")
        assert last_exc is not None
        raise last_exc

    def verify_webhook_hash(self, payload: dict[str, Any]) -> bool:
        actual = str(payload.get("Hash") or "")
        if not actual:
            return False
        for hash_secret in self._hash_secrets():
            expected = self._md5_hash(
                payload.get("EshopId"),
                payload.get("OrderId"),
                payload.get("ServiceName"),
                payload.get("EshopAccount"),
                payload.get("RecipientAmount"),
                payload.get("RecipientCurrency"),
                payload.get("PaymentStatus"),
                payload.get("UserName"),
                payload.get("UserEmail"),
                payload.get("PaymentData"),
                hash_secret,
            )
            if actual.lower() == expected.lower():
                return True
        return False

    @staticmethod
    def parse_payment_state(data: dict[str, Any]) -> dict[str, Any]:
        result = data.get("Result") or {}
        payment_step = str(result.get("PaymentStep") or "")
        form_3ds_raw = result.get("Form3DS") or ""
        form_3ds: dict[str, Any] = {}
        if isinstance(form_3ds_raw, str) and form_3ds_raw.strip():
            try:
                form_3ds = json.loads(form_3ds_raw)
            except json.JSONDecodeError:
                form_3ds = {}
        return {
            "payment_step": payment_step,
            "qr_url": form_3ds.get("SbpQrCodeUrl"),
            "qr_image": form_3ds.get("SbpQrCodeImage"),
        }


intellectmoney = AsyncIntellectMoney()
