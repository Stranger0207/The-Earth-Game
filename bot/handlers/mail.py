"""
هندلر سیستم نامه‌رسان (v1.9): نامه به یک کشور، نامه به چند کشور و صندوق پستی.
هر نامه‌ی دریافتی یک دکمه‌ی «پاسخ به نامه» دارد و صندوق پستی وضعیت پاسخ را نشان می‌دهد.

(v2.1) گزینه‌ی «نامه به تمام کشورها» اضافه شد: با یک کلیک و نوشتن متن، نامه
برای همه‌ی کشورها ارسال می‌شود.
"""

from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import User
from ..database.repositories import alliances as alliances_repo
from ..database.repositories import countries as countries_repo
from ..database.repositories import letters as letters_repo
from ..loader import bot
from ..services.news_service import send_log
from ..states import MailForm
from ..utils.numbers import fa_number
from ..utils.screens import safe_edit
from ..utils.ui import DIVIDER, PICK_OFF, PICK_ON, STYLE_MAIN, STYLE_OK
from .deps import NO_COUNTRY_TEXT, assert_feature, get_player_country

router = Router(name="mail")


def _mail_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ نامه به یک کشور", callback_data="mail:single", style=STYLE_MAIN)],
        [InlineKeyboardButton(text="📨 نامه به چند کشور", callback_data="mail:multi", style=STYLE_MAIN)],
        [InlineKeyboardButton(text="🌍 نامه به تمام کشورها", callback_data="mail:all", style=STYLE_MAIN)],
        [InlineKeyboardButton(text="🤝 نامه به متحدان", callback_data="mail:allies", style=STYLE_MAIN)],
        [InlineKeyboardButton(text="📬 صندوق پستی", callback_data="mail:inbox", style=STYLE_MAIN)],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu:diplomacy", style=STYLE_MAIN)],
    ])


def _back_mail_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="dip:letter", style=STYLE_MAIN)
    ]])


def _reply_kb(letter_id: int) -> InlineKeyboardMarkup:
    """
    دکمه‌ی پاسخ زیر هر نامه‌ی دریافتی.

    (v1.11.1) این دکمه روی **همه‌ی** نامه‌های دریافتی — از جمله پاسخ‌ها — قرار
    می‌گیرد تا گفتگو بدون نیاز به پیداکردن دوباره‌ی کشور ادامه پیدا کند.
    """
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
async def cb_mail(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    await state.clear()
    await call.answer()
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "dip.letter"):
        return
    await safe_edit(call,"✉️ <b>سیستم نامه‌رسان</b>\n\nیک گزینه را انتخاب کنید:", reply_markup=_mail_menu_kb())


# ----- نامه به یک کشور -----
@router.callback_query(F.data == "mail:single")
async def cb_mail_single(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call,NO_COUNTRY_TEXT)
        return
    await state.set_state(MailForm.single_target)
    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id]
    from ..keyboards.common import countries_kb
    await safe_edit(call,
        "✉️ نامه را به کدام کشور می‌فرستید؟",
        reply_markup=countries_kb(others, prefix="mail_to", columns=2, back_data="dip:letter"),
    )


@router.callback_query(MailForm.single_target, F.data.startswith("mail_to:"))
async def cb_mail_to(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.update_data(recipients=[int(call.data.split(":")[1])])
    await state.set_state(MailForm.writing_body)
    await safe_edit(call,"📝 متن نامه را بنویسید:", reply_markup=_back_mail_kb())


# ----- نامه به چند کشور -----
@router.callback_query(F.data == "mail:multi")
async def cb_mail_multi(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call,NO_COUNTRY_TEXT)
        return
    await state.set_state(MailForm.multi_select)
    await state.update_data(selected=[])
    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id]
    await safe_edit(call,
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
    await safe_edit(call,
        f"📝 متن نامه به {fa_number(len(selected))} کشور را بنویسید:", reply_markup=_back_mail_kb()
    )


# ----- نامه به متحدان (v1.11.1) -----
@router.callback_query(F.data == "mail:allies")
async def cb_mail_allies(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """
    نامه به همه‌ی اعضای اتحادِ کشور (به‌جز خودش).

    اگر کشور در هیچ اتحادی نباشد، پیام راهنما نشان داده می‌شود.
    """
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    membership = await alliances_repo.get_membership(session, country.id)
    if membership is None:
        await safe_edit(
            call,
            "🤝 شما در هیچ اتحادی عضو نیستید.\n\n"
            "<i>برای ارسال نامه به متحدان، ابتدا باید در یک اتحاد عضو شوید "
            "(بخش دیپلماسی → اتحاد).</i>",
            reply_markup=_back_mail_kb(),
        )
        return

    members = await alliances_repo.list_members(session, membership.alliance_id)
    recipients = [m.country_id for m in members if m.country_id != country.id]
    if not recipients:
        await safe_edit(
            call,
            "🤝 در حال حاضر متحد دیگری در اتحاد شما وجود ندارد.",
            reply_markup=_back_mail_kb(),
        )
        return

    alliance = await alliances_repo.get_alliance(session, membership.alliance_id)
    names = []
    for rid in recipients:
        target = await countries_repo.get_country(session, rid)
        if target is not None:
            names.append(f"{target.flag} {target.name_fa}")

    await state.set_state(MailForm.writing_body)
    await state.update_data(recipients=recipients, to_allies=True)
    await safe_edit(
        call,
        f"🤝 <b>نامه به متحدان</b>\n{DIVIDER}\n"
        f"اتحاد: <b>{alliance.name if alliance else '—'}</b>\n"
        f"گیرندگان ({fa_number(len(recipients))}): {'، '.join(names) or '—'}\n\n"
        "📝 متن نامه را بنویسید:",
        reply_markup=_back_mail_kb(),
    )


# ----- نامه به تمام کشورها (v2.1) -----
@router.callback_query(F.data == "mail:all")
async def cb_mail_all(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """
    نامه‌ی سراسری به همه‌ی کشورها (به‌جز خودی) — بدون مرحله‌ی انتخاب.

    بازیکن فقط متن را می‌نویسد و نامه برای همه ارسال می‌شود.
    """
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    countries = await countries_repo.list_countries(session)
    recipients = [c.id for c in countries if c.id != country.id]
    if not recipients:
        await safe_edit(call, "کشور دیگری برای ارسال نامه وجود ندارد.", reply_markup=_back_mail_kb())
        return

    await state.set_state(MailForm.writing_body)
    await state.update_data(recipients=recipients, to_all=True)
    await safe_edit(
        call,
        f"🌍 <b>نامه به تمام کشورها</b>\n{DIVIDER}\n"
        f"گیرندگان: <b>همه‌ی کشورها</b> ({fa_number(len(recipients))} کشور)\n\n"
        "📝 متن نامه را بنویسید:",
        reply_markup=_back_mail_kb(),
    )


# ----- نوشتن و ارسال متن نامه -----
@router.message(MailForm.writing_body, F.text)
async def msg_mail_body(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    data = await state.get_data()
    recipients = data.get("recipients", [])
    to_allies = bool(data.get("to_allies"))
    to_all = bool(data.get("to_all"))
    country = await get_player_country(session, db_user)
    await state.clear()
    if country is None or not recipients:
        await message.answer("خطا در ارسال نامه.")
        return
    # سرخط نامه با نوع ارسال فرق دارد تا گیرنده بداند نامه‌ی جمعی است یا شخصی
    if to_all:
        title, emoji = "نامه سراسری", "🌍"
    elif to_allies:
        title, emoji = "نامه به متحدان", "🤝"
    else:
        title, emoji = "نامه", "✉️"
    sent_names = []
    sent_count = 0
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
                    f"{emoji} <b>{title} از {country.flag} {country.name_fa}</b>\n\n{message.text}",
                    reply_markup=_reply_kb(letter.id),
                )
                sent_count += 1
            except Exception:  # noqa: BLE001
                pass
            # نامه‌ی سراسری ده‌ها پیام پشت‌سرهم می‌فرستد؛ وقفه‌ی کوتاه از
            # برخورد با محدودیت نرخ تلگرام جلوگیری می‌کند.
            if to_all:
                await asyncio.sleep(0.05)
    from ..keyboards.diplomacy import diplomacy_menu_kb
    # در نامه‌ی سراسری فهرست ۳۸ نامی خوانا نیست؛ فقط تعداد گزارش می‌شود.
    if to_all:
        summary = (
            f"✅ نامه‌ی سراسری برای {fa_number(len(sent_names))} کشور ثبت شد "
            f"({fa_number(sent_count)} کشور دارای رهبر، پیام را دریافت کردند)."
        )
        recipients_log = f"همه‌ی کشورها ({fa_number(len(sent_names))} کشور)"
    else:
        summary = f"✅ نامه برای {('، '.join(sent_names)) or '—'} ارسال شد."
        recipients_log = ("، ".join(sent_names)) or "—"
    await message.answer(summary, reply_markup=diplomacy_menu_kb())
    await send_log(
        bot,
        f"{emoji} <b>{title}</b>\nفرستنده: {country.flag} {country.name_fa}\n"
        f"گیرنده(ها): {recipients_log}\n\n📝 متن:\n{message.text}",
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
    reply_letter = await letters_repo.add_letter(
        session, country.id, letter.sender_country, message.text, parent_id=letter.id
    )
    letter.replied = True
    if original_sender and original_sender.owner_user_id:
        try:
            # (v1.11.1) روی خودِ پاسخ هم دکمه‌ی پاسخ می‌گذاریم تا زنجیره‌ی گفتگو
            # ادامه پیدا کند و طرف مقابل مجبور نباشد از اول کشور را پیدا کند.
            await bot.send_message(
                original_sender.owner_user_id,
                f"📩 <b>پاسخ نامه از {country.flag} {country.name_fa}</b>\n\n{message.text}",
                reply_markup=_reply_kb(reply_letter.id),
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
        await safe_edit(call,NO_COUNTRY_TEXT)
        return
    inbox = await letters_repo.list_inbox(session, country.id)
    if not inbox:
        await safe_edit(call,"📭 صندوق پستی شما خالی است.", reply_markup=_back_mail_kb())
        return
    lines = ["📬 <b>صندوق پستی</b>", ""]
    builder = InlineKeyboardBuilder()
    for idx, ltr in enumerate(inbox[:20], start=1):
        sender = await countries_repo.get_country(session, ltr.sender_country)
        who = f"{sender.flag} {sender.name_fa}" if sender else "?"
        status = "✅ پاسخ داده شد" if ltr.replied else "🕒 بی‌پاسخ"
        kind = "📩 پاسخ" if ltr.parent_id else "✉️ نامه"
        preview = (ltr.body or "")[:60]
        lines.append(f"{fa_number(idx)}. {kind} از {who} — {status}\n   «{preview}»")
        # (v1.11.1) دکمه‌ی پاسخ روی **همه‌ی** نامه‌ها — حتی پاسخ‌داده‌شده‌ها — تا
        # بازیکن بتواند گفتگو را ادامه دهد و مجبور نباشد از اول کشور را پیدا کند.
        builder.button(
            text=f"📩 پاسخ به نامه‌ی {fa_number(idx)} ({sender.name_fa if sender else '?'})",
            callback_data=f"mail_reply:{ltr.id}",
            style=STYLE_OK,
        )
    builder.button(text="🔙 بازگشت", callback_data="dip:letter", style=STYLE_MAIN)
    builder.adjust(1)
    await safe_edit(call,"\n".join(lines), reply_markup=builder.as_markup())
