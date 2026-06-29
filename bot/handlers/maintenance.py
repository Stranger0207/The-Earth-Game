"""
هندلر پنل خاموش/روشن ربات (v1.10.5) — فقط مالک.

کامند /botpower پنلی می‌دهد که با آن می‌توان:
- ربات را به‌صورت فوری خاموش/روشن کرد (پلیرهای عادی نمی‌توانند کاری انجام دهند).
- یک بازه‌ی خاموشی روزانه‌ی تکرارشونده به وقت تهران تنظیم/غیرفعال کرد.
"""

from __future__ import annotations

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
from ..services.news_service import send_log
from ..states import MaintenanceForm
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK, header

router = Router(name="maintenance")
settings = get_settings()


def _is_owner(user_id: int) -> bool:
    return settings.is_owner(user_id)


def _status_text(state) -> str:
    """متن وضعیت فعلی ربات."""
    if state.maintenance:
        power = "🔴 خاموش (دستی)"
    else:
        power = "🟢 روشن"
    if state.auto_off_enabled and state.auto_off_start and state.auto_off_end:
        window = f"⏰ بازه‌ی روزانه: {state.auto_off_start} تا {state.auto_off_end} (وقت تهران)"
    else:
        window = "⏰ بازه‌ی روزانه: غیرفعال"
    return (
        header("کنترل روشن/خاموش ربات", "🔌")
        + f"\n\nوضعیت: {power}\n{window}\n\n"
        "در حالت خاموش، پلیرها نمی‌توانند هیچ اقدامی انجام دهند (مالک/مدیر معاف‌اند)."
    )


def _panel_kb(state) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if state.maintenance:
        rows.append([InlineKeyboardButton(text="🟢 روشن‌کردن ربات", callback_data="botpw:on", style=STYLE_OK)])
    else:
        rows.append([InlineKeyboardButton(text="🔴 خاموشی فوری", callback_data="botpw:off", style=STYLE_NO)])
    rows.append([InlineKeyboardButton(text="⏰ تنظیم بازه‌ی روزانه", callback_data="botpw:setwin", style=STYLE_MAIN)])
    if state.auto_off_enabled:
        rows.append([InlineKeyboardButton(text="❌ غیرفعال‌کردن بازه", callback_data="botpw:clearwin", style=STYLE_NO)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("botpower"))
async def cmd_botpower(message: Message, session: AsyncSession) -> None:
    """پنل کنترل روشن/خاموش ربات (فقط مالک)."""
    if not _is_owner(message.from_user.id):
        return
    state = await bot_state_repo.get_state(session)
    await message.answer(_status_text(state), reply_markup=_panel_kb(state))


@router.callback_query(F.data == "botpw:off")
async def cb_power_off(call: CallbackQuery, session: AsyncSession) -> None:
    """خاموشی فوری دستی."""
    if not _is_owner(call.from_user.id):
        await call.answer("فقط مالک.", show_alert=True)
        return
    state = await bot_state_repo.update_state(session, maintenance=True)
    await call.answer("ربات خاموش شد ✅")
    await call.message.edit_text(_status_text(state), reply_markup=_panel_kb(state))
    await send_log(call.bot, "🔴 <b>ربات به‌صورت دستی خاموش شد</b> (مالک).")


@router.callback_query(F.data == "botpw:on")
async def cb_power_on(call: CallbackQuery, session: AsyncSession) -> None:
    """روشن‌کردن دوباره‌ی ربات."""
    if not _is_owner(call.from_user.id):
        await call.answer("فقط مالک.", show_alert=True)
        return
    state = await bot_state_repo.update_state(session, maintenance=False)
    await call.answer("ربات روشن شد ✅")
    await call.message.edit_text(_status_text(state), reply_markup=_panel_kb(state))
    await send_log(call.bot, "🟢 <b>ربات دوباره روشن شد</b> (مالک).")


@router.callback_query(F.data == "botpw:clearwin")
async def cb_clear_window(call: CallbackQuery, session: AsyncSession) -> None:
    """غیرفعال‌کردن بازه‌ی خاموشی روزانه."""
    if not _is_owner(call.from_user.id):
        await call.answer("فقط مالک.", show_alert=True)
        return
    state = await bot_state_repo.update_state(session, auto_off_enabled=False)
    await call.answer("بازه‌ی روزانه غیرفعال شد ✅")
    await call.message.edit_text(_status_text(state), reply_markup=_panel_kb(state))
    await send_log(call.bot, "⏰ <b>بازه‌ی خاموشی روزانه غیرفعال شد</b> (مالک).")


@router.callback_query(F.data == "botpw:setwin")
async def cb_set_window(call: CallbackQuery, state: FSMContext) -> None:
    """درخواست ورود بازه‌ی روزانه."""
    if not _is_owner(call.from_user.id):
        await call.answer("فقط مالک.", show_alert=True)
        return
    await call.answer()
    await state.set_state(MaintenanceForm.entering_window)
    await call.message.edit_text(
        "⏰ بازه‌ی خاموشی روزانه را به وقت <b>تهران</b> وارد کنید (شروع و پایان):\n\n"
        "مثال: <code>02:00 08:00</code>\n"
        "برای بازه‌ای که از نیمه‌شب عبور می‌کند هم پشتیبانی می‌شود (مثلاً <code>23:00 06:00</code>)."
    )


def _valid_hhmm(value: str) -> bool:
    try:
        h, m = value.split(":")
        return 0 <= int(h) <= 23 and 0 <= int(m) <= 59
    except (ValueError, AttributeError):
        return False


@router.message(MaintenanceForm.entering_window, F.text)
async def msg_set_window(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """ثبت بازه‌ی روزانه."""
    if not _is_owner(message.from_user.id):
        await state.clear()
        return
    parts = message.text.strip().replace("،", " ").split()
    if len(parts) != 2 or not _valid_hhmm(parts[0]) or not _valid_hhmm(parts[1]):
        await message.answer(
            "⛔️ فرمت نامعتبر است. دو ساعت به‌صورت <code>HH:MM HH:MM</code> وارد کنید. مثال: <code>02:00 08:00</code>"
        )
        return
    start_s, end_s = parts
    await state.clear()
    new_state = await bot_state_repo.update_state(
        session, auto_off_enabled=True, auto_off_start=start_s, auto_off_end=end_s
    )
    await message.answer(_status_text(new_state), reply_markup=_panel_kb(new_state))
    await send_log(
        message.bot,
        f"⏰ <b>بازه‌ی خاموشی روزانه تنظیم شد</b>: {start_s} تا {end_s} (وقت تهران) — مالک.",
    )
