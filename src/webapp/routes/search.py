from typing import Literal
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.crud import search_products, search_users
from src.database import get_db

router = APIRouter(prefix="/search", tags=["search"])

@router.get("/products")
async def products(q: str | None = Query(None), page: int = Query(0, ge=0), limit: int = Query(10, ge=1), tg_category_ids: str | None = Query(None, description="CSV: 1,2,3"), tg_category_mode: Literal["any", "all"] = Query("any"), sort_by: Literal["name", "price"] = Query("name"), sort_dir: Literal["asc", "desc"] = Query("asc"), db: AsyncSession = Depends(get_db)):
    return await search_products(db, q=q, page=page, limit=limit, tg_category_ids=tg_category_ids, tg_category_mode=tg_category_mode, sort_by=sort_by, sort_dir=sort_dir)

@router.get("/users")
async def users(by: str | None = Query(None), value: str | None = Query(None), page: int = Query(0, ge=0), limit: int = Query(10, ge=1, le=200), db: AsyncSession = Depends(get_db)):
    rows, total = await search_users(db, by, value, page, limit)
    return {
        "page": page,
        "limit": limit,
        "total": int(total or 0),
        "items": rows,
    }
