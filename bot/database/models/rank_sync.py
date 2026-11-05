"""مدل صف برون‌خط (Outbox) برای همگام‌سازی رویدادهای ارتقای مقام با ربات مقام."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    """زمان فعلی به‌صورت UTC آگاه از منطقه‌ی زمانی."""
    return datetime.now(timezone.utc)


class RankSyncOutbox(Base):
    """
    صف پیام‌های ارسال‌نشده به ربات مقام (Outbox Pattern).
    هنگامی که ارسال آنی لیست بازیکنان پایان فصل به ربات مقام به هر دلیلی
    (مانند خاموش بودن، خطای شبکه، تایم‌اوت) شکست بخورد، رویداد با همان event_id
    در این جدول ذخیره می‌شود تا زمان‌بند مجدداً آن را ارسال کند.
    این جدول در ریست فصل پاک نمی‌شود (Preserved).
    """

    __tablename__ = "rank_sync_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), default="season_ended", nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<RankSyncOutbox id={self.id} event_id={self.event_id} attempts={self.attempts}>"
