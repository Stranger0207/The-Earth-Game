"""میدلور کنترل و قفل دسترسی گروه‌ها (v2.12.0).

قبل از ثبت کاربر در دیتابیس یا اجرای هرگونه هندلر و میدلور، در گروه‌ها بررسی می‌کند
که آیا کاربر مجاز به تعامل با ربات است یا خیر.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

from ..utils.chat_access import evaluate_group_access

logger = logging.getLogger(__name__)


class GroupAccessMiddleware(BaseMiddleware):
    """
    میدلور بیرونی (Outer Middleware) برای فیلتر کردن آپدیت‌های غیرمجاز در گروه‌ها:
    - در گروه‌های متفرقه فقط مالک اجازه تعامل دارد.
    - در گروه‌های داخلی فقط ادمین‌ها و مالکان مجاز هستند.
    - آپدیت‌های غیرمجاز کاملاً بی‌صدا متوقف می‌شوند (بدون ثبت کاربر در دیتابیس).
    - برای CallbackQuery پاسخ خالی ارسال می‌شود تا لودینگ دکمه بسته شود.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # استخراج چت، کاربر و ارسال‌کننده
        chat = data.get("event_chat") or getattr(event, "chat", None)
        from_user = data.get("event_from_user") or getattr(event, "from_user", None)
        sender_chat = getattr(event, "sender_chat", None)

        is_callback = isinstance(event, CallbackQuery) or (
            hasattr(event, "answer") and hasattr(event, "data")
        )
        if is_callback:
            if chat is None and getattr(event, "message", None):
                chat = event.message.chat
            if from_user is None:
                from_user = getattr(event, "from_user", None)

        if chat and getattr(chat, "type", "") in ("group", "supergroup"):
            is_allowed = evaluate_group_access(chat, from_user, sender_chat=sender_chat)
            if not is_allowed:
                chat_id = getattr(chat, "id", None)
                user_id = getattr(from_user, "id", None)
                sender_id = getattr(sender_chat, "id", None)
                logger.debug(
                    "GroupAccessMiddleware DENY: chat=%s user=%s sender_chat=%s event_type=%s",
                    chat_id,
                    user_id,
                    sender_id,
                    type(event).__name__,
                )
                if is_callback and hasattr(event, "answer"):
                    try:
                        await event.answer()
                    except Exception:
                        pass
                return None

        return await handler(event, data)
