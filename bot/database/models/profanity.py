"""مدل کلمات رکیک و بلک‌لیست فیلتر فحش (Profanity Filter)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProfanityWord(Base):
    """کلمات و عبارات ممنوعه و رکیک در سیستم فیلتر فحش."""

    __tablename__ = "profanity_words"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    word: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    added_by: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)  # 0: کلمات اولیه پیش‌فرض
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<ProfanityWord id={self.id} word='{self.word}' added_by={self.added_by}>"
