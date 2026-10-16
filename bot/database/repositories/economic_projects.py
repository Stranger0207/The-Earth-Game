"""توابع دسترسی داده (CRUD) برای پروژه‌ها و رول‌های اقتصادی (آپدیت شماره ۹)."""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import EconomicProject
from ...enums import EconomicProjectStatus


async def create_project(session: AsyncSession, project: EconomicProject) -> EconomicProject:
    """ایجاد و ذخیره یک پروژه اقتصادی تازه."""
    session.add(project)
    await session.flush()
    return project


async def get_project(session: AsyncSession, project_id: int) -> EconomicProject | None:
    """دریافت پروژه بر اساس شناسه یکتا."""
    result = await session.execute(
        select(EconomicProject).where(EconomicProject.id == project_id)
    )
    return result.scalar_one_or_none()


async def get_project_by_admin_message(
    session: AsyncSession, admin_message_id: int
) -> EconomicProject | None:
    """دریافت پروژه بر اساس شناسه پیام در گروه رول اقتصادی."""
    result = await session.execute(
        select(EconomicProject).where(EconomicProject.admin_message_id == admin_message_id)
    )
    return result.scalar_one_or_none()


async def list_by_country_and_status(
    session: AsyncSession, country_id: int, statuses: list[str]
) -> list[EconomicProject]:
    """دریافت لیست پروژه‌های یک کشور بر اساس وضعیت‌های مشخص."""
    result = await session.execute(
        select(EconomicProject)
        .where(
            EconomicProject.country_id == country_id,
            EconomicProject.status.in_(statuses),
        )
        .order_by(EconomicProject.id.desc())
    )
    return list(result.scalars().all())


async def list_drafts_by_country(
    session: AsyncSession, country_id: int
) -> list[EconomicProject]:
    """لیست پیش‌نویس‌های یک کشور."""
    return await list_by_country_and_status(
        session, country_id, [EconomicProjectStatus.DRAFT.value]
    )


async def list_pending_or_awaiting_by_country(
    session: AsyncSession, country_id: int
) -> list[EconomicProject]:
    """لیست پروژه‌های در حال بررسی مدیریت یا در انتظار افتتاح توسط بازیکن."""
    return await list_by_country_and_status(
        session,
        country_id,
        [
            EconomicProjectStatus.PENDING_REVIEW.value,
            EconomicProjectStatus.APPROVED_AWAITING_LAUNCH.value,
        ],
    )


async def list_active_by_country(
    session: AsyncSession, country_id: int
) -> list[EconomicProject]:
    """لیست پروژه‌های فعال و در حال سوددهی یک کشور."""
    return await list_by_country_and_status(
        session, country_id, [EconomicProjectStatus.ACTIVE.value]
    )


async def list_all_active(session: AsyncSession) -> list[EconomicProject]:
    """دریافت تمام پروژه‌های فعال بازی (برای جاب زمان‌بند یا پنل گاد)."""
    result = await session.execute(
        select(EconomicProject)
        .where(EconomicProject.status == EconomicProjectStatus.ACTIVE.value)
        .order_by(EconomicProject.id.asc())
    )
    return list(result.scalars().all())


async def list_all_by_country(
    session: AsyncSession, country_id: int
) -> list[EconomicProject]:
    """دریافت کلیه پروژه‌های یک کشور فارغ از وضعیت (برای پنل گاد)."""
    result = await session.execute(
        select(EconomicProject)
        .where(EconomicProject.country_id == country_id)
        .order_by(EconomicProject.id.desc())
    )
    return list(result.scalars().all())


async def delete_project(session: AsyncSession, project: EconomicProject) -> None:
    """حذف کامل یک پروژه."""
    await session.delete(project)
    await session.flush()
