"""لایه‌ی دسترسی داده برای عملیات نظامی (v1.10.6)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...enums import OperationStatus, OperationType
from ..models.operation import Operation

# وضعیت‌هایی که یک عملیات را «فعال» می‌کنند (هنوز تمام نشده)
_LIVE_STATUSES = (
    OperationStatus.PENDING_OWNER.value,
    OperationStatus.APPROVED.value,
    OperationStatus.IN_PROGRESS.value,
)

# وضعیت‌هایی که در سقف ۲۴ساعته شمرده می‌شوند (رد‌شده‌ها شمرده نمی‌شوند)
_COUNTED_STATUSES = (
    OperationStatus.PENDING_OWNER.value,
    OperationStatus.APPROVED.value,
    OperationStatus.IN_PROGRESS.value,
    OperationStatus.RESOLVED.value,
    OperationStatus.FAILED.value,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_operation(session: AsyncSession, operation: Operation) -> Operation:
    """ثبت یک عملیات جدید."""
    session.add(operation)
    await session.flush()
    return operation


async def get_operation(session: AsyncSession, operation_id: int) -> Operation | None:
    """دریافت یک عملیات با شناسه."""
    result = await session.execute(select(Operation).where(Operation.id == operation_id))
    return result.scalar_one_or_none()


async def count_in_window(
    session: AsyncSession,
    attacker_id: int,
    window_hours: int,
    *,
    exempt_types: Sequence[str] = (),
) -> int:
    """
    شمارش عملیات‌های یک کشور در پنجره‌ی زمانی اخیر (برای سقف عملیات).
    انواع معاف (گشت/رزمایش) و عملیات‌های ردشده شمرده نمی‌شوند.
    """
    since = _utcnow() - timedelta(hours=window_hours)
    stmt = select(func.count(Operation.id)).where(
        Operation.attacker_country_id == attacker_id,
        Operation.created_at >= since,
        Operation.status.in_(_COUNTED_STATUSES),
    )
    if exempt_types:
        stmt = stmt.where(Operation.operation_type.notin_(list(exempt_types)))
    result = await session.execute(stmt)
    return result.scalar() or 0


async def list_due_phases(session: AsyncSession, now: datetime | None = None) -> Sequence[Operation]:
    """عملیات‌های در حال اجرا که فاز خبری بعدی‌شان سررسید شده است."""
    moment = now or _utcnow()
    stmt = select(Operation).where(
        Operation.status == OperationStatus.IN_PROGRESS.value,
        Operation.next_phase_at.is_not(None),
        Operation.next_phase_at <= moment,
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def list_pending_owner(session: AsyncSession) -> Sequence[Operation]:
    """عملیات‌های در انتظار تأیید مالک بازی."""
    stmt = (
        select(Operation)
        .where(Operation.status == OperationStatus.PENDING_OWNER.value)
        .order_by(Operation.created_at)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def list_by_status(
    session: AsyncSession, status: str, *, limit: int = 30
) -> Sequence[Operation]:
    """عملیات‌های یک وضعیت مشخص (برای پنل مدیریت)، جدیدترین اول."""
    stmt = (
        select(Operation)
        .where(Operation.status == status)
        .order_by(Operation.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def list_for_country(
    session: AsyncSession, country_id: int, *, limit: int = 15
) -> Sequence[Operation]:
    """تاریخچه‌ی عملیات یک کشور (چه مهاجم چه مدافع)، جدیدترین اول."""
    stmt = (
        select(Operation)
        .where(
            or_(
                Operation.attacker_country_id == country_id,
                Operation.defender_country_id == country_id,
            )
        )
        .order_by(Operation.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def has_live_operation(
    session: AsyncSession, attacker_id: int, operation_type: OperationType | None = None
) -> bool:
    """آیا کشور عملیات در جریان (تأییدنشده یا در حال اجرا) دارد؟"""
    stmt = select(Operation.id).where(
        Operation.attacker_country_id == attacker_id,
        Operation.status.in_(_LIVE_STATUSES),
    )
    if operation_type is not None:
        stmt = stmt.where(Operation.operation_type == operation_type.value)
    result = await session.execute(stmt.limit(1))
    return result.scalar_one_or_none() is not None


async def list_recent_against(
    session: AsyncSession, defender_id: int, hours: int = 24
) -> Sequence[Operation]:
    """عملیات‌های اخیر علیه یک کشور (برای گزارش تهدید)."""
    since = _utcnow() - timedelta(hours=hours)
    stmt = (
        select(Operation)
        .where(
            Operation.defender_country_id == defender_id,
            Operation.created_at >= since,
            Operation.status.in_(_COUNTED_STATUSES),
        )
        .order_by(Operation.created_at.desc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()
