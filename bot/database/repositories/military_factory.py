"""توابع دسترسی داده برای کارخانه‌های نظامی (v1.7)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MilitaryFactory


async def add_factory(session: AsyncSession, factory: MilitaryFactory) -> MilitaryFactory:
    session.add(factory)
    await session.flush()
    return factory


async def list_factories(
    session: AsyncSession, country_id: int
) -> list[MilitaryFactory]:
    """فهرست کارخانه‌های نظامی یک کشور."""
    result = await session.execute(
        select(MilitaryFactory).where(MilitaryFactory.country_id == country_id)
    )
    return list(result.scalars().all())


async def all_active_factories(session: AsyncSession) -> list[MilitaryFactory]:
    """همه‌ی کارخانه‌های فعال (برای پردازش بازدهی توسط زمان‌بند)."""
    result = await session.execute(
        select(MilitaryFactory).where(MilitaryFactory.active.is_(True))
    )
    return list(result.scalars().all())


def is_due(factory: MilitaryFactory, now: datetime | None = None) -> bool:
    """آیا زمان بازدهی این کارخانه فرارسیده است؟"""
    now = now or datetime.now(timezone.utc)
    last = factory.last_yield_at
    # مقاوم‌سازی (v1.10.5): اگر زمان آخرین بازدهی نامشخص بود، سررسیده فرض می‌شود.
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    elapsed_h = (now - last).total_seconds() / 3600
    return elapsed_h >= factory.yield_interval_h
