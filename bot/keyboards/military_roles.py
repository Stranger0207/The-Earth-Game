"""کیبوردهای شیشه‌ای مربوط به رول‌ها و عملیات‌های نظامی (آپدیت شماره ۲)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..constants import (
    MILITARY_ROLE_ASSASSINATION_MAX_PAGES,
    MILITARY_ROLE_ATTACK_MAX_PAGES,
    MILITARY_ROLE_SABOTAGE_MAX_PAGES,
)
from ..database.models import Country, MilitaryRole
from ..enums import MilitaryRoleType
from ..utils.numbers import fa_number
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def military_roles_home_kb() -> InlineKeyboardMarkup:
    """منوی اصلی رول‌ها و عملیات‌های نظامی."""
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ ثبت عملیات جدید", callback_data="mil_ops:new", style=STYLE_OK)
    builder.button(text="📝 پیش‌نویس‌های من", callback_data="mil_ops:drafts", style=STYLE_MAIN)
    builder.button(text="⏳ عملیات‌های در حال اجرای من", callback_data="mil_ops:active", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت به ستاد کل", callback_data="menu:military", style=STYLE_MAIN)
    builder.adjust(1, 2, 1)
    return builder.as_markup()


def military_type_picker_kb() -> InlineKeyboardMarkup:
    """انتخاب نوع رول نظامی (خرابکاری / ترور / حمله)."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"💣 رول خرابکاری (حداکثر {fa_number(MILITARY_ROLE_SABOTAGE_MAX_PAGES)} صفحه)",
        callback_data="mil_type:sabotage",
        style=STYLE_MAIN,
    )
    builder.button(
        text=f"🎯 رول ترور (حداکثر {fa_number(MILITARY_ROLE_ASSASSINATION_MAX_PAGES)} صفحه)",
        callback_data="mil_type:assassination",
        style=STYLE_MAIN,
    )
    builder.button(
        text=f"🚀 رول حمله (حداکثر {fa_number(MILITARY_ROLE_ATTACK_MAX_PAGES)} صفحه)",
        callback_data="mil_type:attack",
        style=STYLE_MAIN,
    )
    builder.button(text="🔙 بازگشت", callback_data="mil:ops_roles", style=STYLE_NO)
    builder.adjust(1)
    return builder.as_markup()


def military_target_picker_kb(
    countries: list[Country], attacker_id: int, page: int = 0, per_page: int = 8
) -> InlineKeyboardMarkup:
    """انتخاب کشور هدف (مستثنی کردن کشور مهاجم) با صفحه‌بندی."""
    builder = InlineKeyboardBuilder()
    valid_targets = [c for c in countries if c.id != attacker_id]

    start = page * per_page
    chunk = valid_targets[start : start + per_page]

    for country in chunk:
        builder.button(
            text=f"{country.flag} {country.name_fa}",
            callback_data=f"mil_tgt:{country.id}",
        )
    builder.adjust(2)

    # ناوبری صفحه‌بندی
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="◀️ قبلی", callback_data=f"mil_tgt_p:{page - 1}", style=STYLE_MAIN
            )
        )
    if start + per_page < len(valid_targets):
        nav.append(
            InlineKeyboardButton(
                text="بعدی ▶️", callback_data=f"mil_tgt_p:{page + 1}", style=STYLE_MAIN
            )
        )
    if nav:
        builder.row(*nav)

    builder.row(
        InlineKeyboardButton(text="🔙 انصراف", callback_data="mil:ops_roles", style=STYLE_NO)
    )
    return builder.as_markup()


def military_list_kb(
    roles: list[MilitaryRole],
    back_data: str,
    view_prefix: str = "mil_view",
    countries_map: dict[int, Country] | None = None,
) -> InlineKeyboardMarkup:
    """فهرست دکمه‌ای عملیات‌های نظامی."""
    builder = InlineKeyboardBuilder()
    for role in roles:
        tgt_name = ""
        if countries_map and role.target_country_id in countries_map:
            tgt = countries_map[role.target_country_id]
            tgt_name = f" ⚔️ {tgt.flag} {tgt.name_fa}"

        builder.button(
            text=f"{role.title[:20]}{tgt_name} ({fa_number(role.total_pages)} ص)",
            callback_data=f"{view_prefix}:{role.id}:1",
            style=STYLE_MAIN,
        )
    builder.button(text="🔙 بازگشت", callback_data=back_data, style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def military_draft_view_kb(
    role: MilitaryRole, current_page: int
) -> InlineKeyboardMarkup:
    """کیبورد مشاهده، ورق زدن و ارسال پیش‌نویس رول نظامی."""
    builder = InlineKeyboardBuilder()
    total = role.total_pages
    max_p = role.max_allowed_pages

    # ورق زدن
    nav_buttons: list[InlineKeyboardButton] = []
    if current_page > 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="⬅️ صفحه قبل",
                callback_data=f"mil_draft_p:{role.id}:{current_page - 1}",
                style=STYLE_MAIN,
            )
        )
    nav_buttons.append(
        InlineKeyboardButton(
            text=f"📄 {fa_number(current_page)}/{fa_number(total)}",
            callback_data="mil_noop",
        )
    )
    if current_page < total:
        nav_buttons.append(
            InlineKeyboardButton(
                text="➡️ صفحه بعد",
                callback_data=f"mil_draft_p:{role.id}:{current_page + 1}",
                style=STYLE_MAIN,
            )
        )
    builder.row(*nav_buttons)

    # افزودن صفحه اگر به سقف نرسیده باشد
    if total < max_p:
        builder.row(
            InlineKeyboardButton(
                text=f"➕ افزودن صفحه {fa_number(total + 1)} (تا سقف {fa_number(max_p)})",
                callback_data=f"mil_draft_addp:{role.id}",
                style=STYLE_MAIN,
            )
        )

    # ویرایش صفحه فعلی
    builder.row(
        InlineKeyboardButton(
            text=f"✏️ ویرایش صفحه {fa_number(current_page)}",
            callback_data=f"mil_draft_editp:{role.id}:{current_page}",
            style=STYLE_MAIN,
        )
    )

    # ارسال نهایی عملیات
    builder.row(
        InlineKeyboardButton(
            text="🚀 ارسال نهایی عملیات به ستاد فرماندهی",
            callback_data=f"mil_draft_submit:{role.id}",
            style=STYLE_OK,
        )
    )

    # حذف و بازگشت
    builder.row(
        InlineKeyboardButton(
            text="🗑 حذف این پیش‌نویس",
            callback_data=f"mil_draft_del:{role.id}",
            style=STYLE_NO,
        ),
        InlineKeyboardButton(
            text="🔙 بازگشت به لیست",
            callback_data="mil_ops:drafts",
            style=STYLE_MAIN,
        ),
    )
    return builder.as_markup()


def military_submit_confirm_kb(role_id: int) -> InlineKeyboardMarkup:
    """تأیید نهایی ارسال عملیات نظامی."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🚀 بله، عملیات رسماً آغاز و ارسال شود",
        callback_data=f"mil_submit_do:{role_id}",
        style=STYLE_OK,
    )
    builder.button(
        text="❌ انصراف",
        callback_data=f"mil_draft_p:{role_id}:1",
        style=STYLE_NO,
    )
    builder.adjust(1)
    return builder.as_markup()


def military_delete_confirm_kb(role_id: int) -> InlineKeyboardMarkup:
    """تأیید حذف پیش‌نویس رول نظامی."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🗑 بله، پیش‌نویس حذف شود",
        callback_data=f"mil_del_do:{role_id}",
        style=STYLE_NO,
    )
    builder.button(
        text="❌ انصراف",
        callback_data=f"mil_draft_p:{role_id}:1",
        style=STYLE_MAIN,
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_group_military_role_kb(
    role: MilitaryRole, current_page: int
) -> InlineKeyboardMarkup:
    """
    کیبورد عملیاتی ادمین در گروه رول نظامی (-1004424329237).
    شامل دکمه‌های ثبت تلفات، بررسی آرشیو امنیتی هدف و پایان عملیات.
    """
    builder = InlineKeyboardBuilder()
    total = role.total_pages

    # سطر ورق زدن
    nav_buttons: list[InlineKeyboardButton] = []
    if current_page > 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="⬅️ صفحه قبل",
                callback_data=f"mil_grp_p:{role.id}:{current_page - 1}",
                style=STYLE_MAIN,
            )
        )
    nav_buttons.append(
        InlineKeyboardButton(
            text=f"📄 {fa_number(current_page)}/{fa_number(total)}",
            callback_data="mil_noop",
        )
    )
    if current_page < total:
        nav_buttons.append(
            InlineKeyboardButton(
                text="➡️ صفحه بعد",
                callback_data=f"mil_grp_p:{role.id}:{current_page + 1}",
                style=STYLE_MAIN,
            )
        )
    builder.row(*nav_buttons)

    # دکمه‌های عملیاتی
    builder.row(
        InlineKeyboardButton(
            text="💥 ثبت تلفات",
            callback_data=f"mil_grp_cas:{role.id}",
            style=STYLE_NO,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🛡 مشاهده رول‌های امنیتی کشور هدف",
            callback_data=f"mil_grp_tgt_sec:{role.id}",
            style=STYLE_MAIN,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🏁 پایان عملیات",
            callback_data=f"mil_grp_end:{role.id}",
            style=STYLE_OK,
        )
    )
    return builder.as_markup()


def admin_military_casualty_side_kb(
    role_id: int, attacker_name: str, target_name: str, back_cb: str
) -> InlineKeyboardMarkup:
    """انتخاب طرف درگیر جهت ثبت تلفات و خسارات."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"⚔️ ثبت تلفات کشور مهاجم ({attacker_name})",
        callback_data=f"mil_cas_side:{role_id}:attacker",
        style=STYLE_NO,
    )
    builder.button(
        text=f"🛡 ثبت تلفات و خسارت کشور هدف ({target_name})",
        callback_data=f"mil_cas_side:{role_id}:target",
        style=STYLE_NO,
    )
    builder.button(text="🔙 بازگشت به عملیات", callback_data=back_cb, style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def admin_military_end_confirm_kb(
    role_id: int, back_cb: str
) -> InlineKeyboardMarkup:
    """تأیید پایان دادن به عملیات نظامی و ارسال گزارش به طرفین."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🏁 تأیید اتمام عملیات و ابلاغ به بازیکنان",
        callback_data=f"mil_end_do:{role_id}",
        style=STYLE_OK,
    )
    builder.button(text="❌ انصراف", callback_data=back_cb, style=STYLE_NO)
    builder.adjust(1)
    return builder.as_markup()
