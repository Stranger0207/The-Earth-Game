"""هندلرهای مربوط به سیستم رول‌ها و پروژه‌های امنیتی (آپدیت شماره ۲)."""

from __future__ import annotations

import logging
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import MAX_ROLE_PAGE_LEN, SECURITY_ROLE_COST, SECURITY_ROLE_MAX_PAGES
from ..database.models import Country, SecurityRole, User
from ..database.repositories import countries as countries_repo
from ..database.repositories import security_roles as sec_repo
from ..enums import AdminGroupType, SecurityRoleStatus
from ..keyboards.security_roles import (
    admin_group_security_role_kb,
    security_approved_view_kb,
    security_delete_confirm_kb,
    security_draft_view_kb,
    security_list_kb,
    security_roles_home_kb,
    security_submit_confirm_kb,
)
from ..loader import bot
from ..services.news_service import send_log, send_to_admin_group
from ..services.security_role_service import (
    approve_security_role,
    reject_security_role,
    render_security_role_message,
    submit_security_role,
    validate_role_page,
)
from ..states.forms import SecurityRoleDraftForm, SecurityRoleRejectForm
from ..utils.numbers import fa_money, fa_number
from ..utils.screens import safe_edit, show_menu
from ..utils.ui import DIVIDER, STYLE_MAIN, STYLE_NO, STYLE_OK, header
from .deps import NO_COUNTRY_TEXT, assert_feature, get_player_country

logger = logging.getLogger(__name__)
router = Router(name="security_roles")
settings = get_settings()


# ============================================================
#  ورودی و منوی اصلی پروژه‌های امنیتی
# ============================================================

@router.callback_query(F.data == "mil:security_roles")
async def cb_security_roles_home(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """منوی اصلی پروژه‌های امنیتی کشور."""
    await call.answer()
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "security_roles"):
        return

    text = (
        header("پروژه‌های امنیتی و پدافندی", "🛡")
        + f"\n\nکشور: {country.flag} <b>{country.name_fa}</b>\n"
        f"موجودی بودجه: <b>{fa_money(country.budget)}</b>\n"
        f"{DIVIDER}\n"
        "در این بخش می‌توانید پروژه‌ها و رول‌های دفاعی، امنیتی و ضدجاسوسی کشور خود را تدوین کنید.\n\n"
        "📌 <b>قوانین و ساختار رول امنیتی:</b>\n"
        f"• نگارش بین ۱ تا ۵ صفحه (حداکثر سقف هر صفحه {fa_number(MAX_ROLE_PAGE_LEN)} کاراکتر)\n"
        f"• هزینه ثبت و ارسال نهایی: <b>{fa_money(SECURITY_ROLE_COST)}</b>\n"
        "• پس از تایید توسط تیم مدیریت، پروژه به <b>آرشیو امنیتی کشور</b> اضافه می‌شود و "
        "در زمان حملات و عملیات‌های نظامی ملاک عمل و بررسی ادمین‌ها خواهد بود.\n"
        "• در صورت رد رول توسط مدیریت، کل مبلغ ۲۰ میلیون دلار به خزانه کشور بازگردانده می‌شود.\n\n"
        "گزینه مورد نظر را انتخاب کنید:"
    )
    await show_menu(call, text, reply_markup=security_roles_home_kb(), image_key="security_roles")


# ============================================================
#  فهرست‌ها: پیش‌نویس‌ها، در حال بررسی، آرشیو تاییدشده
# ============================================================

@router.callback_query(F.data == "sec_proj:drafts")
async def cb_drafts_list(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """فهرست پیش‌نویس‌های پروژه امنیتی کشور."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    drafts = await sec_repo.list_drafts_by_country(session, country.id)
    if not drafts:
        await safe_edit(
            call,
            "📝 شما در حال حاضر هیچ پیش‌نویس پروژه امنیتی ندارید.\n"
            "برای ایجاد پیش‌نویس جدید از دکمه زیر استفاده کنید.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="➕ تعریف پروژه جدید", callback_data="sec_proj:new", style=STYLE_OK)],
                    [InlineKeyboardButton(text="🔙 بازگشت", callback_data="mil:security_roles", style=STYLE_MAIN)],
                ]
            ),
        )
        return

    text = (
        header("پیش‌نویس‌های پروژه‌های امنیتی", "📝")
        + f"\n\nتعداد پیش‌نویس‌های در دست نگارش: <b>{fa_number(len(drafts))}</b>\n"
        "جهت مشاهده، ویرایش صفحات یا ارسال نهایی، پروژه موردنظر را انتخاب کنید:"
    )
    await safe_edit(
        call,
        text,
        reply_markup=security_list_kb(drafts, back_data="mil:security_roles", view_prefix="sec_draft_p"),
    )


@router.callback_query(F.data == "sec_proj:pending")
async def cb_pending_list(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """فهرست پروژه‌های امنیتی ارسال‌شده به مدیریت."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    pending = await sec_repo.list_pending_by_country(session, country.id)
    if not pending:
        await safe_edit(
            call,
            "⏳ در حال حاضر هیچ پروژه امنیتی در انتظار بررسی مدیریت ندارید.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 بازگشت", callback_data="mil:security_roles", style=STYLE_MAIN)],
                ]
            ),
        )
        return

    text = (
        header("پروژه‌های امنیتی در انتظار بررسی", "⏳")
        + f"\n\nتعداد پروژه‌ها در صف داوری مدیریت: <b>{fa_number(len(pending))}</b>\n"
        "این پروژه‌ها در گروه رول امنیتی ارسال شده‌اند و متن آن‌ها تا زمان داوری قفل است:"
    )
    await safe_edit(
        call,
        text,
        reply_markup=security_list_kb(pending, back_data="mil:security_roles", view_prefix="sec_view_pend"),
    )


@router.callback_query(F.data == "sec_proj:approved")
async def cb_approved_list(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """آرشیو پروژه‌های امنیتی تاییدشده کشور."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    approved = await sec_repo.list_approved_by_country(session, country.id)
    if not approved:
        await safe_edit(
            call,
            "🛡 شما هنوز هیچ پروژه امنیتی تاییدشده‌ای در آرشیو کشور ندارید.\n"
            "پروژه‌های ارسالی پس از تایید توسط تیم مدیریت در این بخش نگهداری خواهند شد.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 بازگشت", callback_data="mil:security_roles", style=STYLE_MAIN)],
                ]
            ),
        )
        return

    text = (
        header("آرشیو پروژه‌های امنیتی تاییدشده", "🛡")
        + f"\n\nتعداد پروژه‌های تاییدشده کشور: <b>{fa_number(len(approved))}</b>\n"
        "این پروژه‌ها در پایگاه داده‌های ستاد کل و پنل رول‌های ادمین ثبت هستند:"
    )
    await safe_edit(
        call,
        text,
        reply_markup=security_list_kb(approved, back_data="mil:security_roles", view_prefix="sec_view_app"),
    )


# ============================================================
#  فلوی ایجاد و نگارش پیش‌نویس (FSM)
# ============================================================

@router.callback_query(F.data == "sec_proj:new")
async def cb_new_security_role(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """شروع تعریف پروژه امنیتی جدید."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "security_roles"):
        return

    await state.set_state(SecurityRoleDraftForm.entering_title)
    text = (
        header("تعریف پروژه امنیتی جدید", "🛡")
        + "\n\nلطفاً <b>عنوان پروژه امنیتی</b> خود را ارسال کنید (حداکثر ۵۰ کاراکتر):\n"
        "<i>مثال: سامانه پدافند چندلایه پایتخت / سیستم ضدخرابکاری تأسیسات نفتی</i>"
    )
    await safe_edit(
        call,
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ انصراف", callback_data="mil:security_roles", style=STYLE_NO)],
            ]
        ),
    )


@router.message(StateFilter(SecurityRoleDraftForm.entering_title))
async def msg_sec_title(message: Message, state: FSMContext) -> None:
    """دریافت عنوان پروژه امنیتی."""
    title = (message.text or "").strip()
    if not title or len(title) > 50:
        await message.answer("⚠️ لطفاً عنوان پروژه را حداکثر تا ۵۰ کاراکتر وارد کنید:")
        return

    await state.update_data(title=title, page_num=1)
    await state.set_state(SecurityRoleDraftForm.entering_page)
    await message.answer(
        f"✅ عنوان پروژه: <b>{title}</b>\n\n"
        f"اکنون <b>متن صفحه اول</b> رول امنیتی خود را ارسال کنید.\n"
        f"⚠️ <b>توجه:</b> سقف مجاز هر صفحه حداکثر <b>{fa_number(MAX_ROLE_PAGE_LEN)}</b> کاراکتر است.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ انصراف", callback_data="mil:security_roles", style=STYLE_NO)],
            ]
        ),
    )


@router.message(StateFilter(SecurityRoleDraftForm.entering_page))
async def msg_sec_page(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """دریافت متن صفحه پروژه امنیتی."""
    raw = (message.text or "").strip()
    valid, err = validate_role_page(raw)
    if not valid:
        await message.answer(f"⚠️ {err}\nلطفاً متن صفحه را مجدداً ارسال کنید:")
        return

    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        await state.clear()
        return

    data = await state.get_data()
    role_id = data.get("role_id")
    page_num = data.get("page_num", 1)

    if role_id:
        role = await sec_repo.get_security_role(session, role_id)
        if not role or role.status != SecurityRoleStatus.DRAFT.value:
            await message.answer("❌ پیش‌نویس موردنظر یافت نشد یا قفل شده است.")
            await state.clear()
            return
        role.set_page_text(page_num, raw)
        await session.commit()
    else:
        title = data.get("title", "پروژه امنیتی بدون عنوان")
        role = SecurityRole(
            country_id=country.id,
            title=title,
            page_1=raw,
            status=SecurityRoleStatus.DRAFT.value,
        )
        await sec_repo.create_security_role(session, role)
        await session.commit()

    await state.clear()
    msg_text = render_security_role_message(role, country, page_num)
    await message.answer(
        f"✅ <b>صفحه {fa_number(page_num)} با موفقیت ثبت شد.</b>\n\n{msg_text}",
        reply_markup=security_draft_view_kb(role, page_num),
    )


# ============================================================
#  ورق زدن، افزودن صفحه و ویرایش پیش‌نویس
# ============================================================

@router.callback_query(F.data.startswith("sec_draft_p:"))
async def cb_draft_page(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """ورق زدن صفحات پیش‌نویس پروژه امنیتی."""
    await call.answer()
    parts = call.data.split(":")
    role_id, page_num = int(parts[1]), int(parts[2])

    role = await sec_repo.get_security_role(session, role_id)
    if not role or role.status != SecurityRoleStatus.DRAFT.value:
        await safe_edit(call, "❌ این پیش‌نویس یافت نشد یا دیگر در حالت پیش‌نویس نیست.")
        return

    country = await countries_repo.get_country(session, role.country_id)
    if not country:
        return

    msg_text = render_security_role_message(role, country, page_num)
    await safe_edit(call, msg_text, reply_markup=security_draft_view_kb(role, page_num))


@router.callback_query(F.data.startswith("sec_draft_addp:"))
async def cb_draft_add_page(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """افزودن صفحه جدید به پیش‌نویس پروژه امنیتی."""
    await call.answer()
    role_id = int(call.data.split(":")[1])
    role = await sec_repo.get_security_role(session, role_id)
    if not role or role.status != SecurityRoleStatus.DRAFT.value:
        await safe_edit(call, "❌ پیش‌نویس یافت نشد.")
        return

    total = role.total_pages
    if total >= SECURITY_ROLE_MAX_PAGES:
        await call.answer("سقف ۵ صفحه برای این پروژه تکمیل شده است.", show_alert=True)
        return

    next_page = total + 1
    await state.set_state(SecurityRoleDraftForm.entering_page)
    await state.update_data(role_id=role_id, page_num=next_page)

    await safe_edit(
        call,
        f"📄 <b>نگارش صفحه {fa_number(next_page)} از {fa_number(SECURITY_ROLE_MAX_PAGES)}</b>\n\n"
        f"پروژه: <b>{role.title}</b>\n"
        f"لطفاً متن صفحه {fa_number(next_page)} را ارسال کنید (حداکثر {fa_number(MAX_ROLE_PAGE_LEN)} کاراکتر):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 انصراف", callback_data=f"sec_draft_p:{role_id}:{total}", style=STYLE_NO)],
            ]
        ),
    )


@router.callback_query(F.data.startswith("sec_draft_editp:"))
async def cb_draft_edit_page(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """ویرایش متن صفحه مشخص از پیش‌نویس."""
    await call.answer()
    parts = call.data.split(":")
    role_id, page_num = int(parts[1]), int(parts[2])

    role = await sec_repo.get_security_role(session, role_id)
    if not role or role.status != SecurityRoleStatus.DRAFT.value:
        await safe_edit(call, "❌ پیش‌نویس یافت نشد.")
        return

    await state.set_state(SecurityRoleDraftForm.entering_page)
    await state.update_data(role_id=role_id, page_num=page_num)

    await safe_edit(
        call,
        f"✏️ <b>ویرایش صفحه {fa_number(page_num)}</b> از پروژه <b>{role.title}</b>\n\n"
        f"لطفاً متن جدید صفحه را ارسال کنید (حداکثر {fa_number(MAX_ROLE_PAGE_LEN)} کاراکتر):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 انصراف", callback_data=f"sec_draft_p:{role_id}:{page_num}", style=STYLE_NO)],
            ]
        ),
    )


# ============================================================
#  حذف پیش‌نویس
# ============================================================

@router.callback_query(F.data.startswith("sec_draft_del:"))
async def cb_draft_del_ask(call: CallbackQuery, session: AsyncSession) -> None:
    """درخواست تأیید حذف پیش‌نویس."""
    await call.answer()
    role_id = int(call.data.split(":")[1])
    role = await sec_repo.get_security_role(session, role_id)
    if not role:
        await safe_edit(call, "❌ پیش‌نویس یافت نشد.")
        return

    text = (
        f"🗑 <b>تأیید حذف پیش‌نویس</b>\n\n"
        f"آیا مطمئن هستید که می‌خواهید پیش‌نویس پروژه <b>«{role.title}»</b> را حذف کنید؟\n"
        f"این اقدام برگشت‌پذیر نیست."
    )
    await safe_edit(call, text, reply_markup=security_delete_confirm_kb(role_id))


@router.callback_query(F.data.startswith("sec_del_do:"))
async def cb_draft_del_do(call: CallbackQuery, session: AsyncSession) -> None:
    """حذف قطعی پیش‌نویس پروژه امنیتی."""
    await call.answer("پیش‌نویس حذف شد.")
    role_id = int(call.data.split(":")[1])
    role = await sec_repo.get_security_role(session, role_id)
    if role and role.status == SecurityRoleStatus.DRAFT.value:
        await sec_repo.delete_security_role(session, role)
        await session.commit()

    await safe_edit(
        call,
        "🗑 پیش‌نویس پروژه امنیتی با موفقیت حذف شد.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📝 پیش‌نویس‌های من", callback_data="sec_proj:drafts", style=STYLE_MAIN)],
                [InlineKeyboardButton(text="🔙 منوی پروژه‌ها", callback_data="mil:security_roles", style=STYLE_MAIN)],
            ]
        ),
    )


# ============================================================
#  ارسال نهایی به تیم مدیریت با کسر ۲۰M$
# ============================================================

@router.callback_query(F.data.startswith("sec_draft_submit:"))
async def cb_draft_submit_ask(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """درخواست تأیید کسر ۲۰ میلیون دلار و ارسال نهایی."""
    await call.answer()
    role_id = int(call.data.split(":")[1])
    role = await sec_repo.get_security_role(session, role_id)
    if not role or role.status != SecurityRoleStatus.DRAFT.value:
        await safe_edit(call, "❌ پیش‌نویس یافت نشد یا قبلاً ارسال شده است.")
        return

    country = await countries_repo.get_country(session, role.country_id)
    if not country:
        return

    text = (
        header("تأییدیه ارسال نهایی پروژه امنیتی", "⚠️")
        + f"\n\nپروژه: <b>{role.title}</b> ({fa_number(role.total_pages)} صفحه)\n"
        f"موجودی فعلی بودجه: <b>{fa_money(country.budget)}</b>\n"
        f"هزینه ارسال به مدیریت: <b>{fa_money(SECURITY_ROLE_COST)}</b>\n"
        f"{DIVIDER}\n"
        f"🔒 <b>نکات مهم:</b>\n"
        f"۱. با ارسال نهایی، مبلغ ۲۰ میلیون دلار از بودجه کسر شده و امکان ویرایش صفحات قفل خواهد شد.\n"
        f"۲. پروژه بلافاصله در گروه داوری رول امنیتی ارسال می‌شود.\n"
        f"۳. در صورت تایید، پروژه در آرشیو دائمی ثبت و در زمان جنگ استفاده می‌شود.\n"
        f"۴. در صورت رد توسط مدیریت، ۲۰ میلیون دلار مسترد می‌گردد.\n\n"
        f"آیا برای ارسال نهایی اطمینان دارید؟"
    )
    await safe_edit(call, text, reply_markup=security_submit_confirm_kb(role_id))


@router.callback_query(F.data.startswith("sec_submit_do:"))
async def cb_draft_submit_do(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """کسر ۲۰ میلیون دلار، تغییر وضعیت به PENDING_REVIEW و ارسال به گروه رول امنیتی."""
    await call.answer()
    role_id = int(call.data.split(":")[1])
    role = await sec_repo.get_security_role(session, role_id)
    if not role or role.status != SecurityRoleStatus.DRAFT.value:
        await safe_edit(call, "❌ پیش‌نویس یافت نشد یا قبلاً ارسال شده است.")
        return

    country = await countries_repo.get_country(session, role.country_id)
    if not country:
        return

    ok, err = await submit_security_role(session, role, country)
    if not ok:
        await call.answer(err, show_alert=True)
        await safe_edit(call, err, reply_markup=security_draft_view_kb(role, 1))
        return

    # ارسال به گروه رول امنیتی (-1004317826815)
    group_text = render_security_role_message(role, country, 1)
    group_kb = admin_group_security_role_kb(role, 1)

    sent_msg = await send_to_admin_group(
        bot,
        AdminGroupType.ROLE_SECURITY,
        group_text,
        reply_markup=group_kb,
    )
    if sent_msg:
        role.admin_message_id = sent_msg.message_id

    await session.commit()

    # ثبت در گروه لاگ
    await send_log(
        bot,
        f"🛡 <b>ارسال پروژه امنیتی جدید</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"عنوان: {role.title} ({fa_number(role.total_pages)} صفحه)\n"
        f"هزینه کسرشده: {fa_money(SECURITY_ROLE_COST)}",
    )

    success_text = (
        header("ارسال موفق پروژه امنیتی", "✅")
        + f"\n\nپروژه <b>«{role.title}»</b> با موفقیت به تیم مدیریت ارسال شد.\n"
        f"مبلغ <b>{fa_money(SECURITY_ROLE_COST)}</b> از خزانه‌ی کشور کسر گردید.\n\n"
        f"نتیجه بررسی و داوری مدیریت از طریق ربات به شما اطلاع‌رسانی خواهد شد."
    )
    await safe_edit(
        call,
        success_text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⏳ مشاهده در صف انتظار", callback_data="sec_proj:pending", style=STYLE_MAIN)],
                [InlineKeyboardButton(text="🔙 منوی پروژه‌ها", callback_data="mil:security_roles", style=STYLE_MAIN)],
            ]
        ),
    )


# ============================================================
#  مشاهده صفحات پروژه‌های در حال بررسی و تاییدشده
# ============================================================

@router.callback_query(F.data.startswith("sec_view_pend:"))
async def cb_view_pending_role(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """مشاهده صفحات پروژه امنیتی در حال بررسی."""
    await call.answer()
    parts = call.data.split(":")
    role_id, page_num = int(parts[1]), int(parts[2])

    role = await sec_repo.get_security_role(session, role_id)
    if not role:
        await safe_edit(call, "❌ پروژه یافت نشد.")
        return
    country = await countries_repo.get_country(session, role.country_id)
    if not country:
        return

    msg_text = render_security_role_message(role, country, page_num)
    await safe_edit(
        call,
        msg_text,
        reply_markup=security_approved_view_kb(role, page_num, back_callback="sec_proj:pending"),
    )


@router.callback_query(F.data.startswith("sec_view_app:"))
async def cb_view_approved_role(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """مشاهده صفحات پروژه امنیتی تاییدشده (آرشیو)."""
    await call.answer()
    parts = call.data.split(":")
    role_id, page_num = int(parts[1]), int(parts[2])

    role = await sec_repo.get_security_role(session, role_id)
    if not role:
        await safe_edit(call, "❌ پروژه یافت نشد.")
        return
    country = await countries_repo.get_country(session, role.country_id)
    if not country:
        return

    msg_text = render_security_role_message(role, country, page_num)
    await safe_edit(
        call,
        msg_text,
        reply_markup=security_approved_view_kb(role, page_num, back_callback="sec_proj:approved"),
    )


@router.callback_query(F.data.startswith("sec_view_p:"))
async def cb_view_page_nav(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """ناوبری صفحات در حالت مشاهده فقط خواندنی."""
    await call.answer()
    parts = call.data.split(":")
    role_id, page_num, back_cb = int(parts[1]), int(parts[2]), parts[3]

    role = await sec_repo.get_security_role(session, role_id)
    if not role:
        return
    country = await countries_repo.get_country(session, role.country_id)
    if not country:
        return

    msg_text = render_security_role_message(role, country, page_num)
    await safe_edit(
        call,
        msg_text,
        reply_markup=security_approved_view_kb(role, page_num, back_callback=back_cb),
    )


# ============================================================
#  داوری در گروه رول امنیتی (-1004317826815)
# ============================================================

@router.callback_query(F.data.startswith("sec_grp_p:"))
async def cb_admin_group_page(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """ورق زدن صفحات در گروه رول امنیتی."""
    await call.answer()
    parts = call.data.split(":")
    role_id, page_num = int(parts[1]), int(parts[2])

    role = await sec_repo.get_security_role(session, role_id)
    if not role or role.status != SecurityRoleStatus.PENDING_REVIEW.value:
        return

    country = await countries_repo.get_country(session, role.country_id)
    if not country:
        return

    msg_text = render_security_role_message(role, country, page_num)
    try:
        await call.message.edit_text(
            msg_text,
            reply_markup=admin_group_security_role_kb(role, page_num),
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("sec_grp_approve:"))
async def cb_admin_group_approve(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """تایید پروژه امنیتی توسط ادمین در گروه."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("تنها مدیران بازی مجاز به تایید هستند.", show_alert=True)
        return

    await call.answer("تایید شد ✅")
    role_id = int(call.data.split(":")[1])
    role = await sec_repo.get_security_role(session, role_id)
    if not role or role.status != SecurityRoleStatus.PENDING_REVIEW.value:
        await call.answer("این پروژه قبلاً داوری شده است.", show_alert=True)
        return

    country = await countries_repo.get_country(session, role.country_id)
    if not country:
        return

    await approve_security_role(session, role, call.from_user.id)
    await session.commit()

    # بستن دکمه‌ها و ثبت نام ادمین در پیام گروه
    admin_name = call.from_user.full_name
    try:
        await call.message.edit_text(
            call.message.html_text + f"\n\n✅ <b>توسط {admin_name} تایید شد و به آرشیو امنیتی کشور پیوست.</b>",
            reply_markup=None,
        )
    except Exception:
        pass

    # ارسال نوتیفیکیشن به پیوی لیدر کشور
    if country.owner_user_id:
        try:
            await bot.send_message(
                country.owner_user_id,
                f"🎉 <b>پروژه امنیتی شما تایید شد!</b>\n\n"
                f"پروژه دفاعی <b>«{role.title}»</b> توسط تیم مدیریت بررسی و تایید شد و "
                f"رسماً در آرشیو امنیتی {country.flag} <b>{country.name_fa}</b> ثبت گردید.",
            )
        except Exception:
            pass

    # لاگ مدیران
    await send_log(
        bot,
        f"✅ <b>تایید رول امنیتی</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"عنوان: {role.title}\n"
        f"ادمین: {admin_name}",
    )


@router.callback_query(F.data.startswith("sec_grp_reject:"))
async def cb_admin_group_reject(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """شروع فرایند رد رول امنیتی و دریافت دلیل رد."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("تنها مدیران بازی مجاز به رد رول هستند.", show_alert=True)
        return

    await call.answer()
    role_id = int(call.data.split(":")[1])
    role = await sec_repo.get_security_role(session, role_id)
    if not role or role.status != SecurityRoleStatus.PENDING_REVIEW.value:
        await call.answer("این پروژه قبلاً داوری شده است.", show_alert=True)
        return

    await state.set_state(SecurityRoleRejectForm.entering_reason)
    await state.update_data(
        role_id=role_id,
        admin_chat_id=call.message.chat.id,
        admin_message_id=call.message.message_id,
    )
    await call.message.reply(
        f"❌ <b>رد پروژه امنیتی «{role.title}»</b>\n\n"
        f"لطفاً <b>علت رد</b> را ریپلای کنید (مبلغ ۲۰M$ خودکار به بودجه کشور بازگردانده می‌شود):"
    )


@router.message(StateFilter(SecurityRoleRejectForm.entering_reason))
async def msg_sec_reject_reason(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """ثبت دلیل رد، بازگشت ۲۰ میلیون دلار و ارسال پیام به پیوی بازیکن."""
    reason = (message.text or "").strip()
    if not reason:
        await message.reply("⚠️ لطفاً دلیل رد را بنویسید:")
        return

    data = await state.get_data()
    role_id = data.get("role_id")
    group_chat_id = data.get("admin_chat_id")
    group_msg_id = data.get("admin_message_id")

    role = await sec_repo.get_security_role(session, role_id)
    if not role or role.status != SecurityRoleStatus.PENDING_REVIEW.value:
        await message.reply("❌ این پروژه دیگر در وضعیت انتظار بررسی نیست.")
        await state.clear()
        return

    country = await countries_repo.get_country(session, role.country_id)
    if not country:
        await state.clear()
        return

    admin_name = message.from_user.full_name
    await reject_security_role(session, role, country, message.from_user.id, reason)
    await session.commit()
    await state.clear()

    await message.reply(
        f"✅ رول رد شد، مبلغ ۲۰ میلیون دلار به بودجه {country.name_fa} مسترد گردید."
    )

    # ویرایش پیام در گروه
    if group_chat_id and group_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=group_chat_id,
                message_id=group_msg_id,
                text=(
                    f"❌ <b>این رول امنیتی توسط {admin_name} رد شد.</b>\n"
                    f"علت رد: <i>{reason}</i>\n"
                    f"💰 ۲۰ میلیون دلار به بودجه کشور بازگردانده شد."
                ),
                reply_markup=None,
            )
        except Exception:
            pass

    # پیام به پیوی رهبر کشور
    if country.owner_user_id:
        try:
            await bot.send_message(
                country.owner_user_id,
                f"❌ <b>پروژه امنیتی شما رد شد</b>\n\n"
                f"پروژه امنیتی <b>«{role.title}»</b> توسط تیم مدیریت رد شد.\n"
                f"<b>علت رد:</b> <i>{reason}</i>\n\n"
                f"💰 مبلغ <b>{fa_money(SECURITY_ROLE_COST)}</b> به خزانه‌ی کشور بازگردانده شد.",
            )
        except Exception:
            pass

    # لاگ مدیران
    await send_log(
        bot,
        f"❌ <b>رد رول امنیتی</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"عنوان: {role.title}\n"
        f"علت: {reason}\n"
        f"ادمین: {admin_name}",
    )


@router.callback_query(F.data.in_({"sec_noop", "noop"}))
async def cb_sec_noop(call: CallbackQuery) -> None:
    """پاسخ به دکمه‌های اینلاین غیرفعال (شمارنده صفحات)."""
    await call.answer()
