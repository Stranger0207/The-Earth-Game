"""توابع دسترسی داده برای تجهیزات نظامی."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MilitaryAsset


async def list_assets(
    session: AsyncSession, country_id: int
) -> list[MilitaryAsset]:
    """فهرست تجهیزات نظامی یک کشور (مرتب بر اساس زیربخش)."""
    result = await session.execute(
        select(MilitaryAsset)
        .where(MilitaryAsset.country_id == country_id)
        .order_by(MilitaryAsset.branch, MilitaryAsset.category, MilitaryAsset.id)
    )
    return list(result.scalars().all())


async def get_asset_by_name(
    session: AsyncSession, country_id: int, name: str
) -> MilitaryAsset | None:
    """یافتن یک قلم تجهیزات بر اساس نام."""
    result = await session.execute(
        select(MilitaryAsset).where(
            MilitaryAsset.country_id == country_id, MilitaryAsset.name == name
        )
    )
    return result.scalar_one_or_none()


async def reduce_count(
    session: AsyncSession, country_id: int, name: str, amount: int
) -> None:
    """کاهش تعداد یک قلم تجهیزات (پس از تلفات حمله). زیر صفر نمی‌رود."""
    asset = await get_asset_by_name(session, country_id, name)
    if asset is not None:
        asset.count = max(0, asset.count - amount)
