"""
مدل اطلاعات جاسوسی روی فرماندهان (v1.10.7).

پیش از ترور، مهاجم باید محل و برنامه‌ی فرمانده هدف را شناسایی کند.
هر ردیف یعنی «کشور A محل فرمانده X را می‌داند» — اطلاعات مخصوص همان
مهاجم است (کشور دیگر از آن بهره نمی‌برد) و پس از مدتی منقضی می‌شود.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CommanderIntel(Base):
    """اطلاعات شناسایی‌شده‌ی یک کشور روی یک فرمانده‌ی خارجی."""

    __tablename__ = "commander_intel"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # کشوری که جاسوسی کرده (صاحب اطلاعات)
    spy_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    # فرمانده‌ی هدف
    commander_id: Mapped[int] = mapped_column(
        ForeignKey("commanders.id"), nullable=False, index=True
    )
    # کشور صاحب فرمانده (برای کوئری سریع بدون join)
    target_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    # کیفیت اطلاعات (۰ تا ۱۰۰) — هرچه بالاتر، شانس ترور بیشتر
    quality: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # محل شناسایی‌شده (متن تولیدشده برای واقع‌گرایی گزارش)
    known_location: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    # الگوی رفتاری کشف‌شده (برای نمایش در گزارش اطلاعاتی)
    routine_note: Mapped[str] = mapped_column(String(240), default="", nullable=False)

    # آیا هدف از جاسوسی باخبر شد؟ (ضدجاسوسی موفق)
    was_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    gathered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    # پس از این لحظه اطلاعات کهنه است و برای ترور به‌کار نمی‌آید
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    def __repr__(self) -> str:
        return (
            f"<CommanderIntel spy={self.spy_country_id} cmd={self.commander_id} "
            f"q={self.quality:.0f}>"
        )
