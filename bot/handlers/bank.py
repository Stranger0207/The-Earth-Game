"""
هندلر سیستم بانکی (v1.9): موجودی، بدهی (+پرداخت)، انتقال وجه و وام.
منطق مالی ساده است و مستقیماً روی بودجه/بدهی کشور در دیتابیس عمل می‌کند.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import User
from ..database.repositories import countries as countries_repo
from ..keyboards.common import confirm_cancel_kb, countries_kb
from ..keyboards.economy import bank_menu_kb
from ..loader import bot
from ..services.news_service import send_log
from ..states import BankTransferForm, DebtPayForm
from ..utils.numbers import fa_money, parse_amount
from ..utils.ui import STYLE_MAIN
from .deps import NO_COUNTRY_TEXT, get_player_country

router = Router(name="bank")


def _back_bank_kb() -> InlineKeyboardMarkup:
    """دکمه‌ی بازگشت به منوی بانک."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="econ:bank", style=STYLE_MAIN)
    ]])


# ============================================================
#  منوی بانک
# ============================================================
@router.callback_query(F.data == "econ:bank")
async def cb_bank(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.answer()
    await call.message.edit_text(
        "🏦 <b>بانک مرکزی</b>\n\nیکی از خدمات بانکی را انتخاب کنید:",
        reply_markup=bank_menu_kb(),
    )


@router.callback_query(F.data == "bank:balance")
async def cb_bank_balance(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    await call.message.edit_text(
        f"💰 <b>موجودی خزانه‌ی {country.flag} {country.name_fa}</b>\n\n"
        f"بودجه‌ی فعلی: {fa_money(country.budget)}",
        reply_markup=_back_bank_kb(),
    )


# ============================================================
#  بدهی + پرداخت بدهی
# ============================================================
@router.callback_query(F.data == "bank:debt")
async def cb_bank_debt(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    debt = country.govt_debt or 0.0
    lines = [
        f"📉 <b>بدهی دولتی {country.flag} {country.name_fa}</b>",
        "",
        f"مجموع بدهی: {fa_money(debt)}",
        f"موجودی خزانه: {fa_money(country.budget)}",
    ]
    kb_rows = []
    if debt > 0:
        kb_rows.append([InlineKeyboardButton(
            text="💸 پرداخت بدهی", callback_data="bank:debt_pay", style=STYLE_MAIN
        )])
    kb_rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="econ:bank", style=STYLE_MAIN)])
    await call.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))


@router.callback_query(F.data == "bank:debt_pay")
async def cb_bank_debt_pay(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    if (country.govt_debt or 0.0) <= 0:
        await call.message.edit_text("شما بدهی فعالی ندارید.", reply_markup=_back_bank_kb())
        return
    await state.set_state(DebtPayForm.entering_amount)
    await call.message.edit_text(
        "💸 چه مقدار از بدهی را می‌خواهید پرداخت کنید؟ (به دلار، مثلاً 500m)",
        reply_markup=_back_bank_kb(),
    )


@router.message(DebtPayForm.entering_amount, F.text)
async def msg_debt_amount(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    amount = parse_amount(message.text)
    if amount is None or amount <= 0:
        await message.answer("لطفاً یک مبلغ معتبر وارد کنید.")
        return
    country = await get_player_country(session, db_user)
    if country is None:
        await state.clear()
        await message.answer(NO_COUNTRY_TEXT)
        return
    debt = country.govt_debt or 0.0
    if amount > debt:
        amount = debt  # نمی‌توان بیش از کل بدهی پرداخت کرد
    if country.budget < amount:
        await message.answer(
            f"⛔️ بودجه‌ی کافی ندارید. موجودی شما {fa_money(country.budget)} است.",
            reply_markup=_back_bank_kb(),
        )
        return
    await state.update_data(pay_amount=amount)
    await state.set_state(DebtPayForm.confirming)
    await message.answer(
        f"❓ آیا مطمئن هستید که می‌خواهید {fa_money(amount)} از بدهی خود را پرداخت کنید؟",
        reply_markup=confirm_cancel_kb("bank:debt_confirm"),
    )


@router.callback_query(DebtPayForm.confirming, F.data == "bank:debt_confirm")
async def cb_debt_confirm(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    data = await state.get_data()
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    amount = float(data.get("pay_amount", 0))
    debt = country.govt_debt or 0.0
    amount = min(amount, debt, country.budget)
    if amount <= 0:
        await call.message.edit_text("پرداختی انجام نشد.", reply_markup=_back_bank_kb())
        return
    country.budget -= amount
    country.govt_debt = debt - amount
    await call.message.edit_text(
        f"✅ {fa_money(amount)} از بدهی شما پرداخت شد.\n"
        f"بدهی باقی‌مانده: {fa_money(country.govt_debt)}\n"
        f"موجودی خزانه: {fa_money(country.budget)}",
        reply_markup=_back_bank_kb(),
    )
    await send_log(
        bot,
        f"💸 <b>پرداخت بدهی</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"مبلغ پرداختی: {fa_money(amount)}\n"
        f"بدهی باقی‌مانده: {fa_money(country.govt_debt)}",
    )


# ============================================================
#  انتقال وجه به کشور دیگر
# ============================================================
@router.callback_query(F.data == "bank:transfer")
async def cb_bank_transfer(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    await state.set_state(BankTransferForm.choosing_target)
    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id and c.owner_user_id is not None]
    if not others:
        await call.message.edit_text("کشوری برای انتقال وجه وجود ندارد.", reply_markup=_back_bank_kb())
        return
    await call.message.edit_text(
        "🔁 وجه را به کدام کشور منتقل می‌کنید؟",
        reply_markup=countries_kb(others, prefix="bank_to", columns=2, back_data="econ:bank"),
    )


@router.callback_query(BankTransferForm.choosing_target, F.data.startswith("bank_to:"))
async def cb_transfer_to(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    target = await countries_repo.get_country(session, int(call.data.split(":")[1]))
    if target is None:
        await call.message.edit_text("کشور مقصد یافت نشد.", reply_markup=_back_bank_kb())
        return
    await state.update_data(target_id=target.id)
    await state.set_state(BankTransferForm.entering_amount)
    await call.message.edit_text(
        f"💵 چه مبلغی به {target.flag} {target.name_fa} منتقل می‌کنید؟ (به دلار، مثلاً 1b)",
        reply_markup=_back_bank_kb(),
    )


@router.message(BankTransferForm.entering_amount, F.text)
async def msg_transfer_amount(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    amount = parse_amount(message.text)
    if amount is None or amount <= 0:
        await message.answer("لطفاً یک مبلغ معتبر وارد کنید.")
        return
    country = await get_player_country(session, db_user)
    if country is None:
        await state.clear()
        await message.answer(NO_COUNTRY_TEXT)
        return
    if country.budget < amount:
        await message.answer(
            f"⛔️ بودجه‌ی کافی ندارید. موجودی شما {fa_money(country.budget)} است.",
            reply_markup=_back_bank_kb(),
        )
        return
    data = await state.get_data()
    target = await countries_repo.get_country(session, data.get("target_id"))
    if target is None:
        await state.clear()
        await message.answer("کشور مقصد یافت نشد.", reply_markup=_back_bank_kb())
        return
    await state.update_data(amount=amount)
    await state.set_state(BankTransferForm.confirming)
    await message.answer(
        f"❓ آیا مطمئن هستید که می‌خواهید {fa_money(amount)} به "
        f"{target.flag} {target.name_fa} منتقل کنید؟",
        reply_markup=confirm_cancel_kb("bank:transfer_confirm"),
    )


@router.callback_query(BankTransferForm.confirming, F.data == "bank:transfer_confirm")
async def cb_transfer_confirm(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    data = await state.get_data()
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    amount = float(data.get("amount", 0))
    target = await countries_repo.get_country(session, data.get("target_id"))
    if target is None:
        await call.message.edit_text("کشور مقصد یافت نشد.", reply_markup=_back_bank_kb())
        return
    if amount <= 0 or country.budget < amount:
        await call.message.edit_text(
            "⛔️ انتقال انجام نشد (بودجه‌ی ناکافی).", reply_markup=_back_bank_kb()
        )
        return
    country.budget -= amount
    target.budget = (target.budget or 0.0) + amount
    await call.message.edit_text(
        f"✅ {fa_money(amount)} با موفقیت به {target.flag} {target.name_fa} منتقل شد.\n"
        f"موجودی خزانه‌ی شما: {fa_money(country.budget)}",
        reply_markup=_back_bank_kb(),
    )
    # اطلاع به کشور مقصد
    if target.owner_user_id:
        try:
            await bot.send_message(
                target.owner_user_id,
                f"💵 کشور {country.flag} {country.name_fa} مبلغ {fa_money(amount)} به خزانه‌ی شما واریز کرد.",
            )
        except Exception:  # noqa: BLE001
            pass
    # لاگ انتقال وجه
    await send_log(
        bot,
        f"🔁 <b>انتقال وجه</b>\n"
        f"از: {country.flag} {country.name_fa}\n"
        f"به: {target.flag} {target.name_fa}\n"
        f"مبلغ: {fa_money(amount)}",
    )


# ============================================================
#  وام (غیرفعال)
# ============================================================
@router.callback_query(F.data == "bank:loan")
async def cb_bank_loan(call: CallbackQuery) -> None:
    await call.answer(
        "🏛 در حال حاضر سیستم وام توسط تیم مدیریت غیرفعال شده است.",
        show_alert=True,
    )
