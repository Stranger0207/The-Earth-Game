"""
کیبوردهای عملیات مخفیانه (v1.10.7): جاسوسی، ترور و رهگیری محموله.

جدا از `command_center.py` نگه داشته شده چون این دو جریان منطق انتخاب
پیچیده‌تری دارند (وضعیت اطلاعات، قدرت اسکورت).
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..enums import COMMANDER_ROLE_EMOJI, COMMANDER_ROLE_FA, CommanderRole
from ..utils.numbers import fa_number
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def confirm_kb(confirm_data: str, back_data: str) -> InlineKeyboardMarkup:
    """تأیید/انصراف یک عملیات."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ تأیید", callback_data=confirm_data, style=STYLE_OK)
    builder.button(text="❌ انصراف", callback_data=back_data, style=STYLE_NO)
    builder.adjust(1)
    return builder.as_markup()


def shipments_kb(shipments: list[dict], back_data: str) -> InlineKeyboardMarkup:
    """
    فهرست محموله‌های قابل رهگیری با نمایش وضعیت اسکورت.

    shipments: خروجی `interception_service.interceptable_shipments`

    (v1.11.2) محتویات محموله (نوع و مقدار منبع) به رهگیر نشان داده نمی‌شود؛
    او فقط مبدأ/مقصد و وضعیت اسکورت را می‌بیند و پیش از رهگیری نمی‌داند
    داخل محموله چیست.
    """
    builder = InlineKeyboardBuilder()

    for item in shipments:
        label = f"{item['seller']} ← {item['buyer']} | {item['escort_label']}"
        builder.button(
            text=label[:64],
            callback_data=f"intc_pick:{item['sale_id']}",
            style=STYLE_OK if item["escort_power"] <= 0 else STYLE_NO,
        )

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=back_data, style=STYLE_MAIN))
    return builder.as_markup()


def escort_offer_kb(sale_id: int, kind: str) -> InlineKeyboardMarkup:
    """
    پیشنهاد افزودن اسکورت هنگام ارسال محموله.

    kind: "res" برای محموله‌ی منابع، "mil" برای محموله‌ی نظامی
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🛡 افزودن اسکورت محافظ",
        callback_data=f"escort:add:{kind}:{sale_id}",
        style=STYLE_OK,
    )
    builder.button(
        text="🚫 ارسال بدون اسکورت",
        callback_data=f"escort:skip:{kind}:{sale_id}",
        style=STYLE_MAIN,
    )
    builder.adjust(1)
    return builder.as_markup()
