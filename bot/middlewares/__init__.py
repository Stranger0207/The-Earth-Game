"""میدلورهای ربات (تزریق session دیتابیس و کنترل دسترسی)."""

from aiogram import Dispatcher

from .database import DatabaseMiddleware
from .user import UserMiddleware


def setup_middlewares(dp: Dispatcher) -> None:
    """نصب میدلورها روی همه‌ی پیام‌ها و کلیک‌های دکمه."""
    # ترتیب مهم است: اول session ساخته شود، سپس کاربر بارگذاری شود
    for observer in (dp.message, dp.callback_query):
        observer.middleware(DatabaseMiddleware())
        observer.middleware(UserMiddleware())
