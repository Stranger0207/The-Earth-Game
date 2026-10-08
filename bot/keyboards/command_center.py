"""
کیبوردهای ستاد فرماندهی کل (v1.10.6).

منوی نظامی از یک فهرست ساده به یک «ستاد فرماندهی» چندبخشی تبدیل شده تا
بازیکن حس کنترل واقعی ارتش را داشته باشد.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def command_center_kb(is_vip: bool = False) -> InlineKeyboardMarkup:
    """منوی اصلی ستاد فرماندهی کل."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 وضعیت ارتش", callback_data="cc:status", style=STYLE_MAIN)
    builder.button(text="📡 ماهواره فضایی", callback_data="mil:sat", style=STYLE_MAIN)
    builder.button(text="🏗 پایگاه‌های نظامی", callback_data="mil:base", style=STYLE_MAIN)
    builder.button(text="🏭 صنایع نظامی", callback_data="cc:industry", style=STYLE_MAIN)
    builder.button(text="⚓ رهگیری محموله", callback_data="op:intercept", style=STYLE_MAIN)
    builder.button(text="🎖 فرماندهان", callback_data="cc:commanders", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="menu:main", style=STYLE_MAIN)
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def asset_picker_kb(
    assets: list[dict],
    selected: dict[str, int],
    *,
    page: int = 0,
    per_page: int = 8,
) -> InlineKeyboardMarkup:
    """
    انتخاب قلم‌به‌قلم تجهیزات از موجودی واقعی کشور (برای رهگیری محموله).
    """
    builder = InlineKeyboardBuilder()
    start = page * per_page
    chunk = assets[start : start + per_page]

    for idx, asset in enumerate(chunk, start=start):
        name = asset["name"]
        picked = selected.get(name, 0)
        mark = f"✅ {picked}× " if picked else ""
        label = f"{mark}{name} ({asset['count']})"
        builder.button(
            text=label[:60],
            callback_data=f"op_asset:{idx}",
            style=STYLE_OK if picked else None,
        )
    builder.adjust(1)

    # ناوبری صفحه‌ها
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(text="◀️ قبلی", callback_data=f"op_page:{page - 1}", style=STYLE_MAIN)
        )
    if start + per_page < len(assets):
        nav.append(
            InlineKeyboardButton(text="بعدی ▶️", callback_data=f"op_page:{page + 1}", style=STYLE_MAIN)
        )
    if nav:
        builder.row(*nav)

    if selected:
        builder.row(
            InlineKeyboardButton(text="➡️ ادامه", callback_data="op_assets_done", style=STYLE_OK)
        )
        builder.row(
            InlineKeyboardButton(text="🗑 پاک‌کردن انتخاب", callback_data="op_assets_clear", style=STYLE_NO)
        )
    builder.row(
        InlineKeyboardButton(text="❌ انصراف", callback_data="menu:military", style=STYLE_NO)
    )
    return builder.as_markup()


def industry_menu_kb() -> InlineKeyboardMarkup:
    """منوی صنایع نظامی."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏭 کارخانه نظامی", callback_data="mil:factory", style=STYLE_MAIN)
    builder.button(text="💰 فروش تجهیزات", callback_data="mil:sell", style=STYLE_OK)
    builder.button(text="🪖 استقرار نیرو", callback_data="mil:deploy", style=STYLE_MAIN)
    builder.button(text="☢️ تأسیسات هسته‌ای", callback_data="mil:nuclear", style=STYLE_NO)
    builder.button(text="🔙 بازگشت", callback_data="menu:military", style=STYLE_MAIN)
    builder.adjust(2, 2, 1)
    return builder.as_markup()
