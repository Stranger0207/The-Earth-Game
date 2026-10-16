"""کیبوردهای اینلاین برای پروژه‌ها و رول‌های اقتصادی (آپدیت شماره ۹)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..database.models import EconomicProject
from ..enums import (
    ECONOMIC_PROJECT_STATUS_FA,
    RESOURCE_EMOJI,
    RESOURCE_FA,
    EconomicProjectStatus,
    ResourceType,
)
from ..utils.numbers import fa_money, fa_number
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def econ_projects_home_kb() -> InlineKeyboardMarkup:
    """منوی اصلی پروژه‌های اقتصادی."""
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ تعریف پروژه جدید", callback_data="econ_proj:new", style=STYLE_OK)
    builder.button(text="📝 پیش‌نویس‌های من (قابل ویرایش)", callback_data="econ_proj:drafts", style=STYLE_MAIN)
    builder.button(text="⏳ پروژه‌های ارسالی / در حال بررسی", callback_data="econ_proj:pending", style=STYLE_MAIN)
    builder.button(text="📈 پروژه‌های فعال من (در حال سوددهی)", callback_data="econ_proj:active", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت به اقتصاد", callback_data="menu:economy", style=STYLE_MAIN)
    builder.adjust(1, 1, 1, 1, 1)
    return builder.as_markup()


def project_list_kb(
    projects: list[EconomicProject],
    back_data: str,
    view_prefix: str = "ep_view",
) -> InlineKeyboardMarkup:
    """لیست پروژه‌ها جهت انتخاب و مشاهده."""
    builder = InlineKeyboardBuilder()
    for p in projects:
        st_fa = ECONOMIC_PROJECT_STATUS_FA.get(EconomicProjectStatus(p.status), p.status)
        btn_text = f"🏗 {p.title[:20]} ({st_fa})"
        builder.button(text=btn_text, callback_data=f"{view_prefix}:{p.id}:1", style=STYLE_MAIN)
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=back_data, style=STYLE_MAIN))
    return builder.as_markup()


def project_draft_view_kb(project: EconomicProject, current_page: int) -> InlineKeyboardMarkup:
    """کیبورد مشاهده و ویرایش پیش‌نویس رول."""
    builder = InlineKeyboardBuilder()

    # ردیف ورق زدن اگر پروژه ۲ صفحه‌ای باشد
    if project.total_pages > 1:
        prev_p = 1 if current_page == 2 else 1
        next_p = 2 if current_page == 1 else 2
        builder.button(text="⬅️ صفحه قبل", callback_data=f"ep_view:{project.id}:{prev_p}", style=STYLE_MAIN)
        builder.button(text=f"📄 {fa_number(current_page)}/{fa_number(project.total_pages)}", callback_data="noop")
        builder.button(text="➡️ صفحه بعد", callback_data=f"ep_view:{project.id}:{next_p}", style=STYLE_MAIN)
        builder.adjust(3)

    # ردیف‌های ویرایش
    builder.row(
        InlineKeyboardButton(text="✏️ ویرایش نام", callback_data=f"ep_edit_title:{project.id}"),
        InlineKeyboardButton(text="💰 ویرایش بودجه", callback_data=f"ep_edit_budget:{project.id}"),
    )
    builder.row(
        InlineKeyboardButton(text="✏️ ویرایش صفحه ۱", callback_data=f"ep_edit_p1:{project.id}"),
        InlineKeyboardButton(
            text="✏️ ویرایش صفحه ۲" if project.page_2 else "➕ افزودن صفحه ۲",
            callback_data=f"ep_edit_p2:{project.id}",
        ),
    )

    # دکمه‌های کنش اصلی
    builder.row(
        InlineKeyboardButton(
            text="🚀 ارسال نهایی به تیم مدیریت",
            callback_data=f"ep_submit_ask:{project.id}",
            style=STYLE_OK,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🗑 حذف پروژه",
            callback_data=f"ep_delete_ask:{project.id}",
            style=STYLE_NO,
        ),
        InlineKeyboardButton(
            text="🔙 بازگشت به پیش‌نویس‌ها",
            callback_data="econ_proj:drafts",
            style=STYLE_MAIN,
        ),
    )
    return builder.as_markup()


def project_submit_confirm_kb(project_id: int) -> InlineKeyboardMarkup:
    """تأیید دومرحله‌ای ارسال نهایی به مدیریت."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ بله، ارسال نهایی", callback_data=f"ep_submit_do:{project_id}", style=STYLE_OK)
    builder.button(text="❌ انصراف و بازگشت", callback_data=f"ep_view:{project_id}:1", style=STYLE_NO)
    builder.adjust(2)
    return builder.as_markup()


def project_delete_confirm_kb(project_id: int, back_page: int = 1) -> InlineKeyboardMarkup:
    """تأیید دومرحله‌ای حذف پیش‌نویس یا لغو پروژه."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 بله، حذف کن", callback_data=f"ep_delete_do:{project_id}", style=STYLE_NO)
    builder.button(text="❌ انصراف", callback_data=f"ep_view:{project_id}:{back_page}", style=STYLE_MAIN)
    builder.adjust(2)
    return builder.as_markup()


def project_pending_view_kb(project: EconomicProject, current_page: int) -> InlineKeyboardMarkup:
    """مشاهده پروژه‌های ارسالی (در انتظار بررسی یا در انتظار افتتاح)."""
    builder = InlineKeyboardBuilder()

    # ردیف ورق زدن
    if project.total_pages > 1:
        prev_p = 1 if current_page == 2 else 1
        next_p = 2 if current_page == 1 else 2
        builder.button(text="⬅️ صفحه قبل", callback_data=f"ep_view:{project.id}:{prev_p}", style=STYLE_MAIN)
        builder.button(text=f"📄 {fa_number(current_page)}/{fa_number(project.total_pages)}", callback_data="noop")
        builder.button(text="➡️ صفحه بعد", callback_data=f"ep_view:{project.id}:{next_p}", style=STYLE_MAIN)
        builder.adjust(3)

    # اگر در وضعیت APPROVED_AWAITING_LAUNCH است، دکمه افتتاح را قرار بده
    if project.status == EconomicProjectStatus.APPROVED_AWAITING_LAUNCH.value:
        builder.row(
            InlineKeyboardButton(
                text="🟢 افتتاح پروژه (پرداخت هزینه)",
                callback_data=f"ep_launch_do:{project.id}",
                style=STYLE_OK,
            )
        )

    builder.row(
        InlineKeyboardButton(
            text="🗑 لغو/حذف پروژه",
            callback_data=f"ep_delete_ask:{project.id}",
            style=STYLE_NO,
        ),
        InlineKeyboardButton(
            text="🔙 بازگشت به پروژه‌ها",
            callback_data="econ_proj:pending",
            style=STYLE_MAIN,
        ),
    )
    return builder.as_markup()


def project_active_view_kb(project: EconomicProject, current_page: int) -> InlineKeyboardMarkup:
    """مشاهده پروژه‌های فعال."""
    builder = InlineKeyboardBuilder()

    if project.total_pages > 1:
        prev_p = 1 if current_page == 2 else 1
        next_p = 2 if current_page == 1 else 2
        builder.button(text="⬅️ صفحه قبل", callback_data=f"ep_view:{project.id}:{prev_p}", style=STYLE_MAIN)
        builder.button(text=f"📄 {fa_number(current_page)}/{fa_number(project.total_pages)}", callback_data="noop")
        builder.button(text="➡️ صفحه بعد", callback_data=f"ep_view:{project.id}:{next_p}", style=STYLE_MAIN)
        builder.adjust(3)

    builder.row(
        InlineKeyboardButton(
            text="🛑 توقف و حذف پروژه",
            callback_data=f"ep_delete_ask:{project.id}",
            style=STYLE_NO,
        ),
        InlineKeyboardButton(
            text="🔙 بازگشت",
            callback_data="econ_proj:active",
            style=STYLE_MAIN,
        ),
    )
    return builder.as_markup()


# ============================================================
#  کیبوردهای گروه رول اقتصادی (-1004359181892)
# ============================================================

def admin_group_project_kb(project: EconomicProject, current_page: int) -> InlineKeyboardMarkup:
    """دکمه‌های زیر پیام در گروه رول اقتصادی."""
    builder = InlineKeyboardBuilder()

    # ردیف ۱: ورق زدن در صورت ۲ صفحه‌ای بودن
    if project.total_pages > 1:
        prev_p = 1 if current_page == 2 else 1
        next_p = 2 if current_page == 1 else 2
        builder.button(text="⬅️ صفحه قبل", callback_data=f"ep_grp_page:{project.id}:{prev_p}")
        builder.button(text=f"📄 {fa_number(current_page)}/{fa_number(project.total_pages)}", callback_data="noop")
        builder.button(text="➡️ صفحه بعد", callback_data=f"ep_grp_page:{project.id}:{next_p}")
        builder.adjust(3)

    # ردیف ۲: داوری ادمین
    builder.row(
        InlineKeyboardButton(
            text="✅ تایید رول و تعیین بازدهی",
            callback_data=f"ep_grp_approve:{project.id}",
            style=STYLE_OK,
        ),
        InlineKeyboardButton(
            text="❌ رد کردن رول",
            callback_data=f"ep_grp_reject:{project.id}",
            style=STYLE_NO,
        ),
    )
    return builder.as_markup()


def admin_rejection_reasons_kb(project_id: int) -> InlineKeyboardMarkup:
    """دلایل آماده رد کردن رول + امکان دلیل دستی."""
    builder = InlineKeyboardBuilder()
    reasons = [
        "عدم تناسب بودجه با حجم پروژه",
        "تناقض با خط‌مشی و قوانین بازی",
        "متن ناقص یا فاقد توجیه اقتصادی",
        "نیاز به اصلاح و بازنویسی",
    ]
    for r in reasons:
        builder.button(text=f"❌ {r}", callback_data=f"ep_rj_quick:{project_id}:{r[:20]}")
    builder.button(text="✍️ نوشتن دلیل اختصاصی", callback_data=f"ep_rj_custom:{project_id}", style=STYLE_MAIN)
    builder.button(text="🔙 انصراف", callback_data=f"ep_grp_cancel:{project_id}", style=STYLE_NO)
    builder.adjust(1)
    return builder.as_markup()


def admin_approve_settings_kb(
    project_id: int,
    launch_cash: float,
    launch_res_count: int,
    yield_cash: float,
    yield_res_count: int,
) -> InlineKeyboardMarkup:
    """منوی تنظیم هزینه‌ها و بازدهی برای تأیید توسط ادمین."""
    builder = InlineKeyboardBuilder()

    cash_btn = f"💵 هزینه دلاری: {fa_money(launch_cash)}"
    res_btn = f"📦 هزینه ذخایر: ({fa_number(launch_res_count)} قلم)"
    builder.button(text=cash_btn, callback_data=f"ep_cfg_cash:{project_id}")
    builder.button(text=res_btn, callback_data=f"ep_cfg_res:{project_id}")

    ycash_btn = f"📈 سود ۷۲ساعته: {fa_money(yield_cash)}"
    yres_btn = f"💎 سود ذخایر: ({fa_number(yield_res_count)} قلم)"
    builder.button(text=ycash_btn, callback_data=f"ep_cfg_ycash:{project_id}")
    builder.button(text=yres_btn, callback_data=f"ep_cfg_yres:{project_id}")

    builder.adjust(1, 1, 1, 1)

    builder.row(
        InlineKeyboardButton(
            text="🚀 صدور تأییدیه و افتتاح",
            callback_data=f"ep_adm_confirm:{project_id}",
            style=STYLE_OK,
        ),
        InlineKeyboardButton(
            text="❌ انصراف",
            callback_data=f"ep_grp_cancel:{project_id}",
            style=STYLE_NO,
        ),
    )
    return builder.as_markup()


def admin_quick_cash_kb(project_id: int, proposed: float) -> InlineKeyboardMarkup:
    """گزینه‌های سریع برای هزینه دلاری افتتاح."""
    builder = InlineKeyboardBuilder()
    builder.button(text=f"قبول بودجه پیشنهادی ({fa_money(proposed)})", callback_data=f"ep_set_cash:{project_id}:{proposed}")
    builder.button(text="افتتاح رایگان ($0)", callback_data=f"ep_set_cash:{project_id}:0")
    builder.button(text="✍️ ورود مبلغ دلخواه", callback_data=f"ep_set_cash_custom:{project_id}", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data=f"ep_grp_approve:{project_id}", style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def admin_quick_yield_kb(project_id: int, proposed: float) -> InlineKeyboardMarkup:
    """گزینه‌های سریع برای سود دلاری ۷۲ ساعته."""
    builder = InlineKeyboardBuilder()
    p10 = round(proposed * 0.10, 2)
    p15 = round(proposed * 0.15, 2)
    p20 = round(proposed * 0.20, 2)
    builder.button(text=f"۱۰٪ بودجه ({fa_money(p10)})", callback_data=f"ep_set_ycash:{project_id}:{p10}")
    builder.button(text=f"۱۵٪ بودجه ({fa_money(p15)})", callback_data=f"ep_set_ycash:{project_id}:{p15}")
    builder.button(text=f"۲۰٪ بودجه ({fa_money(p20)})", callback_data=f"ep_set_ycash:{project_id}:{p20}")
    builder.button(text="✍️ ورود مبلغ دلخواه", callback_data=f"ep_set_ycash_custom:{project_id}", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data=f"ep_grp_approve:{project_id}", style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def admin_resource_picker_kb(project_id: int, mode: str) -> InlineKeyboardMarkup:
    """انتخاب منبع برای هزینه افتتاح یا سود ۷۲ ساعته (mode: 'cost' or 'yield')."""
    builder = InlineKeyboardBuilder()
    for rtype in ResourceType:
        fa = RESOURCE_FA.get(rtype, rtype.value)
        emo = RESOURCE_EMOJI.get(rtype, "📦")
        builder.button(text=f"{emo} {fa}", callback_data=f"ep_pick_res:{project_id}:{mode}:{rtype.value}")
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(text="🗑 پاک‌سازی همه منابع", callback_data=f"ep_clear_res:{project_id}:{mode}", style=STYLE_NO),
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"ep_grp_approve:{project_id}", style=STYLE_MAIN),
    )
    return builder.as_markup()
