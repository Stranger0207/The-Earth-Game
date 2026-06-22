"""مدل کشور به‌همراه شاخص‌های اقتصادی و سیاست داخلی."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
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
