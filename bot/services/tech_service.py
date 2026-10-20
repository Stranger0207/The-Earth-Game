"""
سرویس مدیریت تکنولوژی و لایسنس تسلیحاتی.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re

from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Country
from ..database.repositories import tech_transfer as tech_repo

logger = logging.getLogger(__name__)

_DATA_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "equipment_origins.json"
_ORIGINS_CACHE: dict[str, str] | None = None


def load_equipment_origins() -> dict[str, str]:
    """بارگذاری و کش بانک اطلاعاتی کشورهای سازنده تجهیزات."""
    global _ORIGINS_CACHE
    if _ORIGINS_CACHE is None:
        if _DATA_FILE.exists():
            try:
                _ORIGINS_CACHE = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error(f"Error loading equipment_origins.json: {e}")
                _ORIGINS_CACHE = {}
        else:
            _ORIGINS_CACHE = {}
    return _ORIGINS_CACHE


def get_equipment_origin(equipment_name: str) -> str | None:
    """
    دریافت نام انگلیسی کشور سازنده اصلی (Origin Country) یک تجهیز.
    """
    origins = load_equipment_origins()
    if equipment_name in origins:
        return origins[equipment_name]

    # پالایش پسوندهای توضیحی مانند (محدود) یا (غنیمتی)
    clean_name = re.sub(r"\s*\([^)]*\)", "", equipment_name).strip()
    if clean_name in origins:
        return origins[clean_name]

    return None


def is_native_equipment(country_en: str, equipment_name: str) -> bool:
    """
    آیا این سلاح برای این کشور بومی محسوب می‌شود؟
    (اگر کشور درخواست‌کننده همان سازنده اصلی باشد نیازی به لایسنس ندارد)
    """
    origin = get_equipment_origin(equipment_name)
    if origin is None:
        # اگر در دیتابیس یافت نشد، سلاح پیش‌فرض بومی تلقی می‌شود تا بازی قفل نشود
        return True
    return origin == country_en


async def can_produce_equipment(
    session: AsyncSession, country: Country, equipment_name: str
) -> tuple[bool, str | None]:
    """
    بررسی دسترسی کشور به دانش فنی و لایسنس بازتولید یک قلم تجهیزات.

    خروجی:
        (مجاز است یا نه, نام کشور سازنده)
    """
    origin_en = get_equipment_origin(equipment_name)
    if origin_en is None or origin_en == country.name_en:
        return True, country.name_en

    # بررسی لایسنس فعال در دیتابیس
    licensed = await tech_repo.has_license(session, country.id, equipment_name)
    if licensed:
        return True, origin_en

    return False, origin_en
