"""مدل رسیدهای واریزی ماهواره اقتصادی (v2.8)."""

from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EconSatReceipt(Base):
    """
    رسید پرداخت کارت‌به‌کارت ۵۰ هزار تومانی برای فعالسازی ماهواره اقتصادی.
    وضعیت‌ها:
    - pending: در انتظار بررسی و تایید پشتیبانی
    - approved: تایید شده و آپشن فعال شد
    - rejected: رد شده
    """

    __tablename__ = "econ_sat_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    photo_file_id: Mapped[str] = mapped_column(String(256), nullable=False)

    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    def __repr__(self) -> str:
        return f"<EconSatReceipt id={self.id} country={self.country_id} status={self.status}>"
