"""
هندلر عملیات مخفیانه (v1.10.7): جاسوسی و ترور.

قاعده‌ی کلیدی: **بدون جاسوسی، ترور ممکن نیست.**
بازیکن اول باید محل و برنامه‌ی فرمانده هدف را کشف کند؛ کیفیت اطلاعاتی
که به دست می‌آورد مستقیماً شانس موفقیت ترور را تعیین می‌کند.

(v2.1) شانس هر عملیات به «قدرت اطلاعاتی» دو کشور وابسته است و اهدافی که
اختلاف قدرت اجازه‌ی نفوذ به آن‌ها را نمی‌دهد با ⛔️ نمایش داده می‌شوند.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    ASSASSINATION_MIN_INTEL_QUALITY,
    ESPIONAGE_COOLDOWN_HOURS,
    ESPIONAGE_COST_USD,
    ESPIONAGE_INTEL_VALID_HOURS,
)
from ..database.models import User
from ..database.repositories import commander_intel as intel_repo
from ..database.repositories import commanders as cmd_repo
from ..database.repositories import countries as countries_repo
from ..enums import COMMANDER_ROLE_FA, CommanderRole
from ..keyboards.covert import (
    commander_targets_kb,
    confirm_kb,
    covert_menu_kb,
    intel_targets_kb,
)
from ..loader import bot
from ..services import assassination_service as assn_service
from ..services import espionage_service as spy_service
from ..services import intel_power_service as intel_power
from ..services import operation_service as op_service
from ..services.news_service import send_log
from ..states import AssassinationForm, EspionageForm
from ..utils.numbers import fa_money, fa_number
from ..utils.screens import safe_edit
from ..utils.ui import DIVIDER, header
from .deps import NO_COUNTRY_TEXT, assert_feature, get_player_country

logger = logging.getLogger(__name__)
router = Router(name="covert_ops")


def _role_fa(commander) -> str:
    """نام فارسی تخصص یک فرمانده."""
    try:
        return COMMANDER_ROLE_FA[CommanderRole(commander.role)]
    except (ValueError, KeyError):
        return commander.role


# ============================================================
#  منوی عملیات مخفیانه
# ============================================================
@router.callback_query(F.data == "op:covert")
async def cb_covert_menu(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """منوی جاسوسی و ترور."""
    await call.answer()
    await state.clear()
    country = await get_player_country(session, db_user)
    tier = (
        f"🕵️ رده‌ی اطلاعاتی کشور شما: <b>{intel_power.tier_text(country.name_en)}</b>\n\n"
        if country
        else ""
    )
    text = (
        header("عملیات مخفیانه", "🕵️") + "\n\n"
        f"{tier}"
        "🔍 <b>جاسوسی</b> — محل و برنامه‌ی فرماندهان دشمن را کشف می‌کند.\n"
        "🎯 <b>ترور</b> — فقط روی فرمانده‌ای ممکن است که از قبل شناسایی کرده باشید.\n\n"
        f"⏱ فاصله‌ی بین دو عملیات جاسوسی: {fa_number(ESPIONAGE_COOLDOWN_HOURS)} ساعت\n"
        f"💰 هزینه‌ی هر جاسوسی: {fa_money(ESPIONAGE_COST_USD)}\n"
        f"📅 اعتبار اطلاعات: {fa_number(ESPIONAGE_INTEL_VALID_HOURS)} ساعت\n\n"
        "<i>شانس موفقیت به اختلاف توان اطلاعاتی شما و کشور هدف بستگی دارد؛ "
        "نفوذ به قدرت‌های اطلاعاتی بسیار سخت و گاهی ناممکن است.</i>"
    )
    await safe_edit(call, text, reply_markup=covert_menu_kb())


# ============================================================
#  🔍 عملیات جاسوسی
# ============================================================
@router.callback_query(F.data == "spy:start")
async def cb_spy_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """شروع جاسوسی: بررسی کول‌داون و انتخاب کشور هدف."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "covert.espionage"):
        return

    try:
        await spy_service.assert_can_spy(session, country)
    except spy_service.EspionageError as err:
        await safe_edit(call, str(err), reply_markup=covert_menu_kb())
        return

    await state.clear()
    await state.set_state(EspionageForm.choosing_country)

    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id]
    rows = spy_service.target_rows(country, others)

    await safe_edit(
        call,
        header("عملیات جاسوسی", "🔍") + "\n\n"
        "سرویس اطلاعاتی شما آماده‌ی اعزام عوامل است.\n"
        f"🕵️ رده‌ی شما: <b>{intel_power.tier_text(country.name_en)}</b>\n"
        f"{DIVIDER}\n"
        "🎯 <b>کشور هدف را انتخاب کنید:</b>\n"
        "<i>عدد کنار هر کشور، شانس تخمینی نفوذ است. ⛔️ یعنی توان اطلاعاتی شما "
        "برای نفوذ به آن کشور کافی نیست.</i>",
        reply_markup=intel_targets_kb(rows, prefix="spy_country", back_data="op:covert"),
    )


@router.callback_query(F.data.startswith("spy_country_blocked:"))
async def cb_spy_blocked(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """راهنما وقتی بازیکن روی کشوری می‌زند که توان نفوذ به آن را ندارد."""
    await call.answer()
    country = await get_player_country(session, db_user)
    target = await countries_repo.get_country(session, int(call.data.split(":")[1]))
    if country is None or target is None:
        return
    await safe_edit(
        call,
        intel_power.block_reason(
            country.name_en,
            target.name_en,
            spy_fa=country.name_fa,
            target_fa=f"{target.flag} {target.name_fa}",
        ),
        reply_markup=covert_menu_kb(),
    )


@router.callback_query(EspionageForm.choosing_country, F.data.startswith("spy_country:"))
async def cb_spy_country(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """انتخاب کشور هدف و نمایش فرماندهان آن."""
    await call.answer()
    target_id = int(call.data.split(":")[1])

    country = await get_player_country(session, db_user)
    target = await countries_repo.get_country(session, target_id)
    if country is None or target is None:
        await safe_edit(call, "کشور هدف یافت نشد.", reply_markup=covert_menu_kb())
        return

    # (v2.1) اعتبارسنجی دوباره‌ی توان نفوذ (کال‌بک قدیمی راه فرار نباشد)
    try:
        spy_service.assert_target_reachable(country, target)
    except spy_service.EspionageError as err:
        await safe_edit(call, str(err), reply_markup=covert_menu_kb())
        return

    rows = await spy_service.targets_with_intel_status(session, country.id, target_id)
    if not rows:
        await safe_edit(
            call,
            f"⚠️ کشور {target.flag} {target.name_fa} فرمانده‌ی ثبت‌شده‌ای ندارد.",
            reply_markup=covert_menu_kb(),
        )
        return

    await state.update_data(target_country_id=target_id)
    await state.set_state(EspionageForm.choosing_commander)

    lines = [
        header("انتخاب هدف جاسوسی", "🔍"),
        "",
        f"کشور هدف: {target.flag} <b>{target.name_fa}</b>",
        DIVIDER,
        "فرماندهی که می‌خواهید شناسایی کنید را انتخاب کنید.",
        "",
        "<i>درصد کنار هر نام، کیفیت اطلاعات فعلی شماست.</i>",
    ]
    await safe_edit(
        call,
        "\n".join(lines),
        reply_markup=commander_targets_kb(
            rows, prefix="spy_cmd", back_data="spy:start"
        ),
    )


@router.callback_query(EspionageForm.choosing_commander, F.data.startswith("spy_cmd:"))
async def cb_spy_commander(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """نمایش تأیید نهایی عملیات جاسوسی."""
    await call.answer()
    commander_id = int(call.data.split(":")[1])

    country = await get_player_country(session, db_user)
    commander = await cmd_repo.get_commander(session, commander_id)
    if country is None or commander is None:
        await safe_edit(call, "فرمانده یافت نشد.", reply_markup=covert_menu_kb())
        return

    target = await countries_repo.get_country(session, commander.country_id)
    await state.update_data(commander_id=commander_id)
    await state.set_state(EspionageForm.confirming)

    existing = await intel_repo.get_valid_intel(session, country.id, commander_id)
    current = (
        f"\n📁 اطلاعات فعلی: {spy_service.quality_label(existing.quality)} "
        f"({fa_number(existing.quality)}٪)\n"
        "<i>عملیات جدید اطلاعات قبلی را جایگزین می‌کند.</i>"
        if existing
        else "\n📁 اطلاعات فعلی: ❔ ندارید"
    )

    # (v2.1) شانس واقعی نفوذ (اختلاف رده + بونوس فرمانده اطلاعات/ماهواره)
    bonus = await assn_service.intel_bonus_for(session, country.id)
    chance = min(
        92.0,
        intel_power.espionage_chance(country.name_en, target.name_en) + bonus * 0.5,
    )
    warn = (
        "\n\n🔴 <b>هشدار:</b> شانس نفوذ بسیار پایین است؛ احتمال از دست دادن "
        "بودجه و لو رفتن عوامل زیاد است."
        if chance < 20.0
        else ""
    )

    text = (
        header("تأیید عملیات جاسوسی", "🔍") + "\n\n"
        f"🎯 هدف: <b>{commander.rank_title} {commander.name}</b>\n"
        f"🎖 سمت: {_role_fa(commander)}\n"
        f"🏴 کشور: {target.flag} {target.name_fa}\n"
        f"{current}\n"
        f"{DIVIDER}\n"
        f"🕵️ رده‌ی شما: {intel_power.tier_text(country.name_en)}\n"
        f"🛡 رده‌ی هدف: {intel_power.tier_text(target.name_en)}\n"
        f"📊 شانس موفقیت: <b>{fa_number(chance, 1)}٪</b>\n"
        f"💰 هزینه: {fa_money(ESPIONAGE_COST_USD)}\n"
        f"⏱ کول‌داون بعدی: {fa_number(ESPIONAGE_COOLDOWN_HOURS)} ساعت\n\n"
        "⚠️ <i>هزینه در هر حالت (موفق یا ناموفق) کسر می‌شود و در صورت لو رفتن "
        "عوامل، رضایت عمومی کشورتان کاهش می‌یابد.</i>"
        f"{warn}"
    )
    await safe_edit(call, text, reply_markup=confirm_kb("spy_confirm", "op:covert"))


@router.callback_query(EspionageForm.confirming, F.data == "spy_confirm")
async def cb_spy_confirm(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """اجرای عملیات جاسوسی و نمایش گزارش اطلاعاتی."""
    await call.answer()
    data = await state.get_data()
    await state.clear()

    country = await get_player_country(session, db_user)
    commander = await cmd_repo.get_commander(session, data.get("commander_id", 0))
    if country is None or commander is None:
        await safe_edit(call, "خطا در اجرای عملیات.", reply_markup=covert_menu_kb())
        return

    target = await countries_repo.get_country(session, commander.country_id)
    if target is None:
        await safe_edit(call, "کشور هدف یافت نشد.", reply_markup=covert_menu_kb())
        return

    try:
        result = await spy_service.run_espionage(session, country, target, commander)
    except spy_service.EspionageError as err:
        await safe_edit(call, f"⛔️ {err}", reply_markup=covert_menu_kb())
        return

    await session.commit()

    # ---------- گزارش به بازیکن ----------
    if result["success"]:
        text = (
            header("گزارش اطلاعاتی", "📁") + "\n\n"
            f"✅ عوامل ما «{result['commander_name']}» را شناسایی کردند.\n\n"
            f"📊 کیفیت اطلاعات: <b>{result['quality_label']}</b> "
            f"({fa_number(result['quality'])}٪)\n"
            f"📍 محل: {result['location']}\n"
            f"🕐 الگوی رفتاری: {result['routine']}\n"
            f"{DIVIDER}\n"
            f"⏳ اعتبار اطلاعات: {fa_number(ESPIONAGE_INTEL_VALID_HOURS)} ساعت\n\n"
        )
        if result["quality"] >= ASSASSINATION_MIN_INTEL_QUALITY:
            text += "🎯 <i>اکنون می‌توانید عملیات ترور روی این هدف اجرا کنید.</i>"
        else:
            text += (
                f"⚠️ <i>کیفیت اطلاعات برای ترور کافی نیست "
                f"(حداقل {fa_number(ASSASSINATION_MIN_INTEL_QUALITY)}٪). "
                "عملیات دیگری اجرا کنید.</i>"
            )
        if result["detected"]:
            text += "\n\n🚨 <b>هشدار:</b> احتمال می‌رود دشمن از حضور عوامل ما باخبر شده باشد."
    else:
        if result["detected"]:
            text = (
                header("شکست عملیات", "🚨") + "\n\n"
                "❌ عوامل ما شناسایی و بازداشت شدند.\n"
                "هیچ اطلاعاتی به دست نیامد و رسوایی امنیتی رخ داد.\n\n"
                "<i>گشت‌های امنیتی کشور هدف فعال بوده‌اند.</i>"
            )
        else:
            text = (
                header("عملیات ناموفق", "🔍") + "\n\n"
                "❌ عوامل ما نتوانستند به هدف نزدیک شوند.\n"
                "اطلاعاتی به دست نیامد.\n\n"
                "<i>می‌توانید پس از پایان کول‌داون دوباره تلاش کنید.</i>"
            )

    await safe_edit(call, text, reply_markup=covert_menu_kb())

    # ---------- لاگ مدیریتی ----------
    status = "موفق" if result["success"] else "ناموفق"
    await send_log(
        bot,
        f"🔍 <b>عملیات جاسوسی — {status}</b>\n"
        f"جاسوس: {country.flag} {country.name_fa}\n"
        f"هدف: {target.flag} {target.name_fa} — {result['commander_name']}\n"
        + (f"کیفیت اطلاعات: {fa_number(result['quality'])}٪\n" if result["success"] else "")
        + (f"⚠️ عوامل لو رفتند\n" if result["detected"] else ""),
    )

    # ---------- اطلاع به کشور هدف در صورت لو رفتن ----------
    if result["detected"] and target.owner_user_id:
        try:
            await bot.send_message(
                target.owner_user_id,
                "🚨 <b>هشدار امنیتی</b>\n\n"
                "سرویس ضداطلاعات کشور شما فعالیت جاسوسی مشکوکی را شناسایی کرد.\n"
                f"هدف احتمالی: {commander.rank_title} {commander.name}\n\n"
                "<i>توصیه: گشت‌های امنیتی خود را تقویت کنید.</i>",
            )
        except Exception:  # noqa: BLE001
            pass


# ============================================================
#  🎯 عملیات ترور
# ============================================================
@router.callback_query(F.data == "assn:start")
async def cb_assn_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """شروع ترور: بررسی سقف عملیات و انتخاب کشور هدف."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "covert.assassination"):
        return

    try:
        await op_service.assert_can_operate(session, country)
    except op_service.OperationError as err:
        await safe_edit(call, str(err), reply_markup=covert_menu_kb())
        return

    await state.clear()
    await state.set_state(AssassinationForm.choosing_country)

    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id]
    rows = spy_service.target_rows(country, others)

    await safe_edit(
        call,
        header("عملیات ترور", "🎯") + "\n\n"
        "⚠️ <b>پیش‌نیاز:</b> ترور فرمانده فقط روی هدفی ممکن است که از قبل "
        "با عملیات جاسوسی شناسایی کرده باشید.\n\n"
        f"🕵️ رده‌ی اطلاعاتی شما: <b>{intel_power.tier_text(country.name_en)}</b>\n"
        f"{DIVIDER}\n"
        "🎯 <b>کشور هدف را انتخاب کنید:</b>\n"
        "<i>⛔️ یعنی توان اطلاعاتی شما برای عملیات در آن کشور کافی نیست.</i>",
        reply_markup=intel_targets_kb(rows, prefix="assn_country", back_data="op:covert"),
    )


@router.callback_query(F.data.startswith("assn_country_blocked:"))
async def cb_assn_blocked(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """راهنما وقتی بازیکن روی کشوری می‌زند که توان عملیات در آن را ندارد."""
    await call.answer()
    country = await get_player_country(session, db_user)
    target = await countries_repo.get_country(session, int(call.data.split(":")[1]))
    if country is None or target is None:
        return
    await safe_edit(
        call,
        intel_power.block_reason(
            country.name_en,
            target.name_en,
            spy_fa=country.name_fa,
            target_fa=f"{target.flag} {target.name_fa}",
        ),
        reply_markup=covert_menu_kb(),
    )


@router.callback_query(AssassinationForm.choosing_country, F.data.startswith("assn_country:"))
async def cb_assn_country(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """نمایش اهداف ممکن (فرماندهان شناسایی‌شده + رئیس‌جمهور)."""
    await call.answer()
    target_id = int(call.data.split(":")[1])

    country = await get_player_country(session, db_user)
    target = await countries_repo.get_country(session, target_id)
    if country is None or target is None:
        await safe_edit(call, "کشور هدف یافت نشد.", reply_markup=covert_menu_kb())
        return

    # (v2.1) اعتبارسنجی دوباره‌ی توان عملیات روی این کشور
    try:
        assn_service.assert_target_reachable(country, target)
    except assn_service.AssassinationError as err:
        await safe_edit(call, str(err), reply_markup=covert_menu_kb())
        return

    rows = await spy_service.targets_with_intel_status(session, country.id, target_id)
    ready = [r for r in rows if r["has_intel"] and r["quality"] >= ASSASSINATION_MIN_INTEL_QUALITY]

    await state.update_data(target_country_id=target_id)
    await state.set_state(AssassinationForm.choosing_target)

    lines = [
        header("انتخاب هدف ترور", "🎯"),
        "",
        f"کشور هدف: {target.flag} <b>{target.name_fa}</b>",
        DIVIDER,
    ]
    if ready:
        lines.append(f"✅ اهداف آماده: {fa_number(len(ready))} فرمانده شناسایی‌شده")
    else:
        lines.append("⚠️ هیچ فرمانده‌ای از این کشور شناسایی نشده است.")
        lines.append("<i>ابتدا عملیات جاسوسی اجرا کنید.</i>")
    lines.append("")
    lines.append("🔒 <i>اهداف قفل‌شده نیاز به جاسوسی دارند.</i>")

    await safe_edit(
        call,
        "\n".join(lines),
        reply_markup=commander_targets_kb(
            rows,
            prefix="assn_target",
            back_data="assn:start",
            require_intel=True,
            include_president=bool(target.owner_user_id),
        ),
    )


@router.callback_query(F.data == "assn:need_intel")
async def cb_assn_need_intel(call: CallbackQuery) -> None:
    """راهنما وقتی بازیکن روی هدف قفل‌شده می‌زند."""
    await call.answer(
        "🔒 برای ترور این فرمانده ابتدا باید با عملیات جاسوسی محل او را کشف کنید.",
        show_alert=True,
    )


@router.callback_query(AssassinationForm.choosing_target, F.data.startswith("assn_target:"))
async def cb_assn_target(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """تأیید نهایی ترور با نمایش شانس موفقیت."""
    await call.answer()
    raw = call.data.split(":")[1]

    country = await get_player_country(session, db_user)
    data = await state.get_data()
    target = await countries_repo.get_country(session, data.get("target_country_id", 0))
    if country is None or target is None:
        await safe_edit(call, "کشور هدف یافت نشد.", reply_markup=covert_menu_kb())
        return

    from ..constants import LEADERSHIP_CRISIS_HOURS

    intel_bonus = await assn_service.intel_bonus_for(session, country.id)

    if raw == "president":
        await state.update_data(target_president=True, commander_id=None)
        chance = assn_service.president_chance(country, target, intel_bonus)
        text = (
            header("تأیید ترور رئیس‌جمهور", "👤") + "\n\n"
            f"🎯 هدف: <b>رئیس‌جمهور {target.flag} {target.name_fa}</b>\n"
            f"{DIVIDER}\n"
            f"🕵️ رده‌ی شما: {intel_power.tier_text(country.name_en)}\n"
            f"🛡 رده‌ی هدف: {intel_power.tier_text(target.name_en)}\n"
            f"📊 شانس موفقیت: <b>{fa_number(chance, 1)}٪</b>\n\n"
            "⚠️ <b>هشدار جدی:</b>\n"
            "• شانس موفقیت بسیار پایین است\n"
            f"• در صورت موفقیت، کشور هدف {fa_number(LEADERSHIP_CRISIS_HOURS)} ساعت "
            "در «بحران رهبری» می‌ماند\n"
            "• شکست عملیات به‌احتمال زیاد افشا می‌شود و بحران دیپلماتیک می‌سازد\n"
            "• گشت امنیتی هدف می‌تواند عوامل را خنثی کند"
        )
    else:
        commander = await cmd_repo.get_commander(session, int(raw))
        if commander is None:
            await safe_edit(call, "فرمانده یافت نشد.", reply_markup=covert_menu_kb())
            return

        intel = await intel_repo.get_valid_intel(session, country.id, commander.id)
        if intel is None:
            await call.answer(
                "🔒 اطلاعات شما روی این هدف منقضی شده است. دوباره جاسوسی کنید.",
                show_alert=True,
            )
            return

        await state.update_data(target_president=False, commander_id=commander.id)

        chance = assn_service.commander_chance(
            country, target, intel.quality, intel_bonus
        )

        text = (
            header("تأیید عملیات ترور", "🎯") + "\n\n"
            f"🎯 هدف: <b>{commander.rank_title} {commander.name}</b>\n"
            f"🎖 سمت: {_role_fa(commander)}\n"
            f"🏴 کشور: {target.flag} {target.name_fa}\n"
            f"{DIVIDER}\n"
            f"📁 کیفیت اطلاعات: {spy_service.quality_label(intel.quality)} "
            f"({fa_number(intel.quality)}٪)\n"
            f"📍 محل شناسایی‌شده: {intel.known_location}\n"
            f"🕵️ رده‌ی شما: {intel_power.tier_text(country.name_en)} — "
            f"رده‌ی هدف: {intel_power.tier_text(target.name_en)}\n"
            f"📊 شانس موفقیت: <b>{fa_number(chance, 1)}٪</b>\n"
            f"{DIVIDER}\n"
            "⚠️ اطلاعات پس از این عملیات مصرف می‌شود (موفق یا ناموفق).\n"
            "<i>گشت امنیتی هدف می‌تواند عوامل را پیش از اجرا خنثی کند.</i>"
        )

    await state.set_state(AssassinationForm.confirming)
    await safe_edit(call, text, reply_markup=confirm_kb("assn_confirm", "op:covert"))


@router.callback_query(AssassinationForm.confirming, F.data == "assn_confirm")
async def cb_assn_confirm(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """اجرای عملیات ترور و انتشار نتیجه."""
    await call.answer()
    data = await state.get_data()
    await state.clear()

    country = await get_player_country(session, db_user)
    target = await countries_repo.get_country(session, data.get("target_country_id", 0))
    if country is None or target is None:
        await safe_edit(call, "خطا در اجرای عملیات.", reply_markup=covert_menu_kb())
        return

    target_president = bool(data.get("target_president"))
    commander = None
    if not target_president:
        commander = await cmd_repo.get_commander(session, data.get("commander_id", 0))
        if commander is None:
            await safe_edit(call, "فرمانده یافت نشد.", reply_markup=covert_menu_kb())
            return

    intel_bonus = await assn_service.intel_bonus_for(session, country.id)

    try:
        result = await assn_service.resolve_assassination(
            session,
            country,
            target,
            commander=commander,
            target_president=target_president,
            intel_bonus=intel_bonus,
        )
    except assn_service.AssassinationError as err:
        await safe_edit(call, f"⛔️ {err}", reply_markup=covert_menu_kb())
        return

    await session.commit()

    # ---------- گزارش به مهاجم ----------
    if result["detected"]:
        text = (
            header("عملیات خنثی شد", "🛡") + "\n\n"
            f"🎯 هدف: {result['target_label']}\n\n"
            f"{result['effect_note']}\n\n"
            "⚠️ هویت عوامل فاش شد و کشور شما هزینه‌ی دیپلماتیک پرداخت کرد."
        )
    elif result["success"]:
        text = (
            header("عملیات موفق", "✅") + "\n\n"
            f"🎯 هدف: <b>{result['target_label']}</b>\n"
            f"💀 عملیات با موفقیت اجرا شد.\n\n"
            f"{result['effect_note']}\n\n"
            + (
                "🚨 هویت شما افشا شد — منتظر واکنش بین‌المللی باشید."
                if result["exposed"]
                else "🤫 عملیات مخفی ماند و هویت شما فاش نشد."
            )
        )
    else:
        text = (
            header("عملیات ناموفق", "❌") + "\n\n"
            f"🎯 هدف: {result['target_label']}\n\n"
            f"{result['effect_note']}\n\n"
            + (
                "🚨 هویت عوامل فاش شد و بحران دیپلماتیک ایجاد شد."
                if result["exposed"]
                else "🤫 عوامل بدون شناسایی عقب‌نشینی کردند."
            )
        )

    await safe_edit(call, text, reply_markup=covert_menu_kb())

    # ---------- لاگ مدیریتی کامل ----------
    outcome = "خنثی‌شده" if result["detected"] else ("موفق" if result["success"] else "ناموفق")
    await send_log(
        bot,
        f"🎯 <b>عملیات ترور — {outcome}</b>\n"
        f"مهاجم: {country.flag} {country.name_fa}\n"
        f"کشور هدف: {target.flag} {target.name_fa}\n"
        f"هدف: {result['target_label']}\n"
        + (
            f"کیفیت اطلاعات: {fa_number(result['intel_quality'])}٪\n"
            if result.get("intel_quality")
            else ""
        )
        + f"افشا: {'بله' if result['exposed'] else 'خیر'}\n"
        f"{result['effect_note']}",
    )

    # ---------- اطلاع به کشور هدف ----------
    if target.owner_user_id:
        who = f"{country.flag} {country.name_fa}" if result["exposed"] else "🕵️ عوامل ناشناس"
        if result["detected"]:
            msg = (
                "🛡 <b>عملیات ترور خنثی شد</b>\n\n"
                f"سرویس امنیتی شما تلاش برای ترور «{result['target_label']}» را ناکام گذاشت.\n"
                f"عامل: {who}"
            )
        elif result["success"]:
            msg = (
                "🚨 <b>حمله‌ی تروریستی</b>\n\n"
                f"«{result['target_label']}» در یک عملیات ترور کشته شد.\n"
                f"عامل: {who}\n\n"
                f"{result['effect_note']}"
            )
        else:
            msg = (
                "⚠️ <b>تلاش ناموفق برای ترور</b>\n\n"
                f"تلاشی برای ترور «{result['target_label']}» صورت گرفت و ناکام ماند.\n"
                f"عامل: {who}"
            )
        try:
            await bot.send_message(target.owner_user_id, msg)
        except Exception:  # noqa: BLE001
            pass


@router.callback_query(F.data == "spy:files")
async def cb_spy_files(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """پرونده‌های اطلاعاتی معتبر کشور."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    rows = await intel_repo.list_all_valid(session, country.id)
    lines = [header("پرونده‌های اطلاعاتی", "📁"), ""]

    if not rows:
        lines.append("هیچ پرونده‌ی اطلاعاتی فعالی ندارید.")
        lines.append("\n<i>با عملیات جاسوسی می‌توانید فرماندهان دشمن را شناسایی کنید.</i>")
    else:
        for intel in rows:
            commander = await cmd_repo.get_commander(session, intel.commander_id)
            target = await countries_repo.get_country(session, intel.target_country_id)
            if commander is None or target is None:
                continue
            ready = "🎯 آماده‌ی ترور" if intel.quality >= ASSASSINATION_MIN_INTEL_QUALITY else "⚠️ ناکافی"
            lines.append(
                f"<b>{commander.rank_title} {commander.name}</b> — {target.flag} {target.name_fa}\n"
                f"   {_role_fa(commander)} | {spy_service.quality_label(intel.quality)} "
                f"({fa_number(intel.quality)}٪) | {ready}\n"
                f"   📍 {intel.known_location}"
            )

    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[:3900] + "\n…"
    await safe_edit(call, text, reply_markup=covert_menu_kb())
