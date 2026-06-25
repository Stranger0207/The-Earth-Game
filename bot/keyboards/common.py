"""کیبوردهای عمومی و کمک‌کننده برای ساخت دکمه‌ها."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..database.models import Country
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def confirm_cancel_kb(confirm_data: str, cancel_data: str = "cancel") -> InlineKeyboardMarkup:
    """کیبورد ساده‌ی «تأیید / لغو» (سبز/قرمز)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ تأیید", callback_data=confirm_data, style=STYLE_OK)
    builder.button(text="❌ لغو", callback_data=cancel_data, style=STYLE_NO)
    builder.adjust(2)
    return builder.as_markup()


def back_kb(callback_data: str = "menu:main") -> InlineKeyboardMarkup:
    """کیبورد «بازگشت» (آبی)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data=callback_data, style=STYLE_MAIN)]
        ]
    )


def countries_kb(
    countries: list[Country],
    prefix: str,
    *,
    columns: int = 2,
    back_data: str | None = None,
    style: str | None = STYLE_MAIN,
) -> InlineKeyboardMarkup:
    """
    کیبورد انتخاب کشور از یک لیست (پیش‌فرض همه آبی).
    callback_data هر دکمه به شکل "{prefix}:{country_id}" ساخته می‌شود.
    """
    builder = InlineKeyboardBuilder()
    for c in countries:
        builder.button(
            text=f"{c.flag} {c.name_fa}",
            callback_data=f"{prefix}:{c.id}",
            style=style,
        )
    builder.adjust(columns)
    if back_data:
        builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=back_data, style=STYLE_MAIN))
    return builder.as_markup()
