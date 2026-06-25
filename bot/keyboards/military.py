"""کیبوردهای بخش نظامی."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..enums import ATTACK_FA, MIL_FACTORY_FA, AttackType, MilitaryFactoryType
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def military_menu_kb() -> InlineKeyboardMarkup:
    """منوی اصلی نظامی."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⚔️ گزارش تجهیزات", callback_data="mil:report", style=STYLE_MAIN)
    builder.button(text="💥 حمله", callback_data="mil:attack", style=STYLE_NO)
    builder.button(text="🏭 کارخانه نظامی", callback_data="mil:factory", style=STYLE_MAIN)
    builder.button(text="💰 فروش تجهیزات", callback_data="mil:sell", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data="menu:main", style=STYLE_MAIN)
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def military_factory_menu_kb() -> InlineKeyboardMarkup:
    """منوی کارخانه‌ی نظامی (v1.7)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏗 احداث کارخانه", callback_data="milfac:build", style=STYLE_OK)
    builder.button(text="🏭 کارخانه‌های من", callback_data="milfac:mine", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="menu:military", style=STYLE_MAIN)
    builder.adjust(2, 1)
    return builder.as_markup()


def military_factory_types_kb() -> InlineKeyboardMarkup:
    """انتخاب نوع کارخانه‌ی نظامی برای احداث (v1.7)."""
    builder = InlineKeyboardBuilder()
    for ftype in MilitaryFactoryType:
        builder.button(text=MIL_FACTORY_FA[ftype], callback_data=f"milfac_type:{ftype.value}", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data="mil:factory", style=STYLE_MAIN)
    builder.adjust(2, 2, 2, 2, 2, 2, 1)
    return builder.as_markup()


def attack_types_kb() -> InlineKeyboardMarkup:
    """انتخاب نوع حمله (همه قرمز — کنش تهاجمی)."""
    builder = InlineKeyboardBuilder()
    for atype in AttackType:
        builder.button(
            text=ATTACK_FA[atype], callback_data=f"atk_type:{atype.value}", style=STYLE_NO
        )
    builder.button(text="🔙 بازگشت", callback_data="menu:military", style=STYLE_MAIN)
    builder.adjust(2, 2, 1)
    return builder.as_markup()
