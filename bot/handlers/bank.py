"""
هندلر سیستم بانکی (v1.9): موجودی، بدهی (+پرداخت)، انتقال وجه و وام.
منطق مالی ساده است و مستقیماً روی بودجه/بدهی کشور در دیتابیس عمل می‌کند.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    LOAN_COOLDOWN_DAYS,
    LOAN_COOLDOWN_HOURS,
    LOAN_DURATION_DAYS,
    LOAN_GOOD_CREDIT_DAYS,
    LOAN_LIMIT_BAD_CREDIT,
    LOAN_LIMIT_GOOD,
    LOAN_LIMIT_NORMAL,
)
from ..database.models import User
from ..database.repositories import bank_loans as loans_repo
from ..database.repositories import cooldowns as cd_repo
from ..database.repositories import countries as countries_repo
from ..enums import CREDIT_RATING_FA, CreditRating, LoanStatus
from ..keyboards.common import confirm_cancel_kb, countries_kb
from ..keyboards.economy import bank_menu_kb, loan_panel_kb
from ..loader import bot
from ..services.news_service import send_log
from ..states import BankTransferForm, DebtPayForm, LoanRepayForm, LoanTakeForm
from ..utils.numbers import fa_money, fa_number, parse_amount
from ..utils.screens import safe_edit, show_menu
from ..utils.ui import STYLE_MAIN
from .deps import NO_COUNTRY_TEXT, assert_feature, get_player_country

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
async def cb_bank(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    await state.clear()
    await call.answer()
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "econ.bank"):
        return
    await show_menu(
        call,
        "🏦 <b>بانک مرکزی</b>\n\nیکی از خدمات بانکی را انتخاب کنید:",
        bank_menu_kb(),
        image_key="bank",
    )


@router.callback_query(F.data == "bank:balance")
async def cb_bank_balance(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    await safe_edit(
        call,
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
        await safe_edit(call, NO_COUNTRY_TEXT)
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
    await safe_edit(call, "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))


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
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "econ.transfer"):
        return
    await state.set_state(BankTransferForm.choosing_target)
    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id and c.owner_user_id is not None]
    if not others:
        await safe_edit(call, "کشوری برای انتقال وجه وجود ندارد.", reply_markup=_back_bank_kb())
        return
    await safe_edit(
        call,
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
#  سیستم وام بانکی (v2.2)
# ============================================================
def _format_time_left(target: datetime) -> str:
    """فرمت فارسی زمان باقی‌مانده تا موعد."""
    now = datetime.now(timezone.utc)
    t = target if target.tzinfo else target.replace(tzinfo=timezone.utc)
    if t <= now:
        return "منقضی شده"
    diff = t - now
    days = diff.days
    hours = diff.seconds // 3600
    minutes = (diff.seconds % 3600) // 60
    parts = []
    if days > 0:
        parts.append(f"{fa_number(days)} روز")
    if hours > 0:
        parts.append(f"{fa_number(hours)} ساعت")
    if not parts or (days == 0 and minutes > 0):
        parts.append(f"{fa_number(minutes)} دقیقه")
    return " و ".join(parts)


def _format_seconds(seconds: float) -> str:
    """فرمت فارسی زمان باقی‌مانده از کول‌داون."""
    if seconds <= 0:
        return "۰ دقیقه"
    total_mins = int(seconds // 60)
    days = total_mins // (24 * 60)
    hours = (total_mins % (24 * 60)) // 60
    mins = total_mins % 60
    parts = []
    if days > 0:
        parts.append(f"{fa_number(days)} روز")
    if hours > 0:
        parts.append(f"{fa_number(hours)} ساعت")
    if mins > 0 or not parts:
        parts.append(f"{fa_number(mins)} دقیقه")
    return " و ".join(parts)


def _loan_limit_for_country(country) -> float:
    """محاسبه سقف وام بر اساس رتبه اعتباری کشور."""
    rating = getattr(country, "credit_rating", CreditRating.NORMAL)
    if rating == CreditRating.GOOD:
        return LOAN_LIMIT_GOOD
    if rating == CreditRating.BAD_CREDIT:
        return LOAN_LIMIT_BAD_CREDIT
    return LOAN_LIMIT_NORMAL


@router.callback_query(F.data == "bank:loan")
async def cb_bank_loan(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    await state.clear()
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "econ.loan"):
        return

    active_loan = await loans_repo.get_active_loan(session, country.id)
    rating = getattr(country, "credit_rating", CreditRating.NORMAL)
    rating_fa = CREDIT_RATING_FA.get(rating, "عادی")

    if active_loan:
        rem_time = _format_time_left(active_loan.deadline)
        reward_time = _format_time_left(active_loan.reward_deadline)
        reward_text = (
            f"🎁 <b>فرصت خوش‌حسابی (سقف ۵ تریلیون):</b> {reward_time}"
            if reward_time != "منقضی شده"
            else "⏳ مهلت خوش‌حسابی به پایان رسیده است."
        )

        text = (
            f"🏛 <b>مدیریت وام بانکی فعال {country.flag} {country.name_fa}</b>\n\n"
            f"💰 <b>مبلغ اصل وام:</b> {fa_money(active_loan.amount)}\n"
            f"💳 <b>مانده بدهی وام:</b> {fa_money(active_loan.remaining_amount)}\n"
            f"⭐ <b>رتبه اعتباری شما:</b> {rating_fa}\n"
            f"⏳ <b>مهلت بازپرداخت کل:</b> {rem_time}\n"
            f"{reward_text}\n\n"
            "<i>برای تسویه بدهی وام خود، از دکمه زیر استفاده کنید.</i>"
        )
        await safe_edit(call, text, reply_markup=loan_panel_kb(has_active_loan=True))
        return

    # بررسی بدهی قبلی
    debt = country.govt_debt or 0.0
    if debt > 0:
        text = (
            f"🏛 <b>بخش وام بانکی {country.flag} {country.name_fa}</b>\n\n"
            f"⛔️ <b>شما دارای بدهی دولتی تسویه‌نشده هستید:</b> {fa_money(debt)}\n\n"
            "طبق قوانین بانک مرکزی، تنها کشورهایی که تمام بدهی‌های دولتی قبلی خود را تسویه کرده باشند، "
            "مجاز به دریافت وام بانکی هستند.\n\n"
            "لطفاً ابتدا از بخش «📉 بدهی» نسبت به تسویه کامل بدهی خود اقدام فرمایید."
        )
        await safe_edit(call, text, reply_markup=_back_bank_kb())
        return

    # بررسی بدحسابی معوقه
    if rating == CreditRating.DEFAULTER:
        text = (
            f"🏛 <b>بخش وام بانکی {country.flag} {country.name_fa}</b>\n\n"
            "🚫 <b>وضعیت حساب: بدحساب (مسدود)</b>\n\n"
            "به دلیل عدم بازپرداخت وام قبلی در مهلت قانونی یک هفته‌ای، رتبه اعتباری کشور شما تنزیل یافته "
            "و امکان دریافت وام بانکی جدید تا اطلاع ثانوی مسدود می‌باشد."
        )
        await safe_edit(call, text, reply_markup=_back_bank_kb())
        return

    # بررسی کول‌داون ۵ روزه دریافت وام
    cd_rem = await cd_repo.remaining_seconds(session, country.id, "bank_loan", LOAN_COOLDOWN_HOURS)
    cd_note = ""
    if cd_rem > 0:
        cd_note = (
            f"\n\n⏳ <b>محدودیت زمانی (کول‌داون):</b> شما هر {fa_number(LOAN_COOLDOWN_DAYS)} روز یک‌بار می‌توانید وام بگیرید.\n"
            f"زمان باقی‌مانده تا امکان اخذ وام جدید: <b>{_format_seconds(cd_rem)}</b>"
        )

    max_limit = _loan_limit_for_country(country)
    text = (
        f"🏛 <b>تسهیلات وام بانکی {country.flag} {country.name_fa}</b>\n\n"
        f"⭐ <b>رتبه اعتباری:</b> {rating_fa}\n"
        f"💎 <b>سقف مجاز دریافت وام:</b> {fa_money(max_limit)}\n"
        f"⏳ <b>مهلت بازپرداخت قانونی:</b> {fa_number(LOAN_DURATION_DAYS)} روز\n"
        f"🔄 <b>کول‌داون دریافت وام:</b> هر {fa_number(LOAN_COOLDOWN_DAYS)} روز ۱ بار\n\n"
        f"💡 <b>قوانین اعتبارسنجی:</b>\n"
        f"• در صورت تسویه زیر {fa_number(LOAN_GOOD_CREDIT_DAYS)} روز، رتبه شما به <b>خوش‌حساب</b> ارتقا یافته و سقف وامتان به <b>۵ تریلیون دلار</b> می‌رسد.\n"
        f"• در صورت عدم تسویه ظرف ۷ روز، حسابتان بدحساب شده و دسترسی به وام مسدود می‌گردد."
        f"{cd_note}"
    )
    await safe_edit(call, text, reply_markup=loan_panel_kb(has_active_loan=False))


@router.callback_query(F.data == "bank:loan_take")
async def cb_bank_loan_take(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "econ.loan"):
        return

    if (country.govt_debt or 0.0) > 0:
        await call.answer("ابتدا باید بدهی قبلی خود را تسویه کنید.", show_alert=True)
        return

    active_loan = await loans_repo.get_active_loan(session, country.id)
    if active_loan:
        await call.answer("شما در حال حاضر وام فعال دارید.", show_alert=True)
        return

    rating = getattr(country, "credit_rating", CreditRating.NORMAL)
    if rating == CreditRating.DEFAULTER:
        await call.answer("حساب شما مسدود است.", show_alert=True)
        return

    # بررسی کول‌داون ۵ روزه دریافت وام
    cd_rem = await cd_repo.remaining_seconds(session, country.id, "bank_loan", LOAN_COOLDOWN_HOURS)
    if cd_rem > 0:
        await call.answer(
            f"⛔️ هر {fa_number(LOAN_COOLDOWN_DAYS)} روز یک‌بار می‌توانید وام بگیرید.\nزمان باقی‌مانده: {_format_seconds(cd_rem)}",
            show_alert=True,
        )
        return

    max_limit = _loan_limit_for_country(country)
    await state.set_state(LoanTakeForm.entering_amount)
    await state.update_data(max_limit=max_limit)
    await call.message.edit_text(
        f"💵 <b>درخواست اخذ وام بانکی</b>\n\n"
        f"سقف مجاز شما: {fa_money(max_limit)}\n\n"
        "چه مبلغی را به عنوان وام می‌خواهید دریافت کنید؟ (مثلاً 500b یا 2t یا 5t):",
        reply_markup=_back_bank_kb(),
    )


@router.message(LoanTakeForm.entering_amount, F.text)
async def msg_loan_take_amount(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    amount = parse_amount(message.text)
    if amount is None or amount <= 0:
        await message.answer("لطفاً یک مبلغ معتبر وارد کنید (مثلاً 1t یا 500b).")
        return

    country = await get_player_country(session, db_user)
    if country is None:
        await state.clear()
        await message.answer(NO_COUNTRY_TEXT)
        return

    max_limit = _loan_limit_for_country(country)
    if amount > max_limit:
        await message.answer(
            f"⛔️ مبلغ درخواستی بیشتر از سقف مجاز شما ({fa_money(max_limit)}) است.\n"
            "لطفاً مبلغ کمتری وارد فرمایید:",
            reply_markup=_back_bank_kb(),
        )
        return

    await state.update_data(loan_amount=amount)
    await state.set_state(LoanTakeForm.confirming)
    await message.answer(
        f"❓ <b>تأییدیه نهایی اخذ وام</b>\n\n"
        f"مبلغ وام درخواستی: {fa_money(amount)}\n"
        f"مهلت بازپرداخت: {fa_number(LOAN_DURATION_DAYS)} روز\n"
        f"فرصت خوش‌حسابی: {fa_number(LOAN_GOOD_CREDIT_DAYS)} روز\n\n"
        "آیا با شرایط فوق و واریز این مبلغ به خزانه‌تان موافقید؟",
        reply_markup=confirm_cancel_kb("bank:loan_take_confirm"),
    )


@router.callback_query(LoanTakeForm.confirming, F.data == "bank:loan_take_confirm")
async def cb_loan_take_confirm(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    await call.answer()
    data = await state.get_data()
    await state.clear()

    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return

    # اعتبارسنجی مجدد
    if (country.govt_debt or 0.0) > 0:
        await call.message.edit_text("⛔️ به دلیل وجود بدهی، اخذ وام متوقف شد.", reply_markup=_back_bank_kb())
        return
    active_loan = await loans_repo.get_active_loan(session, country.id)
    if active_loan:
        await call.message.edit_text("⛔️ شما در حال حاضر وام فعال دارید.", reply_markup=_back_bank_kb())
        return

    # بررسی کول‌داون دریافت وام
    cd_rem = await cd_repo.remaining_seconds(session, country.id, "bank_loan", LOAN_COOLDOWN_HOURS)
    if cd_rem > 0:
        await call.message.edit_text(
            f"⛔️ کول‌داون {fa_number(LOAN_COOLDOWN_DAYS)} روزه وام هنوز به پایان نرسیده است.\nزمان باقی‌مانده: {_format_seconds(cd_rem)}",
            reply_markup=_back_bank_kb(),
        )
        return

    amount = float(data.get("loan_amount", 0))
    max_limit = _loan_limit_for_country(country)
    if amount <= 0 or amount > max_limit:
        await call.message.edit_text("⛔️ مبلغ نامعتبر است.", reply_markup=_back_bank_kb())
        return

    now = datetime.now(timezone.utc)
    deadline = now + timedelta(days=LOAN_DURATION_DAYS)
    reward_deadline = now + timedelta(days=LOAN_GOOD_CREDIT_DAYS)

    loan = await loans_repo.create_loan(
        session,
        country_id=country.id,
        amount=amount,
        deadline=deadline,
        reward_deadline=reward_deadline,
    )
    country.budget = (country.budget or 0.0) + amount

    # ثبت کول‌داون اخذ وام
    await cd_repo.touch(session, country.id, "bank_loan")

    await call.message.edit_text(
        f"✅ <b>وام بانکی با موفقیت دریافت و واریز شد!</b>\n\n"
        f"💰 مبلغ واریزشده: {fa_money(amount)}\n"
        f"🏦 موجودی جدید خزانه: {fa_money(country.budget)}\n"
        f"⏳ مهلت بازپرداخت: تا ۷ روز آینده ({fa_number(LOAN_DURATION_DAYS)} روز)\n\n"
        f"💡 در صورت تسویه زیر {fa_number(LOAN_GOOD_CREDIT_DAYS)} روز، سقف وام بعدی شما <b>۵ تریلیون دلار</b> خواهد شد.",
        reply_markup=_back_bank_kb(),
    )

    await send_log(
        bot,
        f"🏛 <b>اخذ وام بانکی</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"مبلغ وام: {fa_money(amount)}\n"
        f"شناسه وام: #{loan.id}",
    )


@router.callback_query(F.data == "bank:loan_repay")
async def cb_bank_loan_repay(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    active_loan = await loans_repo.get_active_loan(session, country.id)
    if not active_loan:
        await call.answer("شما هیچ وام فعالی ندارید.", show_alert=True)
        return

    await state.set_state(LoanRepayForm.entering_amount)
    await state.update_data(loan_id=active_loan.id, rem=active_loan.remaining_amount)
    await call.message.edit_text(
        f"💳 <b>بازپرداخت وام بانکی</b>\n\n"
        f"مبلغ مانده وام: {fa_money(active_loan.remaining_amount)}\n"
        f"موجودی خزانه‌ی شما: {fa_money(country.budget)}\n\n"
        "چه مبلغی از وام را می‌خواهید بازپرداخت کنید؟ (مثلاً 500b یا 1t یا کل مانده):",
        reply_markup=_back_bank_kb(),
    )


@router.message(LoanRepayForm.entering_amount, F.text)
async def msg_loan_repay_amount(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    amount = parse_amount(message.text)
    if amount is None or amount <= 0:
        await message.answer("لطفاً یک مبلغ معتبر وارد کنید.")
        return

    country = await get_player_country(session, db_user)
    if country is None:
        await state.clear()
        await message.answer(NO_COUNTRY_TEXT)
        return

    active_loan = await loans_repo.get_active_loan(session, country.id)
    if not active_loan:
        await state.clear()
        await message.answer("وام فعالی یافت نشد.", reply_markup=_back_bank_kb())
        return

    if amount > active_loan.remaining_amount:
        amount = active_loan.remaining_amount

    if country.budget < amount:
        await message.answer(
            f"⛔️ بودجه‌ی کافی ندارید. موجودی شما {fa_money(country.budget)} است.",
            reply_markup=_back_bank_kb(),
        )
        return

    await state.update_data(repay_amount=amount)
    await state.set_state(LoanRepayForm.confirming)
    await message.answer(
        f"❓ آیا مطمئن هستید که می‌خواهید مبلغ {fa_money(amount)} از وام خود را تسویه کنید؟",
        reply_markup=confirm_cancel_kb("bank:loan_repay_confirm"),
    )


@router.callback_query(LoanRepayForm.confirming, F.data == "bank:loan_repay_confirm")
async def cb_loan_repay_confirm(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    await call.answer()
    data = await state.get_data()
    await state.clear()

    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return

    active_loan = await loans_repo.get_active_loan(session, country.id)
    if not active_loan:
        await call.message.edit_text("وام فعالی یافت نشد.", reply_markup=_back_bank_kb())
        return

    amount = float(data.get("repay_amount", 0))
    amount = min(amount, active_loan.remaining_amount, country.budget)
    if amount <= 0:
        await call.message.edit_text("پرداختی انجام نشد.", reply_markup=_back_bank_kb())
        return

    country.budget -= amount
    active_loan.remaining_amount -= amount
    now = datetime.now(timezone.utc)

    status_note = ""
    if active_loan.remaining_amount <= 0:
        active_loan.remaining_amount = 0.0
        active_loan.status = LoanStatus.PAID
        active_loan.paid_at = now

        # بررسی مهلت تسویه
        r_deadline = active_loan.reward_deadline
        if r_deadline.tzinfo is None:
            r_deadline = r_deadline.replace(tzinfo=timezone.utc)

        if now <= r_deadline:
            country.credit_rating = CreditRating.GOOD
            status_note = (
                "\n\n🎉 <b>تبریک ویژه!</b>\n"
                f"شما وام خود را در کمتر از {fa_number(LOAN_GOOD_CREDIT_DAYS)} روز تسویه کردید!\n"
                "رتبه اعتباری شما به <b>خوش‌حساب</b> ارتقا یافت و سقف وام بعدی شما <b>۵ تریلیون دلار</b> شد."
            )
        else:
            # اگر قبلاً معوقه شده بود، اکنون با تسویه سقف به ۱ تریلیون بازمی‌گردد
            if getattr(country, "credit_rating", None) == CreditRating.DEFAULTER:
                country.credit_rating = CreditRating.BAD_CREDIT
                status_note = (
                    "\n\n⚠️ <b>رفع مسدودی حساب:</b>\n"
                    "وام معوقه شما تسویه شد. حساب شما از حالت بدحساب خارج شد و سقف وام شما از این پس <b>۱ تریلیون دلار</b> خواهد بود."
                )
            else:
                if getattr(country, "credit_rating", None) != CreditRating.BAD_CREDIT:
                    country.credit_rating = CreditRating.NORMAL
                status_note = "\n\n✅ وام شما با موفقیت به طور کامل تسویه شد."
    else:
        status_note = f"\n\nبدهی باقی‌مانده از وام: {fa_money(active_loan.remaining_amount)}"

    await call.message.edit_text(
        f"✅ مبلغ {fa_money(amount)} بابت بازپرداخت وام کسر گردید.\n"
        f"موجودی جدید خزانه: {fa_money(country.budget)}"
        f"{status_note}",
        reply_markup=_back_bank_kb(),
    )

    await send_log(
        bot,
        f"💳 <b>بازپرداخت وام بانکی</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"مبلغ پرداختی: {fa_money(amount)}\n"
        f"مانده وام: {fa_money(active_loan.remaining_amount)}\n"
        f"وضعیت وام: {active_loan.status}",
    )
