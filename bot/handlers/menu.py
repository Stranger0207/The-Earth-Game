"""هندلر پنل اصلی و ناوبری بین بخش‌ها."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import User
from ..database.repositories import reserves as reserves_repo
from ..keyboards.diplomacy import diplomacy_menu_kb
from ..keyboards.economy import economy_menu_kb
from ..keyboards.menu import main_menu_kb
from ..keyboards.military import military_menu_kb
from ..utils.formatting import render_economy_panel
from ..utils.screens import safe_edit, show_menu
from ..utils.ui import header
from .deps import NO_COUNTRY_TEXT, get_player_country

router = Router(name="menu")

# سربرگ پنل اصلی (در چند نقطه استفاده می‌شود)
PANEL_TITLE = header("پنل مدیریت کشور", "🌍")


@router.callback_query(F.data == "menu:main")
async def cb_main(call: CallbackQuery, state: FSMContext) -> None:
    """بازگشت به پنل اصلی."""
    await state.clear()
    await call.answer()
    await show_menu(call, PANEL_TITLE, main_menu_kb(), image_key="main")


@router.callback_query(F.data == "menu:economy")
async def cb_economy(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    is_usa = country is not None and country.name_en == "USA"
    await show_menu(
        call, header("بخش اقتصاد", "💰"), economy_menu_kb(is_usa=is_usa), image_key="economy"
    )


@router.callback_query(F.data == "menu:diplomacy")
async def cb_diplomacy(call: CallbackQuery) -> None:
    await call.answer()
    await show_menu(call, header("بخش دیپلماسی", "🤝"), diplomacy_menu_kb(), image_key="diplomacy")


@router.callback_query(F.data == "menu:military")
async def cb_military(call: CallbackQuery) -> None:
    await call.answer()
    await show_menu(call, header("بخش نظامی", "⚔️"), military_menu_kb(), image_key="military")


@router.callback_query(F.data == "menu:status")
async def cb_status(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """نمایش خلاصه‌ی وضعیت کشور (اقتصاد + رضایت عمومی)."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    await show_menu(call, render_economy_panel(country), main_menu_kb(), image_key="status")


@router.callback_query(F.data == "cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext) -> None:
    """لغو فرایند جاری و بازگشت به پنل."""
    await state.clear()
    await call.answer("لغو شد")
    await show_menu(call, PANEL_TITLE, main_menu_kb(), image_key="main")
