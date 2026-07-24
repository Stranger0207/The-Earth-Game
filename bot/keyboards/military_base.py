"""کیبوردهای اینلاین مربوط به بخش پایگاه‌های نظامی."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..constants import MILITARY_BASE_TYPES
from ..database.models import MilitaryBase
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def base_main_menu_kb() -> InlineKeyboardMarkup:
    """منوی اصلی بخش پایگاه‌های نظامی."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏗 احداث پایگاه جدید", callback_data="mbase:build", style=STYLE_OK)
    builder.button(text="🏛 پایگاه‌های من", callback_data="mbase:list", style=STYLE_MAIN)
    builder.button(text="📦 استقرار تجهیزات در پایگاه", callback_data="mbase:transfer", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="menu:military", style=STYLE_MAIN)
    builder.adjust(1, 2, 1)
    return builder.as_markup()


def base_types_kb() -> InlineKeyboardMarkup:
    """کیبورد انتخاب نوع پایگاه نظامی."""
    builder = InlineKeyboardBuilder()
    for b_type, (name_fa, cost_usd, cap) in MILITARY_BASE_TYPES.items():
        cost_b = cost_usd / 1_000_000_000
        builder.button(
            text=f"{name_fa} ({cost_b:.0f}B$ | ظرفیت: {cap})",
            callback_data=f"mbase_type:{b_type}",
            style=STYLE_MAIN,
        )
    builder.button(text="🔙 بازگشت", callback_data="mil:base", style=STYLE_NO)
    builder.adjust(1)
    return builder.as_markup()


def bases_list_kb(bases: list[MilitaryBase]) -> InlineKeyboardMarkup:
    """لیست پایگاه‌های فعالی که کاربر مالک آن‌هاست."""
    builder = InlineKeyboardBuilder()
    for b in bases:
        b_type_fa = MILITARY_BASE_TYPES.get(b.base_type, (b.base_type, 0, 0))[0]
        builder.button(
            text=f"🏛 {b.name} ({b_type_fa})",
            callback_data=f"mbase_view:{b.id}",
            style=STYLE_MAIN,
        )
    builder.button(text="🔙 بازگشت", callback_data="mil:base", style=STYLE_NO)
    builder.adjust(1)
    return builder.as_markup()


def base_details_kb(base_id: int) -> InlineKeyboardMarkup:
    """کیبورد مدیریت یک پایگاه خاص."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📦 انتقال تجهیزات به این پایگاه",
        callback_data=f"mbase_tr_to:{base_id}",
        style=STYLE_OK,
    )
    builder.button(
        text="💥 تخریب و تخلیه کامل پایگاه",
        callback_data=f"mbase_del:{base_id}",
        style=STYLE_NO,
    )
    builder.button(text="🔙 بازگشت به لیست", callback_data="mbase:list", style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()
