"""هندلر شروع: /start و معرفی بازی."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
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

    # deep-link رهگیری محموله از مینی‌اپ رادار زنده: /start intc_<sale_id>
    if command.args and (command.args.startswith("intc_") or command.args.startswith("intercept_")):
        try:
            sale_id = int(command.args.split("_", 1)[1])
        except (ValueError, IndexError):
            sale_id = None
        if sale_id is not None:
            from .interception import start_interception_for_sale

            handled = await start_interception_for_sale(message, state, session, db_user, sale_id)
            if handled:
                return

    country = await get_player_country(session, db_user)
    if country is not None:
        if country.name_en == "UN":
            from ..keyboards.united_nations import un_main_menu_kb
            from ..utils.ui import header

            sec_gen_title = db_user.president_name or "دبیرکل محترم"
            un_title = (
                header("مقر فرماندهی دبیرکل سازمان ملل متحد", "🇺🇳")
                + f"\n\n🇺🇳 خوش آمدید، {sec_gen_title}!\n\n"
                "به مقر فرماندهی سازمان ملل متحد (نیویورک) خوش آمدید.\n"
                "ارکان بین‌المللی، آژانس انرژی اتمی، دیوان دادگستری لاهه و مجمع عمومی در اختیار شما هستند."
            )
            await show_menu(message, un_title, un_main_menu_kb(), image_key="main")
            return

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
    """نمایش پنل اصلی (در صورت داشتن کشور)."""
    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer("ابتدا باید کشوری بگیرید. /claim", reply_markup=_claim_kb())
        return

    if country.name_en == "UN":
        from ..keyboards.united_nations import un_main_menu_kb
        from ..utils.ui import header

        sec_gen_title = db_user.president_name or "دبیرکل محترم"
        un_title = (
            header("مقر فرماندهی دبیرکل سازمان ملل متحد", "🇺🇳")
            + f"\n\n🇺🇳 خوش آمدید، {sec_gen_title}!\n\n"
            "به مقر فرماندهی سازمان ملل متحد (نیویورک) خوش آمدید.\n"
            "ارکان بین‌المللی، آژانس انرژی اتمی، دیوان دادگستری لاهه و مجمع عمومی در اختیار شما هستند."
        )
        await show_menu(message, un_title, un_main_menu_kb(), image_key="main")
        return

    await show_menu(message, "پنل مدیریت کشور:", main_menu_kb(), image_key="main")


@router.callback_query(F.data == "check_force_join")
async def cb_check_force_join(
    call: CallbackQuery,
    session: AsyncSession,
    db_user: User,
) -> None:
    """بررسی عضویت کاربر در کانال رسمی پس از کلیک روی 'عضو شدم'."""
    from ..database.repositories import bot_state as bot_state_repo
    from ..loader import bot
    from ..services.channel_service import check_user_channel_subscription

    state = await bot_state_repo.get_state(session)
    if state.force_join_enabled and state.force_join_chat_id:
        is_member = await check_user_channel_subscription(
            bot, state.force_join_chat_id, call.from_user.id
        )
        if not is_member:
            await call.answer(
                "❌ شما هنوز در کانال عضو نشده‌اید! لطفاً ابتدا وارد کانال شوید و سپس دوباره امتحان کنید.",
                show_alert=True,
            )
            return

    await call.answer("✅ عضویت شما تأیید شد!")
    try:
        await call.message.delete()
    except Exception:
        pass

    country = await get_player_country(session, db_user)
    if country is not None:
        if country.name_en == "UN":
            from ..keyboards.united_nations import un_main_menu_kb
            from ..utils.ui import header

            sec_gen_title = db_user.president_name or "دبیرکل محترم"
            un_title = (
                header("مقر فرماندهی دبیرکل سازمان ملل متحد", "🇺🇳")
                + f"\n\n🇺🇳 خوش آمدید، {sec_gen_title}!\n\n"
                "به مقر فرماندهی سازمان ملل متحد (نیویورک) خوش آمدید.\n"
                "ارکان بین‌المللی، آژانس انرژی اتمی، دیوان دادگستری لاهه و مجمع عمومی در اختیار شما هستند."
            )
            await show_menu(call.message, un_title, un_main_menu_kb(), image_key="main")
            return

        await show_menu(
            call.message,
            f"👑 خوش آمدید، رهبر {country.flag} <b>{country.name_fa}</b>!\n\n"
            "پنل مدیریت کشور:",
            main_menu_kb(),
            image_key="main",
        )
    else:
        await call.message.answer(WELCOME_TEXT, reply_markup=_claim_kb())


@router.message(Command("folder"))
async def cmd_folder(
    message: Message,
    session: AsyncSession,
) -> None:
    """نمایش لینک فولدر کانال‌های رسمی بازی به کاربر."""
    from ..database.repositories import bot_state as bot_state_repo
    from ..utils.ui import STYLE_MAIN

    state = await bot_state_repo.get_state(session)
    folder_link = state.game_folder_link

    if not folder_link:
        await message.answer(
            "📁 <b>فولدر کانال‌های بازی</b>\n\n"
            "لینک فولدر کانال‌های بازی هنوز توسط مدیریت تنظیم نشده است و به‌زودی قرار خواهد گرفت."
        )
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📁 افزودن فولدر کانال‌های بازی به تلگرام",
                    url=folder_link,
                    style=STYLE_MAIN,
                )
            ]
        ]
    )
    await message.answer(
        "📁 <b>فولدر اختصاصی کانال‌های بازی کره زمین</b>\n\n"
        "برای دسترسی سریع به تمام اخبار نظامی، اقتصادی، دیپلماسی، بیانیه‌ها و رخدادهای زنده، "
        "با لمس دکمه زیر فولدر رسمی بازی را به تلگرام خود اضافه کنید:\n\n"
        f"🔗 <b>لینک مستقیم:</b>\n{folder_link}",
        reply_markup=kb,
    )
