"""هندلر پنل تأسیسات هسته‌ای (v1.10.4) — فقط کشورهای VIP."""

from __future__ import annotations

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    CENTRIFUGE_BATCH_ALUMINUM,
    CENTRIFUGE_BATCH_COST_USD,
    CENTRIFUGE_BATCH_HOURS,
    CENTRIFUGE_BATCH_SIZE,
    CENTRIFUGE_BATCH_STEEL,
    ENRICHMENT_TIERS,
    NUCLEAR_COUNTERINTEL_COST_USD,
    NUCLEAR_FACILITIES,
    NUCLEAR_FACILITY_RESOURCES,
    NUCLEAR_TECHS,
    NUCLEAR_TEST_COST_USD,
    NUCLEAR_UNDERGROUND_COST_MULT,
    WARHEAD_ASSEMBLY_COST_USD,
    WARHEAD_HEU_REQUIRED_KG,
)
from ..database.models import User
from ..database.repositories import nuclear as nuc_repo
from ..database.repositories import reserves as reserves_repo
from ..enums import (
    DELIVERY_SYSTEM_FA,
    NUCLEAR_FACILITY_STATUS_FA,
    NUCLEAR_PHASE_FA,
    RESOURCE_FA,
    RESOURCE_UNIT_FA,
    DeliverySystem,
    NuclearFacilityStatus,
    NuclearFacilityType,
    NuclearPhase,
    NuclearTechType,
    ResourceType,
    WarheadStatus,
)
from ..keyboards.common import back_kb, confirm_cancel_kb
from ..keyboards.nuclear import (
    delivery_systems_kb,
    nuclear_arsenal_kb,
    nuclear_covert_kb,
    nuclear_enrich_menu_kb,
    nuclear_fac_menu_kb,
    nuclear_fac_types_kb,
    nuclear_main_menu_kb,
    nuclear_tech_kb,
    nuclear_tiers_kb,
    nuclear_underground_kb,
)
from ..services import nuclear_service
from ..services.news_service import send_log
from ..states.nuclear import NuclearForm
from ..utils.numbers import fa_money, fa_number
from ..utils.screens import safe_edit
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK, header
from .deps import NO_COUNTRY_TEXT, get_player_country

router = Router(name="nuclear")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fmt_eta(when: datetime) -> str:
    """فاصله‌ی زمانی تا یک لحظه به شکل «X ساعت و Y دقیقه»."""
    delta = when - _utcnow()
    total_min = max(0, int(delta.total_seconds() // 60))
    hours, minutes = divmod(total_min, 60)
    if hours and minutes:
        return f"{fa_number(hours)} ساعت و {fa_number(minutes)} دقیقه"
    if hours:
        return f"{fa_number(hours)} ساعت"
    return f"{fa_number(minutes)} دقیقه"


async def _vip_country_or_none(call: CallbackQuery, session: AsyncSession, db_user: User):
    """کشور بازیکن را برمی‌گرداند؛ اگر نبود یا VIP نبود، پیام مناسب می‌دهد و None."""
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return None
    if not country.is_vip:
        await call.answer("⛔️ فقط کشورهای VIP به برنامه‌ی هسته‌ای دسترسی دارند.", show_alert=True)
        return None
    return country


# ============================================================
#  منوی اصلی و وضعیت
# ============================================================


@router.callback_query(F.data == "mil:nuclear")
async def cb_nuclear_menu(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """منوی اصلی تأسیسات هسته‌ای."""
    await call.answer()
    await state.clear()
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return

    program = await nuc_repo.get_program(session, country.id)
    phase = NuclearPhase(program.phase) if program else NuclearPhase.NONE

    text = (
        header("تأسیسات هسته‌ای", "☢️") + "\n\n"
        "مسیر پنج‌فازی توسعه‌ی هسته‌ای: استخراج ← تبدیل ← غنی‌سازی ← تسلیحات ← آزمایش.\n"
        "هر اقدام «شاخص افشا» را بالا می‌برد — اگر برنامه کشف شود منتظر واکنش جهانی باشید!\n\n"
        f"🚩 وضعیت فعلی: <b>{NUCLEAR_PHASE_FA[phase]}</b>"
    )
    await safe_edit(call, text, reply_markup=nuclear_main_menu_kb())


@router.callback_query(F.data == "nuc:status")
async def cb_nuc_status(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """داشبورد وضعیت کامل برنامه."""
    await call.answer()
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return

    program = await nuc_repo.get_program(session, country.id)
    if program is None or program.phase == 0:
        await safe_edit(
            call,
            header("وضعیت برنامه", "📊") + "\n\n"
            "هنوز برنامه‌ی هسته‌ای آغاز نکرده‌اید.\n"
            "🧪 از بخش «تحقیقات و فناوری» با تحقیق «زمین‌شناسی سطح ۲» شروع کنید.",
            reply_markup=back_kb("mil:nuclear"),
        )
        return

    phase = NuclearPhase(program.phase)
    # نوار پیشرفت پنج‌فازی
    bar = "".join("🟩" if i <= program.phase else "⬜️" for i in range(1, 6))

    uranium = await reserves_repo.get_reserve(session, country.id, ResourceType.URANIUM)
    uranium_amount = uranium.amount if uranium else 0.0

    warheads = await nuc_repo.count_ready_warheads(session, country.id)
    facilities = await nuc_repo.list_facilities(session, country.id)
    active_fac = sum(1 for f in facilities if f.status == NuclearFacilityStatus.ACTIVE.value)

    # وضعیت افشا
    if program.is_discovered:
        exposure_line = "🚨 برنامه‌ی شما <b>کشف شده</b> و جهان از آن باخبر است!"
    else:
        exposure_line = f"🕵️ شاخص افشا: <b>{fa_number(program.exposure)}٪</b> (مخفی)"

    enrich_line = "⏸ غیرفعال"
    if program.enrich_tier:
        tier_fa = nuclear_service.tier_info(program.enrich_tier)[1]
        out_24h = nuclear_service.enrichment_output_per_24h(program)
        enrich_line = (
            f"▶️ به سمت {tier_fa} با {fa_number(program.enrich_centrifuges)} سانتریفیوژ "
            f"(≈{out_24h:.1f} کیلوگرم در ۲۴ ساعت)"
        )

    text = (
        header("وضعیت برنامه‌ی هسته‌ای", "📊") + "\n\n"
        f"{bar}\n"
        f"🚩 {NUCLEAR_PHASE_FA[phase]}\n\n"
        f"☢️ سنگ اورانیوم: {fa_number(uranium_amount, 1)} تن\n"
        f"🟡 کیک زرد: {fa_number(program.yellowcake_tons, 1)} تن\n"
        f"💨 گاز UF6: {fa_number(program.uf6_tons, 1)} تن\n"
        f"⚛️ غنی‌شده ۳.۵٪: {fa_number(program.leu_35_kg, 1)} kg | "
        f"۲۰٪: {fa_number(program.leu_20_kg, 1)} kg\n"
        f"⚛️ غنی‌شده ۶۰٪: {fa_number(program.heu_60_kg, 1)} kg | "
        f"<b>۹۰٪: {fa_number(program.heu_90_kg, 1)} kg</b>\n\n"
        f"⚙️ سانتریفیوژها: {fa_number(program.centrifuges)}\n"
        f"🔄 غنی‌سازی: {enrich_line}\n"
        f"🏗 تأسیسات فعال: {fa_number(active_fac)} از {fa_number(len(facilities))}\n"
        f"☢️ کلاهک آماده: <b>{fa_number(warheads)}</b>\n\n"
        f"{exposure_line}"
    )
    await safe_edit(call, text, reply_markup=back_kb("mil:nuclear"))


# ============================================================
#  تحقیقات
# ============================================================


@router.callback_query(F.data == "nuc:tech")
async def cb_nuc_tech(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """فهرست فناوری‌ها با وضعیت هرکدام."""
    await call.answer()
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return

    techs = await nuc_repo.list_techs(session, country.id)
    done = {t.tech_type for t in techs if t.is_done}
    pending = {t.tech_type for t in techs if not t.is_done}

    lines = []
    for ttype, (name_fa, cost, days, prereq) in NUCLEAR_TECHS.items():
        if ttype.value in done:
            status = "✅ تکمیل‌شده"
        elif ttype.value in pending:
            tech = next(t for t in techs if t.tech_type == ttype.value)
            status = f"⏳ {_fmt_eta(nuclear_service.tech_done_at(tech))} مانده"
        else:
            status = f"💵 {fa_money(cost)}"
        lines.append(f"• {name_fa} — {status}")

    text = (
        header("تحقیقات و فناوری هسته‌ای", "🧪") + "\n\n"
        + "\n".join(lines)
        + "\n\nفناوری‌ها زنجیره‌ای هستند؛ هر یک پیش‌نیاز بعدی است."
    )
    await safe_edit(call, text, reply_markup=nuclear_tech_kb(done, pending))


@router.callback_query(F.data.startswith("nuc_tech:"))
async def cb_nuc_tech_start(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """شروع تحقیق یک فناوری (با تأیید)."""
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return

    tech_value = call.data.split(":", 1)[1]
    ttype = NuclearTechType(tech_value)
    name_fa, cost, days, prereq = NUCLEAR_TECHS[ttype]

    existing = await nuc_repo.get_tech(session, country.id, ttype)
    if existing is not None:
        await call.answer("این فناوری قبلاً شروع/تکمیل شده است.", show_alert=True)
        return

    await call.answer()
    hours = nuclear_service.spec_days_to_hours(days)
    text = (
        header("تأیید تحقیق", "🧪") + "\n\n"
        f"فناوری: <b>{name_fa}</b>\n"
        f"💵 هزینه: {fa_money(cost)}\n"
        f"⏱ زمان تحقیق: {fa_number(hours)} ساعت\n\n"
        "آیا مطمئنید؟"
    )
    await safe_edit(call, text, reply_markup=confirm_cancel_kb(f"nuc_tech_ok:{tech_value}", "nuc:tech"))


@router.callback_query(F.data.startswith("nuc_tech_ok:"))
async def cb_nuc_tech_confirm(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """اجرای شروع تحقیق."""
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return

    ttype = NuclearTechType(call.data.split(":", 1)[1])
    try:
        tech = await nuclear_service.research_tech(session, country, ttype)
    except nuclear_service.NuclearError as exc:
        await call.answer(str(exc), show_alert=True)
        return

    await session.commit()
    await call.answer("تحقیق آغاز شد ✅")
    name_fa = NUCLEAR_TECHS[ttype][0]
    done_at = nuclear_service.tech_done_at(tech)
    await safe_edit(
        call,
        header("تحقیق آغاز شد", "🧪") + "\n\n"
        f"فناوری «<b>{name_fa}</b>» در حال تحقیق است.\n"
        f"⏳ زمان اتمام: {_fmt_eta(done_at)} دیگر\n"
        "پس از تکمیل، به شما اطلاع داده می‌شود.",
        reply_markup=back_kb("nuc:tech"),
    )
    await send_log(
        call.bot,
        f"🧪 <b>شروع تحقیق هسته‌ای</b>\nکشور: {country.flag} {country.name_fa}\nفناوری: {name_fa}",
    )


# ============================================================
#  تأسیسات
# ============================================================


@router.callback_query(F.data == "nuc:fac")
async def cb_nuc_fac(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """منوی تأسیسات هسته‌ای."""
    await call.answer()
    await state.clear()
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return
    await safe_edit(
        call,
        header("تأسیسات هسته‌ای", "🏗") + "\n\n"
        "زنجیره‌ی تولید: آسیاب کیک زرد ← کارخانه‌ی تبدیل UF6 ← سالن غنی‌سازی.\n"
        "ساخت زیرزمینی گران‌تر است اما کمتر دیده می‌شود و در برابر حمله مقاوم‌تر است.",
        reply_markup=nuclear_fac_menu_kb(),
    )


@router.callback_query(F.data == "nuc_fac:list")
async def cb_nuc_fac_list(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """فهرست تأسیسات کشور."""
    await call.answer()
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return

    facilities = await nuc_repo.list_facilities(session, country.id)
    if not facilities:
        await safe_edit(
            call,
            header("تأسیسات من", "📋") + "\n\nهنوز تأسیساتی نساخته‌اید.",
            reply_markup=back_kb("nuc:fac"),
        )
        return

    lines = []
    for f in facilities:
        status = NUCLEAR_FACILITY_STATUS_FA[NuclearFacilityStatus(f.status)]
        if f.status == NuclearFacilityStatus.BUILDING.value:
            status += f" ({_fmt_eta(nuclear_service.facility_done_at(f))} مانده)"
        ug = " 🕳" if f.is_underground else ""
        integrity = f" | 🛡 {fa_number(f.integrity_pct)}٪" if f.integrity_pct < 100 else ""
        lines.append(f"• <b>{f.name}</b>{ug} — {f.location or '—'}\n  {status}{integrity}")

    await safe_edit(
        call,
        header("تأسیسات من", "📋") + "\n\n" + "\n".join(lines),
        reply_markup=back_kb("nuc:fac"),
    )


@router.callback_query(F.data == "nuc_fac:build")
async def cb_nuc_fac_build(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """انتخاب نوع تأسیسات برای احداث."""
    await call.answer()
    await state.clear()
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return

    lines = []
    for ftype, (name_fa, cost, days, prereq_tech, max_count) in NUCLEAR_FACILITIES.items():
        hours = nuclear_service.spec_days_to_hours(days)
        needed = NUCLEAR_FACILITY_RESOURCES.get(ftype, {})
        res_txt = "، ".join(
            f"{fa_number(a)} {RESOURCE_UNIT_FA[r]} {RESOURCE_FA[r]}" for r, a in needed.items()
        )
        lines.append(
            f"• <b>{name_fa}</b>: {fa_money(cost)} + {res_txt}\n"
            f"  ⏱ {fa_number(hours)} ساعت | سقف: {fa_number(max_count)} | "
            f"پیش‌نیاز: {NUCLEAR_TECHS[prereq_tech][0]}"
        )

    await safe_edit(
        call,
        header("احداث تأسیسات هسته‌ای", "🏗") + "\n\n" + "\n".join(lines),
        reply_markup=nuclear_fac_types_kb(),
    )


@router.callback_query(F.data.startswith("nuc_fac_type:"))
async def cb_nuc_fac_type(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """پس از انتخاب نوع → انتخاب سطحی/زیرزمینی."""
    await call.answer()
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return

    ftype_value = call.data.split(":", 1)[1]
    ftype = NuclearFacilityType(ftype_value)
    name_fa, cost, days, _prereq, _max = NUCLEAR_FACILITIES[ftype]

    await state.update_data(nuc_ftype=ftype_value)
    ug_cost = cost * NUCLEAR_UNDERGROUND_COST_MULT
    await safe_edit(
        call,
        header("نوع ساخت", "🏗") + "\n\n"
        f"تأسیسات: <b>{name_fa}</b>\n\n"
        f"🏗 سطحی: {fa_money(cost)}\n"
        f"🕳 زیرزمینی: {fa_money(ug_cost)} (افشای کمتر + نصف خسارت در حمله، زمان ساخت بیشتر)",
        reply_markup=nuclear_underground_kb(),
    )


@router.callback_query(F.data.startswith("nuc_ug:"))
async def cb_nuc_underground(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """پس از انتخاب سطحی/زیرزمینی → پرسیدن محل احداث."""
    await call.answer()
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return

    data = await state.get_data()
    if "nuc_ftype" not in data:
        await call.answer("فرم منقضی شده؛ دوباره تلاش کنید.", show_alert=True)
        return

    underground = call.data.split(":", 1)[1] == "yes"
    await state.update_data(nuc_underground=underground)
    await state.set_state(NuclearForm.entering_facility_location)
    await safe_edit(
        call,
        header("محل احداث", "📍") + "\n\n"
        "نام شهر/منطقه‌ی محل احداث را بنویسید (مثلاً: نطنز):",
        reply_markup=back_kb("nuc:fac"),
    )


@router.message(NuclearForm.entering_facility_location)
async def msg_nuc_location(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """دریافت محل و نمایش تأیید نهایی."""
    location = (message.text or "").strip()
    if not location or len(location) > 64:
        await message.answer("نام محل نامعتبر است؛ حداکثر ۶۴ کاراکتر بنویسید.")
        return

    data = await state.get_data()
    ftype = NuclearFacilityType(data["nuc_ftype"])
    underground = bool(data.get("nuc_underground"))
    name_fa, cost, days, _prereq, _max = NUCLEAR_FACILITIES[ftype]
    total = cost * (NUCLEAR_UNDERGROUND_COST_MULT if underground else 1.0)

    await state.update_data(nuc_location=location)
    await state.set_state(None)
    await message.answer(
        header("تأیید احداث", "🏗") + "\n\n"
        f"تأسیسات: <b>{name_fa}</b>{' 🕳 (زیرزمینی)' if underground else ''}\n"
        f"📍 محل: {location}\n"
        f"💵 هزینه: {fa_money(total)}\n\n"
        "آیا مطمئنید؟",
        reply_markup=confirm_cancel_kb("nuc_fac_ok", "nuc:fac"),
    )


@router.callback_query(F.data == "nuc_fac_ok")
async def cb_nuc_fac_confirm(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """اجرای احداث تأسیسات."""
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return

    data = await state.get_data()
    if "nuc_ftype" not in data or "nuc_location" not in data:
        await call.answer("فرم منقضی شده؛ دوباره تلاش کنید.", show_alert=True)
        return

    ftype = NuclearFacilityType(data["nuc_ftype"])
    try:
        facility = await nuclear_service.build_nuclear_facility(
            session,
            country,
            ftype,
            data["nuc_location"],
            bool(data.get("nuc_underground")),
        )
    except nuclear_service.NuclearError as exc:
        await call.answer(str(exc), show_alert=True)
        return

    await session.commit()
    await state.clear()
    await call.answer("احداث آغاز شد ✅")
    done_at = nuclear_service.facility_done_at(facility)
    await safe_edit(
        call,
        header("احداث آغاز شد", "🏗") + "\n\n"
        f"«<b>{facility.name}</b>» در {facility.location} در حال ساخت است.\n"
        f"⏳ زمان اتمام: {_fmt_eta(done_at)} دیگر",
        reply_markup=back_kb("nuc:fac"),
    )
    await send_log(
        call.bot,
        "☢️ <b>احداث تأسیسات هسته‌ای</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"تأسیسات: {facility.name}{' (زیرزمینی)' if facility.is_underground else ''}\n"
        f"محل: {facility.location}",
    )


# ============================================================
#  غنی‌سازی
# ============================================================


@router.callback_query(F.data == "nuc:enrich")
async def cb_nuc_enrich(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """منوی غنی‌سازی و سانتریفیوژ."""
    await call.answer()
    await state.clear()
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return

    program = await nuc_repo.get_program(session, country.id)
    if program is None:
        await safe_edit(
            call,
            header("غنی‌سازی", "⚙️") + "\n\nابتدا از بخش تحقیقات، برنامه‌ی هسته‌ای را آغاز کنید.",
            reply_markup=back_kb("mil:nuclear"),
        )
        return

    capacity = await nuc_repo.enrichment_capacity(session, country.id)

    enrich_line = "⏸ غیرفعال"
    if program.enrich_tier:
        tier_fa = nuclear_service.tier_info(program.enrich_tier)[1]
        out = nuclear_service.enrichment_output_per_24h(program)
        enrich_line = f"▶️ {tier_fa} — ≈{out:.1f} کیلوگرم در ۲۴ ساعت"

    batch_line = ""
    batch_done = program.centrifuge_batch_done_at
    if batch_done is not None:
        if batch_done.tzinfo is None:
            batch_done = batch_done.replace(tzinfo=timezone.utc)
        batch_line = (
            f"\n🔄 چرخه‌ی تولید فعال: {fa_number(CENTRIFUGE_BATCH_SIZE)} سانتریفیوژ "
            f"({_fmt_eta(batch_done)} مانده)"
        )

    text = (
        header("غنی‌سازی اورانیوم", "⚙️") + "\n\n"
        f"⚙️ سانتریفیوژها: {fa_number(program.centrifuges)} "
        f"(ظرفیت سالن‌ها: {fa_number(capacity)}){batch_line}\n"
        f"💨 خوراک UF6: {fa_number(program.uf6_tons, 1)} تن\n"
        f"🔄 وضعیت: {enrich_line}\n\n"
        f"⚙️ هر چرخه‌ی تولید: {fa_number(CENTRIFUGE_BATCH_SIZE)} سانتریفیوژ | "
        f"{fa_money(CENTRIFUGE_BATCH_COST_USD)} | {fa_number(CENTRIFUGE_BATCH_HOURS)} ساعت"
    )
    await safe_edit(call, text, reply_markup=nuclear_enrich_menu_kb(program.enrich_tier is not None))


@router.callback_query(F.data == "nuc_en:make")
async def cb_nuc_make_centrifuge(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """تأیید تولید سانتریفیوژ."""
    await call.answer()
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return
    await safe_edit(
        call,
        header("تولید سانتریفیوژ", "⚙️") + "\n\n"
        f"تعداد: {fa_number(CENTRIFUGE_BATCH_SIZE)} عدد\n"
        f"💵 هزینه: {fa_money(CENTRIFUGE_BATCH_COST_USD)}\n"
        f"🏗 فولاد: {fa_number(CENTRIFUGE_BATCH_STEEL)} تن | "
        f"🔩 آلومینیوم: {fa_number(CENTRIFUGE_BATCH_ALUMINUM)} تن\n"
        f"⏱ زمان: {fa_number(CENTRIFUGE_BATCH_HOURS)} ساعت\n\n"
        "آیا مطمئنید؟",
        reply_markup=confirm_cancel_kb("nuc_en_make_ok", "nuc:enrich"),
    )


@router.callback_query(F.data == "nuc_en_make_ok")
async def cb_nuc_make_centrifuge_ok(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """اجرای شروع چرخه‌ی تولید سانتریفیوژ."""
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return
    try:
        done_at = await nuclear_service.produce_centrifuges(session, country)
    except nuclear_service.NuclearError as exc:
        await call.answer(str(exc), show_alert=True)
        return
    await session.commit()
    await call.answer("چرخه‌ی تولید آغاز شد ✅")
    await safe_edit(
        call,
        header("تولید سانتریفیوژ", "⚙️") + "\n\n"
        f"چرخه‌ی تولید {fa_number(CENTRIFUGE_BATCH_SIZE)} سانتریفیوژ آغاز شد.\n"
        f"⏳ اتمام: {_fmt_eta(done_at)} دیگر",
        reply_markup=back_kb("nuc:enrich"),
    )


@router.callback_query(F.data == "nuc_en:start")
async def cb_nuc_enrich_start(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """انتخاب رده‌ی هدف غنی‌سازی."""
    await call.answer()
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return

    lines = []
    for key, name_fa, pct, swu, prereq in ENRICHMENT_TIERS:
        feed = "UF6" if prereq is None else nuclear_service.tier_info(prereq)[1]
        lines.append(f"• {name_fa} — خوراک: {feed} | {fa_number(swu)} SWU بر کیلوگرم")

    await safe_edit(
        call,
        header("انتخاب رده‌ی غنی‌سازی", "⚛️") + "\n\n" + "\n".join(lines) + "\n\n"
        "⚠️ غنی‌سازی بالای ۲۰٪ افشای سنگینی دارد و با پوشش صلح‌آمیز ممکن نیست.",
        reply_markup=nuclear_tiers_kb(),
    )


@router.callback_query(F.data.startswith("nuc_tier:"))
async def cb_nuc_tier(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """پس از انتخاب رده → پرسیدن تعداد سانتریفیوژ."""
    await call.answer()
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return

    tier_key = call.data.split(":", 1)[1]
    program = await nuc_repo.get_program(session, country.id)
    capacity = await nuc_repo.enrichment_capacity(session, country.id)
    available = min(program.centrifuges if program else 0, capacity)

    await state.update_data(nuc_tier=tier_key)
    await state.set_state(NuclearForm.entering_centrifuge_count)
    tier_fa = nuclear_service.tier_info(tier_key)[1]
    await safe_edit(
        call,
        header("تخصیص سانتریفیوژ", "⚙️") + "\n\n"
        f"رده‌ی هدف: <b>{tier_fa}</b>\n"
        f"حداکثر قابل‌تخصیص: {fa_number(available)}\n\n"
        "چند سانتریفیوژ تخصیص می‌دهید؟ (عدد بنویسید)",
        reply_markup=back_kb("nuc:enrich"),
    )


@router.message(NuclearForm.entering_centrifuge_count)
async def msg_nuc_centrifuge_count(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """دریافت تعداد سانتریفیوژ و شروع غنی‌سازی."""
    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        return

    try:
        count = int((message.text or "").strip().replace(",", "").replace("،", ""))
    except ValueError:
        await message.answer("یک عدد صحیح بنویسید.")
        return

    data = await state.get_data()
    tier_key = data.get("nuc_tier")
    if not tier_key:
        await message.answer("فرم منقضی شده؛ دوباره از منوی غنی‌سازی شروع کنید.")
        await state.clear()
        return

    try:
        await nuclear_service.start_enrichment(session, country, tier_key, count)
    except nuclear_service.NuclearError as exc:
        await message.answer(f"⚠️ {exc}")
        return

    await session.commit()
    await state.clear()
    program = await nuc_repo.get_program(session, country.id)
    out = nuclear_service.enrichment_output_per_24h(program)
    tier_fa = nuclear_service.tier_info(tier_key)[1]
    await message.answer(
        header("غنی‌سازی آغاز شد", "⚛️") + "\n\n"
        f"رده‌ی هدف: <b>{tier_fa}</b>\n"
        f"⚙️ سانتریفیوژ فعال: {fa_number(count)}\n"
        f"📈 نرخ تولید: ≈{out:.1f} کیلوگرم در ۲۴ ساعت\n\n"
        "پیشرفت به‌صورت خودکار محاسبه و به شما گزارش می‌شود.",
        reply_markup=back_kb("nuc:enrich"),
    )
    await send_log(
        message.bot,
        "⚛️ <b>شروع غنی‌سازی</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"رده: {tier_fa} | سانتریفیوژ: {fa_number(count)}",
    )


@router.callback_query(F.data == "nuc_en:stop")
async def cb_nuc_enrich_stop(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """توقف غنی‌سازی فعال."""
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return
    try:
        await nuclear_service.stop_enrichment(session, country)
    except nuclear_service.NuclearError as exc:
        await call.answer(str(exc), show_alert=True)
        return
    await session.commit()
    await call.answer("غنی‌سازی متوقف شد.")
    await safe_edit(
        call,
        header("غنی‌سازی", "⏸") + "\n\nفرآیند غنی‌سازی متوقف شد.",
        reply_markup=back_kb("nuc:enrich"),
    )


# ============================================================
#  زرادخانه
# ============================================================


@router.callback_query(F.data == "nuc:arsenal")
async def cb_nuc_arsenal(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """نمایش زرادخانه‌ی کلاهک‌ها."""
    await call.answer()
    await state.clear()
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return

    program = await nuc_repo.get_program(session, country.id)
    warheads = await nuc_repo.list_warheads(session, country.id)

    lines = []
    has_assembled = False
    for wh in warheads:
        if wh.status == WarheadStatus.ASSEMBLING.value:
            status_fa = f"🔧 در حال مونتاژ ({_fmt_eta(nuclear_service.warhead_done_at(wh))} مانده)"
        elif wh.status == WarheadStatus.ASSEMBLED.value:
            status_fa = "☢️ آماده در انبار"
            has_assembled = True
        elif wh.status == WarheadStatus.MOUNTED.value and wh.delivery_system:
            status_fa = f"🚀 نصب روی {DELIVERY_SYSTEM_FA[DeliverySystem(wh.delivery_system)]}"
        else:
            status_fa = wh.status
        lines.append(f"• <b>{wh.name}</b> — {fa_number(wh.yield_kt)} کیلوتن — {status_fa}")

    heu = program.heu_90_kg if program else 0.0
    text = (
        header("زرادخانه‌ی هسته‌ای", "☢️") + "\n\n"
        + ("\n".join(lines) if lines else "زرادخانه خالی است.")
        + f"\n\n⚛️ موجودی HEU ۹۰٪: {fa_number(heu, 1)} کیلوگرم\n"
        f"(هر کلاهک: {fa_number(WARHEAD_HEU_REQUIRED_KG)} کیلوگرم HEU + {fa_money(WARHEAD_ASSEMBLY_COST_USD)})"
    )
    await safe_edit(call, text, reply_markup=nuclear_arsenal_kb(has_assembled))


@router.callback_query(F.data == "nuc_ar:make")
async def cb_nuc_warhead_make(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """پرسیدن نام کلاهک."""
    await call.answer()
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return
    await state.set_state(NuclearForm.entering_warhead_name)
    await safe_edit(
        call,
        header("مونتاژ کلاهک", "🔧") + "\n\n"
        "یک نام برای کلاهک بنویسید (مثلاً: سیمرغ-۱):",
        reply_markup=back_kb("nuc:arsenal"),
    )


@router.message(NuclearForm.entering_warhead_name)
async def msg_nuc_warhead_name(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """دریافت نام و شروع مونتاژ."""
    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        return

    name = (message.text or "").strip()
    if not name or len(name) > 64:
        await message.answer("نام نامعتبر است؛ حداکثر ۶۴ کاراکتر.")
        return

    try:
        warhead = await nuclear_service.assemble_warhead(session, country, name)
    except nuclear_service.NuclearError as exc:
        await message.answer(f"⚠️ {exc}")
        return

    await session.commit()
    await state.clear()
    await message.answer(
        header("مونتاژ آغاز شد", "🔧") + "\n\n"
        f"کلاهک «<b>{warhead.name}</b>» در حال مونتاژ است.\n"
        f"⏳ اتمام: {_fmt_eta(nuclear_service.warhead_done_at(warhead))} دیگر",
        reply_markup=back_kb("nuc:arsenal"),
    )
    await send_log(
        message.bot,
        "☢️ <b>شروع مونتاژ کلاهک هسته‌ای</b>\n"
        f"کشور: {country.flag} {country.name_fa}\nنام: {warhead.name}",
    )


@router.callback_query(F.data == "nuc_ar:mount")
async def cb_nuc_mount(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """انتخاب کلاهک برای نصب روی سامانه‌ی حمل."""
    await call.answer()
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return

    warheads = [
        wh for wh in await nuc_repo.list_warheads(session, country.id)
        if wh.status == WarheadStatus.ASSEMBLED.value
    ]
    if not warheads:
        await call.answer("کلاهک مونتاژشده‌ای در انبار ندارید.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for wh in warheads:
        builder.button(
            text=f"☢️ {wh.name} ({fa_number(wh.yield_kt)}kt)",
            callback_data=f"nuc_mount:{wh.id}",
            style=STYLE_OK,
        )
    builder.button(text="🔙 بازگشت", callback_data="nuc:arsenal", style=STYLE_MAIN)
    builder.adjust(1)
    await safe_edit(
        call,
        header("نصب کلاهک", "🚀") + "\n\nکدام کلاهک را نصب می‌کنید؟",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("nuc_mount:"))
async def cb_nuc_mount_pick(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """انتخاب سامانه‌ی حمل برای کلاهک انتخاب‌شده."""
    await call.answer()
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return
    warhead_id = int(call.data.split(":", 1)[1])
    await safe_edit(
        call,
        header("سامانه‌ی حمل", "🚀") + "\n\nسامانه‌ی حمل را انتخاب کنید:",
        reply_markup=delivery_systems_kb(warhead_id),
    )


@router.callback_query(F.data.startswith("nuc_dlv:"))
async def cb_nuc_delivery(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """اجرای نصب کلاهک روی سامانه."""
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return

    _, warhead_id_s, system_value = call.data.split(":", 2)
    system = DeliverySystem(system_value)
    try:
        warhead = await nuclear_service.mount_warhead(session, country, int(warhead_id_s), system)
    except nuclear_service.NuclearError as exc:
        await call.answer(str(exc), show_alert=True)
        return

    await session.commit()
    await call.answer("کلاهک نصب شد ✅")
    await safe_edit(
        call,
        header("نصب کامل شد", "🚀") + "\n\n"
        f"کلاهک «<b>{warhead.name}</b>» روی {DELIVERY_SYSTEM_FA[system]} نصب شد.\n"
        "☢️ قدرت بازدارندگی کشور شما افزایش یافت.",
        reply_markup=back_kb("nuc:arsenal"),
    )
    await send_log(
        call.bot,
        "🚀 <b>نصب کلاهک روی سامانه‌ی حمل</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"کلاهک: {warhead.name} → {DELIVERY_SYSTEM_FA[system]}",
    )


# ============================================================
#  آزمایش هسته‌ای
# ============================================================


@router.callback_query(F.data == "nuc:test")
async def cb_nuc_test(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """انتخاب کلاهک برای آزمایش هسته‌ای."""
    await call.answer()
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return

    warheads = [
        wh for wh in await nuc_repo.list_warheads(session, country.id)
        if wh.status in (WarheadStatus.ASSEMBLED.value, WarheadStatus.MOUNTED.value)
    ]
    if not warheads:
        await safe_edit(
            call,
            header("آزمایش هسته‌ای", "💥") + "\n\n"
            "کلاهک آماده‌ای برای آزمایش ندارید.\n"
            "برای آزمایش، سایت آزمایش فعال + یک کلاهک آماده لازم است.",
            reply_markup=back_kb("mil:nuclear"),
        )
        return

    builder = InlineKeyboardBuilder()
    for wh in warheads:
        builder.button(
            text=f"💥 {wh.name} ({fa_number(wh.yield_kt)}kt)",
            callback_data=f"nuc_test_pick:{wh.id}",
            style=STYLE_NO,
        )
    builder.button(text="🔙 بازگشت", callback_data="mil:nuclear", style=STYLE_MAIN)
    builder.adjust(1)
    await safe_edit(
        call,
        header("آزمایش هسته‌ای", "💥") + "\n\n"
        f"💵 هزینه: {fa_money(NUCLEAR_TEST_COST_USD)}\n"
        "⚠️ کلاهک در آزمایش <b>مصرف می‌شود</b> و برنامه‌ی شما <b>کاملاً افشا</b> خواهد شد!\n"
        "در عوض: اعتبار جهانی هسته‌ای + رضایت عمومی.\n\n"
        "کدام کلاهک را آزمایش می‌کنید؟",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("nuc_test_pick:"))
async def cb_nuc_test_pick(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """تأیید نهایی آزمایش."""
    await call.answer()
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return

    warhead_id = int(call.data.split(":", 1)[1])
    warhead = await nuc_repo.get_warhead(session, warhead_id)
    if warhead is None or warhead.country_id != country.id:
        await call.answer("کلاهک یافت نشد.", show_alert=True)
        return

    await safe_edit(
        call,
        header("تأیید آزمایش هسته‌ای", "💥") + "\n\n"
        f"کلاهک: <b>{warhead.name}</b> ({fa_number(warhead.yield_kt)} کیلوتن)\n"
        f"💵 هزینه: {fa_money(NUCLEAR_TEST_COST_USD)}\n\n"
        "🚨 <b>هشدار نهایی:</b> این اقدام غیرقابل‌بازگشت است؛ کلاهک مصرف و برنامه‌ی شما "
        "برای همیشه افشا می‌شود. آیا کاملاً مطمئنید؟",
        reply_markup=confirm_cancel_kb(f"nuc_test_ok:{warhead_id}", "mil:nuclear"),
    )


@router.callback_query(F.data.startswith("nuc_test_ok:"))
async def cb_nuc_test_confirm(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """اجرای زمان‌بندی آزمایش هسته‌ای."""
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return

    warhead_id = int(call.data.split(":", 1)[1])
    try:
        test = await nuclear_service.schedule_nuclear_test(session, country, warhead_id)
    except nuclear_service.NuclearError as exc:
        await call.answer(str(exc), show_alert=True)
        return

    await session.commit()
    await call.answer("آزمایش زمان‌بندی شد ✅")
    sched = test.scheduled_at
    if sched is not None and sched.tzinfo is None:
        sched = sched.replace(tzinfo=timezone.utc)
    await safe_edit(
        call,
        header("آزمایش در حال آماده‌سازی", "💥") + "\n\n"
        f"آزمایش هسته‌ای در سایت «{test.site_name}» زمان‌بندی شد.\n"
        f"⏳ اجرا: {_fmt_eta(sched) if sched else '—'} دیگر\n"
        "پس از انفجار، خبر آن در سراسر جهان منتشر خواهد شد!",
        reply_markup=back_kb("mil:nuclear"),
    )
    await send_log(
        call.bot,
        "💥 <b>زمان‌بندی آزمایش هسته‌ای</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"سایت: {test.site_name} | قدرت: {fa_number(test.yield_kt)}kt",
    )


# ============================================================
#  پنهان‌کاری و امنیت
# ============================================================


@router.callback_query(F.data == "nuc:covert")
async def cb_nuc_covert(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """منوی پنهان‌کاری."""
    await call.answer()
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return

    program = await nuclear_service.ensure_program(session, country)
    await session.commit()

    cover_line = "🎭 پوشش صلح‌آمیز: " + ("✅ فعال (سقف غنی‌سازی ۲۰٪، افشای کمتر)" if program.civilian_cover else "❌ غیرفعال")
    npt_line = "📜 پیمان NPT: " + ("✅ عضو" if program.npt_member else "❌ خارج‌شده")
    disc_line = (
        "🚨 برنامه <b>کشف شده</b> است." if program.is_discovered
        else f"🕵️ شاخص افشا: <b>{fa_number(program.exposure)}٪</b>"
    )

    await safe_edit(
        call,
        header("پنهان‌کاری و امنیت", "🕵️") + "\n\n"
        f"{disc_line}\n{cover_line}\n{npt_line}\n\n"
        f"🕵️ عملیات ضدجاسوسی: {fa_money(NUCLEAR_COUNTERINTEL_COST_USD)} — کاهش شاخص افشا (هر ۲۴ ساعت یک‌بار)",
        reply_markup=nuclear_covert_kb(program),
    )


@router.callback_query(F.data.startswith("nuc_cv:"))
async def cb_nuc_covert_action(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """اقدامات پنهان‌کاری: پوشش، ضدجاسوسی، خروج از NPT."""
    country = await _vip_country_or_none(call, session, db_user)
    if country is None:
        return

    action = call.data.split(":", 1)[1]
    program = await nuclear_service.ensure_program(session, country)

    if action == "cover_on":
        program.civilian_cover = True
        await session.commit()
        await call.answer("پوشش صلح‌آمیز فعال شد ✅")
    elif action == "cover_off":
        program.civilian_cover = False
        await session.commit()
        await call.answer("پوشش صلح‌آمیز غیرفعال شد.")
    elif action == "counterintel":
        try:
            drop = await nuclear_service.run_counterintel(session, country)
        except nuclear_service.NuclearError as exc:
            await call.answer(str(exc), show_alert=True)
            return
        await session.commit()
        await call.answer(f"شاخص افشا {fa_number(drop)} واحد کاهش یافت ✅", show_alert=True)
    elif action == "npt_exit":
        if not program.npt_member:
            await call.answer("قبلاً از NPT خارج شده‌اید.", show_alert=True)
            return
        program.npt_member = False
        # خروج از NPT خودش یک سیگنال جهانی بزرگ است
        nuclear_service.add_exposure(program, 20.0)
        await session.commit()
        await call.answer("از پیمان NPT خارج شدید — جهان مشکوک شد!", show_alert=True)
        from ..enums import NewsCategory
        from ..services.news_service import publish_news

        try:
            await publish_news(
                call.bot,
                NewsCategory.DIPLOMACY,
                "🔴 <b>خبر فوری دیپلماتیک!!</b>\n\n"
                f"📜 کشور {country.flag} <b>{country.name_fa}</b> رسماً از پیمان منع گسترش "
                "سلاح‌های هسته‌ای (NPT) خارج شد!\n"
                "⚠️ ناظران بین‌المللی این اقدام را نشانه‌ی احتمال توسعه‌ی برنامه‌ی هسته‌ای نظامی می‌دانند.",
            )
        except Exception:  # noqa: BLE001
            pass
        await send_log(
            call.bot,
            f"📜 خروج از NPT — {country.flag} {country.name_fa}",
        )

    # بازگشت به منوی پنهان‌کاری با وضعیت تازه
    await cb_nuc_covert(call, session, db_user)
