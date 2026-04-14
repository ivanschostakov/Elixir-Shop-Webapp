from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import UsedCode
from src.database.schemas import UsedCodeCreate, UsedCodeUpdate

async def create_used_code(session: AsyncSession, data: UsedCodeCreate) -> UsedCode:
    obj = UsedCode(user_id=data.user_id,code=data.code.strip(),price=data.price)
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return obj

async def get_used_code(session: AsyncSession, used_code_id: int) -> UsedCode | None:
    res = await session.execute(select(UsedCode).where(UsedCode.id == used_code_id))
    return res.scalar_one_or_none()

async def get_used_code_by_code(session: AsyncSession, code: str) -> UsedCode | None:
    code = code.strip()
    res = await session.execute(select(UsedCode).where(UsedCode.code == code))
    return res.scalar_one_or_none()

async def list_used_codes_by_user(session: AsyncSession, user_id: int, limit: int = 50, offset: int = 0) -> list[UsedCode]:
    res = await session.execute(select(UsedCode).where(UsedCode.user_id == user_id).order_by(UsedCode.id.desc()).limit(limit).offset(offset))
    return list(res.scalars().all())

async def update_used_code(session: AsyncSession, used_code_id: int, data: UsedCodeUpdate) -> UsedCode | None:
    obj = await get_used_code(session, used_code_id)
    if not obj: return None

    if data.code is not None: obj.code = data.code.strip()
    if data.price is not None: obj.price = data.price

    await session.commit()
    await session.refresh(obj)
    return obj

async def delete_used_code(session: AsyncSession, used_code_id: int) -> bool:
    res = await session.execute(delete(UsedCode).where(UsedCode.id == used_code_id))
    await session.commit()
    return (res.rowcount or 0) > 0
