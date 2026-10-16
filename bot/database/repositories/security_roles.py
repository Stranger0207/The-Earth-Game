"""توابع دسترسی داده (CRUD) برای پروژه‌ها و رول‌های امنیتی."""

from __future__ import annotations

from sqlalchemy import delete, distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import SecurityRole
from ...enums import SecurityRoleStatus


async def create_security_role(
    session: AsyncSession, role: SecurityRole
) -> SecurityRole:
    """ثبت پروژه امنیتی جدید."""
    session.add(role)
    await session.flush()
    return role


async def get_security_role(
    session: AsyncSession, role_id: int
) -> SecurityRole | None:
    """دریافت پروژه امنیتی با شناسه یکتا."""
    result = await session.execute(
        select(SecurityRole).where(SecurityRole.id == role_id)
    )
    return result.scalar_one_or_none()


async def list_drafts_by_country(
    session: AsyncSession, country_id: int
) -> list[SecurityRole]:
    """فهرست پیش‌نویس‌های امنیتی یک کشور."""
    result = await session.execute(
        select(SecurityRole)
        .where(
            SecurityRole.country_id == country_id,
            SecurityRole.status == SecurityRoleStatus.DRAFT.value,
        )
        .order_by(SecurityRole.created_at.desc())
    )
    return list(result.scalars().all())


async def list_pending_by_country(
    session: AsyncSession, country_id: int
) -> list[SecurityRole]:
    """فهرست رول‌های امنیتی در انتظار بررسی یک کشور."""
    result = await session.execute(
        select(SecurityRole)
        .where(
            SecurityRole.country_id == country_id,
            SecurityRole.status == SecurityRoleStatus.PENDING_REVIEW.value,
        )
        .order_by(SecurityRole.created_at.desc())
    )
    return list(result.scalars().all())


async def list_approved_by_country(
    session: AsyncSession, country_id: int
) -> list[SecurityRole]:
    """فهرست پروژه‌های امنیتی تاییدشده یک کشور (آرشیو امنیتی)."""
    result = await session.execute(
        select(SecurityRole)
        .where(
            SecurityRole.country_id == country_id,
            SecurityRole.status == SecurityRoleStatus.APPROVED.value,
        )
        .order_by(SecurityRole.created_at.desc())
    )
    return list(result.scalars().all())


async def list_all_pending(session: AsyncSession) -> list[SecurityRole]:
    """فهرست تمام رول‌های امنیتی در صف بررسی مدیریت."""
    result = await session.execute(
        select(SecurityRole)
        .where(SecurityRole.status == SecurityRoleStatus.PENDING_REVIEW.value)
        .order_by(SecurityRole.created_at.asc())
    )
    return list(result.scalars().all())


async def list_country_ids_with_approved_roles(
    session: AsyncSession,
) -> list[int]:
    """شناسه کشورهایی که حداقل یک پروژه امنیتی تاییدشده دارند."""
    result = await session.execute(
        select(distinct(SecurityRole.country_id)).where(
            SecurityRole.status == SecurityRoleStatus.APPROVED.value
        )
    )
    return [row[0] for row in result.all()]


async def delete_security_role(
    session: AsyncSession, role: SecurityRole
) -> None:
    """حذف پروژه امنیتی از دیتابیس."""
    await session.delete(role)
    await session.flush()
