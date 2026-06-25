"""کیبوردهای بخش اقتصاد."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..enums import FACILITY_FA, RESOURCE_EMOJI, RESOURCE_FA, FacilityType, ResourceType
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def economy_menu_kb(is_usa: bool = False) -> InlineKeyboardMarkup:
    """منوی اصلی اقتصاد. برای آمریکا دکمه‌ی تعرفه‌ی بین‌المللی هم اضافه می‌شود (v1.5)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 گزارش اقتصادی", callback_data="econ:report", style=STYLE_MAIN)
    builder.button(text="📦 ذخایر", callback_data="econ:reserves", style=STYLE_MAIN)
    builder.button(text="🏗 احداث تأسیسات", callback_data="econ:build", style=STYLE_OK)
    builder.button(text="💱 فروش ذخیره", callback_data="econ:sell", style=STYLE_OK)
    if is_usa:
        builder.button(text="🇺🇸 تعرفه بین‌المللی", callback_data="econ:tariffs", style=STYLE_NO)
    builder.button(text="🔙 بازگشت", callback_data="menu:main", style=STYLE_MAIN)
    if is_usa:
        builder.adjust(2, 2, 1, 1)
    else:
        builder.adjust(2, 2, 1)
    return builder.as_markup()


def facility_types_kb() -> InlineKeyboardMarkup:
    """انتخاب نوع تأسیسات برای احداث."""
    builder = InlineKeyboardBuilder()
    for ftype in FacilityType:
        builder.button(
            text=FACILITY_FA[ftype], callback_data=f"build_type:{ftype.value}", style=STYLE_OK
        )
    builder.button(text="🏭 تأسیسات من", callback_data="econ:facilities", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="menu:economy", style=STYLE_MAIN)
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def mine_resources_kb() -> InlineKeyboardMarkup:
    """انتخاب منبع برای معدن (فقط منابع معدنی قابل‌استخراج)."""
    builder = InlineKeyboardBuilder()
    # معدن فقط برای این منابع معنا دارد (پلی‌بوک: فرم احداث معدن)
    mineable = [
        ResourceType.COAL,
        ResourceType.ALUMINUM,
        ResourceType.IRON,
        ResourceType.GOLD,
    ]
    for r in mineable:
        builder.button(
            text=f"{RESOURCE_EMOJI[r]} {RESOURCE_FA[r]}",
            callback_data=f"mine_res:{r.value}",
            style=STYLE_MAIN,
        )
    builder.button(text="🔙 بازگشت", callback_data="econ:build", style=STYLE_MAIN)
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def sell_resources_kb() -> InlineKeyboardMarkup:
    """انتخاب منبع برای فروش."""
    builder = InlineKeyboardBuilder()
    for r in ResourceType:
        builder.button(
            text=f"{RESOURCE_EMOJI[r]} {RESOURCE_FA[r]}",
            callback_data=f"sell_res:{r.value}",
            style=STYLE_MAIN,
        )
    builder.button(text="🔙 بازگشت", callback_data="menu:economy", style=STYLE_MAIN)
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()
