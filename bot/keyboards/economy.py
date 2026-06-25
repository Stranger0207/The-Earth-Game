"""کیبوردهای بخش اقتصاد."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..enums import FACILITY_FA, RESOURCE_EMOJI, RESOURCE_FA, FacilityType, ResourceType


def economy_menu_kb(is_usa: bool = False) -> InlineKeyboardMarkup:
    """منوی اصلی اقتصاد. برای آمریکا دکمه‌ی تعرفه‌ی بین‌المللی هم اضافه می‌شود (v1.5)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 گزارش اقتصادی", callback_data="econ:report")
    builder.button(text="📦 ذخایر", callback_data="econ:reserves")
    builder.button(text="🏗 احداث تأسیسات", callback_data="econ:build")
    builder.button(text="💱 فروش ذخیره", callback_data="econ:sell")
    if is_usa:
        builder.button(text="🇺🇸 تعرفه بین‌المللی", callback_data="econ:tariffs")
    builder.button(text="🔙 بازگشت", callback_data="menu:main")
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
            text=FACILITY_FA[ftype], callback_data=f"build_type:{ftype.value}"
        )
    builder.button(text="🏭 تأسیسات من", callback_data="econ:facilities")
    builder.button(text="🔙 بازگشت", callback_data="menu:economy")
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
        )
    builder.button(text="🔙 بازگشت", callback_data="econ:build")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def sell_resources_kb() -> InlineKeyboardMarkup:
    """انتخاب منبع برای فروش."""
    builder = InlineKeyboardBuilder()
    for r in ResourceType:
        builder.button(
            text=f"{RESOURCE_EMOJI[r]} {RESOURCE_FA[r]}",
            callback_data=f"sell_res:{r.value}",
        )
    builder.button(text="🔙 بازگشت", callback_data="menu:economy")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()
