"""
ساخت نمونه‌های مشترک (singleton) ربات و دیسپچر.
این فایل از وابستگی حلقوی جلوگیری می‌کند: همه‌جا از همین نمونه‌ها استفاده می‌شود.
"""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from .config import get_settings

settings = get_settings()

# نمونه‌ی ربات؛ به‌صورت پیش‌فرض پیام‌ها با فرمت HTML ارسال می‌شوند
bot = Bot(
    token=settings.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

# ذخیره‌سازی وضعیت FSM در حافظه (برای فرم‌های چندمرحله‌ای)
storage = MemoryStorage()

# دیسپچر اصلی که همه‌ی روترها به آن وصل می‌شوند
dp = Dispatcher(storage=storage)
