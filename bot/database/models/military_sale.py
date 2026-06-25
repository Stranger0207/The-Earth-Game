"""مدل فروش تجهیزات نظامی بین کشورها (v1.7) — محموله‌ی نظامی WTO."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ...enums import TradeStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MilitarySale(Base):
    """
    فروش یک قلم تجهیزات نظامی از کشور فروشنده به خریدار.
    پس از تأیید خریدار، محموله‌ی نظامی توسط WTO ارسال می‌شود و در زمان رسیدن
    (ship_eta) تجهیزات به موجودی نظامی خریدار اضافه می‌گردد.
    """

    __tablename__ = "military_sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    buyer_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    # دسته، نام و واحد تجهیزات فروخته‌شده
    category: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    branch: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), default="عدد", nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)  # دلار

    status: Mapped[str] = mapped_column(
        String(16), default=TradeStatus.PENDING, nullable=False
    )
    ship_eta: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<MilitarySale {self.name} x{self.count} "
            f"{self.seller_country}->{self.buyer_country} {self.status}>"
        )
