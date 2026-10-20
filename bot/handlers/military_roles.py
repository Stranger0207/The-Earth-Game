"""هندلرهای مربوط به سیستم رول‌ها و عملیات‌های نظامی (آپدیت شماره ۲)."""

from __future__ import annotations

import logging
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import DEPLOY_BRANCHES, MAX_ROLE_PAGE_LEN
from ..database.models import Country, MilitaryRole, User
from ..database.repositories import countries as countries_repo
from ..database.repositories import military as mil_repo
from ..database.repositories import military_roles as mil_ops_repo
from ..database.repositories import security_roles as sec_repo
from ..enums import AdminGroupType, MilitaryRoleStatus, MilitaryRoleType
from ..keyboards.military_roles import (
    admin_group_military_role_kb,
    admin_military_casualty_side_kb,
    admin_military_end_confirm_kb,
    military_delete_confirm_kb,
    military_draft_view_kb,
    military_list_kb,
    military_roles_home_kb,
    military_submit_confirm_kb,
    military_target_picker_kb,
    military_type_picker_kb,
)
from ..keyboards.security_roles import security_approved_view_kb
from ..loader import bot
from ..services.military_role_service import (
    complete_military_role,
    format_casualties_report,
    record_casualty,
    render_military_role_message,
    submit_military_role,
)
from ..services.news_service import send_log, send_to_admin_group
from ..services.security_role_service import validate_role_page
from ..states.forms import MilitaryCasualtyForm, MilitaryRoleDraftForm
from ..utils.numbers import fa_number
from ..utils.screens import safe_edit, show_menu
from ..utils.ui import DIVIDER, STYLE_MAIN, STYLE_NO, STYLE_OK, header
from .deps import NO_COUNTRY_TEXT, assert_feature, get_player_country

logger = logging.getLogger(__name__)
router = Router(name="military_roles")
settings = get_settings()


# ============================================================
#  ورودی و منوی اصلی رول‌های نظامی
# ============================================================

@router.callback_query(F.data == "mil:ops_roles")
async def cb_military_roles_home(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """منوی اصلی عملیات‌ها و رول‌های نظامی."""
    await call.answer()
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "military_roles"):
        return

    text = (
        header("عملیات و رول‌های نظامی", "⚔️")
        + f"\n\nکشور: {country.flag} <b>{country.name_fa}</b>\n"
        f"{DIVIDER}\n"
        "در این بخش می‌توانید رول‌های عملیاتی تهاجمی، خرابکاری و ترور را نگارش و ارسال کنید.\n\n"
        "📌 <b>انواع رول‌های نظامی و سقف صفحات:</b>\n"
        "• 💣 <b>رول خرابکاری:</b> حداکثر ۲ صفحه (هر صفحه تا ۴۰۰۰ کاراکتر)\n"
        "• 🎯 <b>رول ترور:</b> حداکثر ۳ صفحه (هر صفحه تا ۴۰۰۰ کاراکتر)\n"
        "• 🚀 <b>رول حمله:</b> حداکثر ۵ صفحه (هر صفحه تا ۴۰۰۰ کاراکتر)\n\n"
        "🔒 <b>قوانین عملیاتی:</b>\n"
        "۱. تعیین کشور هدف پیش از نگارش اجباری است.\n"
        "۲. پس از ارسال نهایی، رول به گروه عملیات ستاد ارسال شده و متن آن قفل می‌شود.\n"
        "۳. رول‌های نظامی نیاز به تایید صوری ندارند؛ ادمین پس از بررسی رول و وضعیت پدافندی کشور هدف، "
        "تلفات طرفین را ثبت و پایان عملیات را اعلام می‌نماید.\n\n"
        "گزینه مورد نظر را انتخاب کنید:"
    )
    await show_menu(call, text, reply_markup=military_roles_home_kb(), image_key="military_roles")


# ============================================================
#  فلوی ایجاد و نگارش رول نظامی جدید (FSM)
# ============================================================

@router.callback_query(F.data == "mil_ops:new")
async def cb_new_military_op(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """انتخاب نوع رول نظامی جدید."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "military_roles"):
        return

    text = (
        header("ثبت عملیات نظامی جدید", "⚔️")
        + "\n\nابتدا <b>نوع عملیات</b> مورد نظر خود را انتخاب کنید:"
    )
    await safe_edit(call, text, reply_markup=military_type_picker_kb())


@router.callback_query(F.data.startswith("mil_type:"))
async def cb_select_type(
    call: CallbackQuery, state: FSMContext
) -> None:
    """انتخاب نوع رول و درخواست عنوان عملیات."""
    await call.answer()
    op_type = call.data.split(":")[1]
    await state.set_state(MilitaryRoleDraftForm.entering_title)
    await state.update_data(op_type=op_type)

    await safe_edit(
        call,
        "📌 لطفاً <b>عنوان عملیات</b> را وارد کنید (حداکثر ۵۰ کاراکتر):\n"
        "<i>مثال: عملیات صاعقه صحرا / نفوذ به پالایشگاه جنوبی</i>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ انصراف", callback_data="mil:ops_roles", style=STYLE_NO)],
            ]
        ),
    )


@router.message(StateFilter(MilitaryRoleDraftForm.entering_title))
async def msg_mil_title(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """دریافت عنوان عملیات و نمایش لیست انتخاب کشور هدف."""
    title = (message.text or "").strip()
    if not title or len(title) > 50:
        await message.answer("⚠️ عنوان عملیات باید حداکثر ۵۰ کاراکتر باشد:")
        return

    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        await state.clear()
        return

    await state.update_data(title=title)
    await state.set_state(MilitaryRoleDraftForm.selecting_target)

    countries = await countries_repo.list_countries(session)
    await message.answer(
        f"✅ عنوان عملیات: <b>{title}</b>\n\n"
        f"🎯 اکنون <b>کشور هدف (مورد حمله/عملیات)</b> را از لیست زیر انتخاب کنید:",
        reply_markup=military_target_picker_kb(countries, country.id, page=0),
    )


@router.callback_query(F.data.startswith("mil_tgt_p:"))
async def cb_mil_target_page(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """ناوبری صفحه‌بندی انتخاب کشور هدف."""
    await call.answer()
    page = int(call.data.split(":")[1])
    country = await get_player_country(session, db_user)
    if country is None:
        return

    countries = await countries_repo.list_countries(session)
    await safe_edit(
        call,
        "🎯 <b>کشور هدف (مورد حمله/عملیات)</b> را از لیست زیر انتخاب کنید:",
        reply_markup=military_target_picker_kb(countries, country.id, page=page),
    )


@router.callback_query(F.data.startswith("mil_tgt:"))
async def cb_mil_target_pick(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """ثبت کشور هدف و شروع نگارش صفحه اول رول."""
    await call.answer()
    target_id = int(call.data.split(":")[1])
    country = await get_player_country(session, db_user)
    if country is None:
        return
    if target_id == country.id:
        await call.answer("نمی‌توانید کشور خود را هدف عملیات قرار دهید!", show_alert=True)
        return

    target = await countries_repo.get_country(session, target_id)
    if not target:
        return

    data = await state.get_data()
    op_type = data.get("op_type", "attack")
    title = data.get("title", "عملیات بدون عنوان")

    await state.update_data(target_id=target_id, page_num=1)
    await state.set_state(MilitaryRoleDraftForm.entering_page)

    await safe_edit(
        call,
        f"🎯 کشور هدف: {target.flag} <b>{target.name_fa}</b>\n"
        f"📌 عنوان: <b>{title}</b>\n\n"
        f"اکنون <b>متن صفحه اول</b> رول عملیاتی خود را ارسال کنید.\n"
        f"⚠️ <b>توجه:</b> حداکثر سقف مجاز هر صفحه <b>{fa_number(MAX_ROLE_PAGE_LEN)}</b> کاراکتر است.",
    )


@router.message(StateFilter(MilitaryRoleDraftForm.entering_page))
async def msg_mil_page(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """دریافت متن صفحه رول نظامی."""
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
        role = await mil_ops_repo.get_military_role(session, role_id)
        if not role or role.status != MilitaryRoleStatus.DRAFT.value:
            await message.answer("❌ این پیش‌نویس یافت نشد یا قفل شده است.")
            await state.clear()
            return
        role.set_page_text(page_num, raw)
        await session.commit()
    else:
        op_type = data.get("op_type", MilitaryRoleType.ATTACK.value)
        title = data.get("title", "عملیات بدون عنوان")
        target_id = data.get("target_id")
        if not target_id:
            await message.answer("❌ کشور هدف مشخص نشده است.")
            await state.clear()
            return

        role = MilitaryRole(
            attacker_country_id=country.id,
            target_country_id=target_id,
            op_type=op_type,
            title=title,
            page_1=raw,
            status=MilitaryRoleStatus.DRAFT.value,
        )
        await mil_ops_repo.create_military_role(session, role)
        await session.commit()

    target = await countries_repo.get_country(session, role.target_country_id)
    await state.clear()
    msg_text = render_military_role_message(role, country, target, page_num)
    await message.answer(
        f"✅ <b>صفحه {fa_number(page_num)} با موفقیت ثبت شد.</b>\n\n{msg_text}",
        reply_markup=military_draft_view_kb(role, page_num),
    )


# ============================================================
#  فهرست‌ها: پیش‌نویس‌ها و عملیات‌های جاری
# ============================================================

@router.callback_query(F.data == "mil_ops:drafts")
async def cb_drafts_list(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """فهرست پیش‌نویس‌های نظامی کشور."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    drafts = await mil_ops_repo.list_drafts_by_country(session, country.id)
    if not drafts:
        await safe_edit(
            call,
            "📝 شما در حال حاضر هیچ پیش‌نویس عملیات نظامی ندارید.\n"
            "برای ایجاد عملیات جدید از دکمه زیر استفاده کنید.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="➕ ثبت عملیات جدید", callback_data="mil_ops:new", style=STYLE_OK)],
                    [InlineKeyboardButton(text="🔙 بازگشت", callback_data="mil:ops_roles", style=STYLE_MAIN)],
                ]
            ),
        )
        return

    all_countries = await countries_repo.list_countries(session)
    cmap = {c.id: c for c in all_countries}
    text = (
        header("پیش‌نویس‌های عملیات‌های نظامی", "📝")
        + f"\n\nتعداد پیش‌نویس‌ها: <b>{fa_number(len(drafts))}</b>\n"
        "جهت مشاهده، افزودن صفحه یا ارسال به ستاد کل، عملیات را انتخاب کنید:"
    )
    await safe_edit(
        call,
        text,
        reply_markup=military_list_kb(
            drafts, back_data="mil:ops_roles", view_prefix="mil_draft_p", countries_map=cmap
        ),
    )


@router.callback_query(F.data == "mil_ops:active")
async def cb_active_ops_list(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """فهرست عملیات‌های در حال اجرای ارسالی به ستاد فرماندهی."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    active = await mil_ops_repo.list_active_by_attacker(session, country.id)
    if not active:
        await safe_edit(
            call,
            "⏳ در حال حاضر هیچ عملیات نظامی باز یا در حال اجرایی ندارید.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 بازگشت", callback_data="mil:ops_roles", style=STYLE_MAIN)],
                ]
            ),
        )
        return

    all_countries = await countries_repo.list_countries(session)
    cmap = {c.id: c for c in all_countries}
    text = (
        header("عملیات‌های نظامی جاری", "⏳")
        + f"\n\nتعداد عملیات‌های در حال اجرا: <b>{fa_number(len(active))}</b>\n"
        "این عملیات‌ها در ستاد کل در حال داوری و ثبت تلفات هستند:"
    )
    await safe_edit(
        call,
        text,
        reply_markup=military_list_kb(
            active, back_data="mil:ops_roles", view_prefix="mil_view_act", countries_map=cmap
        ),
    )


# ============================================================
#  ورق زدن، ویرایش، حذف و ارسال نهایی پیش‌نویس نظامی
# ============================================================

@router.callback_query(F.data.startswith("mil_draft_p:"))
async def cb_draft_page(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """ورق زدن صفحات پیش‌نویس نظامی."""
    await call.answer()
    parts = call.data.split(":")
    role_id, page_num = int(parts[1]), int(parts[2])

    role = await mil_ops_repo.get_military_role(session, role_id)
    if not role or role.status != MilitaryRoleStatus.DRAFT.value:
        await safe_edit(call, "❌ این پیش‌نویس یافت نشد یا قفل شده است.")
        return

    attacker = await countries_repo.get_country(session, role.attacker_country_id)
    target = await countries_repo.get_country(session, role.target_country_id)
    if not attacker or not target:
        return

    msg_text = render_military_role_message(role, attacker, target, page_num)
    await safe_edit(call, msg_text, reply_markup=military_draft_view_kb(role, page_num))


@router.callback_query(F.data.startswith("mil_draft_addp:"))
async def cb_draft_add_page(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """افزودن صفحه جدید به پیش‌نویس رول نظامی."""
    await call.answer()
    role_id = int(call.data.split(":")[1])
    role = await mil_ops_repo.get_military_role(session, role_id)
    if not role or role.status != MilitaryRoleStatus.DRAFT.value:
        await safe_edit(call, "❌ پیش‌نویس یافت نشد.")
        return

    total = role.total_pages
    max_p = role.max_allowed_pages
    if total >= max_p:
        await call.answer(f"سقف {fa_number(max_p)} صفحه برای این نوع عملیات تکمیل شده است.", show_alert=True)
        return

    next_page = total + 1
    await state.set_state(MilitaryRoleDraftForm.entering_page)
    await state.update_data(role_id=role_id, page_num=next_page)

    await safe_edit(
        call,
        f"📄 <b>نگارش صفحه {fa_number(next_page)} از {fa_number(max_p)}</b>\n\n"
        f"عملیات: <b>{role.title}</b>\n"
        f"لطفاً متن صفحه {fa_number(next_page)} را ارسال کنید (حداکثر {fa_number(MAX_ROLE_PAGE_LEN)} کاراکتر):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 انصراف", callback_data=f"mil_draft_p:{role_id}:{total}", style=STYLE_NO)],
            ]
        ),
    )


@router.callback_query(F.data.startswith("mil_draft_editp:"))
async def cb_draft_edit_page(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """ویرایش صفحه مشخص از پیش‌نویس نظامی."""
    await call.answer()
    parts = call.data.split(":")
    role_id, page_num = int(parts[1]), int(parts[2])

    role = await mil_ops_repo.get_military_role(session, role_id)
    if not role or role.status != MilitaryRoleStatus.DRAFT.value:
        await safe_edit(call, "❌ پیش‌نویس یافت نشد.")
        return

    await state.set_state(MilitaryRoleDraftForm.entering_page)
    await state.update_data(role_id=role_id, page_num=page_num)

    await safe_edit(
        call,
        f"✏️ <b>ویرایش صفحه {fa_number(page_num)}</b> از عملیات <b>{role.title}</b>\n\n"
        f"لطفاً متن جدید صفحه را ارسال کنید (حداکثر {fa_number(MAX_ROLE_PAGE_LEN)} کاراکتر):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 انصراف", callback_data=f"mil_draft_p:{role_id}:{page_num}", style=STYLE_NO)],
            ]
        ),
    )


@router.callback_query(F.data.startswith("mil_draft_del:"))
async def cb_draft_del_ask(call: CallbackQuery, session: AsyncSession) -> None:
    """درخواست تأیید حذف پیش‌نویس نظامی."""
    await call.answer()
    role_id = int(call.data.split(":")[1])
    role = await mil_ops_repo.get_military_role(session, role_id)
    if not role:
        await safe_edit(call, "❌ پیش‌نویس یافت نشد.")
        return

    text = (
        f"🗑 <b>تأیید حذف پیش‌نویس عملیات</b>\n\n"
        f"آیا مطمئن هستید که می‌خواهید پیش‌نویس عملیات <b>«{role.title}»</b> را حذف کنید؟"
    )
    await safe_edit(call, text, reply_markup=military_delete_confirm_kb(role_id))


@router.callback_query(F.data.startswith("mil_del_do:"))
async def cb_draft_del_do(call: CallbackQuery, session: AsyncSession) -> None:
    """حذف قطعی پیش‌نویس نظامی."""
    await call.answer("پیش‌نویس حذف شد.")
    role_id = int(call.data.split(":")[1])
    role = await mil_ops_repo.get_military_role(session, role_id)
    if role and role.status == MilitaryRoleStatus.DRAFT.value:
        await mil_ops_repo.delete_military_role(session, role)
        await session.commit()

    await safe_edit(
        call,
        "🗑 پیش‌نویس عملیات نظامی با موفقیت حذف شد.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📝 پیش‌نویس‌های من", callback_data="mil_ops:drafts", style=STYLE_MAIN)],
                [InlineKeyboardButton(text="🔙 منوی عملیات‌ها", callback_data="mil:ops_roles", style=STYLE_MAIN)],
            ]
        ),
    )


@router.callback_query(F.data.startswith("mil_draft_submit:"))
async def cb_draft_submit_ask(call: CallbackQuery, session: AsyncSession) -> None:
    """تأییدیه ارسال نهایی عملیات به ستاد فرماندهی."""
    await call.answer()
    role_id = int(call.data.split(":")[1])
    role = await mil_ops_repo.get_military_role(session, role_id)
    if not role or role.status != MilitaryRoleStatus.DRAFT.value:
        await safe_edit(call, "❌ پیش‌نویس یافت نشد یا قبلاً ارسال شده است.")
        return

    attacker = await countries_repo.get_country(session, role.attacker_country_id)
    target = await countries_repo.get_country(session, role.target_country_id)

    text = (
        header("تأییدیه آغاز و ارسال نهایی عملیات", "⚠️")
        + f"\n\nعملیات: <b>{role.title}</b> ({fa_number(role.total_pages)} صفحه)\n"
        f"مهاجم: {attacker.flag} <b>{attacker.name_fa}</b>\n"
        f"هدف: {target.flag} <b>{target.name_fa}</b>\n"
        f"{DIVIDER}\n"
        f"🔒 <b>توجه مهم:</b>\n"
        f"پس از ارسال، عملیات رسماً آغاز شده و به گروه عملیات ستاد فرماندهی ارسال می‌گردد.\n"
        f"متن رول قفل شده و داوری تلفات و اجرای عملیات توسط ادمین‌های نظامی انجام خواهد شد.\n\n"
        f"آیا برای آغاز این عملیات اطمینان دارید؟"
    )
    await safe_edit(call, text, reply_markup=military_submit_confirm_kb(role_id))


@router.callback_query(F.data.startswith("mil_submit_do:"))
async def cb_draft_submit_do(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """ارسال نهایی رول نظامی به گروه عملیات ستاد (-1004424329237)."""
    await call.answer()
    role_id = int(call.data.split(":")[1])
    role = await mil_ops_repo.get_military_role(session, role_id)
    if not role or role.status != MilitaryRoleStatus.DRAFT.value:
        await safe_edit(call, "❌ پیش‌نویس یافت نشد یا قبلاً ارسال شده است.")
        return

    attacker = await countries_repo.get_country(session, role.attacker_country_id)
    target = await countries_repo.get_country(session, role.target_country_id)
    if not attacker or not target:
        return

    ok, err = await submit_military_role(session, role)
    if not ok:
        await call.answer(err, show_alert=True)
        return

    # ارسال به گروه رول نظامی (-1004424329237)
    group_text = render_military_role_message(role, attacker, target, 1)
    group_kb = admin_group_military_role_kb(role, 1)

    sent_msg = await send_to_admin_group(
        bot,
        AdminGroupType.ROLE_ATTACK,
        group_text,
        reply_markup=group_kb,
    )
    if sent_msg:
        role.admin_message_id = sent_msg.message_id

    await session.commit()

    # لاگ
    await send_log(
        bot,
        f"⚔️ <b>آغاز عملیات نظامی جدید</b>\n"
        f"مهاجم: {attacker.flag} {attacker.name_fa}\n"
        f"هدف: {target.flag} {target.name_fa}\n"
        f"عنوان: {role.title} ({fa_number(role.total_pages)} صفحه)",
    )

    success_text = (
        header("ارسال موفق عملیات نظامی", "✅")
        + f"\n\nعملیات <b>«{role.title}»</b> با موفقیت به ستاد فرماندهی کل ارسال شد.\n"
        f"ادمین‌های نظامی پس از بررسی دقیق رول و استحکامات دفاعی {target.name_fa}، "
        f"تلفات طرفین را ثبت و گزارش نهایی را ابلاغ خواهند کرد."
    )
    await safe_edit(
        call,
        success_text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⏳ مشاهده عملیات‌های جاری", callback_data="mil_ops:active", style=STYLE_MAIN)],
                [InlineKeyboardButton(text="🔙 منوی عملیات‌ها", callback_data="mil:ops_roles", style=STYLE_MAIN)],
            ]
        ),
    )


# ============================================================
#  مشاهده عملیات جاری توسط بازیکن (فقط خواندنی)
# ============================================================

@router.callback_query(F.data.startswith("mil_view_act:"))
async def cb_view_active_op(call: CallbackQuery, session: AsyncSession) -> None:
    """مشاهده صفحات رول در حال اجرا توسط بازیکن."""
    await call.answer()
    parts = call.data.split(":")
    role_id, page_num = int(parts[1]), int(parts[2])

    role = await mil_ops_repo.get_military_role(session, role_id)
    if not role:
        await safe_edit(call, "❌ عملیات یافت نشد.")
        return

    attacker = await countries_repo.get_country(session, role.attacker_country_id)
    target = await countries_repo.get_country(session, role.target_country_id)
    if not attacker or not target:
        return

    msg_text = render_military_role_message(role, attacker, target, page_num)
    total = role.total_pages
    builder = InlineKeyboardBuilder()

    nav: list[InlineKeyboardButton] = []
    if page_num > 1:
        nav.append(InlineKeyboardButton(text="⬅️ صفحه قبل", callback_data=f"mil_view_act:{role.id}:{page_num - 1}", style=STYLE_MAIN))
    nav.append(InlineKeyboardButton(text=f"📄 {fa_number(page_num)}/{fa_number(total)}", callback_data="mil_noop"))
    if page_num < total:
        nav.append(InlineKeyboardButton(text="➡️ صفحه بعد", callback_data=f"mil_view_act:{role.id}:{page_num + 1}", style=STYLE_MAIN))
    builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 بازگشت به عملیات‌های جاری", callback_data="mil_ops:active", style=STYLE_MAIN))

    await safe_edit(call, msg_text, reply_markup=builder.as_markup())


# ============================================================
#  عملیات ادمین در گروه رول نظامی و پنل /roles
# ============================================================

@router.callback_query(F.data.startswith("mil_grp_p:"))
async def cb_admin_group_mil_page(call: CallbackQuery, session: AsyncSession) -> None:
    """ورق زدن صفحات رول نظامی در گروه ستاد."""
    await call.answer()
    parts = call.data.split(":")
    role_id, page_num = int(parts[1]), int(parts[2])

    role = await mil_ops_repo.get_military_role(session, role_id)
    if not role:
        return
    attacker = await countries_repo.get_country(session, role.attacker_country_id)
    target = await countries_repo.get_country(session, role.target_country_id)
    if not attacker or not target:
        return

    msg_text = render_military_role_message(role, attacker, target, page_num)
    try:
        await call.message.edit_text(
            msg_text,
            reply_markup=admin_group_military_role_kb(role, page_num),
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("mil_grp_cas:"))
async def cb_admin_casualty_start(call: CallbackQuery, session: AsyncSession) -> None:
    """شروع فرایند ثبت تلفات (انتخاب کشور مهاجم یا هدف)."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("تنها مدیران بازی مجاز به ثبت تلفات هستند.", show_alert=True)
        return

    await call.answer()
    parts = call.data.split(":")
    role_id = int(parts[1])
    is_panel = len(parts) > 2 and parts[2] == "panel"
    back_cb = f"roles_admin:mil_v:{role_id}:1" if is_panel else f"mil_grp_p:{role_id}:1"

    role = await mil_ops_repo.get_military_role(session, role_id)
    if not role:
        return
    attacker = await countries_repo.get_country(session, role.attacker_country_id)
    target = await countries_repo.get_country(session, role.target_country_id)

    text = (
        header("سیستم ثبت تلفات و خسارات عملیاتی", "💥")
        + f"\n\nعملیات: <b>{role.title}</b>\n"
        f"تلفات یا خسارات را برای کدام طرف درگیر ثبت می‌کنید؟"
    )
    await safe_edit(
        call,
        text,
        reply_markup=admin_military_casualty_side_kb(role_id, attacker.name_fa, target.name_fa, back_cb),
    )


@router.callback_query(F.data.startswith("mil_cas_side:"))
async def cb_admin_casualty_side(call: CallbackQuery, session: AsyncSession) -> None:
    """انتخاب شاخه نظامی کشور انتخابی (زمینی، هوایی، دریایی)."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    await call.answer()
    parts = call.data.split(":")
    role_id, side = int(parts[1]), parts[2]

    role = await mil_ops_repo.get_military_role(session, role_id)
    if not role:
        return
    cid = role.attacker_country_id if side == "attacker" else role.target_country_id
    country = await countries_repo.get_country(session, cid)

    builder = InlineKeyboardBuilder()
    icons = {"ground": "🪖", "navy": "🚢", "air": "✈️"}
    for key, (fa, _stem, _branches) in DEPLOY_BRANCHES.items():
        builder.button(
            text=f"{icons.get(key, '')} {fa}",
            callback_data=f"mil_cas_br:{role_id}:{side}:{key}",
            style=STYLE_NO,
        )
    builder.button(
        text="🔙 بازگشت",
        callback_data=f"mil_grp_cas:{role_id}",
        style=STYLE_MAIN,
    )
    builder.adjust(1)

    side_fa = "مهاجم" if side == "attacker" else "مدافع"
    text = (
        f"💥 ثبت تلفات برای <b>{country.flag} {country.name_fa}</b> ({side_fa})\n\n"
        f"نیروی نظامی مورد نظر را انتخاب کنید:"
    )
    await safe_edit(call, text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("mil_cas_br:"))
async def cb_admin_casualty_branch(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """انتخاب قلم تجهیزات از شاخه انتخاب‌شده همراه با صفحه‌بندی."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    await call.answer()
    parts = call.data.split(":")
    role_id, side, key = int(parts[1]), parts[2], parts[3]
    page = int(parts[4]) if len(parts) > 4 else 0

    role = await mil_ops_repo.get_military_role(session, role_id)
    if not role or key not in DEPLOY_BRANCHES:
        return

    cid = role.attacker_country_id if side == "attacker" else role.target_country_id
    fa_name, _stem, branches = DEPLOY_BRANCHES[key]
    assets = await mil_repo.list_assets(session, cid)
    matching = [a for a in assets if a.branch in branches and a.count > 0]

    if not matching:
        await safe_edit(
            call,
            f"⚠️ این کشور در شاخه «{fa_name}» تجهیزاتی با موجودی بیشتر از صفر ندارد.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 بازگشت به شاخه‌ها", callback_data=f"mil_cas_side:{role_id}:{side}", style=STYLE_MAIN)],
                ]
            ),
        )
        return

    # ذخیره فهرست کل تجهیزات در کانتکست جهت دسترسی اندیس‌ها
    await state.update_data(cas_assets=[a.name for a in matching])

    # صفحه‌بندی ۸ موردی
    page_size = 8
    total_items = len(matching)
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    if page >= total_pages:
        page = max(0, total_pages - 1)
    start_idx = page * page_size
    chunk = matching[start_idx : start_idx + page_size]

    builder = InlineKeyboardBuilder()
    for offset, a in enumerate(chunk):
        real_idx = start_idx + offset
        builder.button(
            text=f"{a.name} ({fa_number(a.count)})",
            callback_data=f"mil_cas_ast:{role_id}:{side}:{key}:{page}:{real_idx}",
            style=STYLE_NO,
        )
    builder.adjust(1)

    # دکمه‌های ناوبری صفحه‌بندی
    nav_btns: list[InlineKeyboardButton] = []
    if page > 0:
        nav_btns.append(
            InlineKeyboardButton(
                text="◀️ قبلی",
                callback_data=f"mil_cas_br:{role_id}:{side}:{key}:{page - 1}",
                style=STYLE_MAIN,
            )
        )
    if total_pages > 1:
        nav_btns.append(
            InlineKeyboardButton(
                text=f"📄 {fa_number(page + 1)}/{fa_number(total_pages)}",
                callback_data="mil_noop",
            )
        )
    if start_idx + page_size < total_items:
        nav_btns.append(
            InlineKeyboardButton(
                text="بعدی ▶️",
                callback_data=f"mil_cas_br:{role_id}:{side}:{key}:{page + 1}",
                style=STYLE_MAIN,
            )
        )
    if nav_btns:
        builder.row(*nav_btns)

    builder.row(
        InlineKeyboardButton(
            text="🔙 بازگشت به انتخاب شاخه",
            callback_data=f"mil_cas_side:{role_id}:{side}",
            style=STYLE_MAIN,
        )
    )

    side_fa = "مهاجم" if side == "attacker" else "مدافع"
    await safe_edit(
        call,
        f"💥 ثبت تلفات در شاخه <b>{fa_name}</b> ({side_fa}):\n"
        "کدام قلم تجهیزات دچار تلفات یا خسارت شده است؟",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("mil_cas_ast:"))
async def cb_admin_casualty_asset(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """دریافت نام قلم و انتقال به وضعیت دریافت عدد تلفات همراه با حفظ کانتکست بازگشت دقیق."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    await call.answer()
    parts = call.data.split(":")
    if len(parts) >= 6:
        role_id, side, key, page, idx = int(parts[1]), parts[2], parts[3], int(parts[4]), int(parts[5])
    else:
        role_id, side, idx = int(parts[1]), parts[2], int(parts[3])
        key = "ground"
        page = 0

    data = await state.get_data()
    assets = data.get("cas_assets", [])
    if idx >= len(assets):
        await call.answer("انتخاب نامعتبر.", show_alert=True)
        return

    asset_name = assets[idx]
    await state.set_state(MilitaryCasualtyForm.entering_count)
    await state.update_data(
        role_id=role_id,
        side=side,
        branch_key=key,
        page=page,
        asset_name=asset_name,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
    )

    await safe_edit(
        call,
        f"🔢 لطفاً <b>تعداد تلفات «{asset_name}»</b> را وارد کنید (مستقیماً از موجودی کسر می‌شود):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔙 انصراف و بازگشت به همین شاخه",
                    callback_data=f"mil_cas_br:{role_id}:{side}:{key}:{page}",
                    style=STYLE_MAIN,
                )],
            ]
        ),
    )


@router.message(StateFilter(MilitaryCasualtyForm.entering_count))
async def msg_admin_casualty_count(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """کسر تلفات از دیتابیس با reduce_count و ارائه دکمه‌های بازگشت مستقیم به همان شاخه و صفحه."""
    raw = (message.text or "").strip()
    try:
        count = int(raw)
        if count <= 0:
            raise ValueError
    except ValueError:
        await message.reply("⚠️ لطفاً یک عدد صحیح مثبت وارد کنید:")
        return

    data = await state.get_data()
    role_id = data.get("role_id")
    side = data.get("side")
    branch_key = data.get("branch_key", "ground")
    page = data.get("page", 0)
    asset_name = data.get("asset_name")

    role = await mil_ops_repo.get_military_role(session, role_id)
    if not role:
        await message.reply("❌ عملیات یافت نشد.")
        await state.clear()
        return

    cid = role.attacker_country_id if side == "attacker" else role.target_country_id
    country = await countries_repo.get_country(session, cid)
    if not country:
        await state.clear()
        return

    ok, res_text, remaining = await record_casualty(
        session, role, side, country, asset_name, count, message.from_user.id
    )
    await session.commit()
    await state.clear()

    side_fa = "مهاجم" if side == "attacker" else "مدافع"
    other_side = "target" if side == "attacker" else "attacker"
    other_side_fa = "مدافع" if other_side == "target" else "مهاجم"
    branch_fa = DEPLOY_BRANCHES.get(branch_key, ("نظامی", "", []))[0]
    admin_name = message.from_user.full_name

    # کیبورد ناوبری هوشمند پس از ثبت تلفات
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"🔙 بازگشت به لیست تجهیزات همین بخش ({branch_fa})",
        callback_data=f"mil_cas_br:{role_id}:{side}:{branch_key}:{page}",
        style=STYLE_MAIN,
    )
    builder.button(
        text="🔄 تغییر شاخه نظامی",
        callback_data=f"mil_cas_side:{role_id}:{side}",
        style=STYLE_MAIN,
    )
    builder.button(
        text=f"🔀 تغییر کشور (به {other_side_fa})",
        callback_data=f"mil_cas_side:{role_id}:{other_side}",
        style=STYLE_MAIN,
    )
    builder.button(
        text="🏁 بازگشت به پنل اصلی رول نظامی",
        callback_data=f"mil_grp_p:{role_id}:1",
        style=STYLE_OK,
    )
    builder.adjust(1)

    await message.reply(
        f"✅ <b>ثبت تلفات عملیاتی موفق:</b>\n"
        f"طرف: {country.flag} {country.name_fa} ({side_fa})\n"
        f"قلم: <b>{asset_name}</b> | تعداد تلفات: <b>{fa_number(count)}</b>\n"
        f"موجودی باقی‌مانده در کشور: <b>{fa_number(remaining)}</b> واحد.",
        reply_markup=builder.as_markup(),
    )

    # ثبت در لاگ
    await send_log(
        bot,
        f"💥 <b>ثبت تلفات در عملیات نظامی</b>\n"
        f"عملیات: {role.title}\n"
        f"کشور: {country.flag} {country.name_fa} ({side_fa})\n"
        f"تجهیزات کسرشده: {fa_number(count)} واحد از {asset_name}\n"
        f"ادمین: {admin_name}",
    )


# ============================================================
#  مشاهده رول‌های امنیتی کشور هدف
# ============================================================

@router.callback_query(F.data.startswith("mil_grp_tgt_sec:"))
async def cb_admin_target_sec_roles(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """مشاهده پروژه‌های امنیتی تاییدشده کشور هدف جهت تصمیم‌گیری عملیاتی."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    await call.answer()
    role_id = int(call.data.split(":")[1])
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
            callback_data=f"sec_view_p:{s.id}:1:mil_grp_p:{role_id}:1",
            style=STYLE_MAIN,
        )
    builder.button(text="🔙 بازگشت به عملیات", callback_data=f"mil_grp_p:{role_id}:1", style=STYLE_MAIN)
    builder.adjust(1)

    text = (
        header("آرشیو امنیتی کشور هدف", "🛡")
        + f"\n\nکشور هدف: {target.flag} <b>{target.name_fa}</b>\n"
        f"تعداد پروژه‌های دفاعی/امنیتی تاییدشده: <b>{fa_number(len(sec_roles))}</b>\n\n"
        "جهت مطالعه رول‌های امنیتی و نحوه پدافند کشور هدف، روی هر کدام کلیک کنید:"
    )
    await safe_edit(call, text, reply_markup=builder.as_markup())


# ============================================================
#  پایان عملیات و ارسال گزارش نهایی به طرفین
# ============================================================

@router.callback_query(F.data.startswith("mil_grp_end:"))
async def cb_admin_end_ask(call: CallbackQuery, session: AsyncSession) -> None:
    """درخواست تأیید پایان عملیات نظامی."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("تنها مدیران بازی مجاز به پایان عملیات هستند.", show_alert=True)
        return

    await call.answer()
    parts = call.data.split(":")
    role_id = int(parts[1])
    is_panel = len(parts) > 2 and parts[2] == "panel"
    back_cb = f"roles_admin:mil_v:{role_id}:1" if is_panel else f"mil_grp_p:{role_id}:1"

    role = await mil_ops_repo.get_military_role(session, role_id)
    if not role:
        return

    text = (
        header("پایان عملیات نظامی", "🏁")
        + f"\n\nآیا از مختومه کردن عملیات <b>«{role.title}»</b> مطمئن هستید؟\n\n"
        f"📊 <b>خلاصه تلفات ثبت‌شده:</b>\n"
        f"{format_casualties_report(role)}\n\n"
        f"با کلیک روی تأیید، دکمه‌های عملیات بسته شده و گزارش نتایج به بازیکن مهاجم ابلاغ خواهد شد."
    )
    await safe_edit(call, text, reply_markup=admin_military_end_confirm_kb(role_id, back_cb))


@router.callback_query(F.data.startswith("mil_end_do:"))
async def cb_admin_end_do(call: CallbackQuery, session: AsyncSession) -> None:
    """مختومه کردن قطعی عملیات و ارسال پیام به پیوی بازیکنان."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    await call.answer("عملیات به پایان رسید ✅")
    role_id = int(call.data.split(":")[1])
    role = await mil_ops_repo.get_military_role(session, role_id)
    if not role or role.status != MilitaryRoleStatus.PENDING_REVIEW.value:
        await call.answer("این عملیات قبلاً مختومه شده است.", show_alert=True)
        return

    attacker = await countries_repo.get_country(session, role.attacker_country_id)
    target = await countries_repo.get_country(session, role.target_country_id)
    if not attacker or not target:
        return

    admin_name = call.from_user.full_name
    await complete_military_role(session, role, call.from_user.id)
    await session.commit()

    # ویرایش پیام در گروه عملیات ستاد
    cas_report = format_casualties_report(role)
    try:
        await call.message.edit_text(
            call.message.html_text + f"\n\n🏁 <b>این عملیات توسط {admin_name} اجرا و رسماً مختومه شد.</b>\n"
            f"💥 <b>گزارش تلفات نهایی:</b>\n{cas_report}",
            reply_markup=None,
        )
    except Exception:
        pass

    # ارسال گزارش رسمی به پیوی لیدر کشور مهاجم
    if attacker.owner_user_id:
        try:
            await bot.send_message(
                attacker.owner_user_id,
                f"⚔️ <b>گزارش ستاد فرماندهی کل:</b>\n\n"
                f"رول عملیاتی شما (<b>{role.title}</b> علیه {target.flag} <b>{target.name_fa}</b>) "
                f"توسط ادمین اجرا شد و عملیات به پایان رسید.\n\n"
                f"💥 <b>گزارش تلفات و خسارات وارده:</b>\n{cas_report}",
            )
        except Exception:
            pass

    # در صورت ثبت خسارت روی کشور هدف، ارسال گزارش به هدف
    target_casualties = [c for c in role.casualties_list if c.get("side") == "target"]
    if target.owner_user_id and target_casualties:
        try:
            t_report_lines = [
                f"• کسر <b>{fa_number(c.get('count', 0))}</b> واحد «{c.get('asset_name')}»"
                for c in target_casualties
            ]
            await bot.send_message(
                target.owner_user_id,
                f"🚨 <b>گزارش فوری ستاد کل نیروهای مسلح:</b>\n\n"
                f"کشور شما هدف یک عملیات نظامی/خرابکاری قرار گرفت.\n\n"
                f"💥 <b>خسارات و تلفات وارده به نیروهای دفاعی:</b>\n"
                + "\n".join(t_report_lines),
            )
        except Exception:
            pass

    # لاگ مدیران
    await send_log(
        bot,
        f"🏁 <b>پایان عملیات نظامی</b>\n"
        f"عملیات: {role.title}\n"
        f"مهاجم: {attacker.flag} {attacker.name_fa}\n"
        f"هدف: {target.flag} {target.name_fa}\n"
        f"توسط ادمین: {admin_name}\n"
        f"تلفات: {cas_report}",
    )
