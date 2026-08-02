"""
هندلر ستاد فرماندهی کل (v1.10.6).

منوهای اصلی بخش نظامی: وضعیت ارتش، دفاع و پدافند، اطلاعات، فرماندهان،
تاریخچه‌ی عملیات و صنایع نظامی.

ثبت خودِ عملیات‌ها در `handlers/operations.py` است.
"""

from __future__ import annotations

import json
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    DRILL_READINESS_MAX,
    OPERATION_LIMIT_PER_WINDOW,
    OPERATION_LIMIT_WINDOW_HOURS,
)
from ..database.models import User
from ..database.repositories import commanders as cmd_repo
from ..database.repositories import countries as countries_repo
from ..database.repositories import military as mil_repo
from ..database.repositories import operations as op_repo
from ..database.repositories import patrols as patrol_repo
from ..enums import (
    COMMANDER_ROLE_EMOJI,
    COMMANDER_ROLE_FA,
    OPERATION_EMOJI,
    OPERATION_FA,
    OPERATION_STATUS_FA,
    PATROL_EMOJI,
    PATROL_FA,
    TARGET_FA,
    CommanderRole,
    OperationStatus,
    OperationType,
    PatrolType,
    TargetType,
)
from ..keyboards.command_center import (
    command_center_kb,
    defense_menu_kb,
    industry_menu_kb,
    intel_menu_kb,
    operations_menu_kb,
)
from ..keyboards.common import back_kb
from ..utils.numbers import fa_number
from ..utils.screens import safe_edit, show_menu
from ..utils.ui import DIVIDER, STYLE_MAIN, header
from .deps import NO_COUNTRY_TEXT, get_player_country

logger = logging.getLogger(__name__)
router = Router(name="command_center")


def _op_label(operation_type: str) -> str:
    """برچسب فارسی + ایموجی یک نوع عملیات."""
    try:
        op = OperationType(operation_type)
        return f"{OPERATION_EMOJI[op]} {OPERATION_FA[op]}"
    except (ValueError, KeyError):
        return operation_type


def _status_label(status: str) -> str:
    try:
        return OPERATION_STATUS_FA[OperationStatus(status)]
    except (ValueError, KeyError):
        return status


# ============================================================
#  🎖 منوی اصلی ستاد فرماندهی
# ============================================================
@router.callback_query(F.data == "menu:military")
async def cb_command_center(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """منوی اصلی ستاد فرماندهی کل (عکس‌دار)."""
    await call.answer()
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    used = await op_repo.count_in_window(session, country.id, OPERATION_LIMIT_WINDOW_HOURS)
    active_patrols = await patrol_repo.count_active(session, country.id)
    readiness = float(getattr(country, "readiness", 0.0) or 0.0)

    text = (
        header("ستاد فرماندهی کل", "🎖") + "\n\n"
        f"🏴 کشور: {country.flag} <b>{country.name_fa}</b>\n"
        f"🎯 آمادگی رزمی: <b>{fa_number(readiness, 1)}</b> از {fa_number(DRILL_READINESS_MAX)}\n"
        f"⚔️ عملیات امروز: {fa_number(used)} از {fa_number(OPERATION_LIMIT_PER_WINDOW)}\n"
        f"🛩 گشت‌های فعال: {fa_number(active_patrols)}\n"
        f"{DIVIDER}\n"
        "بخش موردنظر را انتخاب کنید:"
    )
    await show_menu(call, text, command_center_kb(bool(country.is_vip)), image_key="military")


@router.callback_query(F.data == "cc:operations")
async def cb_operations_menu(call: CallbackQuery, state: FSMContext) -> None:
    """منوی انواع عملیات."""
    await call.answer()
    await state.clear()
    text = (
        header("عملیات‌ها", "⚔️") + "\n\n"
        "نوع عملیاتی که می‌خواهید اجرا کنید را انتخاب کنید.\n\n"
        "🔴 <b>حملات علنی</b> (زمینی/هوایی/دریایی) نیازمند <b>اعلام جنگ رسمی</b> هستند.\n"
        "🕵️ <b>عملیات مخفیانه</b> (خرابکاری/ترور/رهگیری) بدون اعلام جنگ ممکن‌اند، "
        "ولی در صورت افشا هزینه‌ی دیپلماتیک سنگینی دارند.\n"
        "🛩 <b>گشت و رزمایش</b> در سقف عملیات شمرده نمی‌شوند."
    )
    await safe_edit(call, text, reply_markup=operations_menu_kb())


# ============================================================
#  📊 وضعیت ارتش
# ============================================================
@router.callback_query(F.data == "cc:status")
async def cb_army_status(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """گزارش وضعیت کلی ارتش: خلاصه‌ی آمادگی/گشت + سرفصل شاخه‌ها."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    assets = await mil_repo.list_assets(session, country.id)
    by_branch: dict[str, list] = {}
    for asset in assets:
        if asset.count > 0:
            by_branch.setdefault(asset.branch or "سایر", []).append(asset)

    readiness = float(getattr(country, "readiness", 0.0) or 0.0)
    lines = [
        header("وضعیت ارتش", "📊"),
        "",
        f"🏴 {country.flag} <b>{country.name_fa}</b>",
        f"🎯 آمادگی رزمی: <b>{fa_number(readiness, 1)}</b> از {fa_number(DRILL_READINESS_MAX)}",
    ]

    patrols = await patrol_repo.list_active(session, country.id)
    if patrols:
        labels = []
        for patrol in patrols:
            try:
                ptype = PatrolType(patrol.patrol_type)
                labels.append(f"{PATROL_EMOJI[ptype]} {PATROL_FA[ptype]}")
            except (ValueError, KeyError):
                labels.append(patrol.patrol_type)
        lines.append(f"🛩 گشت فعال: {'، '.join(labels)}")

    lines.append(DIVIDER)

    if not by_branch:
        lines.append("⚠️ کشور شما تجهیزات نظامی ثبت‌شده‌ای ندارد.")
    else:
        # (v1.11.1) اینجا فقط خلاصه‌ی هر شاخه می‌آید؛ فهرست کامل قلم‌به‌قلم در
        # «گزارش تجهیزات» با صفحه‌بندی زیربخش‌ها نمایش داده می‌شود.
        for branch, items in by_branch.items():
            total = sum(a.count for a in items)
            lines.append(
                f"\n<b>{branch}</b> — {fa_number(total)} واحد "
                f"({fa_number(len(items))} قلم)"
            )
            for asset in items[:6]:
                lines.append(f"  • {asset.name}: {fa_number(asset.count)} {asset.unit}")
            if len(items) > 6:
                lines.append(f"  <i>… و {fa_number(len(items) - 6)} قلم دیگر</i>")
        lines.append("")
        lines.append(DIVIDER)
        lines.append("📄 برای فهرست کامل، «گزارش تجهیزات» را باز کنید.")

    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[:3900] + "\n…"

    builder = InlineKeyboardBuilder()
    builder.button(text="⚔️ گزارش کامل تجهیزات", callback_data="mil:report", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="menu:military", style=STYLE_MAIN)
    builder.adjust(1)
    await safe_edit(call, text, reply_markup=builder.as_markup())


# ============================================================
#  🛡 دفاع و پدافند
# ============================================================
@router.callback_query(F.data == "cc:defense")
async def cb_defense_menu(call: CallbackQuery) -> None:
    """منوی دفاع و پدافند."""
    await call.answer()
    text = (
        header("دفاع و پدافند", "🛡") + "\n\n"
        "از این بخش می‌توانید آرایش پدافندی کشور را ببینید، گشت‌های فعال را "
        "مدیریت کنید و تهدیدهای اخیر علیه کشورتان را بررسی کنید."
    )
    await safe_edit(call, text, reply_markup=defense_menu_kb())


@router.callback_query(F.data == "cc:def_layout")
async def cb_defense_layout(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """نمایش سامانه‌های پدافندی کشور و بونوس‌های دفاعی فعال."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    from ..constants import BASE_DEFENSE_BONUS_MAX_PCT, BASE_DEFENSE_BONUS_PCT, PATROL_DEFENSE_BONUS_PCT
    from ..services.combat.power import CommittedAsset, defense_power

    assets = await mil_repo.list_assets(session, country.id)
    committed = [
        CommittedAsset(name=a.name, count=a.count, branch=a.branch, category=a.category, unit=a.unit)
        for a in assets
        if a.count > 0
    ]

    lines = [header("آرایش پدافندی", "🛡"), ""]

    # قدرت پدافندی در برابر هر نوع تهدید
    for op in (OperationType.AIR_STRIKE, OperationType.GROUND_ASSAULT, OperationType.NAVAL_STRIKE):
        breakdown = defense_power(committed, op)
        top = breakdown.top_assets(3)
        lines.append(
            f"{OPERATION_EMOJI[op]} برابر {OPERATION_FA[op]}: "
            f"<b>{fa_number(breakdown.total, 0)}</b> امتیاز"
        )
        if top:
            lines.append(f"   ستون اصلی: {'، '.join(top)}")

    lines.append(DIVIDER)

    # بونوس‌های فعال
    active_types = await patrol_repo.active_types(session, country.id)
    if active_types:
        lines.append(f"🛩 بونوس گشت فعال: <b>+{fa_number(PATROL_DEFENSE_BONUS_PCT)}٪</b> رهگیری")
    try:
        from ..database.repositories import military_bases as base_repo

        hosted = await base_repo.list_bases_by_host(session, country.id)
        own = sum(1 for b in hosted if b.owner_country_id == country.id)
        if own:
            bonus = min(own * BASE_DEFENSE_BONUS_PCT, BASE_DEFENSE_BONUS_MAX_PCT)
            lines.append(
                f"🏗 بونوس {fa_number(own)} پایگاه داخلی: <b>+{fa_number(bonus)}٪</b> رهگیری"
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("base bonus display failed: %s", exc)

    lines.append(
        "\n<i>نکته: گشت فعال و پایگاه‌های داخلی مستقیماً درصد رهگیری پدافند شما را بالا می‌برند.</i>"
    )
    await safe_edit(call, "\n".join(lines), reply_markup=defense_menu_kb())


@router.callback_query(F.data == "cc:threats")
async def cb_threat_report(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """گزارش عملیات‌های اخیر علیه کشور."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    threats = await op_repo.list_recent_against(session, country.id, hours=48)
    lines = [header("گزارش تهدید (۴۸ ساعت اخیر)", "⚠️"), ""]

    if not threats:
        lines.append("✅ در ۴۸ ساعت گذشته عملیاتی علیه کشور شما ثبت نشده است.")
    else:
        for op in threats[:10]:
            attacker = await countries_repo.get_country(session, op.attacker_country_id)
            # عملیات مخفیانه‌ی افشانشده، مهاجمش را لو نمی‌دهد
            if not op.claim_responsibility and not op.is_exposed:
                who = "🕵️ <i>عوامل ناشناس</i>"
            else:
                who = f"{attacker.flag} {attacker.name_fa}" if attacker else "نامشخص"

            try:
                target_fa = TARGET_FA[TargetType(op.target_type)]
            except (ValueError, KeyError):
                target_fa = op.target_type

            lines.append(
                f"• {_op_label(op.operation_type)} از سوی {who}\n"
                f"   🎯 هدف: {target_fa} | 💥 خسارت: {fa_number(op.infra_damage_pct, 1)}٪ "
                f"| 🛡 رهگیری: {fa_number(op.intercept_pct, 1)}٪\n"
                f"   وضعیت: {_status_label(op.status)}"
            )

    await safe_edit(call, "\n".join(lines), reply_markup=defense_menu_kb())


# ============================================================
#  🎯 اطلاعات و شناسایی
# ============================================================
@router.callback_query(F.data == "cc:intel")
async def cb_intel_menu(call: CallbackQuery) -> None:
    """منوی اطلاعات و شناسایی."""
    await call.answer()
    text = (
        header("اطلاعات و شناسایی", "🎯") + "\n\n"
        "پیش از هر عملیات، شناسایی هدف شانس موفقیت را بالا می‌برد.\n"
        "از ماهواره‌ی جاسوسی برای رصد پایگاه‌ها و نیروهای دشمن استفاده کنید."
    )
    await safe_edit(call, text, reply_markup=intel_menu_kb())


# ============================================================
#  🎖 فرماندهان
# ============================================================
@router.callback_query(F.data == "cc:commanders")
async def cb_commanders(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """فهرست فرماندهان کشور و بونوس‌هایشان."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    commanders = await cmd_repo.list_commanders(session, country.id)
    lines = [header("فرماندهان ارشد", "🎖"), ""]

    if not commanders:
        lines.append(
            "⚠️ فرماندهی برای کشور شما ثبت نشده است.\n"
            "<i>مدیریت بازی می‌تواند با اجرای seed فرماندهان را ایجاد کند.</i>"
        )
    else:
        for commander in commanders:
            try:
                role = CommanderRole(commander.role)
                role_fa = COMMANDER_ROLE_FA[role]
                emoji = COMMANDER_ROLE_EMOJI[role]
            except (ValueError, KeyError):
                role_fa, emoji = commander.role, "🎖"

            if commander.is_alive:
                status = f"🟢 فعال — بونوس <b>+{fa_number(commander.bonus_pct)}٪</b>"
            else:
                status = "🔴 ترورشده — در انتظار انتصاب جانشین"

            lines.append(
                f"{emoji} <b>{commander.rank_title} {commander.name}</b>\n"
                f"   {role_fa}\n   {status}"
            )

        alive = sum(1 for c in commanders if c.is_alive)
        lines.append(DIVIDER)
        lines.append(f"👥 فرماندهان فعال: {fa_number(alive)} از {fa_number(len(commanders))}")
        lines.append(
            "\n<i>هر فرمانده به شاخه‌ی تخصصی خودش بونوس قدرت می‌دهد. "
            "ترور فرمانده این بونوس را تا انتصاب جانشین از بین می‌برد.</i>"
        )

    await safe_edit(call, "\n".join(lines), reply_markup=back_kb("menu:military"))


# ============================================================
#  📜 تاریخچه‌ی عملیات
# ============================================================
@router.callback_query(F.data == "cc:history")
async def cb_history(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """تاریخچه‌ی عملیات کشور (به‌عنوان مهاجم یا مدافع)."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    operations = await op_repo.list_for_country(session, country.id, limit=12)
    lines = [header("تاریخچه عملیات", "📜"), ""]

    if not operations:
        lines.append("هنوز عملیاتی ثبت نشده است.")
    else:
        for op in operations:
            is_attacker = op.attacker_country_id == country.id
            other_id = op.defender_country_id if is_attacker else op.attacker_country_id
            other = await countries_repo.get_country(session, other_id)
            other_name = f"{other.flag} {other.name_fa}" if other else "نامشخص"
            arrow = "➡️" if is_attacker else "⬅️"

            lines.append(
                f"{arrow} {_op_label(op.operation_type)} "
                f"{'علیه' if is_attacker else 'از سوی'} {other_name}\n"
                f"   {_status_label(op.status)} | شدت {fa_number(op.intensity)}/۱۰"
                + (f" | 💥 {fa_number(op.infra_damage_pct, 1)}٪" if op.infra_damage_pct else "")
                + (f"\n   🏆 {op.outcome}" if op.outcome else "")
            )

    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[:3900] + "\n…"
    await safe_edit(call, text, reply_markup=back_kb("menu:military"))


# ============================================================
#  🏭 صنایع نظامی
# ============================================================
@router.callback_query(F.data == "cc:industry")
async def cb_industry_menu(call: CallbackQuery) -> None:
    """منوی صنایع نظامی (پل به سیستم‌های موجود)."""
    await call.answer()
    text = (
        header("صنایع نظامی", "🏭") + "\n\n"
        "تولید، فروش و استقرار تجهیزات نظامی کشور."
    )
    await safe_edit(call, text, reply_markup=industry_menu_kb())
