"""هندلر انتخاب و جابه‌جایی بین حالت‌های بازی (/gamemode)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import User
from ..database.repositories import cabinet as cabinet_repo
from ..keyboards.cabinet import cabinet_main_menu_kb, cabinet_roles_list_kb, gamemode_selection_kb
from ..keyboards.menu import main_menu_kb
from ..services.cabinet_service import render_official_profile
from ..utils.screens import safe_edit, show_menu
from ..utils.ui import header
from .deps import get_player_country

router = Router(name="gamemode")

GAMEMODE_EXPLANATION = (
    "🎮 <b>انتخاب حالت بازی (Game Mode)</b>\n\n"
    "در بازی کره زمین دو گیم‌مود اصلی وجود دارد:\n\n"
    "🌍 <b>۱. کشوری جهانی (کلاسیک):</b>\n"
    "مدیریت یک کشور مستقل در عرصه بین‌الملل، ساخت و ساز اقتصادی، دیپلماسی جهانی، "
    "تولید تسلیحات و رقابت میان کشورهای جهان.\n\n"
    "🏛 <b>۲. کشوری مقاماتی (دولت فدرال ایالات متحده آمریکا):</b>\n"
    "کل بازی درون ساختار قدرت یک ابرقدرت (آمریکا) تعریف می‌شود. شما در نقش یکی از "
    "<b>۱۵ مقام ارشد کاخ سفید، پنتاگون، سیا، خزانه‌داری، دادگستری، ستاد مشترک و...</b> "
    "قرار می‌گیرید و بازی تیمی/سیاسی را در قالب دولت فدرال پیش می‌برید.\n\n"
    "حالت بازی مورد نظر خود را انتخاب کنید:"
)


@router.message(Command("gamemode"))
async def cmd_gamemode(
    message: Message, state: FSMContext, db_user: User
) -> None:
    """دستور /gamemode برای مشاهده و تغییر حالت بازی."""
    await state.clear()
    current_mode = getattr(db_user, "active_gamemode", "global")
    await message.answer(
        GAMEMODE_EXPLANATION,
        reply_markup=gamemode_selection_kb(current_mode),
    )


@router.callback_query(F.data == "gamemode:menu")
async def cb_gamemode_menu(
    call: CallbackQuery, state: FSMContext, db_user: User
) -> None:
    """نمایش منوی تغییر گیم‌مود از دکمه‌ها."""
    await state.clear()
    await call.answer()
    current_mode = getattr(db_user, "active_gamemode", "global")
    await safe_edit(
        call,
        GAMEMODE_EXPLANATION,
        reply_markup=gamemode_selection_kb(current_mode),
    )


@router.callback_query(F.data == "gamemode:set:global")
async def cb_set_global(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """تغییر حالت به کشوری جهانی."""
    await call.answer("حالت بازی به کشوری جهانی تغییر یافت ✅")
    db_user.active_gamemode = "global"
    await session.commit()

    country = await get_player_country(session, db_user)
    if country is not None:
        await show_menu(
            call,
            f"🌍 <b>حالت بازی: کشوری جهانی</b>\n\n"
            f"👑 رهبر {country.flag} <b>{country.name_fa}</b>، پنل مدیریت کشور شما:",
            main_menu_kb(),
            image_key="main",
        )
    else:
        from ..keyboards.menu import main_menu_kb
        await safe_edit(
            call,
            "🌍 <b>حالت بازی: کشوری جهانی</b>\n\n"
            "شما هم‌اکنون در حالت جهانی هستید، اما هنوز کشوری در اختیار ندارید.\n"
            "برای شروع کشورگیری از دستور /claim یا دکمه‌ی زیر استفاده کنید.",
            reply_markup=gamemode_selection_kb("global"),
        )


@router.callback_query(F.data == "gamemode:set:cabinet")
async def cb_set_cabinet(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """تغییر حالت به کشوری مقاماتی (دولت فدرال آمریکا)."""
    from ..config import get_settings

    if not get_settings().is_admin(call.from_user.id):
        await call.answer(
            "دسترسی به این گیم مود توسط تیم مدیریت کره زمین بسته شده. لطفا گیم مود دیگری را امتحان کنید.",
            show_alert=True,
        )
        return

    await call.answer("حالت بازی به کشوری مقاماتی تغییر یافت ✅")
    db_user.active_gamemode = "cabinet"
    await session.commit()

    # بررسی اینکه آیا کاربر مقامی در کابینه دارد
    member = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if member is not None:
        profile_text = render_official_profile(member.role_key, db_user.first_name)
        await safe_edit(
            call,
            profile_text,
            reply_markup=cabinet_main_menu_kb(member.role_key),
        )
    else:
        members = await cabinet_repo.list_members(session)
        text = (
            "🏛 <b>دولت فدرال ایالات متحده آمریکا (گیم‌مود مقاماتی)</b>\n\n"
            "شما هم‌اکنون سمتی در دولت ندارید.\n"
            "یکی از سمت‌های خالی (🟢) زیر را برای تصدی انتخاب کنید:"
        )
        await safe_edit(
            call,
            text,
            reply_markup=cabinet_roles_list_kb(members, db_user.telegram_id),
        )
