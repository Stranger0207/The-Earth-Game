"""
هندلر سیستم نامه‌رسان (v1.9): نامه به یک کشور، نامه به چند کشور و صندوق پستی.
هر نامه‌ی دریافتی یک دکمه‌ی «پاسخ به نامه» دارد و صندوق پستی وضعیت پاسخ را نشان می‌دهد.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import User
from ..database.repositories import countries as countries_repo
from ..database.repositories import letters as letters_repo
from ..loader import bot
from ..services.news_service import send_log
from ..states import MailForm
from ..utils.numbers import fa_number
from ..utils.ui import PICK_OFF, PICK_ON, STYLE_MAIN, STYLE_OK
from .deps import NO_COUNTRY_TEXT, get_player_country

router = Router(name="mail")


def _mail_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ نامه به یک کشور", callback_data="mail:single", style=STYLE_MAIN)],
        [InlineKeyboardButton(text="📨 نامه به چند کشور", callback_data="mail:multi", style=STYLE_MAIN)],
        [InlineKeyboardButton(text="📬 صندوق پستی", callback_data="mail:inbox", style=STYLE_MAIN)],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu:diplomacy", style=STYLE_MAIN)],
    ])


def _back_mail_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="dip:letter", style=STYLE_MAIN)
    ]])


def _reply_kb(letter_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📩 پاسخ به نامه", callback_data=f"mail_reply:{letter_id}", style=STYLE_OK)
    ]])


def _multi_select_kb(others, selected: set[int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for c in others:
        chosen = c.id in selected
        mark = PICK_ON if chosen else PICK_OFF
        builder.button(
            text=f"{mark} {c.flag} {c.name_fa}",
            callback_data=f"mail_pick:{c.id}",
            style=STYLE_OK if chosen else STYLE_MAIN,
        )
    builder.adjust(2)
    cont = f"✅ ادامه ({fa_number(len(selected))})" if selected else "✔️ ادامه"
    builder.row(InlineKeyboardButton(text=cont, callback_data="mail_multi_next", style=STYLE_OK))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="dip:letter", style=STYLE_MAIN))
    return builder.as_markup()


# ============================================================
#  منوی نامه
# ============================================================
@router.callback_query(F.data == "dip:letter")
async def cb_mail(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.answer()
    await call.message.edit_text("✉️ <b>سیستم نامه‌رسان</b>\n\nیک گزینه را انتخاب کنید:", reply_markup=_mail_menu_kb())


# ----- نامه به یک کشور -----
@router.callback_query(F.data == "mail:single")
async def cb_mail_single(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    await state.set_state(MailForm.single_target)
    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id]
    from ..keyboards.common import countries_kb
    await call.message.edit_text(
        "✉️ نامه را به کدام کشور می‌فرستید؟",
        reply_markup=countries_kb(others, prefix="mail_to", columns=2, back_data="dip:letter"),
    )


@router.callback_query(MailForm.single_target, F.data.startswith("mail_to:"))
async def cb_mail_to(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.update_data(recipients=[int(call.data.split(":")[1])])
    await state.set_state(MailForm.writing_body)
    await call.message.edit_text("📝 متن نامه را بنویسید:", reply_markup=_back_mail_kb())


# ----- نامه به چند کشور -----
@router.callback_query(F.data == "mail:multi")
async def cb_mail_multi(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    await state.set_state(MailForm.multi_select)
    await state.update_data(selected=[])
    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id]
    await call.message.edit_text(
        "📨 کشورهای گیرنده را انتخاب کنید:", reply_markup=_multi_select_kb(others, set())
    )


@router.callback_query(MailForm.multi_select, F.data.startswith("mail_pick:"))
async def cb_mail_pick(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    cid = int(call.data.split(":")[1])
    data = await state.get_data()
    selected = set(data.get("selected", []))
    selected.discard(cid) if cid in selected else selected.add(cid)
    await state.update_data(selected=list(selected))
    country = await get_player_country(session, db_user)
    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id]
    await call.message.edit_reply_markup(reply_markup=_multi_select_kb(others, selected))


@router.callback_query(MailForm.multi_select, F.data == "mail_multi_next")
async def cb_mail_multi_next(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    data = await state.get_data()
    selected = data.get("selected", [])
    if not selected:
        await call.answer("حداقل یک کشور انتخاب کنید.", show_alert=True)
        return
    await state.update_data(recipients=selected)
    await state.set_state(MailForm.writing_body)
    await call.message.edit_text(
        f"📝 متن نامه به {fa_number(len(selected))} کشور را بنویسید:", reply_markup=_back_mail_kb()
    )


# ----- نوشتن و ارسال متن نامه -----
@router.message(MailForm.writing_body, F.text)
async def msg_mail_body(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    data = await state.get_data()
    recipients = data.get("recipients", [])
    country = await get_player_country(session, db_user)
    await state.clear()
    if country is None or not recipients:
        await message.answer("خطا در ارسال نامه.")
        return
    sent_names = []
    for rid in recipients:
        target = await countries_repo.get_country(session, rid)
        if target is None:
            continue
        letter = await letters_repo.add_letter(session, country.id, rid, message.text)
        sent_names.append(f"{target.flag} {target.name_fa}")
        if target.owner_user_id:
            try:
                await bot.send_message(
                    target.owner_user_id,
                    f"✉️ <b>نامه از {country.flag} {country.name_fa}</b>\n\n{message.text}",
                    reply_markup=_reply_kb(letter.id),
                )
            except Exception:  # noqa: BLE001
                pass
    from ..keyboards.diplomacy import diplomacy_menu_kb
    await message.answer(
        f"✅ نامه برای {('، '.join(sent_names)) or '—'} ارسال شد.", reply_markup=diplomacy_menu_kb()
    )
    await send_log(
        bot,
        f"✉️ <b>نامه</b>\nفرستنده: {country.flag} {country.name_fa}\n"
        f"گیرنده(ها): {('، '.join(sent_names)) or '—'}\n\n📝 متن:\n{message.text}",
    )


# ----- پاسخ به نامه -----
@router.callback_query(F.data.startswith("mail_reply:"))
async def cb_mail_reply(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    letter_id = int(call.data.split(":")[1])
    letter = await letters_repo.get_letter(session, letter_id)
    country = await get_player_country(session, db_user)
    if letter is None or country is None or letter.recipient_country != country.id:
        await call.answer("امکان پاسخ به این نامه نیست.", show_alert=True)
        return
    await state.set_state(MailForm.replying)
    await state.update_data(reply_to=letter_id)
    await call.message.answer("📩 متن پاسخ خود را بنویسید:")


@router.message(MailForm.replying, F.text)
async def msg_mail_reply(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    data = await state.get_data()
    await state.clear()
    letter = await letters_repo.get_letter(session, data.get("reply_to"))
    country = await get_player_country(session, db_user)
    if letter is None or country is None:
        await message.answer("خطا در ثبت پاسخ.")
        return
    original_sender = await countries_repo.get_country(session, letter.sender_country)
    # ثبت پاسخ و علامت‌گذاری نامه‌ی اصلی به‌عنوان پاسخ‌داده‌شده
    await letters_repo.add_letter(session, country.id, letter.sender_country, message.text, parent_id=letter.id)
    letter.replied = True
    if original_sender and original_sender.owner_user_id:
        try:
            await bot.send_message(
                original_sender.owner_user_id,
                f"📩 <b>پاسخ نامه از {country.flag} {country.name_fa}</b>\n\n{message.text}",
            )
        except Exception:  # noqa: BLE001
            pass
    from ..keyboards.diplomacy import diplomacy_menu_kb
    await message.answer("✅ پاسخ شما ارسال شد.", reply_markup=diplomacy_menu_kb())
    await send_log(
        bot,
        f"📩 <b>پاسخ نامه</b>\nفرستنده: {country.flag} {country.name_fa}\n"
        f"گیرنده: {original_sender.flag if original_sender else ''} {original_sender.name_fa if original_sender else '?'}\n\n"
        f"📝 متن:\n{message.text}",
    )


# ----- صندوق پستی -----
@router.callback_query(F.data == "mail:inbox")
async def cb_mail_inbox(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    inbox = await letters_repo.list_inbox(session, country.id)
    if not inbox:
        await call.message.edit_text("📭 صندوق پستی شما خالی است.", reply_markup=_back_mail_kb())
        return
    lines = ["📬 <b>صندوق پستی</b>", ""]
    for ltr in inbox[:20]:
        sender = await countries_repo.get_country(session, ltr.sender_country)
        who = f"{sender.flag} {sender.name_fa}" if sender else "?"
        status = "✅ پاسخ داده شد" if ltr.replied else "🕒 بی‌پاسخ"
        preview = (ltr.body or "")[:60]
        lines.append(f"• از {who} — {status}\n   «{preview}»")
    await call.message.edit_text("\n".join(lines), reply_markup=_back_mail_kb())
