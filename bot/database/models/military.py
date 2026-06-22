"""مدل تجهیزات نظامی هر کشور."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base

if TYPE_CHECKING:
    from .country import Country


class MilitaryAsset(Base):
    """
    یک قلم تجهیزات نظامی (مثلاً «جنگنده F-22 Raptor» با تعداد ۱۸۰).
    دسته‌بندی (category) مطابق پنل پلی‌بوک: نیروی زمینی/هوایی/دریایی/سامانه دفاعی و ... .
    """

    __tablename__ = "military_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    # دسته‌بندی نمایشی در پنل (مثلاً "جنگنده"، "تانک"، "ناوشکن")
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    # عنوان زیربخش (مثلاً "نیروی هوایی"، "نیروی دریایی")
    branch: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    # نام تجهیزات (مثلاً "F-22 Raptor")
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # واحد شمارش فارسی (فروند/دستگاه/عراده/سامانه/نفر)
    unit: Mapped[str] = mapped_column(String(16), default="عدد", nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    country: Mapped["Country"] = relationship(back_populates="military_assets")

    def __repr__(self) -> str:
        return f"<MilitaryAsset {self.name} x{self.count} country={self.country_id}>"
