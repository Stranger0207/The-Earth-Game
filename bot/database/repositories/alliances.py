"""توابع دسترسی داده برای اتحادها (v1.9)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Alliance, AllianceMember


async def create_alliance(
    session: AsyncSession, name: str, terms: str, owner_country: int
) -> Alliance:
    """ساخت اتحاد جدید و افزودن کشور سازنده به‌عنوان عضو."""
    alliance = Alliance(name=name, terms=terms, owner_country=owner_country)
    session.add(alliance)
    await session.flush()
    session.add(AllianceMember(alliance_id=alliance.id, country_id=owner_country))
    await session.flush()
    return alliance


async def get_alliance(session: AsyncSession, alliance_id: int) -> Alliance | None:
    return await session.get(Alliance, alliance_id)


async def get_membership(session: AsyncSession, country_id: int) -> AllianceMember | None:
    """عضویت فعال یک کشور در یک اتحاد (هر کشور حداکثر در یک اتحاد)."""
    result = await session.execute(
        select(AllianceMember).where(AllianceMember.country_id == country_id)
    )
    return result.scalars().first()


async def list_members(session: AsyncSession, alliance_id: int) -> list[AllianceMember]:
    result = await session.execute(
        select(AllianceMember).where(AllianceMember.alliance_id == alliance_id)
    )
    return list(result.scalars().all())


async def member_count(session: AsyncSession, alliance_id: int) -> int:
    return len(await list_members(session, alliance_id))


async def add_member(session: AsyncSession, alliance_id: int, country_id: int) -> bool:
    """افزودن عضو اگر قبلاً در هیچ اتحادی نباشد. True اگر افزوده شد."""
    existing = await get_membership(session, country_id)
    if existing is not None:
        return False
    session.add(AllianceMember(alliance_id=alliance_id, country_id=country_id))
    await session.flush()
    return True


async def remove_member(session: AsyncSession, alliance_id: int, country_id: int) -> None:
    member = await session.execute(
        select(AllianceMember).where(
            AllianceMember.alliance_id == alliance_id,
            AllianceMember.country_id == country_id,
        )
    )
    m = member.scalars().first()
    if m is not None:
        await session.delete(m)


async def delete_alliance(session: AsyncSession, alliance_id: int) -> None:
    """حذف اتحاد و همه‌ی اعضای آن (مثلاً وقتی سازنده خارج شود)."""
    for m in await list_members(session, alliance_id):
        await session.delete(m)
    alliance = await session.get(Alliance, alliance_id)
    if alliance is not None:
        await session.delete(alliance)
