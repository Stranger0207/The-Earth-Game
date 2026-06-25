"""
هندلر بخش دیپلماسی: نامه، تماس تلفنی، دیدار حضوری، قرارداد و تحریم.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import MEETING_DURATION_MINUTES, PHONE_CALL_DURATION_MINUTES
from ..database.models import Contract, GroupMeeting, Meeting, PhoneCall, Sanction, Speech, User
from ..database.repositories import countries as countries_repo
from ..database.repositories import diplomacy as dip_repo
from ..enums import SANCTION_FA, DiplomacyStatus, NewsCategory, SanctionType
from ..keyboards.common import countries_kb
from ..keyboards.diplomacy import (
    diplomacy_menu_kb,
    end_call_kb,
    sanction_menu_kb,
    sanction_types_kb,
)
from ..loader import bot
from ..services.ai import evaluators
from ..services.media import send_photo_news, send_specific_photo
from ..services.news_service import publish_news, send_log
from ..services.sanction_service import apply_sanction_effects
from ..database.repositories import users as users_repo
from ..states import CallForm, ContractForm, LetterForm, MeetingForm, SanctionForm, SpeechForm
from ..utils.numbers import fa_number
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK, header
from .deps import NO_COUNTRY_TEXT, get_player_country

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


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _other_countries(session: AsyncSession, country_id: int):
    """فهرست کشورهای دیگر (به‌جز خودِ کشور بازیکن)."""
    countries = await countries_repo.list_countries(session)
    return [c for c in countries if c.id != country_id]


# ============================================================
#  ✉️ نامه
# ============================================================
@router.callback_query(F.data == "dip:letter")
async def cb_letter(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    await state.set_state(LetterForm.choosing_target)
    others = await _other_countries(session, country.id)
    await call.message.edit_text(
        "✉️ نامه را به کدام کشور می‌فرستید؟",
        reply_markup=countries_kb(others, prefix="letter_to", columns=2, back_data="menu:diplomacy"),
    )


@router.callback_query(LetterForm.choosing_target, F.data.startswith("letter_to:"))
async def cb_letter_to(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.update_data(target_id=int(call.data.split(":")[1]))
    await state.set_state(LetterForm.writing_body)
    await call.message.edit_text("متن نامه را بنویسید:")


@router.message(LetterForm.writing_body, F.text)
async def msg_letter_body(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    data = await state.get_data()
    country = await get_player_country(session, db_user)
    target = await countries_repo.get_country(session, data["target_id"])
    await state.clear()
    if country is None or target is None:
        await message.answer("خطا در ارسال نامه.")
        return

    if target.owner_user_id:
        try:
            await bot.send_message(
                target.owner_user_id,
                f"✉️ <b>نامه از {country.flag} {country.name_fa}</b>\n\n{message.text}",
            )
        except Exception:  # noqa: BLE001
            pass
    await message.answer("✅ نامه ارسال شد.", reply_markup=diplomacy_menu_kb())


# ============================================================
#  📞 تماس تلفنی (حداکثر ۵ دقیقه، بدون قرارداد)
# ============================================================
@router.callback_query(F.data == "dip:call")
async def cb_call(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    await state.set_state(CallForm.choosing_target)
    others = await _other_countries(session, country.id)
    await call.message.edit_text(
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
        await call.message.edit_text("امکان تماس با این کشور وجود ندارد (بدون رهبر).")
        return

    phone_call = PhoneCall(
        caller_country=country.id,
        callee_country=target.id,
        status=DiplomacyStatus.PENDING,
    )
    await dip_repo.add_call(session, phone_call)
    await session.flush()

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
    await call.message.edit_text("📞 درخواست تماس ارسال شد. منتظر پاسخ طرف مقابل بمانید.")


@router.callback_query(F.data.startswith("call_accept:"))
async def cb_call_accept(call: CallbackQuery, session: AsyncSession) -> None:
    call_id = int(call.data.split(":")[1])
    phone_call = await dip_repo.get_call(session, call_id)
    if phone_call is None or phone_call.status != DiplomacyStatus.PENDING:
        await call.answer("این تماس دیگر معتبر نیست.", show_alert=True)
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
#  🤝 دیدار حضوری
# ============================================================
@router.callback_query(F.data == "dip:meeting")
async def cb_meeting(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """انتخاب نوع دیدار: دوجانبه یا چندجانبه."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤝 دیدار دوجانبه", callback_data="meet_kind:bi", style=STYLE_MAIN)],
        [InlineKeyboardButton(text="👥 دیدار چندجانبه", callback_data="meet_kind:multi", style=STYLE_MAIN)],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu:diplomacy", style=STYLE_MAIN)],
    ])
    await call.message.edit_text(
        "🤝 <b>دیدار حضوری</b>\n\nنوع دیدار را انتخاب کنید:", reply_markup=kb
    )


@router.callback_query(F.data == "meet_kind:bi")
async def cb_meeting_bi(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """دیدار دوجانبه: انتخاب کشور مقصد (جریان قبلی)."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    await state.set_state(MeetingForm.choosing_target)
    others = await _other_countries(session, country.id)
    await call.message.edit_text(
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
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    await state.set_state(MeetingForm.selecting_members)
    await state.update_data(selected=[])
    others = await _other_countries(session, country.id)
    await call.message.edit_text(
        "👥 کشورهای شرکت‌کننده در نشست را انتخاب کنید (می‌توانید چند کشور را تیک بزنید):",
        reply_markup=_group_select_kb(others, set()),
    )


@router.callback_query(MeetingForm.selecting_members, F.data.startswith("meet_toggle:"))
async def cb_meeting_toggle(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """افزودن/حذف یک کشور از فهرست انتخاب نشست چندجانبه."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
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
    await call.message.edit_text(
        f"👥 {fa_number(len(selected))} کشور انتخاب شد.\n\n"
        "عنوان نشست چندجانبه را وارد کنید (مثلاً «نشست امنیت منطقه‌ای»):"
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

    meeting = GroupMeeting(
        host_country=country.id,
        title=message.text.strip(),
        status=DiplomacyStatus.PENDING,
    )
    await dip_repo.add_group_meeting(session, meeting)
    await session.flush()

    invited_names = []
    for cid in selected:
        await dip_repo.add_group_participant(session, meeting.id, cid)
        target = await countries_repo.get_country(session, cid)
        if target is None:
            continue
        invited_names.append(f"{target.flag} {target.name_fa}")
        if target.owner_user_id:
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

    await message.answer(
        f"👥 نشست «{meeting.title}» ساخته شد و دعوت برای کشورهای زیر ارسال گردید:\n"
        + "، ".join(invited_names)
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

    await call.answer("پذیرفته شد ✅")
    # تخمین زمان پرواز به کشور میزبان توسط AI
    host = await countries_repo.get_country(session, meeting.host_country)
    eta_data = await evaluators.estimate_travel_time(
        country.name_fa, host.name_fa if host else "?"
    )
    minutes = int(eta_data.get("travel_minutes", 20) or 20)
    minutes = max(5, min(minutes, 90))
    participant.response = DiplomacyStatus.ACTIVE
    participant.travel_eta = _utcnow() + timedelta(minutes=minutes)

    await call.message.edit_text(
        call.message.html_text
        + f"\n\n✈️ <b>پذیرفتید</b> — پرواز به میزبان آغاز شد (زمان رسیدن حدود {fa_number(minutes)} دقیقه)"
    )

    # خبر سفر دیپلماتیک (نشست چندجانبه) در کانال دیپلماسی: عکس + فرمت سفر (v1.6)
    if settings.news_diplomacy_channel_id is not None:
        traveler_pres = await _president_name(session, country)
        x = f"{country.flag} {country.name_fa}"
        b = f"{host.flag} {host.name_fa}" if host else "?"
        caption = (
            "⚪ | اطلاع رسانی سفر مقامات دیپلمات\n\n"
            f"✈ | ریاست جمهور محترم کشور {x} ، جناب آقای {traveler_pres} کشور خود را "
            f"به مقصد کشور {b} برای شرکت در نشست «{meeting.title}» ترک کرد.\n"
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
    await call.message.edit_text(call.message.html_text + "\n\n❌ <b>رد کردید</b>")
    await _maybe_schedule_group_meeting(session, meeting)


@router.callback_query(MeetingForm.choosing_target, F.data.startswith("meet_to:"))
async def cb_meet_to(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    await state.clear()
    country = await get_player_country(session, db_user)
    target = await countries_repo.get_country(session, int(call.data.split(":")[1]))
    if country is None or target is None or target.owner_user_id is None:
        await call.message.edit_text("امکان دیدار با این کشور وجود ندارد (بدون رهبر).")
        return

    meeting = Meeting(
        traveler_country=country.id,
        host_country=target.id,
        status=DiplomacyStatus.PENDING,
    )
    await dip_repo.add_meeting(session, meeting)
    await session.flush()

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
    await call.message.edit_text("🤝 درخواست سفر ارسال شد. منتظر پذیرش طرف مقابل بمانید.")


@router.callback_query(F.data.startswith("meet_accept:"))
async def cb_meet_accept(call: CallbackQuery, session: AsyncSession) -> None:
    meeting_id = int(call.data.split(":")[1])
    meeting = await dip_repo.get_meeting(session, meeting_id)
    if meeting is None or meeting.status != DiplomacyStatus.PENDING:
        await call.answer("این درخواست دیگر معتبر نیست.", show_alert=True)
        return

    traveler = await countries_repo.get_country(session, meeting.traveler_country)
    host = await countries_repo.get_country(session, meeting.host_country)
    await call.answer("سفر پذیرفته شد")

    # تخمین زمان سفر توسط AI
    eta_data = await evaluators.estimate_travel_time(
        traveler.name_fa if traveler else "?", host.name_fa if host else "?"
    )
    minutes = int(eta_data.get("travel_minutes", 20) or 20)
    minutes = max(5, min(minutes, 90))
    note = eta_data.get("note", "")

    meeting.status = DiplomacyStatus.ACTIVE
    meeting.travel_eta = _utcnow() + timedelta(minutes=minutes)
    meeting.meeting_ends_at = meeting.travel_eta + timedelta(minutes=MEETING_DURATION_MINUTES)
    meeting.travel_note = note

    msg = (
        f"✈️ سفر آغاز شد. زمان تقریبی رسیدن: {fa_number(minutes)} دقیقه.\n"
        f"{note}\n\n"
        f"پس از رسیدن، دیدار به مدت {MEETING_DURATION_MINUTES} دقیقه فعال می‌شود.\n"
        "💬 در طول دیدار، هر پیامی که بنویسید مستقیماً برای طرف مقابل ارسال می‌شود.\n"
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
        caption = (
            "⚪ | اطلاع رسانی سفر مقامات دیپلمات\n\n"
            f"✈ | ریاست جمهور محترم کشور {x} ، جناب آقای {traveler_pres} کشور خود را "
            f"به مقصد کشور {b} برای برگزاری دیدار حضوری ترک کرد.\n"
            f"⏳ | مدت زمان پرواز: {fa_number(minutes)} دقیقه"
        )
        await send_photo_news(
            bot, settings.news_diplomacy_channel_id, "diplomacy_travel", caption
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

    # ۲) نشست چندجانبه‌ی فعال → انتخاب طرف قرارداد از میان حاضران
    group = await dip_repo.get_active_group_meeting_for_country(session, country.id)
    if group is not None:
        member_ids = await dip_repo.group_member_country_ids(session, group)
        others = []
        for cid in member_ids:
            if cid == country.id:
                continue
            c = await countries_repo.get_country(session, cid)
            if c:
                others.append(c)
        if not others:
            await message.answer("کشور دیگری در نشست حاضر نیست.")
            return
        await message.answer(
            "📜 با کدام کشورِ حاضر در نشست قرارداد می‌بندید؟",
            reply_markup=countries_kb(others, prefix="contract_with", columns=2),
        )
        return

    await message.answer("برای بستن قرارداد باید در یک دیدار حضوری فعال (دوجانبه یا چندجانبه) باشید.")


@router.callback_query(F.data.startswith("contract_with:"))
async def cb_contract_with(call: CallbackQuery, state: FSMContext) -> None:
    """انتخاب طرف قرارداد در نشست چندجانبه."""
    await call.answer()
    other_id = int(call.data.split(":")[1])
    await state.update_data(other_id=other_id)
    await state.set_state(ContractForm.entering_title)
    await call.message.edit_text("📜 عنوان قرارداد را وارد کنید:")


@router.message(ContractForm.entering_title, F.text)
async def msg_contract_title(message: Message, state: FSMContext) -> None:
    await state.update_data(title=message.text.strip())
    await state.set_state(ContractForm.entering_body)
    await message.answer(
        "متن کامل قرارداد را بنویسید (مفاد، تعهدات طرفین، تأمین مالی و ...):"
    )


@router.message(ContractForm.entering_body, F.text)
async def msg_contract_body(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    data = await state.get_data()
    country = await get_player_country(session, db_user)
    other_id = data.get("other_id")
    await state.clear()
    if country is None or other_id is None:
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
    contract.signed_b = True
    contract.status = DiplomacyStatus.ACTIVE
    await call.answer("امضا شد ✅")
    await call.message.edit_text(call.message.html_text + "\n\n✅ <b>قرارداد امضا و فعال شد</b>")

    a = await countries_repo.get_country(session, contract.country_a)
    b = await countries_repo.get_country(session, contract.country_b)
    if a and a.owner_user_id:
        try:
            await bot.send_message(a.owner_user_id, f"✅ قرارداد «{contract.title}» امضا و فعال شد.")
        except Exception:  # noqa: BLE001
            pass
    await publish_news(
        bot,
        NewsCategory.DIPLOMACY,
        f"🕊 قراردادی میان {a.name_fa if a else '?'} و {b.name_fa if b else '?'} منعقد شد.",
    )


@router.callback_query(F.data.startswith("reject_contract:"))
async def cb_reject_contract(call: CallbackQuery, session: AsyncSession) -> None:
    contract_id = int(call.data.split(":")[1])
    contract = await dip_repo.get_contract(session, contract_id)
    if contract is None or contract.status != DiplomacyStatus.PENDING:
        await call.answer()
        return
    contract.status = DiplomacyStatus.REJECTED
    await call.answer("رد شد")
    await call.message.edit_text(call.message.html_text + "\n\n❌ <b>رد شد</b>")


@router.callback_query(F.data == "dip:contracts")
async def cb_contracts(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    contracts = await dip_repo.list_contracts_for_country(session, country.id, only_active=True)
    if not contracts:
        await call.message.edit_text("📜 قرارداد فعالی ندارید.", reply_markup=diplomacy_menu_kb())
        return
    lines = ["📜 <b>قراردادهای فعال:</b>", ""]
    for c in contracts:
        a = await countries_repo.get_country(session, c.country_a)
        b = await countries_repo.get_country(session, c.country_b)
        lines.append(f"• «{c.title}» — {a.name_fa if a else '?'} ↔ {b.name_fa if b else '?'}")
    await call.message.edit_text("\n".join(lines), reply_markup=diplomacy_menu_kb())


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
async def cb_sanction(call: CallbackQuery, state: FSMContext) -> None:
    """منوی تحریم (v1.7)."""
    await call.answer()
    await state.clear()
    await call.message.edit_text(
        header("تحریم", "🚫") + "\n\nیک گزینه را انتخاب کنید:", reply_markup=sanction_menu_kb()
    )


@router.callback_query(F.data == "sanc:impose")
async def cb_sanction_impose(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """وضع تحریم: انتخاب کشور هدف (جریان قبلی)."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    others = await _other_countries(session, country.id)
    await call.message.edit_text(
        "🚫 کدام کشور را تحریم می‌کنید؟",
        reply_markup=countries_kb(others, prefix="sanction_to", columns=2, back_data="dip:sanction"),
    )


@router.callback_query(F.data == "sanc:imposed")
async def cb_sanction_imposed(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """فهرست تحریم‌هایی که این کشور وضع کرده است."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    sanctions = await dip_repo.list_sanctions_by(session, country.id)
    if not sanctions:
        await call.message.edit_text("📋 شما هیچ تحریمی وضع نکرده‌اید.", reply_markup=sanction_menu_kb())
        return
    lines = ["📋 <b>تحریم‌های وضع‌شده توسط شما</b>", ""]
    for s in sanctions:
        target = await countries_repo.get_country(session, s.to_country)
        try:
            stype_fa = SANCTION_FA[SanctionType(s.sanction_type)]
        except (ValueError, KeyError):
            stype_fa = s.sanction_type
        lines.append(f"• {target.flag if target else ''} {target.name_fa if target else '?'} — {stype_fa}")
    await call.message.edit_text("\n".join(lines), reply_markup=sanction_menu_kb())


@router.callback_query(F.data == "sanc:mine")
async def cb_sanction_mine(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """فهرست تحریم‌هایی که دیگران علیه این کشور وضع کرده‌اند."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    sanctions = await dip_repo.list_sanctions_against(session, country.id)
    if not sanctions:
        await call.message.edit_text("🎯 هیچ کشوری شما را تحریم نکرده است.", reply_markup=sanction_menu_kb())
        return
    lines = ["🎯 <b>تحریم‌های علیه کشور شما</b>", ""]
    for s in sanctions:
        src = await countries_repo.get_country(session, s.from_country)
        try:
            stype_fa = SANCTION_FA[SanctionType(s.sanction_type)]
        except (ValueError, KeyError):
            stype_fa = s.sanction_type
        lines.append(f"• {src.flag if src else ''} {src.name_fa if src else '?'} — {stype_fa}")
    await call.message.edit_text("\n".join(lines), reply_markup=sanction_menu_kb())


@router.callback_query(F.data == "sanc:cancel")
async def cb_sanction_cancel_list(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """فهرست تحریم‌های وضع‌شده برای لغو."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    sanctions = await dip_repo.list_sanctions_by(session, country.id)
    if not sanctions:
        await call.message.edit_text("♻️ تحریمی برای لغو ندارید.", reply_markup=sanction_menu_kb())
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
    await call.message.edit_text("♻️ کدام تحریم را لغو می‌کنید؟", reply_markup=builder.as_markup())


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
    await call.message.edit_text(
        f"✅ تحریم علیه {target.flag if target else ''} {target.name_fa if target else '?'} لغو شد.",
        reply_markup=sanction_menu_kb(),
    )


@router.callback_query(F.data.startswith("sanction_to:"))
async def cb_sanction_to(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """انتخاب نوع تحریم (v1.5)."""
    await call.answer()
    target_id = int(call.data.split(":")[1])
    await state.update_data(sanction_target=target_id)
    await state.set_state(SanctionForm.choosing_type)
    target = await countries_repo.get_country(session, target_id)
    await call.message.edit_text(
        f"نوع تحریم علیه {target.flag} {target.name_fa} را انتخاب کنید:",
        reply_markup=sanction_types_kb(),
    )


@router.callback_query(SanctionForm.choosing_type, F.data.startswith("sanc_type:"))
async def cb_sanction_type(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """سنجش منطقی‌بودن تحریم و اعمال اثرات در صورت قابل‌اجرا بودن (v1.5)."""
    await call.answer()
    stype = SanctionType(call.data.split(":")[1])
    data = await state.get_data()
    country = await get_player_country(session, db_user)
    target = await countries_repo.get_country(session, data["sanction_target"])
    await state.clear()
    if country is None or target is None:
        await call.message.edit_text("خطا.")
        return

    await call.message.edit_text("⏳ در حال بررسی امکان‌پذیری تحریم...")
    verdict = await evaluators.evaluate_sanction(
        session, country.id, target.id, SANCTION_FA[stype]
    )

    # تحریم غیرمنطقی/غیرقابل‌اجرا (مثل تحریم آمریکا توسط ایران)
    if verdict.get("feasible") is False:
        reason = verdict.get("reason") or "این تحریم اهرم واقعی بر کشور هدف ندارد."
        await call.message.edit_text(
            f"⛔️ <b>تحریم غیرمنطقی و غیرقابل‌اجراست</b>\n\n"
            f"دلیل: {reason}",
            reply_markup=diplomacy_menu_kb(),
        )
        return

    severity = verdict.get("severity", "medium")
    sanction = Sanction(
        from_country=country.id,
        to_country=target.id,
        sanction_type=stype.value,
        description=f"{SANCTION_FA[stype]} از سوی {country.name_fa} علیه {target.name_fa}",
        active=True,
    )
    await dip_repo.add_sanction(session, sanction)
    # اعمال اثرات واقعی روی کشور هدف
    await apply_sanction_effects(session, target, stype, severity)

    sev_fa = {"low": "خفیف", "medium": "متوسط", "high": "شدید"}.get(severity, "متوسط")
    await call.message.edit_text(
        f"🚫 <b>{SANCTION_FA[stype]}</b> علیه {target.flag} {target.name_fa} اعمال شد.\n"
        f"شدت تأثیر: {sev_fa}\n"
        "اثرات این تحریم روی اقتصاد، رضایت و ثبات کشور هدف اعمال شد.",
        reply_markup=sanction_menu_kb(),
    )

    # خبر تحریم با عکس مخصوص همان نوع تحریم در کانال دیپلماسی (v1.7)
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
    # لاگ تحریم به گروه لاگ
    await send_log(
        bot,
        f"🚫 <b>تحریم وضع شد</b>\nتحریم‌کننده: {x}\nهدف: {y}\nنوع: {SANCTION_FA[stype]}\nشدت: {sev_fa}",
    )

    # اطلاع به کشور هدف
    if target.owner_user_id:
        try:
            await bot.send_message(
                target.owner_user_id,
                f"🚨 کشور شما توسط {country.flag} {country.name_fa} تحریم شد: "
                f"<b>{SANCTION_FA[stype]}</b> (شدت {sev_fa}).",
            )
        except Exception:  # noqa: BLE001
            pass

    president = db_user.president_name or country.name_fa
    await publish_news(
        bot,
        NewsCategory.DIPLOMACY,
        f"🚫 {country.flag} {country.name_fa} به ریاست‌جمهوری {president} "
        f"کشور {target.flag} {target.name_fa} را تحت «{SANCTION_FA[stype]}» قرار داد.",
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
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    await state.set_state(SpeechForm.entering_text)
    await call.message.edit_text("🎤 متن سخنرانی/بیانیه‌ی خود را وارد کنید:")


@router.message(SpeechForm.entering_text, F.text)
async def msg_speech_text(message: Message, state: FSMContext) -> None:
    """ثبت متن سخنرانی و درخواست عکس."""
    await state.update_data(speech_text=message.text)
    await state.set_state(SpeechForm.entering_photo)
    await message.answer("📸 حالا عکس رئیس‌جمهور را ارسال کنید:")


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
    caption = (
        f"📢 یک بیانیه از طرف رئیس‌جمهور <b>{president}</b> —- منتشر شد!\n\n"
        f"متن سخنرانی:\n{speech_text}"
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

    await message.answer("✅ سخنرانی شما در کانال دیپلماسی منتشر شد.", reply_markup=diplomacy_menu_kb())


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
    text = (
        f"🗣 بیانیه‌ی رئیس‌جمهور <b>{quoter_name}</b> —- به نقل از رئیس‌جمهور <b>{speaker_name}</b>:\n\n"
        f"{message.text}"
    )
    try:
        await bot.send_message(
            settings.news_diplomacy_channel_id,
            text,
            reply_to_message_id=speech.channel_message_id,
        )
        await message.answer("✅ نقل قول شما منتشر شد.", reply_markup=diplomacy_menu_kb())
    except Exception:  # noqa: BLE001
        await message.answer("⚠️ خطا در انتشار نقل قول.")


# ============================================================
#  رله‌ی پیام‌ها (در حالت پیش‌فرض): تماس تلفنی، چت دیدار دوجانبه و چندجانبه
# ============================================================
@router.message(StateFilter(None), F.text & ~F.text.startswith("/"))
async def relay_chat_message(message: Message, session: AsyncSession, db_user: User) -> None:
    """
    اگر کاربر در یک تماس تلفنی، دیدار دوجانبه یا نشست چندجانبه‌ی فعال باشد،
    پیام متنی او به طرف(های) مقابل رله می‌شود. در غیر این صورت پیام نادیده گرفته می‌شود.
    """
    country = await get_player_country(session, db_user)
    if country is None:
        return

    # ۱) تماس تلفنی فعال
    active = await dip_repo.get_active_call_for_country(session, country.id)
    if active is not None:
        if _aware(active.ends_at) and _aware(active.ends_at) <= _utcnow():
            active.status = DiplomacyStatus.COMPLETED
            await message.answer("📵 زمان تماس به پایان رسید.")
            return
        partner_id = (
            active.callee_country if active.caller_country == country.id else active.caller_country
        )
        partner = await countries_repo.get_country(session, partner_id)
        await dip_repo.add_call_message(session, active.id, country.id, message.text)
        if partner and partner.owner_user_id:
            try:
                await bot.send_message(
                    partner.owner_user_id,
                    f"📞 {country.flag} {country.name_fa}: {message.text}",
                )
            except Exception:  # noqa: BLE001
                pass
        await send_log(bot, f"📞 [{country.name_fa} → {partner.name_fa if partner else '?'}]: {message.text}")
        return

    # ۲) دیدار دوجانبه‌ی فعال (پس از رسیدن مسافر، تا پایان جلسه) → چت با طرف مقابل
    meeting = await dip_repo.get_active_meeting_for_country(session, country.id)
    if meeting is not None:
        arrived = not (_aware(meeting.travel_eta) and _aware(meeting.travel_eta) > _utcnow())
        ended = _aware(meeting.meeting_ends_at) and _aware(meeting.meeting_ends_at) <= _utcnow()
        if arrived and not ended:
            partner_id = (
                meeting.host_country if meeting.traveler_country == country.id else meeting.traveler_country
            )
            partner = await countries_repo.get_country(session, partner_id)
            if partner and partner.owner_user_id:
                try:
                    await bot.send_message(
                        partner.owner_user_id,
                        f"🤝 {country.flag} {country.name_fa}: {message.text}",
                    )
                except Exception:  # noqa: BLE001
                    pass
            # لاگ صحبت‌های دیدار دوجانبه به گروه لاگ (v1.6)
            await send_log(
                bot,
                f"🤝 [{country.name_fa} → {partner.name_fa if partner else '?'}]: {message.text}",
            )
            return

    # ۳) نشست چندجانبه‌ی فعال → چت با همه‌ی کشورهای حاضر
    group = await dip_repo.get_active_group_meeting_for_country(session, country.id)
    if group is not None:
        ended = _aware(group.meeting_ends_at) and _aware(group.meeting_ends_at) <= _utcnow()
        if not ended:
            member_ids = await dip_repo.group_member_country_ids(session, group)
            for cid in member_ids:
                if cid == country.id:
                    continue
                member = await countries_repo.get_country(session, cid)
                if member and member.owner_user_id:
                    try:
                        await bot.send_message(
                            member.owner_user_id,
                            f"👥 {country.flag} {country.name_fa}: {message.text}",
                        )
                    except Exception:  # noqa: BLE001
                        pass
            # لاگ صحبت‌های نشست چندجانبه به گروه لاگ (v1.6)
            await send_log(
                bot,
                f"👥 [{group.title}] {country.name_fa}: {message.text}",
            )
            return
