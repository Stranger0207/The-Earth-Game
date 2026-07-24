"""کیبوردهای اینلاین بخش جدید نبرد و حملات نظامی (v2.0)."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def battle_attack_types_kb() -> InlineKeyboardMarkup:
    """انتخاب نوع حمله نظامی."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🌾 حمله زمینی", callback_data="btl_atype:ground", style=STYLE_NO)
    builder.button(text="✈️ حمله هوایی", callback_data="btl_atype:air", style=STYLE_NO)
    builder.button(text="🚢 حمله دریایی", callback_data="btl_atype:naval", style=STYLE_NO)
    builder.button(text="🕵️ خرابکاری مخفیانه", callback_data="btl_atype:sabotage", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="menu:military", style=STYLE_MAIN)
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def battle_target_types_kb() -> InlineKeyboardMarkup:
    """انتخاب نوع هدف در کشور دشمن."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏛 پایگاه‌های نظامی", callback_data="btl_ttype:military_base", style=STYLE_NO)
    builder.button(text="🏙 زیرساخت‌های شهری", callback_data="btl_ttype:city", style=STYLE_NO)
    builder.button(text="🛢 سکوی نفتی / گازی", callback_data="btl_ttype:oil_platform", style=STYLE_NO)
    builder.button(text="🏭 کارخانه‌ها و صنایع", callback_data="btl_ttype:factory", style=STYLE_NO)
    builder.button(text="🔙 بازگشت", callback_data="mil:attack", style=STYLE_MAIN)
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def sabotage_claim_kb() -> InlineKeyboardMarkup:
    """انتخاب وضعیت مسئولیت خرابکاری."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✋ پذیرش مسئولیت عملیات", callback_data="btl_claim:yes", style=STYLE_NO)
    builder.button(text="🤫 عملیات مخفیانه (عوامل ناشناس)", callback_data="btl_claim:no", style=STYLE_OK)
    builder.adjust(1)
    return builder.as_markup()
