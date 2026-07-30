"""مدل‌های سیستم حاکمیت: اعتراضات، قوانین و ویزا (v1.10.2)."""

from __future__ import annotations

from datetime import datetime, timezone

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
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Protest(Base):
    """
    یک اعتراض داخلی در کشور.
    اعتراضات به‌صورت تصادفی بر اساس شرایط (رضایت پایین، مالیات بالا و ...) تولید می‌شوند.
    """

    __tablename__ = "protests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(Integer, ForeignKey("countries.id"), nullable=False)

    # نوع و جزئیات
    protest_type: Mapped[str] = mapped_column(String(24), nullable=False)       # ProtestType
    title: Mapped[str] = mapped_column(String(256), nullable=False)              # عنوان فارسی
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)   # شرح وضعیت
    severity: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)  # شدت: ۱ تا ۱۰

    # وضعیت
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False)  # ProtestStatus
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # نتیجه‌ی تصمیم ادمین/AI

    def __repr__(self) -> str:
        return f"<Protest {self.id} country={self.country_id} type={self.protest_type} status={self.status}>"


class Law(Base):
    """
    لایحه‌ی پیشنهادی به مجلس.
    بازیکن متن قانون را می‌نویسد و ادمین (به‌عنوان نمایندگان مجلس) رأی می‌دهند.
    """

    __tablename__ = "laws"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(Integer, ForeignKey("countries.id"), nullable=False)

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)            # متن کامل لایحه
    law_type: Mapped[str] = mapped_column(String(24), default="custom", nullable=False)  # tax/visa/custom

    # وضعیت
    status: Mapped[str] = mapped_column(String(24), default="in_parliament", nullable=False)  # LawStatus
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    voted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    vote_result: Mapped[str | None] = mapped_column(Text, nullable=True)  # مثلاً «۱۵۲ موافق، ۸۸ مخالف»

    def __repr__(self) -> str:
        return f"<Law {self.id} country={self.country_id} status={self.status}>"


class VisaRequirement(Base):
    """
    الزام ویزا: کشور A مشخص می‌کند که شهروندان کشور B برای سفر نیاز به ویزا دارند.
    هر رکورد = یک ویزای اجباری.
    """

    __tablename__ = "visa_requirements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(Integer, ForeignKey("countries.id"), nullable=False)         # کشور وضع‌کننده
    target_country_id: Mapped[int] = mapped_column(Integer, ForeignKey("countries.id"), nullable=False)  # کشور هدف
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    def __repr__(self) -> str:
        return f"<Visa {self.country_id}→{self.target_country_id}>"
