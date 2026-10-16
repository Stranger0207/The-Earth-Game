"""هندلر برنامه فضایی: تفکیک ماهواره نظامی و اقتصادی (v2.8)."""

from __future__ import annotations

from datetime import datetime, timezone
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import (
    ECON_SAT_ALUMINUM_COST,
    ECON_SAT_BUILD_COST_USD,
    ECON_SAT_LEVEL_CONFIG,
    ECON_SAT_OIL_COST,
    ECON_SAT_STEEL_COST,
    MIL_SAT_RECON_COST,
    MIL_SAT_SCAN_COOLDOWN_HOURS,
    SATELLITE_LAUNCH_COOLDOWN_HOURS,
    SPY_SATELLITE_ALUMINUM_COST,
    SPY_SATELLITE_COST_USD,
    SPY_SATELLITE_OIL_COST,
    SPY_SATELLITE_STEEL_COST,
)
from ..database.models import EconSatReceipt, User
from ..database.repositories import countries as countries_repo
from ..database.repositories import satellites as sat_repo
from ..keyboards.common import countries_kb
from ..keyboards.satellite import (
    admin_receipt_review_kb,
    econ_cancel_kb,
    econ_sat_buy_confirm_kb,
    economic_satellite_kb,
    military_satellite_kb,
    satellite_hub_kb,
    satellite_main_menu_kb,
)
from ..loader import bot
from ..services import satellite_service
from ..services.news_service import send_log, send_log_photo
from ..states.satellite import SatelliteForm
from ..utils.numbers import fa_money, fa_number
from ..utils.screens import safe_edit
from ..utils.ui import header, STYLE_NO, STYLE_OK
from .deps import NO_COUNTRY_TEXT, assert_feature, get_player_country

router = Router(name="satellite")
settings = get_settings()


def _is_admin_or_owner(user_id: int) -> bool:
    return settings.is_owner(user_id) or settings.is_admin(user_id)


# ============================================================
#  📡 منوی هاب برنامه فضایی (هاب تفکیک‌شده)
# ============================================================

@router.callback_query(F.data == "mil:sat")
async def cb_sat_hub(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """منوی اصلی هاب ماهواره‌های فضایی (تفکیک نظامی و اقتصادی)."""
    await call.answer()
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "military.satellite"):
        return

    text = (
        header("برنامه فضایی و ماهواره", "📡") + "\n\n"
        "به مرکز توسعه و پرتاب ماهواره‌های فضایی خوش آمدید.\n"
        "می‌توانید وارد بخش ماهواره‌های نظامی (ویژه VIP) یا ماهواره‌های اقتصادی-تجاری شوید:"
    )
    await safe_edit(call, text, reply_markup=satellite_hub_kb())


# ============================================================
#  🛰 بخش ۱: ماهواره‌های نظامی و جاسوسی (ویژه VIP)
# ============================================================

@router.callback_query(F.data == "sat:mil_menu")
async def cb_sat_mil_menu(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """منوی اختصاصی ماهواره نظامی."""
    await call.answer()
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "military.satellite"):
        return

    if not country.is_vip:
        await safe_edit(
            call,
            "⛔️ برنامه ماهواره نظامی منحصراً در اختیار کشورهای VIP است.",
            reply_markup=satellite_hub_kb(),
        )
        return

    text = (
        header("ماهواره‌های نظامی و جاسوسی", "🛰") + "\n\n"
        "کشورهای VIP می‌توانند با پرتاب ماهواره‌های جاسوسی نظامی، "
        "پایگاه‌ها، استقرار نیروها و تجهیزات سایر کشورها را رصد کنند.\n\n"
        f"⏱ **کول‌داون پرتاب:** {SATELLITE_LAUNCH_COOLDOWN_HOURS} ساعت پس از هر پرتاب\n"
        f"💵 **هزینه هر بار رصد:** {fa_money(MIL_SAT_RECON_COST)}\n"
        f"⏳ **کول‌داون رصد:** هر {MIL_SAT_SCAN_COOLDOWN_HOURS} ساعت یک‌بار"
    )
    await safe_edit(call, text, reply_markup=military_satellite_kb())


@router.callback_query(F.data.in_(["sat:launch", "sat:mil_launch"]))
async def cb_sat_launch_start(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """شروع پرتاب ماهواره جاسوسی جدید."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    if not country.is_vip:
        await safe_edit(
            call,
            "⛔️ فقط کشورهای VIP می‌توانند ماهواره جاسوسی نظامی پرتاب کنند.",
            reply_markup=military_satellite_kb(),
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
    await safe_edit(call, text, reply_markup=econ_cancel_kb())


@router.message(SatelliteForm.entering_satellite_name, F.text)
async def msg_sat_name(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """تأیید و اجرای پرتاب ماهواره نظامی."""
    sat_name = message.text.strip()
    await state.clear()

    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        return

    await message.answer("⏳ **در حال سوخت‌گیری موشک حامل و آماده‌سازی سکوی پرتاب...**")

    try:
        sat, is_success = await satellite_service.launch_spy_satellite(
            session=session, country=country, satellite_name=sat_name
        )
    except satellite_service.SatelliteServiceError as err:
        await message.answer(f"⛔️ خطا: {err}", reply_markup=military_satellite_kb())
        return

    if is_success:
        await message.answer(
            f"🚀 **پرتاب موفقیت‌آمیز بود!**\n\n"
            f"ماهواره «**{sat.name}**» با موفقیت از جو خارج شد و به سمت مدار قرارگیری در حرکت است.\n"
            f"⏱ زمان رسیدن به مدار: ۳۰ دقیقه دیگر.",
            reply_markup=military_satellite_kb(),
        )
    else:
        await message.answer(
            f"💥 **پرتاب با شکست مواجه شد!**\n\n"
            f"موشک حامل ماهواره «**{sat.name}**» در مرحله دوم دچار نقص فنی شد و متلاشی گردید.\n"
            "منابع و هزینه‌های ساخت از بین رفت.",
            reply_markup=military_satellite_kb(),
        )


@router.callback_query(F.data.in_(["sat:list", "sat:mil_list"]))
async def cb_sat_list(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """فهرست ماهواره‌های نظامی کشور."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    sats = await sat_repo.list_satellites_by_country_and_type(session, country.id, "spy")
    if not sats:
        await safe_edit(
            call,
            "📋 شما تاکنون هیچ ماهواره نظامی پرتاب نکرده‌اید.",
            reply_markup=military_satellite_kb(),
        )
        return

    lines = [header("ماهواره‌های نظامی شما", "🛰"), ""]
    status_map = {
        "launching": "🚀 در حال پرواز به مدار",
        "in_orbit": "🛰 فعال در مدار",
        "failed": "💥 پرتاب ناموفق",
        "expired": "⌛️ منقضی شده",
    }

    for s in sats:
        st_fa = status_map.get(s.status, s.status)
        lines.append(f"• **{s.name}** ({st_fa})")

    await safe_edit(call, "\n".join(lines), reply_markup=military_satellite_kb())


@router.callback_query(F.data.in_(["sat:scan", "sat:mil_scan"]))
async def cb_sat_scan_start(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """انتخاب کشور هدف برای رصد جاسوسی ماهواره‌ای."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    if not country.is_vip:
        await safe_edit(call, "⛔️ فقط کشورهای VIP دسترسی به رصد ماهواره‌ای دارند.", reply_markup=satellite_hub_kb())
        return

    active_sats = await sat_repo.list_active_orbit_satellites(session, country.id)
    if not active_sats:
        await safe_edit(
            call,
            "⚠️ برای رصد جاسوسی، باید حداقل یک ماهواره فعال در مدار زمین داشته باشید (`in_orbit`).",
            reply_markup=military_satellite_kb(),
        )
        return

    if country.budget < MIL_SAT_RECON_COST:
        await safe_edit(
            call,
            f"⛔️ بودجه کافی نیست! هزینه رصد ماهواره‌ای {fa_money(MIL_SAT_RECON_COST)} است.",
            reply_markup=military_satellite_kb(),
        )
        return

    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id]

    await state.set_state(SatelliteForm.choosing_target_country)
    text = (
        header("رصد جاسوسی ماهواره‌ای", "🔭") + "\n\n"
        f"💵 **هزینه رصد:** {fa_money(MIL_SAT_RECON_COST)}\n"
        f"⏳ **محدودیت:** هر ۶ ساعت یک‌بار\n\n"
        "کدام کشور را می‌خواهید رصد ماهواره‌ای کنید؟"
    )
    await safe_edit(
        call,
        text,
        reply_markup=countries_kb(others, prefix="sat_scan_to", columns=2, back_data="sat:mil_menu"),
    )


@router.callback_query(SatelliteForm.choosing_target_country, F.data.startswith("sat_scan_to:"))
async def cb_sat_scan_exec(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """اجرای اسکن ماهواره‌ای و رندر گزارش نرف‌شده."""
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
        await safe_edit(call, f"⛔️ خطا: {err}", reply_markup=military_satellite_kb())
        return

    lines = [
        header(f"گزارش رصد ماهواره‌ای: {data['target_country']}", "🕵️"),
        f"💵 هزینه رصد: {fa_money(MIL_SAT_RECON_COST)} از بودجه کسر گردید.",
        "",
        "🏛 **پایگاه‌های نظامی شناسایی‌شده:**",
    ]

    if not data["bases"]:
        lines.append(" ◦ پایگاه فعالی کشف نشد.")
    else:
        for b in data["bases"]:
            lines.append(f"• **{b['name']}** (مالک: {b['owner']} | محل: {b['location']})")
            for eq in b["equipments"]:
                lines.append(f"   - {eq['name']}: {fa_number(eq['count'])} عدد")

    if data.get("masked_bases_count", 0) > 0:
        lines.append(f" ◦ ☁️ <i>پوشش ابری و پارازیت سیگنال — عدم دریافت تصویر واضح از {fa_number(data['masked_bases_count'])} پایگاه دیگر</i>")

    lines.append("")
    lines.append("🪖 **نیروهای نظامی مستقر در منطقه:**")
    if not data["deployments"]:
        lines.append(" ◦ نیروی مستقری شناسایی نشد.")
    else:
        for d in data["deployments"]:
            lines.append(f"• {d['branch']} ({d['asset_name']}: {fa_number(d['count'])}) -> منطقه {d['region']}")

    if data.get("masked_deps_count", 0) > 0:
        lines.append(f" ◦ ☁️ <i>پوشش ابری — عدم تشخیص دقیق {fa_number(data['masked_deps_count'])} یگان مستقر دیگر</i>")

    lines.append("")
    lines.append("⚔️ **تجهیزات و صنایع کشف‌شده (تصادفی و تخمینی):**")
    if not data.get("assets_summary"):
        lines.append(" ◦ به دلیل اختلال و پوشش ابری، اقلام نظامی دیده نشد.")
    else:
        for a in data["assets_summary"]:
            lines.append(f"• {a['name']} (~{fa_number(a['count'])} عدد)")

    if data.get("masked_assets_count", 0) > 0:
        lines.append(f" ◦ ☁️ <i>پوشش ابری و استتار — {fa_number(data['masked_assets_count'])} قلم تجهیزات دیگر قابل رؤیت نیستند.</i>")

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
            lines.append(f"\n⚠️ <i>علاوه بر موارد فوق، {fa_number(data['nuclear_hidden_count'])} محل مشکوک زیرزمینی نیز شناسایی شد که جزئیات آن از فضا پنهان است.</i>")

    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[:3900] + "\n..."

    await safe_edit(call, text, reply_markup=military_satellite_kb())


# ============================================================
#  💰 بخش ۲: ماهواره‌های اقتصادی و تجاری (سیستم پرداخت و ارتقا)
# ============================================================

@router.callback_query(F.data.in_(["sat:econ_menu", "econ:sat"]))
async def cb_sat_econ_menu(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """منوی اصلی ماهواره اقتصادی."""
    await call.answer()
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    if not await assert_feature(call, session, country, "econ.satellite"):
        return

    is_unlocked = getattr(country, "econ_sat_unlocked", False)
    if not is_unlocked:
        # صفحه تبلیغاتی فعالسازی ۵۰ هزار تومانی
        text = (
            header("ماهواره تجاری و اقتصادی", "💰") + "\n\n"
            "✨ **فرصت فوق‌العاده درآمدزایی فضایی!**\n\n"
            "با پرتاب ماهواره‌های تجاری و فروش داده‌های هواشناسی، مخابراتی، کشاورزی، "
            "شیلات و ناوبری جهانی، درآمد چشمگیری به بودجه کشورتان واریز کنید:\n\n"
            "📈 **سود خالص پایه:** ۱۰۰ میلیون دلار در هر ۷۲ ساعت\n"
            "⚡️ **قابلیت ارتقا تا سطح ۵:** افزایش سودآوری تا سقف ۷۰۰ میلیون دلار در هر ۷۲ ساعت!\n"
            "🌍 **دسترسی همگانی:** برای تمام کشورهای جهان (VIP و عادی).\n\n"
            "💎 **هزینه فعالسازی دائمی این آپشن:** ۵۰ هزار تومان\n\n"
            "آیا می‌خواهید با پرداخت کارت‌به‌کارت این آپشن را برای کشورتان فعال کنید؟"
        )
        await safe_edit(call, text, reply_markup=economic_satellite_kb(is_unlocked=False))
        return

    # آپشن فعال است؛ بررسی ماهواره فعال کشور
    active_sat = await sat_repo.get_active_economic_satellite(session, country.id)
    if not active_sat:
        text = (
            header("مرکز ماهواره اقتصادی", "🛰") + "\n\n"
            "✅ **آپشن ماهواره اقتصادی برای کشور شما فعال است.**\n\n"
            "شما هم‌اکنون می‌توانید اقدام به ساخت و پرتاب اولین ماهواره تجاری کشور خود نمایید:\n"
            f"💵 **هزینه ساخت اولیه (سطح ۱):** {fa_money(ECON_SAT_BUILD_COST_USD)}\n"
            f"🧱 **منابع ساخت:**\n"
            f" • فولاد: {fa_number(ECON_SAT_STEEL_COST)} تن\n"
            f" • آلومینیوم: {fa_number(ECON_SAT_ALUMINUM_COST)} تن\n"
            f" • نفت سوخت موشک: {ECON_SAT_OIL_COST} میلیون بشکه\n\n"
            f"💰 **سود تضمینی سطح ۱:** ۱۰۰ میلیون دلار هر ۷۲ ساعت"
        )
        await safe_edit(
            call,
            text,
            reply_markup=economic_satellite_kb(is_unlocked=True, has_active_sat=False),
        )
        return

    # ماهواره دارد
    lvl = getattr(active_sat, "level", 1) or 1
    cfg = ECON_SAT_LEVEL_CONFIG.get(lvl, {"yield_usd": 100_000_000.0})
    yield_usd = cfg["yield_usd"]

    if active_sat.status == "launching":
        text = (
            header(f"ماهواره اقتصادی: {active_sat.name}", "🚀") + "\n\n"
            "⏳ **وضعیت:** در حال پرواز و استقرار در مدار تجاری زمین\n"
            "⏱ این ماهواره تا دقایقی دیگر به مدار رسیده و فروش داده‌ها آغاز می‌شود.\n\n"
            f"📊 سطح پایه: {lvl} | سود چرخه اول: {fa_money(yield_usd)}"
        )
        await safe_edit(
            call,
            text,
            reply_markup=economic_satellite_kb(
                is_unlocked=True, has_active_sat=True, is_in_orbit=False, level=lvl
            ),
        )
        return

    # in_orbit
    text = (
        header(f"ماهواره تجاری: {active_sat.name}", "🛰") + "\n\n"
        "🟢 **وضعیت:** فعال و پایدار در مدار زمین\n"
        f"⭐ **سطح فناوری:** سطح {lvl} از ۵\n"
        f"💵 **سود خالص دریافتی:** {fa_money(yield_usd)} هر ۷۲ ساعت\n"
    )
    if lvl < 5:
        next_cost = ECON_SAT_LEVEL_CONFIG.get(lvl + 1, {}).get("upgrade_cost", 0.0)
        next_yield = ECON_SAT_LEVEL_CONFIG.get(lvl + 1, {}).get("yield_usd", 0.0)
        text += (
            f"\n⚡️ **ارتقا به سطح {lvl + 1}:**\n"
            f"هزینه ارتقا: {fa_money(next_cost)} ⬅️ سود جدید: {fa_money(next_yield)} هر ۷۲ ساعت"
        )
    else:
        text += "\n🏆 **حداکثر سطح فناوری:** ماهواره در بالاترین سطح ارتقا (سطح ۵) قرار دارد."

    await safe_edit(
        call,
        text,
        reply_markup=economic_satellite_kb(
            is_unlocked=True, has_active_sat=True, is_in_orbit=True, level=lvl
        ),
    )


# --- فلوی پرداخت کارت‌به‌کارت و ارسال رسید ---

@router.callback_query(F.data == "econsat:buy_prompt")
async def cb_econsat_buy_prompt(call: CallbackQuery) -> None:
    """پرسش تأیید پرداخت ۵۰ هزار تومانی."""
    await call.answer()
    text = (
        header("تأیید فعالسازی ماهواره اقتصادی", "💳") + "\n\n"
        "هزینه فعالسازی دائمی آپشن ماهواره اقتصادی **۵۰ هزار تومان** است.\n"
        "آیا می‌خواهید پرداخت کنید؟"
    )
    await safe_edit(call, text, reply_markup=econ_sat_buy_confirm_kb())


@router.callback_query(F.data == "econsat:buy_confirm")
async def cb_econsat_buy_confirm(call: CallbackQuery, state: FSMContext) -> None:
    """ارسال اطلاعات حساب بانکی و انتظار برای تصویر رسید."""
    await call.answer()
    await state.set_state(SatelliteForm.waiting_for_econ_sat_receipt)

    text = (
        "لطفاً به شماره کارت زیر مبلغ **۵۰ هزار تومان** واریز کنید و پس از پرداخت، "
        "**تصویر رسید** را همینجا ارسال کنید تا به پشتیبانی ارسال شود. "
        "به محض تأیید پشتیبانی، این آپشن برای شما فعال خواهد شد:\n\n"
        "💳 شماره کارت: `6219861843148577`\n"
        "👤 به نام: **رضائی**\n"
        "💵 مبلغ قابل پرداخت: **۵۰,۰۰۰ تومان**"
    )
    await safe_edit(call, text, reply_markup=econ_cancel_kb())


@router.message(SatelliteForm.waiting_for_econ_sat_receipt, F.photo)
async def msg_econ_receipt_photo(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """دریافت تصویر فیش واریزی و ارسال به گروه لاگ مدیران."""
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        return

    photo_file_id = message.photo[-1].file_id

    # ثبت در دیتابیس
    receipt = EconSatReceipt(
        country_id=country.id,
        user_id=message.from_user.id,
        photo_file_id=photo_file_id,
        status="pending",
    )
    receipt = await sat_repo.create_econ_receipt(session, receipt)
    await session.commit()

    # ارسال به گروه لاگ
    user_name = message.from_user.full_name
    username_str = f"@{message.from_user.username}" if message.from_user.username else "—"
    caption = (
        "💳 <b>درخواست فعالسازی ماهواره اقتصادی (رسید ۵۰ هزار تومانی)</b>\n\n"
        f"🏳️ کشور: {country.flag} {country.name_fa}\n"
        f"👤 کاربر: {user_name} ({username_str})\n"
        f"🆔 آیدی عددی: <code>{message.from_user.id}</code>\n"
        f"🔢 شناسه ثبت: #{receipt.id}\n"
        f"💵 مبلغ: ۵۰,۰۰۰ تومان"
    )

    await send_log_photo(
        bot,
        photo=photo_file_id,
        caption=caption,
        reply_markup=admin_receipt_review_kb(receipt.id),
    )

    await message.answer(
        "✅ رسید شما دریافت و برای پشتیبانی ارسال شد. به محض تایید، به شما اطلاع داده می‌شود.",
        reply_markup=satellite_hub_kb(),
    )


# --- بررسی رسید توسط ادمین در گروه لاگ ---

@router.callback_query(F.data.startswith("econsat_adm:approve:"))
async def cb_admin_approve_receipt(call: CallbackQuery, session: AsyncSession) -> None:
    """تأیید فیش واریزی توسط ادمین در گروه لاگ."""
    if not _is_admin_or_owner(call.from_user.id):
        await call.answer("تنها مدیران بازی می‌توانند رسیدها را بررسی کنند.", show_alert=True)
        return

    receipt_id = int(call.data.split(":")[2])
    receipt = await sat_repo.get_econ_receipt(session, receipt_id)
    if not receipt or receipt.status != "pending":
        await call.answer("این درخواست قبلاً بررسی شده است.", show_alert=True)
        return

    await sat_repo.update_econ_receipt_status(
        session, receipt_id, status="approved", admin_id=call.from_user.id
    )

    country = await countries_repo.get_country(session, receipt.country_id)
    if country:
        country.econ_sat_unlocked = True
        await session.commit()

        # پیام تبریک به کاربر
        try:
            await bot.send_message(
                receipt.user_id,
                "🎉 **پرداخت شما تایید شد!**\n\n"
                "آپشن ماهواره اقتصادی هم‌اکنون برای کشور شما فعال است و "
                "می‌توانید اقدام به ساخت و پرتاب آن کنید.",
            )
        except Exception:
            pass

    admin_name = call.from_user.full_name
    old_caption = call.message.caption or ""
    new_caption = f"{old_caption}\n\n✅ <b>تأیید شد</b> توسط {admin_name}"
    try:
        await call.message.edit_caption(caption=new_caption, reply_markup=None)
    except Exception:
        pass
    await call.answer("رسید تأیید و آپشن فعال شد ✅")


@router.callback_query(F.data.startswith("econsat_adm:reject:"))
async def cb_admin_reject_receipt(call: CallbackQuery, session: AsyncSession) -> None:
    """رد فیش واریزی توسط ادمین در گروه لاگ."""
    if not _is_admin_or_owner(call.from_user.id):
        await call.answer("تنها مدیران بازی می‌توانند رسیدها را بررسی کنند.", show_alert=True)
        return

    receipt_id = int(call.data.split(":")[2])
    receipt = await sat_repo.get_econ_receipt(session, receipt_id)
    if not receipt or receipt.status != "pending":
        await call.answer("این درخواست قبلاً بررسی شده است.", show_alert=True)
        return

    await sat_repo.update_econ_receipt_status(
        session, receipt_id, status="rejected", admin_id=call.from_user.id
    )
    await session.commit()

    # پیام به کاربر
    try:
        await bot.send_message(
            receipt.user_id,
            "❌ **اطلاعیه پشتیبانی:**\n\n"
            "متأسفانه رسید ارسالی شما برای فعالسازی ماهواره اقتصادی مورد تایید پشتیبانی قرار نگرفت. "
            "در صورت وجود هرگونه مغایرت لطفاً با پشتیبانی در ارتباط باشید.",
        )
    except Exception:
        pass

    admin_name = call.from_user.full_name
    old_caption = call.message.caption or ""
    new_caption = f"{old_caption}\n\n❌ <b>رد شد</b> توسط {admin_name}"
    try:
        await call.message.edit_caption(caption=new_caption, reply_markup=None)
    except Exception:
        pass
    await call.answer("رسید رد شد ❌")


# --- پرتاب و ارتقای ماهواره اقتصادی ---

@router.callback_query(F.data == "econsat:launch_start")
async def cb_econsat_launch_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """شروع پروسه ساخت و پرتاب ماهواره تجاری."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    if not country.econ_sat_unlocked:
        await safe_edit(
            call,
            "⛔️ ابتدا باید آپشن ماهواره اقتصادی را فعال نمایید.",
            reply_markup=economic_satellite_kb(is_unlocked=False),
        )
        return

    await state.set_state(SatelliteForm.entering_econ_satellite_name)
    text = (
        header("ساخت و پرتاب ماهواره تجاری", "🚀") + "\n\n"
        f"💰 **هزینه نقدی:** {fa_money(ECON_SAT_BUILD_COST_USD)}\n"
        f"🧱 **منابع لازم:**\n"
        f" • فولاد: {fa_number(ECON_SAT_STEEL_COST)} تن\n"
        f" • آلومینیوم: {fa_number(ECON_SAT_ALUMINUM_COST)} تن\n"
        f" • نفت موشک: {ECON_SAT_OIL_COST} میلیون بشکه\n\n"
        "✍️ لطفاً نام ماهواره تجاری جدید خود را وارد کنید (مثال: سپهر-۱):"
    )
    await safe_edit(call, text, reply_markup=econ_cancel_kb())


@router.message(SatelliteForm.entering_econ_satellite_name, F.text)
async def msg_econ_sat_name(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """ثبت و پرتاب ماهواره اقتصادی."""
    sat_name = message.text.strip()
    await state.clear()

    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        return

    await message.answer("⏳ **در حال ساخت ماهواره و آماده‌سازی پرتابگر مداری...**")

    try:
        sat, is_success = await satellite_service.launch_econ_satellite(
            session=session, country=country, satellite_name=sat_name
        )
    except satellite_service.SatelliteServiceError as err:
        await message.answer(f"⛔️ خطا: {err}", reply_markup=satellite_hub_kb())
        return

    if is_success:
        await message.answer(
            f"🚀 **پرتاب موفقیت‌آمیز بود!**\n\n"
            f"ماهواره تجاری «**{sat.name}**» به سوی مدار زمین پرتاب شد و تا ۳۰ دقیقه دیگر در مدار مستقر می‌گردد.\n"
            "پس از استقرار، چرخه سودآوری ۷۲ ساعته آغاز خواهد شد.",
            reply_markup=satellite_hub_kb(),
        )
    else:
        await message.answer(
            f"💥 **سانحه فضایی! پرتاب با شکست مواجه شد.**\n\n"
            f"موشک حامل ماهواره «**{sat.name}**» به دلیل نقص فنی متلاشی گردید.\n"
            "توجه: فعالسازی ۵۰ هزار تومانی شما محفوظ است و پس از کول‌داون ۲۴ ساعته می‌توانید مجدداً با منابع درون‌بازی اقدام به پرتاب نمایید.",
            reply_markup=satellite_hub_kb(),
        )


@router.callback_query(F.data == "econsat:upgrade_prompt")
async def cb_econsat_upgrade_prompt(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """پیش‌نمایش ارتقای ماهواره اقتصادی."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    sat = await sat_repo.get_active_economic_satellite(session, country.id)
    if not sat or sat.status != "in_orbit":
        await safe_edit(call, "⚠️ ماهواره اقتصادی فعالی در مدار یافت نشد.", reply_markup=satellite_hub_kb())
        return

    curr_lvl = getattr(sat, "level", 1) or 1
    if curr_lvl >= 5:
        await safe_edit(call, "ماهواره شما هم‌اکنون در حداکثر سطح است.", reply_markup=satellite_hub_kb())
        return

    next_lvl = curr_lvl + 1
    cfg = ECON_SAT_LEVEL_CONFIG.get(next_lvl, {})
    cost = cfg.get("upgrade_cost", 0.0)
    yield_usd = cfg.get("yield_usd", 0.0)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ تأیید و پرداخت ارتقا", callback_data="econsat:upgrade_do", style=STYLE_OK)
    kb.button(text="❌ انصراف", callback_data="sat:econ_menu", style=STYLE_NO)
    kb.adjust(1, 1)

    text = (
        header(f"ارتقای ماهواره به سطح {next_lvl}", "⚡️") + "\n\n"
        f"ماهواره فعلی: **{sat.name}** (سطح {curr_lvl})\n\n"
        f"💵 **هزینه ارتقا:** {fa_money(cost)}\n"
        f"💰 **سود جدید هر ۷۲ ساعت:** {fa_money(yield_usd)}\n\n"
        "آیا مایلید هزینه ارتقا از خزانه‌ی کشور کسر شود؟"
    )
    await safe_edit(call, text, reply_markup=kb.as_markup())


@router.callback_query(F.data == "econsat:upgrade_do")
async def cb_econsat_upgrade_do(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """اجرای ارتقای سطح ماهواره."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    try:
        sat, new_lvl, cost = await satellite_service.upgrade_econ_satellite(session, country)
    except satellite_service.SatelliteServiceError as err:
        await safe_edit(call, f"⛔️ خطا: {err}", reply_markup=satellite_hub_kb())
        return

    yield_usd = ECON_SAT_LEVEL_CONFIG.get(new_lvl, {}).get("yield_usd", 0.0)
    text = (
        header(f"ارتقا موفقیت‌آمیز بود! (سطح {new_lvl})", "🎉") + "\n\n"
        f"ماهواره **{sat.name}** با موفقیت به سطح {new_lvl} ارتقا یافت.\n"
        f"مبلغ {fa_money(cost)} از بودجه کسر گردید.\n"
        f"از چرخه‌ی بعدی، مبلغ **{fa_money(yield_usd)}** هر ۷۲ ساعت به خزانه واریز خواهد شد."
    )
    await safe_edit(
        call,
        text,
        reply_markup=economic_satellite_kb(
            is_unlocked=True, has_active_sat=True, is_in_orbit=True, level=new_lvl
        ),
    )


@router.callback_query(F.data == "econsat:history")
async def cb_econsat_history(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """تاریخچه ماهواره‌های اقتصادی کشور."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    sats = await sat_repo.list_satellites_by_country_and_type(session, country.id, "economic")
    if not sats:
        await safe_edit(
            call,
            "📋 شما تاکنون هیچ ماهواره تجاری پرتاب نکرده‌اید.",
            reply_markup=satellite_hub_kb(),
        )
        return

    lines = [header("تاریخچه ماهواره‌های اقتصادی", "🛰"), ""]
    status_map = {
        "launching": "🚀 در حال پرواز",
        "in_orbit": "🟢 فعال در مدار",
        "failed": "💥 سقوط در پرتاب",
        "expired": "⌛️ منقضی شده",
    }
    for s in sats:
        st = status_map.get(s.status, s.status)
        lines.append(f"• **{s.name}** (سطح {s.level} | {st})")

    await safe_edit(
        call,
        "\n".join(lines),
        reply_markup=economic_satellite_kb(is_unlocked=country.econ_sat_unlocked, has_active_sat=True),
    )


@router.callback_query(F.data == "econsat:status")
async def cb_econsat_status(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """وضعیت دقیق ماهواره تجاری فعال."""
    await cb_sat_econ_menu(call, state, session, db_user)
