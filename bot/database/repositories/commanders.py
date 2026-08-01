"""لایه‌ی دسترسی داده برای فرماندهان نظامی (v1.10.6)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...enums import CommanderRole
from ..models.commander import Commander


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def add_commander(session: AsyncSession, commander: Commander) -> Commander:
    """ثبت یک فرمانده جدید."""
    session.add(commander)
    await session.flush()
    return commander


async def get_commander(session: AsyncSession, commander_id: int) -> Commander | None:
    """دریافت یک فرمانده با شناسه."""
    result = await session.execute(select(Commander).where(Commander.id == commander_id))
    return result.scalar_one_or_none()


async def list_commanders(session: AsyncSession, country_id: int) -> Sequence[Commander]:
    """همه‌ی فرماندهان یک کشور (زنده و ترورشده)."""
    stmt = (
        select(Commander)
        .where(Commander.country_id == country_id)
        .order_by(Commander.role, Commander.id)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def list_alive(session: AsyncSession, country_id: int) -> Sequence[Commander]:
    """فرماندهان زنده‌ی یک کشور (اهداف ممکن ترور و منبع بونوس)."""
    stmt = (
        select(Commander)
        .where(Commander.country_id == country_id, Commander.is_alive == True)  # noqa: E712
        .order_by(Commander.role, Commander.id)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def bonus_for_role(
    session: AsyncSession, country_id: int, role: CommanderRole
) -> float:
    """
    مجموع بونوس درصدیِ فرماندهان زنده‌ی یک تخصص.
    فرمانده‌ی ترورشده تا انتصاب جانشین بونوسی نمی‌دهد.
    """
    stmt = select(func.coalesce(func.sum(Commander.bonus_pct), 0.0)).where(
        Commander.country_id == country_id,
        Commander.role == role.value,
        Commander.is_alive == True,  # noqa: E712
    )
    result = await session.execute(stmt)
    return float(result.scalar() or 0.0)


async def count_for_country(session: AsyncSession, country_id: int) -> int:
    """تعداد کل فرماندهان یک کشور (برای seed بی‌خطر و تکرارپذیر)."""
    stmt = select(func.count(Commander.id)).where(Commander.country_id == country_id)
    result = await session.execute(stmt)
    return result.scalar() or 0


async def kill_commander(
    session: AsyncSession, commander: Commander, replacement_at: datetime
) -> None:
    """ثبت ترور موفق یک فرمانده و زمان انتصاب جانشین."""
    commander.is_alive = False
    commander.killed_at = _utcnow()
    commander.replacement_at = replacement_at
    await session.flush()


async def list_due_replacements(
    session: AsyncSession, now: datetime | None = None
) -> Sequence[Commander]:
    """فرماندهانی که زمان انتصاب جانشین‌شان رسیده (برای زمان‌بند)."""
    moment = now or _utcnow()
    stmt = select(Commander).where(
        Commander.is_alive == False,  # noqa: E712
        Commander.replacement_at.is_not(None),
        Commander.replacement_at <= moment,
    )
    result = await session.execute(stmt)
    return result.scalars().all()
