"""لایه‌ی دسترسی داده برای نبردها، حملات و اعلان‌های جنگ (v2.0)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.battle import Battle, WarDeclaration


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def declare_war(
    session: AsyncSession, declarer_id: int, target_id: int
) -> WarDeclaration:
    """اعلام جنگ رسمی علیه یک کشور."""
    decl = WarDeclaration(
        declarer_country_id=declarer_id,
        target_country_id=target_id,
        active=True,
    )
    session.add(decl)
    await session.flush()
    return decl


async def has_active_war_declaration(
    session: AsyncSession, declarer_id: int, target_id: int
) -> bool:
    """بررسی اینکه آیا بین دو کشور وضعیت جنگ فعال وجود دارد یا خیر."""
    stmt = select(WarDeclaration).where(
        WarDeclaration.declarer_country_id == declarer_id,
        WarDeclaration.target_country_id == target_id,
        WarDeclaration.active == True,
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none() is not None


async def count_attacks_in_last_24h(session: AsyncSession, attacker_id: int) -> int:
    """شمارش تعداد حملات انجام‌شده توسط یک کشور در ۲۴ ساعت گذشته."""
    since = _utcnow() - timedelta(hours=24)
    stmt = select(func.count(Battle.id)).where(
        Battle.attacker_country_id == attacker_id,
        Battle.created_at >= since,
        Battle.status != "rejected",
    )
    res = await session.execute(stmt)
    return res.scalar() or 0


async def create_battle(session: AsyncSession, battle: Battle) -> Battle:
    """ثبت نبرد جدید در دیتابیس."""
    session.add(battle)
    await session.flush()
    return battle


async def get_battle(session: AsyncSession, battle_id: int) -> Battle | None:
    """دریافت نبرد با شناسه."""
    stmt = select(Battle).where(Battle.id == battle_id)
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def list_in_progress_battles(session: AsyncSession) -> Sequence[Battle]:
    """فهرست نبردهای در حال اجرا که نیازمند پیشرفت فاز خبری/نتیجه هستند."""
    stmt = select(Battle).where(Battle.status == "in_progress")
    res = await session.execute(stmt)
    return res.scalars().all()
