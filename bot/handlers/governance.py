"""هندلر بخش حاکمیت: نظام حاکمیتی، اعتراضات، قانونگذاری (v1.10.2)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import (
    GOVERNMENT_BONUSES,
    TAX_MAX_RATE,
    TAX_MIN_RATE,
)
from ..database.models import User
from ..database.repositories import countries as countries_repo
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
    governance_menu_kb,
    government_system_kb,
    government_type_kb,
    legislation_menu_kb,
    parliament_menu_kb,
    protest_action_kb,
    protest_menu_kb,
    tax_law_kb,
    visa_law_kb,
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
from ..services.news_service import send_log
from ..states import GovernanceForm, LawForm
from ..utils.numbers import fa_money, fa_number, parse_amount
from ..utils.screens import safe_edit
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
    from ..utils.screens import show_menu
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

    await safe_edit(
        call, "\n".join(lines),
        reply_markup=government_system_kb(has_govt, changes_left),
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

    # لاگ
    await send_log(
        bot,
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
    await safe_edit(call, header("اعتراضات و رفراندوم", "✊"), reply_markup=protest_menu_kb())


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

    await send_log(
        bot,
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
    await safe_edit(call, header("قانونگذاری", "📜"), reply_markup=legislation_menu_kb())


# ---------- مالیات ----------

@router.callback_query(F.data == "gov:tax_law")
async def cb_tax_law(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    await call.answer()
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
        rate = float(msg.text.replace("٪", "").replace("%", "").strip())
    except (ValueError, AttributeError):
        await msg.answer("⚠️ لطفاً یک عدد معتبر وارد کنید.")
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

    await send_log(
        bot,
        f"💰 <b>تغییر مالیات</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"نرخ: {old_rate:.1f}٪ → {new_rate:.1f}٪",
    )


# ---------- ویزا ----------

@router.callback_query(F.data == "gov:visa_law")
async def cb_visa_law(call: CallbackQuery) -> None:
    await call.answer()
    await safe_edit(call, header("قانون ویزا", "🛂"), reply_markup=visa_law_kb())


@router.callback_query(F.data == "gov:visa_list")
async def cb_visa_list(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """نمایش کشورهایی که ویزا لازم دارند."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    visas = await gov_repo.get_visa_list(session, country.id)
    if not visas:
        await safe_edit(
            call,
            f"{header('لیست ویزاها', '🛂')}\n\nهیچ کشوری نیاز به ویزا ندارد.",
            reply_markup=visa_law_kb(),
        )
        return

    lines = [header("لیست ویزاها", "🛂"), ""]
    for v in visas:
        target = await countries_repo.get_country(session, v.target_country_id)
        if target:
            lines.append(f"🛂 {target.flag} {target.name_fa}")
    lines.append(f"\nمجموع: {fa_number(len(visas))} کشور")

    await safe_edit(call, "\n".join(lines), reply_markup=visa_law_kb())


@router.callback_query(F.data == "gov:visa_add")
async def cb_visa_add(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """انتخاب کشور برای افزودن ویزا."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    # کشورهایی که قبلاً ویزا دارند را حذف کن
    existing_visas = await gov_repo.get_visa_list(session, country.id)
    excluded_ids = {v.target_country_id for v in existing_visas}
    excluded_ids.add(country.id)  # خود کشور

    all_countries = await countries_repo.list_countries(session)
    filtered = [c for c in all_countries if c.id not in excluded_ids]

    if not filtered:
        await safe_edit(call, "⚠️ کشوری برای افزودن ویزا باقی نمانده.", reply_markup=visa_law_kb())
        return

    kb = countries_kb(filtered, "gov_visa_add", back_data="gov:visa_law")
    await safe_edit(call, "🛂 کشوری که باید ویزا بگیرد را انتخاب کنید:", reply_markup=kb)


@router.callback_query(F.data.startswith("gov_visa_add:"))
async def cb_visa_add_confirm(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """تأیید افزودن ویزا."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    target_id = int(call.data.split(":")[-1])
    target = await countries_repo.get_country(session, target_id)
    if target is None:
        await safe_edit(call, "⚠️ کشور یافت نشد.", reply_markup=visa_law_kb())
        return

    already = await gov_repo.has_visa(session, country.id, target_id)
    if already:
        await safe_edit(call, "⚠️ این کشور از قبل ویزا دارد.", reply_markup=visa_law_kb())
        return

    await gov_repo.add_visa(session, country.id, target_id)
    # کسر رضایت از کشور هدف به دلیل ویزا
    target.public_satisfaction = max(0.0, (target.public_satisfaction or 0.0) - 1.0)
    await session.commit()

    await safe_edit(
        call,
        f"✅ ویزای اجباری برای {target.flag} {target.name_fa} وضع شد.\n\n"
        f"شهروندان {target.name_fa} برای سفر به {country.name_fa} نیاز به ویزا دارند.",
        reply_markup=visa_law_kb(),
    )

    await send_log(
        bot,
        f"🛂 <b>وضع ویزا</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"هدف: {target.flag} {target.name_fa}",
    )


@router.callback_query(F.data == "gov:visa_remove")
async def cb_visa_remove(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """انتخاب ویزا برای حذف."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    visas = await gov_repo.get_visa_list(session, country.id)
    if not visas:
        await safe_edit(
            call, "⚠️ هیچ ویزایی وضع نشده.", reply_markup=visa_law_kb(),
        )
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    for v in visas:
        target = await countries_repo.get_country(session, v.target_country_id)
        if target:
            builder.button(
                text=f"❌ {target.flag} {target.name_fa}",
                callback_data=f"gov_visa_rm:{v.target_country_id}",
                style=STYLE_NO,
            )
    builder.button(text="🔙 بازگشت", callback_data="gov:visa_law", style=STYLE_MAIN)
    builder.adjust(1)

    await safe_edit(call, "ویزای کدام کشور حذف شود؟", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("gov_visa_rm:"))
async def cb_visa_remove_confirm(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """حذف ویزا."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    target_id = int(call.data.split(":")[-1])
    removed = await gov_repo.remove_visa(session, country.id, target_id)
    await session.commit()

    target = await countries_repo.get_country(session, target_id)
    name = f"{target.flag} {target.name_fa}" if target else f"#{target_id}"

    if removed:
        await safe_edit(
            call, f"✅ ویزای {name} حذف شد.", reply_markup=visa_law_kb(),
        )
        await send_log(bot, f"🛂 <b>حذف ویزا</b>\nکشور: {country.flag} {country.name_fa}\nهدف: {name}")
    else:
        await safe_edit(call, "⚠️ ویزا یافت نشد.", reply_markup=visa_law_kb())


# ---------- مجلس ----------

@router.callback_query(F.data == "gov:parliament")
async def cb_parliament(call: CallbackQuery) -> None:
    await call.answer()
    await safe_edit(call, header("مجلس", "🏛"), reply_markup=parliament_menu_kb())


@router.callback_query(F.data == "gov:submit_law")
async def cb_submit_law(call: CallbackQuery, state: FSMContext) -> None:
    """شروع فرم ارائه‌ی لایحه."""
    await call.answer()
    await state.set_state(LawForm.entering_title)
    await safe_edit(
        call,
        f"{header('ارائه لایحه به مجلس', '📝')}\n\n"
        f"عنوان لایحه‌ی خود را وارد کنید:",
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
    await msg.answer("📝 حالا متن لایحه را بنویسید:")


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

    # ارسال به لاگ برای رأی‌گیری
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ تصویب", callback_data=f"gov_admin:law_ok:{law.id}", style=STYLE_OK)
    builder.button(text="❌ رد", callback_data=f"gov_admin:law_no:{law.id}", style=STYLE_NO)
    builder.adjust(2)

    await send_log(
        bot,
        f"🏛 <b>لایحه‌ی جدید در مجلس</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"عنوان: {title}\n\n"
        f"📝 متن:\n{body[:500]}",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("gov_admin:law_ok:"))
async def cb_admin_law_ok(call: CallbackQuery, session: AsyncSession) -> None:
    """ادمین لایحه را تصویب می‌کند."""
    await call.answer("لایحه تصویب شد ✅")
    lid = int(call.data.split(":")[-1])
    law = await gov_repo.vote_law(session, lid, approved=True, vote_result="اکثریت آرای مجلس: موافق")
    await session.commit()

    if law:
        # اطلاع به مالک کشور
        c = await countries_repo.get_country(session, law.country_id)
        if c and c.owner_user_id:
            try:
                await bot.send_message(
                    c.owner_user_id,
                    f"✅ لایحه‌ی «{law.title}» در مجلس <b>تصویب</b> شد.\n"
                    f"رأی: {law.vote_result}",
                )
            except Exception:
                pass

    try:
        await call.message.edit_text(
            call.message.text + "\n\n✅ <b>تصویب شد</b>",
        )
    except Exception:
        pass


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
            call.message.text + "\n\n❌ <b>رد شد</b>",
        )
    except Exception:
        pass


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
