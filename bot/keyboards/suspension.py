"""کیبوردهای اینلاین تعلیق زمان‌دار و رفع تعلیق (/suspension و /unsuspend)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..database.models import User
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def suspension_durations_kb(target_id: int) -> InlineKeyboardMarkup:
    """کیبورد انتخاب مدت زمان تعلیق."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⏱ ۶ ساعت", callback_data=f"susp:dur:{target_id}:6", style=STYLE_OK)
    builder.button(text="⏱ ۱۲ ساعت", callback_data=f"susp:dur:{target_id}:12", style=STYLE_OK)
    builder.button(text="⏱ ۲۴ ساعت (۱ روز)", callback_data=f"susp:dur:{target_id}:24", style=STYLE_OK)
    builder.button(text="⏱ ۴۸ ساعت (۲ روز)", callback_data=f"susp:dur:{target_id}:48", style=STYLE_OK)
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(text="❌ انصراف", callback_data="susp:cancel", style=STYLE_NO)
    )
    return builder.as_markup()


def suspension_reason_kb(target_id: int, hours: int) -> InlineKeyboardMarkup:
    """کیبورد مرحله ورود علت تعلیق (با امکان رد کردن)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⏩ بدون ذکر علت",
                    callback_data=f"susp:confirm:{target_id}:{hours}:none",
                    style=STYLE_MAIN,
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ انصراف",
                    callback_data="susp:cancel",
                    style=STYLE_NO,
                )
            ],
        ]
    )


def unsuspend_list_kb(suspended_users: list[User]) -> InlineKeyboardMarkup:
    """کیبورد فهرست کاربران معلق جهت رفع تعلیق."""
    builder = InlineKeyboardBuilder()
    for user in suspended_users:
        name = user.first_name or f"User {user.telegram_id}"
        if user.username:
            display = f"🔓 {name} (@{user.username})"
        else:
            display = f"🔓 {name} ({user.telegram_id})"
        builder.button(text=display, callback_data=f"unsusp:do:{user.telegram_id}", style=STYLE_OK)
    builder.adjust(1)

    builder.row(
        InlineKeyboardButton(
            text="✏️ ارسال متنی آیدی / یوزرنیم",
            callback_data="unsusp:manual",
            style=STYLE_MAIN,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="❌ بستن",
            callback_data="susp:cancel",
            style=STYLE_NO,
        )
    )
    return builder.as_markup()


def suspension_cancel_kb() -> InlineKeyboardMarkup:
    """دکمه انصراف ساده."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ انصراف", callback_data="susp:cancel", style=STYLE_NO)]
        ]
    )
