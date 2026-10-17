"""میدلور سراسری فیلتر فحش و کلمات رکیک (ProfanityMiddleware).

این میدلور روی تمامی پیام‌های ورودی متنی (text و caption) نظارت می‌کند و در صورت
شناسایی کلمات رکیک:
۱. از پردازش پیام در تمامی هندلرها (رله چت نشست، نامه، رول، بیانیه، قرارداد و...) جلوگیری می‌کند.
۲. وضعیت FSM کاربر را پاک نمی‌کند تا نیازی به تایپ مجدد کل فرم نباشد.
۳. به کاربر اخطار اخلاقی محترمانه ارسال می‌کند.
۴. تخلف را در گروه لاگ اصلی مدیریت ثبت می‌کند.
۵. مدیران و مالکین بازی از فیلتر معاف هستند تا بتوانند دستورات مدیریتی را اجرا کنند.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, User as TgUser

from ..config import get_settings
from ..database.repositories import countries as countries_repo
from ..services import profanity_service
from ..services.news_service import send_log

logger = logging.getLogger(__name__)


class ProfanityMiddleware(BaseMiddleware):
    """میدلور سراسری aiogram برای رهگیری و پالایش کلمات رکیک در کل ربات."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # فیلتر فحش منحصراً روی پیام‌های متنی اعمال می‌شود
        if not isinstance(event, Message):
            return await handler(event, data)

        text = event.text or event.caption
        if not text:
            return await handler(event, data)

        tg_user: TgUser | None = data.get("event_from_user")
        settings = get_settings()

        # مدیران و مالکان بازی از فیلتر معاف هستند (برای ثبت و مدیریت کلمات)
        if tg_user and settings.is_admin(tg_user.id):
            return await handler(event, data)

        # اگر فیلتر کلاً خاموش باشد
        if not profanity_service.is_filter_enabled():
            return await handler(event, data)

        session = data.get("session")
        if session:
            try:
                await profanity_service.ensure_seeded(session)
            except Exception as exc:
                logger.debug("Error in ensure_seeded: %s", exc)

        # بررسی وجود فحش
        has_profanity, bad_word = profanity_service.check_profanity(text)
        if not has_profanity:
            return await handler(event, data)

        # ۱. ارسال اخطار به کاربر (بدون پاک کردن وضعیت FSM)
        warning_msg = (
            "🚫 <b>خطای منشور اخلاقی:</b>\n\n"
            "در متن ارسالی شما الفاظ نامناسب یا ممنوعه شناسایی شد. "
            "لطفاً متن خود را اصلاح کرده و مجدداً ارسال نمایید."
        )
        try:
            await event.answer(warning_msg)
        except Exception:
            pass

        # ۲. ارسال لاگ به گروه مدیریت
        bot = data.get("bot") or event.bot
        if bot and session and tg_user:
            try:
                country = await countries_repo.get_country_by_owner(session, tg_user.id)
                country_name = f"{country.flag} {country.name_fa}" if country else "بدون کشور"
                uname = f"@{tg_user.username}" if tg_user.username else (tg_user.full_name or "ناشناس")
                preview = (text[:100] + "...") if len(text) > 100 else text

                log_text = (
                    "🚫 <b>ثبت تخلف اخلاقی (فیلتر فحش)</b>\n\n"
                    f"👤 <b>کاربر:</b> {uname} (<code>{tg_user.id}</code>)\n"
                    f"🏳 <b>کشور:</b> {country_name}\n"
                    f"⚠️ <b>کلمه شناسایی‌شده:</b> <code>{bad_word}</code>\n"
                    f"📝 <b>بخشی از متن:</b> <i>{preview}</i>"
                )
                await send_log(bot, log_text)
            except Exception as exc:
                logger.debug("Could not send profanity violation log: %s", exc)

        # توقف اجرای ادامه فرآیند (هندلر اجرا نمی‌شود)
        return None
