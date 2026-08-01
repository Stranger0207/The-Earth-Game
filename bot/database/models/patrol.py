"""
مدل گشت دفاعی (v1.10.6).

گشت فعال اثر واقعی دارد: شانس کشف خرابکاری/ترور علیه کشور، بونوس پدافند
در برابر حمله، و بونوس شانس رهگیری محموله‌های عبوری از قلمرو.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Patrol(Base):
    """یک گشت فعال (هوایی/زمینی/دریایی) در منطقه‌ای از قلمرو کشور."""

    __tablename__ = "patrols"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    # نوع گشت (مقادیر PatrolType)
    patrol_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # منطقه‌ی گشت‌زنی (متن آزاد بازیکن: «مرز شرقی»، «تنگه هرمز»، ...)
    area: Mapped[str] = mapped_column(String(120), default="", nullable=False)

    # تجهیزات درگیر در گشت: [{"name","count","unit"}]
    assets_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    # مجموع واحدهای درگیر (برای محاسبه‌ی سریع اثر گشت)
    total_units: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    fuel_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # تعداد رویدادهایی که این گشت کشف/خنثی کرده (برای گزارش به بازیکن)
    detections: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:
        return f"<Patrol {self.patrol_type} country={self.country_id} active={self.is_active}>"
