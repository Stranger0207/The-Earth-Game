"""مدل ذخایر استراتژیک هر کشور."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base

if TYPE_CHECKING:
    from .country import Country


class Reserve(Base):
    """
    یک ردیف ذخیره برای یک کشور (مثلاً آهنِ ایران).
    can_extract مشخص می‌کند آیا کشور توان استخراج این منبع را دارد یا نه
    (مثلاً آذربایجان نمی‌تواند نفت استخراج کند).
    """

    __tablename__ = "reserves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    # نوع ذخیره (مقدار ResourceType به‌صورت رشته)
    resource: Mapped[str] = mapped_column(String(16), nullable=False)

    # مقدار موجود (واحد بسته به نوع منبع: تن/میلیون بشکه/کیلوگرم/...)
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # آیا این کشور توان استخراج این منبع را دارد؟
    can_extract: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # بازدهی طبیعیِ پیش‌فرض در هر ۲۴ ساعت (پیش از ساخت معدن/سکو)
    base_yield: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # بازدهی طبیعی تا این زمان فعال است (پلی‌بوک: ۷۲ ساعت اولیه)
    yield_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    country: Mapped["Country"] = relationship(back_populates="reserves")

    def __repr__(self) -> str:
        return f"<Reserve {self.resource} amount={self.amount} country={self.country_id}>"
