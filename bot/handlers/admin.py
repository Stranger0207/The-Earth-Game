"""هندلر مدیریت: تأیید/رد کشورگیری و ابزارهای مالک."""

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
from ..database.models import User
from ..database.repositories import claims as claims_repo
from ..database.repositories import countries as countries_repo
from ..database.repositories import diplomacy as dip_repo
from ..database.repositories import users as users_repo
from ..enums import ClaimStatus
from ..keyboards.menu import main_menu_kb
from ..loader import bot
from ..services.news_service import send_log
from ..services.season_service import reset_season
from ..states import AnnounceForm
from ..utils.numbers import fa_number
from ..utils.ui import PICK_OFF, PICK_ON, STYLE_MAIN, STYLE_OK

router = Router(name="admin")
settings = get_settings()


def _is_owner(user_id: int) -> bool:
    return settings.is_owner(user_id)


@router.callback_query(F.data.startswith("claim_approve:"))
async def cb_approve(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """تأیید درخواست کشورگیری توسط مالک."""
    if not _is_owner(call.from_user.id):
        await call.answer("فقط مالک بازی می‌تواند تأیید کند.", show_alert=True)
        return

    claim_id = int(call.data.split(":")[1])
    claim = await claims_repo.get_claim(session, claim_id)
    if claim is None or claim.status != ClaimStatus.PENDING:
        await call.answer("این درخواست قبلاً بررسی شده است.", show_alert=True)
        return

    country = await countries_repo.get_country(session, claim.country_id)
    if country is None or country.is_claimed:
        await call.answer("کشور دیگر در دسترس نیست.", show_alert=True)
        await claims_repo.set_status(session, claim_id, ClaimStatus.REJECTED, call.from_user.id)
        return

    # واگذاری مالکیت و به‌روزرسانی کاربر
    await countries_repo.assign_owner(session, claim.country_id, claim.user_id)
    if claim.president_name:
        await users_repo.set_president_name(session, claim.user_id, claim.president_name)
    await claims_repo.set_status(session, claim_id, ClaimStatus.APPROVED, call.from_user.id)

    await call.answer("تأیید شد ✅")
    await call.message.edit_text(
        call.message.html_text + "\n\n✅ <b>تأیید شد</b>"
    )

    # اطلاع به بازیکن
    try:
        await bot.send_message(
            claim.user_id,
            f"🎉 تبریک! درخواست شما تأیید شد.\n"
            f"شما اکنون رهبر {country.flag} <b>{country.name_fa}</b> هستید.\n\n"
            "پنل مدیریت کشور:",
            reply_markup=main_menu_kb(),
        )
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data.startswith("claim_reject:"))
async def cb_reject(call: CallbackQuery, session: AsyncSession) -> None:
    """رد درخواست کشورگیری توسط مالک."""
    if not _is_owner(call.from_user.id):
        await call.answer("فقط مالک بازی می‌تواند رد کند.", show_alert=True)
        return

    claim_id = int(call.data.split(":")[1])
    claim = await claims_repo.get_claim(session, claim_id)
    if claim is None or claim.status != ClaimStatus.PENDING:
        await call.answer("این درخواست قبلاً بررسی شده است.", show_alert=True)
        return

    await claims_repo.set_status(session, claim_id, ClaimStatus.REJECTED, call.from_user.id)
    await call.answer("رد شد ❌")
    await call.message.edit_text(call.message.html_text + "\n\n❌ <b>رد شد</b>")

    try:
        await bot.send_message(
            claim.user_id,
            "متأسفانه درخواست کشورگیری شما رد شد. می‌توانید کشور دیگری را امتحان کنید. /claim",
        )
    except Exception:  # noqa: BLE001
        pass


@router.message(Command("pending"))
async def cmd_pending(
    message: Message, session: AsyncSession
) -> None:
    """فهرست درخواست‌های در انتظار (فقط برای مالک/مدیر)."""
    if not settings.is_admin(message.from_user.id):
        return
    pending = await claims_repo.list_pending(session)
    if not pending:
        await message.answer("هیچ درخواست در انتظاری وجود ندارد.")
        return
    lines = ["📋 <b>درخواست‌های در انتظار تأیید:</b>", ""]
    for c in pending:
        country = await countries_repo.get_country(session, c.country_id)
        cname = country.name_fa if country else "?"
        lines.append(
            f"• #{c.id} — کاربر <code>{c.user_id}</code> برای {cname}"
        )
    await message.answer("\n".join(lines))


# ============================================================
#  پایان فصل: ریست کامل بازی به حالت اولیه (فقط مالک)
#  با تأیید دومرحله‌ای برای جلوگیری از ریست تصادفی.
# ============================================================
async def _broadcast_announcement(
    session: AsyncSession, text: str, target_ids: list[int] | None = None
) -> int:
    """
    ارسال اعلان به همه‌ی کشورهای دارای مالک، یا فقط به کشورهای target_ids (v1.9).
    تعداد دریافت‌کنندگان را برمی‌گرداند.
    """
    body = f"📛اعلانات کره زمین📛\n\n🔴 | {text}"
    countries = await countries_repo.list_countries(session)
    sent = 0
    seen: set[int] = set()
    for c in countries:
        if target_ids is not None and c.id not in target_ids:
            continue
        if c.owner_user_id and c.owner_user_id not in seen:
            seen.add(c.owner_user_id)
            try:
                await bot.send_message(c.owner_user_id, body)
                sent += 1
            except Exception:  # noqa: BLE001 — خطای ارسال نباید بقیه را متوقف کند
                pass
    return sent


def _announce_kind_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 به همه‌ی کشورها", callback_data="annc:all", style=STYLE_MAIN)],
        [InlineKeyboardButton(text="🎯 به یک یا چند کشور", callback_data="annc:multi", style=STYLE_MAIN)],
    ])


def _announce_select_kb(countries, selected: set[int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for c in countries:
        if not c.owner_user_id:
            continue
        chosen = c.id in selected
        mark = PICK_ON if chosen else PICK_OFF
        builder.button(
            text=f"{mark} {c.flag} {c.name_fa}",
            callback_data=f"annc_pick:{c.id}",
            style=STYLE_OK if chosen else STYLE_MAIN,
        )
    builder.adjust(2)
    cont = f"✅ ادامه ({fa_number(len(selected))})" if selected else "✔️ ادامه"
    builder.row(InlineKeyboardButton(text=cont, callback_data="annc_next", style=STYLE_OK))
    return builder.as_markup()


@router.message(Command("announce"))
async def cmd_announce(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """اعلان به همه یا یک/چند کشور (فقط مالک/مدیر) — v1.9."""
    if not settings.is_admin(message.from_user.id):
        return
    text = message.text.partition(" ")[2].strip()
    if text:
        # سازگاری قبلی: /announce متن → ارسال به همه
        sent = await _broadcast_announcement(session, text)
        await send_log(bot, f"📢 <b>اعلان عمومی</b> به {fa_number(sent)} کشور:\n\n{text}")
        await message.answer(f"✅ اعلان عمومی به {fa_number(sent)} کشور ارسال شد.")
        return
    await state.clear()
    await message.answer("📢 نوع اعلان را انتخاب کنید:", reply_markup=_announce_kind_kb())


@router.callback_query(F.data == "annc:all")
async def cb_announce_all(call: CallbackQuery, state: FSMContext) -> None:
    if not settings.is_admin(call.from_user.id):
        await call.answer("فقط مدیر/مالک.", show_alert=True)
        return
    await call.answer()
    await state.set_state(AnnounceForm.writing_body)
    await state.update_data(targets=None)
    await call.message.edit_text("📝 متن اعلان عمومی (به همه‌ی کشورها) را بنویسید:")


@router.callback_query(F.data == "annc:multi")
async def cb_announce_multi(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not settings.is_admin(call.from_user.id):
        await call.answer("فقط مدیر/مالک.", show_alert=True)
        return
    await call.answer()
    await state.set_state(AnnounceForm.multi_select)
    await state.update_data(selected=[])
    countries = await countries_repo.list_countries(session)
    await call.message.edit_text(
        "🎯 کشورهای مقصد اعلان را انتخاب کنید:",
        reply_markup=_announce_select_kb(countries, set()),
    )


@router.callback_query(AnnounceForm.multi_select, F.data.startswith("annc_pick:"))
async def cb_announce_pick(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await call.answer()
    cid = int(call.data.split(":")[1])
    data = await state.get_data()
    selected = set(data.get("selected", []))
    selected.discard(cid) if cid in selected else selected.add(cid)
    await state.update_data(selected=list(selected))
    countries = await countries_repo.list_countries(session)
    await call.message.edit_reply_markup(reply_markup=_announce_select_kb(countries, selected))


@router.callback_query(AnnounceForm.multi_select, F.data == "annc_next")
async def cb_announce_next(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    data = await state.get_data()
    selected = data.get("selected", [])
    if not selected:
        await call.answer("حداقل یک کشور انتخاب کنید.", show_alert=True)
        return
    await state.update_data(targets=selected)
    await state.set_state(AnnounceForm.writing_body)
    await call.message.edit_text(
        f"📝 متن اعلان به {fa_number(len(selected))} کشور انتخاب‌شده را بنویسید:"
    )


@router.message(AnnounceForm.writing_body, F.text)
async def msg_announce_body(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not settings.is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    await state.clear()
    targets = data.get("targets")
    sent = await _broadcast_announcement(session, message.text, target_ids=targets)
    scope = "عمومی (همه)" if not targets else f"{fa_number(len(targets))} کشور"
    await send_log(bot, f"📢 <b>اعلان {scope}</b>:\n\n{message.text}")
    await message.answer(f"✅ اعلان به {fa_number(sent)} کشور ارسال شد.")


@router.message(Command("resetmeetings"))
async def cmd_reset_meetings(message: Message, session: AsyncSession) -> None:
    """
    ریست/غیرفعال‌سازی همه‌ی نشست‌های دوجانبه/چندجانبه و تماس‌های فعال یا معلق (فقط مالک — v1.10.1).
    برای رفع قفل‌ماندن کشورها در نشست‌های گیرکرده استفاده می‌شود.
    """
    if not _is_owner(message.from_user.id):
        return
    counts = await dip_repo.close_all_active_meetings(session)
    await message.answer(
        "♻️ <b>همه‌ی نشست‌ها ریست شدند.</b>\n\n"
        f"🤝 دیدار دوجانبه: {fa_number(counts['meetings'])}\n"
        f"👥 نشست چندجانبه: {fa_number(counts['group_meetings'])}\n"
        f"📞 تماس تلفنی: {fa_number(counts['calls'])}\n\n"
        "اکنون همه‌ی کشورها از نشست‌های فعلی آزاد شدند و می‌توانند نشست/تماس جدید داشته باشند."
    )
    await send_log(
        bot,
        "♻️ <b>ریست نشست‌ها (مالک)</b>\n"
        f"دوجانبه: {counts['meetings']} | چندجانبه: {counts['group_meetings']} | تماس: {counts['calls']}",
    )


@router.message(Command("endseason"))
async def cmd_endseason(message: Message) -> None:
    """نمایش هشدار و دکمه‌ی تأیید پایان فصل (فقط برای مالک)."""
    if not _is_owner(message.from_user.id):
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔴 بله، فصل را ریست کن", callback_data="season_reset_confirm",
                    style="danger",
                )
            ],
            [InlineKeyboardButton(text="❌ انصراف", callback_data="season_reset_cancel", style="primary")],
        ]
    )
    await message.answer(
        "⚠️ <b>پایان فصل و ریست کامل بازی</b>\n\n"
        "با این کار تمام تغییرات فصل به حالت اولیه برمی‌گردد:\n"
        "• اقتصاد، ذخایر و رضایت همه‌ی کشورها بازنشانی می‌شود\n"
        "• تجهیزات نظامی (تلفات‌ها) به تعداد اولیه برمی‌گردد\n"
        "• تأسیسات، کارخانه‌های نظامی، قراردادها، حملات، تماس‌ها، دیدارها و فروش‌ها پاک می‌شوند\n"
        "• <b>مالکیت همه‌ی کشورها آزاد می‌شود</b> و بازیکن‌ها باید دوباره کشورگیری کنند\n\n"
        "❗️ این عملیات <b>غیرقابل‌بازگشت</b> است. مطمئن هستید؟",
        reply_markup=kb,
    )


@router.callback_query(F.data == "season_reset_cancel")
async def cb_season_cancel(call: CallbackQuery) -> None:
    """انصراف از ریست فصل."""
    if not _is_owner(call.from_user.id):
        await call.answer("فقط مالک بازی مجاز است.", show_alert=True)
        return
    await call.answer("لغو شد")
    await call.message.edit_text("✅ ریست فصل لغو شد. هیچ تغییری اعمال نشد.")


@router.callback_query(F.data == "season_reset_confirm")
async def cb_season_confirm(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """اجرای ریست کامل فصل پس از تأیید مالک."""
    if not _is_owner(call.from_user.id):
        await call.answer("فقط مالک بازی مجاز است.", show_alert=True)
        return
    await call.answer("در حال ریست فصل...")
    await call.message.edit_text("⏳ در حال ریست کامل بازی... لطفاً صبر کنید.")

    result = await reset_season(session)

    await call.message.edit_text(
        "🎉 <b>فصل با موفقیت به پایان رسید و بازی ریست شد.</b>\n\n"
        f"✅ {result['countries_reset']} کشور به حالت اولیه بازگشتند.\n"
        "همه‌ی کشورها اکنون آزاد هستند و بازیکن‌ها می‌توانند برای فصل جدید "
        "کشورگیری کنند. (/claim)"
    )
