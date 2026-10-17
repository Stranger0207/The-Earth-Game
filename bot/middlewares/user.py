"""میدلور بارگذاری/ساخت کاربر و مسدودسازی کاربران بن‌شده."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from datetime import datetime, timezone

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User as TgUser

from ..config import get_settings
from ..database.repositories import countries as countries_repo
from ..database.repositories import users as users_repo
from ..utils.numbers import fa_number


class UserMiddleware(BaseMiddleware):
    """
    کاربر تلگرام را در دیتابیس می‌سازد/به‌روز می‌کند و در data["db_user"] قرار می‌دهد.
    اگر کاربر بن شده باشد، ادامه‌ی پردازش متوقف می‌شود (آنتی‌ابیوز).
    مدیران و مالکین بازی از بن و تعلیق مصون هستند.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session = data.get("session")
        tg_user: TgUser | None = data.get("event_from_user")
        if session is None or tg_user is None:
            return await handler(event, data)

        db_user = await users_repo.get_or_create_user(
            session,
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )

        settings = get_settings()
        is_admin_or_owner = settings.is_admin(tg_user.id)

        # مدیران و مالکین بازی هرگز بن یا معلق نمی‌شوند
        if not is_admin_or_owner:
            # کاربر بن‌شده اجازه‌ی ادامه ندارد
            if db_user.is_banned:
                if isinstance(event, Message):
                    await event.answer("⛔️ دسترسی شما به بازی مسدود شده است.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("⛔️ دسترسی شما مسدود شده است.", show_alert=True)
                return None

            # کاربر معلق (v1.10.5): متمایز از بن — برگشت‌پذیر؛ نمی‌تواند اقدامی در کشورش انجام دهد
            if getattr(db_user, "is_suspended", False):
                # اگر کاربر اصلاً کشوری ندارد (مثلاً اخراج شده)، تعلیقش برداشته می‌شود تا بتواند مجدداً کشورگیری کند
                country = await countries_repo.get_country_by_owner(session, db_user.telegram_id)
                if country is None:
                    db_user.is_suspended = False
                    db_user.suspended_until = None
                    db_user.suspension_reason = None
                    await session.commit()
                else:
                    # بررسی تعلیق زمان‌دار
                    suspended_until = getattr(db_user, "suspended_until", None)
                    if suspended_until is not None:
                        now = datetime.now(timezone.utc)
                        if suspended_until.tzinfo is None:
                            suspended_until = suspended_until.replace(tzinfo=timezone.utc)
                        if now >= suspended_until:
                            # پایان خودکار دوره تعلیق
                            db_user.is_suspended = False
                            db_user.suspended_until = None
                            db_user.suspension_reason = None
                            await session.commit()
                        else:
                            remaining = suspended_until - now
                            hours = int(remaining.total_seconds() // 3600)
                            minutes = int((remaining.total_seconds() % 3600) // 60)
                            reason_text = (
                                f"\n📝 <b>علت:</b> {db_user.suspension_reason}"
                                if getattr(db_user, "suspension_reason", None)
                                else ""
                            )
                            msg = (
                                "⏸ <b>حساب کاربری و کشور شما به مدت محدود معلق شده است.</b>\n"
                                f"⏳ <b>زمان باقی‌مانده:</b> {fa_number(hours)} ساعت و {fa_number(minutes)} دقیقه{reason_text}\n\n"
                                "تا پایان دوره تعلیق امکان انجام هیچ عملیاتی در ربات را نخواهید داشت."
                            )
                            if isinstance(event, Message):
                                await event.answer(msg)
                            elif isinstance(event, CallbackQuery):
                                await event.answer(msg, show_alert=True)
                            return None
                    else:
                        msg = "⏸ کشور شما توسط مدیریت بازی معلق شده و فعلاً نمی‌توانید اقدامی انجام دهید."
                        if isinstance(event, Message):
                            await event.answer(msg)
                        elif isinstance(event, CallbackQuery):
                            await event.answer(msg, show_alert=True)
                        return None
        else:
            # پاک‌سازی خودکار هرگونه فلگ اشتباهی بن یا تعلیق برای ادمین‌ها و مالکین
            if db_user.is_banned or getattr(db_user, "is_suspended", False):
                db_user.is_banned = False
                db_user.is_suspended = False
                db_user.suspended_until = None
                db_user.suspension_reason = None
                await session.commit()

        data["db_user"] = db_user
        return await handler(event, data)

