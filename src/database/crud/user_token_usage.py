from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import BotEnum, UserTokenUsage, User
from src.database.schemas import BotLiteral

def _usage_int(value: Any) -> int:
    # Legacy/imported rows can still contain NULL counters despite model defaults.
    return int(value or 0)

async def get_usages(db: AsyncSession, start_date: date, end_date: date | None = None, bot: BotLiteral | None = None,) -> tuple[str, list[dict[str, float]]]:
    end_date = end_date or date.today()
    if end_date < start_date: raise ValueError("end_date cannot be earlier than start_date")

    where_clauses = [UserTokenUsage.date >= start_date, UserTokenUsage.date <= end_date]
    if bot: where_clauses.append(UserTokenUsage.bot == BotEnum(bot))

    stmt = (
        select(
            UserTokenUsage.user_id,
            User.tg_phone,
            UserTokenUsage.bot.label("bot"),
            func.coalesce(UserTokenUsage.total_requests, 0).label("total_requests"),
            func.coalesce(UserTokenUsage.input_tokens, 0).label("input_tokens"),
            func.coalesce(UserTokenUsage.cached_input_tokens, 0).label("cached_input_tokens"),
            func.coalesce(UserTokenUsage.output_tokens, 0).label("output_tokens"),
        )
        .join(User, UserTokenUsage.user_id == User.tg_id)
        .where(*where_clauses)
        .order_by(UserTokenUsage.user_id, UserTokenUsage.date, UserTokenUsage.bot)
    )
    period_label = f"С {start_date:%Y-%m-%d} по {end_date:%Y-%m-%d}" + (f" (бот: {bot})" if bot else "")
    result = await db.execute(stmt)
    rows = result.all()
    usage_list: list[dict[str, float]] = []
    usage_by_user: dict[tuple[int, str | None], dict[str, Any]] = {}

    for row in rows:
        input_tokens = _usage_int(row.input_tokens)
        cached_input_tokens = _usage_int(row.cached_input_tokens)
        output_tokens = _usage_int(row.output_tokens)
        total_requests = _usage_int(row.total_requests)
        input_cost, output_cost = UserTokenUsage.calculate_costs(row.bot, input_tokens, cached_input_tokens, output_tokens)
        key = (int(row.user_id), row.tg_phone)
        aggregate = usage_by_user.setdefault(
            key,
            {
                "user_id": int(row.user_id),
                "tg_phone": row.tg_phone,
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "total_requests": 0,
                "input_cost_usd": 0.0,
                "output_cost_usd": 0.0,
            },
        )
        aggregate["input_tokens"] += input_tokens
        aggregate["cached_input_tokens"] += cached_input_tokens
        aggregate["output_tokens"] += output_tokens
        aggregate["total_requests"] += total_requests
        aggregate["input_cost_usd"] += input_cost
        aggregate["output_cost_usd"] += output_cost

    for aggregate in usage_by_user.values():
        total_tokens = aggregate["input_tokens"] + aggregate["output_tokens"]
        total_cost = aggregate["input_cost_usd"] + aggregate["output_cost_usd"]
        total_requests = aggregate["total_requests"]
        usage_list.append({
            "Айди Телеграм": aggregate["user_id"],
            "Номер Телеграм": aggregate["tg_phone"],
            "Входящие токены": aggregate["input_tokens"],
            "Кэшированные входящие токены": aggregate["cached_input_tokens"],
            "Исходящие токены": aggregate["output_tokens"],
            "Всего токенов": total_tokens,
            "Всего запросов": total_requests,
            "Стоимость входящих в $": round(aggregate["input_cost_usd"], 2),
            "Стоимость исходящих в $": round(aggregate["output_cost_usd"], 2),
            "Стоимость всего в $": round(total_cost, 2),
            "Средняя стоимость запроса": round(total_cost / total_requests, 4) if total_requests else 0.0,
        })

    return period_label, usage_list

async def write_usage(
        db: AsyncSession,
        user_id: int,
        input_tokens: int,
        output_tokens: int,
        bot: BotLiteral,
        usage_date: date | None = None,
        cached_input_tokens: int | None = None,
):
    usage_date = usage_date or date.today()
    input_tokens = _usage_int(input_tokens)
    output_tokens = _usage_int(output_tokens)

    result = await db.execute(select(UserTokenUsage).where(UserTokenUsage.user_id == user_id, UserTokenUsage.date == usage_date, UserTokenUsage.bot == BotEnum(bot)))
    usage = result.scalar_one_or_none()
    cached_input_increment = None if cached_input_tokens is None else max(int(cached_input_tokens), 0)
    if usage:
        usage.input_tokens = _usage_int(usage.input_tokens) + input_tokens
        usage.output_tokens = _usage_int(usage.output_tokens) + output_tokens
        usage.total_requests = _usage_int(usage.total_requests) + 1
        if cached_input_increment is None:
            usage.cached_input_tokens = UserTokenUsage.estimate_cached_input_tokens(usage.bot, usage.input_tokens, usage.total_requests)
            usage.cached_input_tokens_estimated = True
        else:
            usage.cached_input_tokens = min(max(_usage_int(usage.input_tokens), 0), _usage_int(usage.cached_input_tokens) + cached_input_increment)
            if usage.cached_input_tokens_estimated:
                usage.cached_input_tokens_estimated = True

    else:
        cached_input_total = (
            UserTokenUsage.estimate_cached_input_tokens(bot, input_tokens, 1)
            if cached_input_increment is None
            else min(max(cached_input_increment, 0), max(int(input_tokens or 0), 0))
        )
        usage = UserTokenUsage(
            user_id=user_id,
            date=usage_date,
            bot=BotEnum(bot),
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_total,
            cached_input_tokens_estimated=cached_input_increment is None,
            output_tokens=output_tokens,
            total_requests=1,
        )
        db.add(usage)

    await db.commit()
    await db.refresh(usage)
    return usage

async def get_user_usage_totals(db: AsyncSession, user_id: int, start_date: date | None = None, end_date: date | None = None) -> dict[str, Any]:
    end_date = end_date or date.today()
    where_clauses = [UserTokenUsage.user_id == user_id]
    if start_date:
        if end_date < start_date: raise ValueError("end_date cannot be earlier than start_date")
        where_clauses += [UserTokenUsage.date >= start_date, UserTokenUsage.date <= end_date]

    else: where_clauses += [UserTokenUsage.date <= end_date]
    tg_phone = await db.scalar(select(User.tg_phone).where(User.tg_id == user_id))
    stmt = (
        select(
            UserTokenUsage.bot.label("bot"),
            func.coalesce(UserTokenUsage.total_requests, 0).label("total_requests"),
            func.coalesce(UserTokenUsage.input_tokens, 0).label("input_tokens"),
            func.coalesce(UserTokenUsage.cached_input_tokens, 0).label("cached_input_tokens"),
            func.coalesce(UserTokenUsage.output_tokens, 0).label("output_tokens"),
        )
        .where(*where_clauses)
        .order_by(UserTokenUsage.date, UserTokenUsage.bot)
    )
    rows = (await db.execute(stmt)).all()
    by_bot_map: dict[str, dict[str, Any]] = {}
    grand_requests = grand_in = grand_out = 0
    grand_in_cost = grand_out_cost = 0.0

    for r in rows:
        in_tokens = _usage_int(r.input_tokens)
        cached_in_tokens = _usage_int(r.cached_input_tokens)
        out_tokens = _usage_int(r.output_tokens)
        reqs = _usage_int(r.total_requests)
        in_cost, out_cost = UserTokenUsage.calculate_costs(r.bot, in_tokens, cached_in_tokens, out_tokens)
        total_cost = in_cost + out_cost
        bot_name = getattr(r.bot, "value", str(r.bot))
        aggregate = by_bot_map.setdefault(
            bot_name,
            {
                "bot": bot_name,
                "total_requests": 0,
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "input_cost_usd": 0.0,
                "output_cost_usd": 0.0,
            },
        )
        aggregate["total_requests"] += reqs
        aggregate["input_tokens"] += in_tokens
        aggregate["cached_input_tokens"] += cached_in_tokens
        aggregate["output_tokens"] += out_tokens
        aggregate["input_cost_usd"] += in_cost
        aggregate["output_cost_usd"] += out_cost

        grand_requests += reqs
        grand_in += in_tokens
        grand_out += out_tokens
        grand_in_cost += in_cost
        grand_out_cost += out_cost

    by_bot = []
    for bot_name in sorted(by_bot_map):
        aggregate = by_bot_map[bot_name]
        total_cost = aggregate["input_cost_usd"] + aggregate["output_cost_usd"]
        total_requests = aggregate["total_requests"]
        by_bot.append({
            "bot": bot_name,
            "total_requests": total_requests,
            "input_tokens": aggregate["input_tokens"],
            "cached_input_tokens": aggregate["cached_input_tokens"],
            "output_tokens": aggregate["output_tokens"],
            "total_tokens": aggregate["input_tokens"] + aggregate["output_tokens"],
            "input_cost_usd": round(aggregate["input_cost_usd"], 4),
            "output_cost_usd": round(aggregate["output_cost_usd"], 4),
            "total_cost_usd": round(total_cost, 4),
            "avg_cost_per_request": round(total_cost / total_requests, 6) if total_requests else 0.0,
        })

    totals = {
        "total_requests": grand_requests,
        "input_tokens": grand_in,
        "cached_input_tokens": sum(item["cached_input_tokens"] for item in by_bot),
        "output_tokens": grand_out,
        "total_tokens": grand_in + grand_out,
        "input_cost_usd": round(grand_in_cost, 4),
        "output_cost_usd": round(grand_out_cost, 4),
        "total_cost_usd": round(grand_in_cost + grand_out_cost, 4),
        "avg_cost_per_request": round((grand_in_cost + grand_out_cost) / grand_requests, 6) if grand_requests else 0.0,
    }

    period_label = (f"С {start_date:%Y-%m-%d} по {end_date:%Y-%m-%d}" if start_date else f"До {end_date:%Y-%m-%d}")

    return {
        "period": period_label,
        "user_id": user_id,
        "tg_phone": tg_phone,
        "by_bot": by_bot,
        "totals": totals,
    }

async def get_user_total_requests(db: AsyncSession, user_id: int, bots: Sequence[BotLiteral] | None = None,) -> int:
    stmt = select(func.coalesce(func.sum(UserTokenUsage.total_requests), 0)).where(UserTokenUsage.user_id == user_id)
    if bots: stmt = stmt.where(UserTokenUsage.bot.in_([BotEnum(bot) for bot in bots]))
    return int((await db.execute(stmt)).scalar_one() or 0)
