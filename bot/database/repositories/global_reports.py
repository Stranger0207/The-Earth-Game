"""توابع دسترسی داده برای گزارش‌های تراز کلان جهانی و اسنپشات‌ها."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.global_report import GlobalReport


async def add_report(session: AsyncSession, report: GlobalReport) -> GlobalReport:
    """افزودن و ذخیره‌سازی یک گزارش تراز جهانی تازه در دیتابیس."""
    session.add(report)
    await session.flush()
    return report


async def get_report_by_id(session: AsyncSession, report_id: int) -> GlobalReport | None:
    """واکشی یک گزارش با شناسه عددی."""
    return await session.get(GlobalReport, report_id)


async def get_last_report(
    session: AsyncSession, period_hours: int | None = None
) -> GlobalReport | None:
    """
    دریافت آخرین گزارش ثبت‌شده در سیستم.
    در صورت مشخص بودن period_hours، آخرین گزارش مربوط به همان بازه را برمی‌گرداند.
    """
    stmt = select(GlobalReport).order_by(desc(GlobalReport.generated_at), desc(GlobalReport.id))
    if period_hours is not None:
        stmt = stmt.where(GlobalReport.period_hours == period_hours)
    result = await session.execute(stmt.limit(1))
    return result.scalars().first()


async def get_report_near(
    session: AsyncSession, target_time: datetime, period_hours: int | None = None
) -> GlobalReport | None:
    """
    دریافت نزدیک‌ترین گزارش ثبت‌شده به یک زمان هدف (به‌ویژه پیش یا همزمان با target_time).
    جهت مقایسه اسنپشات اول دوره با دوره قبل (Snapshot Diff).
    """
    stmt = (
        select(GlobalReport)
        .where(GlobalReport.generated_at <= target_time)
        .order_by(desc(GlobalReport.generated_at))
    )
    if period_hours is not None:
        stmt = stmt.where(GlobalReport.period_hours == period_hours)
    result = await session.execute(stmt.limit(1))
    rep = result.scalars().first()
    if rep is not None:
        return rep

    # اگر گزارشی قبل از زمان هدف نبود، اولین گزارش بعد از آن را می‌گیرد
    stmt_after = (
        select(GlobalReport)
        .where(GlobalReport.generated_at >= target_time)
        .order_by(GlobalReport.generated_at)
    )
    if period_hours is not None:
        stmt_after = stmt_after.where(GlobalReport.period_hours == period_hours)
    result_after = await session.execute(stmt_after.limit(1))
    return result_after.scalars().first()


async def list_recent_reports(
    session: AsyncSession, limit: int = 10, period_hours: int | None = None
) -> list[GlobalReport]:
    """فهرست آخرین گزارش‌های ثبت‌شده."""
    stmt = select(GlobalReport).order_by(desc(GlobalReport.generated_at))
    if period_hours is not None:
        stmt = stmt.where(GlobalReport.period_hours == period_hours)
    result = await session.execute(stmt.limit(limit))
    return list(result.scalars().all())
