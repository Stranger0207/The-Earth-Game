"""مدل ماهواره‌های جاسوسی فضایی (v2.0)."""

from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Satellite(Base):
    """
    ماهواره فضایی کشور.
    وضعیت‌ها:
    - launching: تازه پرتاب شده و در حال پرواز به جو/مدار است
    - in_orbit: در مدار قرار گرفته و فعال است
    - failed: پرتاب شکست خورده و سقوط کرده
    - expired: عمر مفیدش (۷ روز) به پایان رسیده است
    """

    __tablename__ = "satellites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    satellite_type: Mapped[str] = mapped_column(String(32), default="spy", nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    status: Mapped[str] = mapped_column(String(32), default="launching", nullable=False)
    launch_success_pct: Mapped[float] = mapped_column(Float, default=70.0, nullable=False)

    launch_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    orbit_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    cost_usd: Mapped[float] = mapped_column(Float, default=15_000_000_000.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<Satellite {self.name} country={self.country_id} status={self.status}>"
