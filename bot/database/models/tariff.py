"""مدل تعرفه‌ی بین‌المللی (v1.5) — قابلیت انحصاری آمریکا."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TariffRate(Base):
    """
    نرخ تعرفه‌ای که آمریکا برای یک کشور هدف تعیین کرده است.
    این تعرفه روی همه‌ی فروش‌های آن کشور اعمال می‌شود و درصد آن به خزانه‌ی آمریکا می‌رود.
    """

    __tablename__ = "tariff_rates"
    __table_args__ = (
        UniqueConstraint("target_country", name="uq_tariff_target"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # کشوری که تعرفه روی آن اعمال می‌شود
    target_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    # درصد تعرفه (۰ تا ۱۰۰)
    percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<TariffRate target={self.target_country} {self.percent}%>"
