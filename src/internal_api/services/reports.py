from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import UFA_TZ
from src.database.models import Cart, User, UserTokenUsage
from src.internal_api.schemas import (
    InternalUtmFunnelReportOut,
    InternalUtmFunnelRow,
    InternalUtmFunnelUser,
)


def _money(value: Any) -> float:
    return round(float(value or 0), 2)


def _cost(value: Any) -> float:
    return round(float(value or 0), 6)


def _utm_value(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _range_bounds(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    if end_date < start_date:
        raise ValueError("end_date cannot be earlier than start_date")
    start_dt = datetime.combine(start_date, time.min, tzinfo=UFA_TZ)
    end_dt = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UFA_TZ)
    return start_dt.astimezone(timezone.utc), end_dt.astimezone(timezone.utc)


async def get_utm_funnel_report_service(
    db: AsyncSession,
    *,
    start_date: date,
    end_date: date | None = None,
) -> InternalUtmFunnelReportOut:
    end_date = end_date or start_date
    start_bound, end_bound = _range_bounds(start_date, end_date)

    has_utm = or_(
        User.utm_source.is_not(None),
        User.utm_medium.is_not(None),
        User.utm_campaign.is_not(None),
        User.utm_content.is_not(None),
        User.utm_creative.is_not(None),
    )

    valid_carts = or_(Cart.name.is_(None), ~Cart.name.ilike("%ачальная%"))
    paid_orders = case((Cart.is_paid.is_(True), 1), else_=0)
    paid_sum = case((Cart.is_paid.is_(True), Cart.sum), else_=0)
    paid_delivery = case((Cart.is_paid.is_(True), Cart.delivery_sum), else_=0)

    cart_stats_sq = (
        select(
            Cart.user_id.label("user_id"),
            func.sum(paid_orders).label("paid_orders"),
            func.sum(paid_sum).label("goods_revenue"),
            func.sum(paid_delivery).label("delivery_revenue"),
        )
        .where(valid_carts)
        .group_by(Cart.user_id)
        .subquery()
    )

    usage_stats_sq = (
        select(
            UserTokenUsage.user_id.label("user_id"),
            func.sum(func.coalesce(UserTokenUsage.total_requests, 0)).label("ai_total_requests"),
            func.sum(func.coalesce(UserTokenUsage.input_tokens, 0)).label("input_tokens"),
            func.sum(func.coalesce(UserTokenUsage.cached_input_tokens, 0)).label("cached_input_tokens"),
            func.sum(func.coalesce(UserTokenUsage.output_tokens, 0)).label("output_tokens"),
            (
                func.sum(func.coalesce(UserTokenUsage.input_cost_usd, 0.0))
                + func.sum(func.coalesce(UserTokenUsage.output_cost_usd, 0.0))
            ).label("ai_total_cost_usd"),
        )
        .group_by(UserTokenUsage.user_id)
        .subquery()
    )

    stmt = (
        select(
            User.tg_id,
            User.tg_phone,
            User.created_at,
            User.updated_at,
            User.utm_source,
            User.utm_medium,
            User.utm_campaign,
            User.utm_content,
            User.utm_creative,
            User.utm_payload_raw,
            func.coalesce(cart_stats_sq.c.paid_orders, 0).label("paid_orders"),
            func.coalesce(cart_stats_sq.c.goods_revenue, 0).label("goods_revenue"),
            func.coalesce(cart_stats_sq.c.delivery_revenue, 0).label("delivery_revenue"),
            func.coalesce(usage_stats_sq.c.ai_total_requests, 0).label("ai_total_requests"),
            func.coalesce(usage_stats_sq.c.input_tokens, 0).label("input_tokens"),
            func.coalesce(usage_stats_sq.c.cached_input_tokens, 0).label("cached_input_tokens"),
            func.coalesce(usage_stats_sq.c.output_tokens, 0).label("output_tokens"),
            func.coalesce(usage_stats_sq.c.ai_total_cost_usd, 0.0).label("ai_total_cost_usd"),
        )
        .outerjoin(cart_stats_sq, cart_stats_sq.c.user_id == User.tg_id)
        .outerjoin(usage_stats_sq, usage_stats_sq.c.user_id == User.tg_id)
        .where(
            User.created_at >= start_bound,
            User.created_at < end_bound,
            has_utm,
        )
        .order_by(User.created_at.desc(), User.tg_id.desc())
    )

    rows = (await db.execute(stmt)).all()

    grouped: dict[tuple[str | None, str | None, str | None, str | None, str | None], dict[str, Any]] = {}
    users: list[InternalUtmFunnelUser] = []

    for row in rows:
        utm_key = (
            _utm_value(row.utm_source),
            _utm_value(row.utm_medium),
            _utm_value(row.utm_campaign),
            _utm_value(row.utm_content),
            _utm_value(row.utm_creative),
        )
        paid_orders_count = int(row.paid_orders or 0)
        goods_revenue = _money(row.goods_revenue)
        delivery_revenue = _money(row.delivery_revenue)
        total_revenue = round(goods_revenue + delivery_revenue, 2)
        ai_total_cost_usd = _cost(row.ai_total_cost_usd)
        verified = bool(str(row.tg_phone or "").strip())

        users.append(
            InternalUtmFunnelUser(
                tg_id=int(row.tg_id),
                tg_phone=row.tg_phone,
                created_at=row.created_at,
                updated_at=row.updated_at,
                utm_source=utm_key[0],
                utm_medium=utm_key[1],
                utm_campaign=utm_key[2],
                utm_content=utm_key[3],
                utm_creative=utm_key[4],
                utm_payload_raw=_utm_value(row.utm_payload_raw),
                verified=verified,
                paid_orders=paid_orders_count,
                goods_revenue=goods_revenue,
                delivery_revenue=delivery_revenue,
                total_revenue=total_revenue,
                ai_total_requests=int(row.ai_total_requests or 0),
                input_tokens=int(row.input_tokens or 0),
                cached_input_tokens=int(row.cached_input_tokens or 0),
                output_tokens=int(row.output_tokens or 0),
                ai_total_cost_usd=ai_total_cost_usd,
            )
        )

        aggregate = grouped.setdefault(
            utm_key,
            {
                "utm_source": utm_key[0],
                "utm_medium": utm_key[1],
                "utm_campaign": utm_key[2],
                "utm_content": utm_key[3],
                "utm_creative": utm_key[4],
                "registrations": 0,
                "verified_users": 0,
                "paid_users": 0,
                "paid_orders": 0,
                "goods_revenue": 0.0,
                "delivery_revenue": 0.0,
                "total_revenue": 0.0,
                "ai_total_requests": 0,
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "ai_total_cost_usd": 0.0,
            },
        )
        aggregate["registrations"] += 1
        aggregate["verified_users"] += int(verified)
        aggregate["paid_users"] += int(paid_orders_count > 0)
        aggregate["paid_orders"] += paid_orders_count
        aggregate["goods_revenue"] += goods_revenue
        aggregate["delivery_revenue"] += delivery_revenue
        aggregate["total_revenue"] += total_revenue
        aggregate["ai_total_requests"] += int(row.ai_total_requests or 0)
        aggregate["input_tokens"] += int(row.input_tokens or 0)
        aggregate["cached_input_tokens"] += int(row.cached_input_tokens or 0)
        aggregate["output_tokens"] += int(row.output_tokens or 0)
        aggregate["ai_total_cost_usd"] += ai_total_cost_usd

    grouped_rows = [
        InternalUtmFunnelRow(
            utm_source=payload["utm_source"],
            utm_medium=payload["utm_medium"],
            utm_campaign=payload["utm_campaign"],
            utm_content=payload["utm_content"],
            utm_creative=payload["utm_creative"],
            registrations=payload["registrations"],
            verified_users=payload["verified_users"],
            paid_users=payload["paid_users"],
            paid_orders=payload["paid_orders"],
            goods_revenue=round(payload["goods_revenue"], 2),
            delivery_revenue=round(payload["delivery_revenue"], 2),
            total_revenue=round(payload["total_revenue"], 2),
            ai_total_requests=payload["ai_total_requests"],
            input_tokens=payload["input_tokens"],
            cached_input_tokens=payload["cached_input_tokens"],
            output_tokens=payload["output_tokens"],
            ai_total_cost_usd=round(payload["ai_total_cost_usd"], 6),
        )
        for payload in sorted(
            grouped.values(),
            key=lambda item: (
                -item["registrations"],
                item["utm_source"] or "",
                item["utm_medium"] or "",
                item["utm_campaign"] or "",
                item["utm_content"] or "",
                item["utm_creative"] or "",
            ),
        )
    ]

    period_label = f"С {start_date:%Y-%m-%d} по {end_date:%Y-%m-%d}"
    return InternalUtmFunnelReportOut(period_label=period_label, rows=grouped_rows, users=users)
