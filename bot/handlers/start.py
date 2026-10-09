"""هندلر شروع: /start و معرفی بازی."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import User
from ..keyboards.menu import main_menu_kb
from ..states import SpeechForm
from ..utils.screens import show_menu
from .deps import get_player_country

router = Router(name="start")

WELCOME_TEXT = (
    "🌍 <b>به بازی کره زمین خوش آمدید!</b>\n\n"
    "اینجا شما رهبر یک کشور هستید و باید آن را در سه محور "
    "<b>اقتصاد</b>، <b>دیپلماسی</b> و <b>نظامی</b> مدیریت کنید.\n"
    "سال بازی: ۲۰۲۶ | هدف: کشورتان را به قدرتمندترین کشور جهان تبدیل کنید.\n\n"
    "برای شروع باید یک کشور انتخاب کنید."
)


def _claim_kb() -> InlineKeyboardMarkup:
    """کیبورد دعوت به کشورگیری."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌍 کشورگیری", callback_data="claim:start", style="primary")]
        ]
    )


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    command: CommandObject,
) -> None:
    """پاسخ به /start: اگر کاربر کشور دارد پنل، در غیر این صورت دعوت به کشورگیری."""
    await state.clear()

    # deep-link نقل قول سخنرانی: /start quote_<speech_id>  (v1.5)
    if command.args and command.args.startswith("quote_"):
        try:
            speech_id = int(command.args.split("_", 1)[1])
        except (ValueError, IndexError):
            speech_id = None
        if speech_id is not None:
            country = await get_player_country(session, db_user)
            if country is None:
                await message.answer(
                    "برای نقل قول باید رهبر یک کشور باشید. ابتدا کشورگیری کنید. /claim"
                )
                return
            # کشور نمی‌تواند روی بیانیه‌ی خودش نقل قول بزند (v1.8)
            from ..database.models import Speech

            speech = await session.get(Speech, speech_id)
            if speech is not None and speech.speaker_country == country.id:
                await message.answer("روی حرف خودت میخوای نقل قول کنی؟ دیوانه ای؟ 😅")
                return
            await state.set_state(SpeechForm.quoting)
            await state.update_data(quote_speech_id=speech_id)
            await message.answer("💬 متن نقل قول خود را بنویسید:")
            return

    # deep-link مزایده منابع طبیعی: /start auc_<auction_id> (v2.2)
    if command.args and command.args.startswith("auc_"):
        try:
            auc_id = int(command.args.split("_", 1)[1])
        except (ValueError, IndexError):
            auc_id = None
        if auc_id is not None:
            from .auction import show_auction_details

            await show_auction_details(message, session, db_user, auc_id)
            return

    if getattr(db_user, "active_gamemode", "global") == "cabinet":
        from ..config import get_settings
        if not get_settings().is_admin(db_user.telegram_id):
            db_user.active_gamemode = "global"
            await session.commit()
            await message.answer(
                "دسترسی به این گیم مود توسط تیم مدیریت کره زمین بسته شده. لطفا گیم مود دیگری را امتحان کنید."
            )
        else:
            from ..database.repositories import cabinet as cabinet_repo
            from ..keyboards.cabinet import cabinet_main_menu_kb, cabinet_roles_list_kb
            from ..services.cabinet_service import render_official_profile

            member = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
            if member is not None:
                await message.answer(
                    render_official_profile(member.role_key, db_user.first_name),
                    reply_markup=cabinet_main_menu_kb(member.role_key),
                )
            else:
                members = await cabinet_repo.list_members(session)
                await message.answer(
                    "🏛 <b>دولت فدرال ایالات متحده آمریکا (گیم‌مود مقاماتی)</b>\n\n"
                    "شما سمتی در دولت ندارید. لطفاً یک سمت خالی را انتخاب کنید:",
                    reply_markup=cabinet_roles_list_kb(members, db_user.telegram_id),
                )
            return

    country = await get_player_country(session, db_user)
    if country is not None:
        await show_menu(
            message,
            f"👑 خوش آمدید، رهبر {country.flag} <b>{country.name_fa}</b>!\n\n"
            "پنل مدیریت کشور:",
            main_menu_kb(),
            image_key="main",
        )
    else:
        await message.answer(WELCOME_TEXT, reply_markup=_claim_kb())


@router.message(F.text == "/menu")
async def cmd_menu(
    message: Message,
    session: AsyncSession,
    db_user: User,
) -> None:
    """نمایش پنل اصلی (در صورت داشتن کشور یا سمت در کابینه)."""
    if getattr(db_user, "active_gamemode", "global") == "cabinet":
        from ..config import get_settings
        if not get_settings().is_admin(db_user.telegram_id):
            db_user.active_gamemode = "global"
            await session.commit()
            await message.answer(
                "دسترسی به این گیم مود توسط تیم مدیریت کره زمین بسته شده. لطفا گیم مود دیگری را امتحان کنید."
            )
        else:
            from ..database.repositories import cabinet as cabinet_repo
            from ..keyboards.cabinet import cabinet_main_menu_kb, cabinet_roles_list_kb
            from ..services.cabinet_service import render_official_profile

            member = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
            if member is not None:
                await message.answer(
                    render_official_profile(member.role_key, db_user.first_name),
                    reply_markup=cabinet_main_menu_kb(member.role_key),
                )
            else:
                members = await cabinet_repo.list_members(session)
                await message.answer(
                    "🏛 <b>دولت فدرال ایالات متحده آمریکا (گیم‌مود مقاماتی)</b>\n\n"
                    "شما سمتی در دولت ندارید. لطفاً یک سمت خالی را انتخاب کنید:",
                    reply_markup=cabinet_roles_list_kb(members, db_user.telegram_id),
                )
            return

    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer("ابتدا باید کشوری بگیرید. /claim", reply_markup=_claim_kb())
        return
    await show_menu(message, "پنل مدیریت کشور:", main_menu_kb(), image_key="main")
