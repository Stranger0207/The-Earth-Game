"""مدل نرخ لحظه‌ای و پویای ذخایر در بازار جهانی (آپدیت شماره ۴)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class MarketPrice(Base):
    """جدول نرخ لحظه‌ای هر یک از ذخایر استراتژیک در بازار جهانی WTO."""

    __tablename__ = "market_prices"

    resource: Mapped[str] = mapped_column(String(32), primary_key=True)
    base_price: Mapped[float] = mapped_column(Float, nullable=False)
    current_price: Mapped[float] = mapped_column(Float, nullable=False)
    previous_price: Mapped[float] = mapped_column(Float, nullable=False)
    change_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    trend: Mapped[str] = mapped_column(String(16), default="STABLE", nullable=False)  # UP, DOWN, STABLE
    last_reason_code: Mapped[str] = mapped_column(String(64), default="INITIAL", nullable=False)
    last_reason_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<MarketPrice {self.resource}: current={self.current_price:,.0f} "
            f"change={self.change_pct:+.1f}% trend={self.trend}>"
        )
