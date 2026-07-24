"""مدل‌های سیستم جدید جنگ، اعلان جنگ، فازهای نبرد و حملات (v2.0)."""

from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WarDeclaration(Base):
    """اعلام جنگ رسمی بین دو کشور."""

    __tablename__ = "war_declarations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    declarer_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    target_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    declared_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class Battle(Base):
    """
    مدل جدید نبرد نظامی.
    پشتیبانی از ۴ نوع حمله (ground, air, naval, sabotage) + حمله به محموله WTO (wto_interception).
    دارای وضعیت‌های: pending_owner (در انتظار تأیید مالک بازی)، in_progress (در حال اجرای فازهای خبری)، resolved, rejected.
    """

    __tablename__ = "battles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attacker_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    defender_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    # نوع حمله: ground, air, naval, sabotage, wto_interception
    attack_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # هدف: city, military_base, oil_platform, factory, wto_shipment
    target_type: Mapped[str] = mapped_column(String(32), default="military_base", nullable=False)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # شرح تجهیزات و نقشه تهاجم
    payload: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # تنظیمات خرابکاری
    claim_responsibility: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_exposed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # وضعیت: pending_owner, in_progress, resolved, rejected
    status: Mapped[str] = mapped_column(String(32), default="pending_owner", nullable=False)

    fuel_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # تلفات و اثرات (در قالب JSON)
    attacker_losses_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    defender_losses_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    econ_effects_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    outcome: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    # فاز خبری نبرد (0: شروع نشده، 1: فلش فوری، 2: درگیری اولیه، 3: خسارت، 4: نتیجه نهایی)
    current_phase: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_phase_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<Battle {self.attack_type} {self.attacker_country_id}->{self.defender_country_id} status={self.status}>"
