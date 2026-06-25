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
from ..database.models import User
from ..database.repositories import claims as claims_repo
from ..database.repositories import countries as countries_repo
from ..keyboards.common import countries_kb
from ..loader import bot
from ..states import ClaimForm
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
        reply_markup=countries_kb(countries, prefix="claim_pick", columns=2),
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
    """ثبت کشور انتخاب‌شده و پرسیدن نام رئیس‌جمهور."""
    await call.answer()
    country_id = int(call.data.split(":")[1])
    country = await countries_repo.get_country(session, country_id)
    if country is None or country.is_claimed:
        await call.message.answer("این کشور دیگر در دسترس نیست. لطفاً کشور دیگری انتخاب کنید.")
        return
    await state.update_data(country_id=country_id)
    await state.set_state(ClaimForm.entering_president_name)
    vip = "⭐️ (کشور VIP) " if country.is_vip else ""
    await call.message.answer(
        f"{vip}شما کشور {country.flag} <b>{country.name_fa}</b> را انتخاب کردید.\n\n"
        "لطفاً نام رئیس‌جمهور خود را وارد کنید (این نام در اخبار استفاده می‌شود):"
    )


@router.message(ClaimForm.entering_president_name, F.text)
async def msg_president_name(message: Message, state: FSMContext) -> None:
    """ثبت نام رئیس‌جمهور و پرسیدن توضیح اختیاری."""
    await state.update_data(president_name=message.text.strip())
    await state.set_state(ClaimForm.entering_note)
    await message.answer(
        "در صورت تمایل توضیحی برای مالک بازی بنویسید (یا «-» برای رد کردن):"
    )


@router.message(ClaimForm.entering_note, F.text)
async def msg_note(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """ثبت درخواست کشورگیری و ارسال به مالک‌ها."""
    data = await state.get_data()
    note = None if message.text.strip() == "-" else message.text.strip()
    country_id = data["country_id"]
    president_name = data.get("president_name")

    country = await countries_repo.get_country(session, country_id)
    if country is None or country.is_claimed:
        await message.answer("این کشور دیگر در دسترس نیست.")
        await state.clear()
        return

    claim = await claims_repo.create_claim(
        session, db_user.telegram_id, country_id, president_name, note
    )
    await session.flush()
    await state.clear()

    await message.answer(
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
    for owner_id in settings.owner_ids:
        try:
            await bot.send_message(owner_id, text, reply_markup=kb)
        except Exception:  # noqa: BLE001 — اگر مالکی در دسترس نبود، رد می‌شویم
            continue
