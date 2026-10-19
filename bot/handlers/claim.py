"""هندلر کشورگیری: درخواست برداشتن یک کشور و ارسال به مالک برای تأیید."""

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
from ..constants import (
    VIP_CLAIM_CARD_HOLDER,
    VIP_CLAIM_CARD_NUMBER,
    VIP_CLAIM_PRICE_INFO,
)
from ..database.models import User
from ..database.repositories import claims as claims_repo
from ..database.repositories import countries as countries_repo
from ..enums import AdminGroupType
from ..keyboards.common import countries_kb
from ..loader import bot
from ..services.news_service import send_photo_to_admin_group, send_to_admin_group
from ..states import ClaimForm
from ..utils.ui import STYLE_NO, STYLE_OK
from .deps import get_player_country

router = Router(name="claim")
settings = get_settings()


async def _show_country_list(target: Message, session: AsyncSession) -> None:
    """نمایش لیست کشورهای آزاد برای انتخاب."""
    countries = await countries_repo.list_countries(session, only_unclaimed=True)
    if not countries:
        await target.answer("در حال حاضر هیچ کشور آزادی برای انتخاب وجود ندارد.")
        return
    # علامت‌گذاری کشورهای VIP در متن راهنما
    vip_note = (
        "\n\n⭐️ کشورهای VIP قابلیت‌های ویژه دارند و برای دریافت آن‌ها باید "
        "با مالک بازی در ارتباط باشید."
    )
    await target.answer(
        "🌍 یک کشور را برای رهبری انتخاب کنید:" + vip_note,
        reply_markup=countries_kb(countries, prefix="claim_pick", columns=2, show_vip_star=True),
    )


@router.message(Command("claim"))
async def cmd_claim(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """شروع فرایند کشورگیری با دستور /claim."""
    country = await get_player_country(session, db_user)
    if country is not None:
        await message.answer(
            f"شما هم‌اکنون رهبر {country.flag} {country.name_fa} هستید."
        )
        return
    pending = await claims_repo.get_pending_for_user(session, db_user.telegram_id)
    if pending is not None:
        await message.answer("⏳ درخواست شما در انتظار تأیید مالک است.")
        return
    await state.set_state(ClaimForm.choosing_country)
    await _show_country_list(message, session)


@router.callback_query(F.data == "claim:start")
async def cb_claim_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """شروع کشورگیری از دکمه."""
    await call.answer()
    pending = await claims_repo.get_pending_for_user(session, db_user.telegram_id)
    if pending is not None:
        await call.message.answer("⏳ درخواست شما در انتظار تأیید مالک است.")
        return
    await state.set_state(ClaimForm.choosing_country)
    await _show_country_list(call.message, session)


@router.callback_query(ClaimForm.choosing_country, F.data.startswith("claim_pick:"))
async def cb_pick_country(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """ثبت کشور انتخاب‌شده (عادی یا VIP)."""
    await call.answer()
    country_id = int(call.data.split(":")[1])
    country = await countries_repo.get_country(session, country_id)
    if country is None or country.is_claimed:
        await call.message.answer("این کشور دیگر در دسترس نیست. لطفاً کشور دیگری انتخاب کنید.")
        return

    await state.update_data(country_id=country_id)
    await state.set_state(ClaimForm.entering_president_name)

    vip_badge = " (⭐️ VIP)" if country.is_vip else ""
    back_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 بازگشت به فهرست کشورها", callback_data="claim:start", style="primary")
    ]])
    await call.message.answer(
        f"شما کشور {country.flag} <b>{country.name_fa}</b>{vip_badge} را انتخاب کردید.\n\n"
        "لطفاً نام رئیس‌جمهور خود را وارد کنید (این نام در اخبار استفاده می‌شود):",
        reply_markup=back_kb,
    )


@router.message(ClaimForm.waiting_for_vip_receipt, F.photo)
async def msg_vip_receipt_photo(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """دریافت تصویر فیش واریزی کشورگیری VIP و ارسال به گروه پرداختی‌ها."""
    data = await state.get_data()
    country_id = data.get("country_id")
    if not country_id:
        await state.clear()
        await message.answer("خطا در بازیابی اطلاعات کشور. لطفاً مجدداً /claim بزنید.")
        return

    country = await countries_repo.get_country(session, country_id)
    if country is None or country.is_claimed:
        await state.clear()
        await message.answer("این کشور دیگر در دسترس نیست. لطفاً کشور دیگری را از طریق /claim انتخاب کنید.")
        return

    # بررسی اینکه کاربر هم‌اکنون کشوری نداشته باشد یا درخواست دیگری در انتظار نداشته باشد
    user_country = await get_player_country(session, db_user)
    if user_country is not None:
        await state.clear()
        await message.answer(f"شما هم‌اکنون رهبر {user_country.flag} {user_country.name_fa} هستید.")
        return

    pending = await claims_repo.get_pending_for_user(session, db_user.telegram_id)
    if pending is not None:
        await state.clear()
        await message.answer("⏳ شما از قبل یک درخواست در انتظار تأیید دارید.")
        return

    photo_file_id = message.photo[-1].file_id
    president_name = data.get("president_name") or db_user.first_name
    claim = await claims_repo.create_claim(
        session,
        user_id=db_user.telegram_id,
        country_id=country_id,
        president_name=president_name,
        note=None,
        photo_file_id=photo_file_id,
    )
    await session.flush()
    await state.clear()

    await message.answer(
        "✅ رسید پرداخت شما دریافت و به بخش مالی ارسال شد. "
        "پس از بررسی و تأیید مدیریت، کشور به شما واگذار خواهد شد."
    )

    username_str = f"@{db_user.username}" if db_user.username else (db_user.first_name or "—")
    caption = (
        "💳 <b>درخواست کشورگیری VIP (رسید پرداختی)</b>\n\n"
        f"🏴 کشور: {country.flag} {country.name_fa} (VIP ⭐️)\n"
        f"🧑‍💼 نام رئیس‌جمهور: <b>{president_name}</b>\n"
        f"👤 کاربر: {db_user.first_name or '—'} ({username_str})\n"
        f"🆔 آیدی عددی: <code>{db_user.telegram_id}</code>\n"
        f"🔢 شناسه درخواست: #{claim.id}\n"
        f"💵 هزینه: {VIP_CLAIM_PRICE_INFO}"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ تأیید رسید و واگذاری کشور",
                    callback_data=f"vip_claim_approve:{claim.id}",
                    style=STYLE_OK,
                ),
                InlineKeyboardButton(
                    text="❌ رد درخواست",
                    callback_data=f"vip_claim_reject:{claim.id}",
                    style=STYLE_NO,
                ),
            ]
        ]
    )
    await send_photo_to_admin_group(
        bot,
        AdminGroupType.PAYMENT,
        photo=photo_file_id,
        caption=caption,
        reply_markup=kb,
    )


@router.message(ClaimForm.waiting_for_vip_receipt, F.text)
async def msg_vip_receipt_text_warning(message: Message) -> None:
    """هشدار به کاربر برای ارسال عکس رسید به جای متن."""
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ انصراف و انتخاب کشور دیگر", callback_data="claim:start", style=STYLE_NO)
    ]])
    await message.answer(
        "⚠️ لطفاً **تصویر رسید واریز** را ارسال کنید.\n\n"
        "در صورتی که منصرف شده‌اید، می‌توانید از دکمه زیر برای انتخاب کشور دیگر استفاده کنید.",
        reply_markup=cancel_kb,
    )



def _skip_note_kb() -> InlineKeyboardMarkup:
    """دکمه‌ی «رد کردن این مرحله» برای توضیحات کشورگیری (v1.8)."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⏭ رد کردن این مرحله", callback_data="claim:skip_note", style="primary")
    ]])


def _confirm_kb() -> InlineKeyboardMarkup:
    """دکمه‌های تأیید نهایی کشورگیری (v1.8)."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ بله، مطمئنم", callback_data="claim:confirm", style="success"),
        InlineKeyboardButton(text="❌ انصراف", callback_data="claim:cancel", style="danger"),
    ]])


@router.message(ClaimForm.entering_president_name, F.text)
async def msg_president_name(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """ثبت نام رئیس‌جمهور و بررسی کشور عادی یا VIP."""
    president_name = message.text.strip()
    await state.update_data(president_name=president_name)

    data = await state.get_data()
    country_id = data.get("country_id")
    country = await countries_repo.get_country(session, country_id) if country_id else None

    # اگر کشور VIP است: نمایش شرایط و هدایت به وضعیت دریافت فیش پرداختی
    if country and country.is_vip:
        await state.set_state(ClaimForm.waiting_for_vip_receipt)
        vip_cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ انصراف و انتخاب کشور دیگر", callback_data="claim:start", style=STYLE_NO)
        ]])
        text = (
            f"⭐️ کشور {country.flag} <b>{country.name_fa}</b> جزو <b>کشورهای ابرقدرت / VIP</b> بازی است.\n"
            f"🧑‍💼 رئیس‌جمهور: <b>{president_name}</b>\n\n"
            "💎 <b>قابلیت‌های انحصاری این کشور:</b>\n"
            "• تشکیل و رهبری اتحاد‌های بین‌المللی\n"
            "• برنامه‌ی توسعه و تحقیقات تسلیحات هسته‌ای\n"
            "• احداث پایگاه‌های نظامی در خاک خود یا کشورهای دیگر\n"
            "• ماهواره‌های جاسوسی فضایی نظامی\n"
            "• استقرار و اعزام نیروهای راهبردی نظامی\n"
            "• سقف ساخت نامحدود تأسیسات و صنایع\n\n"
            f"💳 شماره کارت: <code>{VIP_CLAIM_CARD_NUMBER}</code>\n"
            f"👤 به نام: <b>{VIP_CLAIM_CARD_HOLDER}</b>\n"
            f"💵 مبلغ: <b>{VIP_CLAIM_PRICE_INFO}</b>\n\n"
            "لطفاً پس از واریز، <b>تصویر رسید پرداخت</b> خود را در همین صفحه ارسال کنید تا برای مدیریت ارسال شود. "
            "به‌محض تأیید رسید، وارد کشور خود خواهید شد."
        )
        await message.answer(text, reply_markup=vip_cancel_kb)
        return

    # کشورهای عادی: ادامه روال قبلی
    await state.set_state(ClaimForm.entering_note)
    await message.answer(
        "در صورت تمایل توضیحی برای مالک بازی بنویسید، یا این مرحله را رد کنید:",
        reply_markup=_skip_note_kb(),
    )


async def _show_claim_confirm(
    target: Message, state: FSMContext, session: AsyncSession
) -> None:
    """نمایش خلاصه‌ی درخواست و پرسیدن تأیید نهایی از بازیکن."""
    data = await state.get_data()
    country = await countries_repo.get_country(session, data["country_id"])
    if country is None or country.is_claimed:
        await target.answer("این کشور دیگر در دسترس نیست.")
        await state.clear()
        return
    await state.set_state(ClaimForm.confirming)
    note = data.get("note")
    await target.answer(
        "🔎 <b>تأیید نهایی کشورگیری</b>\n\n"
        f"🏴 کشور: {country.flag} {country.name_fa}\n"
        f"🧑‍💼 رئیس‌جمهور: {data.get('president_name') or '—'}\n"
        f"📝 توضیح: {note or '—'}\n\n"
        "آیا از گرفتن این کشور مطمئن هستید؟",
        reply_markup=_confirm_kb(),
    )


@router.message(ClaimForm.entering_note, F.text)
async def msg_note(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """ثبت توضیح و رفتن به مرحله‌ی تأیید نهایی."""
    note = None if message.text.strip() == "-" else message.text.strip()
    await state.update_data(note=note)
    await _show_claim_confirm(message, state, session)


@router.callback_query(ClaimForm.entering_note, F.data == "claim:skip_note")
async def cb_skip_note(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """رد کردن مرحله‌ی توضیحات (توضیح خالی)."""
    await call.answer()
    await state.update_data(note=None)
    await _show_claim_confirm(call.message, state, session)


@router.callback_query(ClaimForm.confirming, F.data == "claim:cancel")
async def cb_claim_cancel(call: CallbackQuery, state: FSMContext) -> None:
    """انصراف از کشورگیری در مرحله‌ی تأیید."""
    await call.answer("لغو شد")
    await state.clear()
    await call.message.edit_text("❌ کشورگیری لغو شد. هر زمان خواستید دوباره /claim بزنید.")


@router.callback_query(ClaimForm.confirming, F.data == "claim:confirm")
async def cb_claim_confirm(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """ثبت نهایی درخواست کشورگیری و ارسال به مالک‌ها."""
    await call.answer()
    data = await state.get_data()
    note = data.get("note")
    country_id = data["country_id"]
    president_name = data.get("president_name")

    country = await countries_repo.get_country(session, country_id)
    if country is None or country.is_claimed:
        await call.message.edit_text("این کشور دیگر در دسترس نیست.")
        await state.clear()
        return

    # جلوگیری از ثبت درخواست تکراری (اگر بین مراحل درخواست دیگری ثبت شده باشد)
    pending = await claims_repo.get_pending_for_user(session, db_user.telegram_id)
    if pending is not None:
        await state.clear()
        await call.message.edit_text("⏳ درخواست شما در انتظار تأیید مالک است.")
        return

    claim = await claims_repo.create_claim(
        session, db_user.telegram_id, country_id, president_name, note
    )
    await session.flush()
    await state.clear()

    await call.message.edit_text(
        "✅ درخواست شما ثبت شد و برای تأیید به مالک بازی ارسال گردید.\n"
        "پس از تأیید، پنل کشورتان فعال می‌شود."
    )

    # ارسال درخواست به همه‌ی مالک‌ها با دکمه‌ی تأیید/رد
    username = f"@{db_user.username}" if db_user.username else db_user.first_name
    text = (
        "🆕 <b>درخواست کشورگیری</b>\n\n"
        f"👤 کاربر: {username} (<code>{db_user.telegram_id}</code>)\n"
        f"🏴 کشور: {country.flag} {country.name_fa}\n"
        f"🧑‍💼 نام رئیس‌جمهور: {president_name or '—'}\n"
        f"📝 توضیح: {note or '—'}"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ تأیید", callback_data=f"claim_approve:{claim.id}", style="success"
                ),
                InlineKeyboardButton(
                    text="❌ رد", callback_data=f"claim_reject:{claim.id}", style="danger"
                ),
            ]
        ]
    )
    # ارسال به گروه لاگ اصلی (MAIN_LOG)
    await send_to_admin_group(bot, AdminGroupType.MAIN_LOG, text, reply_markup=kb)

    # ارسال به پیوی مالک‌ها به عنوان پشتیبان
    for owner_id in settings.owner_ids:
        try:
            await bot.send_message(owner_id, text, reply_markup=kb)
        except Exception:  # noqa: BLE001 — اگر مالکی در دسترس نبود، رد می‌شویم
            continue
