"""
کیبوردهای ستاد فرماندهی کل (v1.10.6).

منوی نظامی از یک فهرست ساده به یک «ستاد فرماندهی» چندبخشی تبدیل شده تا
بازیکن حس کنترل واقعی ارتش را داشته باشد.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def command_center_kb(is_vip: bool = False, has_straits: bool = False) -> InlineKeyboardMarkup:
    """منوی اصلی ستاد فرماندهی کل."""
    from aiogram.types import WebAppInfo
    from ..config import get_settings

    settings = get_settings()
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 وضعیت ارتش", callback_data="cc:status", style=STYLE_MAIN)
    builder.button(text="📡 ماهواره فضایی", callback_data="mil:sat", style=STYLE_MAIN)
    builder.button(text="🏗 پایگاه‌های نظامی", callback_data="mil:base", style=STYLE_MAIN)
    builder.button(text="🏭 صنایع نظامی", callback_data="cc:industry", style=STYLE_MAIN)
    if has_straits:
        builder.button(text="🌊 مدیریت تنگه‌ها", callback_data="menu:straits", style=STYLE_OK)
    builder.button(text="🎖 فرماندهان", callback_data="cc:commanders", style=STYLE_MAIN)
    builder.button(text="🔬 تکنولوژی نظامی", callback_data="tech:menu", style=STYLE_MAIN)
    builder.button(text="🛡 پروژه‌های امنیتی (رول)", callback_data="mil:security_roles", style=STYLE_MAIN)
    builder.button(text="⚔️ عملیات و رول نظامی", callback_data="mil:ops_roles", style=STYLE_MAIN)

    if settings.webapp_base_url:
        builder.button(
            text="🌍 رادار زنده جهان (نقشه)",
            web_app=WebAppInfo(url=settings.webapp_url),
        )
    else:
        builder.button(
            text="🌍 رادار زنده جهان (نقشه)",
            callback_data="menu:radar_info",
            style=STYLE_OK,
        )

    builder.button(text="🔙 بازگشت", callback_data="menu:main", style=STYLE_MAIN)
    if has_straits:
        builder.adjust(2, 2, 2, 2, 2, 1)
    else:
        builder.adjust(2, 2, 2, 2, 1, 1)
    return builder.as_markup()


def industry_menu_kb() -> InlineKeyboardMarkup:
    """منوی صنایع نظامی."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏭 کارخانه نظامی", callback_data="mil:factory", style=STYLE_MAIN)
    builder.button(text="🔬 تکنولوژی و لایسنس", callback_data="tech:menu", style=STYLE_MAIN)
    builder.button(text="💰 فروش تجهیزات", callback_data="mil:sell", style=STYLE_OK)
    builder.button(text="🪖 استقرار نیرو", callback_data="mil:deploy", style=STYLE_MAIN)
    builder.button(text="☢️ تأسیسات هسته‌ای", callback_data="mil:nuclear", style=STYLE_NO)
    builder.button(text="🔙 بازگشت", callback_data="menu:military", style=STYLE_MAIN)
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()
