"""هندلر برنامه فضایی و ماهواره‌های جاسوسی (v2.0)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import (
    SPY_SATELLITE_ALUMINUM_COST,
    SPY_SATELLITE_COST_USD,
    SPY_SATELLITE_OIL_COST,
    SPY_SATELLITE_STEEL_COST,
)
from ..database.models import User
from ..database.repositories import countries as countries_repo
from ..database.repositories import satellites as sat_repo
from ..keyboards.common import confirm_cancel_kb, countries_kb
from ..keyboards.military import military_menu_kb
from ..keyboards.satellite import satellite_main_menu_kb
from ..services import satellite_service
from ..states.satellite import SatelliteForm
from ..utils.numbers import fa_money, fa_number
from ..utils.screens import safe_edit
from ..utils.ui import header
from .deps import NO_COUNTRY_TEXT, get_player_country

router = Router(name="satellite")
settings = get_settings()


@router.callback_query(F.data == "mil:sat")
async def cb_sat_menu(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """منوی اصلی ماهواره‌های فضایی."""
    await call.answer()
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    text = (
        header("برنامه فضایی و ماهواره", "📡") + "\n\n"
        "کشورهای VIP می‌توانند با پرتاب ماهواره‌های جاسوسی به مدار زمین، "
        "پایگاه‌های نظامی، نیروهای مستقر و تجهیزات انبار سایر کشورها را رصد کنند."
    )
    await safe_edit(call, text, reply_markup=satellite_main_menu_kb())


@router.callback_query(F.data == "sat:launch")
async def cb_sat_launch_start(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """شروع پرتاب ماهواره جدید."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    if not country.is_vip:
        await safe_edit(
            call,
            "⛔️ فقط کشورهای VIP می‌توانند ماهواره فضایی پرتاب کنند.",
            reply_markup=satellite_main_menu_kb(),
        )
        return

    success_rate = await satellite_service.calculate_launch_success_rate(session, country)
    await state.set_state(SatelliteForm.entering_satellite_name)

    text = (
        header("پرتاب ماهواره جاسوسی", "🚀") + "\n\n"
        f"📊 **شانس موفقیت پرتاب:** {success_rate:.1f}%\n"
        f"💰 **هزینه:** {fa_money(SPY_SATELLITE_COST_USD)}\n"
        f"🧱 **منابع لازم:**\n"
        f" • نفت: {SPY_SATELLITE_OIL_COST} میلیون بشکه\n"
        f" • فولاد: {fa_number(SPY_SATELLITE_STEEL_COST)} تن\n"
        f" • آلومینیوم: {fa_number(SPY_SATELLITE_ALUMINUM_COST)} تن\n\n"
        "✍️ لطفاً نام ماهواره جدید را وارد کنید (مثال: نور-۱):"
    )
    await safe_edit(call, text)


@router.message(SatelliteForm.entering_satellite_name, F.text)
async def msg_sat_name(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """تأیید و اجرای پرتاب ماهواره."""
    sat_name = message.text.strip()
    await state.clear()

    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        return

    await message.answer("⏳ **در حال آماده‌سازی سکوی پرتاب و سوخت‌گیری موشک حامل...**")

    try:
        sat, is_success = await satellite_service.launch_spy_satellite(
            session=session, country=country, satellite_name=sat_name
        )
    except satellite_service.SatelliteServiceError as err:
        await message.answer(f"⛔️ خطا: {err}", reply_markup=satellite_main_menu_kb())
        return

    if is_success:
        await message.answer(
            f"🚀 **پرتاب موفقیت‌آمیز بود!**\n\n"
            f"ماهواره «**{sat.name}**» با موفقیت از جو زمین خارج شد و به سمت مدار قرارگیری در حرکت است.\n"
            f"⏱ زمان رسیدن به مدار: ۳۰ دقیقه دیگر.",
            reply_markup=satellite_main_menu_kb(),
        )
    else:
        await message.answer(
            f"💥 **پرتاب با شکست مواجه شد!**\n\n"
            f"موشک حامل ماهواره «**{sat.name}**» دچار آسیب فیزیکی شد و متلاشی گردید.\n"
            "منابع و هزینه‌های ساخت از بین رفت.",
            reply_markup=satellite_main_menu_kb(),
        )


@router.callback_query(F.data == "sat:list")
async def cb_sat_list(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """فهرست ماهواره‌های پرتاب‌شده توسط کاربر."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    sats = await sat_repo.list_satellites_by_country(session, country.id)
    if not sats:
        await safe_edit(call, "📋 شما تاکنون هیچ ماهواره‌ای پرتاب نکرده‌اید.", reply_markup=satellite_main_menu_kb())
        return

    lines = [header("ماهواره‌های شما", "📡"), ""]
    status_map = {
        "launching": "🚀 در حال پرواز به مدار",
        "in_orbit": "🛰 فعال در مدار",
        "failed": "💥 پرتاب ناموفق",
        "expired": "⌛️ منقضی شده",
    }

    for s in sats:
        st_fa = status_map.get(s.status, s.status)
        lines.append(f"• **{s.name}** ({st_fa})")

    await safe_edit(call, "\n".join(lines), reply_markup=satellite_main_menu_kb())


@router.callback_query(F.data == "sat:scan")
async def cb_sat_scan_start(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """انتخاب کشور هدف برای رصد جاسوسی ماهواره‌ای."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    active_sats = await sat_repo.list_active_orbit_satellites(session, country.id)
    if not active_sats:
        await safe_edit(
            call,
            "⚠️ برای رصد جاسوسی، باید حداقل یک ماهواره فعال در مدار زمین داشته باشید (`in_orbit`).",
            reply_markup=satellite_main_menu_kb(),
        )
        return

    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id]

    await state.set_state(SatelliteForm.choosing_target_country)
    await safe_edit(
        call,
        header("رصد جاسوسی ماهواره‌ای", "🔭") + "\n\nکدام کشور را می‌خواهید رصد ماهواره‌ای کنید؟",
        reply_markup=countries_kb(others, prefix="sat_scan_to", columns=2, back_data="mil:sat"),
    )


@router.callback_query(SatelliteForm.choosing_target_country, F.data.startswith("sat_scan_to:"))
async def cb_sat_scan_exec(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """اجرای اسکن ماهواره‌ای و رندر گزارش جاسوسی."""
    await call.answer()
    target_id = int(call.data.split(":")[1])
    await state.clear()

    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    try:
        data = await satellite_service.spy_scan_target_country(
            session=session, owner_country_id=country.id, target_country_id=target_id
        )
    except satellite_service.SatelliteServiceError as err:
        await safe_edit(call, f"⛔️ خطا: {err}", reply_markup=satellite_main_menu_kb())
        return

    lines = [
        header(f"گزارش رصد ماهواره‌ای: {data['target_country']}", "🕵️"),
        "",
        "🏛 **پایگاه‌های نظامی شناسایی‌شده:**",
    ]

    if not data["bases"]:
        lines.append(" ◦ هیچ پایگاه نظامی در خاک این کشور مشاهده نشد.")
    else:
        for b in data["bases"]:
            lines.append(f"• **{b['name']}** (مالک: {b['owner']} | محل: {b['location']})")
            for eq in b["equipments"]:
                lines.append(f"   - {eq['name']}: {fa_number(eq['count'])} عدد")

    lines.append("")
    lines.append("🪖 **نیروهای نظامی مستقر در منطقه:**")
    if not data["deployments"]:
        lines.append(" ◦ نیروی مستقری شناسایی نشد.")
    else:

        for d in data["deployments"]:
            lines.append(f"• {d['branch']} ({d['asset_name']}: {fa_number(d['count'])}) -> منطقه {d['region']}")

    lines.append("")
    lines.append("☢️ **تأسیسات هسته‌ای قابل‌مشاهده:**")
    if not data["nuclear_facilities"]:
        if data.get("nuclear_hidden_count", 0) > 0:
            lines.append(" ◦ هیچ تأسیسات سطحی شناسایی نشد، اما نشانه‌هایی از فعالیت مشکوک زیرزمینی وجود دارد.")
        else:
            lines.append(" ◦ هیچ تأسیسات هسته‌ای مشاهده نشد.")
    else:
        for nf in data["nuclear_facilities"]:
            lines.append(f"• <b>{nf['name']}</b> — {nf['location']} ({nf['status']})")
        if data.get("nuclear_hidden_count", 0) > 0:
            lines.append(f"\n⚠️ <i>علاوه بر تأسیسات فوق، {fa_number(data['nuclear_hidden_count'])} محل مشکوک زیرزمینی نیز شناسایی شد که جزئیات آن از دید ماهواره پنهان است.</i>")

    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[:3900] + "\n..."

    await safe_edit(call, text, reply_markup=satellite_main_menu_kb())
