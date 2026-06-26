"""هندلر مشاور هوش مصنوعی: هر ۲۴ ساعت یک پرسش در هر دامنه."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import ADVISOR_COOLDOWN_HOURS
from ..database.models import User
from ..database.repositories import cooldowns as cd_repo
from ..enums import AdvisorDomain
from ..keyboards.menu import main_menu_kb
from ..services.ai import evaluators
from ..states import AdvisorForm
from ..utils.numbers import fa_number
from .deps import NO_COUNTRY_TEXT, get_player_country

router = Router(name="advisor")

# نام فارسی هر دامنه برای نمایش و پرامپت
_DOMAIN_FA = {
    AdvisorDomain.ECONOMY: "اقتصاد",
    AdvisorDomain.DIPLOMACY: "دیپلماسی",
    AdvisorDomain.MILITARY: "نظامی",
}


def _domain_kb():
    """کیبورد انتخاب دامنه‌ی مشاوره."""
    from ..utils.ui import STYLE_MAIN

    builder = InlineKeyboardBuilder()
    for domain, fa in _DOMAIN_FA.items():
        builder.button(text=fa, callback_data=f"adv:{domain.value}", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="menu:main", style=STYLE_MAIN)
    builder.adjust(3, 1)
    return builder.as_markup()


@router.callback_query(F.data == "menu:advisor")
async def cb_advisor(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(AdvisorForm.choosing_domain)
    await call.message.edit_text(
        "🧠 <b>مشاور هوشمند</b>\n\n"
        f"در هر دامنه هر {ADVISOR_COOLDOWN_HOURS} ساعت یک‌بار می‌توانید مشاوره بگیرید.\n"
        "دامنه‌ی موردنظر را انتخاب کنید:",
        reply_markup=_domain_kb(),
    )


@router.callback_query(AdvisorForm.choosing_domain, F.data.startswith("adv:"))
async def cb_advisor_domain(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    await call.answer()
    domain = AdvisorDomain(call.data.split(":")[1])
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        await state.clear()
        return

    # بررسی کول‌داون ۲۴ ساعته برای این دامنه
    action = f"advisor:{domain.value}"
    remaining = await cd_repo.remaining_seconds(
        session, country.id, action, ADVISOR_COOLDOWN_HOURS
    )
    if remaining > 0:
        hours = int(remaining // 3600)
        mins = int((remaining % 3600) // 60)
        await call.message.edit_text(
            f"⏳ شما اخیراً از مشاور «{_DOMAIN_FA[domain]}» استفاده کرده‌اید.\n"
            f"زمان باقی‌مانده: {fa_number(hours)} ساعت و {fa_number(mins)} دقیقه.",
            reply_markup=main_menu_kb(),
        )
        await state.clear()
        return

    await state.update_data(domain=domain.value)
    await state.set_state(AdvisorForm.asking)
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from ..utils.ui import STYLE_MAIN

    back_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="advback:domain", style=STYLE_MAIN)
    ]])
    await call.message.edit_text(
        f"🧠 پرسش خود را از مشاور «{_DOMAIN_FA[domain]}» بنویسید:",
        reply_markup=back_kb,
    )


@router.callback_query(AdvisorForm.asking, F.data == "advback:domain")
async def cb_advisor_back_domain(call: CallbackQuery, state: FSMContext) -> None:
    """بازگشت به انتخاب دامنه‌ی مشاوره."""
    await call.answer()
    await state.set_state(AdvisorForm.choosing_domain)
    await call.message.edit_text(
        "🧠 <b>مشاور هوشمند</b>\n\n"
        f"در هر دامنه هر {ADVISOR_COOLDOWN_HOURS} ساعت یک‌بار می‌توانید مشاوره بگیرید.\n"
        "دامنه‌ی موردنظر را انتخاب کنید:",
        reply_markup=_domain_kb(),
    )


@router.message(AdvisorForm.asking, F.text)
async def msg_advisor_question(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    data = await state.get_data()
    domain = AdvisorDomain(data["domain"])
    country = await get_player_country(session, db_user)
    await state.clear()
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        return

    await message.answer("⏳ مشاور در حال بررسی وضعیت کشور شماست...")
    advice = await evaluators.get_advice(
        session, country.id, _DOMAIN_FA[domain], message.text
    )

    # ثبت کول‌داون پس از مشاوره‌ی موفق
    await cd_repo.touch(session, country.id, f"advisor:{domain.value}")

    await message.answer(
        f"🧠 <b>مشاور {_DOMAIN_FA[domain]}:</b>\n\n{advice}",
        reply_markup=main_menu_kb(),
    )
