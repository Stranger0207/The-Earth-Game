"""هندلر جدید نبردهای نظامی، اعلان جنگ و تأیید مالکین (v2.0)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database.models import User
from ..database.repositories import countries as countries_repo
from ..keyboards.battle import (
    battle_attack_types_kb,
    battle_target_types_kb,
    sabotage_claim_kb,
)
from ..keyboards.common import confirm_cancel_kb, countries_kb
from ..keyboards.military import military_menu_kb
from ..services import battle_service
from ..services.news_service import send_log
from ..states.battle import BattleForm
from ..utils.screens import safe_edit
from ..utils.ui import header
from .deps import NO_COUNTRY_TEXT, get_player_country

router = Router(name="battle")
settings = get_settings()


# ============================================================
#  اعلام جنگ دیپلماتیک
# ============================================================
@router.callback_query(F.data == "dip:declare_war")
async def cb_declare_war_start(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """انتخاب کشور برای اعلام جنگ رسمی."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id]

    text = (
        header("اعلام جنگ رسمی", "🚨") + "\n\n"
        "برای حملات زمینی، هوایی و دریایی، ابتدا باید رسماً علیه کشور مقصد اعلام جنگ کنید.\n"
        "کشور مورد نظر جهت اعلام جنگ را انتخاب کنید:"
    )
    await safe_edit(
        call,
        text,
        reply_markup=countries_kb(others, prefix="war_decl_to", columns=2, back_data="menu:diplomacy"),
    )


@router.callback_query(F.data.startswith("war_decl_to:"))
async def cb_declare_war_confirm(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """اجرای ثبت و انتشار بیانیه اعلان جنگ."""
    await call.answer()
    target_id = int(call.data.split(":")[1])
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    target = await countries_repo.get_country(session, target_id)
    if target is None:
        await safe_edit(call, "کشور هدف یافت نشد.")
        return

    try:
        await battle_service.declare_war(session, declarer=country, target=target)
    except battle_service.BattleServiceError as err:
        await safe_edit(call, f"⛔️ خطا: {err}")
        return

    await safe_edit(
        call,
        f"🚨 **وضعیت جنگ علیه {target.flag} {target.name_fa} رسماً اعلام گردید.**\n"
        "بیانیه در کانال رسمی دیپلماسی منتشر شد.",
    )


# ============================================================
#  ثبت حملات نظامی (۴ نوع)
# ============================================================
@router.callback_query(F.data == "mil:attack")
async def cb_attack_start(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """شروع ثبت حمله نظامی جدید."""
    await call.answer()
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    await state.set_state(BattleForm.choosing_attack_type)
    text = (
        header("فرماندهی عملیات‌های نظامی", "⚔️") + "\n\n"
        "نوع حمله مورد نظر را انتخاب کنید:\n"
        "*(تذکر: برای حملات علنی زمینی/هوایی/دریایی باید قبلاً اعلام جنگ کرده باشید.)*"
    )
    await safe_edit(call, text, reply_markup=battle_attack_types_kb())


@router.callback_query(BattleForm.choosing_attack_type, F.data.startswith("btl_atype:"))
async def cb_attack_type(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """انتخاب کشور هدف حمله."""
    await call.answer()
    atype = call.data.split(":")[1]
    await state.update_data(attack_type=atype)

    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id]

    await state.set_state(BattleForm.choosing_target_country)
    await safe_edit(
        call,
        "🎯 **کشور هدف حمله را انتخاب کنید:**",
        reply_markup=countries_kb(others, prefix="btl_target_to", columns=2, back_data="mil:attack"),
    )


@router.callback_query(BattleForm.choosing_target_country, F.data.startswith("btl_target_to:"))
async def cb_attack_target_country(call: CallbackQuery, state: FSMContext) -> None:
    """انتخاب نوع هدف در کشور دشمن."""
    await call.answer()
    target_country_id = int(call.data.split(":")[1])
    await state.update_data(target_country_id=target_country_id)

    await state.set_state(BattleForm.choosing_target_type)
    await safe_edit(
        call,
        "🏢 **نوع هدف نبرد را مشخص کنید:**",
        reply_markup=battle_target_types_kb(),
    )


@router.callback_query(BattleForm.choosing_target_type, F.data.startswith("btl_ttype:"))
async def cb_attack_target_type(call: CallbackQuery, state: FSMContext) -> None:
    """دریافت نقشه و شرح متنی حمله."""
    await call.answer()
    ttype = call.data.split(":")[1]
    await state.update_data(target_type=ttype)

    data = await state.get_data()
    atype = data.get("attack_type")

    if atype == "sabotage":
        await state.set_state(BattleForm.choosing_sabotage_claim)
        await safe_edit(
            call,
            "🕵️ **تنظیمات مسئولیت خرابکاری:**\n\n"
            "آیا مایلید پس از عملیات، مسئولیت آن رسماً توسط کشور شما پذیرفته شود؟",
            reply_markup=sabotage_claim_kb(),
        )
    else:
        await state.update_data(claim_responsibility=True)
        await state.set_state(BattleForm.entering_payload)
        await safe_edit(
            call,
            "📝 **تجهیزات و نقشه حمله را شرح دهید (متن آزاد):**\n\n"
            "مثال: «حمله با ۳۰ تانک T-90 و ۱۰ نفربر به پایگاه زمینی مرزی دشمن با پشتیبانی توپخانه»"
        )


@router.callback_query(BattleForm.choosing_sabotage_claim, F.data.startswith("btl_claim:"))
async def cb_sabotage_claim(call: CallbackQuery, state: FSMContext) -> None:
    """ثبت انتخاب مسئولیت خرابکاری."""
    await call.answer()
    claim_val = call.data.split(":")[1] == "yes"
    await state.update_data(claim_responsibility=claim_val)

    await state.set_state(BattleForm.entering_payload)
    await safe_edit(
        call,
        "📝 **شرح دقیق عملیات خرابکاری:**\n\n"
        "مثال: «نفوذ به کارخانه فولاد دشمن و بمب‌گذاری در کوره‌های ذوب»"
    )


@router.message(BattleForm.entering_payload, F.text)
async def msg_attack_payload(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """ثبت و ارسال درخواست حمله به مدیریت بازی."""
    payload_text = message.text.strip()
    data = await state.get_data()
    await state.clear()

    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        return

    defender = await countries_repo.get_country(session, data["target_country_id"])
    if defender is None:
        await message.answer("کشور مدافع یافت نشد.")
        return

    try:
        battle = await battle_service.create_battle_request(
            session=session,
            attacker=country,
            defender=defender,
            attack_type=data["attack_type"],
            target_type=data["target_type"],
            payload_text=payload_text,
            claim_responsibility=data.get("claim_responsibility", True),
        )
    except battle_service.BattleServiceError as err:
        await message.answer(f"⛔️ خطا: {err}", reply_markup=military_menu_kb())
        return

    await message.answer(
        "✅ **درخواست عملیات نظامی شما با موفقیت ثبت شد.**\n\n"
        "این درخواست برای بررسی و تأیید اولیه‌ به فرماندهی کل مدیریت بازی ارسال شد. "
        "پس از تأیید، نبرد در فازهای متعدد خبری به اجرا در خواهد آمد.",
        reply_markup=military_menu_kb(),
    )


# ============================================================
#  تأیید نبرد توسط مالکین / مدیریت در گروه لاگ
# ============================================================
@router.callback_query(F.data.startswith("gapprove_btl:"))
async def cb_owner_approve_battle(call: CallbackQuery, session: AsyncSession) -> None:
    """تأیید نبرد توسط مالک بازی (کلیک از گروه لاگ)."""
    battle_id = int(call.data.split(":")[1])

    try:
        battle = await battle_service.approve_battle_by_owner(session, battle_id)
    except battle_service.BattleServiceError as err:
        await call.answer(str(err), show_alert=True)
        return

    await call.answer("نبرد تأیید شد و وارد فازهای اجرا گردید ✅")
    await safe_edit(call, call.message.html_text + "\n\n✅ **این عملیات توسط مدیریت تأیید و فاز ۱ نبرد شروع شد.**")


@router.callback_query(F.data.startswith("greject_btl:"))
async def cb_owner_reject_battle(call: CallbackQuery, session: AsyncSession) -> None:
    """رد نبرد توسط مالک بازی (کلیک از گروه لاگ)."""
    battle_id = int(call.data.split(":")[1])
    battle = await battle_repo.get_battle(session, battle_id)

    if not battle:
        await call.answer("نبرد یافت نشد.", show_alert=True)
        return

    battle.status = "rejected"
    await session.flush()

    await call.answer("حمله رد شد ❌")
    await safe_edit(call, call.message.html_text + "\n\n❌ **این حمله توسط مدیریت رد گردید.**")
