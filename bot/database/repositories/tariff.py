"""توابع دسترسی داده برای تعرفه‌های آمریکا (v1.5)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import TariffRate


async def set_tariff(
    session: AsyncSession, target_country: int, percent: float
) -> TariffRate:
    """تعیین یا به‌روزرسانی نرخ تعرفه برای یک کشور. درصد صفر یعنی حذف تعرفه."""
    existing = await get_tariff(session, target_country)
    if percent <= 0:
        if existing is not None:
            await session.delete(existing)
        return existing  # نوع برگشتی صرفاً برای راحتی
    if existing is None:
        existing = TariffRate(target_country=target_country, percent=percent)
        session.add(existing)
        await session.flush()
    else:
        existing.percent = percent
    return existing


async def get_tariff(
    session: AsyncSession, target_country: int
) -> TariffRate | None:
    """دریافت نرخ تعرفه‌ی یک کشور (یا None اگر تعرفه‌ای نداشته باشد)."""
    result = await session.execute(
        select(TariffRate).where(TariffRate.target_country == target_country)
    )
    return result.scalar_one_or_none()


async def list_tariffs(session: AsyncSession) -> list[TariffRate]:
    """فهرست همه‌ی تعرفه‌های فعال."""
    result = await session.execute(select(TariffRate).order_by(TariffRate.percent.desc()))
    return list(result.scalars().all())
