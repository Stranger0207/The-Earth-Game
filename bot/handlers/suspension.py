"""هندلر تعلیق زمان‌دار و رفع تعلیق بازیکنان (/suspension و /unsuspend)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database.models import User
from ..database.repositories import users as users_repo
from ..keyboards.suspension import (
    suspension_cancel_kb,
    suspension_durations_kb,
    suspension_reason_kb,
    unsuspend_list_kb,
)
from ..loader import bot
from ..services.news_service import send_log
from ..states import SuspensionForm
from ..utils.numbers import fa_number
from ..utils.screens import safe_edit

logger = logging.getLogger(__name__)
router = Router(name="suspension")
settings = get_settings()

VALID_DURATIONS = {6, 12, 24, 48}


async def _apply_suspension(
    session: AsyncSession,
    caller_id: int,
    caller_name: str,
    target_id: int,
    duration_hours: int,
    reason: str | None,
) -> tuple[bool, str]:
    """اعمال تعلیق زمان‌دار بر کاربر."""
    if settings.is_admin(target_id) or settings.is_owner(target_id):
        return False, "⛔️ امکان تعلیق ادمین یا مالک ربات وجود ندارد."

    user = await users_repo.get_user(session, target_id)
    if user is None:
        user = await users_repo.get_or_create_user(session, target_id, None, None)

    _, until = await users_repo.set_timed_suspension(
        session, target_id, duration_hours, reason
    )
    await session.commit()

    until_str = until.strftime("%Y-%m-%d %H:%M UTC")
    reason_display = reason or "بدون ذکر علت"
    user_display = f"@{user.username}" if user.username else (user.first_name or f"کاربر {target_id}")

    # ثبت لاگ
    await send_log(
        bot,
        f"⏸ <b>تعلیق بازیکن</b>\n"
        f"کاربر: {user_display} (<code>{target_id}</code>)\n"
        f"مدت: {fa_number(duration_hours)} ساعت (تا {until_str})\n"
        f"علت: {reason_display}\n"
        f"توسط: {caller_name} (<code>{caller_id}</code>)",
    )

    # ارسال پیام خصوصی به بازیکن
    try:
        await bot.send_message(
            target_id,
            "⏸ <b>حساب کاربری و مدیریت کشور شما موقتاً معلق شد.</b>\n\n"
            f"⏱ <b>مدت تعلیق:</b> {fa_number(duration_hours)} ساعت\n"
            f"⏳ <b>پایان تعلیق:</b> {until_str}\n"
            f"📝 <b>علت:</b> {reason_display}\n\n"
            "تا پایان زمان تعلیق، امکان انجام هیچ اقدامی در بازی را نخواهید داشت.",
        )
    except Exception as exc:
        logger.debug("Failed to notify suspended user %s: %s", target_id, exc)

    return True, (
        f"✅ <b>کاربر با موفقیت معلق شد:</b>\n\n"
        f"👤 کاربر: {user_display}\n"
        f"🆔 شناسه: <code>{target_id}</code>\n"
        f"⏱ مدت: {fa_number(duration_hours)} ساعت\n"
        f"⏳ پایان: {until_str}\n"
        f"📝 علت: {reason_display}"
    )


async def _execute_unsuspend(
    session: AsyncSession,
    caller_id: int,
    caller_name: str,
    target_id: int,
) -> tuple[bool, str]:
    """رفع تعلیق کاربر."""
    user = await users_repo.get_user(session, target_id)
    if user is None or not user.is_suspended:
        return False, f"⚠️ کاربر <code>{target_id}</code> در حالت تعلیق نیست."

    await users_repo.lift_suspension(session, target_id)
    await session.commit()

    user_display = f"@{user.username}" if user.username else (user.first_name or f"کاربر {target_id}")

    await send_log(
        bot,
        f"🟢 <b>رفع تعلیق بازیکن</b>\n"
        f"کاربر: {user_display} (<code>{target_id}</code>)\n"
        f"توسط: {caller_name} (<code>{caller_id}</code>)",
    )

    try:
        await bot.send_message(
            target_id,
            "🟢 <b>پایان تعلیق</b>\n\n"
            "تعلیق حساب کاربری شما توسط مدیریت لغو شد و دسترسی شما مجدداً فعال گردید.\n"
            "می‌توانید با دستور /start فعالیت خود را ادامه دهید.",
        )
    except Exception as exc:
        logger.debug("Failed to notify unsuspended user %s: %s", target_id, exc)

    return True, f"✅ تعلیق کاربر {user_display} (<code>{target_id}</code>) با موفقیت لغو شد."


# ============================================================
#  دستور /suspension
# ============================================================
@router.message(Command("suspension"))
async def cmd_suspension(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """دستور تعلیق بازیکن."""
    if not settings.is_admin(message.from_user.id):
        return

    text = message.text or ""
    parts = text.split(maxsplit=3)
    target_str: str | None = None
    duration: int | None = None
    reason: str | None = None

    # ریپلای روی پیام
    if message.reply_to_message and message.reply_to_message.from_user:
        target_str = str(message.reply_to_message.from_user.id)
        if len(parts) >= 2:
            if parts[1].isdigit() and int(parts[1]) in VALID_DURATIONS:
                duration = int(parts[1])
                if len(parts) >= 3:
                    reason = " ".join(parts[2:])
            else:
                reason = " ".join(parts[1:])
    elif len(parts) >= 2:
        target_str = parts[1]
        if len(parts) >= 3 and parts[2].isdigit() and int(parts[2]) in VALID_DURATIONS:
            duration = int(parts[2])
            if len(parts) >= 4:
                reason = parts[3]
        elif len(parts) >= 3:
            reason = " ".join(parts[2:])

    # اگر هدفی مشخص نشده، پنل تعاملی باز می‌شود
    if not target_str:
        await state.set_state(SuspensionForm.waiting_for_target)
        msg = (
            "⏸ <b>تعلیق زمان‌دار بازیکن (/suspension)</b>\n\n"
            "لطفاً <b>آیدی عددی</b> یا <b>یوزرنیم</b> (با @ یا بدون @) کاربر مورد نظر را ارسال کنید:\n\n"
            "💡 <i>همچنین می‌توانید به صورت تک‌خطی استفاده کنید:</i>\n"
            "<code>/suspension 12345678 12 نقض قوانین بازی</code>\n"
            "<i>(مدت‌های مجاز: ۶، ۱۲، ۲۴، ۴۸ ساعت)</i>"
        )
        await message.answer(msg, reply_markup=suspension_cancel_kb())
        return

    user, uid, err = await users_repo.get_user_by_username_or_id(session, target_str)
    if err:
        await message.answer(err)
        return

    if uid is None:
        await message.answer("❌ کاربر یافت نشد.")
        return

    if settings.is_admin(uid) or settings.is_owner(uid):
        await message.answer("⛔️ امکان تعلیق ادمین یا مالک ربات وجود ندارد.")
        return

    # اگر مدت زمان از قبل داده شده بود، بلافاصله اعمال می‌شود
    if duration is not None:
        ok, res = await _apply_suspension(
            session,
            message.from_user.id,
            message.from_user.full_name,
            uid,
            duration,
            reason,
        )
        await message.answer(res)
        return

    # در غیر این صورت، دکمه‌های مدت زمان نمایش داده می‌شود
    await state.clear()
    user_display = f"@{user.username}" if user and user.username else (user.first_name if user else f"کاربر {uid}")
    msg = (
        f"⏸ <b>انتخاب مدت زمان تعلیق برای:</b>\n"
        f"👤 کاربر: {user_display} (<code>{uid}</code>)\n\n"
        "لطفاً مدت زمان مورد نظر را انتخاب کنید:"
    )
    await message.answer(msg, reply_markup=suspension_durations_kb(uid))


@router.message(SuspensionForm.waiting_for_target)
async def process_suspension_target(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """دریافت شناسه هدف در فلوی تعاملی تعلیق."""
    if not settings.is_admin(message.from_user.id):
        return

    identifier = (message.text or "").strip()
    user, uid, err = await users_repo.get_user_by_username_or_id(session, identifier)
    if err:
        await message.answer(f"{err}\n\nمجدداً ارسال کنید:", reply_markup=suspension_cancel_kb())
        return

    if uid is None:
        await message.answer("❌ کاربر یافت نشد.", reply_markup=suspension_cancel_kb())
        return

    if settings.is_admin(uid) or settings.is_owner(uid):
        await message.answer("⛔️ امکان تعلیق ادمین یا مالک ربات وجود ندارد.", reply_markup=suspension_cancel_kb())
        return

    await state.clear()
    user_display = f"@{user.username}" if user and user.username else (user.first_name if user else f"کاربر {uid}")
    msg = (
        f"⏸ <b>انتخاب مدت زمان تعلیق برای:</b>\n"
        f"👤 کاربر: {user_display} (<code>{uid}</code>)\n\n"
        "یکی از مدت‌های زیر را انتخاب کنید:"
    )
    await message.answer(msg, reply_markup=suspension_durations_kb(uid))


@router.callback_query(F.data.startswith("susp:dur:"))
async def cb_suspension_duration(call: CallbackQuery, state: FSMContext) -> None:
    """انتخاب مدت زمان از کیبورد اینلاین."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    parts = call.data.split(":")
    target_id = int(parts[2])
    hours = int(parts[3])

    await state.set_state(SuspensionForm.entering_reason)
    await state.update_data(target_id=target_id, hours=hours)

    msg = (
        f"⏱ مدت تعلیق: <b>{fa_number(hours)} ساعت</b>\n\n"
        "لطفاً <b>علت تعلیق</b> را بنویسید و ارسال کنید، یا روی «⏩ بدون ذکر علت» بزنید:"
    )
    await safe_edit(call, msg, reply_markup=suspension_reason_kb(target_id, hours))
    await call.answer()


@router.callback_query(F.data.startswith("susp:confirm:"))
async def cb_suspension_confirm_no_reason(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """تأیید تعلیق بدون ذکر علت."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    parts = call.data.split(":")
    target_id = int(parts[2])
    hours = int(parts[3])

    await state.clear()
    ok, res = await _apply_suspension(
        session,
        call.from_user.id,
        call.from_user.full_name,
        target_id,
        hours,
        reason=None,
    )
    await safe_edit(call, res)
    await call.answer("تعلیق با موفقیت اعمال شد.")


@router.message(SuspensionForm.entering_reason)
async def process_suspension_reason_text(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """دریافت متن علت تعلیق."""
    if not settings.is_admin(message.from_user.id):
        return

    data = await state.get_data()
    target_id = data.get("target_id")
    hours = data.get("hours")

    if not target_id or not hours:
        await state.clear()
        await message.answer("❌ اطلاعات نشست نامعتبر است. لطفاً مجدداً اقدام کنید.")
        return

    reason = (message.text or "").strip()
    await state.clear()

    ok, res = await _apply_suspension(
        session,
        message.from_user.id,
        message.from_user.full_name,
        target_id,
        hours,
        reason=reason,
    )
    await message.answer(res)


# ============================================================
#  دستور /unsuspend
# ============================================================
@router.message(Command("unsuspend"))
async def cmd_unsuspend(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """دستور رفع تعلیق کاربر."""
    if not settings.is_admin(message.from_user.id):
        return

    text = message.text or ""
    parts = text.split(maxsplit=1)
    target_str: str | None = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_str = str(message.reply_to_message.from_user.id)
    elif len(parts) >= 2:
        target_str = parts[1]

    # اگر تک‌خطی با شناسه صدا زده شد
    if target_str:
        user, uid, err = await users_repo.get_user_by_username_or_id(session, target_str)
        if err:
            await message.answer(err)
            return
        if uid is None:
            await message.answer("❌ کاربر یافت نشد.")
            return

        ok, res = await _execute_unsuspend(
            session, message.from_user.id, message.from_user.full_name, uid
        )
        await message.answer(res)
        return

    # در صورت عدم ارسال پارامتر، فهرست کاربران معلق نمایش داده می‌شود
    suspended_users = await users_repo.list_suspended_users(session)
    if not suspended_users:
        await message.answer("🟢 در حال حاضر هیچ بازیکنی در وضعیت تعلیق قرار ندارد.")
        return

    msg = (
        "🔓 <b>فهرست کاربران معلق (/unsuspend)</b>\n\n"
        "جهت رفع تعلیق هر بازیکن، روی دکمه مربوطه کلیک کنید یا شناسه او را به صورت متنی ارسال نمایید:"
    )
    await message.answer(msg, reply_markup=unsuspend_list_kb(suspended_users))


@router.callback_query(F.data.startswith("unsusp:do:"))
async def cb_unsuspend_click(call: CallbackQuery, session: AsyncSession) -> None:
    """کلیک روی دکمه رفع تعلیق کاربر."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    target_id = int(call.data.split(":")[2])
    ok, res = await _execute_unsuspend(
        session, call.from_user.id, call.from_user.full_name, target_id
    )
    if not ok:
        await call.answer(res, show_alert=True)
        return

    await call.answer("تعلیق رفع شد.")
    # به‌روزرسانی لیست
    suspended_users = await users_repo.list_suspended_users(session)
    if not suspended_users:
        await safe_edit(call, f"{res}\n\n🟢 در حال حاضر هیچ بازیکن دیگری در حالت تعلیق نیست.")
    else:
        msg = f"{res}\n\nسایر کاربران معلق:"
        await safe_edit(call, msg, reply_markup=unsuspend_list_kb(suspended_users))


@router.callback_query(F.data == "unsusp:manual")
async def cb_unsuspend_manual(call: CallbackQuery, state: FSMContext) -> None:
    """ورود دستی آیدی جهت رفع تعلیق."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    await state.set_state(SuspensionForm.waiting_for_unsuspend)
    msg = (
        "🔓 <b>رفع تعلیق دستی</b>\n\n"
        "لطفاً آیدی عددی یا یوزرنیم بازیکن مورد نظر را ارسال کنید:"
    )
    await safe_edit(call, msg, reply_markup=suspension_cancel_kb())
    await call.answer()


@router.message(SuspensionForm.waiting_for_unsuspend)
async def process_unsuspend_text(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """پردازش متنی رفع تعلیق."""
    if not settings.is_admin(message.from_user.id):
        return

    identifier = (message.text or "").strip()
    user, uid, err = await users_repo.get_user_by_username_or_id(session, identifier)
    if err:
        await message.answer(f"{err}\n\nمجدداً ارسال کنید:", reply_markup=suspension_cancel_kb())
        return

    if uid is None:
        await message.answer("❌ کاربر یافت نشد.", reply_markup=suspension_cancel_kb())
        return

    ok, res = await _execute_unsuspend(
        session, message.from_user.id, message.from_user.full_name, uid
    )
    await state.clear()
    await message.answer(res)


@router.callback_query(F.data == "susp:cancel")
async def cb_susp_cancel(call: CallbackQuery, state: FSMContext) -> None:
    """انصراف از عملیات تعلیق / رفع تعلیق."""
    await state.clear()
    await safe_edit(call, "❌ عملیات لغو شد.")
    await call.answer()
