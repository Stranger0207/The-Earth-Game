"""مدل فروش ذخایر و محموله‌های سازمان انتقالات جهانی (WTO)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ...enums import FeePayer, TradeStatus, TransportMode



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
    # --- اسکورت محموله (v1.10.7) ---
    # فروشنده می‌تواند نیروی محافظ همراه محموله بفرستد تا از رهگیری جلوگیری کند.
    # قدرت اسکورت از تجهیزات اختصاص‌داده‌شده محاسبه و اینجا کش می‌شود.
    escort_power: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # تجهیزات اسکورت: [{"name","count","unit"}]
    escort_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    # --- شیوه حمل‌ونقل و عوارض لجستیک (آپدیت ۳ و ۱۱) ---
    transport_mode: Mapped[str] = mapped_column(
        String(8), default=TransportMode.SEA.value, nullable=False
    )
    fee_payer: Mapped[str] = mapped_column(
        String(8), default=FeePayer.SELLER.value, nullable=False
    )
    transport_fee: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    strait_toll_fee: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    strait_status: Mapped[str] = mapped_column(String(24), default="NONE", nullable=False)
    held_at_strait_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    held_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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
