from sqlalchemy import case, func, select
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.crud import get_user, get_users, search_users, update_user, update_user_name, upsert_user
from src.database.models import User
from src.database.schemas import UserCreate, UserUpdate
from src.amocrm.client import amocrm
from src.internal_api.schemas import InternalSearchUsersOut, InternalUserRead
from src.internal_api.services.serializers import serialize_user, serialize_user_enriched, serialize_users_enriched


def _collapse_spaces(value: str) -> str:
    return " ".join(str(value or "").split())


async def _search_users_by_contact_field(
    db: AsyncSession,
    by: str,
    value: Any,
    *,
    page: int | None = None,
    limit: int | None = None,
) -> tuple[list[User], int]:
    query = str(value or "").strip()
    if not query:
        return [], 0

    contacts = await amocrm.search_contacts(query, limit=min(max(limit or 50, 50) * 4, 250))
    if not contacts:
        return [], 0

    needle = _collapse_spaces(query).replace(" ", "").lower()
    if not needle:
        return [], 0

    matched_contact_ids: list[int] = []
    seen_contact_ids: set[int] = set()
    for contact in contacts:
        raw_contact_id = contact.get("id")
        if not raw_contact_id:
            continue

        try:
            contact_id = int(raw_contact_id)
        except (TypeError, ValueError):
            continue

        contact_data = contact
        if by == "email" and not contact.get("custom_fields_values"):
            full_contact = await amocrm.get_contact(contact_id)
            if full_contact:
                contact_data = full_contact

        if by == "email":
            payload = amocrm.contact_payload(contact_data)
            haystack = str(payload.get("email") or "").replace(" ", "").lower()
        else:
            haystack = _collapse_spaces(contact_data.get("name") or "").replace(" ", "").lower()

        if not haystack or needle not in haystack or contact_id in seen_contact_ids:
            continue

        seen_contact_ids.add(contact_id)
        matched_contact_ids.append(contact_id)

    if not matched_contact_ids:
        return [], 0

    order_by_contact = case(
        {contact_id: position for position, contact_id in enumerate(matched_contact_ids)},
        value=User.contact_id,
        else_=len(matched_contact_ids),
    )
    stmt = select(User).where(User.contact_id.in_(matched_contact_ids))
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = await db.scalar(count_stmt)

    stmt = stmt.order_by(order_by_contact, User.tg_id.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    if page is not None and limit is not None:
        stmt = stmt.offset(page * limit)

    rows = (await db.execute(stmt)).scalars().all()
    return rows, int(total or 0)


async def lookup_user_service(db: AsyncSession, column_name: str, raw_value: Any) -> InternalUserRead | None:
    user = await get_user(db, column_name, raw_value)
    return await serialize_user_enriched(user)


async def list_users_service(db: AsyncSession) -> list[InternalUserRead]:
    users = await get_users(db)
    return [serialize_user(user) for user in users if user]


async def upsert_user_service(db: AsyncSession, data: UserCreate) -> InternalUserRead:
    user = await upsert_user(db, data)
    return serialize_user(user)


async def update_user_service(db: AsyncSession, tg_id: int, data: UserUpdate) -> InternalUserRead | None:
    user = await update_user(db, tg_id, data)
    return await serialize_user_enriched(user)


async def update_user_name_service(tg_id: int, first_name: str | None = None, last_name: str | None = None) -> bool:
    await update_user_name(tg_id, first_name, last_name)
    return True


async def search_users_service(
    db: AsyncSession,
    by: str,
    value: Any,
    *,
    page: int | None = None,
    limit: int | None = None,
) -> InternalSearchUsersOut:
    if by in {"full_name", "email"}:
        rows, total = await _search_users_by_contact_field(db, by, value, page=page, limit=limit)
    else:
        rows, total = await search_users(db, by, value, page=page, limit=limit)

    return InternalSearchUsersOut(rows=await serialize_users_enriched(rows), total=total)
