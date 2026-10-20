"""
مدل‌های لایسنس و انتقال تکنولوژی نظامی (Tech Transfer & Licensing).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base

if TYPE_CHECKING:
    from .country import Country


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TechLicense(Base):
    """
    لایسنس فعال بازتولید یک قلم تجهیزات نظامی برای یک کشور.
    """

    __tablename__ = "tech_licenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    holder_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    origin_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    equipment_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    branch: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    price_paid: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    holder_country: Mapped["Country"] = relationship(foreign_keys=[holder_country_id])
    origin_country: Mapped["Country"] = relationship(foreign_keys=[origin_country_id])

    def __repr__(self) -> str:
        return f"<TechLicense {self.equipment_name} to country={self.holder_country_id}>"


class TechTransferRequest(Base):
    """
    درخواست و فاکتور خرید لایسنس تکنولوژی نظامی.
    """

    __tablename__ = "tech_transfer_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    buyer_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    seller_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    equipment_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    branch: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    # وضعیت‌ها:
    # PENDING_MANUFACTURER: در انتظار تعیین قیمت توسط سازنده
    # INVOICE_SENT: فاکتور صادر شده و منتظر تایید و پرداخت خریدار
    # COMPLETED: تایید و پرداخت شده و لایسنس صادر گردید
    # REJECTED_BY_SELLER: رد شده توسط کشور سازنده
    # CANCELLED_BY_BUYER: لغو شده توسط خریدار
    status: Mapped[str] = mapped_column(
        String(32), default="PENDING_MANUFACTURER", nullable=False
    )
    license_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    buyer_country: Mapped["Country"] = relationship(foreign_keys=[buyer_country_id])
    seller_country: Mapped["Country"] = relationship(foreign_keys=[seller_country_id])

    def __repr__(self) -> str:
        return f"<TechTransferRequest #{self.id} {self.equipment_name} {self.status}>"
