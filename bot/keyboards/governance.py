"""کیبوردهای بخش حاکمیت (v1.10.2)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..enums import (
    GOVERNMENT_EMOJI,
    GOVERNMENT_FA,
    GovernmentType,
)
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def governance_menu_kb() -> InlineKeyboardMarkup:
    """منوی اصلی حاکمیت."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏛 نظام حاکمیتی", callback_data="gov:system", style=STYLE_MAIN)
    builder.button(text="✊ اعتراضات و رفراندوم", callback_data="gov:protests", style=STYLE_MAIN)
    builder.button(text="📜 قانونگذاری", callback_data="gov:legislation", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="menu:main", style=STYLE_MAIN)
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()


def government_type_kb() -> InlineKeyboardMarkup:
    """انتخاب نوع نظام حاکمیتی."""
    builder = InlineKeyboardBuilder()
    for gt in GovernmentType:
        emoji = GOVERNMENT_EMOJI.get(gt, "")
        fa = GOVERNMENT_FA.get(gt, gt.value)
        builder.button(
            text=f"{emoji} {fa}",
            callback_data=f"gov_type:{gt.value}",
            style=STYLE_OK,
        )
    builder.button(text="🔙 بازگشت", callback_data="gov:system", style=STYLE_MAIN)
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup()


def government_system_kb(has_govt: bool, changes_left: int) -> InlineKeyboardMarkup:
    """منوی نظام حاکمیتی: نمایش وضعیت فعلی + دکمه‌ی تغییر."""
    builder = InlineKeyboardBuilder()
    if has_govt:
        builder.button(text="📋 نظام فعلی من", callback_data="gov:current", style=STYLE_MAIN)
    if changes_left > 0:
        label = "🔄 انتخاب نظام" if not has_govt else "🔄 تغییر نظام"
        builder.button(text=label, callback_data="gov:change_system", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data="menu:governance", style=STYLE_MAIN)
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def protest_menu_kb() -> InlineKeyboardMarkup:
    """منوی اعتراضات."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔴 اعتراضات فعال", callback_data="gov:active_protests", style=STYLE_NO)
    builder.button(text="📋 تاریخچه اعتراضات", callback_data="gov:protest_history", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="menu:governance", style=STYLE_MAIN)
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def protest_action_kb(protest_id: int) -> InlineKeyboardMarkup:
    """دکمه‌های عمل روی اعتراض: سرکوب یا ارجاع به مجلس."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="👊 سرکوب",
        callback_data=f"gov:suppress:{protest_id}",
        style=STYLE_NO,
    )
    builder.button(
        text="🏛 ارجاع به مجلس",
        callback_data=f"gov:parliament_ref:{protest_id}",
        style=STYLE_OK,
    )
    builder.button(text="🔙 بازگشت", callback_data="gov:active_protests", style=STYLE_MAIN)
    builder.adjust(2, 1)
    return builder.as_markup()


def legislation_menu_kb() -> InlineKeyboardMarkup:
    """منوی قانونگذاری."""
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 قانون مالیات", callback_data="gov:tax_law", style=STYLE_MAIN)
    builder.button(text="🛂 قانون ویزا", callback_data="gov:visa_law", style=STYLE_MAIN)
    builder.button(text="🏛 مجلس", callback_data="gov:parliament", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="menu:governance", style=STYLE_MAIN)
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()


def tax_law_kb(current_rate: float) -> InlineKeyboardMarkup:
    """منوی مالیات با نمایش نرخ فعلی."""
    from ..utils.numbers import fa_number
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"📊 نرخ فعلی: {fa_number(current_rate, 1)}٪",
        callback_data="gov:tax_info",
        style=STYLE_MAIN,
    )
    builder.button(text="✏️ تعیین نرخ مالیات", callback_data="gov:set_tax", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data="gov:legislation", style=STYLE_MAIN)
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def visa_law_kb() -> InlineKeyboardMarkup:
    """منوی ویزا."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 لیست ویزاها", callback_data="gov:visa_list", style=STYLE_MAIN)
    builder.button(text="➕ افزودن ویزا", callback_data="gov:visa_add", style=STYLE_OK)
    builder.button(text="➖ حذف ویزا", callback_data="gov:visa_remove", style=STYLE_NO)
    builder.button(text="🔙 بازگشت", callback_data="gov:legislation", style=STYLE_MAIN)
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()


def parliament_menu_kb() -> InlineKeyboardMarkup:
    """منوی مجلس."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 ارائه لایحه به مجلس", callback_data="gov:submit_law", style=STYLE_OK)
    builder.button(text="📋 لایحه‌های من", callback_data="gov:my_laws", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="gov:legislation", style=STYLE_MAIN)
    builder.adjust(1, 1, 1)
    return builder.as_markup()
