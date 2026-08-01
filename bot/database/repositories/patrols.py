"""لایه‌ی دسترسی داده برای گشت‌های دفاعی (v1.10.6)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...enums import PatrolType
from ..models.patrol import Patrol


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def add_patrol(session: AsyncSession, patrol: Patrol) -> Patrol:
    """ثبت یک گشت جدید."""
    session.add(patrol)
    await session.flush()
    return patrol


async def get_patrol(session: AsyncSession, patrol_id: int) -> Patrol | None:
    """دریافت یک گشت با شناسه."""
    result = await session.execute(select(Patrol).where(Patrol.id == patrol_id))
    return result.scalar_one_or_none()


async def list_active(session: AsyncSession, country_id: int) -> Sequence[Patrol]:
    """گشت‌های فعال یک کشور."""
    stmt = (
        select(Patrol)
        .where(Patrol.country_id == country_id, Patrol.is_active == True)  # noqa: E712
        .order_by(Patrol.started_at.desc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def count_active(session: AsyncSession, country_id: int) -> int:
    """تعداد گشت‌های فعال یک کشور (برای سقف هم‌زمانی)."""
    stmt = select(func.count(Patrol.id)).where(
        Patrol.country_id == country_id,
        Patrol.is_active == True,  # noqa: E712
    )
    result = await session.execute(stmt)
    return result.scalar() or 0


async def has_active_of_type(
    session: AsyncSession, country_id: int, patrol_type: PatrolType
) -> bool:
    """آیا کشور گشت فعالی از این نوع دارد؟ (برای بونوس پدافند)"""
    stmt = select(Patrol.id).where(
        Patrol.country_id == country_id,
        Patrol.patrol_type == patrol_type.value,
        Patrol.is_active == True,  # noqa: E712
    )
    result = await session.execute(stmt.limit(1))
    return result.scalar_one_or_none() is not None


async def active_types(session: AsyncSession, country_id: int) -> set[str]:
    """مجموعه‌ی انواع گشت فعال یک کشور (یک کوئری به‌جای چند بار پرسیدن)."""
    stmt = select(Patrol.patrol_type).where(
        Patrol.country_id == country_id,
        Patrol.is_active == True,  # noqa: E712
    )
    result = await session.execute(stmt)
    return set(result.scalars().all())


async def list_expired(session: AsyncSession, now: datetime | None = None) -> Sequence[Patrol]:
    """گشت‌های فعالی که زمانشان تمام شده (برای زمان‌بند)."""
    moment = now or _utcnow()
    stmt = select(Patrol).where(
        Patrol.is_active == True,  # noqa: E712
        Patrol.ends_at.is_not(None),
        Patrol.ends_at <= moment,
    )
    result = await session.execute(stmt)
    return result.scalars().all()
