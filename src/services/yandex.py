import asyncio
import io
import logging
import re
import httpx
import pandas as pd

from decimal import Decimal
from typing import Any
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from urllib.parse import quote

from config import YANDEX_DISK_OAUTH_TOKEN
from src.database import get_session
from src.database.models import PromoCode

logger = logging.getLogger("promo_codes")
D0 = Decimal("0.00")

def _clean_str(v: Any) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v): return None
    s = str(v).strip()
    return s or None


def _to_decimal(v: Any, default: Decimal = D0) -> Decimal:
    if v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v): return default
    if isinstance(v, Decimal): return v
    s = str(v).strip()
    if not s: return default
    s = s.replace("%", "").replace(",", ".").strip()
    try: return Decimal(s)
    except Exception: return default


def _expand_codes(raw: str) -> list[str]:
    """
    If raw is like: "Ruslan (Rus, Ruslan2, RUSLAN)" -> create multiple promo codes:
      ["Ruslan", "Rus", "Ruslan2", "RUSLAN"]
    If no parentheses -> ["raw"]
    Also trims trailing quotes like "Ruslan (Ruslan)'" -> ["Ruslan", "Ruslan"]
    """
    if not raw: return []

    s = raw.strip()
    s = re.sub(r"[`’']+$", "", s).strip()
    if not s: return []

    m = re.match(r"^(.*?)\((.*?)\)\s*$", s)
    if not m: return [s]

    base = (m.group(1) or "").strip()
    inside = (m.group(2) or "").strip()

    out: list[str] = []
    seen: set[str] = set()

    def push(x: str):
        x = re.sub(r"[`’']+$", "", (x or "").strip()).strip()
        if not x: return
        if x in seen: return
        seen.add(x)
        out.append(x)

                              
    push(base if base else s)

    for part in re.split(r"[;,]", inside):
        part = part.strip()
        if part: push(part)

                                                                    
    if not out: push(s)

    return out


def _is_valid_promo_code(code: str | None) -> bool:
    code = _clean_str(code)
    if not code:
        return False
    if len(code) > 80:
        return False
    if "\n" in code or "\r" in code:
        return False
    if not re.search(r"[0-9A-Za-zА-Яа-яЁё]", code):
        return False
    if re.search(r"[.!?:\"«»]", code):
        return False
    if len(code.split()) > 3:
        return False
    return True


async def get_first_sheet_df() -> pd.DataFrame:
    base = "https://webdav.yandex.ru"
    url = base + quote("/Для менеджеров/Промокод Бонусная программа.xlsx", safe="/")
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(url, headers={"Authorization": f"OAuth {YANDEX_DISK_OAUTH_TOKEN}"})
        r.raise_for_status()

    df = pd.read_excel(io.BytesIO(r.content), sheet_name=0, engine="openpyxl", header=None, skiprows=2, usecols="A:J")
    return df


async def update_promo_codes(db: AsyncSession) -> dict[str, int]:
    df = await get_first_sheet_df()
    promos_by_code: dict[str, dict[str, Any]] = {}
    skipped_rows = 0
    skipped_codes = 0

    for _, row in df.iterrows():
        raw_code = _clean_str(row.iloc[0])     
        if not raw_code: continue
        owner_name = _clean_str(row.iloc[5])
        if not owner_name:
            skipped_rows += 1
            logger.warning("Skipping promo row without owner_name | raw_code=%r", raw_code)
            continue
        rec_base = {
            "discount_pct": _to_decimal(row.iloc[3], D0),         
            "owner_pct": _to_decimal(row.iloc[4], D0),            
            "owner_name": owner_name,
            "lvl1_pct": _to_decimal(row.iloc[6], D0),             
            "lvl1_name": _clean_str(row.iloc[7]),                 
            "lvl2_pct": _to_decimal(row.iloc[8], D0),             
            "lvl2_name": _clean_str(row.iloc[9]),                 
        }

        for code in _expand_codes(raw_code):
            if not _is_valid_promo_code(code):
                skipped_codes += 1
                logger.warning("Skipping invalid promo code candidate | code=%r | owner_name=%r", code, owner_name)
                continue
            promos_by_code[code] = {"code": code, **rec_base}

    file_codes = set(promos_by_code.keys())
    if not file_codes:
        return {"created": 0, "updated": 0, "deleted": 0, "skipped_rows": skipped_rows, "skipped_codes": skipped_codes}
    res = await db.execute(select(PromoCode).where(PromoCode.code.in_(file_codes)))
    existing = res.scalars().all()
    existing_by_code = {p.code: p for p in existing}

    created = 0
    updated = 0

    for code, rec in promos_by_code.items():
        obj = existing_by_code.get(code)

        if obj is None:
            obj = PromoCode(
                code=rec["code"],
                discount_pct=rec["discount_pct"],
                owner_name=rec["owner_name"],
                owner_pct=rec["owner_pct"],

                lvl1_name=rec["lvl1_name"],
                lvl1_pct=rec["lvl1_pct"],

                lvl2_name=rec["lvl2_name"],
                lvl2_pct=rec["lvl2_pct"],

                                     
                times_used=0,
                owner_amount_gained=D0,
                lvl1_amount_gained=D0,
                lvl2_amount_gained=D0,
            )
            db.add(obj)
            created += 1
            continue

        changed = False
        for field in ("discount_pct", "owner_name", "owner_pct", "lvl1_name", "lvl1_pct", "lvl2_name", "lvl2_pct"):
            new_val = rec[field]
            if getattr(obj, field) != new_val:
                setattr(obj, field, new_val)
                changed = True

        if changed: updated += 1

    del_res = await db.execute(delete(PromoCode).where(~PromoCode.code.in_(file_codes)))
    deleted = int(del_res.rowcount or 0)

    await db.commit()
    return {
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "skipped_rows": skipped_rows,
        "skipped_codes": skipped_codes,
    }


async def promo_codes_worker():
    while True:
        try:
            logger.info("Started updating promo codes")
            async with get_session() as session:
                result = await update_promo_codes(session)
            logger.info(
                "Created: %s, updated: %s, deleted: %s, skipped_rows: %s, skipped_codes: %s promo codes, sleeping for a day",
                result["created"],
                result["updated"],
                result["deleted"],
                result.get("skipped_rows", 0),
                result.get("skipped_codes", 0),
            )
            sleep_for = 24 * 3600
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Promo codes sync failed; retrying in 300s")
            sleep_for = 300
        await asyncio.sleep(sleep_for)
