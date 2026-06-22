"""
هندلر بخش دیپلماسی: نامه، تماس تلفنی، دیدار حضوری، قرارداد و تحریم.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import MEETING_DURATION_MINUTES, PHONE_CALL_DURATION_MINUTES
from ..database.models import Contract, Meeting, PhoneCall, Sanction, User
from ..database.repositories import countries as countries_repo
from ..database.repositories import diplomacy as dip_repo
from ..enums import DiplomacyStatus, NewsCategory
from ..keyboards.common import countries_kb
from ..keyboards.diplomacy import diplomacy_menu_kb, end_call_kb
from ..loader import bot
from ..services.ai import evaluators
from ..services.news_service import publish_news, send_log
from ..states import CallForm, ContractForm, LetterForm, MeetingForm
from ..utils.numbers import fa_number
from .deps import NO_COUNTRY_TEXT, get_player_country

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
        InlineKeyboardButton(text="✅ پاسخ", callback_data=f"call_accept:{phone_call.id}"),
        InlineKeyboardButton(text="❌ رد", callback_data=f"call_reject:{phone_call.id}"),
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
        InlineKeyboardButton(text="✅ پذیرش سفر", callback_data=f"meet_accept:{meeting.id}"),
        InlineKeyboardButton(text="❌ رد", callback_data=f"meet_reject:{meeting.id}"),
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
        f"پس از رسیدن، دیدار به مدت {MEETING_DURATION_MINUTES} دقیقه فعال می‌شود و "
        "می‌توانید با دستور /contract قرارداد ببندید."
    )
    for c in (traveler, host):
        if c and c.owner_user_id:
            try:
                await bot.send_message(c.owner_user_id, msg)
            except Exception:  # noqa: BLE001
                pass


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
    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        return
    meeting = await dip_repo.get_active_meeting_for_country(session, country.id)
    if meeting is None:
        await message.answer("برای بستن قرارداد باید در یک دیدار حضوری فعال باشید.")
        return
    # بررسی رسیدن مسافر
    if _aware(meeting.travel_eta) and _aware(meeting.travel_eta) > _utcnow():
        await message.answer("هنوز سفر به پایان نرسیده است. لطفاً تا رسیدن صبر کنید.")
        return
    await state.update_data(meeting_id=meeting.id)
    await state.set_state(ContractForm.entering_title)
    await message.answer("📜 عنوان قرارداد را وارد کنید:")


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
    meeting = await dip_repo.get_meeting(session, data["meeting_id"])
    await state.clear()
    if country is None or meeting is None:
        await message.answer("خطا در ثبت قرارداد.")
        return

    # طرف دوم قرارداد، طرف مقابلِ این کشور در دیدار است
    other_id = (
        meeting.host_country if meeting.traveler_country == country.id else meeting.traveler_country
    )
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
            InlineKeyboardButton(text="✍️ امضا", callback_data=f"sign_contract:{contract.id}"),
            InlineKeyboardButton(text="❌ رد", callback_data=f"reject_contract:{contract.id}"),
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
@router.callback_query(F.data == "dip:sanction")
async def cb_sanction(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    others = await _other_countries(session, country.id)
    await call.message.edit_text(
        "🚫 کدام کشور را تحریم می‌کنید؟",
        reply_markup=countries_kb(others, prefix="sanction_to", columns=2, back_data="menu:diplomacy"),
    )


@router.callback_query(F.data.startswith("sanction_to:"))
async def cb_sanction_to(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    target = await countries_repo.get_country(session, int(call.data.split(":")[1]))
    if country is None or target is None:
        await call.message.edit_text("خطا.")
        return
    sanction = Sanction(
        from_country=country.id,
        to_country=target.id,
        description=f"تحریم {target.name_fa} توسط {country.name_fa}",
        active=True,
    )
    await dip_repo.add_sanction(session, sanction)
    await call.message.edit_text(
        f"🚫 {target.flag} {target.name_fa} تحریم شد.", reply_markup=diplomacy_menu_kb()
    )
    president = db_user.president_name or country.name_fa
    await publish_news(
        bot,
        NewsCategory.DIPLOMACY,
        f"🚫 {country.flag} {country.name_fa} به ریاست‌جمهوری {president} "
        f"کشور {target.flag} {target.name_fa} را تحریم کرد.",
    )


# ============================================================
#  رله‌ی پیام‌های تماس تلفنی (در حالت پیش‌فرض، اگر تماس فعال باشد)
# ============================================================
@router.message(StateFilter(None), F.text & ~F.text.startswith("/"))
async def relay_call_message(message: Message, session: AsyncSession, db_user: User) -> None:
    """
    اگر کاربر در یک تماس تلفنی فعال باشد، پیام متنی او به طرف مقابل رله و در گروه لاگ ثبت می‌شود.
    در غیر این صورت این هندلر کاری نمی‌کند (پیام نادیده گرفته می‌شود).
    """
    country = await get_player_country(session, db_user)
    if country is None:
        return
    active = await dip_repo.get_active_call_for_country(session, country.id)
    if active is None:
        return
    # بررسی پایان زمان تماس
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
    # لاگ برای مدیران
    await send_log(bot, f"📞 [{country.name_fa} → {partner.name_fa if partner else '?'}]: {message.text}")
