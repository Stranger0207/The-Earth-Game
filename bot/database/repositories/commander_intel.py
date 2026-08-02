"""لایه‌ی دسترسی داده برای اطلاعات جاسوسی روی فرماندهان (v1.10.7)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.commander_intel import CommanderIntel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def add_intel(session: AsyncSession, intel: CommanderIntel) -> CommanderIntel:
    """ثبت اطلاعات جاسوسی جدید."""
    session.add(intel)
    await session.flush()
    return intel


async def get_valid_intel(
    session: AsyncSession, spy_country_id: int, commander_id: int
) -> CommanderIntel | None:
    """
    معتبرترین اطلاعات یک کشور روی یک فرمانده مشخص.
    اطلاعات منقضی‌شده برگردانده نمی‌شود.
    """
    now = _utcnow()
    stmt = (
        select(CommanderIntel)
        .where(
            CommanderIntel.spy_country_id == spy_country_id,
            CommanderIntel.commander_id == commander_id,
            CommanderIntel.expires_at.is_not(None),
            CommanderIntel.expires_at > now,
        )
        .order_by(CommanderIntel.quality.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_valid_for_target(
    session: AsyncSession, spy_country_id: int, target_country_id: int
) -> Sequence[CommanderIntel]:
    """همه‌ی اطلاعات معتبر یک کشور روی فرماندهان یک کشور هدف."""
    now = _utcnow()
    stmt = (
        select(CommanderIntel)
        .where(
            CommanderIntel.spy_country_id == spy_country_id,
            CommanderIntel.target_country_id == target_country_id,
            CommanderIntel.expires_at.is_not(None),
            CommanderIntel.expires_at > now,
        )
        .order_by(CommanderIntel.gathered_at.desc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def list_all_valid(
    session: AsyncSession, spy_country_id: int
) -> Sequence[CommanderIntel]:
    """همه‌ی اطلاعات معتبر یک کشور (برای پنل «پرونده‌های اطلاعاتی»)."""
    now = _utcnow()
    stmt = (
        select(CommanderIntel)
        .where(
            CommanderIntel.spy_country_id == spy_country_id,
            CommanderIntel.expires_at.is_not(None),
            CommanderIntel.expires_at > now,
        )
        .order_by(CommanderIntel.gathered_at.desc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def count_recent_operations(
    session: AsyncSession, spy_country_id: int, hours: int
) -> int:
    """تعداد عملیات جاسوسی اخیر یک کشور (برای کول‌داون)."""
    since = _utcnow() - timedelta(hours=hours)
    stmt = select(func.count(CommanderIntel.id)).where(
        CommanderIntel.spy_country_id == spy_country_id,
        CommanderIntel.gathered_at >= since,
    )
    result = await session.execute(stmt)
    return result.scalar() or 0


async def consume_intel(session: AsyncSession, intel: CommanderIntel) -> None:
    """
    مصرف اطلاعات پس از استفاده در ترور.
    اطلاعات پس از عملیات بی‌ارزش می‌شود (هدف جابه‌جا می‌شود).
    """
    await session.delete(intel)
    await session.flush()


async def purge_expired(session: AsyncSession) -> int:
    """پاک‌سازی اطلاعات منقضی‌شده (برای زمان‌بند)."""
    now = _utcnow()
    result = await session.execute(
        delete(CommanderIntel).where(
            CommanderIntel.expires_at.is_not(None),
            CommanderIntel.expires_at <= now,
        )
    )
    return result.rowcount or 0


async def purge_for_commander(session: AsyncSession, commander_id: int) -> int:
    """
    پاک‌سازی همه‌ی اطلاعات روی یک فرمانده.
    وقتی فرمانده ترور می‌شود، اطلاعات بقیه‌ی کشورها هم بی‌اعتبار می‌شود.
    """
    result = await session.execute(
        delete(CommanderIntel).where(CommanderIntel.commander_id == commander_id)
    )
    return result.rowcount or 0
