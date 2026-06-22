"""مدل حملات نظامی."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ...enums import AttackStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Attack(Base):
    """
    یک حمله از کشور مهاجم به کشور مدافع.
    payload توضیح متنی/تجهیزات انتخاب‌شده، و result نتیجه و تلفات (تولیدشده توسط AI) را نگه می‌دارد.
    """

    __tablename__ = "attacks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attacker_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    defender_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    # نوع حمله (مقدار AttackType)
    type: Mapped[str] = mapped_column(String(16), nullable=False)

    # توضیح بازیکن و تجهیزات انتخابی (متن آزاد)
    payload: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # سوخت لازم (میلیون بشکه نفت) که AI تخمین زده
    fuel_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # نتیجه‌ی نهایی (متن خلاصه + تلفات) — پس از سنجش AI پر می‌شود
    result: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), default=AttackStatus.PENDING, nullable=False
    )
    # زمان اعلام نتیجه (ممکن است از چند دقیقه تا چند ساعت طول بکشد)
    resolve_eta: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<Attack {self.type} {self.attacker_country}->"
            f"{self.defender_country} {self.status}>"
        )
