"""
میدلور ضداسپم (v1.8):
اگر یک کاربر در پنجره‌ی ۳ ثانیه‌ای بیش از ۵ کنش (پیام/کلیک دکمه) انجام دهد،
دسترسی او به ربات به مدت ۱ دقیقه به‌صورت موقت معلق (suspend) می‌شود.

این کنترل در حافظه نگه داشته می‌شود (بدون نیاز به دیتابیس) و مالک/مدیران از آن
معاف هستند تا کارهای مدیریتی محدود نشود.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User as TgUser

from ..config import get_settings

# پارامترهای ضداسپم
_WINDOW_SECONDS = 3.0     # پنجره‌ی زمانی بررسی
_MAX_ACTIONS = 5          # حداکثر کنش مجاز در پنجره (بیش از این ⇒ تعلیق)
_SUSPEND_SECONDS = 60.0   # مدت تعلیق دسترسی


class AntiSpamMiddleware(BaseMiddleware):
    """شمارش کنش‌های هر کاربر و تعلیق موقت در صورت اسپم."""

    def __init__(self) -> None:
        # زمان‌های کنش اخیر هر کاربر (مونوتونیک)
        self._hits: dict[int, deque[float]] = defaultdict(deque)
        # زمان پایان تعلیق هر کاربر (در صورت وجود)
        self._suspended_until: dict[int, float] = {}
        # آیا به کاربر معلق‌شده هشدار داده‌ایم؟ (برای جلوگیری از اسپم پاسخ)
        self._warned: set[int] = set()
        self._settings = get_settings()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        if tg_user is None:
            return await handler(event, data)

        # مالک و مدیران از ضداسپم معاف‌اند
        if self._settings.is_admin(tg_user.id):
            return await handler(event, data)

        now = time.monotonic()
        uid = tg_user.id

        # اگر هنوز در دوره‌ی تعلیق است، کنش نادیده گرفته می‌شود
        until = self._suspended_until.get(uid)
        if until is not None:
            if now < until:
                await self._notify_suspended(event, uid, until - now)
                return None
            # پایان تعلیق
            self._suspended_until.pop(uid, None)
            self._warned.discard(uid)
            self._hits[uid].clear()

        # ثبت کنش جاری و حذف کنش‌های خارج از پنجره
        hits = self._hits[uid]
        hits.append(now)
        while hits and now - hits[0] > _WINDOW_SECONDS:
            hits.popleft()

        # عبور از آستانه ⇒ تعلیق ۱ دقیقه‌ای
        if len(hits) > _MAX_ACTIONS:
            self._suspended_until[uid] = now + _SUSPEND_SECONDS
            self._warned.discard(uid)
            hits.clear()
            await self._notify_suspended(event, uid, _SUSPEND_SECONDS)
            return None

        return await handler(event, data)

    async def _notify_suspended(
        self, event: TelegramObject, uid: int, remaining: float
    ) -> None:
        """به کاربر معلق‌شده یک‌بار هشدار می‌دهد (برای جلوگیری از پاسخ پی‌درپی)."""
        secs = max(1, int(remaining))
        text = (
            "⛔️ به‌دلیل ارسال/کلیک بیش از حد، دسترسی شما به‌مدت ۱ دقیقه موقتاً "
            f"معلق شد. لطفاً حدود {secs} ثانیه صبر کنید."
        )
        try:
            if isinstance(event, CallbackQuery):
                # برای کلیک‌ها همیشه پاسخ کوتاه (alert) داده می‌شود
                await event.answer(text, show_alert=True)
            elif isinstance(event, Message) and uid not in self._warned:
                self._warned.add(uid)
                await event.answer(text)
        except Exception:  # noqa: BLE001 — خطای ارسال نباید جریان را متوقف کند
            pass
