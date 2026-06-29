"""مدل کاربر تلگرام."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base
from ...enums import UserRole

if TYPE_CHECKING:
    from .country import Country


def _utcnow() -> datetime:
    """زمان فعلی به‌صورت UTC آگاه از منطقه‌ی زمانی."""
    return datetime.now(timezone.utc)


class User(Base):
    """کاربر تلگرام که با ربات تعامل دارد."""

    __tablename__ = "users"

    # آی‌دی عددی تلگرام به‌عنوان کلید اصلی
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # نقش کاربر در سیستم (بازیکن/مدیر/مالک)
    role: Mapped[UserRole] = mapped_column(
        String(16), default=UserRole.PLAYER, nullable=False
    )

    # نام رئیس‌جمهور (نامی که کاربر برای رهبر کشورش انتخاب می‌کند؛ در اخبار استفاده می‌شود)
    president_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # تعلیق (v1.10.5): متمایز از بن کامل — پلیر معلق نمی‌تواند در کشورش اقدامی کند
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    # کشوری که این کاربر مالک آن است (در صورت وجود)
    country: Mapped["Country | None"] = relationship(
        back_populates="owner", uselist=False
    )

    def __repr__(self) -> str:  # برای دیباگ
        return f"<User id={self.telegram_id} role={self.role}>"
