"""توابع دسترسی داده برای کشورها."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import Country


async def get_country(session: AsyncSession, country_id: int) -> Country | None:
    """دریافت کشور بر اساس آی‌دی."""
    return await session.get(Country, country_id)


async def get_country_by_owner(
    session: AsyncSession, owner_user_id: int
) -> Country | None:
    """دریافت کشوری که این کاربر مالک آن است."""
    result = await session.execute(
        select(Country).where(Country.owner_user_id == owner_user_id)
    )
    return result.scalar_one_or_none()


async def get_country_by_name(
    session: AsyncSession, name_en: str
) -> Country | None:
    """دریافت کشور بر اساس نام انگلیسی (یکتا)."""
    result = await session.execute(
        select(Country).where(Country.name_en == name_en)
    )
    return result.scalar_one_or_none()


async def get_country_with_relations(
    session: AsyncSession, country_id: int
) -> Country | None:
    """دریافت کشور به‌همراه ذخایر، تأسیسات و تجهیزات (برای ساخت context کامل)."""
    result = await session.execute(
        select(Country)
        .where(Country.id == country_id)
        .options(
            selectinload(Country.reserves),
            selectinload(Country.facilities),
            selectinload(Country.military_assets),
            selectinload(Country.owner),
        )
    )
    return result.scalar_one_or_none()


async def list_countries(
    session: AsyncSession, only_unclaimed: bool = False
) -> list[Country]:
    """فهرست کشورها؛ در صورت only_unclaimed فقط کشورهای آزاد."""
    stmt = select(Country).order_by(Country.id)
    if only_unclaimed:
        stmt = stmt.where(Country.is_claimed.is_(False))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def assign_owner(
    session: AsyncSession, country_id: int, owner_user_id: int
) -> None:
    """واگذاری مالکیت کشور به یک کاربر (پس از تأیید کشورگیری)."""
    country = await session.get(Country, country_id)
    if country is not None:
        country.owner_user_id = owner_user_id
        country.is_claimed = True


async def release_country(session: AsyncSession, country_id: int) -> None:
    """آزاد کردن یک کشور (حذف مالکیت)."""
    country = await session.get(Country, country_id)
    if country is not None:
        country.owner_user_id = None
        country.is_claimed = False
