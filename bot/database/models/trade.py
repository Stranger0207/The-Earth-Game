"""مدل فروش ذخایر و محموله‌های سازمان انتقالات جهانی (WTO)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ...enums import TradeStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ResourceSale(Base):
    """
    فروش یک منبع از کشور فروشنده به کشور خریدار.
    پس از تأیید خریدار، محموله توسط WTO ارسال می‌شود و در زمان رسیدن (ship_eta)
    منبع به ذخایر خریدار اضافه می‌گردد.
    """

    __tablename__ = "resource_sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    buyer_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    resource: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)  # دلار

    status: Mapped[str] = mapped_column(
        String(16), default=TradeStatus.PENDING, nullable=False
    )
    # زمان تخمینی رسیدن محموله (تخمین AI)
    ship_eta: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ResourceSale {self.resource} {self.amount} "
            f"{self.seller_country}->{self.buyer_country} {self.status}>"
        )
