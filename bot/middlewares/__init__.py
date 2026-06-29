"""میدلورهای ربات (تزریق session دیتابیس و کنترل دسترسی)."""

from aiogram import Dispatcher

from .antispam import AntiSpamMiddleware
from .database import DatabaseMiddleware
from .maintenance import MaintenanceMiddleware
from .user import UserMiddleware


def setup_middlewares(dp: Dispatcher) -> None:
    """نصب میدلورها روی همه‌ی پیام‌ها و کلیک‌های دکمه."""
    # ترتیب مهم است: ضداسپم → session → حالت تعمیر (نیاز به session) → کاربر
    antispam = AntiSpamMiddleware()  # یک نمونه مشترک برای پیام و کلیک
    for observer in (dp.message, dp.callback_query):
        observer.middleware(antispam)
        observer.middleware(DatabaseMiddleware())
        observer.middleware(MaintenanceMiddleware())
        observer.middleware(UserMiddleware())
