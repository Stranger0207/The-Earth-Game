"""مدل پایگاه‌های نظامی و تجهیزات مستقر در آن‌ها."""

from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MilitaryBase(Base):
    """
    پایگاه نظامی ساخته‌شده در یک کشور.
    می‌تواند در خاک خود کشور یا در کشور دیگری (با رضایت میزبان) ساخته شود.
    """

    __tablename__ = "military_bases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    host_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    # نوع پایگاه: air_base, ground_base, naval_base
    base_type: Mapped[str] = mapped_column(String(32), nullable=False)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    location: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    # وضعیت: pending (در انتظار تأیید میزبان)، active (فعال)، destroyed (تخریب شده)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    host_approved: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    defense_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    # رابطه با تجهیزات مستقر
    equipments: Mapped[list[BaseEquipment]] = relationship(
        "BaseEquipment", back_populates="base", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<MilitaryBase {self.name} ({self.base_type}) owner={self.owner_country_id} host={self.host_country_id}>"


class BaseEquipment(Base):
    """تجهیزات مستقر در یک پایگاه نظامی خاص."""

    __tablename__ = "base_equipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    base_id: Mapped[int] = mapped_column(
        ForeignKey("military_bases.id", ondelete="CASCADE"), nullable=False, index=True
    )

    asset_name: Mapped[str] = mapped_column(String(128), nullable=False)
    branch: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    base: Mapped[MilitaryBase] = relationship("MilitaryBase", back_populates="equipments")

    def __repr__(self) -> str:
        return f"<BaseEquipment {self.asset_name} count={self.count} base_id={self.base_id}>"
