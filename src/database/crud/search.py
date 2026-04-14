from typing import Literal, Any
from sqlalchemy import func, case, select, bindparam, cast, String, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload

from src.helpers import normalize, normalize_user_value
from src.database.models import Product, User, Cart
from src.database.models.product_tg_categories import product_tg_categories

def _parse_int_csv(value: str | None) -> list[int]:
    if not value: return []
    parts = [p.strip() for p in value.split(",") if p.strip()]
    out: list[int] = []
    for p in parts:
        try: out.append(int(p))
        except ValueError: continue

    seen = set()
    res = []
    for x in out:
        if x not in seen:
            seen.add(x)
            res.append(x)

    return res

async def _allowed_product_onec_ids_by_tg_categories(db: AsyncSession, tg_category_ids: list[int], mode: Literal["any", "all"] = "any") -> set[str] | None:
    if not tg_category_ids: return None
    if mode == "all": stmt = (select(product_tg_categories.c.product_onec_id).where(product_tg_categories.c.tg_category_id.in_(tg_category_ids)).group_by(product_tg_categories.c.product_onec_id).having(func.count(func.distinct(product_tg_categories.c.tg_category_id)) == len(tg_category_ids)))
    else: stmt = (select(product_tg_categories.c.product_onec_id).where(product_tg_categories.c.tg_category_id.in_(tg_category_ids)).distinct())
    rows = (await db.execute(stmt)).scalars().all()
    return set(rows)

async def search_products(db: AsyncSession, q: str | None, page: int, limit: int, tg_category_ids: str | None = None, tg_category_mode: Literal["any", "all"] = "any", sort_by: Literal["name", "price"] = "name", sort_dir: Literal["asc", "desc"] = "asc"):
    offset = page * limit
    filtered = []
    batch_size = 60
    skip = 0
    norm_q = await normalize(q) if q else None
    cat_ids = _parse_int_csv(tg_category_ids)
    allowed_onec_ids = await _allowed_product_onec_ids_by_tg_categories(db, tg_category_ids=cat_ids, mode=tg_category_mode)
    Feature = Product.features.property.mapper.class_
    stats_sq = select(Product.id.label("pid"), func.max(case((Feature.balance > 0, 1), else_=0)).label("has_stock"), func.min(case((Feature.balance > 0, Feature.price), else_=None)).label("min_stock_price"), func.max(case((Feature.balance > 0, Feature.price), else_=None)).label("max_stock_price")).select_from(Product).join(Feature, Product.features, isouter=True).group_by(Product.id).subquery()
    stock_rank = case((stats_sq.c.has_stock == 1, 0), else_=1)

    def ordered_stmt():
        stmt = select(Product).join(stats_sq, stats_sq.c.pid == Product.id).options(selectinload(Product.features))
        if allowed_onec_ids is not None: stmt = stmt.where(Product.onec_id.in_(allowed_onec_ids))
        if sort_by == "price":
            if sort_dir == "asc": stmt = stmt.order_by(stock_rank, stats_sq.c.min_stock_price.nulls_last(), func.lower(Product.name).asc())
            else: stmt = stmt.order_by(stock_rank, stats_sq.c.max_stock_price.desc().nulls_last(), func.lower(Product.name).asc())

        else:
            if sort_dir == "asc": stmt = stmt.order_by(stock_rank, func.lower(Product.name).asc(), stats_sq.c.min_stock_price.nulls_last())
            else: stmt = stmt.order_by(stock_rank, func.lower(Product.name).desc(), stats_sq.c.min_stock_price.nulls_last())

        return stmt

    while True:
        stmt = ordered_stmt().offset(skip).limit(batch_size)
        result = await db.execute(stmt)
        batch = result.scalars().all()
        if not batch: break
        for product in batch:
            if norm_q and norm_q not in await normalize(product.name): continue
            all_features = list(product.features or [])
            in_stock_features = [f for f in all_features if (getattr(f, "balance", 0) or 0) > 0]
            prices = [float(f.price) for f in in_stock_features if f.price is not None]
            min_price = min(prices) if prices else 0.0
            max_price = max(prices) if prices else 0.0

            filtered.append(
                {
                    "name": product.name,
                    "onec_id": product.onec_id,
                    "url": f"/product/{product.onec_id}",
                    "image": "/static/images/product.png",
                    "min_price": min_price,
                    "max_price": max_price,
                    "features": [
                        {
                            "id": f.onec_id,
                            "name": f.name,
                            "price": float(f.price) if f.price is not None else None,
                            "balance": getattr(f, "balance", 0) or 0,
                        }
                        for f in all_features
                    ],
                }
            )

        skip += batch_size

    page_results = filtered[offset: offset + limit]
    if q or cat_ids: total = len(filtered)
    else: total = await db.scalar(select(func.count()).select_from(Product))

    for item in page_results:
        item.pop("min_price", None)
        item.pop("max_price", None)

    return {"results": page_results, "total": total}

async def search_users(db: AsyncSession, by: str, value: Any, page: int | None = None, limit: int | None = None) -> tuple[list[User], int]:
    stmt = select(User)
    if by is not None:
        norm_value = normalize_user_value(by, value) if by not in {"full_name", "phone"} else str(value)
        if norm_value is None or str(norm_value).strip() == "": return [], 0
        if by == "tg_id":
            col = getattr(User, "tg_id", None)
            if col is None: return [], 0
            v = str(norm_value).replace(" ", "")
            stmt = stmt.where(cast(col, String).ilike(bindparam("v", f"%{v}%", type_=String())))

        elif by == "full_name":
            return [], 0
        elif by == "phone":
            tg_phone_col = getattr(User, "tg_phone", None)
            if tg_phone_col is None: return [], 0
            v = str(norm_value).replace(" ", "")
            stmt = stmt.where(func.replace(cast(tg_phone_col, String), " ", "").ilike(bindparam("v", f"%{v}%", type_=String())))

        else:
            col = getattr(User, by, None)
            if col is None: return [], 0
            v = str(norm_value).replace(" ", "")
            col_nospace = func.replace(cast(col, String), " ", "")
            stmt = stmt.where(col_nospace.ilike(bindparam("v", f"%{v}%", type_=String())))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = await db.scalar(count_stmt)

    stmt = stmt.order_by(User.tg_id.desc())
    if limit is not None: stmt = stmt.limit(limit)
    if page is not None and limit is not None: stmt = stmt.offset(page * limit)

    rows = (await db.execute(stmt)).scalars().all()
    return rows, int(total or 0)

async def search_carts(db: AsyncSession, value: Any, page: int | None = None, limit: int | None = None) -> tuple[list[Cart], int]:
    stmt = (select(Cart).where(or_(Cart.name.is_(None), ~Cart.name.ilike(f"%ачальная%"))).options(selectinload(Cart.items), joinedload(Cart.promo), selectinload(Cart.user)))
    v = str(value).replace(" ", "").strip()
    if not v: return [], 0
    col = getattr(Cart, "id", None)
    if col is None: return [], 0

    stmt = stmt.where(cast(col, String).ilike(bindparam("v", f"%{v}%", type_=String())))
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = await db.scalar(count_stmt)

    stmt = stmt.order_by(Cart.id.desc())
    if limit is not None: stmt = stmt.limit(limit)
    if page is not None and limit is not None: stmt = stmt.offset(page * limit)

    rows = (await db.execute(stmt)).scalars().all()
    return rows, int(total or 0)
