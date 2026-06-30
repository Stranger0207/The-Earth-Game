"""توابع دسترسی داده برای استقرار نیرو (v1.11)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Deployment


async def add_deployment(session: AsyncSession, dep: Deployment) -> Deployment:
    session.add(dep)
    await session.flush()
    return dep


async def list_active(session: AsyncSession, country_id: int) -> list[Deployment]:
    """فهرست گروه‌های نیروی مستقرِ فعالِ یک کشور (جدیدترین اول)."""
    result = await session.execute(
        select(Deployment)
        .where(Deployment.country_id == country_id, Deployment.active.is_(True))
        .order_by(Deployment.id.desc())
    )
    return list(result.scalars().all())


async def get(session: AsyncSession, dep_id: int) -> Deployment | None:
    return await session.get(Deployment, dep_id)


async def remove(session: AsyncSession, dep_id: int) -> bool:
    """حذف یک گروه نیرو (بازگشت True اگر یافت و حذف شد)."""
    dep = await session.get(Deployment, dep_id)
    if dep is None:
        return False
    await session.delete(dep)
    return True
