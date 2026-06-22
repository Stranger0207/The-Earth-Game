"""توابع دسترسی داده برای ذخایر."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...enums import ResourceType
from ..models import Reserve


async def get_reserve(
    session: AsyncSession, country_id: int, resource: ResourceType | str
) -> Reserve | None:
    """دریافت ردیف ذخیره‌ی یک منبع خاص برای یک کشور."""
    resource_value = resource.value if isinstance(resource, ResourceType) else resource
    result = await session.execute(
        select(Reserve).where(
            Reserve.country_id == country_id, Reserve.resource == resource_value
        )
    )
    return result.scalar_one_or_none()


async def list_reserves(session: AsyncSession, country_id: int) -> list[Reserve]:
    """فهرست همه‌ی ذخایر یک کشور."""
    result = await session.execute(
        select(Reserve).where(Reserve.country_id == country_id)
    )
    return list(result.scalars().all())


async def add_amount(
    session: AsyncSession,
    country_id: int,
    resource: ResourceType | str,
    delta: float,
) -> Reserve | None:
    """افزایش/کاهش مقدار یک ذخیره (delta می‌تواند منفی باشد). مقدار زیر صفر نمی‌رود."""
    reserve = await get_reserve(session, country_id, resource)
    if reserve is None:
        return None
    reserve.amount = max(0.0, reserve.amount + delta)
    return reserve


async def has_enough(
    session: AsyncSession,
    country_id: int,
    resource: ResourceType | str,
    needed: float,
) -> bool:
    """بررسی کافی‌بودن موجودی یک منبع."""
    reserve = await get_reserve(session, country_id, resource)
    return reserve is not None and reserve.amount >= needed


async def ensure_reserve(
    session: AsyncSession,
    country_id: int,
    resource: ResourceType | str,
) -> Reserve:
    """در صورت نبودِ ردیف ذخیره، آن را با مقدار صفر می‌سازد."""
    reserve = await get_reserve(session, country_id, resource)
    if reserve is None:
        resource_value = (
            resource.value if isinstance(resource, ResourceType) else resource
        )
        reserve = Reserve(
            country_id=country_id, resource=resource_value, amount=0.0
        )
        session.add(reserve)
        await session.flush()
    return reserve
