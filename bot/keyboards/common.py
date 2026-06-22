"""کیبوردهای عمومی و کمک‌کننده برای ساخت دکمه‌ها."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..database.models import Country


def confirm_cancel_kb(confirm_data: str, cancel_data: str = "cancel") -> InlineKeyboardMarkup:
    """کیبورد ساده‌ی «تأیید / لغو»."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ تأیید", callback_data=confirm_data)
    builder.button(text="❌ لغو", callback_data=cancel_data)
    builder.adjust(2)
    return builder.as_markup()


def back_kb(callback_data: str = "menu:main") -> InlineKeyboardMarkup:
    """کیبورد «بازگشت»."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data=callback_data)]
        ]
    )


def countries_kb(
    countries: list[Country],
    prefix: str,
    *,
    columns: int = 2,
    back_data: str | None = None,
) -> InlineKeyboardMarkup:
    """
    کیبورد انتخاب کشور از یک لیست.
    callback_data هر دکمه به شکل "{prefix}:{country_id}" ساخته می‌شود.
    """
    builder = InlineKeyboardBuilder()
    for c in countries:
        builder.button(
            text=f"{c.flag} {c.name_fa}",
            callback_data=f"{prefix}:{c.id}",
        )
    builder.adjust(columns)
    if back_data:
        builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=back_data))
    return builder.as_markup()
