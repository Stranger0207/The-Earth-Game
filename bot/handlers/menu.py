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
from .deps import NO_COUNTRY_TEXT, get_player_country

router = Router(name="menu")


@router.callback_query(F.data == "menu:main")
async def cb_main(call: CallbackQuery, state: FSMContext) -> None:
    """بازگشت به پنل اصلی."""
    await state.clear()
    await call.answer()
    await call.message.edit_text("پنل مدیریت کشور:", reply_markup=main_menu_kb())


@router.callback_query(F.data == "menu:economy")
async def cb_economy(call: CallbackQuery) -> None:
    await call.answer()
    await call.message.edit_text("📊 <b>بخش اقتصاد</b>", reply_markup=economy_menu_kb())


@router.callback_query(F.data == "menu:diplomacy")
async def cb_diplomacy(call: CallbackQuery) -> None:
    await call.answer()
    await call.message.edit_text("🤝 <b>بخش دیپلماسی</b>", reply_markup=diplomacy_menu_kb())


@router.callback_query(F.data == "menu:military")
async def cb_military(call: CallbackQuery) -> None:
    await call.answer()
    await call.message.edit_text("⚔️ <b>بخش نظامی</b>", reply_markup=military_menu_kb())


@router.callback_query(F.data == "menu:status")
async def cb_status(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """نمایش خلاصه‌ی وضعیت کشور (اقتصاد + رضایت عمومی)."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    await call.message.edit_text(
        render_economy_panel(country), reply_markup=main_menu_kb()
    )


@router.callback_query(F.data == "cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext) -> None:
    """لغو فرایند جاری و بازگشت به پنل."""
    await state.clear()
    await call.answer("لغو شد")
    await call.message.edit_text("پنل مدیریت کشور:", reply_markup=main_menu_kb())
