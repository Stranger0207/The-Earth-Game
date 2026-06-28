"""توابع دسترسی داده برای تأسیسات."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Facility


async def add_facility(session: AsyncSession, facility: Facility) -> Facility:
    """افزودن یک تأسیسات جدید."""
    session.add(facility)
    await session.flush()
    return facility


async def list_facilities(
    session: AsyncSession, country_id: int
) -> list[Facility]:
    """فهرست تأسیسات یک کشور."""
    result = await session.execute(
        select(Facility).where(Facility.country_id == country_id)
    )
    return list(result.scalars().all())


async def count_builds_since(
    session: AsyncSession, country_id: int, since: datetime
) -> int:
    """تعداد تأسیسات + کارخانه‌های نظامی ساخته‌شده توسط یک کشور از زمان `since` (v1.9)."""
    from sqlalchemy import func

    from ..models import MilitaryFactory

    fac = await session.execute(
        select(func.count()).select_from(Facility).where(
            Facility.country_id == country_id, Facility.created_at >= since
        )
    )
    mf = await session.execute(
        select(func.count()).select_from(MilitaryFactory).where(
            MilitaryFactory.country_id == country_id, MilitaryFactory.created_at >= since
        )
    )
    return (fac.scalar() or 0) + (mf.scalar() or 0)


async def count_facilities_by_types_since(
    session: AsyncSession, country_id: int, types, since: datetime
) -> int:
    """تعداد تأسیسات یک کشور از نوع‌(های) مشخص که از زمان `since` ساخته شده‌اند (v1.9)."""
    from sqlalchemy import func

    # پشتیبانی از FacilityType یا رشته
    type_values = [getattr(t, "value", t) for t in types]
    res = await session.execute(
        select(func.count()).select_from(Facility).where(
            Facility.country_id == country_id,
            Facility.created_at >= since,
            Facility.type.in_(type_values),
        )
    )
    return res.scalar() or 0


async def count_mil_factories_since(
    session: AsyncSession, country_id: int, since: datetime
) -> int:
    """تعداد کارخانه‌های نظامی ساخته‌شده توسط یک کشور از زمان `since` (v1.9)."""
    from sqlalchemy import func

    from ..models import MilitaryFactory

    res = await session.execute(
        select(func.count()).select_from(MilitaryFactory).where(
            MilitaryFactory.country_id == country_id,
            MilitaryFactory.created_at >= since,
        )
    )
    return res.scalar() or 0


async def all_active_facilities(session: AsyncSession) -> list[Facility]:
    """همه‌ی تأسیسات فعال (برای پردازش بازدهی توسط زمان‌بند)."""
    result = await session.execute(
        select(Facility).where(Facility.active.is_(True))
    )
    return list(result.scalars().all())


async def count_facilities(session: AsyncSession, country_id: int) -> int:
    """تعداد تأسیسات یک کشور."""
    facilities = await list_facilities(session, country_id)
    return len(facilities)


def is_due(facility: Facility, now: datetime | None = None) -> bool:
    """آیا زمان بازدهی این تأسیسات فرارسیده است؟"""
    now = now or datetime.now(timezone.utc)
    last = facility.last_yield_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    elapsed_h = (now - last).total_seconds() / 3600
    return elapsed_h >= facility.yield_interval_h
