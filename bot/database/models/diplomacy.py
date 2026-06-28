"""مدل‌های دیپلماسی: قرارداد، تماس تلفنی، دیدار حضوری، تحریم."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ...enums import DiplomacyStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Contract(Base):
    """
    قرارداد/معاهده میان دو کشور (طبق «فرم قرارداد» پلی‌بوک).
    body متن کامل قرارداد را نگه می‌دارد و پس از امضای هر دو طرف، فعال می‌شود.
    """

    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_a: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    country_b: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(256), default="قرارداد دوجانبه")
    # متن کامل قرارداد (فرم پرشده)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # امضای هر طرف
    signed_a: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    signed_b: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), default=DiplomacyStatus.PENDING, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<Contract {self.country_a}<->{self.country_b} {self.status}>"


class PhoneCall(Base):
    """
    تماس تلفنی میان دو کشور (حداکثر ۵ دقیقه، بدون امکان قرارداد).
    گفتگو در ربات به‌صورت متنی ردوبدل و به گروه لاگ مدیران فرستاده می‌شود.
    """

    __tablename__ = "phone_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # کشور درخواست‌کننده و کشور مقصد
    caller_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    callee_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    status: Mapped[str] = mapped_column(
        String(16), default=DiplomacyStatus.PENDING, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<PhoneCall {self.caller_country}->{self.callee_country} {self.status}>"


class PhoneCallMessage(Base):
    """یک پیام متنی در جریان یک تماس تلفنی (برای لاگ و ارسال به طرف مقابل)."""

    __tablename__ = "phone_call_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[int] = mapped_column(
        ForeignKey("phone_calls.id"), nullable=False, index=True
    )
    sender_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class Meeting(Base):
    """
    دیدار حضوری میان دو کشور.
    ابتدا سفر (با زمان تخمینی AI) انجام می‌شود، سپس جلسه‌ی یک‌ساعته فعال می‌گردد
    که در آن می‌توان قرارداد بست.
    """

    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    traveler_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    host_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    status: Mapped[str] = mapped_column(
        String(16), default=DiplomacyStatus.PENDING, nullable=False
    )
    # زمان رسیدن مسافر (پایان سفر) و زمان پایان جلسه
    travel_eta: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    meeting_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # توضیح AI درباره‌ی زمان سفر (در v1.10.1 دیگر استفاده نمی‌شود؛ برای سازگاری مانده)
    travel_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # آیا خبر شروع نشست (پس از رسیدن مسافر) در کانال اعلام شده؟ (v1.6)
    start_announced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # زمان آخرین پیام ردوبدل‌شده در نشست فعال — برای تایم‌اوت سکوت ۱۰ دقیقه (v1.10.1)
    last_msg_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<Meeting {self.traveler_country}->{self.host_country} {self.status}>"


class Sanction(Base):
    """تحریم یک کشور علیه کشور دیگر (بخش اقتصادی/دیپلماسی)."""

    __tablename__ = "sanctions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    to_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    # نوع تحریم (مقدار SanctionType) — v1.5
    sanction_type: Mapped[str] = mapped_column(String(24), default="", nullable=False)
    # توضیح تحریم
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<Sanction {self.from_country}->{self.to_country} active={self.active}>"


class Speech(Base):
    """سخنرانی/بیانیه‌ی رئیس‌جمهور که در کانال دیپلماسی منتشر می‌شود (v1.5)."""

    __tablename__ = "speeches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    speaker_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    # آی‌دی پیام منتشرشده در کانال دیپلماسی (برای ریپلای نقل قول)
    channel_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class GroupMeeting(Base):
    """
    دیدار حضوری چندجانبه (چند کشوره).
    یک کشور میزبان است و چند کشور را دعوت می‌کند؛ هر دعوت‌شده باید جداگانه تأیید کند.
    وقتی همه پاسخ دادند، جلسه با کشورهای تأییدکننده فعال می‌شود.
    """

    __tablename__ = "group_meetings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    host_country: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(256), default="نشست چندجانبه")
    status: Mapped[str] = mapped_column(
        String(16), default=DiplomacyStatus.PENDING, nullable=False
    )
    # زمان شروع نشست = لحظه‌ی رسیدن آخرین کشور (v1.5)
    start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    meeting_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # زمان آخرین پیام ردوبدل‌شده در نشست فعال — برای تایم‌اوت سکوت ۱۰ دقیقه (v1.10.1)
    last_msg_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<GroupMeeting host={self.host_country} {self.status}>"


class GroupMeetingParticipant(Base):
    """یک شرکت‌کننده در دیدار چندجانبه و وضعیت پاسخ او به دعوت."""

    __tablename__ = "group_meeting_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[int] = mapped_column(
        ForeignKey("group_meetings.id"), nullable=False, index=True
    )
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    # وضعیت پاسخ این کشور به دعوت (pending/active=پذیرفته/rejected)
    response: Mapped[str] = mapped_column(
        String(16), default=DiplomacyStatus.PENDING, nullable=False
    )
    # زمان رسیدن این کشور به میزبان (پس از پذیرش، پرواز شبیه‌سازی می‌شود) — v1.5
    travel_eta: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<GroupParticipant meeting={self.meeting_id} country={self.country_id} {self.response}>"
