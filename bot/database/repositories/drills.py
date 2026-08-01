"""لایه‌ی دسترسی داده برای رزمایش‌های نظامی (v1.10.6)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.drill import Drill


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def add_drill(session: AsyncSession, drill: Drill) -> Drill:
    """ثبت یک رزمایش جدید."""
    session.add(drill)
    await session.flush()
    return drill


async def get_drill(session: AsyncSession, drill_id: int) -> Drill | None:
    """دریافت یک رزمایش با شناسه."""
    result = await session.execute(select(Drill).where(Drill.id == drill_id))
    return result.scalar_one_or_none()


async def list_active(session: AsyncSession, country_id: int) -> Sequence[Drill]:
    """رزمایش‌های در جریان یک کشور (به‌عنوان میزبان یا شریک)."""
    stmt = (
        select(Drill)
        .where(
            or_(Drill.country_id == country_id, Drill.partner_country_id == country_id),
            Drill.is_completed == False,  # noqa: E712
        )
        .order_by(Drill.started_at.desc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def list_due(session: AsyncSession, now: datetime | None = None) -> Sequence[Drill]:
    """
    رزمایش‌هایی که زمانشان تمام شده و باید اثرشان اعمال شود (برای زمان‌بند).
    رزمایش مشترکِ پذیرفته‌نشده نادیده گرفته می‌شود.
    """
    moment = now or _utcnow()
    stmt = select(Drill).where(
        Drill.is_completed == False,  # noqa: E712
        Drill.ends_at.is_not(None),
        Drill.ends_at <= moment,
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def count_since(session: AsyncSession, country_id: int, hours: int) -> int:
    """تعداد رزمایش‌های یک کشور در بازه‌ی اخیر (برای کول‌داون)."""
    since = _utcnow() - timedelta(hours=hours)
    stmt = select(func.count(Drill.id)).where(
        Drill.country_id == country_id,
        Drill.started_at >= since,
    )
    result = await session.execute(stmt)
    return result.scalar() or 0


async def list_pending_invites(session: AsyncSession, partner_id: int) -> Sequence[Drill]:
    """دعوت‌های رزمایش مشترکِ در انتظار پذیرش یک کشور."""
    stmt = (
        select(Drill)
        .where(
            Drill.partner_country_id == partner_id,
            Drill.partner_accepted == False,  # noqa: E712
            Drill.is_completed == False,  # noqa: E712
        )
        .order_by(Drill.started_at.desc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()
