"""
هندلر سیستم اتحاد (v1.9): فقط کشورهای VIP می‌توانند اتحاد بسازند و حداکثر
ALLIANCE_MAX_MEMBERS کشور را به اتحاد خود بیاورند. هر کشور حداکثر در یک اتحاد است.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import ALLIANCE_MAX_MEMBERS
from ..database.models import User
from ..database.repositories import alliances as alli_repo
from ..database.repositories import countries as countries_repo
from ..keyboards.common import confirm_cancel_kb
from ..loader import bot
from ..services.news_service import send_log
from ..states import AllianceForm
from ..utils.numbers import fa_number
from ..utils.ui import PICK_OFF, PICK_ON, STYLE_MAIN, STYLE_NO, STYLE_OK
from .deps import NO_COUNTRY_TEXT, get_player_country

router = Router(name="alliance")


def _alliance_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛡 اتحاد من", callback_data="alli:mine", style=STYLE_MAIN)],
        [InlineKeyboardButton(text="➕ ایجاد اتحاد جدید", callback_data="alli:create", style=STYLE_OK)],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu:diplomacy", style=STYLE_MAIN)],
    ])


def _back_alliance_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="dip:alliance", style=STYLE_MAIN)
    ]])


async def _president_name(session: AsyncSession, country) -> str:
    from ..database.repositories import users as users_repo
    if country is None:
        return "—"
    if country.owner_user_id:
        u = await users_repo.get_user(session, country.owner_user_id)
        if u and u.president_name:
            return u.president_name
    return country.name_fa


# ============================================================
#  منوی اتحاد
# ============================================================
@router.callback_query(F.data == "dip:alliance")
async def cb_alliance(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.answer()
    await call.message.edit_text(
        "🤝 <b>اتحادها</b>\n\nیک گزینه را انتخاب کنید:",
        reply_markup=_alliance_menu_kb(),
    )


@router.callback_query(F.data == "alli:mine")
async def cb_alliance_mine(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    membership = await alli_repo.get_membership(session, country.id)
    if membership is None:
        await call.message.edit_text("شما عضو هیچ اتحادی نیستید.", reply_markup=_back_alliance_kb())
        return
    alliance = await alli_repo.get_alliance(session, membership.alliance_id)
    if alliance is None:
        await call.message.edit_text("اتحاد یافت نشد.", reply_markup=_back_alliance_kb())
        return
    owner = await countries_repo.get_country(session, alliance.owner_country)
    owner_pres = await _president_name(session, owner)
    members = await alli_repo.list_members(session, alliance.id)
    member_lines = []
    for m in members:
        c = await countries_repo.get_country(session, m.country_id)
        if c:
            tag = " 👑" if c.id == alliance.owner_country else ""
            member_lines.append(f"• {c.flag} {c.name_fa}{tag}")
    text = (
        f"🛡 <b>اتحاد «{alliance.name}»</b>\n\n"
        f"👑 مالک اتحاد: {owner.flag if owner else ''} {owner.name_fa if owner else '?'} "
        f"(رئیس‌جمهور {owner_pres})\n"
        f"👥 اعضا ({fa_number(len(members))}):\n" + "\n".join(member_lines)
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 مفاد اتحاد", callback_data="alli:terms", style=STYLE_MAIN)],
        [InlineKeyboardButton(text="🚪 خروج از اتحاد", callback_data="alli:leave", style=STYLE_NO)],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="dip:alliance", style=STYLE_MAIN)],
    ])
    await call.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data == "alli:terms")
async def cb_alliance_terms(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    membership = await alli_repo.get_membership(session, country.id)
    if membership is None:
        await call.message.edit_text("شما عضو هیچ اتحادی نیستید.", reply_markup=_back_alliance_kb())
        return
    alliance = await alli_repo.get_alliance(session, membership.alliance_id)
    terms = (alliance.terms if alliance else "") or "مفادی ثبت نشده است."
    await call.message.edit_text(
        f"📜 <b>مفاد اتحاد «{alliance.name if alliance else ''}»</b>\n\n{terms}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 بازگشت", callback_data="alli:mine", style=STYLE_MAIN)
        ]]),
    )


@router.callback_query(F.data == "alli:leave")
async def cb_alliance_leave(call: CallbackQuery) -> None:
    await call.answer()
    await call.message.edit_text(
        "❓ آیا مطمئن هستید که می‌خواهید از اتحاد خارج شوید؟\n"
        "اگر سازنده‌ی اتحاد باشید، کل اتحاد منحل می‌شود.",
        reply_markup=confirm_cancel_kb("alli:leave_confirm", cancel_data="alli:mine"),
    )


@router.callback_query(F.data == "alli:leave_confirm")
async def cb_alliance_leave_confirm(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    membership = await alli_repo.get_membership(session, country.id)
    if membership is None:
        await call.message.edit_text("شما عضو هیچ اتحادی نیستید.", reply_markup=_back_alliance_kb())
        return
    alliance = await alli_repo.get_alliance(session, membership.alliance_id)
    if alliance is None:
        await call.message.edit_text("اتحاد یافت نشد.", reply_markup=_back_alliance_kb())
        return
    name = alliance.name
    if alliance.owner_country == country.id:
        # سازنده خارج شد → انحلال اتحاد و اطلاع به اعضا
        members = await alli_repo.list_members(session, alliance.id)
        member_ids = [m.country_id for m in members if m.country_id != country.id]
        await alli_repo.delete_alliance(session, alliance.id)
        for cid in member_ids:
            c = await countries_repo.get_country(session, cid)
            if c and c.owner_user_id:
                try:
                    await bot.send_message(c.owner_user_id, f"⚠️ اتحاد «{name}» توسط سازنده منحل شد.")
                except Exception:  # noqa: BLE001
                    pass
        await call.message.edit_text(f"✅ اتحاد «{name}» منحل شد.", reply_markup=_back_alliance_kb())
        await send_log(bot, f"🛡 <b>انحلال اتحاد</b>\nاتحاد «{name}» توسط {country.flag} {country.name_fa} منحل شد.")
    else:
        await alli_repo.remove_member(session, alliance.id, country.id)
        await call.message.edit_text(f"✅ شما از اتحاد «{name}» خارج شدید.", reply_markup=_back_alliance_kb())
        owner = await countries_repo.get_country(session, alliance.owner_country)
        if owner and owner.owner_user_id:
            try:
                await bot.send_message(owner.owner_user_id, f"🚪 {country.flag} {country.name_fa} از اتحاد «{name}» خارج شد.")
            except Exception:  # noqa: BLE001
                pass
        await send_log(bot, f"🚪 <b>خروج از اتحاد</b>\n{country.flag} {country.name_fa} از اتحاد «{name}» خارج شد.")


# ============================================================
#  ساخت اتحاد جدید (فقط VIP)
# ============================================================
@router.callback_query(F.data == "alli:create")
async def cb_alliance_create(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    if not country.is_vip:
        await call.message.edit_text(
            "⛔️ فقط کشورهای VIP می‌توانند اتحاد بسازند.", reply_markup=_back_alliance_kb()
        )
        return
    if await alli_repo.get_membership(session, country.id) is not None:
        await call.message.edit_text(
            "⛔️ شما هم‌اکنون عضو یک اتحاد هستید. ابتدا از آن خارج شوید.",
            reply_markup=_back_alliance_kb(),
        )
        return
    await state.set_state(AllianceForm.entering_name)
    await call.message.edit_text("🛡 نام اتحاد را وارد کنید:", reply_markup=_back_alliance_kb())


@router.message(AllianceForm.entering_name, F.text)
async def msg_alliance_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text.strip())
    await state.set_state(AllianceForm.entering_terms)
    await message.answer("📜 مفاد و شرایط اتحاد را بنویسید:")


def _members_select_kb(others, selected: set[int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for c in others:
        chosen = c.id in selected
        mark = PICK_ON if chosen else PICK_OFF
        builder.button(
            text=f"{mark} {c.flag} {c.name_fa}",
            callback_data=f"alli_pick:{c.id}",
            style=STYLE_OK if chosen else STYLE_MAIN,
        )
    builder.adjust(2)
    cont = f"✅ ساخت اتحاد ({fa_number(len(selected))})" if selected else "✅ ساخت اتحاد"
    builder.row(InlineKeyboardButton(text=cont, callback_data="alli_create_done", style=STYLE_OK))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="dip:alliance", style=STYLE_MAIN))
    return builder.as_markup()


@router.message(AllianceForm.entering_terms, F.text)
async def msg_alliance_terms(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await state.update_data(terms=message.text.strip(), selected=[])
    country = await get_player_country(session, db_user)
    if country is None:
        await state.clear()
        await message.answer(NO_COUNTRY_TEXT)
        return
    await state.set_state(AllianceForm.selecting_members)
    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id and c.owner_user_id is not None]
    await message.answer(
        f"👥 کشورهایی که می‌خواهید به اتحاد بیاورید را انتخاب کنید (حداکثر {fa_number(ALLIANCE_MAX_MEMBERS)} کشور):",
        reply_markup=_members_select_kb(others, set()),
    )


@router.callback_query(AllianceForm.selecting_members, F.data.startswith("alli_pick:"))
async def cb_alliance_pick(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    cid = int(call.data.split(":")[1])
    data = await state.get_data()
    selected = set(data.get("selected", []))
    if cid in selected:
        selected.discard(cid)
    else:
        if len(selected) >= ALLIANCE_MAX_MEMBERS:
            await call.answer(f"حداکثر {ALLIANCE_MAX_MEMBERS} کشور مجاز است.", show_alert=True)
            return
        selected.add(cid)
    await state.update_data(selected=list(selected))
    country = await get_player_country(session, db_user)
    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id and c.owner_user_id is not None]
    await call.message.edit_reply_markup(reply_markup=_members_select_kb(others, selected))


@router.callback_query(AllianceForm.selecting_members, F.data == "alli_create_done")
async def cb_alliance_create_done(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    data = await state.get_data()
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    name = data.get("name", "اتحاد")
    terms = data.get("terms", "")
    selected = data.get("selected", [])[:ALLIANCE_MAX_MEMBERS]

    alliance = await alli_repo.create_alliance(session, name, terms, country.id)
    added_names = []
    for cid in selected:
        ok = await alli_repo.add_member(session, alliance.id, cid)
        c = await countries_repo.get_country(session, cid)
        if ok and c:
            added_names.append(f"{c.flag} {c.name_fa}")
            if c.owner_user_id:
                try:
                    await bot.send_message(
                        c.owner_user_id,
                        f"🛡 کشور شما به اتحاد «{name}» به سازندگی "
                        f"{country.flag} {country.name_fa} پیوست.",
                    )
                except Exception:  # noqa: BLE001
                    pass
    await call.message.edit_text(
        f"✅ اتحاد «{name}» ساخته شد.\n"
        f"اعضای افزوده‌شده: {('، '.join(added_names)) or '—'}",
        reply_markup=_back_alliance_kb(),
    )
    await send_log(
        bot,
        f"🛡 <b>اتحاد جدید</b>\n"
        f"نام: {name}\nسازنده: {country.flag} {country.name_fa}\n"
        f"اعضا: {('، '.join(added_names)) or '—'}",
    )
