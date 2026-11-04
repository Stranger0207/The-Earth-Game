"""کیبوردهای تعاملی شیشه‌ای برای داشبورد تراز جهانی و گزارش‌های آماری ادمین."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..utils.ui import STYLE_MAIN, STYLE_OK


def global_report_dashboard_kb(current_hours: int = 8) -> InlineKeyboardMarkup:
    """
    کیبورد ۵ ردیفه تعاملی داشبورد مدیریت تراز جهانی:
    ردیف ۱: خلاصه (۸، ۲۴، ۷۲ ساعته)
    ردیف ۲: گزارش کامل تفصیلی (۸، ۲۴، ۷۲ ساعته)
    ردیف ۳: تمرکز ۳ دارنده برتر و وضعیت بازار لحظه‌ای
    ردیف ۴: دانلود فایل‌های CSV (۸ و ۲۴ ساعته)
    ردیف ۵: بازگشت به پنل اصلی گادمود (god:home)
    """
    builder = InlineKeyboardBuilder()

    # ردیف ۱: خلاصه
    builder.row(
        InlineKeyboardButton(
            text="📋 خلاصه (8h)" + (" 🔘" if current_hours == 8 else ""),
            callback_data="rep:short:8",
            style=STYLE_OK if current_hours == 8 else None,
        ),
        InlineKeyboardButton(
            text="📋 خلاصه (24h)" + (" 🔘" if current_hours == 24 else ""),
            callback_data="rep:short:24",
            style=STYLE_OK if current_hours == 24 else None,
        ),
        InlineKeyboardButton(
            text="📋 خلاصه (72h)" + (" 🔘" if current_hours == 72 else ""),
            callback_data="rep:short:72",
            style=STYLE_OK if current_hours == 72 else None,
        ),
    )

    # ردیف ۲: گزارش کامل تفصیلی
    builder.row(
        InlineKeyboardButton(
            text="📈 گزارش کامل (8h)",
            callback_data="rep:full:8",
            style=STYLE_MAIN,
        ),
        InlineKeyboardButton(
            text="📈 گزارش کامل (24h)",
            callback_data="rep:full:24",
            style=STYLE_MAIN,
        ),
        InlineKeyboardButton(
            text="📈 گزارش کامل (72h)",
            callback_data="rep:full:72",
            style=STYLE_MAIN,
        ),
    )

    # ردیف ۳: تمرکز منابع و بازار
    builder.row(
        InlineKeyboardButton(
            text="🏆 تمرکز منابع (Top Holders)",
            callback_data=f"rep:top:{current_hours}",
            style=STYLE_MAIN,
        ),
        InlineKeyboardButton(
            text="💹 وضعیت بازار و WTO",
            callback_data=f"rep:market:{current_hours}",
            style=STYLE_MAIN,
        ),
    )

    # ردیف ۴: دریافت CSV
    builder.row(
        InlineKeyboardButton(
            text="📥 دریافت فایل‌های CSV (8h)",
            callback_data="rep:csv:8",
            style=STYLE_OK,
        ),
        InlineKeyboardButton(
            text="📥 CSV (24h)",
            callback_data="rep:csv:24",
            style=STYLE_OK,
        ),
    )

    # ردیف ۵: بازگشت به پنل مدیریت
    builder.row(
        InlineKeyboardButton(
            text="🔙 بازگشت به پنل مدیریت",
            callback_data="god:home",
            style=STYLE_MAIN,
        )
    )

    return builder.as_markup()


def global_report_back_kb(hours: int = 8) -> InlineKeyboardMarkup:
    """کیبورد بازگشت از زیرصفحات گزارش به داشبورد تراز جهانی و پنل اصلی مدیریت."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🔙 بازگشت به داشبورد تراز",
            callback_data=f"rep:short:{hours}",
            style=STYLE_MAIN,
        ),
        InlineKeyboardButton(
            text="🏠 پنل مدیریت",
            callback_data="god:home",
            style=STYLE_MAIN,
        ),
    )
    return builder.as_markup()
