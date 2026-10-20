"""کیبورد پنل اصلی کشور."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb() -> InlineKeyboardMarkup:
    """پنل اصلی مدیریت کشور با چهار محور اصلی + بخش‌های جانبی + رادار زنده جهان."""
    from aiogram.types import WebAppInfo
    from ..config import get_settings
    from ..utils.ui import STYLE_MAIN, STYLE_OK

    settings = get_settings()
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 اقتصاد", callback_data="menu:economy", style=STYLE_MAIN)
    builder.button(text="🤝 دیپلماسی", callback_data="menu:diplomacy", style=STYLE_MAIN)
    builder.button(text="⚔️ نظامی", callback_data="menu:military", style=STYLE_MAIN)
    builder.button(text="🏛 حاکمیت", callback_data="menu:governance", style=STYLE_MAIN)
    builder.button(text="🧠 مشاور هوشمند", callback_data="menu:advisor", style=STYLE_MAIN)
    builder.button(text="🏛 وضعیت کشور", callback_data="menu:status", style=STYLE_MAIN)

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

    builder.adjust(3, 3, 1)
    return builder.as_markup()


