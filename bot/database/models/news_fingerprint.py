"""
مدل اثرانگشت خبری (v1.10.6) — موتور ضدتکرار اخبار.

هر خبر نظامی منتشرشده یک «اثرانگشت» (هش مجموعه‌ی ۳-گرم‌های متن) دارد.
پیش از انتشار خبر جدید، شباهت آن با اخبار اخیر سنجیده می‌شود و در صورت
شباهت بالا، خبر با آرکه‌تایپ دیگری بازتولید می‌شود.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NewsFingerprint(Base):
    """اثرانگشت یک خبر منتشرشده برای تشخیص تکرار."""

    __tablename__ = "news_fingerprints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # دسته‌ی خبر (military / diplomacy / ...) برای مقایسه‌ی درون‌دسته‌ای
    category: Mapped[str] = mapped_column(String(24), default="military", nullable=False, index=True)
    # آرکه‌تایپ استفاده‌شده (مقادیر NewsArchetype)
    archetype: Mapped[str] = mapped_column(String(24), default="", nullable=False)
    # هش کوتاه متن (برای تشخیص سریع تکرار عیناً یکسان)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # مجموعه‌ی ۳-گرم‌ها به‌صورت متن جداشده با «|» (برای محاسبه‌ی شباهت)
    shingles: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # چند کلمه‌ی کلیدی/عبارت شاخص خبر (برای تزریق «این عبارات را تکرار نکن» به پرامپت)
    key_phrases: Mapped[str] = mapped_column(Text, default="", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )

    def __repr__(self) -> str:
        return f"<NewsFingerprint {self.category}/{self.archetype} {self.text_hash[:8]}>"
