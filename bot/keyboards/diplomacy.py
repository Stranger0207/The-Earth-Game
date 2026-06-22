"""کیبوردهای بخش دیپلماسی."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def diplomacy_menu_kb() -> InlineKeyboardMarkup:
    """منوی اصلی دیپلماسی."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✉️ ارسال نامه", callback_data="dip:letter")
    builder.button(text="📞 تماس تلفنی", callback_data="dip:call")
    builder.button(text="🤝 دیدار حضوری", callback_data="dip:meeting")
    builder.button(text="📜 قراردادهای فعال", callback_data="dip:contracts")
    builder.button(text="🚫 تحریم", callback_data="dip:sanction")
    builder.button(text="🔙 بازگشت", callback_data="menu:main")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def end_call_kb() -> InlineKeyboardMarkup:
    """دکمه‌ی پایان تماس تلفنی."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📵 پایان تماس", callback_data="call:end")
    return builder.as_markup()
