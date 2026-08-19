"""
هندلر پنل خاموش/روشن ربات (v1.10.5) — فقط مالک.

کامند /botpower پنلی می‌دهد که با آن می‌توان:
- ربات را به‌صورت فوری خاموش/روشن کرد (پلیرهای عادی نمی‌توانند کاری انجام دهند).
- یک بازه‌ی خاموشی روزانه‌ی تکرارشونده به وقت تهران تنظیم/غیرفعال کرد.

کامند /freeze (v2.1) — تعلیق پلیرها:
- «انجماد سراسری»: همه‌ی صاحبان کشور معلق می‌شوند و نمی‌توانند کاری کنند، ولی
  کاربران بدون کشور هم‌چنان می‌توانند /claim بزنند و به‌محض تأیید، خودکار معلق
  می‌شوند تا مالک دکمه‌ی رفع تعلیق را بزند.
- تعلیق/رفع تعلیق یک کشور خاص.
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
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database.repositories import bot_state as bot_state_repo
from ..database.repositories import countries as countries_repo
from ..database.repositories import users as users_repo
from ..loader import bot
from ..services.news_service import send_log
from ..states import MaintenanceForm
from ..utils.numbers import fa_number
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


# ---------------------------------------------------------------------------
# /killall — لغو فوری تمام عملیات‌های فعال (حملات + ماهواره‌ها) — فقط مالک
# ---------------------------------------------------------------------------

@router.message(Command("killall"))
async def cmd_killall(message: Message, session: AsyncSession) -> None:
    """لغو فوری تمام حملات در حال اجرا و ماهواره‌های در حال پرتاب (فقط مالک)."""
    if not _is_owner(message.from_user.id):
        return

    from sqlalchemy import select, update

    from ..database.models import Battle
    from ..database.models.satellite import Satellite

    # ۱. لغو تمام نبردهای فعال (pending_owner + in_progress)
    battle_result = await session.execute(
        select(Battle).where(Battle.status.in_(["pending_owner", "in_progress"]))
    )
    active_battles = list(battle_result.scalars().all())
    killed_battles = len(active_battles)
    for b in active_battles:
        b.status = "rejected"

    # ۲. لغو تمام ماهواره‌های در حال پرتاب
    sat_result = await session.execute(
        select(Satellite).where(Satellite.status == "launching")
    )
    active_sats = list(sat_result.scalars().all())
    killed_sats = len(active_sats)
    for s in active_sats:
        s.status = "failed"

    await session.commit()

    # گزارش به مالک
    if killed_battles == 0 and killed_sats == 0:
        await message.answer(
            "✅ هیچ عملیات فعالی وجود نداشت. همه‌چیز آرام است!"
        )
        return

    report = (
        "🛑 <b>تمام عملیات‌های فعال لغو شدند!</b>\n\n"
        f"⚔️ نبردهای لغو‌شده: <b>{killed_battles}</b>\n"
        f"📡 ماهواره‌های لغو‌شده: <b>{killed_sats}</b>\n\n"
        "دیگر هیچ خبری از این عملیات‌ها منتشر نخواهد شد."
    )
    await message.answer(report)
    await send_log(message.bot, report + "\n\n👤 <b>توسط مالک بازی</b>")


# ---------------------------------------------------------------------------
# /freeze — تعلیق پلیرها (v2.1) — فقط مالک
# ---------------------------------------------------------------------------
#
# تفاوت با /botpower: خاموشی ربات موقت و سراسری است و هیچ‌کس (حتی کشورگیر جدید)
# نمی‌تواند کاری کند. انجماد اما هدفش «نگه‌داشتن بازی» است: پلیرهای فعلی
# نمی‌توانند اقدامی کنند ولی کشورگیری باز است و تازه‌واردها هم معلق می‌مانند تا
# مالک بازی را رسماً شروع کند.


async def _owner_users(session: AsyncSession) -> list:
    """کاربرانی که مالک یک کشورند (مالک/مدیر بازی مستثنا)."""
    countries = await countries_repo.list_countries(session)
    out = []
    for country in countries:
        uid = country.owner_user_id
        if not uid or settings.is_admin(uid):
            continue
        user = await users_repo.get_user(session, uid)
        if user is not None:
            out.append((country, user))
    return out


async def _freeze_status_text(session: AsyncSession) -> str:
    """متن وضعیت انجماد + شمارش پلیرهای معلق."""
    state = await bot_state_repo.get_state(session)
    pairs = await _owner_users(session)
    suspended = [1 for _, user in pairs if getattr(user, "is_suspended", False)]

    status = "🔴 منجمد (سراسری)" if getattr(state, "global_freeze", False) else "🟢 فعال"
    return (
        header("تعلیق پلیرها", "❄️")
        + f"\n\n❄️ وضعیت: <b>{status}</b>\n"
        f"👥 معلق: <b>{fa_number(len(suspended))}</b> از {fa_number(len(pairs))} پلیر\n\n"
        "<i>در حالت منجمد، پلیرها نمی‌توانند اقدامی انجام دهند ولی کشورگیری باز "
        "می‌ماند؛ هر کشورگیریِ تأییدشده هم خودکار معلق می‌شود تا خودتان رفع تعلیق کنید. "
        "مالک و مدیران بازی معاف‌اند.</i>"
    )


async def _freeze_panel_kb(session: AsyncSession) -> InlineKeyboardMarkup:
    state = await bot_state_repo.get_state(session)
    builder = InlineKeyboardBuilder()
    if getattr(state, "global_freeze", False):
        builder.button(text="🟢 رفع انجماد همه", callback_data="frz:unfreeze_all", style=STYLE_OK)
    else:
        builder.button(text="❄️ انجماد همه", callback_data="frz:freeze_all", style=STYLE_NO)
    builder.button(text="⏸ تعلیق یک کشور", callback_data="frz:suspend", style=STYLE_NO)
    builder.button(text="▶️ رفع تعلیق یک کشور", callback_data="frz:unsuspend", style=STYLE_OK)
    builder.button(text="📋 فهرست معلق‌ها", callback_data="frz:list", style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


async def _show_freeze_panel(target: Message | CallbackQuery, session: AsyncSession) -> None:
    """نمایش/به‌روزرسانی پنل انجماد."""
    text = await _freeze_status_text(session)
    kb = await _freeze_panel_kb(session)
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.message(Command("freeze"))
async def cmd_freeze(message: Message, session: AsyncSession) -> None:
    """پنل تعلیق پلیرها (فقط مالک)."""
    if not _is_owner(message.from_user.id):
        return
    await _show_freeze_panel(message, session)


@router.callback_query(F.data == "frz:panel")
async def cb_freeze_panel(call: CallbackQuery, session: AsyncSession) -> None:
    """بازگشت به پنل انجماد."""
    if not _is_owner(call.from_user.id):
        await call.answer("فقط مالک.", show_alert=True)
        return
    await call.answer()
    await _show_freeze_panel(call, session)


@router.callback_query(F.data == "frz:freeze_all")
async def cb_freeze_all(call: CallbackQuery, session: AsyncSession) -> None:
    """انجماد سراسری: تعلیق همه‌ی صاحبان کشور."""
    if not _is_owner(call.from_user.id):
        await call.answer("فقط مالک.", show_alert=True)
        return

    await bot_state_repo.update_state(session, global_freeze=True)
    pairs = await _owner_users(session)
    frozen = 0
    for _, user in pairs:
        if not getattr(user, "is_suspended", False):
            user.is_suspended = True
            frozen += 1
    await session.commit()

    await call.answer(f"{frozen} پلیر معلق شد ❄️", show_alert=True)
    await _show_freeze_panel(call, session)
    await send_log(
        bot,
        f"❄️ <b>انجماد سراسری بازی</b>\nپلیرهای معلق‌شده: {fa_number(frozen)}\n"
        "کشورگیری باز است؛ کشورگیرهای جدید خودکار معلق می‌شوند.\n👤 توسط مالک",
    )

    # اطلاع به پلیرها تا فکر نکنند ربات خراب شده است
    for country, user in pairs:
        try:
            await bot.send_message(
                user.telegram_id,
                "⏸ <b>بازی موقتاً معلق شد.</b>\n\n"
                "تا اطلاع ثانوی نمی‌توانید اقدامی انجام دهید. "
                "به‌محض رفع تعلیق توسط مدیریت، خبر می‌دهیم.",
            )
        except Exception:  # noqa: BLE001
            continue


@router.callback_query(F.data == "frz:unfreeze_all")
async def cb_unfreeze_all(call: CallbackQuery, session: AsyncSession) -> None:
    """رفع انجماد سراسری: رفع تعلیق همه‌ی پلیرها."""
    if not _is_owner(call.from_user.id):
        await call.answer("فقط مالک.", show_alert=True)
        return

    await bot_state_repo.update_state(session, global_freeze=False)
    pairs = await _owner_users(session)
    released = 0
    for _, user in pairs:
        if getattr(user, "is_suspended", False):
            user.is_suspended = False
            released += 1
    await session.commit()

    await call.answer(f"تعلیق {released} پلیر برداشته شد ▶️", show_alert=True)
    await _show_freeze_panel(call, session)
    await send_log(
        bot,
        f"🟢 <b>رفع انجماد سراسری</b>\nپلیرهای آزادشده: {fa_number(released)}\n👤 توسط مالک",
    )

    for country, user in pairs:
        try:
            await bot.send_message(
                user.telegram_id,
                "▶️ <b>تعلیق برداشته شد؛ بازی از سر گرفته شد!</b>\n\n"
                f"اکنون می‌توانید {country.flag} {country.name_fa} را مدیریت کنید. /start",
            )
        except Exception:  # noqa: BLE001
            continue


def _freeze_countries_kb(pairs: list, prefix: str) -> InlineKeyboardMarkup:
    """کیبورد انتخاب کشور برای تعلیق/رفع تعلیق."""
    builder = InlineKeyboardBuilder()
    for country, user in pairs:
        mark = "⏸" if getattr(user, "is_suspended", False) else "🟢"
        builder.button(
            text=f"{mark} {country.flag} {country.name_fa}",
            callback_data=f"{prefix}:{country.id}",
            style=STYLE_MAIN,
        )
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="frz:panel", style=STYLE_MAIN)
    )
    return builder.as_markup()


@router.callback_query(F.data == "frz:suspend")
async def cb_pick_suspend(call: CallbackQuery, session: AsyncSession) -> None:
    """انتخاب کشور برای تعلیق."""
    if not _is_owner(call.from_user.id):
        await call.answer("فقط مالک.", show_alert=True)
        return
    await call.answer()
    pairs = [p for p in await _owner_users(session) if not getattr(p[1], "is_suspended", False)]
    if not pairs:
        await call.message.edit_text(
            "همه‌ی پلیرها از قبل معلق‌اند.", reply_markup=await _freeze_panel_kb(session)
        )
        return
    await call.message.edit_text(
        "⏸ کدام کشور معلق شود؟", reply_markup=_freeze_countries_kb(pairs, "frz_sp")
    )


@router.callback_query(F.data == "frz:unsuspend")
async def cb_pick_unsuspend(call: CallbackQuery, session: AsyncSession) -> None:
    """انتخاب کشور برای رفع تعلیق."""
    if not _is_owner(call.from_user.id):
        await call.answer("فقط مالک.", show_alert=True)
        return
    await call.answer()
    pairs = [p for p in await _owner_users(session) if getattr(p[1], "is_suspended", False)]
    if not pairs:
        await call.message.edit_text(
            "هیچ پلیر معلقی وجود ندارد.", reply_markup=await _freeze_panel_kb(session)
        )
        return
    await call.message.edit_text(
        "▶️ تعلیق کدام کشور برداشته شود؟",
        reply_markup=_freeze_countries_kb(pairs, "frz_un"),
    )


async def _set_suspended(
    call: CallbackQuery, session: AsyncSession, cid: int, suspended: bool
) -> None:
    """تعلیق/رفع تعلیق مالک یک کشور + اطلاع و لاگ."""
    country = await countries_repo.get_country(session, cid)
    if country is None or country.owner_user_id is None:
        await call.answer("این کشور مالک ندارد.", show_alert=True)
        return

    await users_repo.set_suspended(session, country.owner_user_id, suspended)
    await session.commit()
    await call.answer("معلق شد ⏸" if suspended else "تعلیق برداشته شد ▶️", show_alert=True)

    msg = (
        "⏸ کشور شما توسط مدیریت بازی معلق شد و فعلاً نمی‌توانید اقدامی انجام دهید."
        if suspended
        else "▶️ تعلیق کشور شما برداشته شد؛ اکنون می‌توانید دوباره فعالیت کنید. /start"
    )
    try:
        await bot.send_message(country.owner_user_id, msg)
    except Exception:  # noqa: BLE001
        pass

    await send_log(
        bot,
        f"{'⏸' if suspended else '▶️'} <b>{'تعلیق' if suspended else 'رفع تعلیق'} پلیر</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n👤 توسط مالک",
    )
    await _show_freeze_panel(call, session)


@router.callback_query(F.data.startswith("frz_sp:"))
async def cb_do_suspend(call: CallbackQuery, session: AsyncSession) -> None:
    """تعلیق یک کشور."""
    if not _is_owner(call.from_user.id):
        await call.answer("فقط مالک.", show_alert=True)
        return
    await _set_suspended(call, session, int(call.data.split(":")[1]), True)


@router.callback_query(F.data.startswith("frz_un:"))
async def cb_do_unsuspend(call: CallbackQuery, session: AsyncSession) -> None:
    """رفع تعلیق یک کشور."""
    if not _is_owner(call.from_user.id):
        await call.answer("فقط مالک.", show_alert=True)
        return
    await _set_suspended(call, session, int(call.data.split(":")[1]), False)


@router.callback_query(F.data == "frz:list")
async def cb_freeze_list(call: CallbackQuery, session: AsyncSession) -> None:
    """فهرست پلیرهای معلق."""
    if not _is_owner(call.from_user.id):
        await call.answer("فقط مالک.", show_alert=True)
        return
    await call.answer()

    pairs = await _owner_users(session)
    suspended = [(c, u) for c, u in pairs if getattr(u, "is_suspended", False)]

    lines = [header("پلیرهای معلق", "📋"), ""]
    if not suspended:
        lines.append("🟢 هیچ پلیری معلق نیست.")
    else:
        for country, user in suspended:
            uname = (f"@{user.username}" if user.username else user.first_name) or "—"
            lines.append(f"⏸ {country.flag} <b>{country.name_fa}</b> — {uname}")
        lines.append(f"\nمجموع: {fa_number(len(suspended))} پلیر")

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="frz:panel", style=STYLE_MAIN)
    ]])
    await call.message.edit_text("\n".join(lines), reply_markup=kb)

