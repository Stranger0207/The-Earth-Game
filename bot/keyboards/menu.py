"""کیبورد پنل اصلی کشور."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb() -> InlineKeyboardMarkup:
    """پنل اصلی مدیریت کشور با سه محور اصلی + بخش‌های جانبی."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 اقتصاد", callback_data="menu:economy")
    builder.button(text="🤝 دیپلماسی", callback_data="menu:diplomacy")
    builder.button(text="⚔️ نظامی", callback_data="menu:military")
    builder.button(text="🧠 مشاور هوشمند", callback_data="menu:advisor")
    builder.button(text="🏛 وضعیت کشور", callback_data="menu:status")
    builder.adjust(3, 2)
    return builder.as_markup()
