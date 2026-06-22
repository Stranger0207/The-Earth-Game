"""
توابع کمکی مشترک هندلرها (دریافت کشورِ بازیکن و بررسی دسترسی).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Country, User
from ..database.repositories import countries as countries_repo


async def get_player_country(
    session: AsyncSession, db_user: User
) -> Country | None:
    """کشوری که این کاربر مالک آن است را برمی‌گرداند (یا None)."""
    return await countries_repo.get_country_by_owner(session, db_user.telegram_id)


NO_COUNTRY_TEXT = (
    "شما هنوز کشوری ندارید. برای پیوستن به بازی از دستور /claim "
    "یا دکمه‌ی «🌍 کشورگیری» استفاده کنید."
)
