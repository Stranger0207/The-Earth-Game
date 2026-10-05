"""توابع دسترسی داده برای وام‌های بانکی (v2.2)."""

from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...enums import LoanStatus
from ..models import BankLoan


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def get_active_loan(session: AsyncSession, country_id: int) -> BankLoan | None:
    """دریافت وام فعال کشور در صورت وجود."""
    result = await session.execute(
        select(BankLoan).where(
            BankLoan.country_id == country_id,
            BankLoan.status == LoanStatus.ACTIVE,
        )
    )
    return result.scalars().first()


async def get_loan(session: AsyncSession, loan_id: int) -> BankLoan | None:
    """دریافت یک وام بر اساس شناسه."""
    return await session.get(BankLoan, loan_id)


async def create_loan(
    session: AsyncSession,
    country_id: int,
    amount: float,
    deadline: datetime,
    reward_deadline: datetime,
) -> BankLoan:
    """ثبت وام جدید."""
    loan = BankLoan(
        country_id=country_id,
        amount=amount,
        remaining_amount=amount,
        status=LoanStatus.ACTIVE,
        taken_at=_utcnow(),
        deadline=deadline,
        reward_deadline=reward_deadline,
    )
    session.add(loan)
    await session.flush()
    return loan


async def list_active_loans(session: AsyncSession) -> list[BankLoan]:
    """فهرست تمام وام‌های فعال برای بررسی توسط زمان‌بند."""
    result = await session.execute(
        select(BankLoan).where(BankLoan.status == LoanStatus.ACTIVE)
    )
    return list(result.scalars().all())


async def list_country_loans(session: AsyncSession, country_id: int) -> list[BankLoan]:
    """فهرست کل تاریخچه وام‌های یک کشور."""
    result = await session.execute(
        select(BankLoan)
        .where(BankLoan.country_id == country_id)
        .order_by(BankLoan.id.desc())
    )
    return list(result.scalars().all())
