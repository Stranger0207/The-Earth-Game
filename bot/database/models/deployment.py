"""مدل استقرار نیرو (v1.11) — فقط کشورهای VIP می‌توانند نیرو مستقر کنند."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Deployment(Base):
    """
    یک گروه نیروی مستقرشده: نوع کلان (زمینی/دریایی/هوایی)، قلم تجهیزات، تعداد، منطقه‌ی هدف
    و هزینه‌ی نفت پرداخت‌شده. تجهیزات از موجودی کشور کم نمی‌شوند (فقط نفت کسر می‌شود).
    """

    __tablename__ = "deployments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    # کلید دسته‌ی کلان: ground / navy / air (مقدار از DEPLOY_BRANCHES)
    branch_key: Mapped[str] = mapped_column(String(16), nullable=False)
    # نام فارسی دسته برای نمایش (زمینی/دریایی/هوایی)
    branch_fa: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    asset_name: Mapped[str] = mapped_column(String(128), nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    region: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    oil_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # میلیون بشکه
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<Deployment {self.country_id} {self.branch_key} {self.asset_name} x{self.count}>"
