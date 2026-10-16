"""کیبوردهای شیشه‌ای مربوط به رول‌ها و پروژه‌های امنیتی (آپدیت شماره ۲)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..constants import SECURITY_ROLE_MAX_PAGES
from ..database.models import SecurityRole
from ..utils.numbers import fa_number
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def security_roles_home_kb() -> InlineKeyboardMarkup:
    """منوی اصلی پروژه‌های امنیتی کشور."""
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ تعریف پروژه جدید", callback_data="sec_proj:new", style=STYLE_OK)
    builder.button(text="📝 پیش‌نویس‌های من", callback_data="sec_proj:drafts", style=STYLE_MAIN)
    builder.button(text="⏳ در انتظار بررسی مدیریت", callback_data="sec_proj:pending", style=STYLE_MAIN)
    builder.button(text="🛡 پروژه‌های تاییدشده (آرشیو)", callback_data="sec_proj:approved", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت به ستاد کل", callback_data="menu:military", style=STYLE_MAIN)
    builder.adjust(1, 2, 1, 1)
    return builder.as_markup()


def security_list_kb(
    roles: list[SecurityRole], back_data: str, view_prefix: str = "sec_view"
) -> InlineKeyboardMarkup:
    """فهرست دکمه‌ای پروژه‌های امنیتی."""
    builder = InlineKeyboardBuilder()
    for role in roles:
        title = role.title[:30]
        pages_badge = f"({fa_number(role.total_pages)} ص)"
        builder.button(
            text=f"🛡 {title} {pages_badge}",
            callback_data=f"{view_prefix}:{role.id}:1",
            style=STYLE_MAIN,
        )
    builder.button(text="🔙 بازگشت", callback_data=back_data, style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def security_draft_view_kb(
    role: SecurityRole, current_page: int
) -> InlineKeyboardMarkup:
    """کیبورد مشاهده، ورق زدن و ارسال پیش‌نویس پروژه امنیتی."""
    builder = InlineKeyboardBuilder()
    total = role.total_pages

    # سطر ناوبری ورق زدن صفحات
    nav_buttons: list[InlineKeyboardButton] = []
    if current_page > 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="⬅️ صفحه قبل",
                callback_data=f"sec_draft_p:{role.id}:{current_page - 1}",
                style=STYLE_MAIN,
            )
        )
    nav_buttons.append(
        InlineKeyboardButton(
            text=f"📄 {fa_number(current_page)}/{fa_number(total)}",
            callback_data="sec_noop",
        )
    )
    if current_page < total:
        nav_buttons.append(
            InlineKeyboardButton(
                text="➡️ صفحه بعد",
                callback_data=f"sec_draft_p:{role.id}:{current_page + 1}",
                style=STYLE_MAIN,
            )
        )
    builder.row(*nav_buttons)

    # امکان افزودن صفحه جدید تا سقف ۵ صفحه
    if total < SECURITY_ROLE_MAX_PAGES:
        builder.row(
            InlineKeyboardButton(
                text=f"➕ افزودن صفحه {fa_number(total + 1)}",
                callback_data=f"sec_draft_addp:{role.id}",
                style=STYLE_MAIN,
            )
        )

    # دکمه ویرایش صفحه فعلی
    builder.row(
        InlineKeyboardButton(
            text=f"✏️ ویرایش صفحه {fa_number(current_page)}",
            callback_data=f"sec_draft_editp:{role.id}:{current_page}",
            style=STYLE_MAIN,
        )
    )

    # ارسال نهایی با هزینه ۲۰M
    builder.row(
        InlineKeyboardButton(
            text="🚀 ارسال نهایی به تیم مدیریت (۲۰M$)",
            callback_data=f"sec_draft_submit:{role.id}",
            style=STYLE_OK,
        )
    )

    # حذف و بازگشت
    builder.row(
        InlineKeyboardButton(
            text="🗑 حذف این پیش‌نویس",
            callback_data=f"sec_draft_del:{role.id}",
            style=STYLE_NO,
        ),
        InlineKeyboardButton(
            text="🔙 بازگشت به لیست",
            callback_data="sec_proj:drafts",
            style=STYLE_MAIN,
        ),
    )
    return builder.as_markup()


def security_submit_confirm_kb(role_id: int) -> InlineKeyboardMarkup:
    """تأیید دومرحله‌ای کسر ۲۰ میلیون دلار و ارسال نهایی."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ تأیید کسر ۲۰M$ و ارسال نهایی",
        callback_data=f"sec_submit_do:{role_id}",
        style=STYLE_OK,
    )
    builder.button(
        text="❌ انصراف و بازگشت",
        callback_data=f"sec_draft_p:{role_id}:1",
        style=STYLE_NO,
    )
    builder.adjust(1)
    return builder.as_markup()


def security_delete_confirm_kb(role_id: int) -> InlineKeyboardMarkup:
    """تأیید حذف پیش‌نویس پروژه امنیتی."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🗑 بله، پیش‌نویس حذف شود",
        callback_data=f"sec_del_do:{role_id}",
        style=STYLE_NO,
    )
    builder.button(
        text="❌ انصراف",
        callback_data=f"sec_draft_p:{role_id}:1",
        style=STYLE_MAIN,
    )
    builder.adjust(1)
    return builder.as_markup()


def security_approved_view_kb(
    role: SecurityRole, current_page: int, back_callback: str = "sec_proj:approved"
) -> InlineKeyboardMarkup:
    """کیبورد مشاهده پروژه امنیتی تاییدشده (فقط خواندنی و ورق‌زدن)."""
    builder = InlineKeyboardBuilder()
    total = role.total_pages

    nav_buttons: list[InlineKeyboardButton] = []
    if current_page > 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="⬅️ صفحه قبل",
                callback_data=f"sec_view_p:{role.id}:{current_page - 1}:{back_callback}",
                style=STYLE_MAIN,
            )
        )
    nav_buttons.append(
        InlineKeyboardButton(
            text=f"📄 {fa_number(current_page)}/{fa_number(total)}",
            callback_data="sec_noop",
        )
    )
    if current_page < total:
        nav_buttons.append(
            InlineKeyboardButton(
                text="➡️ صفحه بعد",
                callback_data=f"sec_view_p:{role.id}:{current_page + 1}:{back_callback}",
                style=STYLE_MAIN,
            )
        )
    builder.row(*nav_buttons)
    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=back_callback, style=STYLE_MAIN)
    )
    return builder.as_markup()


def admin_group_security_role_kb(
    role: SecurityRole, current_page: int
) -> InlineKeyboardMarkup:
    """کیبورد داوری پروژه امنیتی در گروه رول امنیتی (-1004317826815)."""
    builder = InlineKeyboardBuilder()
    total = role.total_pages

    # ورق زدن
    nav_buttons: list[InlineKeyboardButton] = []
    if current_page > 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="⬅️ صفحه قبل",
                callback_data=f"sec_grp_p:{role.id}:{current_page - 1}",
                style=STYLE_MAIN,
            )
        )
    nav_buttons.append(
        InlineKeyboardButton(
            text=f"📄 {fa_number(current_page)}/{fa_number(total)}",
            callback_data="sec_noop",
        )
    )
    if current_page < total:
        nav_buttons.append(
            InlineKeyboardButton(
                text="➡️ صفحه بعد",
                callback_data=f"sec_grp_p:{role.id}:{current_page + 1}",
                style=STYLE_MAIN,
            )
        )
    builder.row(*nav_buttons)

    # اکشن‌های داوری
    builder.row(
        InlineKeyboardButton(
            text="✅ تایید رول امنیتی",
            callback_data=f"sec_grp_approve:{role.id}",
            style=STYLE_OK,
        ),
        InlineKeyboardButton(
            text="❌ رد کردن رول",
            callback_data=f"sec_grp_reject:{role.id}",
            style=STYLE_NO,
        ),
    )
    return builder.as_markup()
