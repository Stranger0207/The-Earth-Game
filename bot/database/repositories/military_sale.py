"""توابع دسترسی داده برای فروش تجهیزات نظامی (v1.7)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...enums import TradeStatus
from ..models import MilitarySale


async def add_sale(session: AsyncSession, sale: MilitarySale) -> MilitarySale:
    session.add(sale)
    await session.flush()
    return sale


async def get_sale(session: AsyncSession, sale_id: int) -> MilitarySale | None:
    return await session.get(MilitarySale, sale_id)


async def list_in_transit(session: AsyncSession) -> list[MilitarySale]:
    """محموله‌های نظامی در حال حمل (برای پردازش رسیدن توسط زمان‌بند)."""
    result = await session.execute(
        select(MilitarySale).where(MilitarySale.status == TradeStatus.IN_TRANSIT)
    )
    return list(result.scalars().all())
