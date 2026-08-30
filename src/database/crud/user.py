from typing import Any

from sqlalchemy import select, update, bindparam
from sqlalchemy.ext.asyncio import AsyncSession

from src.helpers import normalize_user_value
from src.database.models import ConversationToken, User
from src.database.schemas import UserCreate, UserUpdate


_FIRST_TOUCH_ONLY_FIELDS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_creative",
    "utm_payload_raw",
}


def _normalize_conversation_id(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


async def _ensure_conversation_token(db: AsyncSession, conversation_id: Any) -> str | None:
    normalized = _normalize_conversation_id(conversation_id)
    if normalized is None:
        return None
    conversation = await db.get(ConversationToken, normalized)
    if conversation is None:
        db.add(ConversationToken(conversation_id=normalized))
        await db.flush()
    return normalized

async def create_user(db: AsyncSession, data: UserCreate) -> User:
    payload = data.dict()
    payload["conversation_id"] = await _ensure_conversation_token(db, payload.get("conversation_id"))
    user = User(**payload)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

async def get_user(db, column_name: str, raw_value: Any) -> User | None:
    column = getattr(User, column_name, None)
    if column is None: return None

    value = normalize_user_value(column_name, raw_value)
    stmt = select(User).where(column == bindparam("v", value, type_=column.type))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def get_tg_refs(db: AsyncSession, value, by: str = 'tg_ref_id') -> User | None:
    if not hasattr(User, by): raise AttributeError(f"User model has no attribute '{by}'")

    column = getattr(User, by)
    result = await db.execute(select(User).where(column == value))
    return result.scalars().all()

async def get_users(db: AsyncSession) -> list[User]:
    result = await db.execute(select(User))
    return result.scalars().all()

                                          
async def update_user(db: AsyncSession, tg_id: int, data: UserUpdate) -> User | None:
    user = await db.get(User, tg_id)
    if not user: return None

    for field, value in data.dict(exclude_unset=True).items():
        if field == "conversation_id":
            setattr(user, field, await _ensure_conversation_token(db, value))
            continue
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)
    return user

                                          
async def upsert_user(db: AsyncSession, user_upsert) -> User:
    data = user_upsert.model_dump(exclude_unset=True)
    if "conversation_id" in data:
        data["conversation_id"] = await _ensure_conversation_token(db, data.get("conversation_id"))
    tg_id: int | None = data.get("tg_id")
    contact_id: int | None = data.get("contact_id")
    user: User | None = None

    if tg_id is not None:
        res = await db.execute(select(User).where(User.tg_id == tg_id))
        user = res.scalar_one_or_none()

    if user is None and contact_id is not None:
        res = await db.execute(select(User).where(User.contact_id == contact_id))
        user = res.scalar_one_or_none()

    if user is not None:
        for field, value in data.items():
            if field in _FIRST_TOUCH_ONLY_FIELDS:
                continue
            if value is not None: setattr(user, field, value)
    else:
        user = User(**data)
        db.add(user)

    await db.commit()
    await db.refresh(user)
    return user

async def increment_tokens(db: AsyncSession, tg_id: int, input_inc: int = 0, output_inc: int = 0):
    stmt = (
        update(User)
        .where(User.tg_id == tg_id)
        .values(
            input_tokens=User.input_tokens + input_inc,
            output_tokens=User.output_tokens + output_inc
        )
        .execution_options(synchronize_session=False)
    )
    await db.execute(stmt)
    await db.commit()

                                          
async def delete_user(db: AsyncSession, tg_id: int) -> bool:
    user = await db.get(User, tg_id)
    if not user: return False
    await db.delete(user)
    await db.commit()
    return True

async def update_premium_requests(db: AsyncSession, value: int = 2) -> int:
    result = await db.execute(
        update(User)
        .values(premium_requests=value)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return result.rowcount or 0

async def update_user_name(i: int, first_name: str | None = None, last_name: str | None = None) -> User | None:
    from src.database import get_session
    async with get_session() as _session:
        user = await _session.get(User, i)
        return user
