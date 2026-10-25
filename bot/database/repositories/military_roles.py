"""توابع دسترسی داده (CRUD) برای رول‌ها و عملیات‌های نظامی."""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import func, select
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


async def count_roles_by_attacker_since(
    session: AsyncSession,
    attacker_country_id: int,
    since_dt: datetime,
    valid_statuses: list[str] | None = None,
) -> int:
    """
    شمارش عملیات‌های نظامی ثبت‌شده توسط مهاجم در بازه زمانی مشخص.
    پیش‌نویس‌ها (DRAFT) و لغوشده‌ها (CANCELLED) شمارش نمی‌شوند.
    """
    if valid_statuses is None:
        valid_statuses = [
            MilitaryRoleStatus.PENDING_REVIEW.value,
            MilitaryRoleStatus.COMPLETED.value,
        ]
    q = select(func.count(MilitaryRole.id)).where(
        MilitaryRole.attacker_country_id == attacker_country_id,
        MilitaryRole.created_at >= since_dt,
        MilitaryRole.status.in_(valid_statuses),
    )
    res = await session.execute(q)
    return res.scalar_one() or 0


async def get_earliest_role_since(
    session: AsyncSession,
    attacker_country_id: int,
    since_dt: datetime,
    valid_statuses: list[str] | None = None,
) -> MilitaryRole | None:
    """قدیمی‌ترین رول نظامی معتبر در پنجره زمانی جهت محاسبه زمان آزادسازی سهمیه بعدی."""
    if valid_statuses is None:
        valid_statuses = [
            MilitaryRoleStatus.PENDING_REVIEW.value,
            MilitaryRoleStatus.COMPLETED.value,
        ]
    q = (
        select(MilitaryRole)
        .where(
            MilitaryRole.attacker_country_id == attacker_country_id,
            MilitaryRole.created_at >= since_dt,
            MilitaryRole.status.in_(valid_statuses),
        )
        .order_by(MilitaryRole.created_at.asc())
        .limit(1)
    )
    res = await session.execute(q)
    return res.scalars().first()
