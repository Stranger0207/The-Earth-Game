"""
توابع کمکی مشترک هندلرها (دریافت کشورِ بازیکن و بررسی دسترسی).
"""

from __future__ import annotations

from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import FEATURE_LOCKED_TEXT, LOCKABLE_FEATURES
from ..database.models import Country, User
from ..database.repositories import countries as countries_repo
from ..database.repositories import feature_locks as locks_repo


async def get_player_country(
    session: AsyncSession, db_user: User
) -> Country | None:
    """کشوری که این کاربر مالک آن است را برمی‌گرداند (یا None)."""
    return await countries_repo.get_country_by_owner(session, db_user.telegram_id)


NO_COUNTRY_TEXT = (
    "شما هنوز کشوری ندارید. برای پیوستن به بازی از دستور /claim "
    "یا دکمه‌ی «🌍 کشورگیری» استفاده کنید."
)


def feature_name(feature_key: str) -> str:
    """نام فارسی یک آپشن قابل‌قفل (برای پیام‌ها و لاگ)."""
    entry = LOCKABLE_FEATURES.get(feature_key)
    return entry[0] if entry else feature_key


async def is_feature_locked(
    session: AsyncSession, country: Country | None, feature_key: str
) -> bool:
    """آیا این آپشن برای این کشور قفل است؟ (قفل سراسری هم لحاظ می‌شود)"""
    return await locks_repo.is_locked(
        session, feature_key, country.id if country else None
    )


async def assert_feature(
    event: CallbackQuery | Message,
    session: AsyncSession,
    country: Country | None,
    feature_key: str,
) -> bool:
    """
    (v2.1) گارد آپشن‌های قفل‌شده توسط مالک بازی.

    در ابتدای هندلرِ ورودیِ هر آپشن صدا زده می‌شود:

        if not await assert_feature(call, session, country, "covert.espionage"):
            return

    اگر آپشن قفل باشد، به بازیکن هشدار نمایش داده می‌شود و `False` برمی‌گردد.
    مالک/مدیر بازی از قفل‌ها معاف است تا بتواند وضعیت را آزمایش کند.
    """
    from ..config import get_settings

    if get_settings().is_admin(event.from_user.id):
        return True

    if not await is_feature_locked(session, country, feature_key):
        return True

    text = FEATURE_LOCKED_TEXT.format(name=feature_name(feature_key))
    if isinstance(event, CallbackQuery):
        await event.answer(text, show_alert=True)
    else:
        await event.answer(text)
    return False


async def check_hall_lock(
    event: CallbackQuery | Message,
    session: AsyncSession,
    country: Country | None,
) -> bool:
    """
    بررسی قفل بودن پنل کشور در اثر حضور در صحن علنی تالار مجمع عمومی سازمان ملل.
    اگر کشور داخل تالار باشد، پیام هشدار نشان می‌دهد و True برمی‌گرداند.
    """
    if country is None or country.name_en == "UN":
        return False
    from ..database.repositories import united_nations as un_repo
    part = await un_repo.get_active_participant_for_country(session, country.id)
    if part and part.status == "inside_hall":
        from ..keyboards.united_nations import assembly_hall_kb
        text = (
            "🏛 <b>شما هم‌اکنون در تالار مجمع عمومی سازمان ملل حضور دارید؛</b>\n\n"
            "جهت حفظ تشریفات و نظم صحن علنی، برای مدیریت پنل کشور ابتدا باید با دکمه "
            "«🚪 خروج از تالار مجمع» از صحن خارج شده و وارد لابی نیویورک شوید."
        )
        if isinstance(event, CallbackQuery):
            await event.answer("دسترسی به پنل کشور در حین حضور در صحن مجمع قفل است.", show_alert=True)
            try:
                await event.message.answer(text, reply_markup=assembly_hall_kb(part.session_id))
            except Exception:
                pass
        elif event is not None:
            await event.answer(text, reply_markup=assembly_hall_kb(part.session_id))
        return True
    return False
