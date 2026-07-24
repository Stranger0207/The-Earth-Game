"""لایه‌ی دسترسی داده برای ماهواره‌های فضایی."""

from __future__ import annotations

from typing import Sequence
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.satellite import Satellite


async def create_satellite(session: AsyncSession, satellite: Satellite) -> Satellite:
    """ثبت ماهواره جدید."""
    session.add(satellite)
    await session.flush()
    return satellite


async def get_satellite(session: AsyncSession, sat_id: int) -> Satellite | None:
    """دریافت ماهواره با شناسه."""
    stmt = select(Satellite).where(Satellite.id == sat_id)
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def list_satellites_by_country(
    session: AsyncSession, country_id: int
) -> Sequence[Satellite]:
    """فهرست تمام ماهواره‌های پرتاب‌شده توسط یک کشور."""
    stmt = (
        select(Satellite)
        .where(Satellite.country_id == country_id)
        .order_by(Satellite.id.desc())
    )
    res = await session.execute(stmt)
    return res.scalars().all()


async def list_active_orbit_satellites(
    session: AsyncSession, country_id: int
) -> Sequence[Satellite]:
    """فهرست ماهواره‌های فعال در مدار یک کشور."""
    stmt = (
        select(Satellite)
        .where(
            Satellite.country_id == country_id,
            Satellite.status == "in_orbit",
        )
        .order_by(Satellite.id.desc())
    )
    res = await session.execute(stmt)
    return res.scalars().all()


async def list_pending_launch_satellites(session: AsyncSession) -> Sequence[Satellite]:
    """فهرست ماهواره‌هایی که در حال طی مراحل پرتاب هستند."""
    stmt = select(Satellite).where(Satellite.status == "launching")
    res = await session.execute(stmt)
    return res.scalars().all()


async def count_successful_launches(session: AsyncSession, country_id: int) -> int:
    """تعداد پرتاب‌های موفق قبلی کشور."""
    stmt = select(func.count(Satellite.id)).where(
        Satellite.country_id == country_id,
        Satellite.status.in_(["in_orbit", "expired"]),
    )
    res = await session.execute(stmt)
    return res.scalar() or 0
