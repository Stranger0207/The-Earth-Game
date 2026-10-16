"""هندلر پنل جامع مدیریتی /roles برای ادمین‌ها و مالکان (آپدیت شماره ۲)."""

from __future__ import annotations

import logging
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database.models import Country, EconomicProject, MilitaryRole, SecurityRole, User
from ..database.repositories import countries as countries_repo
from ..database.repositories import economic_projects as proj_repo
from ..database.repositories import military_roles as mil_ops_repo
from ..database.repositories import security_roles as sec_repo
from ..enums import AdminGroupType, EconomicProjectStatus, SecurityRoleStatus
from ..keyboards.admin_roles import (
    admin_active_military_list_kb,
    admin_countries_archive_kb,
    admin_pending_econ_list_kb,
    admin_pending_security_list_kb,
    admin_roles_country_security_kb,
    admin_roles_main_kb,
    admin_roles_view_military_kb,
    admin_roles_view_security_kb,
)
from ..keyboards.economic_projects import admin_group_project_kb
from ..loader import bot
from ..services.economic_project_service import render_project_message
from ..services.military_role_service import render_military_role_message
from ..services.news_service import send_log
from ..services.security_role_service import (
    approve_security_role,
    render_security_role_message,
)
from ..states.forms import SecurityRoleRejectForm
from ..utils.numbers import fa_number
from ..utils.screens import safe_edit
from ..utils.ui import DIVIDER, STYLE_MAIN, STYLE_NO, STYLE_OK, header

logger = logging.getLogger(__name__)
router = Router(name="admin_roles")
settings = get_settings()


def _is_admin(user_id: int) -> bool:
    """بررسی دسترسی ادمین یا مالک."""
    return settings.is_admin(user_id) or settings.is_owner(user_id)


# ============================================================
#  دستور اصلی /roles
# ============================================================

@router.message(Command("roles"))
async def cmd_roles(message: Message, state: FSMContext) -> None:
    """مرکز فرماندهی و مدیریت جامع رول‌ها (/roles)."""
    if not _is_admin(message.from_user.id):
        await message.reply("⛔️ شما به این بخش دسترسی ندارید.")
        return

    await state.clear()
    text = (
        header("مرکز مدیریت جامع رول‌ها", "🎖")
        + f"\n\nادمین گرامی <b>{message.from_user.full_name}</b>، به پنل جامع رول‌ها خوش آمدید.\n"
        f"{DIVIDER}\n"
        "از این بخش می‌توانید:\n"
        "• 🛡 به آرشیو تمام پروژه‌های امنیتی تاییدشده کشورها دسترسی پیدا کرده و آن‌ها را مطالعه کنید.\n"
        "• ⏳ رول‌های امنیتی در صف انتظار را ورق زده و تایید یا رد کنید.\n"
        "• 💰 رول‌های اقتصادی در انتظار تایید را بررسی و داوری نمایید.\n"
        "• ⚔️ عملیات‌های نظامی باز را مدیریت، تلفات طرفین را ثبت و عملیات را خاتمه دهید.\n\n"
        "بخش مورد نظر را انتخاب کنید:"
    )
    await message.answer(text, reply_markup=admin_roles_main_kb())


@router.callback_query(F.data == "roles_admin:home")
async def cb_roles_admin_home(call: CallbackQuery, state: FSMContext) -> None:
    """بازگشت به منوی اصلی پنل /roles."""
    if not _is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    await call.answer()
    await state.clear()
    text = (
        header("مرکز مدیریت جامع رول‌ها", "🎖")
        + f"\n\nادمین گرامی <b>{call.from_user.full_name}</b>، به پنل جامع رول‌ها خوش آمدید.\n"
        f"{DIVIDER}\n"
        "بخش مورد نظر را انتخاب کنید:"
    )
    await safe_edit(call, text, reply_markup=admin_roles_main_kb())


@router.callback_query(F.data == "roles_admin:close")
async def cb_roles_admin_close(call: CallbackQuery) -> None:
    """بستن پنل مدیریت."""
    await call.answer("پنل بسته شد.")
    try:
        await call.message.delete()
    except Exception:
        await safe_edit(call, "🔒 پنل مدیریت رول‌ها بسته شد.", reply_markup=None)


# ============================================================
#  ۱. آرشیو رول‌های امنیتی کشورها (تاییدشده)
# ============================================================

@router.callback_query(F.data == "roles_admin:sec_archive")
async def cb_roles_admin_sec_archive(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """فهرست کشورهایی که پروژه امنیتی تاییدشده دارند."""
    if not _is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    await call.answer()
    country_ids = await sec_repo.list_country_ids_with_approved_roles(session)
    if not country_ids:
        await safe_edit(
            call,
            "🛡 در حال حاضر هیچ کشوری پروژه امنیتی تاییدشده‌ای در آرشیو ندارد.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 بازگشت", callback_data="roles_admin:home", style=STYLE_MAIN)],
                ]
            ),
        )
        return

    all_countries = await countries_repo.list_countries(session)
    countries = [c for c in all_countries if c.id in country_ids]

    text = (
        header("آرشیو پروژه‌های امنیتی کشورها", "🛡")
        + f"\n\nتعداد کشورهای دارای آرشیو فعال: <b>{fa_number(len(countries))}</b>\n"
        "کشور موردنظر را جهت مشاهده رول‌های تاییدشده انتخاب کنید:"
    )
    await safe_edit(call, text, reply_markup=admin_countries_archive_kb(countries))


@router.callback_query(F.data.startswith("roles_admin:c_sec:"))
async def cb_roles_admin_country_sec(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """لیست پروژه‌های امنیتی تاییدشده یک کشور مشخص."""
    if not _is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    await call.answer()
    country_id = int(call.data.split(":")[2])
    country = await countries_repo.get_country(session, country_id)
    if not country:
        return

    roles = await sec_repo.list_approved_by_country(session, country_id)
    text = (
        header("آرشیو پروژه‌های امنیتی", "🛡")
        + f"\n\nکشور: {country.flag} <b>{country.name_fa}</b>\n"
        f"تعداد پروژه‌های تاییدشده: <b>{fa_number(len(roles))}</b>\n\n"
        "پروژه موردنظر را جهت مطالعه صفحات انتخاب کنید:"
    )
    await safe_edit(call, text, reply_markup=admin_roles_country_security_kb(roles, country_id))


@router.callback_query(F.data.startswith("roles_admin:sec_v:"))
async def cb_roles_admin_sec_view(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """مشاهده و ورق زدن رول امنیتی در پنل /roles."""
    if not _is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    await call.answer()
    parts = call.data.split(":")
    role_id, page_num, mode = int(parts[2]), int(parts[3]), parts[4]

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
        reply_markup=admin_roles_view_security_kb(role, page_num, mode),
    )


# ============================================================
#  ۲. رول‌های امنیتی در انتظار تایید
# ============================================================

@router.callback_query(F.data == "roles_admin:sec_pending")
async def cb_roles_admin_sec_pending(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """فهرست رول‌های امنیتی در صف انتظار تایید."""
    if not _is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    await call.answer()
    pending = await sec_repo.list_all_pending(session)
    if not pending:
        await safe_edit(
            call,
            "⏳ در حال حاضر هیچ رول امنیتی در صف انتظار تایید وجود ندارد.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 بازگشت", callback_data="roles_admin:home", style=STYLE_MAIN)],
                ]
            ),
        )
        return

    all_countries = await countries_repo.list_countries(session)
    cmap = {c.id: c for c in all_countries}

    text = (
        header("رول‌های امنیتی در انتظار تایید", "⏳")
        + f"\n\nتعداد موارد در صف داوری: <b>{fa_number(len(pending))}</b>\n"
        "جهت مطالعه و تایید یا رد مستقیم، رول مورد نظر را انتخاب کنید:"
    )
    await safe_edit(
        call,
        text,
        reply_markup=admin_pending_security_list_kb(pending, cmap),
    )


@router.callback_query(F.data.startswith("roles_admin:sec_app:"))
async def cb_roles_admin_sec_approve(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """تایید مستقیم رول امنیتی از داخل پنل /roles و همگام‌سازی گروه."""
    if not _is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    await call.answer("تایید شد ✅")
    role_id = int(call.data.split(":")[2])
    role = await sec_repo.get_security_role(session, role_id)
    if not role or role.status != SecurityRoleStatus.PENDING_REVIEW.value:
        await call.answer("این پروژه قبلاً داوری شده است.", show_alert=True)
        return

    country = await countries_repo.get_country(session, role.country_id)
    admin_name = call.from_user.full_name

    await approve_security_role(session, role, call.from_user.id)
    await session.commit()

    # همگام‌سازی و ویرایش پیام در گروه رول امنیتی
    if role.admin_message_id:
        try:
            await bot.edit_message_text(
                chat_id=settings.role_security_group_id,
                message_id=role.admin_message_id,
                text=(
                    f"✅ <b>این رول امنیتی از طریق پنل مدیریت (/roles) توسط {admin_name} تایید شد.</b>\n"
                    f"عنوان: <b>{role.title}</b> | کشور: {country.flag} {country.name_fa}\n"
                    f"رسماً به آرشیو امنیتی کشور اضافه گردید."
                ),
                reply_markup=None,
            )
        except Exception:
            pass

    # نوتیفیکیشن به پیوی لیدر کشور
    if country and country.owner_user_id:
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
        f"✅ <b>تایید رول امنیتی از پنل /roles</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"عنوان: {role.title}\n"
        f"توسط ادمین: {admin_name}",
    )

    # بازگشت به صف رول‌های امنیتی
    await cb_roles_admin_sec_pending(call, session)


@router.callback_query(F.data.startswith("roles_admin:sec_rej:"))
async def cb_roles_admin_sec_reject(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """شروع فرایند رد رول امنیتی از پنل /roles."""
    if not _is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    await call.answer()
    role_id = int(call.data.split(":")[2])
    role = await sec_repo.get_security_role(session, role_id)
    if not role or role.status != SecurityRoleStatus.PENDING_REVIEW.value:
        await call.answer("این پروژه قبلاً داوری شده است.", show_alert=True)
        return

    await state.set_state(SecurityRoleRejectForm.entering_reason)
    await state.update_data(
        role_id=role_id,
        admin_chat_id=settings.role_security_group_id,
        admin_message_id=role.admin_message_id,
    )
    await call.message.reply(
        f"❌ <b>رد پروژه امنیتی «{role.title}»</b>\n\n"
        f"لطفاً <b>علت رد</b> را ارسال کنید (مبلغ ۲۰M$ خودکار به بودجه کشور عودت داده می‌شود):"
    )


# ============================================================
#  ۳. رول‌های اقتصادی در انتظار تایید
# ============================================================

@router.callback_query(F.data == "roles_admin:econ_pending")
async def cb_roles_admin_econ_pending(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """فهرست رول‌های اقتصادی در انتظار داوری."""
    if not _is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    await call.answer()
    pending = await proj_repo.list_all_pending(session)
    if not pending:
        await safe_edit(
            call,
            "💰 در حال حاضر هیچ رول اقتصادی در صف داوری مدیریت وجود ندارد.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 بازگشت", callback_data="roles_admin:home", style=STYLE_MAIN)],
                ]
            ),
        )
        return

    all_countries = await countries_repo.list_countries(session)
    cmap = {c.id: c for c in all_countries}

    text = (
        header("رول‌های اقتصادی در انتظار داوری", "💰")
        + f"\n\nتعداد پروژه‌ها در صف: <b>{fa_number(len(pending))}</b>\n"
        "جهت مشاهده، ورق زدن و تخصیص بودجه یا رد پروژه، انتخاب کنید:"
    )
    await safe_edit(
        call,
        text,
        reply_markup=admin_pending_econ_list_kb(pending, cmap),
    )


@router.callback_query(F.data.startswith("roles_admin:econ_v:"))
async def cb_roles_admin_econ_view(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """مشاهده صفحات رول اقتصادی در پنل /roles با قابلیت انتقال به داوری."""
    if not _is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    await call.answer()
    parts = call.data.split(":")
    proj_id, page_num = int(parts[2]), int(parts[3])

    project = await proj_repo.get_project(session, proj_id)
    if not project:
        await safe_edit(call, "❌ پروژه یافت نشد.")
        return

    country = await countries_repo.get_country(session, project.country_id)
    if not country:
        return

    msg_text = render_project_message(country, project, page_num, db_user)
    total = project.total_pages

    builder = InlineKeyboardBuilder()
    nav: list[InlineKeyboardButton] = []
    if page_num > 1:
        nav.append(
            InlineKeyboardButton(
                text="⬅️ صفحه قبل",
                callback_data=f"roles_admin:econ_v:{project.id}:{page_num - 1}",
                style=STYLE_MAIN,
            )
        )
    nav.append(InlineKeyboardButton(text=f"📄 {fa_number(page_num)}/{fa_number(total)}", callback_data="roles_admin:noop"))
    if page_num < total:
        nav.append(
            InlineKeyboardButton(
                text="➡️ صفحه بعد",
                callback_data=f"roles_admin:econ_v:{project.id}:{page_num + 1}",
                style=STYLE_MAIN,
            )
        )
    builder.row(*nav)

    # داوری با دکمه‌های موجود گروه اقتصادی
    builder.row(
        InlineKeyboardButton(
            text="✅ تخصیص بودجه و تایید",
            callback_data=f"ep_admin_approve:{project.id}",
            style=STYLE_OK,
        ),
        InlineKeyboardButton(
            text="❌ رد پروژه",
            callback_data=f"ep_admin_reject:{project.id}",
            style=STYLE_NO,
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🔙 بازگشت به صف اقتصادی",
            callback_data="roles_admin:econ_pending",
            style=STYLE_MAIN,
        )
    )

    await safe_edit(call, msg_text, reply_markup=builder.as_markup())


# ============================================================
#  ۴. رول‌های نظامی باز (در حال اجرا)
# ============================================================

@router.callback_query(F.data == "roles_admin:mil_open")
async def cb_roles_admin_mil_open(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """فهرست رول‌های نظامی جاری در پنل /roles."""
    if not _is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    await call.answer()
    active = await mil_ops_repo.list_all_pending(session)
    if not active:
        await safe_edit(
            call,
            "⚔️ در حال حاضر هیچ عملیات نظامی باز یا در حال اجرایی وجود ندارد.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 بازگشت", callback_data="roles_admin:home", style=STYLE_MAIN)],
                ]
            ),
        )
        return

    all_countries = await countries_repo.list_countries(session)
    cmap = {c.id: c for c in all_countries}

    text = (
        header("عملیات‌های نظامی باز (در حال اجرا)", "⚔️")
        + f"\n\nتعداد عملیات‌های فعال: <b>{fa_number(len(active))}</b>\n"
        "جهت ثبت تلفات، بررسی آرشیو امنیتی هدف و اتمام عملیات، انتخاب کنید:"
    )
    await safe_edit(
        call,
        text,
        reply_markup=admin_active_military_list_kb(active, cmap),
    )


@router.callback_query(F.data.startswith("roles_admin:mil_v:"))
async def cb_roles_admin_mil_view(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """مشاهده صفحات عملیات نظامی در پنل /roles."""
    if not _is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    await call.answer()
    parts = call.data.split(":")
    role_id, page_num = int(parts[2]), int(parts[3])

    role = await mil_ops_repo.get_military_role(session, role_id)
    if not role:
        await safe_edit(call, "❌ عملیات یافت نشد.")
        return

    attacker = await countries_repo.get_country(session, role.attacker_country_id)
    target = await countries_repo.get_country(session, role.target_country_id)
    if not attacker or not target:
        return

    msg_text = render_military_role_message(role, attacker, target, page_num)
    await safe_edit(
        call,
        msg_text,
        reply_markup=admin_roles_view_military_kb(role, page_num),
    )


@router.callback_query(F.data.startswith("roles_admin:mil_tgt_sec:"))
async def cb_roles_admin_mil_tgt_sec(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """مشاهده پروژه‌های امنیتی کشور هدف از داخل پنل /roles."""
    if not _is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    await call.answer()
    role_id = int(call.data.split(":")[2])
    role = await mil_ops_repo.get_military_role(session, role_id)
    if not role:
        return

    target = await countries_repo.get_country(session, role.target_country_id)
    sec_roles = await sec_repo.list_approved_by_country(session, role.target_country_id)

    if not sec_roles:
        await call.answer(
            f"کشور هدف ({target.name_fa}) هیچ پروژه امنیتی تاییدشده‌ای ندارد.",
            show_alert=True,
        )
        return

    builder = InlineKeyboardBuilder()
    for s in sec_roles:
        builder.button(
            text=f"🛡 {s.title[:25]} ({fa_number(s.total_pages)} ص)",
            callback_data=f"roles_admin:sec_v:{s.id}:1:mil_back:{role_id}",
            style=STYLE_MAIN,
        )
    builder.button(
        text="🔙 بازگشت به عملیات نظامی",
        callback_data=f"roles_admin:mil_v:{role_id}:1",
        style=STYLE_MAIN,
    )
    builder.adjust(1)

    text = (
        header("آرشیو امنیتی کشور هدف", "🛡")
        + f"\n\nکشور هدف: {target.flag} <b>{target.name_fa}</b>\n"
        f"پروژه‌های تاییدشده: <b>{fa_number(len(sec_roles))}</b>\n\n"
        "جهت بررسی نحوه دفاع و پدافند کشور هدف، روی هر کدام کلیک کنید:"
    )
    await safe_edit(call, text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "roles_admin:noop")
async def cb_roles_admin_noop(call: CallbackQuery) -> None:
    """دکمه خنثی بدون عملکرد."""
    await call.answer()
