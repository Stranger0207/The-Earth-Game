"""توابع دسترسی داده برای سرمایه‌گذاری‌ها (v1.9)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Investment


async def add_investment(session: AsyncSession, inv: Investment) -> Investment:
    session.add(inv)
    await session.flush()
    return inv


async def list_by_investor(session: AsyncSession, country_id: int) -> list[Investment]:
    """سرمایه‌گذاری‌هایی که این کشور انجام داده (داخلی + خارجی)."""
    result = await session.execute(
        select(Investment)
        .where(Investment.investor_country == country_id, Investment.active.is_(True))
        .order_by(Investment.id.desc())
    )
    return list(result.scalars().all())


async def list_on_target(session: AsyncSession, country_id: int) -> list[Investment]:
    """سرمایه‌گذاری‌هایی که دیگران روی این کشور انجام داده‌اند (فقط خارجی)."""
    result = await session.execute(
        select(Investment)
        .where(
            Investment.target_country == country_id,
            Investment.investor_country != country_id,
            Investment.active.is_(True),
        )
        .order_by(Investment.id.desc())
    )
    return list(result.scalars().all())


async def all_active(session: AsyncSession) -> list[Investment]:
    """همه‌ی سرمایه‌گذاری‌های فعال (برای پردازش بازدهی توسط زمان‌بند)."""
    result = await session.execute(
        select(Investment).where(Investment.active.is_(True))
    )
    return list(result.scalars().all())


async def count_by_investor_since(
    session: AsyncSession, investor_id: int, since
) -> int:
    """تعداد سرمایه‌گذاری‌های ثبت‌شده توسط یک کشور از زمان `since` (محدودیت v1.11)."""
    from sqlalchemy import func

    res = await session.execute(
        select(func.count()).select_from(Investment).where(
            Investment.investor_country == investor_id,
            Investment.created_at >= since,
        )
    )
    return res.scalar() or 0
