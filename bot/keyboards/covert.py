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


def covert_menu_kb() -> InlineKeyboardMarkup:
    """منوی عملیات مخفیانه: جاسوسی، ترور، پرونده‌های اطلاعاتی."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔍 عملیات جاسوسی", callback_data="spy:start", style=STYLE_MAIN)
    builder.button(text="🎯 عملیات ترور", callback_data="assn:start", style=STYLE_NO)
    builder.button(text="📁 پرونده‌های اطلاعاتی", callback_data="spy:files", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="cc:operations", style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def commander_targets_kb(
    rows: list[dict],
    *,
    prefix: str,
    back_data: str,
    require_intel: bool = False,
    include_president: bool = False,
) -> InlineKeyboardMarkup:
    """
    فهرست فرماندهان یک کشور برای جاسوسی یا ترور.

    rows: خروجی `espionage_service.targets_with_intel_status`
    require_intel: در حالت ترور، فرمانده‌های بدون اطلاعات غیرفعال نمایش داده می‌شوند.
    include_president: افزودن گزینه‌ی «ترور رئیس‌جمهور» (بدون نیاز به جاسوسی).
    """
    builder = InlineKeyboardBuilder()

    for row in rows:
        commander = row["commander"]
        try:
            role = CommanderRole(commander.role)
            emoji = COMMANDER_ROLE_EMOJI[role]
            role_fa = COMMANDER_ROLE_FA[role]
        except (ValueError, KeyError):
            emoji, role_fa = "🎖", commander.role

        if require_intel and not row["has_intel"]:
            # بدون اطلاعات، ترور ممکن نیست — دکمه راهنما می‌دهد
            builder.button(
                text=f"🔒 {commander.name} ({role_fa}) — بدون اطلاعات",
                callback_data="assn:need_intel",
            )
            continue

        quality_tag = ""
        if row["has_intel"]:
            quality_tag = f" · {fa_number(row['quality'])}٪"

        builder.button(
            text=f"{emoji} {commander.name} — {role_fa}{quality_tag}",
            callback_data=f"{prefix}:{commander.id}",
            style=STYLE_NO if require_intel else STYLE_MAIN,
        )

    builder.adjust(1)

    if include_president:
        builder.row(
            InlineKeyboardButton(
                text="👤 ترور رئیس‌جمهور (بسیار پرخطر)",
                callback_data=f"{prefix}:president",
                style=STYLE_NO,
            )
        )

    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=back_data, style=STYLE_MAIN))
    return builder.as_markup()


def confirm_kb(confirm_data: str, back_data: str) -> InlineKeyboardMarkup:
    """تأیید/انصراف یک عملیات مخفیانه."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ اجرای عملیات", callback_data=confirm_data, style=STYLE_OK)
    builder.button(text="❌ انصراف", callback_data=back_data, style=STYLE_NO)
    builder.adjust(1)
    return builder.as_markup()


def shipments_kb(shipments: list[dict], back_data: str) -> InlineKeyboardMarkup:
    """
    فهرست محموله‌های قابل رهگیری با نمایش وضعیت اسکورت.

    shipments: خروجی `interception_service.interceptable_shipments`
    """
    builder = InlineKeyboardBuilder()

    for item in shipments:
        escort = item["escort_label"]
        label = (
            f"{item['seller']} ← {item['buyer']} | "
            f"{fa_number(item['amount'])} {item['unit']} {item['resource_fa']} | {escort}"
        )
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
