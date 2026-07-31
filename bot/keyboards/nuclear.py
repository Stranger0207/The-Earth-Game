"""کیبوردهای پنل برنامه‌ی هسته‌ای (v1.10.4)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..enums import (
    DELIVERY_SYSTEM_FA,
    DeliverySystem,
    NuclearFacilityType,
    NuclearTechType,
)
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def nuclear_main_menu_kb() -> InlineKeyboardMarkup:
    """منوی اصلی تأسیسات هسته‌ای."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 وضعیت برنامه", callback_data="nuc:status", style=STYLE_MAIN)
    builder.button(text="🧪 تحقیقات و فناوری", callback_data="nuc:tech", style=STYLE_MAIN)
    builder.button(text="🏗 تأسیسات", callback_data="nuc:fac", style=STYLE_MAIN)
    builder.button(text="⚙️ غنی‌سازی", callback_data="nuc:enrich", style=STYLE_MAIN)
    builder.button(text="☢️ زرادخانه", callback_data="nuc:arsenal", style=STYLE_MAIN)
    builder.button(text="💥 آزمایش هسته‌ای", callback_data="nuc:test", style=STYLE_NO)
    builder.button(text="🕵️ پنهان‌کاری و امنیت", callback_data="nuc:covert", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="menu:military", style=STYLE_MAIN)
    builder.adjust(1, 2, 2, 2, 1)
    return builder.as_markup()


def nuclear_tech_kb(done: set[str], pending: set[str]) -> InlineKeyboardMarkup:
    """فهرست فناوری‌ها: تیک برای تکمیل‌شده، ساعت برای در حال تحقیق."""
    from ..constants import NUCLEAR_TECHS

    builder = InlineKeyboardBuilder()
    for ttype, (name_fa, _cost, _days, _prereq) in NUCLEAR_TECHS.items():
        if ttype.value in done:
            icon, style = "✅", None
        elif ttype.value in pending:
            icon, style = "⏳", None
        else:
            icon, style = "🔬", STYLE_OK
        kwargs = {"style": style} if style else {}
        builder.button(
            text=f"{icon} {name_fa}", callback_data=f"nuc_tech:{ttype.value}", **kwargs
        )
    builder.button(text="🔙 بازگشت", callback_data="mil:nuclear", style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def nuclear_fac_menu_kb() -> InlineKeyboardMarkup:
    """منوی تأسیسات هسته‌ای."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏗 احداث تأسیسات جدید", callback_data="nuc_fac:build", style=STYLE_OK)
    builder.button(text="📋 تأسیسات من", callback_data="nuc_fac:list", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="mil:nuclear", style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def nuclear_fac_types_kb() -> InlineKeyboardMarkup:
    """انتخاب نوع تأسیسات هسته‌ای برای احداث."""
    from ..constants import NUCLEAR_FACILITIES

    icons = {
        NuclearFacilityType.MILL: "🟡",
        NuclearFacilityType.CONVERSION: "💨",
        NuclearFacilityType.CENTRIFUGE_PLANT: "⚙️",
        NuclearFacilityType.ENRICHMENT_HALL: "⚛️",
        NuclearFacilityType.WEAPONS_LAB: "🔬",
        NuclearFacilityType.TEST_SITE: "💥",
    }
    builder = InlineKeyboardBuilder()
    for ftype, (name_fa, _c, _d, _t, _m) in NUCLEAR_FACILITIES.items():
        builder.button(
            text=f"{icons.get(ftype, '🏗')} {name_fa}",
            callback_data=f"nuc_fac_type:{ftype.value}",
            style=STYLE_OK,
        )
    builder.button(text="🔙 بازگشت", callback_data="nuc:fac", style=STYLE_MAIN)
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def nuclear_underground_kb() -> InlineKeyboardMarkup:
    """انتخاب سطحی/زیرزمینی برای احداث."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏗 سطحی (ارزان‌تر و سریع‌تر)", callback_data="nuc_ug:no", style=STYLE_OK)
    builder.button(text="🕳 زیرزمینی (مخفی‌تر و مقاوم‌تر)", callback_data="nuc_ug:yes", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="nuc_fac:build", style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def nuclear_enrich_menu_kb(active: bool) -> InlineKeyboardMarkup:
    """منوی غنی‌سازی: تولید سانتریفیوژ + شروع/توقف."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⚙️ تولید سانتریفیوژ", callback_data="nuc_en:make", style=STYLE_OK)
    if active:
        builder.button(text="⏸ توقف غنی‌سازی", callback_data="nuc_en:stop", style=STYLE_NO)
    else:
        builder.button(text="▶️ شروع غنی‌سازی", callback_data="nuc_en:start", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data="mil:nuclear", style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def nuclear_tiers_kb() -> InlineKeyboardMarkup:
    """انتخاب رده‌ی هدف غنی‌سازی."""
    from ..constants import ENRICHMENT_TIERS

    builder = InlineKeyboardBuilder()
    for key, name_fa, pct, _swu, _pre in ENRICHMENT_TIERS:
        style = STYLE_NO if pct >= 60 else STYLE_OK
        builder.button(text=f"⚛️ {name_fa}", callback_data=f"nuc_tier:{key}", style=style)
    builder.button(text="🔙 بازگشت", callback_data="nuc:enrich", style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def nuclear_arsenal_kb(has_assembled: bool) -> InlineKeyboardMarkup:
    """منوی زرادخانه."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔧 مونتاژ کلاهک جدید", callback_data="nuc_ar:make", style=STYLE_OK)
    if has_assembled:
        builder.button(text="🚀 نصب روی سامانه‌ی حمل", callback_data="nuc_ar:mount", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="mil:nuclear", style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def delivery_systems_kb(warhead_id: int) -> InlineKeyboardMarkup:
    """انتخاب سامانه‌ی حمل برای یک کلاهک."""
    builder = InlineKeyboardBuilder()
    for system in DeliverySystem:
        builder.button(
            text=DELIVERY_SYSTEM_FA[system],
            callback_data=f"nuc_dlv:{warhead_id}:{system.value}",
            style=STYLE_OK,
        )
    builder.button(text="🔙 بازگشت", callback_data="nuc:arsenal", style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def nuclear_covert_kb(program) -> InlineKeyboardMarkup:
    """منوی پنهان‌کاری: پوشش صلح‌آمیز، ضدجاسوسی، NPT."""
    builder = InlineKeyboardBuilder()
    if program.civilian_cover:
        builder.button(text="🎭 غیرفعال‌کردن پوشش صلح‌آمیز", callback_data="nuc_cv:cover_off", style=STYLE_NO)
    else:
        builder.button(text="🎭 فعال‌کردن پوشش صلح‌آمیز", callback_data="nuc_cv:cover_on", style=STYLE_OK)
    builder.button(text="🕵️ عملیات ضدجاسوسی", callback_data="nuc_cv:counterintel", style=STYLE_MAIN)
    if program.npt_member:
        builder.button(text="📜 خروج از پیمان NPT", callback_data="nuc_cv:npt_exit", style=STYLE_NO)
    builder.button(text="🔙 بازگشت", callback_data="mil:nuclear", style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()
