"""مدل پروژه‌ها / رول‌های اقتصادی (آپدیت شماره ۹)."""

from __future__ import annotations

from datetime import datetime, timezone
import json

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ...enums import EconomicProjectStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EconomicProject(Base):
    """
    چرخه حیات کامل یک پروژه / رول اقتصادی:
    - پیش‌نویس ۱ یا ۲ صفحه‌ای (حداکثر ۴۰۰۰ کاراکتر در هر صفحه)
    - ارسال نهایی به گروه رول اقتصادی (-1004359181892)
    - داوری ادمین (رد با ذکر دلیل یا تأیید همراه با تعیین هزینه و سود)
    - کسر هزینه و فعال‌سازی یا انتظار تأمین هزینه توسط کشور
    - چرخه بازدهی ۷۲ ساعته دلاری و ذخایری در زمان‌بند.
    """

    __tablename__ = "economic_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(64), nullable=False)
    page_1: Mapped[str] = mapped_column(Text, nullable=False)
    page_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_budget: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    status: Mapped[str] = mapped_column(
        String(32), default=EconomicProjectStatus.DRAFT.value, nullable=False, index=True
    )

    # شناسه پیام ارسالی در گروه رول اقتصادی (-1004359181892)
    admin_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # دلیل رد توسط ادمین در صورت رد
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # هزینه‌های افتتاح تعیین‌شده توسط مدیریت
    launch_cost_cash: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    launch_cost_resources: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    # سود و بازدهی هر ۷۲ ساعت
    yield_cash_72h: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    yield_resources_72h: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    last_yield_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_yield_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # آیدی عددی تلگرام ادمین بررسی‌کننده
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    @property
    def launch_resources_dict(self) -> dict[str, float]:
        """دیکشنری منابع مورد نیاز برای افتتاح."""
        try:
            return json.loads(self.launch_cost_resources or "{}")
        except Exception:
            return {}

    @launch_resources_dict.setter
    def launch_resources_dict(self, val: dict[str, float]) -> None:
        self.launch_cost_resources = json.dumps(val, ensure_ascii=False)

    @property
    def yield_resources_dict(self) -> dict[str, float]:
        """دیکشنری منابع بازدهی هر ۷۲ ساعت."""
        try:
            return json.loads(self.yield_resources_72h or "{}")
        except Exception:
            return {}

    @yield_resources_dict.setter
    def yield_resources_dict(self, val: dict[str, float]) -> None:
        self.yield_resources_72h = json.dumps(val, ensure_ascii=False)

    @property
    def total_pages(self) -> int:
        """تعداد کل صفحات پروژه (۱ یا ۲)."""
        return 2 if (self.page_2 and self.page_2.strip()) else 1

    def get_page_text(self, page_num: int) -> str:
        """دریافت متن صفحه بر اساس شماره صفحه (۱ یا ۲)."""
        if page_num == 2 and self.page_2 and self.page_2.strip():
            return self.page_2
        return self.page_1

    def __repr__(self) -> str:
        return f"<EconomicProject id={self.id} country_id={self.country_id} status={self.status} title={self.title!r}>"
