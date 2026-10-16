"""لایه‌ی دسترسی داده برای ماهواره‌های فضایی."""

from __future__ import annotations

from typing import Sequence
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.econ_sat_receipt import EconSatReceipt
from ..models.satellite import Satellite


async def create_satellite(session: AsyncSession, satellite: Satellite) -> Satellite:
    """ثبت ماهواره جدید."""
    session.add(satellite)
    await session.flush()
    return satellite


async def get_satellite(session: AsyncSession, sat_id: int) -> Satellite | None:
    """دریافت ماهواره با شناسه."""
    stmt = select(Satellite).where(Satellite.id == sat_id)
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def list_satellites_by_country(
    session: AsyncSession, country_id: int
) -> Sequence[Satellite]:
    """فهرست تمام ماهواره‌های پرتاب‌شده توسط یک کشور."""
    stmt = (
        select(Satellite)
        .where(Satellite.country_id == country_id)
        .order_by(Satellite.id.desc())
    )
    res = await session.execute(stmt)
    return res.scalars().all()


async def list_active_orbit_satellites(
    session: AsyncSession, country_id: int
) -> Sequence[Satellite]:
    """فهرست ماهواره‌های فعال در مدار یک کشور."""
    stmt = (
        select(Satellite)
        .where(
            Satellite.country_id == country_id,
            Satellite.status == "in_orbit",
        )
        .order_by(Satellite.id.desc())
    )
    res = await session.execute(stmt)
    return res.scalars().all()


async def list_pending_launch_satellites(session: AsyncSession) -> Sequence[Satellite]:
    """فهرست ماهواره‌هایی که در حال طی مراحل پرتاب هستند."""
    stmt = select(Satellite).where(Satellite.status == "launching")
    res = await session.execute(stmt)
    return res.scalars().all()


async def count_successful_launches(session: AsyncSession, country_id: int) -> int:
    """تعداد پرتاب‌های موفق قبلی کشور."""
    stmt = select(func.count(Satellite.id)).where(
        Satellite.country_id == country_id,
        Satellite.status.in_(["in_orbit", "expired"]),
    )
    res = await session.execute(stmt)
    return res.scalar() or 0


async def get_active_economic_satellite(
    session: AsyncSession, country_id: int
) -> Satellite | None:
    """دریافت ماهواره اقتصادی فعال یا در حال پرتاب کشور."""
    stmt = (
        select(Satellite)
        .where(
            Satellite.country_id == country_id,
            Satellite.satellite_type == "economic",
            Satellite.status.in_(["launching", "in_orbit"]),
        )
        .order_by(Satellite.id.desc())
    )
    res = await session.execute(stmt)
    return res.scalars().first()


async def list_active_economic_satellites_in_orbit(
    session: AsyncSession,
) -> Sequence[Satellite]:
    """فهرست تمام ماهواره‌های اقتصادی فعال در مدار برای زمان‌بند."""
    stmt = (
        select(Satellite)
        .where(
            Satellite.satellite_type == "economic",
            Satellite.status == "in_orbit",
        )
        .order_by(Satellite.id.asc())
    )
    res = await session.execute(stmt)
    return res.scalars().all()


async def list_satellites_by_country_and_type(
    session: AsyncSession, country_id: int, sat_type: str
) -> Sequence[Satellite]:
    """فهرست ماهواره‌های یک کشور بر اساس نوع."""
    stmt = (
        select(Satellite)
        .where(
            Satellite.country_id == country_id,
            Satellite.satellite_type == sat_type,
        )
        .order_by(Satellite.id.desc())
    )
    res = await session.execute(stmt)
    return res.scalars().all()


async def create_econ_receipt(
    session: AsyncSession, receipt: EconSatReceipt
) -> EconSatReceipt:
    """ثبت رسید پرداخت ماهواره اقتصادی."""
    session.add(receipt)
    await session.flush()
    return receipt


async def get_econ_receipt(
    session: AsyncSession, receipt_id: int
) -> EconSatReceipt | None:
    """دریافت رسید پرداخت با شناسه."""
    stmt = select(EconSatReceipt).where(EconSatReceipt.id == receipt_id)
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def update_econ_receipt_status(
    session: AsyncSession,
    receipt_id: int,
    status: str,
    admin_id: int,
) -> EconSatReceipt | None:
    """به‌روزرسانی وضعیت بررسی رسید پرداخت توسط ادمین."""
    from datetime import datetime, timezone

    receipt = await get_econ_receipt(session, receipt_id)
    if receipt:
        receipt.status = status
        receipt.reviewed_by = admin_id
        receipt.reviewed_at = datetime.now(timezone.utc)
        await session.flush()
    return receipt
