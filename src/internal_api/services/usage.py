from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.crud import get_user_total_requests, get_user_usage_totals, get_usages, increment_tokens, write_usage
from src.database.schemas import BotLiteral
from src.internal_api.schemas import InternalIdResult, InternalUsageReportOut, InternalUserUsageTotalsOut


async def increment_tokens_service(db: AsyncSession, tg_id: int, *, input_inc: int = 0, output_inc: int = 0) -> None:
    await increment_tokens(db, tg_id, input_inc=input_inc, output_inc=output_inc)


async def write_usage_service(
    db: AsyncSession,
    *,
    user_id: int,
    input_tokens: int,
    output_tokens: int,
    bot: BotLiteral,
    usage_date: date | None = None,
    cached_input_tokens: int | None = None,
) -> InternalIdResult:
    usage = await write_usage(
        db,
        user_id,
        input_tokens,
        output_tokens,
        bot,
        usage_date=usage_date,
        cached_input_tokens=cached_input_tokens,
    )
    return InternalIdResult(id=usage.id)


async def get_user_total_requests_service(db: AsyncSession, user_id: int, bots: Sequence[BotLiteral] | None = None) -> int:
    return await get_user_total_requests(db, user_id, bots)


async def get_usages_service(
    db: AsyncSession,
    *,
    start_date: date,
    end_date: date | None = None,
    bot: BotLiteral | None = None,
) -> InternalUsageReportOut:
    period_label, usages = await get_usages(db, start_date=start_date, end_date=end_date, bot=bot)
    return InternalUsageReportOut(period_label=period_label, usages=usages)


async def get_user_usage_totals_service(
    db: AsyncSession,
    *,
    user_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> InternalUserUsageTotalsOut:
    totals = await get_user_usage_totals(db, user_id, start_date=start_date, end_date=end_date)
    return InternalUserUsageTotalsOut.model_validate(totals)
