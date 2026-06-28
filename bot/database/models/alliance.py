"""مدل اتحاد بین کشورها (v1.9)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Alliance(Base):
    """یک اتحاد که توسط یک کشور VIP ساخته می‌شود و چند عضو دارد."""

    __tablename__ = "alliances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    terms: Mapped[str] = mapped_column(Text, default="", nullable=False)  # مفاد اتحاد
    owner_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<Alliance {self.name} owner={self.owner_country}>"


class AllianceMember(Base):
    """عضویت یک کشور در یک اتحاد (شامل کشور سازنده)."""

    __tablename__ = "alliance_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alliance_id: Mapped[int] = mapped_column(
        ForeignKey("alliances.id"), nullable=False, index=True
    )
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<AllianceMember a={self.alliance_id} c={self.country_id}>"
