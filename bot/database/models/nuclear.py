"""مدل‌های برنامه‌ی توسعه‌ی هسته‌ای (v1.10.4) — فقط کشورهای VIP."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NuclearProgram(Base):
    """
    برنامه‌ی هسته‌ای یک کشور (یک ردیف به ازای هر کشور).
    انبارهای زنجیره‌ی سوخت و شاخص افشا اینجا نگه داشته می‌شوند.
    """

    __tablename__ = "nuclear_programs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, unique=True, index=True
    )

    # بالاترین فازی که کشور به آن رسیده است (مقدار NuclearPhase)
    phase: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ---------- انبارهای زنجیره‌ی سوخت ----------
    yellowcake_tons: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # کیک زرد (تن)
    uf6_tons: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)         # گاز UF6 (تن)
    # اورانیوم غنی‌شده به تفکیک رده (کیلوگرم)
    leu_35_kg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)   # ۳.۵٪
    leu_20_kg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)   # ۲۰٪
    heu_60_kg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)   # ۶۰٪
    heu_90_kg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)   # ۹۰٪

    # ---------- سانتریفیوژ و غنی‌سازی ----------
    centrifuges: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # چرخه‌ی تولید سانتریفیوژ در حال ساخت (زمان اتمام)
    centrifuge_batch_done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # رده‌ی هدفِ غنی‌سازی فعال (کلید ENRICHMENT_TIERS) — None یعنی متوقف
    enrich_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # تعداد سانتریفیوژهای تخصیص‌یافته به غنی‌سازی فعال
    enrich_centrifuges: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # SWU انباشته‌ی رده‌ی جاری (تا رسیدن به آستانه‌ی تولید محصول)
    swu_accumulated: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    enrich_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_enrich_tick_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ---------- پنهان‌کاری و افشا ----------
    exposure: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # ۰ تا ۱۰۰
    is_discovered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    discovered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # پوشش صلح‌آمیز فعال (سقف رده در عوض افشای کمتر)
    civilian_cover: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # عضویت در NPT (خروج از آن افشا و فشار بین‌المللی می‌آورد)
    npt_member: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_counterintel_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # آخرین اجرای پردازش ۲۴ساعته‌ی تأسیسات (آسیاب/تبدیل)
    last_chain_tick_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<NuclearProgram country={self.country_id} phase={self.phase}>"


class NuclearTech(Base):
    """یک فناوری هسته‌ای در حال تحقیق یا تکمیل‌شده."""

    __tablename__ = "nuclear_techs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    tech_type: Mapped[str] = mapped_column(String(32), nullable=False)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<NuclearTech {self.tech_type} country={self.country_id} done={self.is_done}>"


class NuclearFacility(Base):
    """یک تأسیسات هسته‌ای (آسیاب، تبدیل، سالن غنی‌سازی، آزمایشگاه، سایت آزمایش)."""

    __tablename__ = "nuclear_facilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    facility_type: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    location: Mapped[str] = mapped_column(String(128), default="", nullable=False)

    status: Mapped[str] = mapped_column(String(16), default="building", nullable=False)
    is_underground: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # سلامت سازه (۰ تا ۱۰۰) — با حمله/خرابکاری کاهش می‌یابد
    integrity_pct: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)

    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    built_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<NuclearFacility {self.facility_type} country={self.country_id} status={self.status}>"


class NuclearWarhead(Base):
    """یک کلاهک هسته‌ای در زرادخانه‌ی کشور."""

    __tablename__ = "nuclear_warheads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="assembling", nullable=False)
    yield_kt: Mapped[float] = mapped_column(Float, default=20.0, nullable=False)
    heu_used_kg: Mapped[float] = mapped_column(Float, default=25.0, nullable=False)
    # سامانه‌ی حمل نصب‌شده (مقدار DeliverySystem) — None یعنی در انبار
    delivery_system: Mapped[str | None] = mapped_column(String(16), nullable=True)

    assembled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<NuclearWarhead country={self.country_id} status={self.status} kt={self.yield_kt}>"


class NuclearTest(Base):
    """یک آزمایش هسته‌ای (فاز ۵)."""

    __tablename__ = "nuclear_tests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    site_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    yield_kt: Mapped[float] = mapped_column(Float, default=20.0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    warhead_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<NuclearTest country={self.country_id} status={self.status}>"


class NuclearInspection(Base):
    """درخواست بازرسی بین‌المللی از تأسیسات هسته‌ای یک کشور."""

    __tablename__ = "nuclear_inspections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # کشور درخواست‌کننده (بازرس) و کشور هدف
    requester_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    target_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    # pending | accepted | rejected
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    report: Mapped[str] = mapped_column(Text, default="", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<NuclearInspection {self.requester_id}→{self.target_id} {self.status}>"
