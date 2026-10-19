"""
هندلرهای پیام همگانی سراسری، تنظیم جوین اجباری کانال و لینک فولدر بازی.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database.repositories import bot_state as bot_state_repo
from ..database.repositories import users as users_repo
from ..enums import AdminGroupType
from ..loader import bot
from ..services.news_service import send_to_admin_group
from ..states import BroadcastForm, SetChannelForm, SetFolderForm
from ..utils.numbers import fa_number
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK, header

router = Router(name="broadcast")
settings = get_settings()
logger = logging.getLogger(__name__)


def _is_admin(user_id: int) -> bool:
    """بررسی دسترسی ادمین یا مالک."""
    return settings.is_admin(user_id) or settings.is_owner(user_id)


# ============================================================
#  ارسال پیام همگانی سراسری (/broadcast و /sendall)
# ============================================================

@router.message(Command("broadcast", "sendall"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    """آغاز فرآیند ارسال پیام همگانی به تمام کاربران ربات."""
    if not _is_admin(message.from_user.id):
        return

    await state.clear()
    await state.set_state(BroadcastForm.waiting_for_content)

    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ انصراف", callback_data="bcast:cancel", style=STYLE_NO)]
        ]
    )
    await message.answer(
        "📢 <b>ارسال پیام همگانی به کل کاربران ربات</b>\n\n"
        "لطفاً پیام خود را ارسال کنید. می‌توانید <b>فقط متن</b> بفرستید و یا "
        "<b>یک عکس به همراه کپشن (متن زیر عکس)</b> ارسال کنید:",
        reply_markup=cancel_kb,
    )


@router.callback_query(F.data == "bcast:cancel")
async def cb_broadcast_cancel(call: CallbackQuery, state: FSMContext) -> None:
    """لغو فرآیند ارسال پیام همگانی."""
    if not _is_admin(call.from_user.id):
        return
    await call.answer("لغو شد")
    await state.clear()
    await call.message.edit_text("❌ ارسال پیام همگانی لغو شد.")


@router.message(BroadcastForm.waiting_for_content, F.photo)
async def msg_broadcast_photo(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """دریافت تصویر به همراه متن برای پیام همگانی."""
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    photo_file_id = message.photo[-1].file_id
    caption = message.html_text or message.caption or ""

    user_ids = await users_repo.list_all_user_telegram_ids(session)
    total_users = len(user_ids)

    await state.update_data(
        content_type="photo",
        photo_file_id=photo_file_id,
        caption=caption,
    )
    await state.set_state(BroadcastForm.confirming)

    confirm_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ بله، ارسال به همه",
                    callback_data="bcast:confirm",
                    style=STYLE_OK,
                ),
                InlineKeyboardButton(
                    text="❌ انصراف",
                    callback_data="bcast:cancel",
                    style=STYLE_NO,
                ),
            ]
        ]
    )

    # ارسال پیش‌نمایش عکس
    await message.answer_photo(
        photo=photo_file_id,
        caption=(
            f"👁‍🗨 <b>پیش‌نمایش پیام همگانی:</b>\n\n{caption}\n\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"📊 این پیام برای <b>{fa_number(total_users)}</b> نفر که تاکنون ربات را استارت کرده‌اند "
            f"ارسال خواهد شد. آیا تأیید می‌کنید؟"
        ),
        reply_markup=confirm_kb,
    )


@router.message(BroadcastForm.waiting_for_content, F.text)
async def msg_broadcast_text(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """دریافت متن برای پیام همگانی."""
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    text_body = message.html_text or message.text or ""
    user_ids = await users_repo.list_all_user_telegram_ids(session)
    total_users = len(user_ids)

    await state.update_data(
        content_type="text",
        text_body=text_body,
    )
    await state.set_state(BroadcastForm.confirming)

    confirm_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ بله، ارسال به همه",
                    callback_data="bcast:confirm",
                    style=STYLE_OK,
                ),
                InlineKeyboardButton(
                    text="❌ انصراف",
                    callback_data="bcast:cancel",
                    style=STYLE_NO,
                ),
            ]
        ]
    )

    await message.answer(
        f"👁‍🗨 <b>پیش‌نمایش پیام همگانی:</b>\n\n{text_body}\n\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"📊 این پیام برای <b>{fa_number(total_users)}</b> نفر که تاکنون ربات را استارت کرده‌اند "
        f"ارسال خواهد شد. آیا تأیید می‌کنید؟",
        reply_markup=confirm_kb,
    )


@router.callback_query(BroadcastForm.confirming, F.data == "bcast:confirm")
async def cb_broadcast_confirm(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """اجرای ارسال پیام همگانی به کل کاربران با رعایت نرخ ارسال تلگرام."""
    if not _is_admin(call.from_user.id):
        return

    data = await state.get_data()
    await state.clear()
    await call.answer("در حال شروع ارسال...")

    content_type = data.get("content_type")
    photo_file_id = data.get("photo_file_id")
    caption = data.get("caption", "")
    text_body = data.get("text_body", "")

    status_msg = await call.message.answer(
        "⏳ <b>ارسال پیام همگانی به تمام کاربران آغاز شد...</b>\n"
        "لطفاً تا پایان عملیات و آماده‌سازی گزارش شکیبا باشید."
    )

    user_ids = await users_repo.list_all_user_telegram_ids(session)
    success_count = 0
    fail_count = 0

    for uid in user_ids:
        try:
            if content_type == "photo":
                await bot.send_photo(
                    chat_id=uid,
                    photo=photo_file_id,
                    caption=caption,
                )
            else:
                await bot.send_message(
                    chat_id=uid,
                    text=text_body,
                )
            success_count += 1
        except Exception:
            fail_count += 1

        # وقفه برای رعایت محدودیت ارسال تلگرام
        await asyncio.sleep(0.05)

    report = (
        "✅ <b>ارسال پیام همگانی به پایان رسید:</b>\n\n"
        f"🟢 <b>ارسال موفق:</b> {fa_number(success_count)} نفر\n"
        f"🔴 <b>ناموفق (بلاک/حذف اکانت):</b> {fa_number(fail_count)} نفر\n"
        f"📊 <b>مجموع جامعه هدف:</b> {fa_number(len(user_ids))} نفر"
    )

    try:
        await status_msg.edit_text(report)
    except Exception:
        await call.message.answer(report)

    # ثبت در گروه لاگ اصلی
    admin_name = call.from_user.full_name or str(call.from_user.id)
    log_report = (
        f"📢 <b>گزارش ارسال پیام همگانی</b>\n"
        f"ارسال‌کننده: {admin_name} (<code>{call.from_user.id}</code>)\n\n"
        f"{report}"
    )
    await send_to_admin_group(bot, AdminGroupType.MAIN_LOG, log_report)


# ============================================================
#  تنظیم لینک فولدر بازی (/setfolder)
# ============================================================

@router.message(Command("setfolder"))
async def cmd_setfolder(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """تنظیم یا تغییر لینک فولدر رسمی کانال‌های بازی."""
    if not _is_admin(message.from_user.id):
        return

    text = message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) >= 2:
        new_link = parts[1].strip()
        await bot_state_repo.update_state(session, game_folder_link=new_link)
        await session.commit()
        await message.answer(
            f"✅ <b>لینک فولدر کانال‌های بازی با موفقیت به‌روزرسانی شد:</b>\n\n"
            f"🔗 {new_link}\n\n"
            "از هم‌اکنون تمام کاربران با دستور /folder این لینک را مشاهده خواهند کرد."
        )
        return

    await state.clear()
    await state.set_state(SetFolderForm.waiting_for_link)
    bstate = await bot_state_repo.get_state(session)
    curr = bstate.game_folder_link or "تنظیم نشده"
    await message.answer(
        f"📁 <b>تنظیم لینک فولدر رسمی بازی</b>\n\n"
        f"لینک فعلی: <code>{curr}</code>\n\n"
        "لطفاً لینک جدید فولدر تلگرام (مانند <code>https://t.me/addlist/...</code>) را ارسال کنید:"
    )


@router.message(SetFolderForm.waiting_for_link, F.text)
async def msg_setfolder_link(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """دریافت و ذخیره لینک فولدر در دیتابیس."""
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    new_link = message.text.strip()
    await bot_state_repo.update_state(session, game_folder_link=new_link)
    await session.commit()
    await state.clear()

    await message.answer(
        f"✅ <b>لینک فولدر کانال‌های بازی با موفقیت به‌روزرسانی شد:</b>\n\n"
        f"🔗 {new_link}\n\n"
        "از هم‌اکنون تمام کاربران با دستور /folder این لینک را دریافت می‌کنند."
    )


# ============================================================
#  تنظیم جوین اجباری در کانال رسمی (/setchannel)
# ============================================================

def _channel_settings_kb(enabled: bool) -> InlineKeyboardMarkup:
    toggle_text = "🔴 غیرفعال‌سازی جوین اجباری" if enabled else "🟢 فعال‌سازی جوین اجباری"
    toggle_style = STYLE_NO if enabled else STYLE_OK
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle_text, callback_data="setchan:toggle", style=toggle_style)],
            [
                InlineKeyboardButton(text="✏️ تغییر آیدی/یوزرنیم کانال", callback_data="setchan:chat_id", style=STYLE_MAIN),
                InlineKeyboardButton(text="🔗 تغییر لینک دعوت", callback_data="setchan:link", style=STYLE_MAIN),
            ],
            [InlineKeyboardButton(text="🔙 بستن", callback_data="setchan:close", style=STYLE_MAIN)],
        ]
    )


@router.message(Command("setchannel"))
async def cmd_setchannel(
    message: Message, session: AsyncSession
) -> None:
    """مشاهده و مدیریت تنظیمات جوین اجباری کانال."""
    if not _is_admin(message.from_user.id):
        return

    bstate = await bot_state_repo.get_state(session)
    status_text = "🟢 فعال" if bstate.force_join_enabled else "🔴 غیرفعال"
    chat_id_text = bstate.force_join_chat_id or "تنظیم نشده"
    link_text = bstate.force_join_invite_link or "تنظیم نشده"

    text = (
        header("مدیریت سیستم عضویت اجباری کانال", "📢")
        + f"\n\n<b>وضعیت فعلی:</b> {status_text}\n"
        f"<b>شناسه یا @یوزرنیم کانال:</b> <code>{chat_id_text}</code>\n"
        f"<b>لینک ورود به کانال:</b> {link_text}\n\n"
        "جهت تغییر تنظیمات از کلیدهای زیر استفاده کنید:"
    )
    await message.answer(text, reply_markup=_channel_settings_kb(bstate.force_join_enabled))


@router.callback_query(F.data == "setchan:close")
async def cb_channel_close(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    await state.clear()
    await call.message.delete()


@router.callback_query(F.data == "setchan:toggle")
async def cb_channel_toggle(call: CallbackQuery, session: AsyncSession) -> None:
    """تغییر وضعیت فعال/غیرفعال جوین اجباری."""
    if not _is_admin(call.from_user.id):
        return

    bstate = await bot_state_repo.get_state(session)
    new_status = not bstate.force_join_enabled
    await bot_state_repo.update_state(session, force_join_enabled=new_status)
    await session.commit()

    await call.answer("وضعیت جوین اجباری تغییر یافت")
    status_text = "🟢 فعال" if new_status else "🔴 غیرفعال"
    chat_id_text = bstate.force_join_chat_id or "تنظیم نشده"
    link_text = bstate.force_join_invite_link or "تنظیم نشده"

    text = (
        header("مدیریت سیستم عضویت اجباری کانال", "📢")
        + f"\n\n<b>وضعیت فعلی:</b> {status_text}\n"
        f"<b>شناسه یا @یوزرنیم کانال:</b> <code>{chat_id_text}</code>\n"
        f"<b>لینک ورود به کانال:</b> {link_text}\n\n"
        "جهت تغییر تنظیمات از کلیدهای زیر استفاده کنید:"
    )
    await call.message.edit_text(text, reply_markup=_channel_settings_kb(new_status))


@router.callback_query(F.data == "setchan:chat_id")
async def cb_channel_set_chat_id(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    await state.set_state(SetChannelForm.waiting_for_chat_id)
    await call.message.answer(
        "📢 لطفاً آیدی عددی کانال (مثلاً <code>-1001234567890</code>) یا یوزرنیم کانال "
        "(مثلاً <code>@my_channel</code>) را ارسال کنید:\n\n"
        "<i>نکته: ربات باید در کانال ادمین باشد تا بتواند عضویت کاربران را بررسی کند.</i>"
    )


@router.message(SetChannelForm.waiting_for_chat_id, F.text)
async def msg_channel_chat_id(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    chat_id = message.text.strip()
    await bot_state_repo.update_state(session, force_join_chat_id=chat_id)
    await session.commit()
    await state.clear()

    await message.answer(
        f"✅ <b>شناسه کانال هدف ثبت شد:</b> <code>{chat_id}</code>\n\n"
        "جهت مدیریت کامل از دستور /setchannel استفاده کنید."
    )


@router.callback_query(F.data == "setchan:link")
async def cb_channel_set_link(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    await state.set_state(SetChannelForm.waiting_for_invite_link)
    await call.message.answer(
        "🔗 لطفاً لینک ورود/عضویت کانال (مثلاً <code>https://t.me/...</code>) را ارسال کنید:"
    )


@router.message(SetChannelForm.waiting_for_invite_link, F.text)
async def msg_channel_invite_link(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    invite_link = message.text.strip()
    await bot_state_repo.update_state(session, force_join_invite_link=invite_link)
    await session.commit()
    await state.clear()

    await message.answer(
        f"✅ <b>لینک ورود به کانال با موفقیت ثبت شد:</b>\n{invite_link}\n\n"
        "جهت مدیریت کامل از دستور /setchannel استفاده کنید."
    )
