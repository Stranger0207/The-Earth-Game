"""
هندلر تأسیسات مشترک (v1.9): انتخاب شریک → نوع تأسیسات → درصد شریک → محل،
سپس درخواست برای شریک. با تأیید شریک، هزینه به نسبت تقسیم و تأسیسات ساخته می‌شود
و بازدهی هر ۲۴ ساعت به همان نسبت بین دو کشور تقسیم می‌شود (در زمان‌بند).
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import FACILITY_COST_USD
from ..database.models import JointBuildRequest, User
from ..database.repositories import countries as countries_repo
from ..enums import FACILITY_FA, RESOURCE_FA, FacilityType, ResourceType
from ..keyboards.common import countries_kb
from ..keyboards.economy import (
    economy_menu_kb,
    joint_facility_types_kb,
    joint_mine_resources_kb,
)
from ..loader import bot
from ..services.economy_service import EconomyError, build_joint_facility
from ..services.news_service import send_log
from ..states import JointFacilityForm
from ..utils.numbers import fa_money, fa_number, parse_amount
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK
from .deps import NO_COUNTRY_TEXT, get_player_country

router = Router(name="joint")


def _back_build_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="econ:build", style=STYLE_MAIN)
    ]])


@router.callback_query(F.data == "joint:start")
async def cb_joint_start(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    await state.set_state(JointFacilityForm.choosing_partner)
    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id and c.owner_user_id is not None]
    await call.message.edit_text(
        "🤝 <b>تأسیسات مشترک</b>\n\nشریک تجاری خود را انتخاب کنید:",
        reply_markup=countries_kb(others, prefix="joint_partner", columns=2, back_data="econ:build"),
    )


@router.callback_query(JointFacilityForm.choosing_partner, F.data.startswith("joint_partner:"))
async def cb_joint_partner(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await call.answer()
    partner = await countries_repo.get_country(session, int(call.data.split(":")[1]))
    if partner is None or partner.owner_user_id is None:
        await call.message.edit_text("شریک نامعتبر است.", reply_markup=_back_build_kb())
        return
    await state.update_data(partner_id=partner.id)
    await state.set_state(JointFacilityForm.choosing_type)
    await call.message.edit_text(
        f"🤝 شریک: {partner.flag} {partner.name_fa}\n\nنوع تأسیسات مشترک را انتخاب کنید:",
        reply_markup=joint_facility_types_kb(),
    )


@router.callback_query(JointFacilityForm.choosing_type, F.data.startswith("joint_type:"))
async def cb_joint_type(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    ftype = FacilityType(call.data.split(":")[1])
    await state.update_data(facility_type=ftype.value)
    cost = FACILITY_COST_USD[ftype]
    if ftype == FacilityType.MINE:
        await state.set_state(JointFacilityForm.choosing_resource)
        await call.message.edit_text(
            f"⛏ معدن مشترک چه منبعی؟\n💰 هزینه‌ی کل: {fa_money(cost)}",
            reply_markup=joint_mine_resources_kb(),
        )
    else:
        await state.update_data(resource=None)
        await state.set_state(JointFacilityForm.entering_percent)
        await call.message.edit_text(
            f"🏭 {FACILITY_FA[ftype]} مشترک\n💰 هزینه‌ی کل: {fa_money(cost)}\n\n"
            "درصد سهم شریک را وارد کنید (۱ تا ۹۹، مثلاً 40):",
            reply_markup=_back_build_kb(),
        )


@router.callback_query(JointFacilityForm.choosing_resource, F.data.startswith("joint_res:"))
async def cb_joint_resource(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.update_data(resource=call.data.split(":")[1])
    await state.set_state(JointFacilityForm.entering_percent)
    await call.message.edit_text(
        "درصد سهم شریک را وارد کنید (۱ تا ۹۹، مثلاً 40):",
        reply_markup=_back_build_kb(),
    )


@router.message(JointFacilityForm.entering_percent, F.text)
async def msg_joint_percent(message: Message, state: FSMContext) -> None:
    pct = parse_amount(message.text)
    if pct is None or pct < 1 or pct > 99:
        await message.answer("لطفاً عددی بین ۱ تا ۹۹ وارد کنید.")
        return
    await state.update_data(percent=float(pct))
    await state.set_state(JointFacilityForm.entering_location)
    await message.answer("📍 محل احداث را وارد کنید:")


@router.message(JointFacilityForm.entering_location, F.text)
async def msg_joint_location(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    data = await state.get_data()
    await state.clear()
    country = await get_player_country(session, db_user)
    partner = await countries_repo.get_country(session, data.get("partner_id"))
    if country is None or partner is None:
        await message.answer("خطا در ثبت درخواست.")
        return
    ftype = FacilityType(data["facility_type"])
    resource = data.get("resource")
    percent = float(data.get("percent", 0))
    location = message.text.strip()
    cost = FACILITY_COST_USD[ftype]
    partner_share = cost * percent / 100.0
    owner_share = cost - partner_share

    req = JointBuildRequest(
        initiator_country=country.id,
        partner_country=partner.id,
        facility_type=ftype.value,
        resource=resource,
        partner_percent=percent,
        location=location,
        cost=cost,
        status="pending",
    )
    session.add(req)
    await session.flush()

    label = FACILITY_FA[ftype]
    if resource:
        try:
            label = f"{FACILITY_FA[ftype]} {RESOURCE_FA[ResourceType(resource)]}"
        except (ValueError, KeyError):
            pass

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ تأیید و پرداخت سهم", callback_data=f"joint_ok:{req.id}", style=STYLE_OK),
        InlineKeyboardButton(text="❌ رد", callback_data=f"joint_no:{req.id}", style=STYLE_NO),
    ]])
    try:
        await bot.send_message(
            partner.owner_user_id,
            f"🤝 <b>درخواست تأسیسات مشترک</b> از {country.flag} {country.name_fa}\n\n"
            f"تأسیسات: {label}\n📍 محل: {location}\n"
            f"💰 هزینه‌ی کل: {fa_money(cost)}\n"
            f"سهم شما ({fa_number(percent)}٪): {fa_money(partner_share)}\n"
            f"سهم {country.name_fa} ({fa_number(100 - percent)}٪): {fa_money(owner_share)}\n\n"
            "با تأیید، سهم شما از بودجه‌تان کسر می‌شود.",
            reply_markup=kb,
        )
    except Exception:  # noqa: BLE001
        pass
    await message.answer(
        f"📨 درخواست تأسیسات مشترک برای {partner.flag} {partner.name_fa} ارسال شد. "
        "پس از تأیید او، تأسیسات احداث می‌شود.",
        reply_markup=economy_menu_kb(),
    )


@router.callback_query(F.data.startswith("joint_ok:"))
async def cb_joint_ok(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    req = await session.get(JointBuildRequest, int(call.data.split(":")[1]))
    if req is None or req.status != "pending":
        await call.answer("این درخواست دیگر معتبر نیست.", show_alert=True)
        return
    partner = await get_player_country(session, db_user)
    if partner is None or partner.id != req.partner_country:
        await call.answer("شما مجاز به تأیید این درخواست نیستید.", show_alert=True)
        return
    initiator = await countries_repo.get_country(session, req.initiator_country)
    if initiator is None:
        await call.answer("کشور سازنده یافت نشد.", show_alert=True)
        return
    ftype = FacilityType(req.facility_type)
    try:
        facility = await build_joint_facility(
            session, initiator, partner, ftype, req.resource, req.location, req.partner_percent
        )
    except EconomyError as exc:
        await call.answer(str(exc), show_alert=True)
        return
    req.status = "done"
    await call.answer("تأسیسات مشترک ساخته شد ✅")

    label = FACILITY_FA[ftype]
    await call.message.edit_text(
        call.message.html_text + "\n\n✅ <b>تأیید شد</b> — تأسیسات مشترک احداث شد."
    )
    if initiator.owner_user_id:
        try:
            await bot.send_message(
                initiator.owner_user_id,
                f"✅ {partner.flag} {partner.name_fa} درخواست تأسیسات مشترک «{label}» را تأیید کرد و احداث شد.",
            )
        except Exception:  # noqa: BLE001
            pass
    await send_log(
        bot,
        "🤝 <b>تأسیسات مشترک</b>\n"
        f"سازنده: {initiator.flag} {initiator.name_fa}\n"
        f"شریک: {partner.flag} {partner.name_fa} ({fa_number(req.partner_percent)}٪)\n"
        f"تأسیسات: {label}\n📍 محل: {req.location}",
    )


@router.callback_query(F.data.startswith("joint_no:"))
async def cb_joint_no(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    req = await session.get(JointBuildRequest, int(call.data.split(":")[1]))
    if req is None or req.status != "pending":
        await call.answer()
        return
    req.status = "rejected"
    await call.answer("رد شد")
    await call.message.edit_text(call.message.html_text + "\n\n❌ <b>رد شد</b>")
    initiator = await countries_repo.get_country(session, req.initiator_country)
    if initiator and initiator.owner_user_id:
        try:
            await bot.send_message(
                initiator.owner_user_id, "❌ درخواست تأسیسات مشترک شما رد شد."
            )
        except Exception:  # noqa: BLE001
            pass
