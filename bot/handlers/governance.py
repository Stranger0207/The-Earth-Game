"""هندلر بخش حاکمیت: نظام حاکمیتی، اعتراضات، قانونگذاری (v1.10.2)."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import (
    GOVERNMENT_BONUSES,
    LEGISLATION_LIMIT_COUNT,
    LEGISLATION_LIMIT_HOURS,
    TAX_MAX_RATE,
    TAX_MIN_RATE,
)
from ..database.models import Country, Law, User
from ..database.repositories import countries as countries_repo
from ..database.repositories import diplomacy as dip_repo
from ..database.repositories import governance as gov_repo
from ..enums import (
    GOVERNMENT_EMOJI,
    GOVERNMENT_FA,
    GovernmentType,
    LAW_STATUS_FA,
    PROTEST_EMOJI,
    PROTEST_FA,
    PROTEST_STATUS_FA,
    LawStatus,
    ProtestStatus,
    ProtestType,
)
from ..keyboards.common import countries_kb
from ..keyboards.governance import (
    admin_law_panel_kb,
    admin_law_result_kb,
    governance_menu_kb,
    government_system_kb,
    government_type_kb,
    legislation_menu_kb,
    parliament_menu_kb,
    protest_action_kb,
    protest_menu_kb,
    tax_law_kb,
    visa_all_confirm_kb,
    visa_law_dashboard_kb,
    visa_law_kb,
    visa_rm_all_confirm_kb,
    visa_rm_menu_kb,
    visa_status_menu_kb,
)
from ..loader import bot
from ..services.governance_service import (
    GovernanceError,
    change_government,
    compute_tax_revenue,
    set_tax_rate,
    suppress_protest,
    refer_to_parliament,
    tax_satisfaction_delta,
)
from ..enums import AdminGroupType
from ..services.news_service import send_log, send_to_admin_group
from ..states import AdminLawResultForm, GovernanceForm, LawForm
from ..utils.numbers import _FA_TO_EN, fa_money, fa_number, parse_amount
from ..utils.screens import safe_edit, show_menu
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK, header
from .deps import NO_COUNTRY_TEXT, assert_feature, get_player_country

router = Router(name="governance")
settings = get_settings()


# ============================================================
#  منوی اصلی حاکمیت
# ============================================================

@router.callback_query(F.data == "menu:governance")
async def cb_governance_menu(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.answer()
    await show_menu(
        call, header("بخش حاکمیت", "🏛"), governance_menu_kb(), image_key="governance"
    )


# ============================================================
#  نظام حاکمیتی
# ============================================================

@router.callback_query(F.data == "gov:system")
async def cb_system_menu(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "gov.system"):
        return

    has_govt = bool(country.government_type)
    changes_left = country.govt_changes_left

    lines = [header("نظام حاکمیتی", "🏛")]
    if has_govt:
        try:
            gt = GovernmentType(country.government_type)
            emoji = GOVERNMENT_EMOJI.get(gt, "")
            fa = GOVERNMENT_FA.get(gt, country.government_type)
            lines.append(f"\n{emoji} نظام فعلی: <b>{fa}</b>")
        except ValueError:
            lines.append(f"\nنظام فعلی: {country.government_type}")
    else:
        lines.append("\n⚠️ هنوز نظامی انتخاب نشده است.")

    lines.append(f"\n🔄 تغییرات باقی‌مانده: <b>{fa_number(changes_left)}</b> از ۲")

    await show_menu(
        call, "\n".join(lines),
        reply_markup=government_system_kb(has_govt, changes_left),
        image_key="governance",
    )


@router.callback_query(F.data == "gov:current")
async def cb_current_system(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """نمایش جزئیات نظام فعلی و بونوس‌ها."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    if not country.government_type:
        await safe_edit(call, "⚠️ هنوز نظامی انتخاب نشده.", reply_markup=governance_menu_kb())
        return

    try:
        gt = GovernmentType(country.government_type)
    except ValueError:
        await safe_edit(call, "⚠️ نظام نامعتبر.", reply_markup=governance_menu_kb())
        return

    emoji = GOVERNMENT_EMOJI.get(gt, "")
    fa = GOVERNMENT_FA.get(gt, gt.value)
    bonuses = GOVERNMENT_BONUSES.get(gt, {})

    # فرمت بونوس‌ها
    bonus_labels = {
        "satisfaction": "رضایت عمومی",
        "stability": "ثبات داخلی",
        "unemployment": "بیکاری",
        "inflation": "تورم",
        "economic_power": "قدرت اقتصادی",
    }
    bonus_lines = []
    for k, v in bonuses.items():
        lbl = bonus_labels.get(k, k)
        sign = "+" if v > 0 else ""
        bonus_lines.append(f"  • {lbl}: {sign}{fa_number(v, 1)}")

    lines = [
        header("نظام حاکمیتی من", emoji),
        f"\n{emoji} <b>{fa}</b>",
        "",
        "📊 <b>اثرات نظام:</b>",
        *bonus_lines,
        f"\n🔄 تغییرات باقی‌مانده: {fa_number(country.govt_changes_left)}",
    ]
    await safe_edit(
        call, "\n".join(lines),
        reply_markup=government_system_kb(True, country.govt_changes_left),
    )


@router.callback_query(F.data == "gov:change_system")
async def cb_change_system(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """نمایش لیست نظام‌ها برای انتخاب."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if country.govt_changes_left <= 0:
        await safe_edit(
            call, "⚠️ شما هر دو بار حق تغییر نظام را استفاده کرده‌اید.",
            reply_markup=governance_menu_kb(),
        )
        return

    lines = [
        header("انتخاب نظام حاکمیتی", "🏛"),
        "\nنظام مورد نظر خود را انتخاب کنید:",
    ]
    # نمایش خلاصه‌ی بونوس‌ها
    for gt in GovernmentType:
        emoji = GOVERNMENT_EMOJI.get(gt, "")
        fa = GOVERNMENT_FA.get(gt, gt.value)
        bonuses = GOVERNMENT_BONUSES.get(gt, {})
        effects = []
        for k, v in bonuses.items():
            sign = "+" if v > 0 else ""
            short = {"satisfaction": "رضایت", "stability": "ثبات", "unemployment": "بیکاری",
                     "inflation": "تورم", "economic_power": "اقتصاد"}
            effects.append(f"{sign}{v:.0f} {short.get(k, k)}")
        lines.append(f"\n{emoji} <b>{fa}</b>: {' | '.join(effects)}")

    await safe_edit(call, "\n".join(lines), reply_markup=government_type_kb())


@router.callback_query(F.data.startswith("gov_type:"))
async def cb_select_government(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """انتخاب/تغییر نظام حاکمیتی."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    type_val = call.data.split(":", 1)[1]
    try:
        gt = GovernmentType(type_val)
    except ValueError:
        await safe_edit(call, "⚠️ نظام نامعتبر.", reply_markup=governance_menu_kb())
        return

    try:
        bonuses = await change_government(session, country, gt)
        await session.commit()
    except GovernanceError as e:
        await safe_edit(call, f"⚠️ {e}", reply_markup=governance_menu_kb())
        return

    emoji = GOVERNMENT_EMOJI.get(gt, "")
    fa = GOVERNMENT_FA.get(gt, gt.value)

    # فرمت بونوس‌ها
    bonus_labels = {
        "satisfaction": "رضایت عمومی", "stability": "ثبات داخلی",
        "unemployment": "بیکاری", "inflation": "تورم", "economic_power": "قدرت اقتصادی",
    }
    bonus_lines = []
    for k, v in bonuses.items():
        sign = "+" if v > 0 else ""
        bonus_lines.append(f"  • {bonus_labels.get(k, k)}: {sign}{fa_number(v, 1)}")

    lines = [
        f"✅ نظام حاکمیتی شما به <b>{emoji} {fa}</b> تغییر یافت!",
        "",
        "📊 اثرات اعمال‌شده:",
        *bonus_lines,
        f"\n🔄 تغییرات باقی‌مانده: {fa_number(country.govt_changes_left)}",
    ]
    await safe_edit(call, "\n".join(lines), reply_markup=governance_menu_kb())

    # لاگ تغییر نظام به گروه تحریم و لایحه (گروه ۱)
    await send_to_admin_group(
        bot,
        AdminGroupType.SANCTION_BILL,
        f"🏛 <b>تغییر نظام</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"نظام جدید: {emoji} {fa}\n"
        f"تغییرات باقی‌مانده: {country.govt_changes_left}",
    )


# ============================================================
#  اعتراضات
# ============================================================

@router.callback_query(F.data == "gov:protests")
async def cb_protest_menu(call: CallbackQuery) -> None:
    await call.answer()
    await show_menu(call, header("اعتراضات و رفراندوم", "✊"), reply_markup=protest_menu_kb(), image_key="governance")


@router.callback_query(F.data == "gov:active_protests")
async def cb_active_protests(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """نمایش اعتراضات فعال."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    protests = await gov_repo.get_active_protests(session, country.id)
    if not protests:
        await safe_edit(
            call, f"{header('اعتراضات فعال', '✊')}\n\n✅ هیچ اعتراض فعالی وجود ندارد.",
            reply_markup=protest_menu_kb(),
        )
        return

    lines = [header("اعتراضات فعال", "✊"), ""]
    for p in protests:
        try:
            pt = ProtestType(p.protest_type)
            emoji = PROTEST_EMOJI.get(pt, "❗")
            fa = PROTEST_FA.get(pt, p.protest_type)
        except ValueError:
            emoji, fa = "❗", p.protest_type

        lines.append(f"{emoji} <b>{p.title}</b>")
        lines.append(f"  نوع: {fa} | شدت: {fa_number(p.severity, 1)}/۱۰")
        if p.description:
            lines.append(f"  {p.description}")
        lines.append("")

    # اگر فقط یک اعتراض فعال هست، دکمه‌های عمل نمایش بده
    if len(protests) == 1:
        await safe_edit(
            call, "\n".join(lines),
            reply_markup=protest_action_kb(protests[0].id),
        )
    else:
        # چند اعتراض: لیست + دکمه‌ی هر کدام
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        for p in protests:
            builder.button(
                text=f"⚡ {p.title[:30]}",
                callback_data=f"gov:protest_detail:{p.id}",
                style=STYLE_NO,
            )
        builder.button(text="🔙 بازگشت", callback_data="gov:protests", style=STYLE_MAIN)
        builder.adjust(1)
        await safe_edit(call, "\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("gov:protest_detail:"))
async def cb_protest_detail(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """جزئیات یک اعتراض + دکمه‌های عمل."""
    await call.answer()
    pid = int(call.data.split(":")[-1])
    p = await gov_repo.get_protest_by_id(session, pid)
    if p is None:
        await safe_edit(call, "⚠️ اعتراض یافت نشد.", reply_markup=protest_menu_kb())
        return

    try:
        pt = ProtestType(p.protest_type)
        emoji = PROTEST_EMOJI.get(pt, "❗")
        fa = PROTEST_FA.get(pt, p.protest_type)
    except ValueError:
        emoji, fa = "❗", p.protest_type

    status_fa = PROTEST_STATUS_FA.get(ProtestStatus(p.status), p.status) if p.status else "نامشخص"

    lines = [
        header(p.title, emoji),
        f"\nنوع: {fa}",
        f"شدت: {fa_number(p.severity, 1)}/۱۰",
        f"وضعیت: {status_fa}",
    ]
    if p.description:
        lines.append(f"\n📝 {p.description}")

    kb = protest_action_kb(pid) if p.status == "active" else protest_menu_kb()
    await safe_edit(call, "\n".join(lines), reply_markup=kb)


@router.callback_query(F.data.startswith("gov:suppress:"))
async def cb_suppress(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """سرکوب اعتراض."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    pid = int(call.data.split(":")[-1])
    try:
        await suppress_protest(session, country, pid)
        await session.commit()
    except GovernanceError as e:
        await safe_edit(call, f"⚠️ {e}", reply_markup=protest_menu_kb())
        return

    lines = [
        "👊 <b>اعتراض سرکوب شد</b>",
        "",
        f"📈 ثبات: {fa_number(country.stability, 1)}",
        f"📉 رضایت عمومی: {fa_number(country.public_satisfaction, 1)}",
        "",
        "⚠️ سرکوب اعتراضات ثبات را بالا می‌برد ولی رضایت مردم را کاهش می‌دهد.",
    ]
    await safe_edit(call, "\n".join(lines), reply_markup=protest_menu_kb())

    await send_log(
        bot,
        f"👊 <b>سرکوب اعتراض</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"ثبات: {country.stability:.1f} | رضایت: {country.public_satisfaction:.1f}",
    )


@router.callback_query(F.data.startswith("gov:parliament_ref:"))
async def cb_parliament_ref(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """ارجاع اعتراض به مجلس."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    pid = int(call.data.split(":")[-1])
    try:
        await refer_to_parliament(session, country, pid)
        await session.commit()
    except GovernanceError as e:
        await safe_edit(call, f"⚠️ {e}", reply_markup=protest_menu_kb())
        return

    lines = [
        "🏛 <b>اعتراض به مجلس ارجاع شد</b>",
        "",
        f"📈 ثبات: {fa_number(country.stability, 1)}",
        f"📈 رضایت عمومی: {fa_number(country.public_satisfaction, 1)}",
        "",
        "ادمین‌ها می‌توانند درباره‌ی اجازه‌ی رفراندوم تصمیم بگیرند.",
    ]
    await safe_edit(call, "\n".join(lines), reply_markup=protest_menu_kb())

    # ارسال به لاگ برای ادمین‌ها
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ تأیید رفراندوم", callback_data=f"gov_admin:ref_ok:{pid}", style=STYLE_OK)
    builder.button(text="❌ رد", callback_data=f"gov_admin:ref_no:{pid}", style=STYLE_NO)
    builder.adjust(2)

    await send_to_admin_group(
        bot,
        AdminGroupType.SANCTION_BILL,
        f"🏛 <b>ارجاع به مجلس</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"اعتراض #{pid}\n\n"
        f"ادمین: آیا اجازه‌ی رفراندوم داده می‌شود؟",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("gov_admin:ref_ok:"))
async def cb_admin_ref_ok(call: CallbackQuery, session: AsyncSession) -> None:
    """ادمین رفراندوم را تأیید می‌کند."""
    await call.answer("رفراندوم تأیید شد ✅")
    pid = int(call.data.split(":")[-1])
    await gov_repo.update_protest_status(session, pid, "referendum", "مجلس اجازه‌ی رفراندوم داد")
    await session.commit()
    await call.message.edit_text(
        call.message.text + "\n\n✅ <b>رفراندوم تأیید شد</b>",
    )


@router.callback_query(F.data.startswith("gov_admin:ref_no:"))
async def cb_admin_ref_no(call: CallbackQuery, session: AsyncSession) -> None:
    """ادمین رفراندوم را رد می‌کند."""
    await call.answer("رفراندوم رد شد ❌")
    pid = int(call.data.split(":")[-1])
    await gov_repo.update_protest_status(session, pid, "resolved", "مجلس رفراندوم را رد کرد")
    await session.commit()
    await call.message.edit_text(
        call.message.text + "\n\n❌ <b>رفراندوم رد شد</b>",
    )


@router.callback_query(F.data == "gov:protest_history")
async def cb_protest_history(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """تاریخچه‌ی همه‌ی اعتراضات."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    all_protests = await gov_repo.get_all_protests(session, country.id)
    if not all_protests:
        await safe_edit(
            call, f"{header('تاریخچه اعتراضات', '📋')}\n\nهیچ اعتراضی ثبت نشده.",
            reply_markup=protest_menu_kb(),
        )
        return

    lines = [header("تاریخچه اعتراضات", "📋"), ""]
    for p in all_protests[:15]:  # حداکثر ۱۵ تا
        try:
            status_fa = PROTEST_STATUS_FA.get(ProtestStatus(p.status), p.status)
        except ValueError:
            status_fa = p.status
        lines.append(f"• {p.title} — {status_fa}")

    await safe_edit(call, "\n".join(lines), reply_markup=protest_menu_kb())


# ============================================================
#  قانونگذاری
# ============================================================

@router.callback_query(F.data == "gov:legislation")
async def cb_legislation(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "gov.legislation"):
        return
    await show_menu(call, header("قانونگذاری", "📜"), reply_markup=legislation_menu_kb(), image_key="governance")


# ---------- مالیات ----------

@router.callback_query(F.data == "gov:tax_law")
async def cb_tax_law(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    await call.answer()
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    revenue = compute_tax_revenue(country)
    sat_delta = tax_satisfaction_delta(country.tax_rate)
    sat_sign = "+" if sat_delta >= 0 else ""

    lines = [
        header("قانون مالیات", "💰"),
        f"\n📊 نرخ فعلی: <b>{fa_number(country.tax_rate, 1)}٪</b>",
        f"💵 درآمد مالیاتی (هر ۲۴ ساعت): {fa_money(revenue)}",
        f"😊 تأثیر بر رضایت: {sat_sign}{fa_number(sat_delta, 1)} در هر ۲۴ ساعت",
        f"\n👥 جمعیت: {fa_number(country.population)}",
        f"\n⚠️ مالیات بالا درآمد بیشتری دارد ولی رضایت مردم را کم می‌کند.",
        f"حداقل: {fa_number(TAX_MIN_RATE)}٪ | حداکثر: {fa_number(TAX_MAX_RATE)}٪",
    ]
    await safe_edit(call, "\n".join(lines), reply_markup=tax_law_kb(country.tax_rate))


@router.callback_query(F.data == "gov:tax_info")
async def cb_tax_info(call: CallbackQuery) -> None:
    await call.answer("نرخ مالیات فعلی شما")


@router.callback_query(F.data == "gov:set_tax")
async def cb_set_tax(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """شروع فرم تعیین نرخ مالیات."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "gov.tax"):
        return
    await state.set_state(GovernanceForm.entering_tax_rate)
    await safe_edit(
        call,
        f"{header('تعیین نرخ مالیات', '✏️')}\n\n"
        f"نرخ مالیات مورد نظر را به‌صورت عدد (درصد) وارد کنید.\n"
        f"مثال: <code>15</code>\n\n"
        f"حداقل: {fa_number(TAX_MIN_RATE)}٪ | حداکثر: {fa_number(TAX_MAX_RATE)}٪",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 انصراف و بازگشت", callback_data="gov:tax_law", style=STYLE_NO)],
            ]
        ),
    )


@router.message(StateFilter(GovernanceForm.entering_tax_rate))
async def msg_set_tax(
    msg: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """دریافت نرخ مالیات و اعمال."""
    country = await get_player_country(session, db_user)
    if country is None:
        await msg.answer(NO_COUNTRY_TEXT)
        await state.clear()
        return

    try:
        norm = (msg.text or "").replace("٪", "").replace("%", "").strip()
        parsed = parse_amount(norm)
        if parsed is None:
            raise ValueError
        rate = float(parsed)
    except (ValueError, AttributeError):
        await msg.answer("⚠️ لطفاً یک عدد معتبر وارد کنید:")
        return

    if rate < TAX_MIN_RATE or rate > TAX_MAX_RATE:
        await msg.answer(
            f"⚠️ نرخ باید بین {fa_number(TAX_MIN_RATE)}٪ و {fa_number(TAX_MAX_RATE)}٪ باشد."
        )
        return

    old_rate = country.tax_rate
    new_rate = await set_tax_rate(session, country, rate)
    await session.commit()
    await state.clear()

    revenue = compute_tax_revenue(country)
    sat_delta = tax_satisfaction_delta(new_rate)
    sat_sign = "+" if sat_delta >= 0 else ""

    await msg.answer(
        f"✅ نرخ مالیات از <b>{fa_number(old_rate, 1)}٪</b> به <b>{fa_number(new_rate, 1)}٪</b> تغییر یافت.\n\n"
        f"💵 درآمد جدید (هر ۲۴ ساعت): {fa_money(revenue)}\n"
        f"😊 تأثیر بر رضایت: {sat_sign}{fa_number(sat_delta, 1)}",
        reply_markup=governance_menu_kb(),
    )

    await send_to_admin_group(
        bot,
        AdminGroupType.SANCTION_BILL,
        f"💰 <b>تغییر مالیات</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"نرخ: {old_rate:.1f}٪ → {new_rate:.1f}٪",
    )


# ============================================================
#  🛂 سامانه جامع روادید (ویزا) و کنترل مرزها
# ============================================================

REGION_LABELS: dict[str, str] = {
    "middle_east": "خاورمیانه 🏜",
    "europe": "اروپا 🏰",
    "east_asia": "شرق آسیا 🏯",
    "asia": "آسیا 🌏",
    "americas": "قاره آمریکا 🌎",
    "america": "قاره آمریکا 🌎",
    "north_america": "آمریکای شمالی 🗽",
    "south_america": "آمریکای جنوبی 🌴",
    "africa": "آفریقا 🌍",
    "oceania": "اقیانوسیه 🏝",
}


async def _build_visa_dashboard_data(session: AsyncSession, country: Country) -> dict:
    """محاسبه کامل آمار و وضعیت‌های مرزی برای سامانه ویزا."""
    all_countries = await countries_repo.list_countries(session)
    other_countries = [c for c in all_countries if c.id != country.id]

    visas = await gov_repo.get_visa_list(session, country.id)
    req_target_ids = {v.target_country_id for v in visas}

    granted_waivers = await dip_repo.list_granted_visa_waivers(session, country.id)
    granted_target_ids = {w.target_country_id for w in granted_waivers}

    received_waivers = await dip_repo.list_received_visa_waivers(session, country.id)

    normal_count = max(0, len(other_countries) - len(req_target_ids | granted_target_ids))

    return {
        "all_others": other_countries,
        "req_target_ids": req_target_ids,
        "req_count": len(req_target_ids),
        "granted_waivers": granted_waivers,
        "granted_target_ids": granted_target_ids,
        "granted_count": len(granted_target_ids),
        "received_waivers": received_waivers,
        "rec_count": len(received_waivers),
        "normal_count": normal_count,
        "total_others": len(other_countries),
    }


def _format_visa_dashboard_text(country: Country, data: dict) -> str:
    """متن داشبورد اصلی سامانه ویزا."""
    lines = [
        "╔══════════════════════════════╗",
        "  🛂 <b>سامانه جامع روادید (ویزا) و مدیریت مرزها</b>",
        f"  🏳️ <b>کشور:</b> {country.flag} {country.name_fa}",
        "╚══════════════════════════════╝",
        "",
        "📊 <b>وضعیت کنونی سیاست‌های مرزی کشور:</b>",
        f"• ⛔️ <b>ویزای اجباری وضع‌شده:</b> {fa_number(data['req_count'])} کشور",
        f"• 🤝 <b>توافق لغو روادید اعطایی (مرز باز):</b> {fa_number(data['granted_count'])} کشور (۵۰٪ تخفیف عوارض ترانزیت)",
        f"• 📥 <b>لغو روادید دریافتی از سایرین:</b> {fa_number(data['rec_count'])} کشور",
        f"• ⚪️ <b>روابط مرزی عادی:</b> {fa_number(data['normal_count'])} کشور",
        "",
        "💡 <b>راهنمای قوانین روادید (ویزا):</b>",
        "• <b>لغو ویزا (Visa Waiver):</b> معافیت از روادید ورود و ۵۰٪ تخفیف عوارض ارسال محموله است که در <b>دیدار حضوری فعال</b> منعقد می‌شود.",
        "• <b>وضع ویزای اجباری:</b> اعمال محدودیت تردد اتباع خارجی بر مرزهای کشور، که به صورت تکی، منطقه‌ای یا سراسری برای تمامی کشورهای جهان قابل اجراست.",
    ]
    return "\n".join(lines)


@router.callback_query(F.data == "gov:visa_law")
async def cb_visa_law(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """داشبورد اصلی سامانه جامع ویزا و مرزها."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    data = await _build_visa_dashboard_data(session, country)
    text = _format_visa_dashboard_text(country, data)
    await show_menu(call, text, reply_markup=visa_law_dashboard_kb(), image_key="governance")


@router.callback_query(F.data == "gov:visa_status")
@router.callback_query(F.data == "gov:visa_list")
async def cb_visa_status(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """منوی تفکیک و انتخاب دسته‌بندی استعلام ویزاها."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    data = await _build_visa_dashboard_data(session, country)
    text = (
        "╔══════════════════════════════╗\n"
        "  📋 <b>استعلام وضعیت مرزها (کیا دارن / کیا ندارن)</b>\n"
        f"  🏳️ <b>کشور:</b> {country.flag} {country.name_fa}\n"
        "╚══════════════════════════════╝\n\n"
        "لطفاً دسته‌بندی مورد نظر خود را جهت مشاهده لیست تفکیک‌شده کشورها انتخاب کنید:"
    )
    kb = visa_status_menu_kb(
        req_count=data["req_count"],
        granted_count=data["granted_count"],
        rec_count=data["rec_count"],
        normal_count=data["normal_count"],
    )
    await safe_edit(call, text, reply_markup=kb)


@router.callback_query(F.data.startswith("gov_vview:"))
async def cb_visa_view(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """مشاهده لیست کشورها در هر یک از ۴ وضعیت مرزی به صورت صفحه‌بندی‌شده."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    parts = call.data.split(":")
    view_type = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 0

    all_countries = await countries_repo.list_countries(session)
    c_map = {c.id: c for c in all_countries}
    other_countries = [c for c in all_countries if c.id != country.id]

    visas = await gov_repo.get_visa_list(session, country.id)
    req_target_ids = {v.target_country_id for v in visas}

    granted_waivers = await dip_repo.list_granted_visa_waivers(session, country.id)
    granted_target_ids = {w.target_country_id for w in granted_waivers}

    received_waivers = await dip_repo.list_received_visa_waivers(session, country.id)
    received_source_ids = {w.country_id for w in received_waivers}

    if view_type == "req":
        title = "⛔️ <b>فهرست کشورهای نیازمند ویزای ورود</b>"
        sub_desc = "<i>ورود اتباع این کشورها به خاک شما نیازمند اخذ روادید اجباری است.</i>"
        matched_countries = [c_map[tid] for tid in req_target_ids if tid in c_map]
    elif view_type == "waiver":
        title = "🤝 <b>فهرست کشورهای دارای لغو روادید اعطایی</b>"
        sub_desc = "<i>با این کشورها توافق لغو ویزا دارید (مرز باز + ۵۰٪ تخفیف عوارض ترانزیت کالا).</i>"
        matched_countries = [c_map[tid] for tid in granted_target_ids if tid in c_map]
    elif view_type == "rec":
        title = "📥 <b>فهرست کشورهایی که ویزای شما را لغو کرده‌اند</b>"
        sub_desc = "<i>این کشورها برای ورود اتباع شما روادید را لغو کرده و ارسال کالا به آنها با ۵۰٪ تخفیف عوارض است.</i>"
        matched_countries = [c_map[sid] for sid in received_source_ids if sid in c_map]
    else:  # none
        title = "⚪️ <b>فهرست کشورهای دارای روابط مرزی عادی</b>"
        sub_desc = "<i>برای اتباع این کشورها ویزای اجباری وضع نشده و روابط مرزی به صورت استاندارد است.</i>"
        matched_countries = [c for c in other_countries if c.id not in req_target_ids and c.id not in granted_target_ids]

    PAGE_SIZE = 10
    total_items = len(matched_countries)
    total_pages = max(1, (total_items + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    slice_items = matched_countries[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    lines = [
        title,
        f"📊 مجموع: {fa_number(total_items)} کشور | صفحه {fa_number(page + 1)} از {fa_number(total_pages)}",
        "",
        sub_desc,
        "",
    ]

    if not slice_items:
        lines.append("<i>موردی در این دسته ثبت نشده است.</i>")
    else:
        for idx, c in enumerate(slice_items, start=page * PAGE_SIZE + 1):
            lines.append(f"{fa_number(idx)}. {c.flag} {c.name_fa} ({c.name_en})")

    builder = InlineKeyboardBuilder()
    nav_btns = []
    if page > 0:
        nav_btns.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=f"gov_vview:{view_type}:{page - 1}"))
    nav_btns.append(InlineKeyboardButton(text=f"📄 {fa_number(page + 1)}/{fa_number(total_pages)}", callback_data="noop"))
    if page < total_pages - 1:
        nav_btns.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=f"gov_vview:{view_type}:{page + 1}"))
    if len(nav_btns) > 1:
        builder.row(*nav_btns)

    builder.row(InlineKeyboardButton(text="🔙 بازگشت به دسته‌بندی‌ها", callback_data="gov:visa_status", style=STYLE_MAIN))
    await safe_edit(call, "\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data == "gov:visa_all_ask")
async def cb_visa_all_ask(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """درخواست تایید برای وضع ویزا روی تمامی کشورها."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    all_countries = await countries_repo.list_countries(session)
    others_count = len([c for c in all_countries if c.id != country.id])

    text = (
        "⚠️ <b>هشدار وضع ویزای اجباری سراسری (بستن مرزها)</b>\n\n"
        f"آیا اطمینان دارید که می‌خواهید برای <b>تمامی کشورهای جهان</b> ({fa_number(others_count)} کشور) ویزای اجباری ورود وضع کنید؟\n\n"
        "📌 <b>پیامدهای این تصمیم:</b>\n"
        "• ورود اتباع تمامی کشورهای خارجی به خاک کشور شما مشروط به اخذ روادید خواهد شد.\n"
        "• کنترل‌های مرزی و امنیتی به حداکثر سطح خواهد رسید."
    )
    await safe_edit(call, text, reply_markup=visa_all_confirm_kb())


@router.callback_query(F.data == "gov:visa_all_confirm")
async def cb_visa_all_confirm(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """اجرای وضع ویزا بر تمامی کشورهای جهان."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    all_countries = await countries_repo.list_countries(session)
    other_ids = [c.id for c in all_countries if c.id != country.id]

    added = await gov_repo.add_visas_bulk(session, country.id, other_ids)
    await session.commit()

    text = (
        "✅ <b>ویزای اجباری ورود برای تمامی کشورهای جهان با موفقیت وضع گردید!</b>\n\n"
        f"• تعداد کل کشورهای مشمول ویزا: {fa_number(len(other_ids))} کشور\n"
        f"• ویزاهای جدیداً وضع‌شده: {fa_number(added)} مورد\n\n"
        "از این پس هیچ تبعه‌ی خارجی بدون اخذ روادید رسمی اجازه ورود به خاک کشور شما را نخواهد داشت."
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 بازگشت به سامانه ویزا", callback_data="gov:visa_law", style=STYLE_MAIN)

    await safe_edit(call, text, reply_markup=builder.as_markup())

    await send_to_admin_group(
        bot,
        AdminGroupType.SANCTION_BILL,
        f"🛂 <b>وضع ویزای سراسری (بستن کامل مرزها)</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"شامل: تمامی {fa_number(len(other_ids))} کشور جهان\n"
        f"موارد جدید: {fa_number(added)}",
    )


@router.callback_query(F.data == "gov:visa_bulk_menu")
@router.callback_query(F.data == "gov:visa_add")
async def cb_visa_bulk_menu(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """منوی وضع ویزا بر اساس منطقه یا انتخاب تکی/چندتایی."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    all_countries = await countries_repo.list_countries(session)
    visas = await gov_repo.get_visa_list(session, country.id)
    req_target_ids = {v.target_country_id for v in visas}
    req_target_ids.add(country.id)

    regions_map: dict[str, list[Country]] = {}
    for c in all_countries:
        if c.id not in req_target_ids:
            reg = getattr(c, "region", "other") or "other"
            regions_map.setdefault(reg, []).append(c)

    text = (
        "╔══════════════════════════════╗\n"
        "  🌐 <b>وضع ویزا بر چند کشور یا یک قاره</b>\n"
        "╚══════════════════════════════╝\n\n"
        "شما می‌توانید برای کشورهای یک قاره/منطقه به صورت یکجا، یا به صورت تکی/چندتایی ویزای ورود وضع نمایید:\n\n"
        "<b>🌍 مناطق دارای کشورهای بدون ویزا:</b>"
    )

    builder = InlineKeyboardBuilder()
    for reg, c_list in sorted(regions_map.items()):
        reg_title = REGION_LABELS.get(reg, reg.replace("_", " ").title())
        builder.button(
            text=f"{reg_title} ({fa_number(len(c_list))} کشور)",
            callback_data=f"gov_vreg:{reg}",
            style=STYLE_NO,
        )

    builder.button(
        text="📌 انتخاب تکی / چندتایی کشورها",
        callback_data="gov_vpick:0",
        style=STYLE_MAIN,
    )
    builder.button(
        text="🔙 بازگشت به سامانه ویزا",
        callback_data="gov:visa_law",
        style=STYLE_MAIN,
    )
    builder.adjust(1)
    await safe_edit(call, text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("gov_vreg:"))
async def cb_visa_region_ask(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """تایید وضع ویزا روی کشورهای یک منطقه."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    reg_key = call.data.split(":")[1]
    all_countries = await countries_repo.list_countries(session)
    visas = await gov_repo.get_visa_list(session, country.id)
    req_target_ids = {v.target_country_id for v in visas}
    req_target_ids.add(country.id)

    targets = [c for c in all_countries if getattr(c, "region", "") == reg_key and c.id not in req_target_ids]
    reg_title = REGION_LABELS.get(reg_key, reg_key.replace("_", " ").title())

    if not targets:
        await safe_edit(
            call,
            f"⚠️ تمامی کشورهای منطقه {reg_title} از قبل دارای ویزای اجباری هستند.",
            reply_markup=InlineKeyboardBuilder().button(text="🔙 بازگشت", callback_data="gov:visa_bulk_menu", style=STYLE_MAIN).as_markup(),
        )
        return

    preview = "، ".join(f"{c.flag} {c.name_fa}" for c in targets[:8])
    if len(targets) > 8:
        preview += f" و {fa_number(len(targets) - 8)} کشور دیگر"

    text = (
        f"⚠️ <b>وضع ویزای اجباری برای منطقه {reg_title}</b>\n\n"
        f"آیا اطمینان دارید که می‌خواهید برای <b>تمامی {fa_number(len(targets))} کشور</b> این منطقه ویزای اجباری وضع کنید؟\n\n"
        f"📋 <b>کشورها:</b> {preview}"
    )

    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"⛔️ بله، وضع ویزا برای منطقه {reg_title}",
        callback_data=f"gov_vreg_do:{reg_key}",
        style=STYLE_NO,
    )
    builder.button(
        text="🔙 انصراف و بازگشت",
        callback_data="gov:visa_bulk_menu",
        style=STYLE_MAIN,
    )
    builder.adjust(1)
    await safe_edit(call, text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("gov_vreg_do:"))
async def cb_visa_region_do(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """اعمال وضع ویزا برای کشورهای یک منطقه."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    reg_key = call.data.split(":")[1]
    all_countries = await countries_repo.list_countries(session)
    visas = await gov_repo.get_visa_list(session, country.id)
    req_target_ids = {v.target_country_id for v in visas}
    req_target_ids.add(country.id)

    targets = [c for c in all_countries if getattr(c, "region", "") == reg_key and c.id not in req_target_ids]
    reg_title = REGION_LABELS.get(reg_key, reg_key.replace("_", " ").title())

    added = await gov_repo.add_visas_bulk(session, country.id, [c.id for c in targets])
    for c in targets:
        c.public_satisfaction = max(0.0, (c.public_satisfaction or 0.0) - 1.0)
    await session.commit()

    text = (
        f"✅ <b>ویزای اجباری برای منطقه {reg_title} با موفقیت وضع گردید!</b>\n\n"
        f"• تعداد کشورهای افزوده شده: {fa_number(added)} کشور"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 بازگشت به سامانه ویزا", callback_data="gov:visa_law", style=STYLE_MAIN)
    await safe_edit(call, text, reply_markup=builder.as_markup())

    await send_to_admin_group(
        bot,
        AdminGroupType.SANCTION_BILL,
        f"🛂 <b>وضع ویزای منطقه‌ای</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"منطقه: {reg_title}\n"
        f"تعداد: {fa_number(added)} کشور",
    )


@router.callback_query(F.data.startswith("gov_vpick:"))
async def cb_visa_pick(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """لیست صفحه‌بندی‌شده کشورها برای انتخاب تکی/چندتایی وضع ویزا."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    page = int(call.data.split(":")[1])
    all_countries = await countries_repo.list_countries(session)
    visas = await gov_repo.get_visa_list(session, country.id)
    req_target_ids = {v.target_country_id for v in visas}
    req_target_ids.add(country.id)

    available = [c for c in all_countries if c.id not in req_target_ids]

    PAGE_SIZE = 8
    total_pages = max(1, (len(available) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    slice_items = available[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    builder = InlineKeyboardBuilder()
    for c in slice_items:
        builder.button(
            text=f"➕ {c.flag} {c.name_fa}",
            callback_data=f"gov_vadd_one:{c.id}:{page}",
            style=STYLE_NO,
        )
    builder.adjust(2)

    nav_btns = []
    if page > 0:
        nav_btns.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=f"gov_vpick:{page - 1}"))
    nav_btns.append(InlineKeyboardButton(text=f"📄 {fa_number(page + 1)}/{fa_number(total_pages)}", callback_data="noop"))
    if page < total_pages - 1:
        nav_btns.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=f"gov_vpick:{page + 1}"))
    if len(nav_btns) > 1:
        builder.row(*nav_btns)

    builder.row(InlineKeyboardButton(text="🔙 بازگشت به منوی ویزا", callback_data="gov:visa_bulk_menu", style=STYLE_MAIN))

    text = (
        "📌 <b>انتخاب کشور برای وضع ویزای اجباری</b>\n\n"
        f"تعداد کل کشورهای بدون ویزا: {fa_number(len(available))} کشور\n"
        "روی هر کشور بزنید تا ویزای اجباری برای اتباع آن وضع شود:"
    )
    await safe_edit(call, text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("gov_vadd_one:"))
async def cb_visa_add_one(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """وضع ویزا برای یک کشور و بازگشت به صفحه انتخاب."""
    country = await get_player_country(session, db_user)
    if country is None:
        await call.answer(NO_COUNTRY_TEXT, show_alert=True)
        return

    parts = call.data.split(":")
    target_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0

    target = await countries_repo.get_country(session, target_id)
    if not target:
        await call.answer("کشور یافت نشد.", show_alert=True)
        return

    already = await gov_repo.has_visa(session, country.id, target_id)
    if already:
        await call.answer("این کشور از قبل ویزا دارد.", show_alert=True)
    else:
        await gov_repo.add_visa(session, country.id, target_id)
        target.public_satisfaction = max(0.0, (target.public_satisfaction or 0.0) - 1.0)
        await session.commit()
        await call.answer(f"✅ ویزای اجباری برای {target.name_fa} وضع شد.", show_alert=True)

        await send_to_admin_group(
            bot,
            AdminGroupType.SANCTION_BILL,
            f"🛂 <b>وضع ویزا</b>\nکشور: {country.flag} {country.name_fa}\nهدف: {target.flag} {target.name_fa}",
        )

    call.data = f"gov_vpick:{page}"
    await cb_visa_pick(call, session, db_user)


@router.callback_query(F.data == "gov:visa_rm_menu")
@router.callback_query(F.data == "gov:visa_remove")
async def cb_visa_rm_menu(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """منوی رفع ویزای اجباری (تکی یا سراسری)."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    visas = await gov_repo.get_visa_list(session, country.id)
    has_visas = len(visas) > 0

    if not has_visas:
        text = (
            "⚠️ <b>هیچ ویزای اجباری ثبت نشده است.</b>\n\n"
            "کشور شما در حال حاضر برای هیچ کشوری ویزای ورود وضع نکرده است."
        )
    else:
        text = (
            "➖ <b>مدیریت رفع ویزای اجباری</b>\n\n"
            f"در حال حاضر برای {fa_number(len(visas))} کشور ویزای اجباری وضع شده است.\n"
            "می‌توانید ویزا را به صورت انتخابی یا برای تمامی کشورها لغو نمایید:"
        )

    await safe_edit(call, text, reply_markup=visa_rm_menu_kb(has_visas))


@router.callback_query(F.data.startswith("gov_vrm_pick:"))
async def cb_visa_rm_pick(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """لیست صفحه‌بندی‌شده کشورها برای رفع تکی ویزا."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    page = int(call.data.split(":")[1])
    visas = await gov_repo.get_visa_list(session, country.id)

    all_countries = await countries_repo.list_countries(session)
    c_map = {c.id: c for c in all_countries}
    visa_countries = [c_map[v.target_country_id] for v in visas if v.target_country_id in c_map]

    if not visa_countries:
        await safe_edit(
            call,
            "⚠️ هیچ ویزایی برای رفع وجود ندارد.",
            reply_markup=InlineKeyboardBuilder().button(text="🔙 بازگشت به سامانه ویزا", callback_data="gov:visa_law", style=STYLE_MAIN).as_markup(),
        )
        return

    PAGE_SIZE = 8
    total_pages = max(1, (len(visa_countries) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    slice_items = visa_countries[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    builder = InlineKeyboardBuilder()
    for c in slice_items:
        builder.button(
            text=f"❌ {c.flag} {c.name_fa}",
            callback_data=f"gov_vrm_do:{c.id}:{page}",
            style=STYLE_NO,
        )
    builder.adjust(2)

    nav_btns = []
    if page > 0:
        nav_btns.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=f"gov_vrm_pick:{page - 1}"))
    nav_btns.append(InlineKeyboardButton(text=f"📄 {fa_number(page + 1)}/{fa_number(total_pages)}", callback_data="noop"))
    if page < total_pages - 1:
        nav_btns.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=f"gov_vrm_pick:{page + 1}"))
    if len(nav_btns) > 1:
        builder.row(*nav_btns)

    builder.row(InlineKeyboardButton(text="🔙 بازگشت به منوی رفع ویزا", callback_data="gov:visa_rm_menu", style=STYLE_MAIN))

    text = (
        "❌ <b>رفع ویزای اجباری (انتخاب کشور)</b>\n\n"
        f"تعداد کشورهای دارای ویزا: {fa_number(len(visa_countries))} کشور\n"
        "روی هر کشور بزنید تا ویزای اجباری آن لغو شود:"
    )
    await safe_edit(call, text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("gov_vrm_do:"))
async def cb_visa_rm_do(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """لغو ویزا برای یک کشور و بازنشانی لیست."""
    country = await get_player_country(session, db_user)
    if country is None:
        await call.answer(NO_COUNTRY_TEXT, show_alert=True)
        return

    parts = call.data.split(":")
    target_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0

    target = await countries_repo.get_country(session, target_id)
    target_name = f"{target.flag} {target.name_fa}" if target else f"#{target_id}"

    removed = await gov_repo.remove_visa(session, country.id, target_id)
    await session.commit()

    if removed:
        await call.answer(f"✅ ویزای {target_name} لغو شد.", show_alert=True)
        await send_to_admin_group(
            bot,
            AdminGroupType.SANCTION_BILL,
            f"🛂 <b>لغو ویزای اجباری</b>\nکشور: {country.flag} {country.name_fa}\nهدف: {target_name}",
        )
    else:
        await call.answer("ویزا یافت نشد.", show_alert=True)

    call.data = f"gov_vrm_pick:{page}"
    await cb_visa_rm_pick(call, session, db_user)


@router.callback_query(F.data == "gov_vrm_all_ask")
async def cb_visa_rm_all_ask(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """درخواست تایید برای رفع ویزا از تمامی کشورها."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    visas = await gov_repo.get_visa_list(session, country.id)
    text = (
        "⚠️ <b>تأیید رفع ویزای اجباری از تمامی کشورها (عادی‌سازی مرزها)</b>\n\n"
        f"آیا اطمینان دارید که می‌خواهید ویزای اجباری تمامی <b>{fa_number(len(visas))} کشور</b> را لغو کرده و روابط مرزی را عادی‌سازی کنید؟"
    )
    await safe_edit(call, text, reply_markup=visa_rm_all_confirm_kb())


@router.callback_query(F.data == "gov_vrm_all_confirm")
async def cb_visa_rm_all_confirm(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """اجرای رفع تمامی ویزاهای اجباری."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    count = await gov_repo.remove_all_visas(session, country.id)
    await session.commit()

    text = (
        "✅ <b>تمامی ویزاهای اجباری ورود با موفقیت لغو شدند!</b>\n\n"
        f"تعداد {fa_number(count)} کشور از حالت ویزای اجباری خارج شده و مرزها به وضعیت عادی بازگشت."
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 بازگشت به سامانه ویزا", callback_data="gov:visa_law", style=STYLE_MAIN)
    await safe_edit(call, text, reply_markup=builder.as_markup())

    await send_to_admin_group(
        bot,
        AdminGroupType.SANCTION_BILL,
        f"🛂 <b>لغو کلیه ویزاهای اجباری (عادی‌سازی مرزها)</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"تعداد: {fa_number(count)} کشور",
    )


# ---------- مجلس ----------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _format_cooldown(rem_seconds: int | float) -> str:
    rem_sec = max(0, int(rem_seconds))
    h = rem_sec // 3600
    m = (rem_sec % 3600) // 60
    if h > 0 and m > 0:
        return f"{fa_number(h)} ساعت و {fa_number(m)} دقیقه"
    elif h > 0:
        return f"{fa_number(h)} ساعت"
    else:
        return f"{fa_number(max(1, m))} دقیقه"


def _aware_dt(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@router.callback_query(F.data == "gov:parliament", StateFilter("*"))
async def cb_parliament(
    call: CallbackQuery, session: AsyncSession, db_user: User, state: FSMContext | None = None
) -> None:
    await call.answer()
    if state:
        await state.clear()
    country = await get_player_country(session, db_user)
    quota_line = ""
    if country:
        now = _utcnow()
        since = now - timedelta(hours=LEGISLATION_LIMIT_HOURS)
        used = await gov_repo.count_laws_by_country_since(session, country.id, since)
        rem_quota = max(0, LEGISLATION_LIMIT_COUNT - used)
        if rem_quota > 0:
            quota_line = f"\n📊 <b>سهمیه لایحه شما:</b> {fa_number(rem_quota)} از {fa_number(LEGISLATION_LIMIT_COUNT)} (در {fa_number(LEGISLATION_LIMIT_HOURS)} ساعت)\n"
        else:
            earliest = await gov_repo.get_earliest_law_since(session, country.id, since)
            rem_str = "به‌زودی"
            if earliest and earliest.created_at:
                earliest_aware = _aware_dt(earliest.created_at)
                rem_sec = max(0, int((earliest_aware + timedelta(hours=LEGISLATION_LIMIT_HOURS) - now).total_seconds()))
                rem_str = _format_cooldown(rem_sec)
            quota_line = f"\n⏳ <b>سهمیه لایحه پر است.</b> آزادسازی سهمیه بعدی: {rem_str}\n"

    text = (
        header("مجلس شورای ملی", "🏛")
        + f"{quota_line}\n"
        "لوایح پیشنهادی شما جهت رای‌گیری به نمایندگان مجلس (ادمین‌ها) ارائه خواهد شد."
    )
    await safe_edit(call, text, reply_markup=parliament_menu_kb())


@router.callback_query(F.data == "gov:submit_law")
async def cb_submit_law(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """شروع فرم ارائه‌ی لایحه با بررسی گارد قفل و محدودیت زمانی."""
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "gov.legislation"):
        return

    # ۱. بررسی محدودیت سهمیه ۲ لایحه در ۱۲ ساعت (Fail-Fast)
    now = _utcnow()
    since = now - timedelta(hours=LEGISLATION_LIMIT_HOURS)
    used = await gov_repo.count_laws_by_country_since(session, country.id, since)
    if used >= LEGISLATION_LIMIT_COUNT:
        earliest = await gov_repo.get_earliest_law_since(session, country.id, since)
        rem_str = "به‌زودی"
        if earliest and earliest.created_at:
            earliest_aware = _aware_dt(earliest.created_at)
            rem_sec = max(0, int((earliest_aware + timedelta(hours=LEGISLATION_LIMIT_HOURS) - now).total_seconds()))
            rem_str = _format_cooldown(rem_sec)
        await call.answer(
            f"⏳ شما به سقف مجاز ثبت لایحه رسیده‌اید ({fa_number(LEGISLATION_LIMIT_COUNT)} لایحه در {fa_number(LEGISLATION_LIMIT_HOURS)} ساعت).\n"
            f"زمان باقیمانده تا ثبت بعدی: {rem_str}",
            show_alert=True,
        )
        return

    await call.answer()
    await state.set_state(LawForm.entering_title)
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 انصراف و بازگشت", callback_data="gov:parliament", style=STYLE_NO)
    ]])
    await safe_edit(
        call,
        f"{header('ارائه لایحه به مجلس', '📝')}\n\n"
        f"عنوان لایحه‌ی خود را وارد کنید (حداکثر ۲۰۰ کاراکتر):",
        reply_markup=cancel_kb,
    )


@router.message(StateFilter(LawForm.entering_title))
async def msg_law_title(msg: Message, state: FSMContext) -> None:
    """دریافت عنوان لایحه."""
    title = msg.text.strip() if msg.text else ""
    if not title or len(title) > 200:
        await msg.answer("⚠️ عنوان باید بین ۱ تا ۲۰۰ کاراکتر باشد.")
        return
    await state.update_data(law_title=title)
    await state.set_state(LawForm.entering_body)
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 انصراف و بازگشت", callback_data="gov:parliament", style=STYLE_NO)
    ]])
    await msg.answer("📝 حالا متن لایحه را بنویسید:", reply_markup=cancel_kb)


@router.message(StateFilter(LawForm.entering_body))
async def msg_law_body(
    msg: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """دریافت متن لایحه و ارسال به مجلس."""
    country = await get_player_country(session, db_user)
    if country is None:
        await msg.answer(NO_COUNTRY_TEXT)
        await state.clear()
        return

    body = msg.text.strip() if msg.text else ""
    if not body:
        await msg.answer("⚠️ متن لایحه نمی‌تواند خالی باشد.")
        return

    # بررسی نهایی سهمیه ۲ لایحه در ۱۲ ساعت (Final Check)
    now = _utcnow()
    since = now - timedelta(hours=LEGISLATION_LIMIT_HOURS)
    used = await gov_repo.count_laws_by_country_since(session, country.id, since)
    if used >= LEGISLATION_LIMIT_COUNT:
        await msg.answer(
            f"⏳ متأسفانه سقف مجاز ثبت لایحه شما ({fa_number(LEGISLATION_LIMIT_COUNT)} لایحه در {fa_number(LEGISLATION_LIMIT_HOURS)} ساعت) پر شده است.",
            reply_markup=parliament_menu_kb(),
        )
        await state.clear()
        return

    data = await state.get_data()
    title = data.get("law_title", "بدون عنوان")

    law = await gov_repo.create_law(session, country.id, title, body)
    await session.commit()
    await state.clear()

    await msg.answer(
        f"✅ لایحه‌ی «{title}» به مجلس ارائه شد.\n\n"
        f"ادمین‌ها (نمایندگان مجلس) درباره‌ی آن رأی خواهند داد.",
        reply_markup=parliament_menu_kb(),
    )

    # ارسال به گروه تحریم و لایحه با پنل مدیریتی جدید
    law_msg_text = _format_admin_law_msg(country, law)
    await send_to_admin_group(
        bot,
        AdminGroupType.SANCTION_BILL,
        law_msg_text,
        reply_markup=admin_law_panel_kb(law.id),
    )


def _format_admin_law_msg(country: Country, law: Law) -> str:
    """فرمت پیام لایحه در گروه ادمین همراه با پیش‌نمایش زنده اثرات ثبت‌شده."""
    stab_sign = "+" if law.stability_effect >= 0 else ""
    sat_sign = "+" if law.satisfaction_effect >= 0 else ""
    return (
        f"🏛 <b>لایحه‌ی جدید در مجلس</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"عنوان: <b>{law.title}</b>\n\n"
        f"📝 <b>متن لایحه:</b>\n{law.body[:600]}\n\n"
        f"📌 <b>نتیجه ثبت‌شده فعلی:</b> {stab_sign}{law.stability_effect:.1f}٪ ثبات داخلی | "
        f"{sat_sign}{law.satisfaction_effect:.1f}٪ رضایت عمومی"
    )


@router.callback_query(F.data.startswith("gov_admin:law_main:"))
async def cb_admin_law_main(call: CallbackQuery, session: AsyncSession) -> None:
    """بازگشت به پنل اصلی لایحه در گروه ادمین."""
    await call.answer()
    lid = int(call.data.split(":")[-1])
    law = await gov_repo.get_law_by_id(session, lid)
    if not law:
        await call.answer("لایحه یافت نشد.", show_alert=True)
        return
    country = await countries_repo.get_country(session, law.country_id)
    if not country:
        return
    await safe_edit(call, _format_admin_law_msg(country, law), reply_markup=admin_law_panel_kb(law.id))


@router.callback_query(F.data.startswith("gov_admin:law_res:"))
async def cb_admin_law_result_menu(call: CallbackQuery, session: AsyncSession) -> None:
    """باز کردن منوی تعیین/ویرایش اثرات لایحه روی ثبات و رضایت."""
    await call.answer()
    lid = int(call.data.split(":")[-1])
    law = await gov_repo.get_law_by_id(session, lid)
    if not law:
        await call.answer("لایحه یافت نشد.", show_alert=True)
        return
    country = await countries_repo.get_country(session, law.country_id)
    if not country:
        return

    text = (
        _format_admin_law_msg(country, law)
        + "\n\n⚙️ <b>تنظیم اثرات لایحه:</b>\n"
        "برای تغییر اثرات، دکمه‌های آماده زیر را بزنید یا گزینه عدد دلخواه را انتخاب کنید:"
    )
    await safe_edit(
        call,
        text,
        reply_markup=admin_law_result_kb(law.id, law.stability_effect, law.satisfaction_effect),
    )


@router.callback_query(F.data.startswith("gov_admin:stab:"))
async def cb_admin_set_stability(call: CallbackQuery, session: AsyncSession) -> None:
    """تنظیم سریع ثبات داخلی لایحه."""
    parts = call.data.split(":")
    lid = int(parts[2])
    val = float(parts[3])

    law = await gov_repo.update_law_effects(session, lid, stability_effect=val)
    if not law:
        await call.answer("لایحه یافت نشد.", show_alert=True)
        return
    await session.commit()
    await call.answer(f"ثبات روی {val:+.1f}٪ تنظیم شد")

    country = await countries_repo.get_country(session, law.country_id)
    if country:
        text = (
            _format_admin_law_msg(country, law)
            + "\n\n⚙️ <b>تنظیم اثرات لایحه:</b>\n"
            "برای تغییر اثرات، دکمه‌های آماده زیر را بزنید یا گزینه عدد دلخواه را انتخاب کنید:"
        )
        await safe_edit(
            call,
            text,
            reply_markup=admin_law_result_kb(law.id, law.stability_effect, law.satisfaction_effect),
        )


@router.callback_query(F.data.startswith("gov_admin:sat:"))
async def cb_admin_set_satisfaction(call: CallbackQuery, session: AsyncSession) -> None:
    """تنظیم سریع رضایت عمومی لایحه."""
    parts = call.data.split(":")
    lid = int(parts[2])
    val = float(parts[3])

    law = await gov_repo.update_law_effects(session, lid, satisfaction_effect=val)
    if not law:
        await call.answer("لایحه یافت نشد.", show_alert=True)
        return
    await session.commit()
    await call.answer(f"رضایت روی {val:+.1f}٪ تنظیم شد")

    country = await countries_repo.get_country(session, law.country_id)
    if country:
        text = (
            _format_admin_law_msg(country, law)
            + "\n\n⚙️ <b>تنظیم اثرات لایحه:</b>\n"
            "برای تغییر اثرات، دکمه‌های آماده زیر را بزنید یا گزینه عدد دلخواه را انتخاب کنید:"
        )
        await safe_edit(
            call,
            text,
            reply_markup=admin_law_result_kb(law.id, law.stability_effect, law.satisfaction_effect),
        )


@router.callback_query(F.data.startswith("gov_admin:cstab:"))
async def cb_admin_custom_stability(call: CallbackQuery, state: FSMContext) -> None:
    """شروع فرم ورود دستی عدد ثبات داخلی."""
    lid = int(call.data.split(":")[-1])
    await state.set_state(AdminLawResultForm.entering_custom_stability)
    await state.update_data(law_id=lid, chat_id=call.message.chat.id, message_id=call.message.message_id)
    await call.answer()
    await call.message.reply(
        f"✏️ لطفاً درصد تغییر <b>ثبات داخلی</b> را برای لایحه #{lid} ارسال کنید (مثلاً <code>+7.5</code> یا <code>-4</code>):"
    )


@router.message(StateFilter(AdminLawResultForm.entering_custom_stability))
async def msg_admin_custom_stability(msg: Message, state: FSMContext, session: AsyncSession) -> None:
    """دریافت عدد دستی ثبات و اعمال."""
    raw = (msg.text or "").replace("٪", "").replace("%", "").replace("+", "").strip().translate(_FA_TO_EN)
    try:
        val = float(raw)
        if "-" in (msg.text or ""):
            val = -abs(val)
    except ValueError:
        await msg.reply("⚠️ لطفاً یک عدد معتبر ارسال کنید (مثلاً <code>+5</code> یا <code>-3</code>):")
        return

    data = await state.get_data()
    lid = data.get("law_id")
    chat_id = data.get("chat_id")
    orig_msg_id = data.get("message_id")
    await state.clear()

    law = await gov_repo.update_law_effects(session, lid, stability_effect=val)
    if not law:
        await msg.reply("❌ لایحه یافت نشد.")
        return
    await session.commit()

    country = await countries_repo.get_country(session, law.country_id)
    await msg.reply(f"✅ اثر بر ثبات داخلی با موفقیت روی <b>{val:+.1f}٪</b> تنظیم شد.")

    if country and chat_id and orig_msg_id:
        try:
            text = (
                _format_admin_law_msg(country, law)
                + "\n\n⚙️ <b>تنظیم اثرات لایحه:</b>\n"
                "برای تغییر اثرات، دکمه‌های آماده زیر را بزنید یا گزینه عدد دلخواه را انتخاب کنید:"
            )
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=orig_msg_id,
                text=text,
                reply_markup=admin_law_result_kb(law.id, law.stability_effect, law.satisfaction_effect),
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("gov_admin:csat:"))
async def cb_admin_custom_satisfaction(call: CallbackQuery, state: FSMContext) -> None:
    """شروع فرم ورود دستی عدد رضایت عمومی."""
    lid = int(call.data.split(":")[-1])
    await state.set_state(AdminLawResultForm.entering_custom_satisfaction)
    await state.update_data(law_id=lid, chat_id=call.message.chat.id, message_id=call.message.message_id)
    await call.answer()
    await call.message.reply(
        f"✏️ لطفاً درصد تغییر <b>رضایت عمومی</b> را برای لایحه #{lid} ارسال کنید (مثلاً <code>+8</code> یا <code>-5</code>):"
    )


@router.message(StateFilter(AdminLawResultForm.entering_custom_satisfaction))
async def msg_admin_custom_satisfaction(msg: Message, state: FSMContext, session: AsyncSession) -> None:
    """دریافت عدد دستی رضایت و اعمال."""
    raw = (msg.text or "").replace("٪", "").replace("%", "").replace("+", "").strip().translate(_FA_TO_EN)
    try:
        val = float(raw)
        if "-" in (msg.text or ""):
            val = -abs(val)
    except ValueError:
        await msg.reply("⚠️ لطفاً یک عدد معتبر ارسال کنید (مثلاً <code>+5</code> یا <code>-3</code>):")
        return

    data = await state.get_data()
    lid = data.get("law_id")
    chat_id = data.get("chat_id")
    orig_msg_id = data.get("message_id")
    await state.clear()

    law = await gov_repo.update_law_effects(session, lid, satisfaction_effect=val)
    if not law:
        await msg.reply("❌ لایحه یافت نشد.")
        return
    await session.commit()

    country = await countries_repo.get_country(session, law.country_id)
    await msg.reply(f"✅ اثر بر رضایت عمومی با موفقیت روی <b>{val:+.1f}٪</b> تنظیم شد.")

    if country and chat_id and orig_msg_id:
        try:
            text = (
                _format_admin_law_msg(country, law)
                + "\n\n⚙️ <b>تنظیم اثرات لایحه:</b>\n"
                "برای تغییر اثرات، دکمه‌های آماده زیر را بزنید یا گزینه عدد دلخواه را انتخاب کنید:"
            )
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=orig_msg_id,
                text=text,
                reply_markup=admin_law_result_kb(law.id, law.stability_effect, law.satisfaction_effect),
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("gov_admin:law_apply:"))
async def cb_admin_law_apply(call: CallbackQuery, session: AsyncSession) -> None:
    """ادمین لایحه را تصویب و نهایی می‌کند و اثرات روی کشور اعمال می‌شود."""
    await call.answer("لایحه اعمال و بسته شد ✅")
    lid = int(call.data.split(":")[-1])

    law, country, stab_delta, sat_delta = await gov_repo.apply_and_close_law(session, lid)
    if not law or not country:
        await call.answer("خطا در یافتن لایحه یا کشور.", show_alert=True)
        return
    await session.commit()

    # ویرایش پیام در گروه ادمین و بستن دکمه‌ها
    stab_sign = "+" if stab_delta >= 0 else ""
    sat_sign = "+" if sat_delta >= 0 else ""
    admin_name = call.from_user.full_name

    try:
        await call.message.edit_text(
            f"{call.message.text}\n\n"
            f"✅ <b>لایحه رسماً تصویب، اعمال و بسته شد.</b>\n"
            f"• تغییر ثبات داخلی: <b>{stab_sign}{stab_delta:.1f}٪</b> (میزان فعلی: {country.stability:.1f}٪)\n"
            f"• تغییر رضایت عمومی: <b>{sat_sign}{sat_delta:.1f}٪</b> (میزان فعلی: {country.public_satisfaction:.1f}٪)\n"
            f"• مجری تصویب: {admin_name}",
            reply_markup=None,
        )
    except Exception:
        pass

    # ارسال گزارش تصویب لایحه به پیوی بازیکن کشور
    if country.owner_user_id:
        try:
            await bot.send_message(
                country.owner_user_id,
                f"🏛 <b>لایحه‌ی «{law.title}» در مجلس تصویب و اجرایی شد!</b>\n\n"
                f"نمایندگان مجلس شورای ملی لایحه‌ی پیشنهادی شما را مصوب نموده و نتایج آن رسماً در کشور اعمال گردید:\n"
                f"📈 تغییر ثبات داخلی: <b>{stab_sign}{stab_delta:.1f}٪</b>\n"
                f"😊 تغییر رضایت عمومی: <b>{sat_sign}{sat_delta:.1f}٪</b>\n\n"
                f"📊 وضعیت جدید کشور: ثبات داخلی {country.stability:.1f}٪ | رضایت عمومی {country.public_satisfaction:.1f}٪",
            )
        except Exception:
            pass

    # ثبت لاگ در گروه لاگ اصلی
    await send_log(
        bot,
        f"🏛 <b>تصویب و اعمال نهایی لایحه</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"لایحه: {law.title}\n"
        f"اثرات اعمال‌شده: {stab_sign}{stab_delta:.1f}٪ ثبات | {sat_sign}{sat_delta:.1f}٪ رضایت\n"
        f"ادمین: {admin_name}",
    )


@router.callback_query(F.data.startswith("gov_admin:law_no:"))
async def cb_admin_law_no(call: CallbackQuery, session: AsyncSession) -> None:
    """ادمین لایحه را رد می‌کند."""
    await call.answer("لایحه رد شد ❌")
    lid = int(call.data.split(":")[-1])
    law = await gov_repo.vote_law(session, lid, approved=False, vote_result="اکثریت آرای مجلس: مخالف")
    await session.commit()

    if law:
        c = await countries_repo.get_country(session, law.country_id)
        if c and c.owner_user_id:
            try:
                await bot.send_message(
                    c.owner_user_id,
                    f"❌ لایحه‌ی «{law.title}» در مجلس <b>رد</b> شد.\n"
                    f"رأی: {law.vote_result}",
                )
            except Exception:
                pass

        try:
            await call.message.edit_text(
                call.message.text + "\n\n❌ <b>لایحه توسط مجلس رد شد.</b>",
                reply_markup=None,
            )
        except Exception:
            pass

        await send_log(
            bot,
            f"🏛 <b>رد لایحه در مجلس</b>\n"
            f"کشور: {c.flag if c else ''} {c.name_fa if c else ''}\n"
            f"لایحه: {law.title}\n"
            f"ادمین: {call.from_user.full_name}",
        )


@router.callback_query(F.data == "gov:my_laws")
async def cb_my_laws(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """لیست لوایح کشور."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    laws = await gov_repo.get_laws(session, country.id)
    if not laws:
        await safe_edit(
            call,
            f"{header('لایحه‌های من', '📋')}\n\nهیچ لایحه‌ای ثبت نشده.",
            reply_markup=parliament_menu_kb(),
        )
        return

    lines = [header("لایحه‌های من", "📋"), ""]
    for law in laws[:15]:
        try:
            status_fa = LAW_STATUS_FA.get(LawStatus(law.status), law.status)
        except ValueError:
            status_fa = law.status
        lines.append(f"• <b>{law.title}</b> — {status_fa}")
        if law.vote_result:
            lines.append(f"  🗳 {law.vote_result}")

    await safe_edit(call, "\n".join(lines), reply_markup=parliament_menu_kb())
