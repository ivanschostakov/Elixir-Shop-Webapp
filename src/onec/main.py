import asyncio
import json
import logging
import time
import xml.etree.ElementTree as ET
import aiofiles
import httpx

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from config import ENTERPRISE_URL, ENTERPRISE_LOGIN, ENTERPRISE_PASSWORD
from src.onec import endpoints, keywords
from src.database import get_db_items, get_session

UPSERT_BATCH_SIZE = 500
SLEEP_INTERVAL = 900


def _dec(v: Any, default: str = "0") -> Decimal:
    if v is None: return Decimal(default)
    s = str(v).strip()
    if not s: return Decimal(default)
    s = s.replace(",", ".")
    try: return Decimal(s)
    except Exception: return Decimal(default)


class OneCEnterprise:
    TG_NOT_SOLD_PROP_KEY = "87cfc3b4-defa-11f0-8b75-fa163eccf8af"
    PARENT_KEY = "63d865c8-5fad-11f0-818d-fa163eccf8af"
    EMPTY_FEATURE_KEY = "00000000-0000-0000-0000-000000000000"
    FORCE_INCLUDE_PRODUCT_IDS = {
        "b019df8a-5a25-11f0-9098-fa163e347889",
        "101972c4-5a26-11f0-9098-fa163e347889",
        "3c8fd1e6-dd66-11ef-86f7-fa163e347889",
        "4039be2e-5a25-11f0-9098-fa163e347889",
        "346dda8e-5a26-11f0-9098-fa163e347889",
        "06543a26-5a26-11f0-9098-fa163e347889",
        "5242d4fc-5a25-11f0-9098-fa163e347889",
    }

    NS = {
        "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
        "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
        "atom": "http://www.w3.org/2005/Atom",
    }

    @staticmethod
    def _is_truthy(v: Any) -> bool:
        if v is None: return False
        return str(v).strip().lower() in {"true", "1", "yes", "y", "да", "истина"}

    @classmethod
    def _not_sold_in_tg(cls, extras: Any) -> bool:
        if not extras: return False
        for r in extras:
            if not isinstance(r, dict): continue
            if (r.get("Свойство_Key") or "").lower() == cls.TG_NOT_SOLD_PROP_KEY.lower(): return cls._is_truthy(r.get("Значение"))
        return False

    @classmethod
    def _synthetic_feature_id(cls, product_id: str) -> str:
        return f"{product_id}__synthetic"

    def __init__(self, url=ENTERPRISE_URL, username=ENTERPRISE_LOGIN, password=ENTERPRISE_PASSWORD):
        self.__client = httpx.AsyncClient(
            auth=(username, password),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            timeout=httpx.Timeout(30.0),
        )
        self.__url = url
        self.log = logging.getLogger(self.__class__.__name__)

    async def __fetch_odata(self, endpoint: str, save: bool = False) -> list[dict[str, Any]]:
        url = f"{self.__url}{endpoint}"
        response = None
        started = time.perf_counter()

        self.log.info(f"FETCH start: {endpoint}")

        for attempt in range(3):
            try:
                attempt_started = time.perf_counter()
                response = await self.__client.get(url)
                response.raise_for_status()
                self.log.info(
                    f"FETCH http ok: {endpoint} status={response.status_code} "
                    f"bytes={len(response.content)} attempt={attempt + 1} "
                    f"in {time.perf_counter() - attempt_started:.2f}s"
                )
                if response.status_code == httpx.codes.OK: break
            except Exception as e:
                self.log.warning(f"⚠️ Attempt {attempt + 1} failed for {url}: {e}")
                await asyncio.sleep(3)

        if not response: raise RuntimeError(f"❌ Failed to fetch {url} after 3 attempts")

        parse_started = time.perf_counter()
        root = ET.fromstring(response.content)
        self.log.info(f"FETCH xml parsed: {endpoint} in {time.perf_counter() - parse_started:.2f}s")

        entries = []
        build_started = time.perf_counter()

        for entry in root.findall("atom:entry", self.NS):
            content = entry.find("atom:content/m:properties", self.NS)
            if content is None: continue

            record = {}
            for elem in content:
                tag = elem.tag.split("}", 1)[1] if "}" in elem.tag else elem.tag
                if tag == "ДополнительныеРеквизиты":
                    record[tag] = [{sub.tag.split("}", 1)[1]: sub.text for sub in extra} for extra in elem.findall("d:element", self.NS)]
                else:
                    record[tag] = elem.text
            entries.append(record)

        self.log.info(
            f"FETCH built records: {endpoint} count={len(entries)} "
            f"in {time.perf_counter() - build_started:.2f}s total={time.perf_counter() - started:.2f}s"
        )

        if save:
            save_started = time.perf_counter()
            async with aiofiles.open(f"{endpoint.split('?')[0]}.json", "w", encoding="utf-8") as f:
                await f.write(json.dumps(entries, ensure_ascii=False, indent=4))
            self.log.info(f"FETCH saved json: {endpoint} in {time.perf_counter() - save_started:.2f}s")

        return entries

    async def get_units_1c(self, save: bool = False) -> dict[str, dict[str, Any]]:
        started = time.perf_counter()
        units = await self.__fetch_odata(endpoints.UNITS, save)
        result = {
            u["Ref_Key"]: {
                "onec_id": u["Ref_Key"],
                "name": u.get("Description"),
                "description": u.get("НаименованиеПолное"),
            }
            for u in units if u.get("Ref_Key") and u.get("DeletionMark") not in [True, "true"]
        }
        self.log.info(f"UNITS ready: {len(result)} in {time.perf_counter() - started:.2f}s")
        return result

    async def get_categories_1c(self, save: bool = False) -> dict[str, dict[str, Any]]:
        started = time.perf_counter()
        cats = await self.__fetch_odata(endpoints.CATEGORIES, save)
        result = {
            c["Ref_Key"]: {
                "onec_id": c["Ref_Key"],
                "unit_onec_id": None if c.get("ЕдиницаИзмерения_Key") == self.EMPTY_FEATURE_KEY else c.get("ЕдиницаИзмерения_Key"),
                "name": c.get("Description", "Без категории"),
                "code": c.get("Code"),
            }
            for c in cats if c.get("Ref_Key") and c.get("DeletionMark") not in [True, "true"]
        }
        self.log.info(f"CATEGORIES ready: {len(result)} in {time.perf_counter() - started:.2f}s")
        return result

    async def get_prices_1c(self, save: bool = False) -> dict[str, dict[str, Any]]:
        started = time.perf_counter()
        prices = await self.__fetch_odata(endpoints.PRICES, save)
        latest = {}

        for p in prices:
            product_id = p.get("Номенклатура_Key")
            feature_id = p.get("Характеристика_Key") or self.EMPTY_FEATURE_KEY
            period = p.get("Period")
            if not product_id or not period: continue

            key = (product_id, feature_id)
            try: dt = datetime.fromisoformat(period)
            except Exception: continue

            prev = latest.get(key)
            if not prev or dt > datetime.fromisoformat(prev["Period"]):
                latest[key] = p

        result = {
            f"{v['Номенклатура_Key']}_{v.get('Характеристика_Key') or self.EMPTY_FEATURE_KEY}": {
                "product_onec_id": v["Номенклатура_Key"],
                "feature_onec_id": v.get("Характеристика_Key") or self.EMPTY_FEATURE_KEY,
                "price": v.get("Цена"),
            }
            for v in latest.values()
        }
        self.log.info(
            f"PRICES ready: raw={len(prices)} latest={len(result)} in {time.perf_counter() - started:.2f}s"
        )
        return result

    async def get_balances_1c(self, save: bool = False) -> dict[str, dict[str, Any]]:
        started = time.perf_counter()
        balances = await self.__fetch_odata(endpoints.BALANCES, save)
        result = {
            f"{b['Номенклатура_Key']}_{b.get('Характеристика_Key') or self.EMPTY_FEATURE_KEY}": {
                "product_onec_id": b["Номенклатура_Key"],
                "feature_onec_id": b.get("Характеристика_Key") or self.EMPTY_FEATURE_KEY,
                "balance": b.get("Количество"),
            }
            for b in balances if b.get("Номенклатура_Key")
        }
        self.log.info(f"BALANCES ready: raw={len(balances)} mapped={len(result)} in {time.perf_counter() - started:.2f}s")
        return result

    async def get_features_1c(self, save: bool = False) -> dict[str, dict[str, Any]]:
        started = time.perf_counter()
        features_raw = await self.__fetch_odata(endpoints.FEATURES, save)

        features = {}
        for f in features_raw:
            if f.get("DeletionMark") in [True, "true"]: continue
            fid, pid = f.get("Ref_Key"), f.get("Owner")
            if not fid or not pid: continue

            features[fid] = {
                "onec_id": fid,
                "product_onec_id": pid,
                "name": f.get("Description"),
                "code": f.get("Code"),
                "file_id": f.get("ФайлКартинки_Key"),
            }

        self.log.info(f"FEATURES ready: raw={len(features_raw)} mapped={len(features)} in {time.perf_counter() - started:.2f}s")
        return features

    async def get_products_1c(self, save: bool = False) -> dict[str, dict[str, Any]]:
        started = time.perf_counter()
        products = await self.__fetch_odata(endpoints.PRODUCTS, save)
        out = {}

        for p in products:
            ref_key = p.get("Ref_Key")
            if not ref_key: continue
            if not p.get("КатегорияНоменклатуры_Key"): continue
            if p.get("Недействителен") == "true": continue
            if p.get("DeletionMark") in [True, "true"]: continue
            if p.get("ТипНоменклатуры") != "Запас": continue
            if ref_key not in self.FORCE_INCLUDE_PRODUCT_IDS and p.get("Parent_Key") != self.PARENT_KEY: continue

            extras = p.get("ДополнительныеРеквизиты") or []
            if self._not_sold_in_tg(extras): continue

            out[ref_key] = {
                "onec_id": ref_key,
                "category_onec_id": p.get("КатегорияНоменклатуры_Key"),
                "name": p.get("Description"),
                "code": p.get("Code"),
                "description": p.get("Комментарий"),
                "usage": next((t.get("ТекстоваяСтрока") for t in extras if any(k in (t.get("ТекстоваяСтрока", "") or "") for k in keywords.use)), None),
                "expiration": next((t.get("ТекстоваяСтрока") for t in extras if any(k in (t.get("ТекстоваяСтрока", "") or "") for k in keywords.expire)), None),
            }

        self.log.info(f"PRODUCTS ready: raw={len(products)} filtered={len(out)} in {time.perf_counter() - started:.2f}s")
        return out

    @staticmethod
    async def _upsert_table(db: AsyncSession, table, rows: list[dict[str, Any]], conflict_cols: list[str], update_cols: list[str], log: logging.Logger) -> None:
        if not rows:
            log.info(f"UPSERT skip: {table.name} no rows")
            return

        total = len(rows)
        started = time.perf_counter()
        log.info(f"UPSERT start: {table.name} rows={total}")

        for i in range(0, total, UPSERT_BATCH_SIZE):
            chunk = rows[i:i + UPSERT_BATCH_SIZE]
            chunk_started = time.perf_counter()

            stmt = pg_insert(table).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=[getattr(table.c, c) for c in conflict_cols],
                set_={c: getattr(stmt.excluded, c) for c in update_cols},
            )
            await db.execute(stmt)

            log.info(
                f"UPSERT chunk: {table.name} {i + len(chunk)}/{total} "
                f"in {time.perf_counter() - chunk_started:.2f}s"
            )

        log.info(f"UPSERT done: {table.name} rows={total} in {time.perf_counter() - started:.2f}s")

    async def update_db(self, approach: Literal["json", "postgres"], save: bool = False) -> None:
        total_started = time.perf_counter()
        self.log.info(f"UPDATE start: approach={approach} save={save}")

        fetch_started = time.perf_counter()
        products, features, categories, units, prices_map, balances_map = await asyncio.gather(
            self.get_products_1c(save),
            self.get_features_1c(save),
            self.get_categories_1c(save),
            self.get_units_1c(save),
            self.get_prices_1c(save),
            self.get_balances_1c(save),
        )
        self.log.info(
            f"UPDATE fetched all in {time.perf_counter() - fetch_started:.2f}s | "
            f"products={len(products)} features={len(features)} categories={len(categories)} "
            f"units={len(units)} prices={len(prices_map)} balances={len(balances_map)}"
        )

        merge_started = time.perf_counter()
        for fid, f in features.items():
            key = f"{f['product_onec_id']}_{fid}"
            f["price"] = prices_map.get(key, {}).get("price", "0")
            f["balance"] = balances_map.get(key, {}).get("balance", "0")
        self.log.info(f"UPDATE merged feature price/balance in {time.perf_counter() - merge_started:.2f}s")

        filter_started = time.perf_counter()
        features = {fid: f for fid, f in features.items() if f.get("product_onec_id") in products}
        products_with_features = {f["product_onec_id"] for f in features.values()}
        self.log.info(
            f"UPDATE filtered features in {time.perf_counter() - filter_started:.2f}s | "
            f"features_after_filter={len(features)} products_with_features={len(products_with_features)}"
        )

        synthetic_started = time.perf_counter()
        synthetic_added = 0
        for pid in products:
            if pid in products_with_features: continue

            key = f"{pid}_{self.EMPTY_FEATURE_KEY}"
            price = prices_map.get(key, {}).get("price", "0")
            balance = balances_map.get(key, {}).get("balance", "0")

            if _dec(price) > 0 or _dec(balance) > 0:
                sid = self._synthetic_feature_id(pid)
                features[sid] = {
                    "onec_id": sid,
                    "product_onec_id": pid,
                    "name": "Основной вариант",
                    "code": "__AUTO_DEFAULT__",
                    "file_id": None,
                    "price": price,
                    "balance": balance,
                }
                synthetic_added += 1

        self.log.info(
            f"UPDATE synthetic features added={synthetic_added} in {time.perf_counter() - synthetic_started:.2f}s | "
            f"total_features_now={len(features)}"
        )

        if approach != "postgres":
            json_started = time.perf_counter()
            self.log.info("UPDATE writing json files...")
            await asyncio.gather(
                self._write_json("products.json", products),
                self._write_json("features.json", features),
                self._write_json("categories.json", categories),
                self._write_json("units.json", units),
            )
            self.log.info(f"UPDATE json done in {time.perf_counter() - json_started:.2f}s total={time.perf_counter() - total_started:.2f}s")
            return

        from src.database.models import Unit, Category, Product, Feature

        rows_started = time.perf_counter()
        unit_rows = [{"onec_id": u["onec_id"], "name": u.get("name") or "", "description": u.get("description")} for u in units.values() if u.get("onec_id")]
        category_rows = [{"onec_id": c["onec_id"], "unit_onec_id": c.get("unit_onec_id"), "name": c.get("name") or "", "code": c.get("code")} for c in categories.values() if c.get("onec_id")]
        product_rows = [{"onec_id": p["onec_id"], "category_onec_id": p.get("category_onec_id"), "name": p.get("name") or "", "code": p.get("code"), "description": p.get("description"), "usage": p.get("usage"), "expiration": p.get("expiration")} for p in products.values() if p.get("onec_id")]
        feature_rows = [{"onec_id": f["onec_id"], "product_onec_id": f.get("product_onec_id"), "name": f.get("name") or "", "code": f.get("code"), "file_id": f.get("file_id"), "price": _dec(f.get("price")), "balance": _dec(max(int(_dec(f.get("balance"))), 0) - 3 if int(_dec(f.get("balance"))) >= 3 else 0)} for f in features.values() if f.get("onec_id")]
        self.log.info(
            f"UPDATE rows prepared in {time.perf_counter() - rows_started:.2f}s | "
            f"units={len(unit_rows)} categories={len(category_rows)} products={len(product_rows)} features={len(feature_rows)}"
        )

        db_started = time.perf_counter()
        self.log.info("UPDATE db session open...")
        async with get_session() as db:
            await self._upsert_table(db, Unit.__table__, unit_rows, ["onec_id"], ["name", "description"], self.log)
            await self._upsert_table(db, Category.__table__, category_rows, ["onec_id"], ["unit_onec_id", "name", "code"], self.log)
            await self._upsert_table(db, Product.__table__, product_rows, ["onec_id"], ["category_onec_id", "name", "code", "description", "usage", "expiration"], self.log)
            await self._upsert_table(db, Feature.__table__, feature_rows, ["onec_id"], ["product_onec_id", "name", "code", "file_id", "price", "balance"], self.log)

            commit_started = time.perf_counter()
            self.log.info("UPDATE db commit start...")
            await db.commit()
            self.log.info(f"UPDATE db commit done in {time.perf_counter() - commit_started:.2f}s")

        self.log.info(f"UPDATE db done in {time.perf_counter() - db_started:.2f}s total={time.perf_counter() - total_started:.2f}s")

    @staticmethod
    async def _write_json(file, data):
        started = time.perf_counter()
        async with aiofiles.open(file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, ensure_ascii=False, indent=4))
        logging.getLogger("OneCEnterprise").info(f"JSON written: {file} in {time.perf_counter() - started:.2f}s")

    async def postgres_worker(self):
        while True:
            cycle_started = time.perf_counter()
            self.log.info("WORKER cycle start")
            try:
                await self.update_db("postgres", False)
                self.log.info("WORKER update_db done, now get_db_items...")
                await get_db_items(self.log)
                self.log.info(f"WORKER cycle success in {time.perf_counter() - cycle_started:.2f}s")
            except Exception as e:
                self.log.exception(f"❌ Worker failed: {e}")
            self.log.info(f"WORKER sleep {SLEEP_INTERVAL}s")
            await asyncio.sleep(SLEEP_INTERVAL)

    async def close(self):
        self.log.info("HTTP client closing...")
        await self.__client.aclose()
        self.log.info("HTTP client closed")