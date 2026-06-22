"""مدل کول‌داون‌ها (محدودیت‌های زمانی کنش‌ها)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Cooldown(Base):
    """
    آخرین زمان انجام یک نوع کنش توسط یک کشور.
    برای محدودیت‌هایی مثل «فروش ذخیره هر ۶ ساعت» و «مشاور هر ۲۴ ساعت» استفاده می‌شود.

    action_type نمونه‌ها:
      - "resource_sale"
      - "advisor:economy" / "advisor:diplomacy" / "advisor:military"
    """

    __tablename__ = "cooldowns"
    __table_args__ = (
        UniqueConstraint("country_id", "action_type", name="uq_cooldown_country_action"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(String(48), nullable=False)
    last_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<Cooldown country={self.country_id} {self.action_type}>"
