"""کیبوردهای مربوط به بخش ماهواره فضایی."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def satellite_main_menu_kb() -> InlineKeyboardMarkup:
    """منوی اصلی برنامه فضایی و ماهواره."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 پرتاب ماهواره جاسوسی", callback_data="sat:launch", style=STYLE_OK)
    builder.button(text="📡 ماهواره‌های من", callback_data="sat:list", style=STYLE_MAIN)
    builder.button(text="🔭 رصد جاسوسی کشورها", callback_data="sat:scan", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="menu:military", style=STYLE_MAIN)
    builder.adjust(1, 2, 1)
    return builder.as_markup()
