"""مدل تأسیسات (معدن، کارخانه فولاد، سکوی نفت/گاز)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base

if TYPE_CHECKING:
    from .country import Country


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Facility(Base):
    """
    یک تأسیسات احداث‌شده توسط یک کشور.
    بازدهی هر ۲۴ ساعت توسط زمان‌بند (scheduler) به ذخایر اضافه می‌شود.
    """

    __tablename__ = "facilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    # نوع تأسیسات (مقدار FacilityType)
    type: Mapped[str] = mapped_column(String(24), nullable=False)

    # برای معدن: نوع منبعی که استخراج می‌کند؛ برای کارخانه فولاد: steel و غیره
    resource: Mapped[str | None] = mapped_column(String(16), nullable=True)

    location: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    budget: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # بازدهی تولید در هر بازه (مثلاً تن در ۲۴ ساعت)
    yield_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    yield_interval_h: Mapped[int] = mapped_column(Integer, default=24, nullable=False)

    # برای کارخانه فولاد: مقدار آهن مصرفی در هر بازه
    intake_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_yield_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    country: Mapped["Country"] = relationship(back_populates="facilities")

    def __repr__(self) -> str:
        return f"<Facility {self.type} country={self.country_id}>"
