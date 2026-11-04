"""مدل گزارش تراز جهانی و اسنپشات آماری کلان سرور."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GlobalReport(Base):
    """
    جدول ذخیره‌سازی گزارش‌های دوره‌ای تراز کلان جهانی و اسنپشات ذخایر کشورها.
    داده‌های کامل به صورت JSON در payload_json ذخیره می‌شوند تا مبنای مقایسه (Snapshot Diff)
    و کشف انحراف داده (Data Drift / Audit Delta) برای دوره‌های بعدی باشند.
    """

    __tablename__ = "global_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # بازه زمانی گزارش به ساعت (مثلاً 8، 24 یا 72)
    period_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=8)

    # زمان شروع و پایان بازه گزارش
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # زمان تولید گزارش
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    # دیکشنری کامل داده‌های محاسبه‌شده به صورت JSON (شامل اسنپشات کشورها، ذخایر، تولید، مصرف و مارکت)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    # متن خلاصه تولیدشده برای ارسال سریع به لاگ یا تلگرام
    short_text: Mapped[str] = mapped_column(Text, default="", nullable=False)

    def __repr__(self) -> str:
        return (
            f"<GlobalReport id={self.id} period={self.period_hours}h "
            f"generated_at={self.generated_at.isoformat()}>"
        )
