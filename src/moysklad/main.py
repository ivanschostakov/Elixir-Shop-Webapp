import asyncio
import json
import logging
import time
import uuid

import aiofiles
import httpx

from decimal import Decimal
from typing import Any, Literal
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from config import (
    MOY_SKLAD_BASE_URL,
    MOY_SKLAD_STOCK_RESERVE,
    MOY_SKLAD_SYNC_INTERVAL_SECONDS,
    MOY_SKLAD_TIMEOUT_SECONDS,
    MOY_SKLAD_TOKEN,
)
from src.database import get_db_items, get_session

UPSERT_BATCH_SIZE = 500
SLEEP_INTERVAL = max(int(MOY_SKLAD_SYNC_INTERVAL_SECONDS), 60)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _fit_text(value: Any, max_len: int, fallback: str = "") -> str:
    normalized = _text(value)
    source = normalized if normalized is not None else fallback
    source = source.strip()
    if not source:
        source = fallback or ""
    if len(source) <= max_len:
        return source
    return source[:max_len]


def _dec(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    normalized = str(value).strip()
    if not normalized:
        return Decimal(default)
    normalized = normalized.replace(",", ".")
    try:
        return Decimal(normalized)
    except Exception:
        return Decimal(default)


def _uuid_text(value: Any) -> str | None:
    normalized = _text(value)
    if not normalized:
        return None
    try:
        return str(uuid.UUID(normalized))
    except Exception:
        return None


class MoySkladEnterprise:
    EXCLUDED_PATH_FILTER = "pathName!=Товары интернет-магазинов/elixirpeptide.ru"
    EXCLUDED_PATH_NAMES = {
        "Товары интернет-магазинов/elixirpeptide.ru",
        "Товары интернет-магазинов/https://elixirpeptide.ru/",
        "Пасхалка",
    }
    EXCLUDED_PRODUCT_NAME_PREFIXES = ("пакет",)

    def __init__(
        self,
        *,
        base_url: str | None = MOY_SKLAD_BASE_URL,
        token: str | None = MOY_SKLAD_TOKEN,
        timeout_seconds: int = MOY_SKLAD_TIMEOUT_SECONDS,
        stock_reserve: int = MOY_SKLAD_STOCK_RESERVE,
    ) -> None:
        self._base_url = (_text(base_url) or "").rstrip("/")
        self._token = _text(token) or ""
        self._timeout_seconds = max(int(timeout_seconds), 1)
        self._stock_reserve = max(int(stock_reserve), 0)
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()
        self.log = logging.getLogger(self.__class__.__name__)

    def is_configured(self) -> bool:
        return bool(self._base_url and self._token)

    async def _get_client(self) -> httpx.AsyncClient:
        if not self.is_configured():
            raise RuntimeError("MoySklad integration is not configured")
        if self._client is not None and not self._client.is_closed:
            return self._client

        async with self._client_lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    base_url=self._base_url,
                    timeout=httpx.Timeout(self._timeout_seconds),
                    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/json;charset=utf-8",
                        "Content-Type": "application/json;charset=utf-8",
                    },
                )
        return self._client

    async def close(self) -> None:
        self.log.info("HTTP client closing...")
        async with self._client_lock:
            if self._client is not None and not self._client.is_closed:
                await self._client.aclose()
            self._client = None
        self.log.info("HTTP client closed")

    @staticmethod
    def _meta_href_id(meta: Any) -> str | None:
        if not isinstance(meta, dict):
            return None
        href = _text(meta.get("href"))
        if not href:
            return None
        return _uuid_text(href.rstrip("/").rsplit("/", 1)[-1])

    @classmethod
    def _product_folder_id(cls, product: dict[str, Any]) -> str | None:
        folder = product.get("productFolder")
        if isinstance(folder, dict):
            direct = _uuid_text(folder.get("id"))
            if direct:
                return direct
            from_meta = cls._meta_href_id(folder.get("meta"))
            if from_meta:
                return from_meta
        return None

    @staticmethod
    def _stock_assortment_id(stock: dict[str, Any]) -> str | None:
        direct = _uuid_text(stock.get("assortmentId"))
        if direct:
            return direct

        assortment = stock.get("assortment")
        if isinstance(assortment, dict):
            assortment_id = _uuid_text(assortment.get("id"))
            if assortment_id:
                return assortment_id
            from_meta = MoySkladEnterprise._meta_href_id(assortment.get("meta"))
            if from_meta:
                return from_meta

        return MoySkladEnterprise._meta_href_id(stock.get("meta"))

    @staticmethod
    def _money(value: Any) -> Decimal:
        if value is None:
            return Decimal("0")
        return _dec(value) / Decimal("100")

    def _sale_price(self, item: dict[str, Any]) -> Decimal:
        sale_prices = item.get("salePrices")
        if isinstance(sale_prices, list):
            for sale_price in sale_prices:
                if isinstance(sale_price, dict):
                    amount = self._money(sale_price.get("value"))
                    if amount >= 0:
                        return amount
        return Decimal("0")

    def _available_stock(self, value: Any) -> int:
        raw = max(int(_dec(value)), 0)
        if self._stock_reserve <= 0:
            return raw
        return raw - self._stock_reserve if raw >= self._stock_reserve else 0

    @staticmethod
    def _variant_name(variant_name: Any, product_name: Any, fallback: str = "Основной вариант") -> str:
        name = _text(variant_name)
        if not name:
            return fallback

        product = _text(product_name)
        if not product:
            return name

        normalized_name = name.casefold().replace("ё", "е")
        normalized_product = product.casefold().replace("ё", "е")

        if normalized_name == normalized_product:
            return fallback

        if normalized_name.startswith(normalized_product):
            remainder = name[len(product):].strip(" -–—:|/\\\t\r\n")
            if remainder:
                if remainder.startswith("(") and remainder.endswith(")") and len(remainder) > 2:
                    remainder = remainder[1:-1].strip()
                if remainder:
                    return remainder

        return name

    async def _get_page(self, path: str, *, limit: int = 100, offset: int = 0, **params: Any) -> dict[str, Any]:
        request_params = dict(params)
        request_params["limit"] = limit
        request_params["offset"] = offset
        client = await self._get_client()
        response = await client.get(path, params=request_params)
        response.raise_for_status()
        return response.json()

    async def _get_all_rows(self, path: str, *, base_params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            data = await self._get_page(path, limit=100, offset=offset, **(base_params or {}))
            batch = data.get("rows", [])
            if not isinstance(batch, list):
                break
            rows.extend(item for item in batch if isinstance(item, dict))
            if len(batch) < 100:
                break
            offset += 100
        return rows

    async def get_products(self) -> list[dict[str, Any]]:
        try:
            rows = await self._get_all_rows("/entity/product", base_params={"filter": self.EXCLUDED_PATH_FILTER})
        except Exception:
            self.log.warning("MoySklad product filter rejected, retrying without path filter", exc_info=True)
            rows = await self._get_all_rows("/entity/product")

        products: list[dict[str, Any]] = []
        for product in rows:
            if bool(product.get("archived")):
                continue

            path_name = _text(product.get("pathName"))
            if path_name in self.EXCLUDED_PATH_NAMES:
                continue

            product_name = _text(product.get("name")) or ""
            if product_name.casefold().startswith(self.EXCLUDED_PRODUCT_NAME_PREFIXES):
                continue

            products.append(product)

        return products

    async def get_variants(self) -> list[dict[str, Any]]:
        return await self._get_all_rows("/entity/variant", base_params={"expand": "product"})

    async def get_stocks_report(self) -> list[dict[str, Any]]:
        return await self._get_all_rows("/report/stock/all")

    async def get_product_folders(self) -> list[dict[str, Any]]:
        return await self._get_all_rows("/entity/productfolder")

    @staticmethod
    async def _upsert_table(
        db: AsyncSession,
        table,
        rows: list[dict[str, Any]],
        conflict_cols: list[str],
        update_cols: list[str],
        log: logging.Logger,
    ) -> None:
        if not rows:
            log.info("UPSERT skip: %s no rows", table.name)
            return

        total = len(rows)
        started = time.perf_counter()
        log.info("UPSERT start: %s rows=%s", table.name, total)

        for index in range(0, total, UPSERT_BATCH_SIZE):
            chunk = rows[index : index + UPSERT_BATCH_SIZE]
            chunk_started = time.perf_counter()

            stmt = pg_insert(table).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=[getattr(table.c, column) for column in conflict_cols],
                set_={column: getattr(stmt.excluded, column) for column in update_cols},
            )
            await db.execute(stmt)

            log.info(
                "UPSERT chunk: %s %s/%s in %.2fs",
                table.name,
                index + len(chunk),
                total,
                time.perf_counter() - chunk_started,
            )

        log.info("UPSERT done: %s rows=%s in %.2fs", table.name, total, time.perf_counter() - started)

    async def _build_rows(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        fetch_started = time.perf_counter()
        products, variants, stocks, folders = await asyncio.gather(
            self.get_products(),
            self.get_variants(),
            self.get_stocks_report(),
            self.get_product_folders(),
        )
        self.log.info(
            "FETCH completed in %.2fs | products=%s variants=%s stocks=%s folders=%s",
            time.perf_counter() - fetch_started,
            len(products),
            len(variants),
            len(stocks),
            len(folders),
        )

        folders_by_id: dict[str, dict[str, Any]] = {}
        for folder in folders:
            folder_id = _uuid_text(folder.get("id"))
            if folder_id:
                folders_by_id[folder_id] = folder

        category_rows_by_id: dict[str, dict[str, Any]] = {}
        product_rows_by_id: dict[str, dict[str, Any]] = {}
        products_by_external_code: dict[str, dict[str, Any]] = {}

        for product in products:
            product_id = _uuid_text(product.get("id"))
            if not product_id:
                continue

            folder_id = self._product_folder_id(product)
            folder = folders_by_id.get(folder_id or "")
            if folder_id:
                category_rows_by_id[folder_id] = {
                    "onec_id": folder_id,
                    "unit_onec_id": None,
                    "name": _fit_text((folder or {}).get("name") or product.get("pathName") or "Без категории", 255, "Без категории"),
                    "code": _fit_text((folder or {}).get("code"), 128, ""),
                }

            product_name = _fit_text(product.get("name"), 96, _fit_text(product.get("code") or product_id, 96, "Без названия"))
            product_code = _fit_text(product.get("article") or product.get("code") or product_id, 16, "UNKNOWN")

            row = {
                "onec_id": product_id,
                "category_onec_id": folder_id,
                "name": product_name,
                "code": product_code,
                "description": _text(product.get("description")),
                "usage": None,
                "expiration": None,
            }
            product_rows_by_id[product_id] = row

            external_code = _text(product.get("externalCode"))
            if external_code:
                products_by_external_code[external_code] = product

        stock_by_assortment_id: dict[str, dict[str, Any]] = {}
        stock_by_external_code: dict[str, dict[str, Any]] = {}
        duplicated_stock_external_codes: set[str] = set()

        for stock in stocks:
            assortment_id = self._stock_assortment_id(stock)
            if assortment_id:
                stock_by_assortment_id[assortment_id] = stock

            external_code = _text(stock.get("externalCode"))
            if external_code:
                if external_code in stock_by_external_code:
                    duplicated_stock_external_codes.add(external_code)
                stock_by_external_code[external_code] = stock

        for external_code in duplicated_stock_external_codes:
            stock_by_external_code.pop(external_code, None)

        feature_rows_by_id: dict[str, dict[str, Any]] = {}
        products_with_variants: set[str] = set()

        for variant in variants:
            variant_id = _uuid_text(variant.get("id"))
            if not variant_id:
                continue

            product_meta = variant.get("product") if isinstance(variant.get("product"), dict) else {}
            product_id = _uuid_text(product_meta.get("id"))
            product = product_rows_by_id.get(product_id or "")

            product_external_code = _text(product_meta.get("externalCode"))
            if product is None and product_external_code:
                mapped_product = products_by_external_code.get(product_external_code)
                mapped_product_id = _uuid_text((mapped_product or {}).get("id"))
                if mapped_product_id:
                    product_id = mapped_product_id
                    product = product_rows_by_id.get(product_id)

            if product is None or not product_id:
                continue

            products_with_variants.add(product_id)

            variant_external_code = _text(variant.get("externalCode"))
            stock = stock_by_assortment_id.get(variant_id) or stock_by_external_code.get(variant_external_code or "")
            raw_stock = (stock or {}).get("quantity")
            if raw_stock is None:
                raw_stock = (stock or {}).get("stock")
            if raw_stock is None:
                raw_stock = (stock or {}).get("freeStock")

            feature_rows_by_id[variant_id] = {
                "onec_id": variant_id,
                "product_onec_id": product_id,
                "name": _fit_text(
                    self._variant_name(
                        variant.get("name"),
                        product.get("name"),
                        fallback=_fit_text(variant.get("code"), 255, "Основной вариант"),
                    ),
                    255,
                    "Основной вариант",
                ),
                "code": _fit_text(variant.get("code") or variant_external_code or variant_id, 128, variant_id),
                "file_id": None,
                "price": self._sale_price(variant),
                "balance": self._available_stock(raw_stock),
            }

        for product_id, product in product_rows_by_id.items():
            if product_id in products_with_variants:
                continue

            source_product = None
            source_external_code = None
            for external_code, item in products_by_external_code.items():
                if _uuid_text(item.get("id")) == product_id:
                    source_product = item
                    source_external_code = external_code
                    break

            stock = stock_by_assortment_id.get(product_id)
            if stock is None and source_external_code:
                stock = stock_by_external_code.get(source_external_code)

            raw_stock = (stock or {}).get("quantity")
            if raw_stock is None:
                raw_stock = (stock or {}).get("stock")
            if raw_stock is None:
                raw_stock = (stock or {}).get("freeStock")

            synthetic_id = f"{product_id}__synthetic"
            feature_rows_by_id[synthetic_id] = {
                "onec_id": synthetic_id,
                "product_onec_id": product_id,
                "name": "Основной вариант",
                "code": "__AUTO_DEFAULT__",
                "file_id": None,
                "price": self._sale_price(source_product or {}),
                "balance": self._available_stock(raw_stock),
            }

        unit_rows: list[dict[str, Any]] = []
        category_rows = list(category_rows_by_id.values())
        product_rows = list(product_rows_by_id.values())
        feature_rows = list(feature_rows_by_id.values())

        self.log.info(
            "ROWS prepared | units=%s categories=%s products=%s features=%s",
            len(unit_rows),
            len(category_rows),
            len(product_rows),
            len(feature_rows),
        )
        return unit_rows, category_rows, product_rows, feature_rows

    async def update_db(self, approach: Literal["json", "postgres"] = "postgres", save: bool = False) -> None:
        total_started = time.perf_counter()
        self.log.info("UPDATE start: approach=%s save=%s", approach, save)

        unit_rows, category_rows, product_rows, feature_rows = await self._build_rows()

        if approach != "postgres":
            json_started = time.perf_counter()
            self.log.info("UPDATE writing json files...")
            await asyncio.gather(
                self._write_json("units.json", {row["onec_id"]: row for row in unit_rows}),
                self._write_json("categories.json", {row["onec_id"]: row for row in category_rows}),
                self._write_json("products.json", {row["onec_id"]: row for row in product_rows}),
                self._write_json("features.json", {row["onec_id"]: row for row in feature_rows}),
            )
            self.log.info(
                "UPDATE json done in %.2fs total=%.2fs",
                time.perf_counter() - json_started,
                time.perf_counter() - total_started,
            )
            return

        from src.database.models import Category, Feature, Product, Unit

        db_started = time.perf_counter()
        async with get_session() as db:
            await self._upsert_table(db, Unit.__table__, unit_rows, ["onec_id"], ["name", "description"], self.log)
            await self._upsert_table(db, Category.__table__, category_rows, ["onec_id"], ["unit_onec_id", "name", "code"], self.log)
            await self._upsert_table(db, Product.__table__, product_rows, ["onec_id"], ["category_onec_id", "name", "code", "description", "usage", "expiration"], self.log)
            await self._upsert_table(db, Feature.__table__, feature_rows, ["onec_id"], ["product_onec_id", "name", "code", "file_id", "price", "balance"], self.log)

            commit_started = time.perf_counter()
            self.log.info("UPDATE db commit start...")
            await db.commit()
            self.log.info("UPDATE db commit done in %.2fs", time.perf_counter() - commit_started)

        self.log.info("UPDATE db done in %.2fs total=%.2fs", time.perf_counter() - db_started, time.perf_counter() - total_started)

    @staticmethod
    async def _write_json(file_name: str, data: dict[str, Any]) -> None:
        started = time.perf_counter()
        async with aiofiles.open(file_name, "w", encoding="utf-8") as file:
            await file.write(json.dumps(data, ensure_ascii=False, indent=4))
        logging.getLogger("MoySkladEnterprise").info("JSON written: %s in %.2fs", file_name, time.perf_counter() - started)

    async def postgres_worker(self) -> None:
        while True:
            cycle_started = time.perf_counter()
            self.log.info("WORKER cycle start")
            try:
                await self.update_db("postgres", False)
                self.log.info("WORKER update_db done, now get_db_items...")
                await get_db_items(self.log)
                self.log.info("WORKER cycle success in %.2fs", time.perf_counter() - cycle_started)
            except Exception as exc:
                self.log.exception("Worker failed: %s", exc)
            self.log.info("WORKER sleep %ss", SLEEP_INTERVAL)
            await asyncio.sleep(SLEEP_INTERVAL)
