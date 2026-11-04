"""میدلورهای ربات (تزریق session دیتابیس و کنترل دسترسی)."""

from aiogram import Dispatcher

from .antispam import AntiSpamMiddleware
from .database import DatabaseMiddleware
from .group_access import GroupAccessMiddleware
from .maintenance import MaintenanceMiddleware
from .profanity import ProfanityMiddleware
from .user import UserMiddleware


def setup_middlewares(dp: Dispatcher) -> None:
    """نصب میدلورها روی همه‌ی پیام‌ها و کلیک‌های دکمه."""
    # ۱) Outer middleware کنترل دسترسی گروه‌ها (قبل از ضداسپم، دیتابیس و UserMiddleware)
    group_guard = GroupAccessMiddleware()
    dp.message.outer_middleware(group_guard)
    dp.edited_message.outer_middleware(group_guard)
    dp.callback_query.outer_middleware(group_guard)
    dp.chat_member.outer_middleware(group_guard)
    dp.inline_query.outer_middleware(group_guard)

    # ۲) میدلورهای داخلی: ترتیب مهم است: ضداسپم → session → حالت تعمیر (نیاز به session) → کاربر
    antispam = AntiSpamMiddleware()  # یک نمونه مشترک برای پیام و کلیک
    for observer in (dp.message, dp.callback_query):
        observer.middleware(antispam)
        observer.middleware(DatabaseMiddleware())
        observer.middleware(MaintenanceMiddleware())
        observer.middleware(UserMiddleware())

    # فیلتر فحش منحصراً روی پیام‌های متنی
    dp.message.middleware(ProfanityMiddleware())

