"""
مدل فرماندهان نظامی (v1.10.6).

هر کشور چند فرمانده NPC دارد که به شاخه‌ی تخصصی خود بونوس قدرت می‌دهند.
ترور موفق یک فرمانده، بونوس او را تا انتصاب جانشین از بین می‌برد.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Commander(Base):
    """یک فرمانده نظامی یا دانشمند ارشد (NPC) متعلق به یک کشور."""

    __tablename__ = "commanders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    # نام فارسی فرمانده (از data/commanders.json تولید می‌شود)
    name: Mapped[str] = mapped_column(String(96), nullable=False)
    # درجه/عنوان (سرلشکر، دریادار، ...)
    rank_title: Mapped[str] = mapped_column(String(48), default="", nullable=False)
    # تخصص (مقادیر CommanderRole)
    role: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    # درصد بونوس قدرت به شاخه‌ی تخصصی
    bonus_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # --- وضعیت حیات ---
    is_alive: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    killed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # زمان انتصاب جانشین؛ پس از این لحظه فرمانده دوباره فعال می‌شود
    replacement_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        state = "alive" if self.is_alive else "dead"
        return f"<Commander {self.name} role={self.role} country={self.country_id} {state}>"
