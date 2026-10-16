"""مدل رول‌ها و عملیات‌های نظامی: خرابکاری، ترور، حمله (آپدیت شماره ۲)."""

from __future__ import annotations

from datetime import datetime, timezone
import json

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ...constants import (
    MILITARY_ROLE_ASSASSINATION_MAX_PAGES,
    MILITARY_ROLE_ATTACK_MAX_PAGES,
    MILITARY_ROLE_SABOTAGE_MAX_PAGES,
)
from ...enums import MilitaryRoleStatus, MilitaryRoleType


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MilitaryRole(Base):
    """
    مدل رول‌های نظامی و عملیاتی:
    - ۳ نوع عملیات: خرابکاری (حداکثر ۲ صفحه)، ترور (حداکثر ۳ صفحه)، حمله (حداکثر ۵ صفحه)
    - دارای کشور مهاجم و کشور هدف مشخص
    - بدون دکمه تایید/رد در گروه مدیریت؛ دارای دکمه‌های ثبت تلفات دوطرفه و پایان عملیات
    - ارسال پیام رسمی پایان عملیات به کشور مهاجم و کشور هدف
    """

    __tablename__ = "military_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attacker_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    target_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    op_type: Mapped[str] = mapped_column(
        String(32), default=MilitaryRoleType.ATTACK.value, nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(64), nullable=False)

    page_1: Mapped[str] = mapped_column(Text, nullable=False)
    page_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_3: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_4: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_5: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), default=MilitaryRoleStatus.DRAFT.value, nullable=False, index=True
    )

    # شناسه پیام ارسالی در گروه رول نظامی (-1004424329237)
    admin_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # ثبت تاریخچه و خلاصه‌ی تلفات وارده به صورت JSON
    casualties_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    # آیدی عددی ادمین ثبت‌کننده تلفات یا مختومه‌کننده
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def max_allowed_pages(self) -> int:
        """حداکثر صفحات مجاز با توجه به نوع عملیات."""
        if self.op_type == MilitaryRoleType.SABOTAGE.value:
            return MILITARY_ROLE_SABOTAGE_MAX_PAGES
        elif self.op_type == MilitaryRoleType.ASSASSINATION.value:
            return MILITARY_ROLE_ASSASSINATION_MAX_PAGES
        return MILITARY_ROLE_ATTACK_MAX_PAGES

    @property
    def total_pages(self) -> int:
        """تعداد کل صفحات ثبت‌شده بر اساس سقف مجاز."""
        all_pages = [self.page_1, self.page_2, self.page_3, self.page_4, self.page_5]
        limit = self.max_allowed_pages
        count = 1
        for idx in range(1, limit):
            p = all_pages[idx]
            if p and p.strip():
                count += 1
            else:
                break
        return count

    def get_page_text(self, page_num: int) -> str:
        """دریافت متن صفحه بر اساس شماره صفحه."""
        pages = [self.page_1, self.page_2, self.page_3, self.page_4, self.page_5]
        idx = max(0, min(page_num - 1, self.max_allowed_pages - 1))
        content = pages[idx]
        return content if content else (self.page_1 or "")

    def set_page_text(self, page_num: int, text_content: str) -> None:
        """تنظیم متن صفحه متناسب با شماره صفحه."""
        if page_num == 1:
            self.page_1 = text_content
        elif page_num == 2 and self.max_allowed_pages >= 2:
            self.page_2 = text_content
        elif page_num == 3 and self.max_allowed_pages >= 3:
            self.page_3 = text_content
        elif page_num == 4 and self.max_allowed_pages >= 4:
            self.page_4 = text_content
        elif page_num == 5 and self.max_allowed_pages >= 5:
            self.page_5 = text_content

    @property
    def casualties_list(self) -> list[dict]:
        """فهرست ساختاریافته‌ی تلفات ثبت‌شده روی عملیات."""
        try:
            return json.loads(self.casualties_json or "[]")
        except Exception:
            return []

    @casualties_list.setter
    def casualties_list(self, val: list[dict]) -> None:
        self.casualties_json = json.dumps(val, ensure_ascii=False)

    def add_casualty(self, casualty_info: dict) -> None:
        """افزودن یک ردیف تلفات جدید به سوابق این عملیات."""
        current = self.casualties_list
        current.append(casualty_info)
        self.casualties_list = current

    def __repr__(self) -> str:
        return (
            f"<MilitaryRole id={self.id} type={self.op_type} attacker={self.attacker_country_id} "
            f"target={self.target_country_id} status={self.status} title={self.title!r}>"
        )
