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
    # سرمایه سیاسی مقام در کاخ سفید (۰ تا ۱۰۰، پیش‌فرض ۵۰) — v2.6
    political_capital: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    # بودجه اختصاصی وزارتخانه (بر حسب میلیون دلار) — v2.6
    allocated_budget: Mapped[float] = mapped_column(Float, default=10_000.0, nullable=False)
    # شاخص سوءظن امنیتی و درز اطلاعات (۰ تا ۱۰۰، پیش‌فرض ۰) — v2.6
    leak_suspicion: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # امتیاز کارآمدی عملکرد (۰ تا ۱۰۰، پیش‌فرض ۸۰) — v2.6
    efficiency_score: Mapped[int] = mapped_column(Integer, default=80, nullable=False)
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


class CabinetOperation(Base):
    """پرونده‌ها و عملیات‌های چندمرحله‌ای بوروکراتیک کابینه (v2.6)."""

    __tablename__ = "cabinet_operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    op_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    initiator_role: Mapped[str] = mapped_column(String(32), nullable=False)
    current_step: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    steps_json: Mapped[str] = mapped_column(Text, nullable=False)
    signed_by_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    budget_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CabinetCrisis(Base):
    """بحران‌های ساعتی و خودکار کابینه (v2.6)."""

    __tablename__ = "cabinet_crises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    primary_role: Mapped[str] = mapped_column(String(32), nullable=False)
    secondary_role: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    options_json: Mapped[str] = mapped_column(Text, nullable=False)
    primary_approved: Mapped[int | None] = mapped_column(Integer, nullable=True)
    secondary_approved: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CabinetBudgetRequest(Base):
    """درخواست‌های تخصیص بودجه ارسالی به وزیر خزانه‌داری (v2.6)."""

    __tablename__ = "cabinet_budget_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    requester_role: Mapped[str] = mapped_column(String(32), nullable=False)
    requester_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    treasury_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CabinetAgenda(Base):
    """اهداف و ماموریت‌های مخفی ۲۴ ساعته اعضای کابینه (v2.6)."""

    __tablename__ = "cabinet_agendas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_key: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    reward_capital: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CabinetLeak(Base):
    """درز اطلاعات ناشناس به رسانه‌ها علیه وزارتخانه‌ها (v2.6)."""

    __tablename__ = "cabinet_leaks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    leaker_role: Mapped[str] = mapped_column(String(32), nullable=False)
    leaker_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_role: Mapped[str] = mapped_column(String(32), nullable=False)
    leak_headline: Mapped[str] = mapped_column(String(256), nullable=False)
    leak_content: Mapped[str] = mapped_column(Text, nullable=False)
    is_discovered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    discovered_by_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

