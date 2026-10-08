"""
هندلر ستاد فرماندهی کل.

منوهای اصلی بخش نظامی: وضعیت ارتش، ماهواره فضایی، پایگاه‌ها، فرماندهان و صنایع نظامی.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import User
from ..database.repositories import commanders as cmd_repo
from ..database.repositories import military as mil_repo
from ..enums import (
    COMMANDER_ROLE_EMOJI,
    COMMANDER_ROLE_FA,
    CommanderRole,
)
from ..keyboards.command_center import (
    command_center_kb,
    industry_menu_kb,
)
from ..keyboards.common import back_kb
from ..utils.numbers import fa_number
from ..utils.screens import safe_edit, show_menu
from ..utils.ui import DIVIDER, STYLE_MAIN, header
from .deps import NO_COUNTRY_TEXT, get_player_country

logger = logging.getLogger(__name__)
router = Router(name="command_center")


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

    text = (
        header("ستاد فرماندهی کل", "🎖") + "\n\n"
        f"🏴 کشور: {country.flag} <b>{country.name_fa}</b>\n"
        f"{DIVIDER}\n"
        "بخش موردنظر را انتخاب کنید:"
    )
    await show_menu(call, text, command_center_kb(bool(country.is_vip)), image_key="military")


# ============================================================
#  📊 وضعیت ارتش
# ============================================================
@router.callback_query(F.data == "cc:status")
async def cb_army_status(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """گزارش وضعیت کلی ارتش: سرفصل شاخه‌ها و تجهیزات."""
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

    lines = [
        header("وضعیت ارتش", "📊"),
        "",
        f"🏴 {country.flag} <b>{country.name_fa}</b>",
        DIVIDER,
    ]

    if not by_branch:
        lines.append("⚠️ کشور شما تجهیزات نظامی ثبت‌شده‌ای ندارد.")
    else:
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
#  🎖 فرماندهان
# ============================================================
@router.callback_query(F.data == "cc:commanders")
async def cb_commanders(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """فهرست فرماندهان ارشد کشور و بونوس‌هایشان."""
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

            status = f"🟢 فعال — بونوس <b>+{fa_number(commander.bonus_pct)}٪</b>"

            lines.append(
                f"{emoji} <b>{commander.rank_title} {commander.name}</b>\n"
                f"   {role_fa}\n   {status}"
            )

        lines.append(DIVIDER)
        lines.append(f"👥 فرماندهان فعال: {fa_number(len(commanders))} نفر")
        lines.append(
            "\n<i>هر فرمانده به شاخه‌ی تخصصی خودش بونوس قدرت می‌دهد.</i>"
        )

    await safe_edit(call, "\n".join(lines), reply_markup=back_kb("menu:military"))


# ============================================================
#  🏭 صنایع نظامی
# ============================================================
@router.callback_query(F.data == "cc:industry")
async def cb_industry_menu(call: CallbackQuery) -> None:
    """منوی صنایع نظامی."""
    await call.answer()
    text = (
        header("صنایع نظامی", "🏭") + "\n\n"
        "تولید، فروش و استقرار تجهیزات نظامی کشور."
    )
    await safe_edit(call, text, reply_markup=industry_menu_kb())

