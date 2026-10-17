"""مدل فروش تجهیزات نظامی بین کشورها (v1.7) — محموله‌ی نظامی WTO."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ...enums import FeePayer, TradeStatus, TransportMode



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
    # --- اسکورت محموله (v1.10.7) ---
    escort_power: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    escort_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    # --- شیوه حمل‌ونقل و عوارض لجستیک (آپدیت ۳ و ۱۱: تسلیحات منحصراً هوایی است) ---
    transport_mode: Mapped[str] = mapped_column(
        String(8), default=TransportMode.AIR.value, nullable=False
    )
    fee_payer: Mapped[str] = mapped_column(
        String(8), default=FeePayer.SELLER.value, nullable=False
    )
    transport_fee: Mapped[float] = mapped_column(Float, default=8_000_000.0, nullable=False)

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
