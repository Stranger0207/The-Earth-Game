"""
میدلور حالت تعمیر/خاموشی ربات (v1.10.5).

اگر ربات در حالت خاموشی باشد (دستیِ فوری یا بازه‌ی روزانه‌ی تکرارشونده به وقت تهران)،
پلیرهای عادی نمی‌توانند هیچ کاری انجام دهند؛ مالک و مدیران معاف‌اند تا بتوانند دوباره
ربات را روشن کنند.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User as TgUser

from ..config import get_settings
from ..database.repositories import bot_state as bot_state_repo

# منطقه‌ی زمانی تهران (offset ثابت +3:30؛ ایران از ۲۰۲۲ ساعت تابستانی ندارد)
_TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))


def _parse_hhmm(value: str | None) -> int | None:
    """رشته‌ی "HH:MM" را به دقیقه‌ی روز تبدیل می‌کند؛ در صورت نامعتبر None."""
    if not value:
        return None
    try:
        h, m = value.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _within_daily_window(start: str | None, end: str | None, now_min: int) -> bool:
    """آیا زمان فعلی (دقیقه‌ی روز) داخل بازه‌ی [start, end] است؟ (با پشتیبانی از عبور از نیمه‌شب)"""
    s = _parse_hhmm(start)
    e = _parse_hhmm(end)
    if s is None or e is None:
        return False
    if s == e:
        return False
    if s < e:
        # بازه‌ی عادی در همان روز (مثلاً 02:00 تا 08:00)
        return s <= now_min < e
    # بازه‌ای که از نیمه‌شب عبور می‌کند (مثلاً 22:00 تا 06:00)
    return now_min >= s or now_min < e


class MaintenanceMiddleware(BaseMiddleware):
    """در حالت خاموشی، کنش‌های پلیرهای عادی را مسدود می‌کند."""

    def __init__(self) -> None:
        self._settings = get_settings()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        session = data.get("session")
        # مالک/مدیر معاف‌اند؛ بدون session هم نمی‌توان وضعیت را خواند
        if tg_user is None or session is None or self._settings.is_admin(tg_user.id):
            return await handler(event, data)

        state = await bot_state_repo.get_state(session)

        now_tehran = datetime.now(_TEHRAN_TZ)
        now_min = now_tehran.hour * 60 + now_tehran.minute
        in_window = state.auto_off_enabled and _within_daily_window(
            state.auto_off_start, state.auto_off_end, now_min
        )

        if not (state.maintenance or in_window):
            return await handler(event, data)

        # ربات خاموش است → کنش پلیر عادی مسدود می‌شود
        text = state.maint_message or (
            "🔌 ربات موقتاً در دسترس نیست. لطفاً بعداً دوباره تلاش کنید."
        )
        try:
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            elif isinstance(event, Message):
                await event.answer(text)
        except Exception:  # noqa: BLE001 — خطای ارسال نباید جریان را متوقف کند
            pass
        return None
