
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..models import Unit
from ..schemas import UnitCreate, UnitUpdate

async def create_unit(db: AsyncSession, unit: UnitCreate) -> Unit:
    stmt = insert(Unit).values(**unit.dict())
    stmt = stmt.on_conflict_do_update(
        index_elements=["onec_id"],
        set_={
            "name": stmt.excluded.name,
            "description": stmt.excluded.description,
        },
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one_or_none()

async def get_units(db: AsyncSession) -> list[Unit]:
    result = await db.execute(select(Unit))
    return result.scalars().all()

async def get_unit(db: AsyncSession, unit_id: int) -> Unit | None:
    result = await db.execute(select(Unit).where(Unit.id == unit_id))
    return result.scalars().first()

async def update_unit(db: AsyncSession, unit_id: int, unit_data: UnitUpdate) -> Unit | None:
    result = await db.execute(select(Unit).where(Unit.id == unit_id))
    db_unit = result.scalars().first()
    if db_unit is None: return None

    for field, value in unit_data.dict().items(): setattr(db_unit, field, value)

    db.add(db_unit)
    await db.commit()
    await db.refresh(db_unit)
    return db_unit
