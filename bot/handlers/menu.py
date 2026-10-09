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
from ..utils.formatting import render_economy_panel
from ..utils.screens import safe_edit, show_menu
from ..utils.ui import header
from .deps import NO_COUNTRY_TEXT, get_player_country

router = Router(name="menu")

# سربرگ پنل اصلی (در چند نقطه استفاده می‌شود)
PANEL_TITLE = header("پنل مدیریت کشور", "🌍")


@router.callback_query(F.data == "menu:main")
async def cb_main(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """بازگشت به پنل اصلی (کشوری یا مقاماتی)."""
    await state.clear()
    await call.answer()
    if getattr(db_user, "active_gamemode", "global") == "cabinet":
        from ..config import get_settings
        if not get_settings().is_admin(db_user.telegram_id):
            db_user.active_gamemode = "global"
            await session.commit()
            await call.answer(
                "دسترسی به این گیم مود توسط تیم مدیریت کره زمین بسته شده. لطفا گیم مود دیگری را امتحان کنید.",
                show_alert=True,
            )
        else:
            from ..database.repositories import cabinet as cabinet_repo
            from ..keyboards.cabinet import cabinet_main_menu_kb, cabinet_roles_list_kb
            from ..services.cabinet_service import render_official_profile

            member = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
            if member is not None:
                await safe_edit(
                    call,
                    render_official_profile(member.role_key, db_user.first_name),
                    reply_markup=cabinet_main_menu_kb(member.role_key),
                )
            else:
                members = await cabinet_repo.list_members(session)
                await safe_edit(
                    call,
                    "🏛 <b>دولت فدرال ایالات متحده آمریکا (گیم‌مود مقاماتی)</b>\n\n"
                    "شما سمتی در دولت ندارید. لطفاً یک سمت خالی را انتخاب کنید:",
                    reply_markup=cabinet_roles_list_kb(members, db_user.telegram_id),
                )
            return

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


# توجه (v1.10.6): «menu:military» اکنون در handlers/command_center.py مدیریت می‌شود
# (ستاد فرماندهی کل). هندلر قدیمی اینجا حذف شد تا تضاد ثبت روتر پیش نیاید.


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
