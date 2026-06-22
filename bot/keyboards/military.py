"""کیبوردهای بخش نظامی."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..enums import ATTACK_FA, AttackType


def military_menu_kb() -> InlineKeyboardMarkup:
    """منوی اصلی نظامی."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⚔️ گزارش تجهیزات", callback_data="mil:report")
    builder.button(text="💥 حمله", callback_data="mil:attack")
    builder.button(text="🔙 بازگشت", callback_data="menu:main")
    builder.adjust(2, 1)
    return builder.as_markup()


def attack_types_kb() -> InlineKeyboardMarkup:
    """انتخاب نوع حمله."""
    builder = InlineKeyboardBuilder()
    for atype in AttackType:
        builder.button(
            text=ATTACK_FA[atype], callback_data=f"atk_type:{atype.value}"
        )
    builder.button(text="🔙 بازگشت", callback_data="menu:military")
    builder.adjust(2, 2, 1)
    return builder.as_markup()
