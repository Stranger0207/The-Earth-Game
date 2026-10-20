"""
توابع دسترسی داده (Repository) برای لایسنس و انتقال تکنولوژی نظامی.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import TechLicense, TechTransferRequest


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
#  لایسنس‌های فعال (TechLicense)
# ============================================================


async def has_license(session: AsyncSession, country_id: int, equipment_name: str) -> bool:
    """آیا این کشور لایسنس فعال برای این قلم تجهیزات دارد؟"""
    stmt = (
        select(TechLicense.id)
        .where(
            TechLicense.holder_country_id == country_id,
            TechLicense.equipment_name == equipment_name,
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def get_license(
    session: AsyncSession, country_id: int, equipment_name: str
) -> TechLicense | None:
    """دریافت لایسنس مشخص یک کشور برای یک قلم."""
    stmt = select(TechLicense).where(
        TechLicense.holder_country_id == country_id,
        TechLicense.equipment_name == equipment_name,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def grant_license(
    session: AsyncSession,
    holder_country_id: int,
    origin_country_id: int,
    equipment_name: str,
    branch: str = "",
    category: str = "",
    price_paid: float = 0.0,
) -> TechLicense:
    """اعطای لایسنس جدید (یا برگرداندن لایسنس موجود)."""
    existing = await get_license(session, holder_country_id, equipment_name)
    if existing is not None:
        return existing

    license_obj = TechLicense(
        holder_country_id=holder_country_id,
        origin_country_id=origin_country_id,
        equipment_name=equipment_name,
        branch=branch,
        category=category,
        price_paid=price_paid,
        granted_at=_utcnow(),
    )
    session.add(license_obj)
    await session.flush()
    return license_obj


async def revoke_license(session: AsyncSession, license_id: int) -> bool:
    """لغو/حذف یک لایسنس."""
    lic = await session.get(TechLicense, license_id)
    if lic is not None:
        await session.delete(lic)
        await session.flush()
        return True
    return False


async def list_licenses_for_country(
    session: AsyncSession, country_id: int
) -> list[TechLicense]:
    """فهرست تمام لایسنس‌هایی که این کشور خریداری/دریافت کرده است."""
    stmt = (
        select(TechLicense)
        .where(TechLicense.holder_country_id == country_id)
        .options(selectinload(TechLicense.origin_country))
        .order_by(TechLicense.granted_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_granted_licenses_by_country(
    session: AsyncSession, origin_country_id: int
) -> list[TechLicense]:
    """فهرست تمام لایسنس‌هایی که این کشور به کشورهای دیگر واگذار کرده است."""
    stmt = (
        select(TechLicense)
        .where(TechLicense.origin_country_id == origin_country_id)
        .options(selectinload(TechLicense.holder_country))
        .order_by(TechLicense.granted_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ============================================================
#  درخواست‌ها و فاکتورها (TechTransferRequest)
# ============================================================


async def get_active_request(
    session: AsyncSession, buyer_country_id: int, equipment_name: str
) -> TechTransferRequest | None:
    """دریافت درخواست باز فعال خریدار برای این تجهیز."""
    stmt = select(TechTransferRequest).where(
        TechTransferRequest.buyer_country_id == buyer_country_id,
        TechTransferRequest.equipment_name == equipment_name,
        TechTransferRequest.status.in_(["PENDING_MANUFACTURER", "INVOICE_SENT"]),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_request(
    session: AsyncSession, request_id: int
) -> TechTransferRequest | None:
    """دریافت درخواست با شناسه همراه با روابط کشورها."""
    stmt = (
        select(TechTransferRequest)
        .where(TechTransferRequest.id == request_id)
        .options(
            selectinload(TechTransferRequest.buyer_country),
            selectinload(TechTransferRequest.seller_country),
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_request(
    session: AsyncSession,
    buyer_country_id: int,
    seller_country_id: int,
    equipment_name: str,
    branch: str = "",
    category: str = "",
) -> TechTransferRequest:
    """ثبت درخواست جدید خرید لایسنس تکنولوژی."""
    req = TechTransferRequest(
        buyer_country_id=buyer_country_id,
        seller_country_id=seller_country_id,
        equipment_name=equipment_name,
        branch=branch,
        category=category,
        status="PENDING_MANUFACTURER",
        license_price=0.0,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    session.add(req)
    await session.flush()
    return req


async def list_incoming_requests(
    session: AsyncSession, seller_country_id: int, status: str | None = None
) -> list[TechTransferRequest]:
    """درخواست‌های دریافتی برای کشور سازنده."""
    stmt = (
        select(TechTransferRequest)
        .where(TechTransferRequest.seller_country_id == seller_country_id)
        .options(selectinload(TechTransferRequest.buyer_country))
        .order_by(TechTransferRequest.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(TechTransferRequest.status == status)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_outgoing_requests(
    session: AsyncSession, buyer_country_id: int, status: str | None = None
) -> list[TechTransferRequest]:
    """درخواست‌های ارسالی توسط کشور خریدار."""
    stmt = (
        select(TechTransferRequest)
        .where(TechTransferRequest.buyer_country_id == buyer_country_id)
        .options(selectinload(TechTransferRequest.seller_country))
        .order_by(TechTransferRequest.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(TechTransferRequest.status == status)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def set_invoice_price(
    session: AsyncSession, request_id: int, price: float
) -> TechTransferRequest | None:
    """تنظیم قیمت توسط سازنده و صدور فاکتور."""
    req = await get_request(session, request_id)
    if req is None or req.status != "PENDING_MANUFACTURER":
        return None
    req.license_price = price
    req.status = "INVOICE_SENT"
    req.updated_at = _utcnow()
    await session.flush()
    return req


async def complete_transfer(
    session: AsyncSession, request_id: int
) -> tuple[TechTransferRequest, TechLicense] | None:
    """نهایی‌سازی فاکتور پس از پرداخت موفق و صدور لایسنس."""
    req = await get_request(session, request_id)
    if req is None or req.status != "INVOICE_SENT":
        return None

    # انتقال مستقیم مبلغ فاکتور از خریدار به سازنده
    if req.license_price > 0:
        buyer = req.buyer_country
        seller = req.seller_country
        if buyer is not None and seller is not None:
            buyer.budget -= req.license_price
            seller.budget += req.license_price

    req.status = "COMPLETED"
    req.updated_at = _utcnow()

    license_obj = await grant_license(
        session,
        holder_country_id=req.buyer_country_id,
        origin_country_id=req.seller_country_id,
        equipment_name=req.equipment_name,
        branch=req.branch,
        category=req.category,
        price_paid=req.license_price,
    )
    await session.flush()
    return req, license_obj


async def reject_request(
    session: AsyncSession, request_id: int
) -> TechTransferRequest | None:
    """رد درخواست توسط کشور سازنده."""
    req = await get_request(session, request_id)
    if req is None:
        return None
    req.status = "REJECTED_BY_SELLER"
    req.updated_at = _utcnow()
    await session.flush()
    return req


async def cancel_request(
    session: AsyncSession, request_id: int
) -> TechTransferRequest | None:
    """لغو درخواست یا فاکتور توسط کشور خریدار."""
    req = await get_request(session, request_id)
    if req is None:
        return None
    req.status = "CANCELLED_BY_BUYER"
    req.updated_at = _utcnow()
    await session.flush()
    return req
