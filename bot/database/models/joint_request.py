"""مدل درخواست تأسیسات مشترک (v1.9) — تا تأیید شریک نگه داشته می‌شود."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String

from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JointBuildRequest(Base):
    """درخواست احداث تأسیسات مشترک از سوی یک کشور به شریک تجاری‌اش."""

    __tablename__ = "joint_build_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    initiator_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    partner_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    facility_type: Mapped[str] = mapped_column(String(24), nullable=False)
    resource: Mapped[str | None] = mapped_column(String(16), nullable=True)
    partner_percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    location: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<JointBuildRequest {self.initiator_country}+{self.partner_country} {self.facility_type}>"
