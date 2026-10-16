"""کیبوردهای مربوط به بخش ماهواره فضایی نظامی و اقتصادی (v2.8)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..constants import ECON_SAT_LEVEL_CONFIG
from ..utils.numbers import fa_money
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def satellite_hub_kb() -> InlineKeyboardMarkup:
    """منوی اصلی هاب ماهواره فضایی (تفکیک نظامی و اقتصادی)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🛰 ماهواره نظامی (ویژه VIP)", callback_data="sat:mil_menu", style=STYLE_MAIN)
    builder.button(text="💰 ماهواره اقتصادی (عمومی)", callback_data="sat:econ_menu", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data="menu:military", style=STYLE_MAIN)
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def military_satellite_kb() -> InlineKeyboardMarkup:
    """منوی ماهواره نظامی (جاسوسی)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 پرتاب ماهواره جاسوسی", callback_data="sat:mil_launch", style=STYLE_OK)
    builder.button(text="📡 ماهواره‌های من", callback_data="sat:mil_list", style=STYLE_MAIN)
    builder.button(text="🔭 رصد جاسوسی کشورها (۵۰M $)", callback_data="sat:mil_scan", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت به بخش فضا", callback_data="mil:sat", style=STYLE_MAIN)
    builder.adjust(1, 2, 1)
    return builder.as_markup()


# سازگاری با کدهای قبلی
satellite_main_menu_kb = military_satellite_kb


def economic_satellite_kb(
    is_unlocked: bool,
    has_active_sat: bool = False,
    is_in_orbit: bool = False,
    level: int = 1,
    back_to: str = "mil:sat",
) -> InlineKeyboardMarkup:
    """منوی اختصاصی ماهواره تجاری و اقتصادی."""
    builder = InlineKeyboardBuilder()

    if not is_unlocked:
        builder.button(
            text="💳 فعالسازی آپشن (۵۰ هزار تومان)",
            callback_data="econsat:buy_prompt",
            style=STYLE_OK,
        )
        builder.button(text="🔙 بازگشت", callback_data=back_to, style=STYLE_MAIN)
        builder.adjust(1, 1)
        return builder.as_markup()

    if not has_active_sat:
        builder.button(
            text="🚀 ساخت و پرتاب ماهواره تجاری",
            callback_data="econsat:launch_start",
            style=STYLE_OK,
        )
        builder.button(text="📋 تاریخچه ماهواره‌ها", callback_data="econsat:history", style=STYLE_MAIN)
        builder.button(text="🔙 بازگشت", callback_data=back_to, style=STYLE_MAIN)
        builder.adjust(1, 1, 1)
        return builder.as_markup()

    # ماهواره فعال دارد
    if is_in_orbit:
        builder.button(text="📊 وضعیت ماهواره و بازدهی", callback_data="econsat:status", style=STYLE_MAIN)
        if level < 5:
            next_lvl = level + 1
            cost = ECON_SAT_LEVEL_CONFIG.get(next_lvl, {}).get("upgrade_cost", 0.0)
            builder.button(
                text=f"⚡️ ارتقا به سطح {next_lvl} ({fa_money(cost)})",
                callback_data="econsat:upgrade_prompt",
                style=STYLE_OK,
            )
    else:
        builder.button(text="⏳ وضعیت پرتاب در حال پرواز", callback_data="econsat:status", style=STYLE_MAIN)

    builder.button(text="📋 تاریخچه ماهواره‌ها", callback_data="econsat:history", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data=back_to, style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def econ_sat_buy_confirm_kb() -> InlineKeyboardMarkup:
    """تأیید ورود به پرداخت کارت‌به‌کارت."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ بله، پرداخت می‌کنم", callback_data="econsat:buy_confirm", style=STYLE_OK)
    builder.button(text="❌ خیر / بازگشت", callback_data="sat:econ_menu", style=STYLE_NO)
    builder.adjust(1, 1)
    return builder.as_markup()


def econ_cancel_kb() -> InlineKeyboardMarkup:
    """دکمه انصراف از فرم."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ انصراف و بازگشت", callback_data="sat:econ_menu", style=STYLE_NO)
    return builder.as_markup()


def admin_receipt_review_kb(receipt_id: int) -> InlineKeyboardMarkup:
    """دکمه‌های تأیید و رد رسید در گروه لاگ پشتیبانی."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ تأیید رسید و فعالسازی",
        callback_data=f"econsat_adm:approve:{receipt_id}",
        style=STYLE_OK,
    )
    builder.button(
        text="❌ رد رسید",
        callback_data=f"econsat_adm:reject:{receipt_id}",
        style=STYLE_NO,
    )
    builder.adjust(1, 1)
    return builder.as_markup()
