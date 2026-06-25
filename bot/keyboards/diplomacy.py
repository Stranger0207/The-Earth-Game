"""کیبوردهای بخش دیپلماسی."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def diplomacy_menu_kb() -> InlineKeyboardMarkup:
    """منوی اصلی دیپلماسی."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✉️ ارسال نامه", callback_data="dip:letter", style=STYLE_MAIN)
    builder.button(text="📞 تماس تلفنی", callback_data="dip:call", style=STYLE_MAIN)
    builder.button(text="🤝 دیدار حضوری", callback_data="dip:meeting", style=STYLE_MAIN)
    builder.button(text="📜 قراردادهای فعال", callback_data="dip:contracts", style=STYLE_MAIN)
    builder.button(text="🎤 سخنرانی", callback_data="dip:speech", style=STYLE_MAIN)
    builder.button(text="🚫 تحریم", callback_data="dip:sanction", style=STYLE_NO)
    builder.button(text="🔙 بازگشت", callback_data="menu:main", style=STYLE_MAIN)
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def end_call_kb() -> InlineKeyboardMarkup:
    """دکمه‌ی پایان تماس تلفنی."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📵 پایان تماس", callback_data="call:end", style=STYLE_NO)
    return builder.as_markup()


def sanction_menu_kb() -> InlineKeyboardMarkup:
    """منوی تحریم (v1.7): وضع/وضع‌شده/تحریم‌های من/لغو."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🚫 وضع تحریم", callback_data="sanc:impose", style=STYLE_NO)
    builder.button(text="📋 تحریم‌های وضع‌شده", callback_data="sanc:imposed", style=STYLE_MAIN)
    builder.button(text="🎯 تحریم‌های من", callback_data="sanc:mine", style=STYLE_MAIN)
    builder.button(text="♻️ لغو تحریم", callback_data="sanc:cancel", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data="menu:diplomacy", style=STYLE_MAIN)
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def sanction_types_kb() -> InlineKeyboardMarkup:
    """کیبورد انتخاب نوع تحریم (v1.7: بدون تحریم فردی)."""
    from ..enums import SANCTION_FA, SanctionType

    builder = InlineKeyboardBuilder()
    for stype in SanctionType:
        if stype == SanctionType.INDIVIDUAL:
            continue  # تحریم فردی از فهرست حذف شد (v1.7)
        builder.button(text=SANCTION_FA[stype], callback_data=f"sanc_type:{stype.value}", style=STYLE_NO)
    builder.button(text="🔙 بازگشت", callback_data="dip:sanction", style=STYLE_MAIN)
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup()
