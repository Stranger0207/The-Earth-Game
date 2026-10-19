"""
مدل‌های سازمان ملل متحد (UN)، اجلاس مجمع عمومی در نیویورک، دیوان بین‌المللی دادگستری (ICJ) و قطعنامه‌ها.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UNAssemblySession(Base):
    """یک دوره‌ی اجلاس سالانه مجمع عمومی سازمان ملل متحد در نیویورک."""

    __tablename__ = "un_assembly_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)  # pending | active | closed
    title: Mapped[str] = mapped_column(
        String(255), default="اجلاس سالانه مجمع عمومی سازمان ملل متحد - نیویورک", nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # سخنران فعلی پشت تریبون
    current_speaker_country_id: Mapped[int | None] = mapped_column(
        ForeignKey("countries.id", ondelete="SET NULL"), nullable=True
    )
    speech_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # سیستم رای‌گیری فوری در صحن مجمع
    voting_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    voting_topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_msg_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<UNAssemblySession #{self.session_number} status={self.status}>"


class UNAssemblyParticipant(Base):
    """وضعیت و موقعیت یک کشور در اجلاس سالانه نیویورک."""

    __tablename__ = "un_assembly_participants"
    __table_args__ = (
        UniqueConstraint("session_id", "country_id", name="uq_un_session_country"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("un_assembly_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # in_flight | in_new_york | inside_hall | left
    status: Mapped[str] = mapped_column(String(32), default="in_flight", nullable=False)
    travel_eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    joined_hall_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    walkout: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<UNAssemblyParticipant session={self.session_id} country={self.country_id} status={self.status}>"


class UNSpeechQueue(Base):
    """صف نوبت سخنرانی ۵ دقیقه‌ای کشورهای حاضر در تالار مجمع عمومی."""

    __tablename__ = "un_speech_queues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("un_assembly_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # waiting | speaking | done | skipped
    status: Mapped[str] = mapped_column(String(32), default="waiting", nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # متن تجمیع‌شده‌ی سخنرانی و کپشن‌های عکس برای ارسال به AI
    speech_transcript: Mapped[str] = mapped_column(Text, default="", nullable=False)

    def __repr__(self) -> str:
        return f"<UNSpeechQueue session={self.session_id} country={self.country_id} status={self.status}>"


class InternationalCourtCase(Base):
    """یک پرونده در دیوان بین‌المللی دادگستری (دادگاه لاهه - ICJ)."""

    __tablename__ = "international_court_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    claimant_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    defendant_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # strait_block | military_attack | nuclear_violation | treaty_breach | sanction | custom
    issue_type: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_title: Mapped[str] = mapped_column(String(255), nullable=False)
    claim_description: Mapped[str] = mapped_column(Text, nullable=False)
    demanded_compensation: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # pending | trial | verdict_issued | dismissed
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    # کشوری که در جلسه دادگاه تریبون صحبت را در دست دارد (None یعنی تریبون آزاد همه)
    current_turn_country_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # acquittal | compensation | release_cargo | sanction_auth
    verdict_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verdict_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    compensation_awarded: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    blocked_cargo_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<InternationalCourtCase #{self.case_number} status={self.status}>"


class CourtParty(Base):
    """طرف‌ها، شاکی، متهم یا شهود حاضر در یک پرونده دادگاه لاهه."""

    __tablename__ = "court_parties"
    __table_args__ = (
        UniqueConstraint("case_id", "country_id", name="uq_court_case_country"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("international_court_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # claimant | defendant | witness | judge
    role: Mapped[str] = mapped_column(String(32), default="claimant", nullable=False)
    can_speak: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:
        return f"<CourtParty case={self.case_id} country={self.country_id} role={self.role}>"


class UNResolution(Base):
    """یک قطعنامه مجمع عمومی یا شورای امنیت سازمان ملل."""

    __tablename__ = "un_resolutions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resolution_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("un_assembly_sessions.id", ondelete="SET NULL"), nullable=True
    )
    proposed_by_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # voting | adopted | rejected
    status: Mapped[str] = mapped_column(String(32), default="voting", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<UNResolution #{self.resolution_number} status={self.status}>"


class UNResolutionVote(Base):
    """رای یک کشور به قطعنامه سازمان ملل."""

    __tablename__ = "un_resolution_votes"
    __table_args__ = (
        UniqueConstraint("resolution_id", "country_id", name="uq_resolution_country_vote"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resolution_id: Mapped[int] = mapped_column(
        ForeignKey("un_resolutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # yes | no | abstain
    vote: Mapped[str] = mapped_column(String(16), nullable=False)
    voted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<UNResolutionVote res={self.resolution_id} country={self.country_id} vote={self.vote}>"
