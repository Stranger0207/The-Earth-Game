"""مدل پروژه‌ها / رول‌های امنیتی و دفاعی (آپدیت شماره ۲)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ...enums import SecurityRoleStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SecurityRole(Base):
    """
    مدل پروژه‌های امنیتی کشورها:
    - پیش‌نویس ۱ تا ۵ صفحه‌ای (هر صفحه حداکثر ۴۰۰۰ کاراکتر)
    - کسر ۲۰ میلیون دلار هنگام ارسال نهایی
    - ارسال به گروه رول امنیتی (-1004317826815)
    - تایید (افزودن به آرشیو امنیتی کشور) یا رد (با ذکر دلیل و عودت ۲۰ میلیون دلار).
    """

    __tablename__ = "security_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(64), nullable=False)
    page_1: Mapped[str] = mapped_column(Text, nullable=False)
    page_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_3: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_4: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_5: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), default=SecurityRoleStatus.DRAFT.value, nullable=False, index=True
    )

    # شناسه پیام ارسالی در گروه رول امنیتی (-1004317826815)
    admin_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # دلیل رد توسط ادمین در صورت رد شدن رول
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # آیدی عددی ادمین بررسی‌کننده
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def total_pages(self) -> int:
        """تعداد کل صفحات ثبت‌شده (۱ تا ۵)."""
        count = 1
        for p in (self.page_2, self.page_3, self.page_4, self.page_5):
            if p and p.strip():
                count += 1
            else:
                break
        return count

    def get_page_text(self, page_num: int) -> str:
        """دریافت متن صفحه بر اساس شماره صفحه (۱ تا ۵)."""
        pages = [self.page_1, self.page_2, self.page_3, self.page_4, self.page_5]
        idx = max(0, min(page_num - 1, 4))
        content = pages[idx]
        return content if content else (self.page_1 or "")

    def set_page_text(self, page_num: int, text_content: str) -> None:
        """تنظیم متن یک صفحه مشخص."""
        if page_num == 1:
            self.page_1 = text_content
        elif page_num == 2:
            self.page_2 = text_content
        elif page_num == 3:
            self.page_3 = text_content
        elif page_num == 4:
            self.page_4 = text_content
        elif page_num == 5:
            self.page_5 = text_content

    def __repr__(self) -> str:
        return f"<SecurityRole id={self.id} country_id={self.country_id} status={self.status} title={self.title!r}>"
