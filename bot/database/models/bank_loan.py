"""مدل وام بانکی (v2.2)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ...enums import LoanStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BankLoan(Base):
    """
    وام دریافتی یک کشور از بانک مرکزی.
    مهلت بازپرداخت ۷ روز است؛ در صورتی که زیر ۵ روز تسویه شود، کشور خوش‌حساب می‌شود.
    در صورت عدم تسویه در ۷ روز، کشور بدحساب (defaulter) می‌شود.
    """

    __tablename__ = "bank_loans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    amount: Mapped[float] = mapped_column(Float, nullable=False)  # مبلغ کل وام دریافتی
    remaining_amount: Mapped[float] = mapped_column(Float, nullable=False)  # مبلغ باقی‌مانده

    status: Mapped[str] = mapped_column(
        String(16), default=LoanStatus.ACTIVE, nullable=False
    )

    taken_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    deadline: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )  # مهلت ۷ روزه
    reward_deadline: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )  # مهلت ۵ روزه برای خوش‌حسابی

    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # فلگ‌های یادآوری زمان‌بند
    warned_5d: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    warned_6d: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:
        return f"<BankLoan #{self.id} country={self.country_id} rem={self.remaining_amount} status={self.status}>"
