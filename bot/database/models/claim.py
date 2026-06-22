"""مدل درخواست کشورگیری (claim)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ...enums import ClaimStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ClaimRequest(Base):
    """
    درخواست یک کاربر برای برداشتن (claim) یک کشور.
    مالک بازی باید آن را تأیید یا رد کند.
    """

    __tablename__ = "claim_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True
    )
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    # نام رئیس‌جمهوری که کاربر هنگام درخواست انتخاب کرده
    president_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # توضیح اختیاری کاربر
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), default=ClaimStatus.PENDING, nullable=False
    )
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<ClaimRequest user={self.user_id} country={self.country_id} {self.status}>"
