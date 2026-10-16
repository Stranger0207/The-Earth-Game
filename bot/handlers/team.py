"""هندلر مدیریت تیم و مالکان ربات (/team)."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import (
    add_dynamic_admin,
    add_dynamic_owner,
    get_settings,
    remove_dynamic_admin,
    remove_dynamic_owner,
)
from ..database.models import User
from ..database.repositories import users as users_repo
from ..keyboards.team import (
    team_cancel_kb,
    team_main_kb,
    team_owners_kb,
    team_remove_admin_kb,
    team_remove_owner_kb,
)
from ..loader import bot
from ..services.news_service import send_log
from ..states import TeamManageForm
from ..utils.numbers import fa_number
from ..utils.screens import safe_edit

logger = logging.getLogger(__name__)
router = Router(name="team")
settings = get_settings()


async def _format_user_line(session: AsyncSession, uid: int, label: str) -> str:
    """فرمت‌بندی یک خط از اعضای تیم."""
    user = await users_repo.get_user(session, uid)
    if user:
        name = user.first_name or f"کاربر {uid}"
        uname = f"@{user.username}" if user.username else "بدون یوزرنیم"
        return f"• <b>{name}</b> ({uname} | <code>{uid}</code>) — <i>{label}</i>"
    return f"• <code>{uid}</code> — <i>{label}</i>"


async def _render_team_screen(session: AsyncSession, caller_id: int) -> tuple[str, Any]:
    """تولید متن و کیبورد منوی تیم."""
    db_admins, db_owners = await users_repo.list_team_members(session)

    # تفکیک مالکان
    static_owner_ids = set(settings.owner_ids)
    dynamic_owner_ids = {u.telegram_id for u in db_owners}
    all_owner_ids = static_owner_ids | dynamic_owner_ids

    # تفکیک ادمین‌ها (به جز کسانی که مالک هستند)
    static_admin_ids = set(settings.admin_ids) - all_owner_ids
    dynamic_admin_ids = {u.telegram_id for u in db_admins} - all_owner_ids
    all_admin_ids = static_admin_ids | dynamic_admin_ids

    lines = [
        "👥 <b>تیم مدیریت ربات و سرور</b>",
        "────────────────────",
        "👑 <b>مالکان سیستم (Owners):</b>",
    ]

    if not all_owner_ids:
        lines.append("<i>(مالکی در تنظیمات ثبت نشده است)</i>")
    else:
        for oid in sorted(all_owner_ids):
            label = "مالک اصلی (غیرقابل خلع)" if oid in static_owner_ids else "مالک پویا"
            lines.append(await _format_user_line(session, oid, label))

    lines.append("\n🛡 <b>مدیران فعال (Admins):</b>")
    if not all_admin_ids:
        lines.append("<i>(هیچ ادمین اختصاصی ثبت نشده است)</i>")
    else:
        for aid in sorted(all_admin_ids):
            label = "مدیر ثابت" if aid in static_admin_ids else "مدیر پویا"
            lines.append(await _format_user_line(session, aid, label))

    lines.append("────────────────────")
    lines.append("💡 <i>مالکان اصلی در فایل کانفیگ تعیین شده و غیرقابل تغییر یا حذف هستند.</i>")

    is_caller_owner = settings.is_owner(caller_id)
    kb = team_main_kb(is_owner=is_caller_owner)
    return "\n".join(lines), kb


@router.message(Command("team"))
async def cmd_team(message: Message, session: AsyncSession) -> None:
    """ورود به پنل مدیریت تیم ربات."""
    if not settings.is_admin(message.from_user.id):
        return

    text, kb = await _render_team_screen(session, message.from_user.id)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "team:main")
async def cb_team_main(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """بازگشت به منوی اصلی تیم."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    await state.clear()
    text, kb = await _render_team_screen(session, call.from_user.id)
    await safe_edit(call, text, reply_markup=kb)
    await call.answer()


# ============================================================
#  افزودن ادمین جدید
# ============================================================
@router.callback_query(F.data == "team:add_admin")
async def cb_add_admin_start(call: CallbackQuery, state: FSMContext) -> None:
    """شروع فرایند افزودن ادمین جدید."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    await state.set_state(TeamManageForm.waiting_for_admin_id)
    msg = (
        "➕ <b>افزودن ادمین جدید</b>\n\n"
        "لطفاً <b>آیدی عددی</b> یا <b>یوزرنیم</b> (با علامت @ یا بدون آن) شخصی را که می‌خواهید به عنوان ادمین ربات منصوب شود ارسال کنید:\n\n"
        "💡 <i>اگر شخص هنوز ربات را استارت نکرده، با ارسال آیدی عددی می‌توانید او را پیشاپیش ثبت کنید.</i>"
    )
    await safe_edit(call, msg, reply_markup=team_cancel_kb())
    await call.answer()


@router.message(TeamManageForm.waiting_for_admin_id)
async def process_add_admin(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """پردازش ورودی آیدی/یوزرنیم برای افزودن ادمین."""
    if not settings.is_admin(message.from_user.id):
        return

    identifier = (message.text or "").strip()
    user, uid, err = await users_repo.get_user_by_username_or_id(session, identifier)
    if err:
        await message.answer(f"{err}\n\nلطفاً مجدداً ارسال کنید یا روی انصراف بزنید:", reply_markup=team_cancel_kb())
        return

    if user is None and uid:
        # ساخت کاربر پیشاپیش
        user = await users_repo.get_or_create_user(session, uid, None, None)

    if user is None or uid is None:
        await message.answer("❌ کاربر مورد نظر یافت نشد.", reply_markup=team_cancel_kb())
        return

    if settings.is_admin(uid):
        await message.answer(
            f"ℹ️ کاربر <code>{uid}</code> از قبل دسترسی مدیریت دارد.",
            reply_markup=team_cancel_kb(),
        )
        return

    # اعمال ادمین
    await users_repo.set_user_admin(session, uid, True)
    add_dynamic_admin(uid)
    await session.commit()
    await state.clear()

    caller_name = message.from_user.full_name
    user_display = f"@{user.username}" if user.username else (user.first_name or f"کاربر {uid}")

    await message.answer(
        f"✅ <b>ادمین جدید با موفقیت اضافه شد!</b>\n\n"
        f"👤 کاربر: {user_display}\n"
        f"🆔 شناسه: <code>{uid}</code>\n"
        f"🛡 دسترسی‌های مدیریتی ربات برای این شخص فعال گردید.",
        reply_markup=team_cancel_kb(),
    )

    # اطلاع به لاگ
    await send_log(
        bot,
        f"🛡 <b>انتصاب ادمین جدید</b>\n"
        f"کاربر: {user_display} (<code>{uid}</code>)\n"
        f"توسط: {caller_name} (<code>{message.from_user.id}</code>)",
    )

    # ارسال پیام تبریک به پیوی کاربر
    try:
        await bot.send_message(
            uid,
            "🎉 <b>تبریک! شما توسط مدیریت به عنوان ادمین ربات منصوب شدید.</b>\n\n"
            "دستورات مدیریتی ربات (مانند /team، /ban و...) اکنون برای شما فعال هستند.\n"
            "با دستور /team می‌توانید وضعیت تیم را مشاهده کنید.",
        )
    except Exception as exc:
        logger.debug("Failed to notify promoted admin %s: %s", uid, exc)


# ============================================================
#  حذف ادمین
# ============================================================
@router.callback_query(F.data == "team:remove_admin")
async def cb_remove_admin_menu(call: CallbackQuery, session: AsyncSession) -> None:
    """نمایش لیست ادمین‌های پویا جهت حذف."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    db_admins, db_owners = await users_repo.list_team_members(session)
    owner_uids = {u.telegram_id for u in db_owners} | set(settings.owner_ids)

    # فقط ادمین‌های پویا که مالک نیستند و در static_admin_ids نیستند قابل حذف از دیتابیس هستند
    removable_admins = [u for u in db_admins if u.telegram_id not in owner_uids]

    msg = (
        "➖ <b>حذف ادمین</b>\n\n"
        "یکی از ادمین‌های زیر را جهت سلب دسترسی انتخاب کنید، یا دکمه ارسال متنی را بزنید:"
    )
    await safe_edit(call, msg, reply_markup=team_remove_admin_kb(removable_admins))
    await call.answer()


@router.callback_query(F.data == "team:manual_del_admin")
async def cb_manual_del_admin(call: CallbackQuery, state: FSMContext) -> None:
    """ورود دستی آیدی جهت حذف ادمین."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    await state.set_state(TeamManageForm.waiting_for_remove_admin)
    msg = (
        "➖ <b>سلب دسترسی ادمین (ورود دستی)</b>\n\n"
        "لطفاً آیدی عددی یا یوزرنیم شخصی را که می‌خواهید از مدیریت خلع شود ارسال کنید:"
    )
    await safe_edit(call, msg, reply_markup=team_cancel_kb())
    await call.answer()


async def _execute_remove_admin(
    session: AsyncSession,
    caller_id: int,
    caller_name: str,
    target_id: int,
) -> tuple[bool, str]:
    """تابع کمکی اجرای حذف ادمین با اعتبارسنجی امنیتی."""
    if settings.is_static_owner(target_id):
        return False, "⛔️ امکان خلع مالک اصلی سیستم وجود ندارد."

    if target_id == caller_id:
        return False, "⛔️ شما نمی‌توانید دسترسی خودتان را سلب کنید."

    if settings.is_owner(target_id) and not settings.is_owner(caller_id):
        return False, "⛔️ فقط مالکان ربات می‌توانند مالکان دیگر را عزل کنند."

    if target_id in settings.admin_ids:
        return False, "⚠️ این کاربر در متغیرهای محیطی (.env) به عنوان ادمین ثابت تعریف شده و فقط از فایل تنظیمات قابل تغییر است."

    user = await users_repo.get_user(session, target_id)
    if user is None or not user.is_admin:
        return False, f"⚠️ کاربر <code>{target_id}</code> ادمین پویای ثبت‌شده نیست."

    await users_repo.set_user_admin(session, target_id, False)
    remove_dynamic_admin(target_id)
    await session.commit()

    user_display = f"@{user.username}" if user.username else (user.first_name or f"کاربر {target_id}")

    # ثبت لاگ
    await send_log(
        bot,
        f"⚠️ <b>خلع ادمین</b>\n"
        f"کاربر: {user_display} (<code>{target_id}</code>)\n"
        f"توسط: {caller_name} (<code>{caller_id}</code>)",
    )

    # اطلاع به پیوی کاربر
    try:
        await bot.send_message(
            target_id,
            "⚠️ <b>پایان دسترسی مدیریت</b>\n\n"
            "دسترسی شما به پنل و دستورات ادمین ربات توسط مدیریت خاتمه یافت.",
        )
    except Exception as exc:
        logger.debug("Failed to notify demoted admin %s: %s", target_id, exc)

    return True, f"✅ کاربر {user_display} (<code>{target_id}</code>) با موفقیت از مقام ادمینی خلع شد."


@router.callback_query(F.data.startswith("team:del_admin:"))
async def cb_del_admin_click(call: CallbackQuery, session: AsyncSession) -> None:
    """کلیک روی دکمه حذف ادمین از لیست."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    target_id = int(call.data.split(":")[2])
    ok, res = await _execute_remove_admin(
        session, call.from_user.id, call.from_user.full_name, target_id
    )
    if not ok:
        await call.answer(res, show_alert=True)
        return

    await call.answer("ادمین با موفقیت خلع شد.")
    text, kb = await _render_team_screen(session, call.from_user.id)
    await safe_edit(call, f"{res}\n\n{text}", reply_markup=kb)


@router.message(TeamManageForm.waiting_for_remove_admin)
async def process_remove_admin_text(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """پردازش ورودی متنی برای حذف ادمین."""
    if not settings.is_admin(message.from_user.id):
        return

    identifier = (message.text or "").strip()
    user, uid, err = await users_repo.get_user_by_username_or_id(session, identifier)
    if err:
        await message.answer(f"{err}\n\nلطفاً مجدداً ارسال کنید یا روی انصراف بزنید:", reply_markup=team_cancel_kb())
        return

    if uid is None:
        await message.answer("❌ کاربر یافت نشد.", reply_markup=team_cancel_kb())
        return

    ok, res = await _execute_remove_admin(
        session, message.from_user.id, message.from_user.full_name, uid
    )
    if not ok:
        await message.answer(res, reply_markup=team_cancel_kb())
        return

    await state.clear()
    text, kb = await _render_team_screen(session, message.from_user.id)
    await message.answer(f"{res}\n\n{text}", reply_markup=kb)


# ============================================================
#  مدیریت مالکان (مختص Owners)
# ============================================================
@router.callback_query(F.data == "team:manage_owners")
async def cb_manage_owners_menu(call: CallbackQuery) -> None:
    """ورود به زیرمنوی مدیریت مالکان ربات."""
    if not settings.is_owner(call.from_user.id):
        await call.answer("⛔️ این بخش منحصراً مختص مالکان ربات است.", show_alert=True)
        return

    msg = (
        "👑 <b>مدیریت مالکان ربات</b>\n\n"
        "در این بخش می‌توانید مالکان پویا به دیتابیس اضافه یا آن‌ها را خلع کنید.\n\n"
        "⚠️ <i>مالکان اصلی ثبت‌شده در فایل تنظیمات غیرقابل خلع هستند.</i>"
    )
    await safe_edit(call, msg, reply_markup=team_owners_kb())
    await call.answer()


@router.callback_query(F.data == "team:add_owner")
async def cb_add_owner_start(call: CallbackQuery, state: FSMContext) -> None:
    """شروع فرایند افزودن مالک جدید."""
    if not settings.is_owner(call.from_user.id):
        await call.answer("⛔️ فقط مالک ربات مجاز به این کار است.", show_alert=True)
        return

    await state.set_state(TeamManageForm.waiting_for_owner_id)
    msg = (
        "➕ <b>افزودن مالک جدید</b>\n\n"
        "لطفاً <b>آیدی عددی</b> یا <b>یوزرنیم</b> شخصی را که می‌خواهید به عنوان مالک ربات منصوب شود ارسال کنید:\n\n"
        "⚠️ <i>مالک به بالاترین سطح دسترسی ربات (مدیریت تیم، ریست بازی و...) دسترسی خواهد داشت.</i>"
    )
    await safe_edit(call, msg, reply_markup=team_cancel_kb())
    await call.answer()


@router.message(TeamManageForm.waiting_for_owner_id)
async def process_add_owner(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """پردازش ورودی برای افزودن مالک."""
    if not settings.is_owner(message.from_user.id):
        return

    identifier = (message.text or "").strip()
    user, uid, err = await users_repo.get_user_by_username_or_id(session, identifier)
    if err:
        await message.answer(f"{err}\n\nلطفاً مجدداً ارسال کنید:", reply_markup=team_cancel_kb())
        return

    if user is None and uid:
        user = await users_repo.get_or_create_user(session, uid, None, None)

    if user is None or uid is None:
        await message.answer("❌ کاربر یافت نشد.", reply_markup=team_cancel_kb())
        return

    if settings.is_owner(uid):
        await message.answer(f"ℹ️ کاربر <code>{uid}</code> از قبل مالک بازی است.", reply_markup=team_cancel_kb())
        return

    await users_repo.set_user_owner(session, uid, True)
    add_dynamic_owner(uid)
    add_dynamic_admin(uid)
    await session.commit()
    await state.clear()

    caller_name = message.from_user.full_name
    user_display = f"@{user.username}" if user.username else (user.first_name or f"کاربر {uid}")

    await message.answer(
        f"👑 <b>مالک جدید با موفقیت منصوب شد!</b>\n\n"
        f"👤 کاربر: {user_display}\n"
        f"🆔 شناسه: <code>{uid}</code>\n"
        f"دسترسی کامل مدیریت و مالکیت برای ایشان فعال گردید.",
        reply_markup=team_cancel_kb(),
    )

    await send_log(
        bot,
        f"👑 <b>انتصاب مالک جدید</b>\n"
        f"کاربر: {user_display} (<code>{uid}</code>)\n"
        f"توسط: {caller_name} (<code>{message.from_user.id}</code>)",
    )

    try:
        await bot.send_message(
            uid,
            "👑 <b>تبریک! شما به عنوان مالک (Owner) ربات منصوب شدید.</b>\n\n"
            "اکنون دسترسی کامل به پنل‌های ارشد مدیریتی و فرمان /team را دارا هستید.",
        )
    except Exception as exc:
        logger.debug("Failed to notify promoted owner %s: %s", uid, exc)


@router.callback_query(F.data == "team:remove_owner")
async def cb_remove_owner_menu(call: CallbackQuery, session: AsyncSession) -> None:
    """نمایش لیست مالکان پویا جهت خلع."""
    if not settings.is_owner(call.from_user.id):
        await call.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    _, db_owners = await users_repo.list_team_members(session)
    static_owner_ids = set(settings.owner_ids)
    removable_owners = [u for u in db_owners if u.telegram_id not in static_owner_ids]

    if not removable_owners:
        await call.answer("هیچ مالک پویایی برای خلع وجود ندارد (مالکان اصلی غیرقابل حذف هستند).", show_alert=True)
        return

    msg = (
        "➖ <b>خلع مالک پویا</b>\n\n"
        "یکی از مالکان زیر را انتخاب کنید:"
    )
    await safe_edit(call, msg, reply_markup=team_remove_owner_kb(removable_owners))
    await call.answer()


@router.callback_query(F.data == "team:manual_del_owner")
async def cb_manual_del_owner(call: CallbackQuery, state: FSMContext) -> None:
    """ورود دستی آیدی جهت خلع مالک."""
    if not settings.is_owner(call.from_user.id):
        await call.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    await state.set_state(TeamManageForm.waiting_for_remove_owner)
    msg = (
        "➖ <b>خلع مالک پویا (ورود دستی)</b>\n\n"
        "لطفاً آیدی عددی یا یوزرنیم مالک را ارسال کنید:"
    )
    await safe_edit(call, msg, reply_markup=team_cancel_kb())
    await call.answer()


async def _execute_remove_owner(
    session: AsyncSession,
    caller_id: int,
    caller_name: str,
    target_id: int,
) -> tuple[bool, str]:
    """اجرای خلع مالک پویا."""
    if settings.is_static_owner(target_id):
        return False, "⛔️ مالک اصلی سیستم در فایل کانفیگ تعیین شده و غیرقابل خلع است."

    if target_id == caller_id:
        return False, "⛔️ شما نمی‌توانید مالکیت خودتان را سلب کنید."

    user = await users_repo.get_user(session, target_id)
    if user is None or not user.is_owner:
        return False, f"⚠️ کاربر <code>{target_id}</code> مالک پویای ثبت‌شده نیست."

    await users_repo.set_user_owner(session, target_id, False)
    # دسترسی ادمینی را هم از او برمی‌داریم
    await users_repo.set_user_admin(session, target_id, False)
    remove_dynamic_owner(target_id)
    remove_dynamic_admin(target_id)
    await session.commit()

    user_display = f"@{user.username}" if user.username else (user.first_name or f"کاربر {target_id}")

    await send_log(
        bot,
        f"⚠️ <b>خلع مالک ربات</b>\n"
        f"کاربر: {user_display} (<code>{target_id}</code>)\n"
        f"توسط: {caller_name} (<code>{caller_id}</code>)",
    )

    try:
        await bot.send_message(
            target_id,
            "⚠️ <b>سلب دسترسی مالکیت ربات</b>\n\n"
            "دسترسی مالکیت شما توسط مدیریت سیستم لغو شد.",
        )
    except Exception as exc:
        logger.debug("Failed to notify demoted owner %s: %s", target_id, exc)

    return True, f"✅ کاربر {user_display} (<code>{target_id}</code>) با موفقیت از مقام مالکیت خلع شد."


@router.callback_query(F.data.startswith("team:del_owner:"))
async def cb_del_owner_click(call: CallbackQuery, session: AsyncSession) -> None:
    """کلیک روی دکمه خلع مالک."""
    if not settings.is_owner(call.from_user.id):
        await call.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    target_id = int(call.data.split(":")[2])
    ok, res = await _execute_remove_owner(
        session, call.from_user.id, call.from_user.full_name, target_id
    )
    if not ok:
        await call.answer(res, show_alert=True)
        return

    await call.answer("مالک خلع شد.")
    text, kb = await _render_team_screen(session, call.from_user.id)
    await safe_edit(call, f"{res}\n\n{text}", reply_markup=kb)


@router.message(TeamManageForm.waiting_for_remove_owner)
async def process_remove_owner_text(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """پردازش متنی خلع مالک."""
    if not settings.is_owner(message.from_user.id):
        return

    identifier = (message.text or "").strip()
    user, uid, err = await users_repo.get_user_by_username_or_id(session, identifier)
    if err:
        await message.answer(f"{err}\n\nلطفاً مجدداً ارسال کنید:", reply_markup=team_cancel_kb())
        return

    if uid is None:
        await message.answer("❌ کاربر یافت نشد.", reply_markup=team_cancel_kb())
        return

    ok, res = await _execute_remove_owner(
        session, message.from_user.id, message.from_user.full_name, uid
    )
    if not ok:
        await message.answer(res, reply_markup=team_cancel_kb())
        return

    await state.clear()
    text, kb = await _render_team_screen(session, message.from_user.id)
    await message.answer(f"{res}\n\n{text}", reply_markup=kb)
