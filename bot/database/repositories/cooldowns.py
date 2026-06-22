"""توابع دسترسی داده برای کول‌داون‌ها (محدودیت‌های زمانی)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Cooldown


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def get_cooldown(
    session: AsyncSession, country_id: int, action_type: str
) -> Cooldown | None:
    """دریافت رکورد کول‌داون یک کنش برای یک کشور."""
    result = await session.execute(
        select(Cooldown).where(
            Cooldown.country_id == country_id,
            Cooldown.action_type == action_type,
        )
    )
    return result.scalar_one_or_none()


async def remaining_seconds(
    session: AsyncSession, country_id: int, action_type: str, cooldown_hours: int
) -> float:
    """
    چند ثانیه تا پایان کول‌داون باقی مانده است؟
    صفر یعنی کنش مجاز است.
    """
    cd = await get_cooldown(session, country_id, action_type)
    if cd is None:
        return 0.0
    last = cd.last_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    ready_at = last + timedelta(hours=cooldown_hours)
    remaining = (ready_at - _utcnow()).total_seconds()
    return max(0.0, remaining)


async def touch(
    session: AsyncSession, country_id: int, action_type: str
) -> None:
    """ثبت زمان فعلی به‌عنوان آخرین انجام کنش (شروع کول‌داون)."""
    cd = await get_cooldown(session, country_id, action_type)
    if cd is None:
        cd = Cooldown(country_id=country_id, action_type=action_type, last_at=_utcnow())
        session.add(cd)
    else:
        cd.last_at = _utcnow()
