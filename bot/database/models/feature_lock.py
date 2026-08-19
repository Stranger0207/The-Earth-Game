"""
مدل قفل آپشن‌ها (v2.1) — غیرفعال‌کردن یک بخش بازی توسط مالک.

پیش از این، تنها راه بستن یک قابلیت، خاموش‌کردن کل ربات (`/botpower`) بود.
اکنون مالک می‌تواند هر آپشن (ترور، احداث تأسیسات، سفر، بانک، ...) را برای
یک کشور، چند کشور یا **همه‌ی کشورها** ببندد.

- `country_id = NULL` یعنی قفل **سراسری** (برای همه‌ی کشورها).
- `country_id` مقدار داشته باشد یعنی قفل فقط برای همان کشور.

فهرست کلیدهای مجاز در `constants.LOCKABLE_FEATURES` است و اعمال قفل در
`handlers/deps.assert_feature` انجام می‌شود.

توجه: عمداً `ForeignKey` به `countries` گذاشته نشده (مثل
`facilities.partner_country` در v1.9) تا رابطه‌ی مبهم ORM ساخته نشود؛
ریست فصل این جدول را کامل پاک می‌کند.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FeatureLock(Base):
    """یک قفل فعال روی یک آپشن بازی (سراسری یا مخصوص یک کشور)."""

    __tablename__ = "feature_locks"
    __table_args__ = (
        UniqueConstraint("feature_key", "country_id", name="uq_feature_lock_key_country"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # کلید آپشن — یکی از کلیدهای constants.LOCKABLE_FEATURES
    feature_key: Mapped[str] = mapped_column(String(48), nullable=False, index=True)

    # None = قفل سراسری برای همه‌ی کشورها
    country_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # دلیل اختیاری (فعلاً فقط در پنل مالک نمایش داده می‌شود)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        scope = "all" if self.country_id is None else f"country={self.country_id}"
        return f"<FeatureLock {self.feature_key} {scope}>"
