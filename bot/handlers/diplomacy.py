"""
هندلر بخش دیپلماسی: نامه، تماس تلفنی، دیدار حضوری، قرارداد و تحریم.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import (
    FLIGHT_DURATION_MINUTES,
    MEETING_COOLDOWN_HOURS,
    MEETING_DURATION_MINUTES,
    MEETING_IDLE_TIMEOUT_MINUTES,
    PHONE_CALL_COOLDOWN_MINUTES,
    PHONE_CALL_DURATION_MINUTES,
    SPEECH_COOLDOWN_MINUTES,
    VISA_WAIVER_ADMIN_COST,
    VISA_WAIVER_SATISFACTION_PENALTY,
    VISA_WAIVER_STABILITY_PENALTY,
)
from ..database.models import (
    Contract,
    ContractSignatory,
    GroupMeeting,
    Meeting,
    PhoneCall,
    Sanction,
    Speech,
    User,
    VisaWaiver,
)
from ..database.repositories import cooldowns as cd_repo
from ..database.repositories import countries as countries_repo
from ..database.repositories import diplomacy as dip_repo
from ..database.repositories import governance as gov_repo
from ..enums import AdminGroupType, SANCTION_FA, DiplomacyStatus, NewsCategory, SanctionType
from ..keyboards.common import countries_kb
from ..keyboards.diplomacy import (
    diplomacy_menu_kb,
    end_call_kb,
    end_meeting_kb,
    sanction_menu_kb,
    sanction_types_kb,
)
from ..loader import bot
from ..services import geo_service as geo
from ..services.letter_image_service import render_contract_image
from ..services.media import send_photo_news, send_specific_photo
from ..services.news_service import (
    get_admin_group_id,
    publish_news,
    send_log,
    send_log_photo,
    send_to_admin_group,
)
from ..services.sanction_service import apply_sanction_effects
from ..database.repositories import users as users_repo
from ..states import CallForm, ContractForm, MeetingForm, SanctionForm, SpeechForm
from ..utils.numbers import fa_number
from ..utils.screens import safe_edit
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK, header
from .deps import NO_COUNTRY_TEXT, assert_feature, get_player_country

logger = logging.getLogger(__name__)
settings = get_settings()
# نام کاربری ربات برای ساخت deep-link نقل قول (یک‌بار کش می‌شود)
_bot_username: str | None = None


async def _get_bot_username() -> str:
    """نام کاربری ربات را یک‌بار می‌گیرد و کش می‌کند."""
    global _bot_username
    if _bot_username is None:
        me = await bot.get_me()
        _bot_username = me.username
    return _bot_username

async def _president_name(session: AsyncSession, country) -> str:
    """نام رئیس‌جمهور یک کشور (در صورت نبود، نام کشور)."""
    if country is None:
        return "—"
    if country.owner_user_id:
        u = await users_repo.get_user(session, country.owner_user_id)
        if u and u.president_name:
            return u.president_name
    return country.name_fa


router = Router(name="diplomacy")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _back_kb(callback_data: str) -> InlineKeyboardMarkup:
    """کیبورد تک‌دکمه‌ای بازگشت به مرحله‌ی قبل (v1.8)."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=callback_data, style=STYLE_MAIN)
    ]])


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _other_countries(session: AsyncSession, country_id: int):
    """فهرست کشورهای دیگر (به‌جز خودِ کشور بازیکن)."""
    countries = await countries_repo.list_countries(session)
    return [c for c in countries if c.id != country_id]


# ============================================================
#  ⛔ سیستم انحصار نشست‌ها (v1.10)
#  یک کشور هم‌زمان فقط می‌تواند در یک نشست/تماس فعال باشد. برای شروع یا پذیرش
#  هر تماس/دیدار/نشست جدید، نباید نشست فعالِ دیگری داشته باشد.
# ============================================================
async def _busy_block_cb(
    call: CallbackQuery, session: AsyncSession, country_id: int, *, is_self: bool = True
) -> bool:
    """
    اگر کشور موردنظر نشست/تماس فعالی داشته باشد، به کاربرِ دکمه‌زننده هشدار می‌دهد و
    True برمی‌گرداند (یعنی باید عملیات متوقف شود). is_self مشخص می‌کند مشغول‌بودن مربوط
    به خودِ کاربر است یا طرف مقابل (برای متن مناسب).
    """
    label = await dip_repo.get_active_engagement_label(session, country_id)
    if label is None:
        return False
    if is_self:
        text = (
            f"⛔ شما هم‌اکنون {label} دارید.\n"
            "ابتدا نشست فعلی را پایان دهید، سپس دوباره تلاش کنید."
        )
    else:
        text = (
            f"⛔ طرف مقابل هم‌اکنون {label} دارد.\n"
            "تا پایان نشست فعلی او امکان شروع نشست جدید نیست."
        )
    await call.answer(text, show_alert=True)
    return True


# ------------------------- کول‌داون کنش‌ها (v1.9) -------------------------
async def _cooldown_remaining_min(
    session: AsyncSession, country_id: int, action: str, hours: float
) -> int:
    """دقیقه‌ی باقی‌مانده تا پایان کول‌داون یک کنش (رند به بالا)."""
    secs = await cd_repo.remaining_seconds(session, country_id, action, hours)
    return int((secs + 59) // 60)


def _cooldown_text(label: str, every_fa: str, mins: int) -> str:
    return (
        f"⏳ {label} هر {every_fa} یک‌بار امکان‌پذیر است.\n"
        f"حدود {fa_number(mins)} دقیقه‌ی دیگر دوباره تلاش کنید."
    )


# ============================================================
#  ✉️ نامه — به handlers/mail.py منتقل شد (v1.9): به یک/چند کشور + صندوق پستی
# ============================================================


# ============================================================
#  📞 تماس تلفنی (حداکثر ۱۰ دقیقه، بدون قرارداد)
# ============================================================
@router.callback_query(F.data == "dip:call")
async def cb_call(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call,NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "dip.call"):
        return
    # کول‌داون تماس: هر ۳۰ دقیقه ۱ تماس (v1.9)
    mins = await _cooldown_remaining_min(
        session, country.id, "phone_call", PHONE_CALL_COOLDOWN_MINUTES / 60
    )
    if mins > 0:
        await safe_edit(call,
            _cooldown_text("تماس تلفنی", f"{fa_number(PHONE_CALL_COOLDOWN_MINUTES)} دقیقه", mins),
            reply_markup=diplomacy_menu_kb(),
        )
        return
    await state.set_state(CallForm.choosing_target)
    others = await _other_countries(session, country.id)
    await safe_edit(call,
        "📞 با کدام کشور می‌خواهید تماس بگیرید؟",
        reply_markup=countries_kb(others, prefix="call_to", columns=2, back_data="menu:diplomacy"),
    )


@router.callback_query(CallForm.choosing_target, F.data.startswith("call_to:"))
async def cb_call_to(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    await state.clear()
    country = await get_player_country(session, db_user)
    target = await countries_repo.get_country(session, int(call.data.split(":")[1]))
    if country is None or target is None or target.owner_user_id is None:
        await safe_edit(call,"امکان تماس با این کشور وجود ندارد (بدون رهبر).")
        return

    # سیستم انحصار: تا وقتی نشست/تماس فعالی داری نمی‌توانی تماس جدید آغاز کنی (v1.10)
    label = await dip_repo.get_active_engagement_label(session, country.id)
    if label is not None:
        await safe_edit(call,
            f"⛔ شما هم‌اکنون {label} دارید.\n"
            "ابتدا نشست فعلی را پایان دهید، سپس دوباره برای تماس اقدام کنید.",
            reply_markup=diplomacy_menu_kb(),
        )
        return

    # (v1.10.1) اگر طرف مقابل در نشست/تماس/پرواز باشد، اصلاً نمی‌توان برایش درخواست فرستاد
    target_label = await dip_repo.get_active_engagement_label(session, target.id)
    if target_label is not None:
        await safe_edit(call,
            f"⛔ کشور {target.flag} {target.name_fa} هم‌اکنون {target_label} دارد.\n"
            "تا پایان آن نمی‌توانید با این کشور تماس بگیرید.",
            reply_markup=diplomacy_menu_kb(),
        )
        return

    # کول‌داون تماس: هر ۳۰ دقیقه ۱ تماس (v1.9)
    mins = await _cooldown_remaining_min(
        session, country.id, "phone_call", PHONE_CALL_COOLDOWN_MINUTES / 60
    )
    if mins > 0:
        await safe_edit(call,
            _cooldown_text("تماس تلفنی", f"{fa_number(PHONE_CALL_COOLDOWN_MINUTES)} دقیقه", mins),
            reply_markup=diplomacy_menu_kb(),
        )
        return

    phone_call = PhoneCall(
        caller_country=country.id,
        callee_country=target.id,
        status=DiplomacyStatus.PENDING,
    )
    await dip_repo.add_call(session, phone_call)
    await session.flush()
    # ثبت کول‌داون تماس برای تماس‌گیرنده
    await cd_repo.touch(session, country.id, "phone_call")

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ پاسخ", callback_data=f"call_accept:{phone_call.id}", style=STYLE_OK),
        InlineKeyboardButton(text="❌ رد", callback_data=f"call_reject:{phone_call.id}", style=STYLE_NO),
    ]])
    try:
        await bot.send_message(
            target.owner_user_id,
            f"📞 <b>درخواست تماس تلفنی</b> از {country.flag} {country.name_fa}",
            reply_markup=kb,
        )
    except Exception:  # noqa: BLE001
        pass
    await safe_edit(call,"📞 درخواست تماس ارسال شد. منتظر پاسخ طرف مقابل بمانید.")


@router.callback_query(F.data.startswith("call_accept:"))
async def cb_call_accept(call: CallbackQuery, session: AsyncSession) -> None:
    call_id = int(call.data.split(":")[1])
    phone_call = await dip_repo.get_call(session, call_id)
    if phone_call is None or phone_call.status != DiplomacyStatus.PENDING:
        await call.answer("این تماس دیگر معتبر نیست.", show_alert=True)
        return
    # سیستم انحصار: نه پذیرنده و نه تماس‌گیرنده نباید نشست فعال دیگری داشته باشند (v1.10)
    if await _busy_block_cb(call, session, phone_call.callee_country, is_self=True):
        return
    if await _busy_block_cb(call, session, phone_call.caller_country, is_self=False):
        return
    phone_call.status = DiplomacyStatus.ACTIVE
    phone_call.started_at = _utcnow()
    phone_call.ends_at = _utcnow() + timedelta(minutes=PHONE_CALL_DURATION_MINUTES)
    await call.answer("تماس برقرار شد")

    caller = await countries_repo.get_country(session, phone_call.caller_country)
    callee = await countries_repo.get_country(session, phone_call.callee_country)
    note = (
        f"☎️ تماس برقرار شد (حداکثر {PHONE_CALL_DURATION_MINUTES} دقیقه).\n"
        "پیام‌های متنی شما به طرف مقابل ارسال می‌شود. برای پایان از دکمه‌ی زیر استفاده کنید.\n"
        "⚠️ در تماس تلفنی امکان عقد قرارداد وجود ندارد."
    )
    for c in (caller, callee):
        if c and c.owner_user_id:
            try:
                await bot.send_message(c.owner_user_id, note, reply_markup=end_call_kb())
            except Exception:  # noqa: BLE001
                pass
    await send_log(
        bot,
        f"📞 شروع تماس: {caller.name_fa if caller else '?'} ↔ {callee.name_fa if callee else '?'}",
    )


@router.callback_query(F.data.startswith("call_reject:"))
async def cb_call_reject(call: CallbackQuery, session: AsyncSession) -> None:
    call_id = int(call.data.split(":")[1])
    phone_call = await dip_repo.get_call(session, call_id)
    if phone_call is None or phone_call.status != DiplomacyStatus.PENDING:
        await call.answer()
        return
    phone_call.status = DiplomacyStatus.REJECTED
    await call.answer("رد شد")
    caller = await countries_repo.get_country(session, phone_call.caller_country)
    if caller and caller.owner_user_id:
        try:
            await bot.send_message(caller.owner_user_id, "❌ تماس شما رد شد.")
        except Exception:  # noqa: BLE001
            pass


@router.callback_query(F.data == "call:end")
async def cb_call_end(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    country = await get_player_country(session, db_user)
    if country is None:
        await call.answer()
        return
    active = await dip_repo.get_active_call_for_country(session, country.id)
    if active is None:
        await call.answer("تماس فعالی ندارید.")
        return
    active.status = DiplomacyStatus.COMPLETED
    await call.answer("تماس پایان یافت")
    caller = await countries_repo.get_country(session, active.caller_country)
    callee = await countries_repo.get_country(session, active.callee_country)
    for c in (caller, callee):
        if c and c.owner_user_id:
            try:
                await bot.send_message(c.owner_user_id, "📵 تماس پایان یافت.")
            except Exception:  # noqa: BLE001
                pass


# ============================================================
#  🔚 پایان نشست (دیدار دوجانبه/چندجانبه) — v1.8
# ============================================================
async def _end_all_engagements_for_country(session: AsyncSession, country) -> int:
    """
    همه‌ی نشست‌های دوجانبه/چندجانبه‌ای که این کشور در آن‌ها درگیر است (فعال یا در حال سفر/معلق)
    را می‌بندد و به اعضای درگیر اطلاع می‌دهد. تعداد نشست‌های بسته‌شده را برمی‌گرداند (v1.10.1).
    این تابع تضمین می‌کند کشور پس از کلیک «پایان نشست» هیچ نشست قفل‌کننده‌ای باقی نگذارد.
    """
    ended = 0

    # ۱) همه‌ی دیدارهای دوجانبه‌ی فعال/معلق این کشور
    for meeting in await dip_repo.list_recent_meetings_for_country(session, country.id, limit=20):
        if meeting.status not in (DiplomacyStatus.PENDING, DiplomacyStatus.ACTIVE):
            continue
        meeting.status = DiplomacyStatus.COMPLETED
        ended += 1
        traveler = await countries_repo.get_country(session, meeting.traveler_country)
        host = await countries_repo.get_country(session, meeting.host_country)
        for c in (traveler, host):
            if c and c.owner_user_id:
                try:
                    await bot.send_message(
                        c.owner_user_id,
                        f"🔚 نشست توسط {country.flag} {country.name_fa} پایان یافت.",
                    )
                except Exception:  # noqa: BLE001
                    pass

    # ۲) همه‌ی نشست‌های چندجانبه‌ی فعال/معلق این کشور (میزبان یا شرکت‌کننده)
    for group in await dip_repo.list_recent_group_meetings_for_country(session, country.id, limit=20):
        if group.status not in (DiplomacyStatus.PENDING, DiplomacyStatus.ACTIVE):
            continue
        group.status = DiplomacyStatus.COMPLETED
        ended += 1
        member_ids = await dip_repo.group_member_country_ids(session, group)
        for cid in member_ids:
            member = await countries_repo.get_country(session, cid)
            if member and member.owner_user_id:
                try:
                    await bot.send_message(
                        member.owner_user_id,
                        f"🔚 نشست «{group.title}» توسط {country.flag} {country.name_fa} پایان یافت.",
                    )
                except Exception:  # noqa: BLE001
                    pass

    return ended


@router.callback_query(F.data == "meeting:end")
async def cb_meeting_end(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """پایان دادن به نشست فعال توسط یکی از شرکت‌کنندگان (همه‌ی نشست‌های درگیر را می‌بندد)."""
    country = await get_player_country(session, db_user)
    if country is None:
        await call.answer()
        return
    ended = await _end_all_engagements_for_country(session, country)
    if ended:
        await call.answer("نشست پایان یافت ✅")
    else:
        await call.answer("نشست فعالی ندارید.", show_alert=True)


# ============================================================
#  🕘 نشست‌های اخیر (v1.10.1)
#  فهرست نشست‌های دوجانبه/چندجانبه‌ی اخیر کشور؛ نشست‌های فعال/معلق دکمه‌ی «پایان» دارند
#  تا کاربر مطمئن شود نشست بسته شده و از قفل‌ماندن خارج شود.
# ============================================================
_DIP_STATUS_FA = {
    DiplomacyStatus.PENDING: "⏳ در حال سفر/انتظار",
    DiplomacyStatus.ACTIVE: "🟢 فعال",
    DiplomacyStatus.COMPLETED: "✔️ پایان‌یافته",
    DiplomacyStatus.REJECTED: "❌ ردشده",
    DiplomacyStatus.CANCELLED: "🚫 لغوشده",
}


def _status_fa(status: str) -> str:
    try:
        return _DIP_STATUS_FA[DiplomacyStatus(status)]
    except (ValueError, KeyError):
        return status


async def _render_recent_meetings(call: CallbackQuery, session: AsyncSession, country) -> None:
    meetings = await dip_repo.list_recent_meetings_for_country(session, country.id, limit=8)
    groups = await dip_repo.list_recent_group_meetings_for_country(session, country.id, limit=8)

    lines = ["🕘 <b>نشست‌های اخیر شما</b>", ""]
    builder = InlineKeyboardBuilder()
    open_states = (DiplomacyStatus.PENDING, DiplomacyStatus.ACTIVE)

    if meetings:
        lines.append("🤝 <b>دوجانبه:</b>")
        for m in meetings:
            other_id = m.host_country if m.traveler_country == country.id else m.traveler_country
            other = await countries_repo.get_country(session, other_id)
            other_name = f"{other.flag} {other.name_fa}" if other else "?"
            lines.append(f"• {other_name} — {_status_fa(m.status)}")
            if m.status in open_states:
                builder.button(
                    text=f"🔚 پایان دیدار با {other.name_fa if other else '?'}",
                    callback_data=f"meet_force_end:bi:{m.id}",
                    style=STYLE_NO,
                )
        lines.append("")

    if groups:
        lines.append("👥 <b>چندجانبه:</b>")
        for g in groups:
            lines.append(f"• «{g.title}» — {_status_fa(g.status)}")
            if g.status in open_states:
                builder.button(
                    text=f"🔚 پایان نشست «{g.title}»",
                    callback_data=f"meet_force_end:grp:{g.id}",
                    style=STYLE_NO,
                )
        lines.append("")

    if not meetings and not groups:
        lines.append("هیچ نشستی در سابقه‌ی شما نیست.")

    builder.button(text="🔙 بازگشت", callback_data="dip:meeting", style=STYLE_MAIN)
    builder.adjust(1)
    await safe_edit(call,"\n".join(lines).strip(), reply_markup=builder.as_markup())


@router.callback_query(F.data == "dip:meetings_recent")
async def cb_meetings_recent(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call,NO_COUNTRY_TEXT)
        return
    await _render_recent_meetings(call, session, country)


@router.callback_query(F.data.startswith("meet_force_end:"))
async def cb_meet_force_end(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """پایان‌دادن دستی به یک نشست مشخص از فهرست نشست‌های اخیر."""
    country = await get_player_country(session, db_user)
    if country is None:
        await call.answer()
        return
    _, kind, mid_s = call.data.split(":", 2)
    mid = int(mid_s)

    if kind == "bi":
        meeting = await dip_repo.get_meeting(session, mid)
        if meeting is None or (
            country.id not in (meeting.traveler_country, meeting.host_country)
        ):
            await call.answer("این دیدار متعلق به شما نیست.", show_alert=True)
            return
        if meeting.status not in (DiplomacyStatus.PENDING, DiplomacyStatus.ACTIVE):
            await call.answer("این دیدار از قبل بسته شده است.")
            await _render_recent_meetings(call, session, country)
            return
        meeting.status = DiplomacyStatus.COMPLETED
        traveler = await countries_repo.get_country(session, meeting.traveler_country)
        host = await countries_repo.get_country(session, meeting.host_country)
        for c in (traveler, host):
            if c and c.owner_user_id:
                try:
                    await bot.send_message(
                        c.owner_user_id,
                        f"🔚 دیدار توسط {country.flag} {country.name_fa} پایان یافت.",
                    )
                except Exception:  # noqa: BLE001
                    pass
        await call.answer("دیدار پایان یافت ✅")
    else:  # grp
        group = await dip_repo.get_group_meeting(session, mid)
        member_ids = await dip_repo.group_member_country_ids(session, group) if group else []
        if group is None or country.id not in member_ids:
            await call.answer("این نشست متعلق به شما نیست.", show_alert=True)
            return
        if group.status not in (DiplomacyStatus.PENDING, DiplomacyStatus.ACTIVE):
            await call.answer("این نشست از قبل بسته شده است.")
            await _render_recent_meetings(call, session, country)
            return
        group.status = DiplomacyStatus.COMPLETED
        for cid in member_ids:
            member = await countries_repo.get_country(session, cid)
            if member and member.owner_user_id:
                try:
                    await bot.send_message(
                        member.owner_user_id,
                        f"🔚 نشست «{group.title}» توسط {country.flag} {country.name_fa} پایان یافت.",
                    )
                except Exception:  # noqa: BLE001
                    pass
        await call.answer("نشست پایان یافت ✅")

    await _render_recent_meetings(call, session, country)


# ============================================================
#  🤝 دیدار حضوری
# ============================================================
@router.callback_query(F.data == "dip:meeting")
async def cb_meeting(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """انتخاب نوع دیدار: دوجانبه یا چندجانبه."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call,NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "dip.meeting"):
        return
    # نکته (v1.10.1): کول‌داون اینجا چک نمی‌شود تا کاربر همیشه به «نشست‌های اخیر» دسترسی
    # داشته باشد و بتواند نشست گیرکرده را پایان دهد. کول‌داون در مرحله‌ی ساخت نشست اعمال می‌شود.
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤝 دیدار دوجانبه", callback_data="meet_kind:bi", style=STYLE_MAIN)],
        [InlineKeyboardButton(text="👥 دیدار چندجانبه", callback_data="meet_kind:multi", style=STYLE_MAIN)],
        [InlineKeyboardButton(text="🕘 نشست‌های اخیر", callback_data="dip:meetings_recent", style=STYLE_MAIN)],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu:diplomacy", style=STYLE_MAIN)],
    ])
    await safe_edit(call,
        "🤝 <b>دیدار حضوری</b>\n\nنوع دیدار را انتخاب کنید:", reply_markup=kb
    )


@router.callback_query(F.data == "meet_kind:bi")
async def cb_meeting_bi(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """دیدار دوجانبه: انتخاب کشور مقصد (جریان قبلی)."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call,NO_COUNTRY_TEXT)
        return
    await state.set_state(MeetingForm.choosing_target)
    others = await _other_countries(session, country.id)
    await safe_edit(call,
        "🤝 به کدام کشور سفر می‌کنید؟",
        reply_markup=countries_kb(others, prefix="meet_to", columns=2, back_data="menu:diplomacy"),
    )


def _group_select_kb(others, selected: set[int]):
    """کیبورد انتخاب چندتایی کشورها برای نشست چندجانبه (انتخاب‌شده سبز)."""
    from ..utils.ui import PICK_OFF, PICK_ON, STYLE_MAIN, STYLE_OK

    builder = InlineKeyboardBuilder()
    for c in others:
        chosen = c.id in selected
        mark = PICK_ON if chosen else PICK_OFF
        builder.button(
            text=f"{mark} {c.flag} {c.name_fa}",
            callback_data=f"meet_toggle:{c.id}",
            style=STYLE_OK if chosen else STYLE_MAIN,
        )
    builder.adjust(2)
    cont_text = f"✅ ادامه ({fa_number(len(selected))})" if selected else "✔️ ادامه"
    builder.row(
        InlineKeyboardButton(
            text=cont_text, callback_data="meet_multi_next",
            style=STYLE_OK if selected else STYLE_MAIN,
        ),
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu:diplomacy", style=STYLE_MAIN),
    )
    return builder.as_markup()


@router.callback_query(F.data == "meet_kind:multi")
async def cb_meeting_multi(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """دیدار چندجانبه: شروع انتخاب چند کشور."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call,NO_COUNTRY_TEXT)
        return
    await state.set_state(MeetingForm.selecting_members)
    await state.update_data(selected=[])
    others = await _other_countries(session, country.id)
    await safe_edit(call,
        "👥 کشورهای شرکت‌کننده در نشست را انتخاب کنید (می‌توانید چند کشور را تیک بزنید):",
        reply_markup=_group_select_kb(others, set()),
    )


@router.callback_query(MeetingForm.selecting_members, F.data.startswith("meet_toggle:"))
async def cb_meeting_toggle(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """افزودن/حذف یک کشور از فهرست انتخاب نشست چندجانبه."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call,NO_COUNTRY_TEXT)
        return
    cid = int(call.data.split(":")[1])
    data = await state.get_data()
    selected = set(data.get("selected", []))
    if cid in selected:
        selected.discard(cid)
    else:
        selected.add(cid)
    await state.update_data(selected=list(selected))
    others = await _other_countries(session, country.id)
    await call.message.edit_reply_markup(reply_markup=_group_select_kb(others, selected))


@router.callback_query(MeetingForm.selecting_members, F.data == "meet_multi_next")
async def cb_meeting_multi_next(call: CallbackQuery, state: FSMContext) -> None:
    """پس از انتخاب کشورها، عنوان نشست را می‌پرسد."""
    await call.answer()
    data = await state.get_data()
    selected = data.get("selected", [])
    if not selected:
        await call.answer("حداقل یک کشور انتخاب کنید.", show_alert=True)
        return
    await state.set_state(MeetingForm.entering_group_title)
    await safe_edit(call,
        f"👥 {fa_number(len(selected))} کشور انتخاب شد.\n\n"
        "عنوان نشست چندجانبه را وارد کنید (مثلاً «نشست امنیت منطقه‌ای»):",
        reply_markup=_back_kb("meetback:members"),
    )


@router.callback_query(StateFilter(MeetingForm), F.data == "meetback:members")
async def cb_meeting_back_members(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """بازگشت به انتخاب کشورهای نشست چندجانبه."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call,NO_COUNTRY_TEXT)
        return
    data = await state.get_data()
    selected = set(data.get("selected", []))
    await state.set_state(MeetingForm.selecting_members)
    others = await _other_countries(session, country.id)
    await safe_edit(call,
        "👥 کشورهای شرکت‌کننده در نشست را انتخاب کنید (می‌توانید چند کشور را تیک بزنید):",
        reply_markup=_group_select_kb(others, selected),
    )


@router.message(MeetingForm.entering_group_title, F.text)
async def msg_group_title(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """ساخت نشست چندجانبه و ارسال دعوت به همه‌ی کشورهای انتخاب‌شده."""
    data = await state.get_data()
    selected = data.get("selected", [])
    country = await get_player_country(session, db_user)
    await state.clear()
    if country is None or not selected:
        await message.answer("خطا در ساخت نشست.")
        return

    # سیستم انحصار: تا وقتی نشست/تماس فعالی داری نمی‌توانی نشست جدیدی میزبانی کنی (v1.10)
    label = await dip_repo.get_active_engagement_label(session, country.id)
    if label is not None:
        await message.answer(
            f"⛔ شما هم‌اکنون {label} دارید.\n"
            "ابتدا نشست فعلی را پایان دهید، سپس نشست جدید بسازید.",
            reply_markup=diplomacy_menu_kb(),
        )
        return

    # کول‌داون دیدار حضوری: هر ۳ ساعت ۱ نشست (شامل نشست چندجانبه) (v1.9)
    mins = await _cooldown_remaining_min(session, country.id, "meeting", MEETING_COOLDOWN_HOURS)
    if mins > 0:
        await message.answer(
            _cooldown_text("دیدار حضوری", f"{fa_number(MEETING_COOLDOWN_HOURS)} ساعت", mins),
            reply_markup=diplomacy_menu_kb(),
        )
        return

    meeting = GroupMeeting(
        host_country=country.id,
        title=message.text.strip(),
        status=DiplomacyStatus.PENDING,
    )
    await dip_repo.add_group_meeting(session, meeting)
    await session.flush()
    # ثبت کول‌داون نشست برای میزبان (v1.9)
    await cd_repo.touch(session, country.id, "meeting")

    invited_names = []
    busy_names = []
    for cid in selected:
        target = await countries_repo.get_country(session, cid)
        if target is None or target.owner_user_id is None:
            continue
        # (v1.10.1) کشورهای مشغول (نشست/تماس/پرواز) دعوت نمی‌شوند
        if await dip_repo.get_active_engagement_label(session, cid) is not None:
            busy_names.append(f"{target.flag} {target.name_fa}")
            continue
        await dip_repo.add_group_participant(session, meeting.id, cid)
        invited_names.append(f"{target.flag} {target.name_fa}")
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ شرکت می‌کنم", callback_data=f"gmeet_accept:{meeting.id}", style=STYLE_OK),
            InlineKeyboardButton(text="❌ رد", callback_data=f"gmeet_reject:{meeting.id}", style=STYLE_NO),
        ]])
        try:
            await bot.send_message(
                target.owner_user_id,
                f"👥 <b>دعوت به نشست چندجانبه</b>\n\n"
                f"عنوان: {meeting.title}\n"
                f"میزبان: {country.flag} {country.name_fa}",
                reply_markup=kb,
            )
        except Exception:  # noqa: BLE001
            pass

    # اگر هیچ کشوری قابل‌دعوت نبود، نشست لغو می‌شود تا میزبان قفل نماند (v1.10.1)
    if not invited_names:
        meeting.status = DiplomacyStatus.CANCELLED
        await message.answer(
            "⛔ هیچ‌کدام از کشورهای انتخاب‌شده در دسترس نبودند (همه مشغول نشست/تماس بودند). "
            "نشست ساخته نشد.",
            reply_markup=diplomacy_menu_kb(),
        )
        return

    extra = f"\n\n⛔ کشورهای مشغول (دعوت نشدند): {('، '.join(busy_names))}" if busy_names else ""
    await message.answer(
        f"👥 نشست «{meeting.title}» ساخته شد و دعوت برای کشورهای زیر ارسال گردید:\n"
        + "، ".join(invited_names)
        + extra
        + "\n\nپس از پاسخ کشورها، نشست فعال می‌شود.",
        reply_markup=diplomacy_menu_kb(),
    )


async def _maybe_schedule_group_meeting(session: AsyncSession, meeting: GroupMeeting) -> None:
    """
    وقتی همه‌ی دعوت‌شده‌ها پاسخ دادند، زمان برگزاری نشست را تعیین می‌کند (v1.5):
    نشست زمانی شروع می‌شود که آخرین کشورِ پذیرنده به میزبان برسد (بیشترین travel_eta).
    این زمان همان لحظه به همه اعلام می‌شود. فعال‌سازی نهایی توسط زمان‌بند انجام می‌شود.
    """
    participants = await dip_repo.list_group_participants(session, meeting.id)
    if any(p.response == DiplomacyStatus.PENDING for p in participants):
        return  # هنوز همه پاسخ نداده‌اند
    accepted = [p for p in participants if p.response == DiplomacyStatus.ACTIVE]
    host = await countries_repo.get_country(session, meeting.host_country)

    if not accepted:
        meeting.status = DiplomacyStatus.CANCELLED
        if host and host.owner_user_id:
            try:
                await bot.send_message(
                    host.owner_user_id,
                    f"❌ نشست «{meeting.title}» لغو شد؛ هیچ کشوری دعوت را نپذیرفت.",
                )
            except Exception:  # noqa: BLE001
                pass
        return

    # زمان شروع = دیرترین زمان رسیدن میان پذیرندگان
    etas = [_aware(p.travel_eta) for p in accepted if p.travel_eta is not None]
    start_at = max(etas) if etas else _utcnow()
    meeting.start_at = start_at

    # اعلام زمان برگزاری به میزبان و همه‌ی پذیرندگان
    members = [host] if host else []
    for p in accepted:
        c = await countries_repo.get_country(session, p.country_id)
        if c:
            members.append(c)
    names = "، ".join(f"{c.flag} {c.name_fa}" for c in members if c)
    remaining_min = max(0, int((start_at - _utcnow()).total_seconds() // 60))
    notice = (
        f"🛬 <b>نشست «{meeting.title}» برنامه‌ریزی شد</b>\n\n"
        f"شرکت‌کنندگان: {names}\n"
        f"⏱ نشست پس از رسیدن همه‌ی کشورها (حدود {fa_number(remaining_min)} دقیقه‌ی دیگر) آغاز می‌شود."
    )
    for c in members:
        if c and c.owner_user_id:
            try:
                await bot.send_message(c.owner_user_id, notice)
            except Exception:  # noqa: BLE001
                pass

    # لاگ + دکمه‌ی «آغاز فوری نشست» برای مدیران (v1.8)
    arrive_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="⚡️ آغاز فوری نشست", callback_data=f"garrive:gmeet:{meeting.id}", style=STYLE_OK
        )
    ]])
    await send_log(
        bot,
        f"👥 نشست چندجانبه «{meeting.title}» برنامه‌ریزی شد (شروع پس از رسیدن همه).",
        reply_markup=arrive_kb,
    )


@router.callback_query(F.data.startswith("gmeet_accept:"))
async def cb_gmeet_accept(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """پذیرش دعوت نشست چندجانبه: کشور با پرواز به میزبان می‌رود (v1.5)."""
    meeting_id = int(call.data.split(":")[1])
    meeting = await dip_repo.get_group_meeting(session, meeting_id)
    if meeting is None or meeting.status != DiplomacyStatus.PENDING:
        await call.answer("این نشست دیگر معتبر نیست.", show_alert=True)
        return
    country = await get_player_country(session, db_user)
    if country is None:
        await call.answer()
        return
    participant = await dip_repo.get_group_participant(session, meeting_id, country.id)
    if participant is None:
        await call.answer("شما در این نشست دعوت نشده‌اید.", show_alert=True)
        return

    # سیستم انحصار: تا وقتی نشست/تماس فعالی داری نمی‌توانی نشست جدیدی را بپذیری (v1.10)
    if await _busy_block_cb(call, session, country.id, is_self=True):
        return

    await call.answer("پذیرفته شد ✅")
    # زمان پرواز مسافت‌محور به کشور میزبان
    host = await countries_repo.get_country(session, meeting.host_country)
    minutes = geo.compute_flight_duration(country.name_en, host.name_en) if host else FLIGHT_DURATION_MINUTES
    participant.response = DiplomacyStatus.ACTIVE
    participant.travel_eta = _utcnow() + timedelta(minutes=minutes)

    await safe_edit(call,
        call.message.html_text
        + f"\n\n✈️ <b>پذیرفتید</b> — پرواز به میزبان آغاز شد (زمان رسیدن حدود {fa_number(minutes)} دقیقه)"
    )

    # خبر سفر دیپلماتیک (نشست چندجانبه) در کانال دیپلماسی: عکس + فرمت سفر (v1.6)
    if settings.news_diplomacy_channel_id is not None:
        traveler_pres = await _president_name(session, country)
        x = f"{country.flag} {country.name_fa}"
        b = f"{host.flag} {host.name_fa}" if host else "?"
        if country.name_en == "UN":
            flight_lead = f"✈ | دبیرکل محترم سازمان ملل متحد 🇺🇳 مقر سازمان ملل را به مقصد کشور {b}"
        elif host and host.name_en == "UN":
            flight_lead = f"✈ | ریاست جمهور محترم کشور {x} ، جناب آقای {traveler_pres} کشور خود را به مقصد مقر سازمان ملل متحد 🇺🇳"
        else:
            flight_lead = f"✈ | ریاست جمهور محترم کشور {x} ، جناب آقای {traveler_pres} کشور خود را به مقصد کشور {b}"

        caption = (
            "⚪ | اطلاع رسانی سفر مقامات دیپلمات\n\n"
            f"{flight_lead} برای شرکت در نشست «{meeting.title}» ترک کرد.\n"
            f"⏳ | مدت زمان پرواز: {fa_number(minutes)} دقیقه"
        )
        await send_photo_news(
            bot, settings.news_diplomacy_channel_id, "diplomacy_travel", caption
        )

    await _maybe_schedule_group_meeting(session, meeting)


@router.callback_query(F.data.startswith("gmeet_reject:"))
async def cb_gmeet_reject(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """رد دعوت نشست چندجانبه."""
    meeting_id = int(call.data.split(":")[1])
    meeting = await dip_repo.get_group_meeting(session, meeting_id)
    if meeting is None or meeting.status != DiplomacyStatus.PENDING:
        await call.answer("این نشست دیگر معتبر نیست.", show_alert=True)
        return
    country = await get_player_country(session, db_user)
    if country is None:
        await call.answer()
        return
    participant = await dip_repo.get_group_participant(session, meeting_id, country.id)
    if participant is None:
        await call.answer()
        return
    participant.response = DiplomacyStatus.REJECTED
    await call.answer("رد شد")
    await safe_edit(call,call.message.html_text + "\n\n❌ <b>رد کردید</b>")
    await _maybe_schedule_group_meeting(session, meeting)


@router.callback_query(MeetingForm.choosing_target, F.data.startswith("meet_to:"))
async def cb_meet_to(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    await state.clear()
    country = await get_player_country(session, db_user)
    target = await countries_repo.get_country(session, int(call.data.split(":")[1]))
    if country is None or target is None or target.owner_user_id is None:
        await safe_edit(call,"امکان دیدار با این کشور وجود ندارد (بدون رهبر).")
        return

    # سیستم انحصار: تا وقتی نشست/تماس فعالی داری نمی‌توانی سفر/دیدار جدید آغاز کنی (v1.10)
    label = await dip_repo.get_active_engagement_label(session, country.id)
    if label is not None:
        await safe_edit(call,
            f"⛔ شما هم‌اکنون {label} دارید.\n"
            "ابتدا نشست فعلی را پایان دهید، سپس دوباره برای دیدار اقدام کنید.",
            reply_markup=diplomacy_menu_kb(),
        )
        return

    # (v1.10.1) اگر طرف مقابل مشغول نشست/تماس/پرواز باشد، اصلاً نمی‌توان برایش درخواست فرستاد
    target_label = await dip_repo.get_active_engagement_label(session, target.id)
    if target_label is not None:
        await safe_edit(call,
            f"⛔ کشور {target.flag} {target.name_fa} هم‌اکنون {target_label} دارد.\n"
            "تا پایان آن نمی‌توانید با این کشور دیدار داشته باشید.",
            reply_markup=diplomacy_menu_kb(),
        )
        return

    # کول‌داون دیدار حضوری: هر ۳ ساعت ۱ نشست (v1.9)
    mins = await _cooldown_remaining_min(session, country.id, "meeting", MEETING_COOLDOWN_HOURS)
    if mins > 0:
        await safe_edit(call,
            _cooldown_text("دیدار حضوری", f"{fa_number(MEETING_COOLDOWN_HOURS)} ساعت", mins),
            reply_markup=diplomacy_menu_kb(),
        )
        return

    meeting = Meeting(
        traveler_country=country.id,
        host_country=target.id,
        status=DiplomacyStatus.PENDING,
    )
    await dip_repo.add_meeting(session, meeting)
    await session.flush()
    # ثبت کول‌داون نشست برای آغازکننده (v1.9)
    await cd_repo.touch(session, country.id, "meeting")

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ پذیرش سفر", callback_data=f"meet_accept:{meeting.id}", style=STYLE_OK),
        InlineKeyboardButton(text="❌ رد", callback_data=f"meet_reject:{meeting.id}", style=STYLE_NO),
    ]])
    try:
        await bot.send_message(
            target.owner_user_id,
            f"🤝 <b>درخواست دیدار حضوری</b> از {country.flag} {country.name_fa}",
            reply_markup=kb,
        )
    except Exception:  # noqa: BLE001
        pass
    await safe_edit(call,"🤝 درخواست سفر ارسال شد. منتظر پذیرش طرف مقابل بمانید.")


@router.callback_query(F.data.startswith("meet_accept:"))
async def cb_meet_accept(call: CallbackQuery, session: AsyncSession) -> None:
    meeting_id = int(call.data.split(":")[1])
    meeting = await dip_repo.get_meeting(session, meeting_id)
    if meeting is None or meeting.status != DiplomacyStatus.PENDING:
        await call.answer("این درخواست دیگر معتبر نیست.", show_alert=True)
        return

    # سیستم انحصار: نه میزبان (پذیرنده) و نه مسافر نباید نشست فعال دیگری داشته باشند (v1.10)
    if await _busy_block_cb(call, session, meeting.host_country, is_self=True):
        return
    if await _busy_block_cb(call, session, meeting.traveler_country, is_self=False):
        return

    traveler = await countries_repo.get_country(session, meeting.traveler_country)
    host = await countries_repo.get_country(session, meeting.host_country)
    await call.answer("سفر پذیرفته شد")

    # زمان پرواز مسافت‌محور میان دو پایتخت
    minutes = geo.compute_flight_duration(traveler.name_en, host.name_en) if (traveler and host) else FLIGHT_DURATION_MINUTES
    meeting.status = DiplomacyStatus.ACTIVE
    meeting.travel_eta = _utcnow() + timedelta(minutes=minutes)
    meeting.meeting_ends_at = meeting.travel_eta + timedelta(minutes=MEETING_DURATION_MINUTES)
    meeting.travel_note = ""

    msg = (
        f"✈️ سفر آغاز شد. زمان رسیدن: {fa_number(minutes)} دقیقه.\n\n"
        f"پس از رسیدن، دیدار به مدت {fa_number(MEETING_DURATION_MINUTES)} دقیقه فعال می‌شود.\n"
        "⛔ تا پایان نشست، شما و طرف مقابل نمی‌توانید نشست/تماس/نامه‌ی دیگری داشته باشید.\n"
        "💬 در طول دیدار، هر پیامی که بنویسید مستقیماً برای طرف مقابل ارسال می‌شود "
        "(می‌توانید روی پیام طرف مقابل ریپلای کنید).\n"
        "📜 برای عقد قرارداد از دستور /contract استفاده کنید."
    )
    for c in (traveler, host):
        if c and c.owner_user_id:
            try:
                await bot.send_message(c.owner_user_id, msg)
            except Exception:  # noqa: BLE001
                pass

    # خبر سفر دیپلماتیک در کانال دیپلماسی: عکس + فرمت جدید (v1.6)
    if settings.news_diplomacy_channel_id is not None:
        traveler_pres = await _president_name(session, traveler)
        x = f"{traveler.flag} {traveler.name_fa}" if traveler else "?"
        b = f"{host.flag} {host.name_fa}" if host else "?"
        if traveler and traveler.name_en == "UN":
            flight_lead = f"✈ | دبیرکل محترم سازمان ملل متحد 🇺🇳 مقر سازمان ملل را به مقصد کشور {b}"
        elif host and host.name_en == "UN":
            flight_lead = f"✈ | ریاست جمهور محترم کشور {x} ، جناب آقای {traveler_pres} کشور خود را به مقصد مقر سازمان ملل متحد 🇺🇳"
        else:
            flight_lead = f"✈ | ریاست جمهور محترم کشور {x} ، جناب آقای {traveler_pres} کشور خود را به مقصد کشور {b}"

        caption = (
            "⚪ | اطلاع رسانی سفر مقامات دیپلمات\n\n"
            f"{flight_lead} برای برگزاری دیدار حضوری ترک کرد.\n"
            f"⏳ | مدت زمان پرواز: {fa_number(minutes)} دقیقه"
        )
        await send_photo_news(
            bot, settings.news_diplomacy_channel_id, "diplomacy_travel", caption
        )

    # لاگ سفر + دکمه‌ی «رساندن فوری» برای مدیران (v1.8)
    arrive_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="⚡️ رساندن فوری و آغاز نشست", callback_data=f"garrive:meet:{meeting.id}", style=STYLE_OK
        )
    ]])
    await send_log(
        bot,
        f"✈️ سفر دیپلماتیک: {traveler.name_fa if traveler else '?'} → "
        f"{host.name_fa if host else '?'} (زمان رسیدن حدود {fa_number(minutes)} دقیقه)",
        reply_markup=arrive_kb,
    )


@router.callback_query(F.data.startswith("meet_reject:"))
async def cb_meet_reject(call: CallbackQuery, session: AsyncSession) -> None:
    meeting_id = int(call.data.split(":")[1])
    meeting = await dip_repo.get_meeting(session, meeting_id)
    if meeting is None or meeting.status != DiplomacyStatus.PENDING:
        await call.answer()
        return
    meeting.status = DiplomacyStatus.REJECTED
    await call.answer("رد شد")
    traveler = await countries_repo.get_country(session, meeting.traveler_country)
    if traveler and traveler.owner_user_id:
        try:
            await bot.send_message(traveler.owner_user_id, "❌ درخواست دیدار شما رد شد.")
        except Exception:  # noqa: BLE001
            pass


# ============================================================
#  📜 قرارداد (در جریان دیدار حضوری فعال)
# ============================================================
@router.message(Command("contract"))
async def cmd_contract(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """بستن قرارداد در دیدار دوجانبه یا چندجانبه‌ی فعال."""
    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        return

    # ۱) دیدار دوجانبه‌ی فعال
    meeting = await dip_repo.get_active_meeting_for_country(session, country.id)
    if meeting is not None:
        # بررسی رسیدن مسافر
        if _aware(meeting.travel_eta) and _aware(meeting.travel_eta) > _utcnow():
            await message.answer("هنوز سفر به پایان نرسیده است. لطفاً تا رسیدن صبر کنید.")
            return
        other_id = (
            meeting.host_country if meeting.traveler_country == country.id else meeting.traveler_country
        )
        await state.update_data(other_id=other_id)
        await state.set_state(ContractForm.entering_title)
        await message.answer("📜 عنوان قرارداد را وارد کنید:")
        return

    # ۲) نشست چندجانبه‌ی فعال → انعقاد معاهده میان تمام کشورهای حاضر در نشست
    group = await dip_repo.get_active_group_meeting_for_country(session, country.id)
    if group is not None:
        member_ids = await dip_repo.group_member_country_ids(session, group)
        if len(member_ids) < 2:
            await message.answer("برای بستن معاهده چندجانبه، باید حداقل دو کشور در نشست حاضر باشند.")
            return
        await state.update_data(is_multilateral=True, group_id=group.id, member_ids=member_ids)
        await state.set_state(ContractForm.entering_title)
        await message.answer(
            f"🌐 <b>تنظیم معاهده چندجانبه بین‌المللی</b>\n\n"
            f"این معاهده میان تمام {fa_number(len(member_ids))} کشور حاضر در نشست تنظیم خواهد شد.\n"
            f"📜 لطفاً عنوان معاهده را وارد کنید:"
        )
        return

    await message.answer("برای بستن قرارداد باید در یک دیدار حضوری فعال (دوجانبه یا چندجانبه) باشید.")


@router.callback_query(F.data.startswith("contract_with:"))
async def cb_contract_with(call: CallbackQuery, state: FSMContext) -> None:
    """انتخاب طرف قرارداد در نشست چندجانبه (در صورت نیاز)."""
    await call.answer()
    other_id = int(call.data.split(":")[1])
    await state.update_data(other_id=other_id, is_multilateral=False)
    await state.set_state(ContractForm.entering_title)
    await safe_edit(call, "📜 عنوان قرارداد را وارد کنید:")


@router.message(ContractForm.entering_title, F.text)
async def msg_contract_title(message: Message, state: FSMContext) -> None:
    await state.update_data(title=message.text.strip())
    await state.set_state(ContractForm.entering_body)
    await message.answer(
        "متن کامل قرارداد را بنویسید (مفاد، تعهدات طرفین، تأمین مالی و ...):",
        reply_markup=_back_kb("contractback:title"),
    )


@router.callback_query(StateFilter(ContractForm), F.data == "contractback:title")
async def cb_contract_back_title(call: CallbackQuery, state: FSMContext) -> None:
    """بازگشت به وارد کردن عنوان قرارداد."""
    await call.answer()
    await state.set_state(ContractForm.entering_title)
    await safe_edit(call, "📜 عنوان قرارداد را وارد کنید:")


async def _build_multilateral_panel_text(session: AsyncSession, contract: Contract) -> str:
    """ساخت متن پنل وضعیت امضای معاهده چندجانبه."""
    signatories = await dip_repo.get_contract_signatories(session, contract.id)
    proposer = await countries_repo.get_country(session, contract.country_a)
    proposer_name = f"{proposer.flag} {proposer.name_fa}" if proposer else "نامشخص"

    lines = [
        "🌐 <b>پیش‌نویس معاهده چندجانبه بین‌المللی</b>",
        f"🏛 <b>عنوان:</b> {contract.title}",
        f"✍️ <b>تنظیم‌کننده:</b> {proposer_name}",
        "",
        "📝 <b>مفاد و تعهدات معاهده:</b>",
        f"<blockquote>{contract.body}</blockquote>",
        "",
        "📊 <b>وضعیت امضای طرفین معاهده:</b>",
    ]
    for s in signatories:
        c = await countries_repo.get_country(session, s.country_id)
        c_name = f"{c.flag} {c.name_fa}" if c else f"کشور #{s.country_id}"
        status_ico = "🟢 امضا شده" if s.signed else "⚪️ در انتظار امضا"
        lines.append(f"• {c_name}: {status_ico}")

    signed_count = sum(1 for s in signatories if s.signed)
    total_count = len(signatories)
    lines.append(f"\n📈 <b>پیشرفت امضا:</b> {fa_number(signed_count)} از {fa_number(total_count)}")
    return "\n".join(lines)


def _build_multilateral_sign_kb(contract_id: int) -> InlineKeyboardMarkup:
    """کیبورد تعاملی امضا یا رد معاهده چندجانبه."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✍️ امضا", callback_data=f"sign_contract:{contract_id}", style=STYLE_OK),
        InlineKeyboardButton(text="❌ رد معاهده", callback_data=f"reject_contract:{contract_id}", style=STYLE_NO),
    ]])


@router.message(ContractForm.entering_body, F.text)
async def msg_contract_body(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    data = await state.get_data()
    country = await get_player_country(session, db_user)
    is_multilateral = data.get("is_multilateral", False)
    await state.clear()

    if country is None:
        await message.answer("خطا در شناسایی کشور.")
        return

    # ۱) ثبت معاهده چندجانبه
    if is_multilateral:
        member_ids: list[int] = data.get("member_ids", [])
        if not member_ids or country.id not in member_ids or len(member_ids) < 2:
            await message.answer("خطا در تعیین کشورهای عضو نشست.")
            return

        other_cid = next((cid for cid in member_ids if cid != country.id), country.id)
        contract = Contract(
            country_a=country.id,
            country_b=other_cid,
            title=data["title"],
            body=message.text,
            signed_a=True,
            signed_b=False,
            status=DiplomacyStatus.PENDING,
            is_multilateral=True,
        )
        await dip_repo.add_contract(session, contract)
        await session.flush()

        await dip_repo.add_contract_signatories(
            session=session,
            contract_id=contract.id,
            country_ids=member_ids,
            proposer_id=country.id,
        )
        await session.flush()

        panel_text = await _build_multilateral_panel_text(session, contract)
        await message.answer(
            "🌐 <b>معاهده چندجانبه ثبت شد و برای امضای تمام اعضای نشست ارسال گردید.</b>\n\n" + panel_text
        )

        sign_kb = _build_multilateral_sign_kb(contract.id)
        for cid in member_ids:
            if cid == country.id:
                continue
            c = await countries_repo.get_country(session, cid)
            if c and c.owner_user_id:
                try:
                    await bot.send_message(
                        c.owner_user_id,
                        panel_text,
                        reply_markup=sign_kb,
                    )
                except Exception:  # noqa: BLE001
                    pass
        return

    # ۲) ثبت قرارداد دوجانبه
    other_id = data.get("other_id")
    if other_id is None:
        await message.answer("خطا در ثبت قرارداد.")
        return

    contract = Contract(
        country_a=country.id,
        country_b=other_id,
        title=data["title"],
        body=message.text,
        signed_a=True,   # تنظیم‌کننده، طرف اول است و امضا کرده
        signed_b=False,
        status=DiplomacyStatus.PENDING,
        is_multilateral=False,
    )
    await dip_repo.add_contract(session, contract)
    await session.flush()

    other = await countries_repo.get_country(session, other_id)
    await message.answer("📜 قرارداد ثبت شد و برای امضای طرف مقابل ارسال گردید.")

    if other and other.owner_user_id:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✍️ امضا", callback_data=f"sign_contract:{contract.id}", style=STYLE_OK),
            InlineKeyboardButton(text="❌ رد", callback_data=f"reject_contract:{contract.id}", style=STYLE_NO),
        ]])
        try:
            await bot.send_message(
                other.owner_user_id,
                f"📜 <b>{contract.title}</b>\n\n{contract.body}\n\n"
                f"طرف اول: {country.flag} {country.name_fa}",
                reply_markup=kb,
            )
        except Exception:  # noqa: BLE001
            pass


@router.callback_query(F.data.startswith("sign_contract:"))
async def cb_sign_contract(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    contract_id = int(call.data.split(":")[1])
    contract = await dip_repo.get_contract(session, contract_id)
    if contract is None or contract.status != DiplomacyStatus.PENDING:
        await call.answer("این قرارداد دیگر معتبر نیست.", show_alert=True)
        return

    country = await get_player_country(session, db_user)
    if country is None:
        await call.answer("کشوری برای شما ثبت نشده است.", show_alert=True)
        return

    # جریان معاهده چندجانبه
    if contract.is_multilateral:
        sig = await dip_repo.get_contract_signatory(session, contract.id, country.id)
        if sig is None:
            await call.answer("شما طرف این معاهده نیستید.", show_alert=True)
            return
        if sig.signed:
            await call.answer("شما قبلاً این معاهده را امضا کرده‌اید.", show_alert=True)
            return

        ok, all_signed = await dip_repo.sign_contract_signatory(session, contract.id, country.id)
        await session.flush()
        await call.answer("امضا شد ✅")

        if not all_signed:
            updated_panel = await _build_multilateral_panel_text(session, contract)
            await safe_edit(call, updated_panel + "\n\n✅ <i>امضای شما ثبت شد. در انتظار سایر اعضا...</i>")
            return

        # تمام اعضا امضا کردند؛ معاهده لازم‌الاجرا می‌شود
        contract.signed_b = True
        contract.status = DiplomacyStatus.ACTIVE
        await session.flush()
        await safe_edit(call, call.message.html_text + "\n\n✅ <b>تمام اعضا امضا کردند؛ معاهده رسمی و لازم‌الاجرا شد.</b>")

        signatories = await dip_repo.get_contract_signatories(session, contract.id)
        parties = []
        party_countries = []
        for s in signatories:
            c = await countries_repo.get_country(session, s.country_id)
            if c:
                party_countries.append(c)
                c_user = await users_repo.get_user(session, c.owner_user_id) if c.owner_user_id else None
                leader = c_user.president_name if (c_user and c_user.president_name) else (c_user.first_name if c_user else None)
                parties.append({
                    "country_name": c.name_fa,
                    "country_flag": c.flag,
                    "leader_name": leader,
                })

        treaty_bytes: bytes | None = None
        try:
            treaty_bytes = render_contract_image(
                contract_id=contract.id,
                title=contract.title,
                country_a_name="",
                country_a_flag="",
                country_b_name="",
                country_b_flag="",
                body=contract.body,
                created_at=contract.created_at,
                parties=parties,
            )
        except Exception as exc:
            logger.exception("Failed to render multilateral treaty image for contract %s: %s", contract.id, exc)

        parties_str = "، ".join([f"{p['country_flag']} {p['country_name']}" for p in parties])
        doc_caption = (
            f"🌐 <b>معاهده چندجانبه بین‌المللی منعقد شد</b>\n\n"
            f"🏛 <b>عنوان:</b> {contract.title}\n"
            f"🤝 <b>طرفین:</b> {parties_str}\n\n"
            f"🖼 <i>سند رسمی معاهده با امضای تمام طرفین پیوست شد.</i>"
        )
        doc_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📜 قراردادهای من", callback_data="dip:contracts", style=STYLE_MAIN),
            InlineKeyboardButton(text="🔙 منوی دیپلماسی", callback_data="menu:diplomacy", style=STYLE_MAIN),
        ]])

        for c in party_countries:
            if c.owner_user_id:
                try:
                    if treaty_bytes:
                        photo_doc = BufferedInputFile(treaty_bytes, filename=f"treaty_{contract.id}.png")
                        await bot.send_photo(c.owner_user_id, photo=photo_doc, caption=doc_caption, reply_markup=doc_kb)
                    else:
                        await bot.send_message(c.owner_user_id, f"✅ معاهده چندجانبه «{contract.title}» به تایید تمام اعضا رسید و فعال شد.", reply_markup=doc_kb)
                except Exception:  # noqa: BLE001
                    pass

        await publish_news(
            bot,
            NewsCategory.DIPLOMACY,
            f"🕊 معاهده‌ی چندجانبه‌ی «{contract.title}» میان کشورهای {parties_str} به امضای تمام طرفین رسید و لازم‌الاجرا شد.",
        )

        if treaty_bytes:
            photo_log = BufferedInputFile(treaty_bytes, filename=f"treaty_{contract.id}.png")
            await send_log_photo(
                bot,
                photo=photo_log,
                caption=(
                    f"🌐 <b>معاهده چندجانبه منعقد شد</b>\n"
                    f"شماره معاهده: #{contract.id}\n"
                    f"عنوان: {contract.title}\n"
                    f"طرفین: {parties_str}"
                ),
            )
        else:
            await send_log(
                bot,
                f"🌐 <b>معاهده چندجانبه منعقد شد</b>\n"
                f"عنوان: {contract.title}\n"
                f"طرفین: {parties_str}",
            )
        return

    # جریان قرارداد دوجانبه
    contract.signed_b = True
    contract.status = DiplomacyStatus.ACTIVE
    await call.answer("امضا شد ✅")
    await safe_edit(call, call.message.html_text + "\n\n✅ <b>قرارداد امضا و فعال شد</b>")

    a = await countries_repo.get_country(session, contract.country_a)
    b = await countries_repo.get_country(session, contract.country_b)

    # استخراج نام رهبران طرفین جهت درج در سند معاهده
    user_a = await users_repo.get_user(session, a.owner_user_id) if (a and a.owner_user_id) else None
    user_b = await users_repo.get_user(session, b.owner_user_id) if (b and b.owner_user_id) else None
    leader_a = user_a.president_name if (user_a and user_a.president_name) else (user_a.first_name if user_a else None)
    leader_b = user_b.president_name if (user_b and user_b.president_name) else (user_b.first_name if user_b else None)

    # تولید تصویر رسمی سند معاهده با امضای طرفین (v2.9)
    treaty_bytes: bytes | None = None
    try:
        treaty_bytes = render_contract_image(
            contract_id=contract.id,
            title=contract.title,
            country_a_name=a.name_fa if a else "کشور اول",
            country_a_flag=a.flag if a else "",
            country_a_leader=leader_a,
            country_b_name=b.name_fa if b else "کشور دوم",
            country_b_flag=b.flag if b else "",
            country_b_leader=leader_b,
            body=contract.body,
            created_at=contract.created_at,
        )
    except Exception as exc:
        logger.exception("Failed to render treaty image for contract %s: %s", contract.id, exc)

    doc_caption = (
        f"📜 <b>معاهده رسمی منعقد شد</b>\n\n"
        f"🏛 <b>عنوان:</b> {contract.title}\n"
        f"🤝 <b>طرفین:</b> {a.flag if a else ''} {a.name_fa if a else '?'} ↔ {b.flag if b else ''} {b.name_fa if b else '?'}\n\n"
        f"🖼 <i>سند رسمی بین‌المللی با امضای طرفین در تصویر فوق پیوست شد.</i>"
    )
    doc_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📜 قراردادهای من", callback_data="dip:contracts", style=STYLE_MAIN),
        InlineKeyboardButton(text="🔙 منوی دیپلماسی", callback_data="menu:diplomacy", style=STYLE_MAIN),
    ]])

    # ارسال برای طرف اول معاهده
    if a and a.owner_user_id:
        try:
            if treaty_bytes:
                photo_a = BufferedInputFile(treaty_bytes, filename=f"treaty_{contract.id}.png")
                await bot.send_photo(a.owner_user_id, photo=photo_a, caption=doc_caption, reply_markup=doc_kb)
            else:
                await bot.send_message(a.owner_user_id, f"✅ قرارداد «{contract.title}» امضا و فعال شد.", reply_markup=doc_kb)
        except Exception:  # noqa: BLE001
            pass

    # ارسال برای طرف دوم معاهده (امضاکننده)
    if b and b.owner_user_id and b.owner_user_id != (a.owner_user_id if a else None):
        try:
            if treaty_bytes:
                photo_b = BufferedInputFile(treaty_bytes, filename=f"treaty_{contract.id}.png")
                await bot.send_photo(b.owner_user_id, photo=photo_b, caption=doc_caption, reply_markup=doc_kb)
        except Exception:  # noqa: BLE001
            pass

    await publish_news(
        bot,
        NewsCategory.DIPLOMACY,
        f"🕊 معاهده‌ی رسمی «{contract.title}» میان {a.name_fa if a else '?'} و {b.name_fa if b else '?'} منعقد و لازم‌الاجرا شد.",
    )

    # ارسال لاگ به گروه مدیران (همراه با تصویر سند)
    if treaty_bytes:
        photo_log = BufferedInputFile(treaty_bytes, filename=f"treaty_{contract.id}.png")
        await send_log_photo(
            bot,
            photo=photo_log,
            caption=(
                f"📜 <b>معاهده رسمی منعقد شد</b>\n"
                f"شماره معاهده: #{contract.id}\n"
                f"عنوان: {contract.title}\n"
                f"طرفین: {a.flag if a else ''} {a.name_fa if a else '?'} ↔ {b.flag if b else ''} {b.name_fa if b else '?'}"
            ),
        )
    else:
        await send_log(
            bot,
            f"📜 <b>قرارداد منعقد شد</b>\n"
            f"عنوان: {contract.title}\n"
            f"طرفین: {a.flag if a else ''} {a.name_fa if a else '?'} ↔ {b.flag if b else ''} {b.name_fa if b else '?'}",
        )


@router.callback_query(F.data.startswith("reject_contract:"))
async def cb_reject_contract(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    contract_id = int(call.data.split(":")[1])
    contract = await dip_repo.get_contract(session, contract_id)
    if contract is None or contract.status != DiplomacyStatus.PENDING:
        await call.answer()
        return

    country = await get_player_country(session, db_user)
    contract.status = DiplomacyStatus.REJECTED
    await session.flush()
    await call.answer("رد شد")

    c_name = f"{country.flag} {country.name_fa}" if country else "یک کشور"
    await safe_edit(call, call.message.html_text + f"\n\n❌ <b>این معاهده توسط {c_name} رد شد و به تصویب نرسید.</b>")

    if contract.is_multilateral:
        signatories = await dip_repo.get_contract_signatories(session, contract.id)
        for s in signatories:
            if country and s.country_id == country.id:
                continue
            c = await countries_repo.get_country(session, s.country_id)
            if c and c.owner_user_id:
                try:
                    await bot.send_message(
                        c.owner_user_id,
                        f"❌ <b>رد پیش‌نویس معاهده چندجانبه</b>\n\nمعاهده «{contract.title}» توسط {c_name} رد شد و پرونده آن بسته شد.",
                    )
                except Exception:  # noqa: BLE001
                    pass


@router.callback_query(F.data == "dip:contracts")
async def cb_contracts(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "dip.contract"):
        return
    contracts = await dip_repo.list_contracts_for_country(session, country.id, only_active=True)
    if not contracts:
        await safe_edit(call, "📜 قرارداد فعالی ندارید.", reply_markup=diplomacy_menu_kb())
        return

    lines = [
        "📜 <b>قراردادهای فعال شما:</b>",
        "",
        "<i>برای مشاهده مفاد و لغو هر معاهده، روی آن کلیک کنید:</i>",
        "",
    ]
    builder = InlineKeyboardBuilder()
    for idx, c in enumerate(contracts, start=1):
        if c.is_multilateral:
            signatories = await dip_repo.get_contract_signatories(session, c.id)
            c_names = []
            for s in signatories:
                sc = await countries_repo.get_country(session, s.country_id)
                if sc:
                    c_names.append(f"{sc.flag} {sc.name_fa}")
            parties_str = " | ".join(c_names)
            lines.append(f"{fa_number(idx)}. «{c.title}» 🌐 <i>(معاهده چندجانبه)</i>\n   🏛 اعضا: {parties_str}")
            builder.button(
                text=f"🌐 #{fa_number(idx)}. «{c.title[:18]}»",
                callback_data=f"contract_view:{c.id}",
                style=STYLE_MAIN,
            )
        else:
            a = await countries_repo.get_country(session, c.country_a)
            b = await countries_repo.get_country(session, c.country_b)
            a_name = a.name_fa if a else "?"
            b_name = b.name_fa if b else "?"
            lines.append(f"{fa_number(idx)}. «{c.title}»\n   🏛 طرفین: {a_name} ↔ {b_name}")
            builder.button(
                text=f"📜 #{fa_number(idx)}. «{c.title[:18]}»",
                callback_data=f"contract_view:{c.id}",
                style=STYLE_MAIN,
            )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 بازگشت به دیپلماسی", callback_data="menu:diplomacy", style=STYLE_MAIN))
    await safe_edit(call, "\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("contract_view:"))
async def cb_contract_view(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """مشاهده متن کامل یک قرارداد همراه با گزینه لغو."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    try:
        cid = int(call.data.split(":")[1])
    except (IndexError, ValueError):
        await call.answer("شناسه نامعتبر است.", show_alert=True)
        return

    contract = await dip_repo.get_contract(session, cid)
    if contract is None or contract.status != DiplomacyStatus.ACTIVE:
        await safe_edit(call, "قرارداد یافت نشد یا دیگر فعال نیست.", reply_markup=diplomacy_menu_kb())
        return
    if not await dip_repo.is_contract_party(session, contract, country.id):
        await call.answer("شما طرف این قرارداد نیستید.", show_alert=True)
        return

    if contract.is_multilateral:
        signatories = await dip_repo.get_contract_signatories(session, contract.id)
        party_lines = []
        for s in signatories:
            sc = await countries_repo.get_country(session, s.country_id)
            if sc:
                party_lines.append(f"• {sc.flag} {sc.name_fa}")
        parties_text = "\n".join(party_lines)
        text = (
            f"🌐 <b>معاهده چندجانبه: {contract.title}</b>\n\n"
            f"🏛 <b>کشورهای عضو معاهده ({fa_number(len(party_lines))} کشور):</b>\n{parties_text}\n\n"
            f"📝 <b>متن و مفاد معاهده:</b>\n"
            f"<blockquote>{contract.body}</blockquote>"
        )
        cancel_btn_text = "❌ خروج از معاهده (لغو یک‌طرفه)"
    else:
        a = await countries_repo.get_country(session, contract.country_a)
        b = await countries_repo.get_country(session, contract.country_b)
        text = (
            f"📜 <b>قرارداد: {contract.title}</b>\n\n"
            f"🏛 <b>طرف اول:</b> {a.flag if a else ''} {a.name_fa if a else '?'}\n"
            f"🏛 <b>طرف دوم:</b> {b.flag if b else ''} {b.name_fa if b else '?'}\n\n"
            f"📝 <b>متن و مفاد قرارداد:</b>\n"
            f"<blockquote>{contract.body}</blockquote>"
        )
        cancel_btn_text = "❌ لغو یک‌طرفه قرارداد"

    builder = InlineKeyboardBuilder()
    builder.button(
        text="🖼 دریافت تصویر رسمی معاهده",
        callback_data=f"contract_img:{contract.id}",
        style=STYLE_MAIN,
    )
    builder.button(
        text=cancel_btn_text,
        callback_data=f"contract_cancel:{contract.id}",
        style=STYLE_NO,
    )
    builder.button(
        text="🔙 بازگشت به قراردادها",
        callback_data="dip:contracts",
        style=STYLE_MAIN,
    )
    builder.adjust(1)
    await safe_edit(call, text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("contract_img:"))
async def cb_contract_image(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """دریافت تصویر گرافیکی رسمی سند معاهده بین‌المللی با امضای طرفین."""
    country = await get_player_country(session, db_user)
    if country is None:
        await call.answer("کشوری برای شما ثبت نشده است.", show_alert=True)
        return
    try:
        cid = int(call.data.split(":")[1])
    except (IndexError, ValueError):
        await call.answer("شناسه نامعتبر است.", show_alert=True)
        return

    contract = await dip_repo.get_contract(session, cid)
    if contract is None:
        await call.answer("قرارداد یافت نشد.", show_alert=True)
        return
    if not await dip_repo.is_contract_party(session, contract, country.id):
        await call.answer("شما طرف این معاهده نیستید.", show_alert=True)
        return

    await call.answer("در حال آماده‌سازی تصویر سند رسمی معاهده... ⏳")

    if contract.is_multilateral:
        signatories = await dip_repo.get_contract_signatories(session, contract.id)
        parties = []
        for s in signatories:
            sc = await countries_repo.get_country(session, s.country_id)
            if sc:
                sc_user = await users_repo.get_user(session, sc.owner_user_id) if sc.owner_user_id else None
                leader = sc_user.president_name if (sc_user and sc_user.president_name) else (sc_user.first_name if sc_user else None)
                parties.append({
                    "country_name": sc.name_fa,
                    "country_flag": sc.flag,
                    "leader_name": leader,
                })
        try:
            treaty_bytes = render_contract_image(
                contract_id=contract.id,
                title=contract.title,
                country_a_name="",
                country_a_flag="",
                country_b_name="",
                country_b_flag="",
                body=contract.body,
                created_at=contract.created_at,
                parties=parties,
            )
        except Exception as exc:
            logger.exception("Failed to render multilateral treaty image for contract %s: %s", contract.id, exc)
            await call.answer("خطا در تولید تصویر سند معاهده.", show_alert=True)
            return

        names_str = "، ".join([f"{p['country_flag']} {p['country_name']}" for p in parties])
        caption = (
            f"🌐 <b>سند رسمی معاهده چندجانبه بین‌المللی</b>\n\n"
            f"🏛 <b>عنوان:</b> {contract.title}\n"
            f"🤝 <b>طرفین:</b> {names_str}\n"
            f"🔢 <b>شماره ثبت:</b> #{fa_number(contract.id)}\n\n"
            f"✍️ <i>امضاهای رسمی و مهرهای دیپلماتیک تمام کشورهای عضو در تصویر فوق درج شده است.</i>"
        )
    else:
        a = await countries_repo.get_country(session, contract.country_a)
        b = await countries_repo.get_country(session, contract.country_b)
        user_a = await users_repo.get_user(session, a.owner_user_id) if (a and a.owner_user_id) else None
        user_b = await users_repo.get_user(session, b.owner_user_id) if (b and b.owner_user_id) else None
        leader_a = user_a.president_name if (user_a and user_a.president_name) else (user_a.first_name if user_a else None)
        leader_b = user_b.president_name if (user_b and user_b.president_name) else (user_b.first_name if user_b else None)

        try:
            treaty_bytes = render_contract_image(
                contract_id=contract.id,
                title=contract.title,
                country_a_name=a.name_fa if a else "کشور اول",
                country_a_flag=a.flag if a else "",
                country_a_leader=leader_a,
                country_b_name=b.name_fa if b else "کشور دوم",
                country_b_flag=b.flag if b else "",
                country_b_leader=leader_b,
                body=contract.body,
                created_at=contract.created_at,
            )
        except Exception as exc:
            logger.exception("Failed to render treaty image for contract %s: %s", contract.id, exc)
            await call.answer("خطا در تولید تصویر سند معاهده.", show_alert=True)
            return

        caption = (
            f"📜 <b>سند رسمی معاهده بین‌المللی</b>\n\n"
            f"🏛 <b>عنوان:</b> {contract.title}\n"
            f"🤝 <b>طرفین:</b> {a.flag if a else ''} {a.name_fa if a else '?'} ↔ {b.flag if b else ''} {b.name_fa if b else '?'}\n"
            f"🔢 <b>شماره ثبت:</b> #{fa_number(contract.id)}\n\n"
            f"✍️ <i>امضاهای رسمی و مهر دیپلماتیک در تصویر فوق درج شده است.</i>"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 بازگشت به قرارداد", callback_data=f"contract_view:{contract.id}", style=STYLE_MAIN),
        InlineKeyboardButton(text="📜 فهرست قراردادها", callback_data="dip:contracts", style=STYLE_MAIN),
    ]])
    photo = BufferedInputFile(treaty_bytes, filename=f"treaty_{contract.id}.png")
    try:
        await bot.send_photo(call.from_user.id, photo=photo, caption=caption, reply_markup=kb)
    except Exception as exc:
        logger.warning("Could not send treaty photo via bot: %s", exc)
        if call.message:
            await call.message.answer_photo(photo=photo, caption=caption, reply_markup=kb)


@router.callback_query(F.data.startswith("contract_cancel:"))
async def cb_contract_cancel(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """تأییدیه لغو قرارداد / خروج از معاهده."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    try:
        cid = int(call.data.split(":")[1])
    except (IndexError, ValueError):
        await call.answer("شناسه نامعتبر است.", show_alert=True)
        return

    contract = await dip_repo.get_contract(session, cid)
    if contract is None or contract.status != DiplomacyStatus.ACTIVE:
        await safe_edit(call, "قرارداد یافت نشد یا دیگر فعال نیست.", reply_markup=diplomacy_menu_kb())
        return
    if not await dip_repo.is_contract_party(session, contract, country.id):
        await call.answer("شما طرف این قرارداد نیستید.", show_alert=True)
        return

    if contract.is_multilateral:
        prompt = (
            f"❓ <b>خروج از معاهده چندجانبه</b>\n\n"
            f"آیا مطمئن هستید که می‌خواهید از معاهده «{contract.title}» خارج شوید؟\n\n"
            "⚠️ با خروج شما، نام کشورتان از فهرست اعضای معاهده حذف شده و به سایر کشورهای عضو اطلاع داده خواهد شد."
        )
        ok_btn_text = "❌ تأیید و خروج از معاهده"
    else:
        other_id = contract.country_b if contract.country_a == country.id else contract.country_a
        other = await countries_repo.get_country(session, other_id)
        other_name = f"{other.flag} {other.name_fa}" if other else "طرف مقابل"
        prompt = (
            f"❓ <b>لغو قرارداد</b>\n\n"
            f"آیا مطمئن هستید که می‌خواهید قرارداد «{contract.title}» با {other_name} را لغو کنید؟\n\n"
            "⚠️ با لغو این معاهده، وضعیت قرارداد به «لغوشده» تغییر می‌یابد و به مقامات کشور مقابل اطلاع داده می‌شود."
        )
        ok_btn_text = "❌ تأیید و لغو معاهده"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=ok_btn_text, callback_data=f"contract_cancel_ok:{contract.id}", style=STYLE_NO)],
        [InlineKeyboardButton(text="🔙 انصراف", callback_data=f"contract_view:{contract.id}", style=STYLE_MAIN)],
    ])
    await safe_edit(call, prompt, reply_markup=kb)


@router.callback_query(F.data.startswith("contract_cancel_ok:"))
async def cb_contract_cancel_confirm(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """اجرای نهایی لغو معاهده یا خروج یک‌طرفه از معاهده چندجانبه."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    try:
        cid = int(call.data.split(":")[1])
    except (IndexError, ValueError):
        await call.answer("شناسه نامعتبر است.", show_alert=True)
        return

    contract = await dip_repo.get_contract(session, cid)
    if contract is None or contract.status != DiplomacyStatus.ACTIVE:
        await safe_edit(call, "این قرارداد قبلاً لغو شده یا دیگر فعال نیست.", reply_markup=diplomacy_menu_kb())
        return
    if not await dip_repo.is_contract_party(session, contract, country.id):
        await call.answer("شما طرف این قرارداد نیستید.", show_alert=True)
        return

    if contract.is_multilateral:
        # خروج یک‌طرفه از معاهده چندجانبه
        await dip_repo.remove_contract_signatory(session, contract.id, country.id)
        await session.flush()

        remaining_signatories = await dip_repo.get_contract_signatories(session, contract.id)
        is_dissolved = len(remaining_signatories) < 2
        if is_dissolved:
            contract.status = DiplomacyStatus.CANCELLED
            await session.flush()

        # اطلاع به سایر اعضا
        for s in remaining_signatories:
            c = await countries_repo.get_country(session, s.country_id)
            if c and c.owner_user_id:
                try:
                    notice = (
                        f"⚠️ <b>خروج از معاهده چندجانبه</b>\n\n"
                        f"کشور {country.flag} {country.name_fa} از معاهده «{contract.title}» خارج شد."
                    )
                    if is_dissolved:
                        notice += "\n\n⚠️ با کاهش تعداد اعضا به کمتر از دو کشور، این معاهده به طور کامل لغو گردید."
                    await bot.send_message(c.owner_user_id, notice)
                except Exception:  # noqa: BLE001
                    pass

        # خبر در کانال دیپلماسی
        if is_dissolved:
            news_msg = f"📜 با خروج {country.name_fa}، معاهده چندجانبه‌ی «{contract.title}» به حد نصاب نرسید و به طور کامل لغو شد."
        else:
            news_msg = f"📜 کشور {country.name_fa} به صورت یک‌طرفه از معاهده چندجانبه‌ی «{contract.title}» خارج شد."
        await publish_news(bot, NewsCategory.DIPLOMACY, news_msg)

        # لاگ به گروه مدیران
        await send_log(
            bot,
            f"🌐 <b>خروج از معاهده چندجانبه</b>\n"
            f"عنوان: {contract.title}\n"
            f"کشور خارج‌شده: {country.flag} {country.name_fa}\n"
            f"وضعیت معاهده: {'کامل لغو شد' if is_dissolved else f'فعال با {len(remaining_signatories)} عضو'}",
        )

        res_text = (
            f"✅ خروج شما از معاهده «{contract.title}» ثبت شد."
            if not is_dissolved
            else f"✅ خروج شما ثبت شد و به دلیل به حد نصاب نرسیدن اعضا، معاهده «{contract.title}» لغو گردید."
        )
        await safe_edit(
            call,
            res_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="📜 فهرست قراردادها", callback_data="dip:contracts", style=STYLE_MAIN),
                InlineKeyboardButton(text="🔙 منوی دیپلماسی", callback_data="menu:diplomacy", style=STYLE_MAIN),
            ]]),
        )
        return

    # لغو قرارداد دوجانبه
    contract.status = DiplomacyStatus.CANCELLED
    await session.flush()

    a = await countries_repo.get_country(session, contract.country_a)
    b = await countries_repo.get_country(session, contract.country_b)
    other = b if contract.country_a == country.id else a

    # اطلاع به کشور طرف مقابل
    if other and other.owner_user_id:
        try:
            await bot.send_message(
                other.owner_user_id,
                f"⚠️ <b>لغو قرارداد</b>\n\nکشور {country.flag} {country.name_fa} قرارداد دوجانبه‌ی «{contract.title}» را به صورت یک‌طرفه لغو کرد.",
            )
        except Exception:  # noqa: BLE001
            pass

    # خبر در کانال دیپلماسی
    await publish_news(
        bot,
        NewsCategory.DIPLOMACY,
        f"📜 قرارداد «{contract.title}» میان {a.name_fa if a else '?'} و {b.name_fa if b else '?'} توسط {country.name_fa} لغو شد.",
    )

    # لاگ به گروه مدیران
    await send_log(
        bot,
        f"📜 <b>لغو قرارداد</b>\n"
        f"عنوان: {contract.title}\n"
        f"لغوکننده: {country.flag} {country.name_fa}\n"
        f"طرفین: {a.name_fa if a else '?'} ↔ {b.name_fa if b else '?'}",
    )

    await safe_edit(
        call,
        f"✅ قرارداد «{contract.title}» با موفقیت لغو شد.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📜 فهرست قراردادها", callback_data="dip:contracts", style=STYLE_MAIN),
            InlineKeyboardButton(text="🔙 منوی دیپلماسی", callback_data="menu:diplomacy", style=STYLE_MAIN),
        ]]),
    )


# ============================================================
#  🛂 لغو روادید (Visa Waiver) در دیدار حضوری و مدیریت مرزها
# ============================================================

async def _get_active_meeting_partners(session: AsyncSession, country_id: int) -> tuple[bool, str, list[int]]:
    """
    بررسی اینکه آیا کشور در یک دیدار حضوری فعال است و واجد شرایط لغو روادید می‌باشد یا خیر.
    خروجی: (is_valid, error_reason, list_of_partner_country_ids)
    """
    # ۱) بررسی دیدار دوجانبه
    meeting = await dip_repo.get_active_meeting_for_country(session, country_id)
    if meeting is not None:
        if _aware(meeting.travel_eta) and _aware(meeting.travel_eta) > _utcnow():
            return False, "✈️ هنوز سفر به پایان نرسیده است. لطفاً تا رسیدن به مقصد و آغاز رسمی جلسه صبر کنید.", []
        partner_id = (
            meeting.host_country if meeting.traveler_country == country_id else meeting.traveler_country
        )
        return True, "", [partner_id]

    # ۲) بررسی دیدار چندجانبه
    group = await dip_repo.get_active_group_meeting_for_country(session, country_id)
    if group is not None:
        member_ids = await dip_repo.group_member_country_ids(session, group)
        partners = [cid for cid in member_ids if cid != country_id]
        if not partners:
            return False, "⚠️ کشور دیگری در این نشست حاضر نیست.", []
        return True, "", partners

    return False, "⚠️ لغو روادید (Visa Waiver) منحصراً در جریان دیدار حضوری فعال (دوجانبه یا چندجانبه) امکان‌پذیر است.", []


@router.message(Command("visa_waiver", "waiver"))
async def cmd_visa_waiver(message: Message, session: AsyncSession, db_user: User) -> None:
    """دستور لغو ویزا در جریان دیدار حضوری فعال."""
    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        return

    ok, reason, partners = await _get_active_meeting_partners(session, country.id)
    if not ok:
        await message.answer(reason)
        return

    if len(partners) == 1:
        await _show_visa_waiver_confirm(message, session, country, partners[0], is_callback=False)
    else:
        # نشست چندجانبه: انتخاب طرف
        builder = InlineKeyboardBuilder()
        for pid in partners:
            pc = await countries_repo.get_country(session, pid)
            if pc:
                builder.button(text=f"{pc.flag} {pc.name_fa}", callback_data=f"vw_pick:{pc.id}", style=STYLE_MAIN)
        builder.button(text="❌ انصراف", callback_data="vw_cancel", style=STYLE_NO)
        builder.adjust(2)
        await message.answer("🛂 با کدام یک از کشورهای حاضر در نشست مایل به لغو روادید هستید؟", reply_markup=builder.as_markup())


@router.callback_query(F.data == "dip:visa_waiver_start")
async def cb_visa_waiver_start(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """کلیک روی دکمه لغو ویزا در پنل نشست حضوری."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    ok, reason, partners = await _get_active_meeting_partners(session, country.id)
    if not ok:
        await call.message.reply(reason)
        return

    if len(partners) == 1:
        await _show_visa_waiver_confirm(call, session, country, partners[0], is_callback=True)
    else:
        builder = InlineKeyboardBuilder()
        for pid in partners:
            pc = await countries_repo.get_country(session, pid)
            if pc:
                builder.button(text=f"{pc.flag} {pc.name_fa}", callback_data=f"vw_pick:{pc.id}", style=STYLE_MAIN)
        builder.button(text="❌ انصراف", callback_data="vw_cancel", style=STYLE_NO)
        builder.adjust(2)
        await call.message.reply("🛂 با کدام یک از کشورهای حاضر در نشست مایل به لغو روادید هستید؟", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("vw_pick:"))
async def cb_visa_waiver_pick(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """انتخاب کشور مقصد لغو روادید در نشست چندجانبه."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        return
    target_id = int(call.data.split(":")[1])
    await _show_visa_waiver_confirm(call, session, country, target_id, is_callback=True)


async def _show_visa_waiver_confirm(
    event: Message | CallbackQuery, session: AsyncSession, country: Country, target_id: int, is_callback: bool
) -> None:
    """نمایش پیش‌نمایش، اخطار جریمه و درخواست تأیید دومرحله‌ای لغو ویزا."""
    target = await countries_repo.get_country(session, target_id)
    if not target:
        if is_callback:
            await event.answer("کشور نامعتبر است.", show_alert=True)
        return

    already = await dip_repo.has_visa_waiver(session, country.id, target.id)
    if already:
        text = f"ℹ️ شما قبلاً روادید (ویزا) را برای شهروندان و خدمه کشور {target.flag} {target.name_fa} لغو کرده‌اید و مرزهای شما به روی این کشور باز است."
        if is_callback:
            await event.message.reply(text)
        else:
            await event.answer(text)
        return

    text = (
        f"⚠️ <b>تأییدیه لغو روادید (Visa Waiver) با {target.flag} {target.name_fa}</b>\n\n"
        f"با لغو روادید، اتباع، ملوانان و خلبانان تجاری {target.name_fa} بدون مانع اداری وارد کشور شما می‌شوند.\n\n"
        f"✨ <b>مزایای تجاری:</b>\n"
        f"• اعمال <b>۵۰٪ تخفیف عوارض حمل‌ونقل</b> هوایی ({fa_money(AIR_TRANSPORT_FEE_NO_VISA)}) و دریایی ({fa_money(SEA_TRANSPORT_FEE_NO_VISA)})\n\n"
        f"🛑 <b>تبعات و هزینه‌های باز کردن مرزها برای کشور شما:</b>\n"
        f"• کسر <b>{fa_number(VISA_WAIVER_STABILITY_PENALTY, 1)}٪ از ثبات داخلی</b> (نگرانی‌های امنیتی و بازرسی)\n"
        f"• کسر <b>{fa_number(VISA_WAIVER_SATISFACTION_PENALTY, 1)}٪ از رضایت عمومی</b> (چالش‌های مهاجرتی و هویتی)\n"
        f"• کسر <b>{fa_money(VISA_WAIVER_ADMIN_COST)}</b> از بودجه کشور (تجهیز گمرک و ساماندهی خطوط مرزی)\n\n"
        f"آیا با لغو ویزا و اعمال این تبعات موافقید؟"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ بله، لغو روادید اعمال شود", callback_data=f"vw_confirm:{target.id}", style=STYLE_OK)
    builder.button(text="❌ انصراف", callback_data="vw_cancel", style=STYLE_NO)
    builder.adjust(1)

    if is_callback:
        await event.message.reply(text, reply_markup=builder.as_markup())
    else:
        await event.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "vw_cancel")
async def cb_visa_waiver_cancel(call: CallbackQuery) -> None:
    """انصراف از لغو ویزا."""
    await call.answer("انصراف داده شد.")
    try:
        await call.message.delete()
    except Exception:
        pass


@router.callback_query(F.data.startswith("vw_confirm:"))
async def cb_visa_waiver_confirm(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """تأیید نهایی لغو ویزا و کسر جریمه."""
    country = await get_player_country(session, db_user)
    if country is None:
        await call.answer(NO_COUNTRY_TEXT, show_alert=True)
        return

    target_id = int(call.data.split(":")[1])
    target = await countries_repo.get_country(session, target_id)
    if not target:
        await call.answer("کشور هدف یافت نشد.", show_alert=True)
        return

    ok, reason, partners = await _get_active_meeting_partners(session, country.id)
    if not ok or target.id not in partners:
        await call.answer("دیدار حضوری به پایان رسیده یا معتبر نیست.", show_alert=True)
        return

    already = await dip_repo.has_visa_waiver(session, country.id, target.id)
    if already:
        await call.answer("این توافق قبلاً ثبت شده است.", show_alert=True)
        return

    # بررسی بودجه
    cur_budget = float(country.budget or 0.0)
    if cur_budget < VISA_WAIVER_ADMIN_COST:
        await call.answer("بودجه کافی برای تأمین هزینه‌های اداری لغو ویزا (۴ میلیون دلار) ندارید.", show_alert=True)
        return

    # اعمال جرایم و کسر هزینه
    country.budget = cur_budget - VISA_WAIVER_ADMIN_COST
    country.stability = max(0.0, float(country.stability or 50.0) - VISA_WAIVER_STABILITY_PENALTY)
    country.public_satisfaction = max(0.0, float(country.public_satisfaction or 50.0) - VISA_WAIVER_SATISFACTION_PENALTY)

    # ثبت لغو روادید
    await dip_repo.add_visa_waiver(session, country.id, target.id)
    # رفع هرگونه ویزای اجباری پیشین
    await gov_repo.remove_visa(session, country.id, target.id)
    await session.commit()

    await call.answer("توافق لغو روادید با موفقیت منعقد شد ✅")

    try:
        await call.message.edit_text(
            f"✅ <b>توافق لغو روادید (Visa Waiver) با {target.flag} {target.name_fa} رسماً اجرایی شد.</b>\n\n"
            f"• عوارض پایه ارسال محموله‌های هوایی و دریایی بین طرفین ۵۰٪ کاهش یافت.\n"
            f"• هزینه‌های اداری ({fa_money(VISA_WAIVER_ADMIN_COST)}) و تغییرات ثبات و رضایت بر کشور شما اعمال شد.",
            reply_markup=None,
        )
    except Exception:
        pass

    # ارسال اعلان به پیوی طرف مقابل
    if target.owner_user_id:
        try:
            await bot.send_message(
                target.owner_user_id,
                f"🛂 <b>اطلاعیه دیپلماتیک: لغو روادید (Visa Waiver)</b>\n\n"
                f"کشور {country.flag} {country.name_fa} در جریان دیدار حضوری، روادید ورود را برای اتباع، بازرگانان و خدمه ترابری کشور شما لغو کرد!\n"
                f"✈️🚢 از این پس ارسال محموله‌های صادراتی و تسلیحاتی به این کشور شامل <b>۵۰٪ تخفیف عوارض حمل‌ونقل</b> خواهد بود.",
            )
        except Exception:
            pass

    # خبر در کانال دیپلماسی
    news_text = (
        f"توافق لغو روادید (Visa Waiver) بین مقامات {country.flag} {country.name_fa} و "
        f"{target.flag} {target.name_fa} در جریان دیدار حضوری به امضا رسید. "
        f"این توافق موجب تسهیل تردد تجاری و کاهش ۵۰ درصدی عوارض ترانزیت کالا میان دو کشور گردید."
    )
    await publish_news(bot, NewsCategory.DIPLOMACY, news_text)

    # ثبت لاگ
    await send_log(
        bot,
        f"🛂 <b>انعقاد توافق لغو روادید در دیدار حضوری</b>\n"
        f"کشور لغوکننده: {country.flag} {country.name_fa}\n"
        f"کشور بهره‌مند: {target.flag} {target.name_fa}\n"
        f"هزینه کسرشده: {fa_money(VISA_WAIVER_ADMIN_COST)} | ثبات: -{VISA_WAIVER_STABILITY_PENALTY}٪ | رضایت: -{VISA_WAIVER_SATISFACTION_PENALTY}٪",
    )


@router.callback_query(F.data == "dip:visa_waivers")
async def cb_visa_waivers_menu(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """مشاهده لیست توافقات لغو روادید و مدیریت ابطال آن."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    granted = await dip_repo.list_granted_visa_waivers(session, country.id)
    received = await dip_repo.list_received_visa_waivers(session, country.id)

    lines = [
        header("توافقات لغو روادید (Visa Waiver)", "🛂"),
        "",
        "<i>با لغو روادید، ۵۰٪ تخفیف عوارض حمل‌ونقل پایه هوایی و دریایی اعمال می‌شود.</i>",
        "",
        "<b>🌍 کشورهایی که شما ویزای آن‌ها را لغو کرده‌اید (مرز باز است):</b>",
    ]

    builder = InlineKeyboardBuilder()

    if not granted:
        lines.append("  • موردی وجود ندارد.")
    else:
        for vw in granted:
            tgt = await countries_repo.get_country(session, vw.target_country_id)
            if tgt:
                lines.append(f"  • {tgt.flag} {tgt.name_fa} (۵۰٪ تخفیف عوارض لجستیک)")
                builder.button(
                    text=f"🚫 برقراری مجدد ویزا با {tgt.name_fa}",
                    callback_data=f"vw_revoke:{tgt.id}",
                    style=STYLE_NO,
                )

    lines.append("")
    lines.append("<b>📥 کشورهایی که ویزای کشور شما را لغو کرده‌اند:</b>")
    if not received:
        lines.append("  • موردی وجود ندارد.")
    else:
        for vw in received:
            src = await countries_repo.get_country(session, vw.country_id)
            if src:
                lines.append(f"  • {src.flag} {src.name_fa} (تردد و ارسال محموله با ۵۰٪ تخفیف عوارض)")

    lines.append("")
    lines.append("💡 <i>لغو روادید جدید فقط در جریان دیدارهای حضوری فعال قابل انعقاد است.</i>")

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🛂 سامانه جامع روادید و کنترل مرزها", callback_data="gov:visa_law", style=STYLE_MAIN))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت به دیپلماسی", callback_data="menu:diplomacy", style=STYLE_MAIN))

    await safe_edit(call, "\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("vw_revoke:"))
async def cb_visa_waiver_revoke(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """ابطال لغو روادید و بازگرداندن ویزای اجباری."""
    country = await get_player_country(session, db_user)
    if country is None:
        await call.answer(NO_COUNTRY_TEXT, show_alert=True)
        return

    target_id = int(call.data.split(":")[1])
    target = await countries_repo.get_country(session, target_id)
    if not target:
        await call.answer("کشور نامعتبر است.", show_alert=True)
        return

    removed = await dip_repo.remove_visa_waiver(session, country.id, target.id)
    if not removed:
        await call.answer("توافق لغو روادید یافت نشد.", show_alert=True)
        return
    await session.commit()

    await call.answer(f"لغو روادید با {target.name_fa} باطل شد و ویزا مجدداً برقرار گردید ✅")

    # اطلاع به پیوی هدف
    if target.owner_user_id:
        try:
            await bot.send_message(
                target.owner_user_id,
                f"🛂 <b>اطلاعیه دیپلماتیک</b>\n\n"
                f"کشور {country.flag} {country.name_fa} توافق لغو روادید با کشور شما را باطل نمود.\n"
                f"از این پس عوارض لجستیک و حمل‌ونقل محموله‌ها با این کشور به حالت عادی و بدون تخفیف بازگشت.",
            )
        except Exception:
            pass

    # خبر در کانال دیپلماسی
    news_text = (
        f"کشور {country.flag} {country.name_fa} توافق لغو روادید با {target.flag} {target.name_fa} را "
        f"یک‌طرفه باطل نمود. شرایط ترانزیتی و روادید میان دو کشور به حالت استاندارد بازگشت."
    )
    await publish_news(bot, NewsCategory.DIPLOMACY, news_text)

    # ثبت لاگ
    await send_log(
        bot,
        f"🛂 <b>ابطال لغو روادید (برقراری مجدد ویزا)</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"هدف: {target.flag} {target.name_fa}",
    )

    # به‌روزرسانی منو
    await cb_visa_waivers_menu(call, session, db_user)


# ============================================================
#  🚫 تحریم
# ============================================================
# نگاشت نوع تحریم به شماره‌ی عکس در فولدر D:\PictureDB\Embargo (v1.7)
SANCTION_IMAGE_STEM: dict[SanctionType, str] = {
    SanctionType.OIL_TRADE: "1",
    SanctionType.GAS_TRADE: "2",
    SanctionType.STEEL_TRADE: "3",
    SanctionType.MINERAL_TRADE: "4",
    SanctionType.FINANCIAL: "5",
    SanctionType.ARMS: "6",
    SanctionType.TRANSPORT: "7",
    SanctionType.DIPLOMATIC: "8",
}


@router.callback_query(F.data == "dip:sanction")
async def cb_sanction(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """منوی تحریم (v1.7)."""
    await call.answer()
    await state.clear()
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "dip.sanction"):
        return
    await safe_edit(call,
        header("تحریم", "🚫") + "\n\nیک گزینه را انتخاب کنید:", reply_markup=sanction_menu_kb()
    )


@router.callback_query(F.data == "sanc:impose")
async def cb_sanction_impose(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """وضع تحریم: انتخاب کشور هدف (جریان قبلی)."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call,NO_COUNTRY_TEXT)
        return
    others = await _other_countries(session, country.id)
    await safe_edit(call,
        "🚫 کدام کشور را تحریم می‌کنید؟",
        reply_markup=countries_kb(others, prefix="sanction_to", columns=2, back_data="dip:sanction"),
    )


@router.callback_query(F.data == "sanc:imposed")
async def cb_sanction_imposed(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """فهرست تحریم‌هایی که این کشور وضع کرده است."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call,NO_COUNTRY_TEXT)
        return
    sanctions = await dip_repo.list_sanctions_by(session, country.id)
    if not sanctions:
        await safe_edit(call,"📋 شما هیچ تحریمی وضع نکرده‌اید.", reply_markup=sanction_menu_kb())
        return
    lines = ["📋 <b>تحریم‌های وضع‌شده توسط شما</b>", ""]
    for s in sanctions:
        target = await countries_repo.get_country(session, s.to_country)
        try:
            stype_fa = SANCTION_FA[SanctionType(s.sanction_type)]
        except (ValueError, KeyError):
            stype_fa = s.sanction_type
        lines.append(f"• {target.flag if target else ''} {target.name_fa if target else '?'} — {stype_fa}")
    await safe_edit(call,"\n".join(lines), reply_markup=sanction_menu_kb())


@router.callback_query(F.data == "sanc:mine")
async def cb_sanction_mine(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """فهرست تحریم‌هایی که دیگران علیه این کشور وضع کرده‌اند."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call,NO_COUNTRY_TEXT)
        return
    sanctions = await dip_repo.list_sanctions_against(session, country.id)
    if not sanctions:
        await safe_edit(call,"🎯 هیچ کشوری شما را تحریم نکرده است.", reply_markup=sanction_menu_kb())
        return
    lines = ["🎯 <b>تحریم‌های علیه کشور شما</b>", ""]
    for s in sanctions:
        src = await countries_repo.get_country(session, s.from_country)
        try:
            stype_fa = SANCTION_FA[SanctionType(s.sanction_type)]
        except (ValueError, KeyError):
            stype_fa = s.sanction_type
        lines.append(f"• {src.flag if src else ''} {src.name_fa if src else '?'} — {stype_fa}")
    await safe_edit(call,"\n".join(lines), reply_markup=sanction_menu_kb())


@router.callback_query(F.data == "sanc:cancel")
async def cb_sanction_cancel_list(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """فهرست تحریم‌های وضع‌شده برای لغو."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call,NO_COUNTRY_TEXT)
        return
    sanctions = await dip_repo.list_sanctions_by(session, country.id)
    if not sanctions:
        await safe_edit(call,"♻️ تحریمی برای لغو ندارید.", reply_markup=sanction_menu_kb())
        return
    builder = InlineKeyboardBuilder()
    for s in sanctions:
        target = await countries_repo.get_country(session, s.to_country)
        try:
            stype_fa = SANCTION_FA[SanctionType(s.sanction_type)]
        except (ValueError, KeyError):
            stype_fa = s.sanction_type
        builder.button(
            text=f"❌ {target.name_fa if target else '?'} — {stype_fa}",
            callback_data=f"sanc_cancel:{s.id}",
            style=STYLE_OK,
        )
    builder.button(text="🔙 بازگشت", callback_data="dip:sanction", style=STYLE_MAIN)
    builder.adjust(1)
    await safe_edit(call,"♻️ کدام تحریم را لغو می‌کنید؟", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("sanc_cancel:"))
async def cb_sanction_do_cancel(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """لغو یک تحریم وضع‌شده توسط همین کشور."""
    await call.answer()
    country = await get_player_country(session, db_user)
    sanction = await dip_repo.get_sanction(session, int(call.data.split(":")[1]))
    if country is None or sanction is None or sanction.from_country != country.id or not sanction.active:
        await call.answer("این تحریم دیگر معتبر نیست.", show_alert=True)
        return
    await dip_repo.deactivate_sanction(session, sanction.id)
    target = await countries_repo.get_country(session, sanction.to_country)
    await safe_edit(call,
        f"✅ تحریم علیه {target.flag if target else ''} {target.name_fa if target else '?'} لغو شد.",
        reply_markup=sanction_menu_kb(),
    )

    # نام فارسی نوع تحریم
    try:
        stype_fa = SANCTION_FA[SanctionType(sanction.sanction_type)]
    except (ValueError, KeyError):
        stype_fa = sanction.sanction_type or "تحریم"

    x = f"{target.flag} {target.name_fa}" if target else "?"   # کشور تحریم‌شده
    y = f"{country.flag} {country.name_fa}"                      # کشور تحریم‌کننده

    # خبر رفع تحریم در کانال دیپلماسی (v1.9)
    if settings.news_diplomacy_channel_id is not None:
        news = (
            "🔴 | فوری!\n\n"
            f"✅ | کشور {x} توسط کشور {y} که پیش‌تر مورد {stype_fa} قرار گرفته بود، "
            "امروز در خبری اعلام کرده که تحریم‌های مرتبط با این موضوع در حال حذف شدن و رفع تحریم می‌باشد!"
        )
        try:
            await bot.send_message(settings.news_diplomacy_channel_id, news)
        except Exception:  # noqa: BLE001
            pass

    # اطلاع به کشور تحریم‌شده
    if target and target.owner_user_id:
        try:
            await bot.send_message(
                target.owner_user_id,
                f"✅ کشور {y} {stype_fa} علیه شما را لغو کرد.",
            )
        except Exception:  # noqa: BLE001
            pass

    # لاگ رفع تحریم به گروه تحریم و لایحه (گروه ۱)
    await send_to_admin_group(
        bot,
        AdminGroupType.SANCTION_BILL,
        f"✅ <b>رفع تحریم</b>\nتحریم‌کننده: {y}\nکشور هدف: {x}\nنوع: {stype_fa}",
    )


@router.callback_query(F.data.startswith("sanction_to:"))
async def cb_sanction_to(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """انتخاب نوع تحریم (v1.5)."""
    await call.answer()
    target_id = int(call.data.split(":")[1])
    await state.update_data(sanction_target=target_id)
    await state.set_state(SanctionForm.choosing_type)
    target = await countries_repo.get_country(session, target_id)
    await safe_edit(call,
        f"نوع تحریم علیه {target.flag} {target.name_fa} را انتخاب کنید:",
        reply_markup=sanction_types_kb(),
    )


_SEVERITY_FA = {"low": "خفیف", "medium": "متوسط", "high": "شدید"}


@router.callback_query(SanctionForm.choosing_type, F.data.startswith("sanc_type:"))
async def cb_sanction_type(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """درخواست تحریم را برای تأیید مالک به گروه لاگ می‌فرستد (v1.10.5: بدون امکان‌سنجی AI)."""
    await call.answer()
    stype = SanctionType(call.data.split(":")[1])
    data = await state.get_data()
    country = await get_player_country(session, db_user)
    target = await countries_repo.get_country(session, data["sanction_target"])
    await state.clear()
    if country is None or target is None:
        await safe_edit(call,"خطا.")
        return

    x = f"{country.flag} {country.name_fa}"
    y = f"{target.flag} {target.name_fa}"

    if get_admin_group_id(AdminGroupType.SANCTION_BILL) is None:
        await safe_edit(call,
            "⛔️ امکان ثبت درخواست تحریم نیست (گروه تحریم و لایحه تنظیم نشده). با مدیریت تماس بگیرید.",
            reply_markup=diplomacy_menu_kb(),
        )
        return

    # کیبورد تأیید/رد برای مالک در گروه تحریم و لایحه: انتخاب شدت یا رد
    builder = InlineKeyboardBuilder()
    base = f"{country.id}:{target.id}:{stype.value}"
    builder.button(text="🟢 خفیف", callback_data=f"sancok:{base}:low", style=STYLE_OK)
    builder.button(text="🟡 متوسط", callback_data=f"sancok:{base}:medium", style=STYLE_OK)
    builder.button(text="🔴 شدید", callback_data=f"sancok:{base}:high", style=STYLE_OK)
    builder.button(text="❌ رد", callback_data=f"sancno:{base}", style=STYLE_NO)
    builder.adjust(3, 1)

    await send_to_admin_group(
        bot,
        AdminGroupType.SANCTION_BILL,
        "🚫 <b>درخواست تحریم (نیازمند تأیید مالک)</b>\n\n"
        f"🔴 تحریم‌کننده: {x}\n"
        f"🔵 هدف: {y}\n"
        f"📋 نوع: {SANCTION_FA[stype]}\n\n"
        "شدت تحریم را انتخاب کنید یا درخواست را رد کنید:",
        reply_markup=builder.as_markup(),
    )

    await safe_edit(call,
        "✅ درخواست تحریم شما برای بررسی و تأیید مدیریت بازی ارسال شد. "
        "نتیجه پس از تصمیم مدیریت اعلام می‌شود.",
        reply_markup=sanction_menu_kb(),
    )


@router.callback_query(F.data.startswith("sancok:"))
async def cb_sanction_approve(call: CallbackQuery, session: AsyncSession) -> None:
    """تأیید تحریم توسط مالک با انتخاب شدت → اعمال اثر + خبر (v1.10.5)."""
    if not settings.is_owner(call.from_user.id):
        await call.answer("فقط مالک بازی می‌تواند تأیید کند.", show_alert=True)
        return
    _, from_id, to_id, stype_v, sev = call.data.split(":")
    stype = SanctionType(stype_v)
    country = await countries_repo.get_country(session, int(from_id))
    target = await countries_repo.get_country(session, int(to_id))
    if country is None or target is None:
        await call.answer("کشور یافت نشد.", show_alert=True)
        return

    sev_fa = _SEVERITY_FA.get(sev, "متوسط")
    sanction = Sanction(
        from_country=country.id,
        to_country=target.id,
        sanction_type=stype.value,
        description=f"{SANCTION_FA[stype]} از سوی {country.name_fa} علیه {target.name_fa}",
        active=True,
    )
    await dip_repo.add_sanction(session, sanction)
    await apply_sanction_effects(session, target, stype, sev)

    await call.answer("تحریم تأیید و اعمال شد ✅")
    await safe_edit(call,
        call.message.html_text + f"\n\n✅ <b>تأیید شد</b> (شدت: {sev_fa})"
    )

    x = f"{country.flag} {country.name_fa}"
    y = f"{target.flag} {target.name_fa}"
    caption = (
        "🔴 | فووووووووووری\n\n"
        f"📛 | دولت {x} امروز اعلام کرد که مجموعه‌ای از {SANCTION_FA[stype]} جدید را "
        f"علیه کشور {y} اعمال کرده است.\n\n"
        "❌ | این تصمیم در پی اختلافات اخیر میان این دو کشور اتخاذ شده است. خبر های بیشتر در "
        "رابطه با این موضوع در دست بررسی ست و به محض منتشر شدن، به استحضارتان خواهیم رساند."
    )
    if settings.news_diplomacy_channel_id is not None:
        stem = SANCTION_IMAGE_STEM.get(stype, "1")
        await send_specific_photo(
            bot, settings.news_diplomacy_channel_id,
            f"embargo:{stype.value}", "embargo", stem, caption,
        )
    await send_to_admin_group(
        bot,
        AdminGroupType.SANCTION_BILL,
        f"🚫 <b>تحریم تأیید و وضع شد</b>\nتحریم‌کننده: {x}\nهدف: {y}\nنوع: {SANCTION_FA[stype]}\nشدت: {sev_fa}",
    )

    # اطلاع به درخواست‌کننده و کشور هدف
    if country.owner_user_id:
        try:
            await bot.send_message(
                country.owner_user_id,
                f"✅ درخواست تحریم شما تأیید شد: <b>{SANCTION_FA[stype]}</b> علیه {y} (شدت {sev_fa}).",
            )
        except Exception:  # noqa: BLE001
            pass
    if target.owner_user_id:
        try:
            await bot.send_message(
                target.owner_user_id,
                f"🚨 کشور شما توسط {x} تحریم شد: <b>{SANCTION_FA[stype]}</b> (شدت {sev_fa}).",
            )
        except Exception:  # noqa: BLE001
            pass


@router.callback_query(F.data.startswith("sancno:"))
async def cb_sanction_reject(call: CallbackQuery, session: AsyncSession) -> None:
    """رد درخواست تحریم توسط مالک (v1.10.5)."""
    if not settings.is_owner(call.from_user.id):
        await call.answer("فقط مالک بازی می‌تواند رد کند.", show_alert=True)
        return
    _, from_id, to_id, stype_v = call.data.split(":")
    stype = SanctionType(stype_v)
    country = await countries_repo.get_country(session, int(from_id))
    target = await countries_repo.get_country(session, int(to_id))

    await call.answer("درخواست رد شد ❌")
    await safe_edit(call,call.message.html_text + "\n\n❌ <b>رد شد</b>")

    if country and country.owner_user_id:
        y = f"{target.flag} {target.name_fa}" if target else "کشور هدف"
        try:
            await bot.send_message(
                country.owner_user_id,
                f"❌ درخواست تحریم شما ({SANCTION_FA[stype]} علیه {y}) توسط مدیریت بازی رد شد.",
            )
        except Exception:  # noqa: BLE001
            pass
    await send_to_admin_group(
        bot,
        AdminGroupType.SANCTION_BILL,
        f"❌ <b>درخواست تحریم رد شد</b> (نوع: {SANCTION_FA[stype]}).",
    )


# ============================================================
#  🎤 سیستم سخنرانی و نقل قول (v1.5)
# ============================================================
@router.callback_query(F.data == "dip:speech")
async def cb_speech(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """شروع سخنرانی: درخواست متن."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call,NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "dip.speech"):
        return
    # کول‌داون بیانیه: هر ۱۰ دقیقه ۱ بیانیه (v1.9)
    mins = await _cooldown_remaining_min(
        session, country.id, "speech", SPEECH_COOLDOWN_MINUTES / 60
    )
    if mins > 0:
        await safe_edit(call,
            _cooldown_text("ارسال بیانیه", f"{fa_number(SPEECH_COOLDOWN_MINUTES)} دقیقه", mins),
            reply_markup=diplomacy_menu_kb(),
        )
        return
    await state.set_state(SpeechForm.entering_text)
    await safe_edit(call,
        "🎤 متن سخنرانی/بیانیه‌ی خود را وارد کنید:",
        reply_markup=_back_kb("menu:diplomacy"),
    )


@router.message(SpeechForm.entering_text, F.text)
async def msg_speech_text(message: Message, state: FSMContext) -> None:
    """ثبت متن سخنرانی و درخواست عکس."""
    await state.update_data(speech_text=message.text)
    await state.set_state(SpeechForm.entering_photo)
    await message.answer(
        "📸 حالا عکس رئیس‌جمهور را ارسال کنید:",
        reply_markup=_back_kb("speechback:text"),
    )


@router.callback_query(StateFilter(SpeechForm), F.data == "speechback:text")
async def cb_speech_back_text(call: CallbackQuery, state: FSMContext) -> None:
    """بازگشت به وارد کردن متن سخنرانی."""
    await call.answer()
    await state.set_state(SpeechForm.entering_text)
    await safe_edit(call,
        "🎤 متن سخنرانی/بیانیه‌ی خود را وارد کنید:",
        reply_markup=_back_kb("menu:diplomacy"),
    )


@router.message(SpeechForm.entering_photo, F.photo)
async def msg_speech_photo(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """انتشار سخنرانی (عکس + متن) در کانال دیپلماسی به‌همراه دکمه‌ی نقل قول."""
    data = await state.get_data()
    speech_text = data.get("speech_text", "")
    country = await get_player_country(session, db_user)
    await state.clear()
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        return

    if settings.news_diplomacy_channel_id is None:
        await message.answer("کانال دیپلماسی تنظیم نشده است.")
        return

    president = db_user.president_name or country.name_fa
    photo_id = message.photo[-1].file_id  # بزرگ‌ترین نسخه‌ی عکس

    # ابتدا رکورد سخنرانی ساخته می‌شود تا آی‌دی برای دکمه‌ی نقل قول داشته باشیم
    speech = Speech(speaker_country=country.id)
    session.add(speech)
    await session.flush()

    username = await _get_bot_username()
    is_un = (country.name_en == "UN")
    if is_un:
        caption = (
            "🎙 <b>بیانیه رسمی دبیرکل سازمان ملل متحد 🇺🇳</b>\n\n"
            f"متن بیانیه:\n{speech_text}"
        )
        log_text = (
            "🎙 <b>بیانیه رسمی دبیرکل سازمان ملل متحد 🇺🇳</b>\n\n"
            f"📝 متن:\n{speech_text}"
        )
    else:
        caption = (
            f"📢 یک بیانیه از طرف رئیس‌جمهور <b>{president}</b> —- منتشر شد!\n\n"
            f"متن سخنرانی:\n{speech_text}"
        )
        log_text = (
            f"📢 <b>بیانیه</b>\n"
            f"کشور: {country.flag} {country.name_fa} (رئیس‌جمهور {president})\n\n"
            f"📝 متن:\n{speech_text}"
        )

    quote_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="💬 نقل قول",
            url=f"https://t.me/{username}?start=quote_{speech.id}",
            style=STYLE_MAIN,
        )
    ]])
    sent = await bot.send_photo(
        settings.news_diplomacy_channel_id,
        photo=photo_id,
        caption=caption,
        reply_markup=quote_kb,
    )
    # ذخیره‌ی آی‌دی پیام کانال برای ریپلای نقل قول‌ها
    speech.channel_message_id = sent.message_id

    # ثبت کول‌داون بیانیه: هر ۱۰ دقیقه ۱ بیانیه (v1.9)
    await cd_repo.touch(session, country.id, "speech")

    # لاگ بیانیه به گروه لاگ مدیران (v1.9)
    await send_log(bot, log_text)

    from ..keyboards.united_nations import un_main_menu_kb
    resp_kb = un_main_menu_kb() if is_un else diplomacy_menu_kb()
    await message.answer("✅ سخنرانی شما در کانال دیپلماسی منتشر شد.", reply_markup=resp_kb)


@router.message(SpeechForm.quoting, F.text)
async def msg_speech_quote(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """انتشار نقل قول در کانال دیپلماسی به‌صورت ریپلای به سخنرانی اصلی."""
    data = await state.get_data()
    speech_id = data.get("quote_speech_id")
    country = await get_player_country(session, db_user)
    await state.clear()
    if country is None or speech_id is None:
        await message.answer("خطا در ثبت نقل قول.")
        return

    speech = await session.get(Speech, speech_id)
    if speech is None or settings.news_diplomacy_channel_id is None:
        await message.answer("سخنرانی موردنظر یافت نشد.")
        return

    # نام رئیس‌جمهور گوینده‌ی اصلی
    speaker_country = await countries_repo.get_country(session, speech.speaker_country)
    speaker_name = "—"
    if speaker_country and speaker_country.owner_user_id:
        from ..database.repositories import users as users_repo
        speaker_user = await users_repo.get_user(session, speaker_country.owner_user_id)
        speaker_name = (speaker_user.president_name if speaker_user else None) or (
            speaker_country.name_fa if speaker_country else "—"
        )

    quoter_name = db_user.president_name or country.name_fa

    speaker_desc = "دبیرکل سازمان ملل متحد 🇺🇳" if (speaker_country and speaker_country.name_en == "UN") else f"رئیس‌جمهور <b>{speaker_name}</b>"
    quoter_desc = "دبیرکل سازمان ملل متحد 🇺🇳" if country.name_en == "UN" else f"رئیس‌جمهور <b>{quoter_name}</b>"

    text = (
        f"🗣 بیانیه‌ی {quoter_desc} —- به نقل از {speaker_desc}:\n\n"
        f"{message.text}"
    )
    try:
        await bot.send_message(
            settings.news_diplomacy_channel_id,
            text,
            reply_to_message_id=speech.channel_message_id,
        )
        from ..keyboards.united_nations import un_main_menu_kb
        resp_kb = un_main_menu_kb() if country.name_en == "UN" else diplomacy_menu_kb()
        await message.answer("✅ نقل قول شما منتشر شد.", reply_markup=resp_kb)
    except Exception:  # noqa: BLE001
        await message.answer("⚠️ خطا در انتشار نقل قول.")


# ============================================================
#  رله‌ی پیام‌ها (در حالت پیش‌فرض): تماس تلفنی، چت دیدار دوجانبه و چندجانبه
# ============================================================
def _reply_prefix(message: Message) -> str:
    """
    اگر این پیام ریپلای به یک پیامِ نشست باشد، یک سرخط «در پاسخ به ...» می‌سازد (v1.10.1).
    این کار باعث می‌شود ریپلای‌کردن روی پیام طرف مقابل، برای او معنادار رله شود.
    """
    replied = message.reply_to_message
    if replied is None:
        return ""
    quoted = (replied.text or replied.caption or "").strip()
    if not quoted:
        return ""
    # حذف پیشوند رله‌ی قبلی (مثل «🤝 پرچم نام: ») برای خلاصه‌ی تمیزتر
    if ": " in quoted[:60]:
        quoted = quoted.split(": ", 1)[1]
    snippet = quoted[:50] + ("…" if len(quoted) > 50 else "")
    return f"↩️ در پاسخ به «{snippet}»:\n"


@router.message(StateFilter(None), F.text & ~F.text.startswith("/"))
async def relay_chat_message(message: Message, session: AsyncSession, db_user: User) -> None:
    """
    اگر کاربر در یک تماس تلفنی، دیدار دوجانبه یا نشست چندجانبه‌ی فعال باشد،
    پیام متنی او به طرف(های) مقابل رله می‌شود (شامل ریپلای). در غیر این صورت نادیده گرفته می‌شود.
    نکته (v1.10.1): در هر رله زمان آخرین پیام نشست به‌روز می‌شود تا تایم‌اوت سکوت درست کار کند،
    و خطای ارسال هرگز جریان را متوقف نمی‌کند.
    """
    country = await get_player_country(session, db_user)
    if country is None:
        return

    now = _utcnow()
    prefix = _reply_prefix(message)
    text = message.text or ""

    # ۱) تماس تلفنی فعال
    active = await dip_repo.get_active_call_for_country(session, country.id)
    if active is not None:
        if _aware(active.ends_at) and _aware(active.ends_at) <= now:
            active.status = DiplomacyStatus.COMPLETED
            await message.answer("📵 زمان تماس به پایان رسید.")
            return
        partner_id = (
            active.callee_country if active.caller_country == country.id else active.caller_country
        )
        partner = await countries_repo.get_country(session, partner_id)
        await dip_repo.add_call_message(session, active.id, country.id, text)
        if partner and partner.owner_user_id:
            try:
                await bot.send_message(
                    partner.owner_user_id,
                    f"📞 {country.flag} {country.name_fa}: {prefix}{text}",
                )
            except Exception:  # noqa: BLE001
                pass
        await send_log(bot, f"📞 [{country.name_fa} → {partner.name_fa if partner else '?'}]: {text}")
        return

    # ۲) دیدار دوجانبه‌ی فعال (پس از رسیدن مسافر، تا پایان جلسه) → چت با طرف مقابل
    meeting = await dip_repo.get_active_meeting_for_country(session, country.id)
    if meeting is not None:
        arrived = not (_aware(meeting.travel_eta) and _aware(meeting.travel_eta) > now)
        ended = _aware(meeting.meeting_ends_at) and _aware(meeting.meeting_ends_at) <= now
        if not arrived:
            await message.answer("✈️ هنوز به مقصد نرسیده‌اید؛ نشست پس از رسیدن آغاز می‌شود.")
            return
        if not ended:
            meeting.last_msg_at = now  # تایم‌اوت سکوت (v1.10.1)
            partner_id = (
                meeting.host_country if meeting.traveler_country == country.id else meeting.traveler_country
            )
            partner = await countries_repo.get_country(session, partner_id)
            if partner and partner.owner_user_id:
                try:
                    await bot.send_message(
                        partner.owner_user_id,
                        f"🤝 {country.flag} {country.name_fa}: {prefix}{text}",
                    )
                except Exception:  # noqa: BLE001
                    pass
            # لاگ صحبت‌های دیدار دوجانبه به گروه لاگ (v1.6)
            await send_log(
                bot,
                f"🤝 [{country.name_fa} → {partner.name_fa if partner else '?'}]: {text}",
            )
            return

    # ۳) نشست چندجانبه‌ی فعال → چت با همه‌ی کشورهای حاضر
    group = await dip_repo.get_active_group_meeting_for_country(session, country.id)
    if group is not None:
        ended = _aware(group.meeting_ends_at) and _aware(group.meeting_ends_at) <= now
        if not ended:
            group.last_msg_at = now  # تایم‌اوت سکوت (v1.10.1)
            member_ids = await dip_repo.group_member_country_ids(session, group)
            for cid in member_ids:
                if cid == country.id:
                    continue
                member = await countries_repo.get_country(session, cid)
                if member and member.owner_user_id:
                    try:
                        await bot.send_message(
                            member.owner_user_id,
                            f"👥 {country.flag} {country.name_fa}: {prefix}{text}",
                        )
                    except Exception:  # noqa: BLE001
                        pass
            # لاگ صحبت‌های نشست چندجانبه به گروه لاگ (v1.6)
            await send_log(
                bot,
                f"👥 [{group.title}] {country.name_fa}: {text}",
            )
            return

    # ۴) مجمع عمومی سازمان ملل متحد (صحن علنی تالار نیویورک)
    from ..database.repositories import united_nations as un_repo
    from ..keyboards.united_nations import speech_reactions_kb
    active_asmb = await un_repo.get_active_session(session)
    if active_asmb is not None and active_asmb.status == "active":
        is_un_sec = (country.name_en == "UN")
        is_active_speaker = (active_asmb.current_speaker_country_id == country.id)

        if is_active_speaker or is_un_sec:
            active_q = await un_repo.get_active_speech(session, active_asmb.id)
            if active_q and is_active_speaker:
                await un_repo.append_speech_transcript(session, active_q.id, text)

            speaker_title = "دبیرکل سازمان ملل متحد" if is_un_sec else f"رهبر {country.flag} {country.name_fa}"
            hall_parts = await un_repo.list_participants_by_status(session, active_asmb.id, "inside_hall")

            reactions_kb = speech_reactions_kb(active_asmb.id) if is_active_speaker else None

            for p in hall_parts:
                if p.country_id == country.id:
                    continue
                member = await countries_repo.get_country(session, p.country_id)
                if member and member.owner_user_id:
                    try:
                        await bot.send_message(
                            member.owner_user_id,
                            f"🎙 <b>تریبون مجمع عمومی — {speaker_title}:</b>\n\n{prefix}{text}",
                            reply_markup=reactions_kb,
                        )
                    except Exception:
                        pass

            if not is_un_sec:
                un_c = await countries_repo.get_country_by_name(session, "UN")
                if un_c and un_c.owner_user_id:
                    try:
                        await bot.send_message(
                            un_c.owner_user_id,
                            f"🎙 <b>تریبون مجمع عمومی — {speaker_title}:</b>\n\n{prefix}{text}",
                        )
                    except Exception:
                        pass

            await send_log(bot, f"🏛 [مجمع عمومی] {country.name_fa}: {text}")
            return

    # ۵) دیوان بین‌المللی دادگستری (دادگاه لاهه)
    court_pair = await un_repo.get_active_case_for_party(session, country.id)
    if court_pair is not None:
        case, party = court_pair
        if party.can_speak or case.current_turn_country_id in (None, country.id):
            court_parties = await un_repo.list_court_parties(session, case.id)
            role_fa = "شاکی" if party.role == "claimant" else ("متهم" if party.role == "defendant" else "حاضر در دادگاه")
            for cp in court_parties:
                if cp.country_id == country.id:
                    continue
                c = await countries_repo.get_country(session, cp.country_id)
                if c and c.owner_user_id:
                    try:
                        await bot.send_message(
                            c.owner_user_id,
                            f"⚖️ <b>جلسه دادگاه لاهه ({case.case_number}) — {country.flag} {country.name_fa} ({role_fa}):</b>\n\n{prefix}{text}",
                        )
                    except Exception:
                        pass

            un_c = await countries_repo.get_country_by_name(session, "UN")
            if un_c and un_c.owner_user_id and un_c.id != country.id:
                try:
                    await bot.send_message(
                        un_c.owner_user_id,
                        f"⚖️ <b>جلسه دادگاه لاهه ({case.case_number}) — {country.flag} {country.name_fa} ({role_fa}):</b>\n\n{prefix}{text}",
                    )
                except Exception:
                    pass
            await send_log(bot, f"⚖️ [دادگاه {case.case_number}] {country.name_fa}: {text}")
            return


@router.message(StateFilter(None), F.photo)
async def relay_speech_photo(message: Message, session: AsyncSession, db_user: User) -> None:
    """رله عکس‌های ارسالی سخنران در حین سخنرانی ۵ دقیقه‌ای مجمع عمومی."""
    country = await get_player_country(session, db_user)
    if country is None:
        return

    from ..database.repositories import united_nations as un_repo
    active_asmb = await un_repo.get_active_session(session)
    if not active_asmb or active_asmb.status != "active":
        return

    is_un_sec = (country.name_en == "UN")
    is_active_speaker = (active_asmb.current_speaker_country_id == country.id)
    if not (is_active_speaker or is_un_sec):
        return

    caption = message.caption or ""
    active_q = await un_repo.get_active_speech(session, active_asmb.id)
    if active_q and is_active_speaker and caption:
        await un_repo.append_speech_transcript(session, active_q.id, f"[تصویر با شرح]: {caption}")

    from ..keyboards.united_nations import speech_reactions_kb

    photo_id = message.photo[-1].file_id
    speaker_title = "دبیرکل سازمان ملل متحد" if is_un_sec else f"رهبر {country.flag} {country.name_fa}"
    full_caption = f"🎙 <b>تریبون مجمع عمومی — {speaker_title}:</b>\n\n{caption}".strip()
    reactions_kb = speech_reactions_kb(active_asmb.id) if is_active_speaker else None

    hall_parts = await un_repo.list_participants_by_status(session, active_asmb.id, "inside_hall")
    for p in hall_parts:
        if p.country_id == country.id:
            continue
        member = await countries_repo.get_country(session, p.country_id)
        if member and member.owner_user_id:
            try:
                await bot.send_photo(
                    member.owner_user_id, photo_id, caption=full_caption, reply_markup=reactions_kb
                )
            except Exception:
                pass

    if not is_un_sec:
        un_c = await countries_repo.get_country_by_name(session, "UN")
        if un_c and un_c.owner_user_id:
            try:
                await bot.send_photo(un_c.owner_user_id, photo_id, caption=full_caption)
            except Exception:
                pass
