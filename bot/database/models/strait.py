"""
مدل‌های ژئوپلیتیک تنگه‌ها، مسدودسازی و اموال بلوکه‌شده (آپدیت ۳ و ۱۱).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ...enums import StraitBlockScope


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StraitConfig(Base):
    """
    تنظیمات وضعیت و عوارض تنگه‌های استراتژیک بین‌المللی.
    """

    __tablename__ = "strait_configs"

    strait_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name_fa: Mapped[str] = mapped_column(String(64), nullable=False)
    name_en: Mapped[str] = mapped_column(String(64), nullable=False)
    # کشور کنترل‌کننده تنگه (نام انگلیسی برای تطابق دقیق با geography.json و countries.json)
    controller_country_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # وضعیت مسدودسازی تنگه
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    block_scope: Mapped[str] = mapped_column(
        String(16), default=StraitBlockScope.NONE.value, nullable=False
    )  # NONE, ALL, CUSTOM

    # عوارض عبور پایه برای همه کشورها (دلار)
    default_toll: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<StraitConfig {self.strait_id} ({self.name_fa}) controller={self.controller_country_name}>"


class StraitBlockRule(Base):
    """
    قوانین اختصاصی مسدودسازی یا عوارض ویژه برای هر کشور روی یک تنگه خاص.
    """

    __tablename__ = "strait_block_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strait_id: Mapped[str] = mapped_column(
        ForeignKey("strait_configs.strait_id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id", ondelete="CASCADE"), nullable=False, index=True
    )

    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # عوارض سفارشی (اگر None باشد، از default_toll تنگه تبعیت می‌کند)
    custom_toll: Mapped[float | None] = mapped_column(Float, nullable=True)

    def __repr__(self) -> str:
        return f"<StraitBlockRule {self.strait_id} -> country={self.target_country_id} blocked={self.is_blocked}>"


class BlockedCargo(Base):
    """
    محموله‌های توقیف‌شده در تنگه‌ها و اموال بلوکه‌شده در دست کشور کنترل‌کننده.
    """

    __tablename__ = "blocked_cargos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # کشوری که در حال حاضر بار را در توقیف / بلوکه نگه داشته است
    holding_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # کشور فروشنده (فرستنده اصلی)
    source_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id", ondelete="CASCADE"), nullable=False
    )
    # کشور خریدار (مقصد اصلی)
    dest_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id", ondelete="CASCADE"), nullable=False
    )

    resource: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    strait_id: Mapped[str] = mapped_column(String(32), nullable=False)

    original_sale_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<BlockedCargo {self.resource} x{self.amount} held_by={self.holding_country_id} at {self.strait_id}>"
