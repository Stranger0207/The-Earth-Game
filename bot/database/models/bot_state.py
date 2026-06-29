"""مدل وضعیت سراسری ربات (v1.10.5) — حالت تعمیر/خاموشی.

یک سطرِ تکی (id=1) که وضعیت روشن/خاموش ربات را نگه می‌دارد:
- خاموشی فوری دستی (`maintenance`)
- بازه‌ی خاموشی روزانه‌ی تکرارشونده به وقت تهران (`auto_off_*`)
"""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class BotState(Base):
    """وضعیت سراسری ربات (سطر تکی با id=1)."""

    __tablename__ = "bot_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    # خاموشی فوری دستی: اگر True باشد، پلیرهای عادی نمی‌توانند کاری انجام دهند
    maintenance: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # پیام نمایش‌داده‌شده هنگام خاموشی (اختیاری)
    maint_message: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # بازه‌ی خاموشی روزانه‌ی تکرارشونده (ساعت تهران، فرمت "HH:MM")
    auto_off_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_off_start: Mapped[str | None] = mapped_column(String(5), nullable=True)
    auto_off_end: Mapped[str | None] = mapped_column(String(5), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<BotState maintenance={self.maintenance} "
            f"auto={self.auto_off_enabled} {self.auto_off_start}-{self.auto_off_end}>"
        )
