"""میدلور بارگذاری/ساخت کاربر و مسدودسازی کاربران بن‌شده."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User as TgUser

from ..database.repositories import users as users_repo


class UserMiddleware(BaseMiddleware):
    """
    کاربر تلگرام را در دیتابیس می‌سازد/به‌روز می‌کند و در data["db_user"] قرار می‌دهد.
    اگر کاربر بن شده باشد، ادامه‌ی پردازش متوقف می‌شود (آنتی‌ابیوز).
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

        # کاربر بن‌شده اجازه‌ی ادامه ندارد
        if db_user.is_banned:
            if isinstance(event, Message):
                await event.answer("⛔️ دسترسی شما به بازی مسدود شده است.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔️ دسترسی شما مسدود شده است.", show_alert=True)
            return None

        # کاربر معلق (v1.10.5): متمایز از بن — برگشت‌پذیر؛ نمی‌تواند اقدامی انجام دهد
        if getattr(db_user, "is_suspended", False):
            msg = "⏸ کشور شما توسط مدیریت بازی معلق شده و فعلاً نمی‌توانید اقدامی انجام دهید."
            if isinstance(event, Message):
                await event.answer(msg)
            elif isinstance(event, CallbackQuery):
                await event.answer(msg, show_alert=True)
            return None

        data["db_user"] = db_user
        return await handler(event, data)
