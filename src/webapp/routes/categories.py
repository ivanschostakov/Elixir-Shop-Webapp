from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.database.models import TgCategory

router = APIRouter(prefix="/tg-categories", tags=["tg-categories"])


@router.get("")
@router.get("/")
async def list_categories(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(TgCategory).order_by(TgCategory.name.asc()))).scalars().all()
    return [{"id": c.id, "name": c.name, "description": c.description} for c in rows]
