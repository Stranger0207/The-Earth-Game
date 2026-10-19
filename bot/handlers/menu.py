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
from ..services import geo_service as geo
from ..utils.formatting import render_economy_panel
from ..utils.screens import safe_edit, show_menu
from ..utils.ui import header
from .deps import NO_COUNTRY_TEXT, assert_feature, check_hall_lock, get_player_country

router = Router(name="menu")

# سربرگ پنل اصلی (در چند نقطه استفاده می‌شود)
PANEL_TITLE = header("پنل مدیریت کشور", "🌍")


@router.callback_query(F.data == "menu:main")
async def cb_main(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """بازگشت به پنل اصلی (تشخیص ویژه سازمان ملل و قفل تالار)."""
    await state.clear()
    await call.answer()
    country = await get_player_country(session, db_user)

    # اگر کاربر دبیرکل سازمان ملل باشد، پنل اختصاصی دبیرکل باز می‌شود
    if country and country.name_en == "UN":
        from ..keyboards.united_nations import un_main_menu_kb
        un_title = header("مقر فرماندهی دبیرکل سازمان ملل متحد", "🇺🇳") + "\n\nدبیرکل محترم، ارکان سازمان ملل متحد در خدمت شماست."
        await show_menu(call, un_title, un_main_menu_kb(), image_key="main")
        return

    # بررسی قفل تالار مجمع عمومی
    if await check_hall_lock(call, session, country):
        return

    await show_menu(call, PANEL_TITLE, main_menu_kb(), image_key="main")


@router.callback_query(F.data == "menu:economy")
async def cb_economy(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    country = await get_player_country(session, db_user)
    if await check_hall_lock(call, session, country):
        return
    await call.answer()
    is_usa = country is not None and country.name_en == "USA"
    has_straits = bool(country and geo.get_straits_for_country(country.name_en))
    await show_menu(
        call,
        header("بخش اقتصاد", "💰"),
        economy_menu_kb(is_usa=is_usa, has_straits=has_straits),
        image_key="economy",
    )


@router.callback_query(F.data == "menu:diplomacy")
async def cb_diplomacy(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    country = await get_player_country(session, db_user)
    if await check_hall_lock(call, session, country):
        return
    await call.answer()
    await show_menu(call, header("بخش دیپلماسی", "🤝"), diplomacy_menu_kb(), image_key="diplomacy")


# توجه (v1.10.6): «menu:military» اکنون در handlers/command_center.py مدیریت می‌شود
# (ستاد فرماندهی کل). هندلر قدیمی اینجا حذف شد تا تضاد ثبت روتر پیش نیاید.


@router.callback_query(F.data == "menu:status")
async def cb_status(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """نمایش خلاصه‌ی وضعیت کشور (اقتصاد + رضایت عمومی)."""
    country = await get_player_country(session, db_user)
    if await check_hall_lock(call, session, country):
        return
    await call.answer()
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    await show_menu(call, render_economy_panel(country), main_menu_kb(), image_key="status")


@router.callback_query(F.data == "menu:radar_info")
async def cb_radar_info(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """نمایش راهنمای رادار زنده در صورت عدم تنظیم آدرس مینی‌اپ."""
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "live_radar_map"):
        return

    text = (
        "🛰 <b>سامانه رادار زنده استراتژیک جهان (Live Strategic Radar)</b>\n\n"
        "این سامانه یک مینی‌اپ تلگرامی با نقشه تعاملی و نظامی است که موقعیت و حرکت لحظه‌ای "
        "پروازهای دیپلماتیک، کشتی‌های تجاری/سوخت، هواپیماهای ترابری WTO و وضعیت ۱۴ تنگه استراتژیک جهان را نمایش می‌دهد.\n\n"
        "⚙️ <b>وضعیت اتصال:</b>\n"
        "آدرس وب‌اپلیکیشن (<code>WEBAPP_BASE_URL</code>) در تنظیمات سرور ثبت نشده است. "
        "با راه‌اندازی Ngrok یا ثبت آدرس معتبر HTTPS در فایل <code>.env</code>، این کلید مستقیماً نقشه زنده را باز خواهد کرد."
    )
    await call.answer()
    await safe_edit(call, text, reply_markup=main_menu_kb())


@router.callback_query(F.data == "cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext) -> None:
    """لغو فرایند جاری و بازگشت به پنل."""
    await state.clear()
    await call.answer("لغو شد")
    await show_menu(call, PANEL_TITLE, main_menu_kb(), image_key="main")

