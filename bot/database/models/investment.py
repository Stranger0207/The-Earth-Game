"""مدل سرمایه‌گذاری داخلی/خارجی (v1.9)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String

from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Investment(Base):
    """
    یک سرمایه‌گذاری روی یک «دسته» (مثلاً گردشگری) که هر ۲۴ ساعت برای سرمایه‌گذار سود نقدی
    تولید می‌کند. اگر کشور هدف با سرمایه‌گذار فرق کند، «سرمایه‌گذاری خارجی» است و علاوه بر
    سود نقدیِ سرمایه‌گذار، اثرات اجتماعی (رضایت/بیکاری/تورم) روی کشور هدف اعمال می‌شود.
    """

    __tablename__ = "investments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investor_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    target_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    # کلید دسته‌ی سرمایه‌گذاری (مقدار از INVESTMENT_CATEGORIES)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # اصل سرمایه (دلار)
    profit_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # درصد سود ۲۴ساعته

    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_yield_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    @property
    def is_foreign(self) -> bool:
        """آیا سرمایه‌گذاری خارجی است؟ (هدف ≠ سرمایه‌گذار)."""
        return self.target_country != self.investor_country

    def __repr__(self) -> str:
        return f"<Investment {self.category} {self.investor_country}->{self.target_country}>"
