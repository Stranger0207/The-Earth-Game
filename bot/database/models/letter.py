"""مدل نامه‌ی دیپلماتیک (v1.9) — برای صندوق پستی و پاسخ به نامه."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Letter(Base):
    """یک نامه از یک کشور به کشور دیگر. پاسخ‌ها با parent_id به نامه‌ی اصلی وصل می‌شوند."""

    __tablename__ = "letters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sender_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    recipient_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # نامه‌ی والد (در صورت پاسخ‌بودن این نامه)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("letters.id"), nullable=True
    )
    # آیا گیرنده به این نامه پاسخ داده است؟
    replied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<Letter {self.sender_country}->{self.recipient_country}>"
