"""مدل کارخانه‌ی نظامی (v1.7) — بازتولید تجهیزات موجود یک کشور."""

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


class MilitaryFactory(Base):
    """
    یک کارخانه‌ی نظامی که هر چرخه (۲۴ یا ۱۴۴ ساعت) تعدادی از یک قلم تجهیزات
    مشخص (asset_name) را تولید و به موجودی نظامی کشور اضافه می‌کند.
    منابع لازم برای ساخت و مصرف هر چرخه از روی نوع کارخانه (constants) خوانده می‌شود.
    """

    __tablename__ = "military_factories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    # نوع کارخانه (مقدار MilitaryFactoryType)
    factory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # قلم تجهیزاتی که بازتولید می‌شود (مثلاً "F-22 Raptor")
    asset_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # دسته‌ی تجهیزات (مثلاً "جنگنده") و واحد شمارش (فروند/عراده/...)
    category: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    unit: Mapped[str] = mapped_column(String(16), default="عدد", nullable=False)

    location: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # تعداد تولید در هر چرخه و طول چرخه (ساعت)
    yield_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    yield_interval_h: Mapped[int] = mapped_column(Integer, default=24, nullable=False)

    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_yield_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    country: Mapped["Country"] = relationship()

    def __repr__(self) -> str:
        return f"<MilitaryFactory {self.factory_type}:{self.asset_name} country={self.country_id}>"
