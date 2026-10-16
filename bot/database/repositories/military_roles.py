"""توابع دسترسی داده (CRUD) برای رول‌ها و عملیات‌های نظامی."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MilitaryRole
from ...enums import MilitaryRoleStatus


async def create_military_role(
    session: AsyncSession, role: MilitaryRole
) -> MilitaryRole:
    """ثبت رول نظامی جدید."""
    session.add(role)
    await session.flush()
    return role


async def get_military_role(
    session: AsyncSession, role_id: int
) -> MilitaryRole | None:
    """دریافت رول نظامی با شناسه یکتا."""
    result = await session.execute(
        select(MilitaryRole).where(MilitaryRole.id == role_id)
    )
    return result.scalar_one_or_none()


async def list_drafts_by_country(
    session: AsyncSession, attacker_country_id: int
) -> list[MilitaryRole]:
    """فهرست پیش‌نویس‌های نظامی یک کشور."""
    result = await session.execute(
        select(MilitaryRole)
        .where(
            MilitaryRole.attacker_country_id == attacker_country_id,
            MilitaryRole.status == MilitaryRoleStatus.DRAFT.value,
        )
        .order_by(MilitaryRole.created_at.desc())
    )
    return list(result.scalars().all())


async def list_active_by_attacker(
    session: AsyncSession, attacker_country_id: int
) -> list[MilitaryRole]:
    """فهرست عملیات‌های در حال اجرای ارسالی توسط کشور مهاجم."""
    result = await session.execute(
        select(MilitaryRole)
        .where(
            MilitaryRole.attacker_country_id == attacker_country_id,
            MilitaryRole.status == MilitaryRoleStatus.PENDING_REVIEW.value,
        )
        .order_by(MilitaryRole.created_at.desc())
    )
    return list(result.scalars().all())


async def list_all_pending(session: AsyncSession) -> list[MilitaryRole]:
    """فهرست تمام عملیات‌های نظامی جاری / باز جهت مدیریت ادمین‌ها."""
    result = await session.execute(
        select(MilitaryRole)
        .where(MilitaryRole.status == MilitaryRoleStatus.PENDING_REVIEW.value)
        .order_by(MilitaryRole.created_at.asc())
    )
    return list(result.scalars().all())


async def delete_military_role(
    session: AsyncSession, role: MilitaryRole
) -> None:
    """حذف رول نظامی از دیتابیس."""
    await session.delete(role)
    await session.flush()
