"""
مدل رزمایش نظامی (v1.10.6).

رزمایش آمادگی رزمی (readiness) کشور را بالا می‌برد که مستقیماً روی قدرت
عملیات بعدی اثر می‌گذارد. رزمایش مشترک برای هر دو کشور بونوس دارد.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Drill(Base):
    """یک رزمایش نظامی (تکی یا مشترک با کشور دیگر)."""

    __tablename__ = "drills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    # کشور شریک در رزمایش مشترک (در رزمایش تکی خالی است)
    partner_country_id: Mapped[int | None] = mapped_column(
        ForeignKey("countries.id"), nullable=True, index=True
    )

    # نوع رزمایش (مقادیر DrillType)
    drill_type: Mapped[str] = mapped_column(String(16), default="solo", nullable=False)
    # نام رزمایش (بازیکن انتخاب می‌کند: «اقتدار ۱۴۰۵»)
    title: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    area: Mapped[str] = mapped_column(String(120), default="", nullable=False)

    # تجهیزات شرکت‌کننده: [{"name","count","unit"}]
    assets_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    fuel_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    budget_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # میزان آمادگی رزمی اعطاشده در پایان رزمایش
    readiness_gain: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # در انتظار پذیرش شریک (فقط رزمایش مشترک)
    partner_accepted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # آیا رزمایش تمام شده و اثرش اعمال شده است؟
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    def __repr__(self) -> str:
        return f"<Drill {self.drill_type} country={self.country_id} done={self.is_completed}>"
