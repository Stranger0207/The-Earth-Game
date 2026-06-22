"""توابع دسترسی داده برای درخواست‌های کشورگیری."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...enums import ClaimStatus
from ..models import ClaimRequest


async def create_claim(
    session: AsyncSession,
    user_id: int,
    country_id: int,
    president_name: str | None,
    note: str | None,
) -> ClaimRequest:
    """ساخت درخواست کشورگیری جدید."""
    claim = ClaimRequest(
        user_id=user_id,
        country_id=country_id,
        president_name=president_name,
        note=note,
        status=ClaimStatus.PENDING,
    )
    session.add(claim)
    await session.flush()
    return claim


async def get_claim(session: AsyncSession, claim_id: int) -> ClaimRequest | None:
    """دریافت یک درخواست بر اساس آی‌دی."""
    return await session.get(ClaimRequest, claim_id)


async def get_pending_for_user(
    session: AsyncSession, user_id: int
) -> ClaimRequest | None:
    """آیا کاربر درخواست در انتظار تأیید دارد؟"""
    result = await session.execute(
        select(ClaimRequest).where(
            ClaimRequest.user_id == user_id,
            ClaimRequest.status == ClaimStatus.PENDING,
        )
    )
    return result.scalar_one_or_none()


async def list_pending(session: AsyncSession) -> list[ClaimRequest]:
    """فهرست همه‌ی درخواست‌های در انتظار تأیید."""
    result = await session.execute(
        select(ClaimRequest)
        .where(ClaimRequest.status == ClaimStatus.PENDING)
        .order_by(ClaimRequest.created_at)
    )
    return list(result.scalars().all())


async def set_status(
    session: AsyncSession, claim_id: int, status: ClaimStatus, reviewer_id: int
) -> ClaimRequest | None:
    """تغییر وضعیت درخواست (تأیید/رد) و ثبت بازبینی‌کننده."""
    claim = await session.get(ClaimRequest, claim_id)
    if claim is not None:
        claim.status = status
        claim.reviewed_by = reviewer_id
    return claim
