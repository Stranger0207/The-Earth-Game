"""توابع دسترسی داده برای فروش/محموله‌های ذخایر."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...enums import TradeStatus
from ..models import ResourceSale


async def add_sale(session: AsyncSession, sale: ResourceSale) -> ResourceSale:
    session.add(sale)
    await session.flush()
    return sale


async def get_sale(session: AsyncSession, sale_id: int) -> ResourceSale | None:
    return await session.get(ResourceSale, sale_id)


async def list_in_transit(session: AsyncSession) -> list[ResourceSale]:
    """محموله‌های در حال حمل (برای پردازش رسیدن توسط زمان‌بند)."""
    result = await session.execute(
        select(ResourceSale).where(ResourceSale.status == TradeStatus.IN_TRANSIT)
    )
    return list(result.scalars().all())


async def set_status(
    session: AsyncSession, sale_id: int, status: TradeStatus
) -> ResourceSale | None:
    sale = await session.get(ResourceSale, sale_id)
    if sale is not None:
        sale.status = status
    return sale
