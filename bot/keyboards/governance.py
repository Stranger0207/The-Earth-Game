"""کیبوردهای بخش حاکمیت (v1.10.2)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..enums import (
    GOVERNMENT_EMOJI,
    GOVERNMENT_FA,
    GovernmentType,
)
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def governance_menu_kb() -> InlineKeyboardMarkup:
    """منوی اصلی حاکمیت."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏛 نظام حاکمیتی", callback_data="gov:system", style=STYLE_MAIN)
    builder.button(text="✊ اعتراضات و رفراندوم", callback_data="gov:protests", style=STYLE_MAIN)
    builder.button(text="📜 قانونگذاری", callback_data="gov:legislation", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="menu:main", style=STYLE_MAIN)
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()


def government_type_kb() -> InlineKeyboardMarkup:
    """انتخاب نوع نظام حاکمیتی."""
    builder = InlineKeyboardBuilder()
    for gt in GovernmentType:
        emoji = GOVERNMENT_EMOJI.get(gt, "")
        fa = GOVERNMENT_FA.get(gt, gt.value)
        builder.button(
            text=f"{emoji} {fa}",
            callback_data=f"gov_type:{gt.value}",
            style=STYLE_OK,
        )
    builder.button(text="🔙 بازگشت", callback_data="gov:system", style=STYLE_MAIN)
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup()


def government_system_kb(has_govt: bool, changes_left: int) -> InlineKeyboardMarkup:
    """منوی نظام حاکمیتی: نمایش وضعیت فعلی + دکمه‌ی تغییر."""
    builder = InlineKeyboardBuilder()
    if has_govt:
        builder.button(text="📋 نظام فعلی من", callback_data="gov:current", style=STYLE_MAIN)
    if changes_left > 0:
        label = "🔄 انتخاب نظام" if not has_govt else "🔄 تغییر نظام"
        builder.button(text=label, callback_data="gov:change_system", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data="menu:governance", style=STYLE_MAIN)
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def protest_menu_kb() -> InlineKeyboardMarkup:
    """منوی اعتراضات."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔴 اعتراضات فعال", callback_data="gov:active_protests", style=STYLE_NO)
    builder.button(text="📋 تاریخچه اعتراضات", callback_data="gov:protest_history", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="menu:governance", style=STYLE_MAIN)
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def protest_action_kb(protest_id: int) -> InlineKeyboardMarkup:
    """دکمه‌های عمل روی اعتراض: سرکوب یا ارجاع به مجلس."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="👊 سرکوب",
        callback_data=f"gov:suppress:{protest_id}",
        style=STYLE_NO,
    )
    builder.button(
        text="🏛 ارجاع به مجلس",
        callback_data=f"gov:parliament_ref:{protest_id}",
        style=STYLE_OK,
    )
    builder.button(text="🔙 بازگشت", callback_data="gov:active_protests", style=STYLE_MAIN)
    builder.adjust(2, 1)
    return builder.as_markup()


def legislation_menu_kb() -> InlineKeyboardMarkup:
    """منوی قانونگذاری."""
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 قانون مالیات", callback_data="gov:tax_law", style=STYLE_MAIN)
    builder.button(text="🛂 قانون ویزا", callback_data="gov:visa_law", style=STYLE_MAIN)
    builder.button(text="🏛 مجلس", callback_data="gov:parliament", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="menu:governance", style=STYLE_MAIN)
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()


def tax_law_kb(current_rate: float) -> InlineKeyboardMarkup:
    """منوی مالیات با نمایش نرخ فعلی."""
    from ..utils.numbers import fa_number
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"📊 نرخ فعلی: {fa_number(current_rate, 1)}٪",
        callback_data="gov:tax_info",
        style=STYLE_MAIN,
    )
    builder.button(text="✏️ تعیین نرخ مالیات", callback_data="gov:set_tax", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data="gov:legislation", style=STYLE_MAIN)
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def visa_law_dashboard_kb() -> InlineKeyboardMarkup:
    """داشبورد اصلی سامانه جامع ویزا و کنترل مرزها."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📋 استعلام وضعیت مرزها (کیا دارن / کیا ندارن)",
        callback_data="gov:visa_status",
        style=STYLE_MAIN,
    )
    builder.button(
        text="➕ وضع ویزا بر چند کشور / قاره",
        callback_data="gov:visa_bulk_menu",
        style=STYLE_NO,
    )
    builder.button(
        text="🌍 وضع ویزا بر تمامی کشورهای جهان",
        callback_data="gov:visa_all_ask",
        style=STYLE_NO,
    )
    builder.button(
        text="🤝 توافقات لغو روادید (دیدارهای حضوری)",
        callback_data="dip:visa_waivers",
        style=STYLE_OK,
    )
    builder.button(
        text="➖ رفع ویزای اجباری (تکی یا همگانی)",
        callback_data="gov:visa_rm_menu",
        style=STYLE_MAIN,
    )
    builder.button(
        text="🔙 بازگشت به قانون‌گذاری",
        callback_data="gov:legislation",
        style=STYLE_MAIN,
    )
    builder.adjust(1, 1, 1, 1, 1, 1)
    return builder.as_markup()


def visa_law_kb() -> InlineKeyboardMarkup:
    """سازگاری با کدهای قبلی."""
    return visa_law_dashboard_kb()


def visa_status_menu_kb(
    req_count: int, granted_count: int, rec_count: int, normal_count: int
) -> InlineKeyboardMarkup:
    """منوی انتخاب دسته‌بندی ویزاها."""
    from ..utils.numbers import fa_number

    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"⛔️ ویزای اجباری وضع‌شده ({fa_number(req_count)})",
        callback_data="gov_vview:req:0",
        style=STYLE_NO,
    )
    builder.button(
        text=f"🤝 لغو روادید اعطایی ({fa_number(granted_count)})",
        callback_data="gov_vview:waiver:0",
        style=STYLE_OK,
    )
    builder.button(
        text=f"📥 لغو روادید دریافتی ({fa_number(rec_count)})",
        callback_data="gov_vview:rec:0",
        style=STYLE_MAIN,
    )
    builder.button(
        text=f"⚪️ مرز عادی (بدون ویزای اجباری) ({fa_number(normal_count)})",
        callback_data="gov_vview:none:0",
        style=STYLE_MAIN,
    )
    builder.button(
        text="🔙 بازگشت به سامانه ویزا",
        callback_data="gov:visa_law",
        style=STYLE_MAIN,
    )
    builder.adjust(1, 1, 1, 1, 1)
    return builder.as_markup()


def visa_all_confirm_kb() -> InlineKeyboardMarkup:
    """تأییدیه وضع ویزا بر همه کشورها."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⛔️ بله، وضع ویزا بر تمامی کشورها",
        callback_data="gov:visa_all_confirm",
        style=STYLE_NO,
    )
    builder.button(
        text="🔙 انصراف و بازگشت",
        callback_data="gov:visa_law",
        style=STYLE_MAIN,
    )
    builder.adjust(1, 1)
    return builder.as_markup()


def visa_rm_menu_kb(has_visas: bool) -> InlineKeyboardMarkup:
    """منوی رفع ویزای اجباری."""
    builder = InlineKeyboardBuilder()
    if has_visas:
        builder.button(
            text="❌ رفع ویزا از یک کشور خاص",
            callback_data="gov_vrm_pick:0",
            style=STYLE_MAIN,
        )
        builder.button(
            text="🔓 رفع ویزا از تمامی کشورها (عادی‌سازی)",
            callback_data="gov_vrm_all_ask",
            style=STYLE_OK,
        )
    builder.button(
        text="🔙 بازگشت به سامانه ویزا",
        callback_data="gov:visa_law",
        style=STYLE_MAIN,
    )
    builder.adjust(1)
    return builder.as_markup()


def visa_rm_all_confirm_kb() -> InlineKeyboardMarkup:
    """تأییدیه رفع ویزا از همه کشورها."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔓 بله، رفع ویزا از تمامی کشورها",
        callback_data="gov_vrm_all_confirm",
        style=STYLE_OK,
    )
    builder.button(
        text="🔙 انصراف",
        callback_data="gov:visa_rm_menu",
        style=STYLE_MAIN,
    )
    builder.adjust(1, 1)
    return builder.as_markup()


def parliament_menu_kb() -> InlineKeyboardMarkup:
    """منوی مجلس."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 ارائه لایحه به مجلس", callback_data="gov:submit_law", style=STYLE_OK)
    builder.button(text="📋 لایحه‌های من", callback_data="gov:my_laws", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="gov:legislation", style=STYLE_MAIN)
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def admin_law_panel_kb(law_id: int) -> InlineKeyboardMarkup:
    """
    پنل مدیریتی لایحه در گروه تحریم و لایحه:
    ۱- تعیین/ویرایش نتیجه لایحه
    ۲- بستن و اعمال نهایی لایحه
    ۳- رد کردن لایحه
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📊 تعیین/ویرایش نتیجه لایحه",
        callback_data=f"gov_admin:law_res:{law_id}",
        style=STYLE_MAIN,
    )
    builder.button(
        text="✅ بستن و اعمال نهایی لایحه",
        callback_data=f"gov_admin:law_apply:{law_id}",
        style=STYLE_OK,
    )
    builder.button(
        text="❌ رد کردن لایحه",
        callback_data=f"gov_admin:law_no:{law_id}",
        style=STYLE_NO,
    )
    builder.adjust(1, 2)
    return builder.as_markup()


def admin_law_result_kb(law_id: int, cur_stab: float, cur_sat: float) -> InlineKeyboardMarkup:
    """
    کیبورد تنظیم اثرات لایحه روی ثبات و رضایت عمومی.
    """
    builder = InlineKeyboardBuilder()

    # ردیف تنظیم ثبات (Presets)
    builder.button(text="ثبات +۲٪", callback_data=f"gov_admin:stab:{law_id}:2", style=STYLE_MAIN)
    builder.button(text="ثبات +۵٪", callback_data=f"gov_admin:stab:{law_id}:5", style=STYLE_MAIN)
    builder.button(text="ثبات +۱۰٪", callback_data=f"gov_admin:stab:{law_id}:10", style=STYLE_MAIN)
    builder.button(text="ثبات +۱۵٪", callback_data=f"gov_admin:stab:{law_id}:15", style=STYLE_MAIN)

    builder.button(text="ثبات -۵٪", callback_data=f"gov_admin:stab:{law_id}:-5", style=STYLE_NO)
    builder.button(text="✏️ عدد دلخواه ثبات", callback_data=f"gov_admin:cstab:{law_id}", style=STYLE_MAIN)

    # ردیف تنظیم رضایت (Presets)
    builder.button(text="رضایت +۲٪", callback_data=f"gov_admin:sat:{law_id}:2", style=STYLE_MAIN)
    builder.button(text="رضایت +۵٪", callback_data=f"gov_admin:sat:{law_id}:5", style=STYLE_MAIN)
    builder.button(text="رضایت +۱۰٪", callback_data=f"gov_admin:sat:{law_id}:10", style=STYLE_MAIN)
    builder.button(text="رضایت +۱۵٪", callback_data=f"gov_admin:sat:{law_id}:15", style=STYLE_MAIN)

    builder.button(text="رضایت -۵٪", callback_data=f"gov_admin:sat:{law_id}:-5", style=STYLE_NO)
    builder.button(text="✏️ عدد دلخواه رضایت", callback_data=f"gov_admin:csat:{law_id}", style=STYLE_MAIN)

    # دکمه‌های ناوبری و اقدام
    builder.button(
        text="🔙 بازگشت به پنل لایحه",
        callback_data=f"gov_admin:law_main:{law_id}",
        style=STYLE_MAIN,
    )
    builder.button(
        text="✅ بستن و اعمال نهایی",
        callback_data=f"gov_admin:law_apply:{law_id}",
        style=STYLE_OK,
    )

    builder.adjust(4, 2, 4, 2, 2)
    return builder.as_markup()

