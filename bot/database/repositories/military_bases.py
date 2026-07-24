"""لایه‌ی دسترسی داده برای پایگاه‌های نظامی و تجهیزات آن‌ها."""

from __future__ import annotations

from typing import Sequence
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models.military_base import BaseEquipment, MilitaryBase


async def create_base(session: AsyncSession, base: MilitaryBase) -> MilitaryBase:
    """ایجاد یک پایگاه جدید."""
    session.add(base)
    await session.flush()
    return base


async def get_base(session: AsyncSession, base_id: int) -> MilitaryBase | None:
    """دریافت پایگاه با شناسه به همراه تجهیزات مستقر."""
    stmt = (
        select(MilitaryBase)
        .options(selectinload(MilitaryBase.equipments))
        .where(MilitaryBase.id == base_id)
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def list_bases_by_owner(
    session: AsyncSession, owner_country_id: int
) -> Sequence[MilitaryBase]:
    """فهرست تمام پایگاه‌های تحت مالکیت یک کشور (داخلی + خارجی)."""
    stmt = (
        select(MilitaryBase)
        .options(selectinload(MilitaryBase.equipments))
        .where(
            MilitaryBase.owner_country_id == owner_country_id,
            MilitaryBase.status == "active",
        )
        .order_by(MilitaryBase.id.desc())
    )
    res = await session.execute(stmt)
    return res.scalars().all()


async def list_bases_by_host(
    session: AsyncSession, host_country_id: int
) -> Sequence[MilitaryBase]:
    """فهرست تمام پایگاه‌های فعال مستقر در یک کشور میزبان."""
    stmt = (
        select(MilitaryBase)
        .options(selectinload(MilitaryBase.equipments))
        .where(
            MilitaryBase.host_country_id == host_country_id,
            MilitaryBase.status == "active",
        )
        .order_by(MilitaryBase.id.desc())
    )
    res = await session.execute(stmt)
    return res.scalars().all()


async def count_foreign_bases_by_owner(
    session: AsyncSession, owner_country_id: int
) -> int:
    """شمارش پایگاه‌های خارجی یک کشور (پایگاه‌هایی که کشور خودش میزبانش نیست)."""
    stmt = select(func.count(MilitaryBase.id)).where(
        MilitaryBase.owner_country_id == owner_country_id,
        MilitaryBase.host_country_id != owner_country_id,
        MilitaryBase.status == "active",
    )
    res = await session.execute(stmt)
    return res.scalar() or 0


async def count_foreign_bases_in_host(
    session: AsyncSession, host_country_id: int
) -> int:
    """شمارش پایگاه‌های کشورهای بیگانه مستقر در خاک کشور میزبان."""
    stmt = select(func.count(MilitaryBase.id)).where(
        MilitaryBase.host_country_id == host_country_id,
        MilitaryBase.owner_country_id != host_country_id,
        MilitaryBase.status == "active",
    )
    res = await session.execute(stmt)
    return res.scalar() or 0


async def get_base_equipment(
    session: AsyncSession, base_id: int, asset_name: str
) -> BaseEquipment | None:
    """دریافت یک قلم تجهیزات مشخص در پایگاه."""
    stmt = select(BaseEquipment).where(
        BaseEquipment.base_id == base_id,
        BaseEquipment.asset_name == asset_name,
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def add_base_equipment(
    session: AsyncSession, base_id: int, asset_name: str, branch: str, count: int
) -> BaseEquipment:
    """افزایش موجودی تجهیزات در پایگاه (اگر وجود نداشت، ایجاد می‌شود)."""
    eq = await get_base_equipment(session, base_id, asset_name)
    if eq:
        eq.count += count
    else:
        eq = BaseEquipment(
            base_id=base_id, asset_name=asset_name, branch=branch, count=count
        )
        session.add(eq)
    await session.flush()
    return eq


async def reduce_base_equipment(
    session: AsyncSession, base_id: int, asset_name: str, count: int
) -> bool:
    """کاهش موجودی تجهیزات در پایگاه."""
    eq = await get_base_equipment(session, base_id, asset_name)
    if not eq or eq.count < count:
        return False
    eq.count -= count
    if eq.count <= 0:
        await session.delete(eq)
    await session.flush()
    return True


async def update_base_status(
    session: AsyncSession, base_id: int, status: str
) -> None:
    """تغییر وضعیت پایگاه (مثلاً active, destroyed, pending)."""
    base = await get_base(session, base_id)
    if base:
        base.status = status
        await session.flush()


async def delete_base(session: AsyncSession, base_id: int) -> None:
    """حذف کامل یک پایگاه."""
    base = await get_base(session, base_id)
    if base:
        await session.delete(base)
        await session.flush()
