"""مدل کشور به‌همراه شاخص‌های اقتصادی و سیاست داخلی."""

from __future__ import annotations

from typing import TYPE_CHECKING
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    DateTime,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base

if TYPE_CHECKING:
    from .facility import Facility
    from .military import MilitaryAsset
    from .reserves import Reserve
    from .user import User


class Country(Base):
    """
    یک کشور در بازی.
    شاخص‌های اقتصادی (طبق فرمت پلی‌بوک) و رضایت عمومی مستقیماً اینجا نگه داشته می‌شوند.
    """

    __tablename__ = "countries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # --- اطلاعات پایه ---
    name_en: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name_fa: Mapped[str] = mapped_column(String(64), nullable=False)
    flag: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    region: Mapped[str] = mapped_column(String(32), nullable=False)
    is_vip: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    population: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # --- مالکیت ---
    owner_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=True
    )
    is_claimed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- شاخص‌های اقتصادی (📊 گزارش وضعیت اقتصادی) ---
    economic_power: Mapped[float] = mapped_column(Float, default=50.0)   # از ۱۰۰
    budget: Mapped[float] = mapped_column(Float, default=0.0)            # دلار
    growth: Mapped[str] = mapped_column(String(8), default="flat")       # up/flat/down
    inflation: Mapped[float] = mapped_column(Float, default=0.0)         # درصد
    unemployment: Mapped[float] = mapped_column(Float, default=0.0)      # درصد
    energy_status: Mapped[str] = mapped_column(String(16), default="medium")  # weak/medium/good/excellent
    foreign_trade: Mapped[str] = mapped_column(String(16), default="balanced")  # negative/balanced/positive
    govt_debt: Mapped[float] = mapped_column(Float, default=0.0)         # دلار

    # --- سیاست داخلی ---
    public_satisfaction: Mapped[float] = mapped_column(Float, default=60.0)  # رضایت عمومی (۰ تا ۱۰۰)
    stability: Mapped[float] = mapped_column(Float, default=60.0)            # ثبات داخلی (۰ تا ۱۰۰)

    # --- حاکمیت (v1.10.2) ---
    government_type: Mapped[str] = mapped_column(String(24), default="", nullable=False)  # نوع نظام (خالی = انتخاب نشده)
    govt_changes_left: Mapped[int] = mapped_column(Integer, default=2, nullable=False)    # تعداد تغییرات مجاز (پیش‌فرض ۲)
    tax_rate: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)          # نرخ مالیات (درصد)
    last_tax_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True) # آخرین زمان جمع‌آوری مالیات
    last_protest_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True) # آخرین بررسی اعتراضات

    # --- عوارض بین‌المللی (v1.5) — فقط برای آمریکا معنا دارد: مجموع تعرفه‌های جمع‌آوری‌شده ---
    international_duties: Mapped[float] = mapped_column(Float, default=0.0)

    # --- توان نظامی (v1.10.6) ---
    # آمادگی رزمی (۰ تا ۴۰): با رزمایش بالا می‌رود، روزانه افت می‌کند و
    # مستقیماً قدرت عملیات نظامی کشور را تقویت می‌کند.
    readiness: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    last_readiness_decay_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # پس از ترور موفق رئیس‌جمهور، کشور تا این لحظه در «بحران رهبری» است
    # و نمی‌تواند عملیات نظامی جدید ثبت کند.
    leadership_crisis_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- روابط ---
    owner: Mapped["User | None"] = relationship(back_populates="country")
    reserves: Mapped[list["Reserve"]] = relationship(
        back_populates="country", cascade="all, delete-orphan"
    )
    facilities: Mapped[list["Facility"]] = relationship(
        back_populates="country", cascade="all, delete-orphan"
    )
    military_assets: Mapped[list["MilitaryAsset"]] = relationship(
        back_populates="country", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Country {self.name_en} claimed={self.is_claimed}>"
