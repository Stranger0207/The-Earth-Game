"""مدل‌های پایگاه داده برای گیم‌مود مقاماتی (کابینه دولت ایالات متحده آمریکا)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base

if TYPE_CHECKING:
    from .user import User


def _utcnow() -> datetime:
    """زمان فعلی به‌صورت UTC آگاه از منطقه‌ی زمانی."""
    return datetime.now(timezone.utc)


class CabinetMember(Base):
    """عضو کابینه و مقام فدرال در گیم‌مود مقاماتی."""

    __tablename__ = "cabinet_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # کلید یکتای نقش از CabinetRole (مثلاً 'president', 'secretary_state')
    role_key: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    # کاربری که این سمت را بر عهده گرفته است (در صورت خالی بودن = سمت آزاد)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="SET NULL"), unique=True, nullable=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    custom_title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # شاخص رضایت و محبوبیت عملکرد این مقام (۰ تا ۱۰۰)
    approval_rating: Mapped[float] = mapped_column(Float, default=50.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    user: Mapped["User | None"] = relationship(back_populates="cabinet_member")

    def __repr__(self) -> str:
        return f"<CabinetMember role={self.role_key} user_id={self.user_id}>"


class CabinetMemo(Base):
    """مکاتبات و یادداشت‌های درون‌سازمانی و نامه‌های بین اعضای کابینه."""

    __tablename__ = "cabinet_memos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sender_role: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient_role: Mapped[str] = mapped_column(String(32), nullable=False)  # role_key یا 'all'
    sender_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject: Mapped[str] = mapped_column(String(256), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_urgent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class CabinetInquiry(Base):
    """استعلام اطلاعات رسمی بین ارگان‌ها و وزارتخانه‌ها."""

    __tablename__ = "cabinet_inquiries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_role: Mapped[str] = mapped_column(String(32), nullable=False)
    to_role: Mapped[str] = mapped_column(String(32), nullable=False)
    sender_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    topic: Mapped[str] = mapped_column(String(128), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)  # pending, answered, rejected
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CabinetInspection(Base):
    """حکم و گزارش بازرسی ویژه دادستان کل / وزارت دادگستری از ارگان‌ها."""

    __tablename__ = "cabinet_inspections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_role: Mapped[str] = mapped_column(String(32), nullable=False)
    target_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    initiated_by_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    findings: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="open", nullable=False)  # open, completed
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class CabinetMeeting(Base):
    """دیدارها و تماس‌های امن بین اعضای کابینه."""

    __tablename__ = "cabinet_meetings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    host_role: Mapped[str] = mapped_column(String(32), nullable=False)
    guest_role: Mapped[str] = mapped_column(String(32), nullable=False)
    host_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    guest_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    meeting_type: Mapped[str] = mapped_column(String(24), default="meeting", nullable=False)  # meeting یا call
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)  # pending, active, ended, rejected
    last_msg_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class CabinetActionLog(Base):
    """لاگ رسمی فعالیت‌ها و فرامین صادره توسط مقامات در کابینه."""

    __tablename__ = "cabinet_action_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_key: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
