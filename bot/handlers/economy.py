"""هندلر بخش اقتصاد: گزارش، ذخایر، احداث تأسیسات و فروش ذخیره."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    FACILITY_COST_USD,
    RESOURCE_SALE_COOLDOWN_HOURS,
)
from ..database.models import User
from ..database.repositories import cooldowns as cd_repo
from ..database.repositories import countries as countries_repo
from ..database.repositories import reserves as reserves_repo
from ..database.repositories import trade as trade_repo
from ..database.models import ResourceSale
from ..enums import (
    FACILITY_FA,
    RESOURCE_FA,
    RESOURCE_UNIT_FA,
    FacilityType,
    NewsCategory,
    ResourceType,
    TradeStatus,
)
from ..keyboards.common import countries_kb
from ..keyboards.economy import (
    economy_menu_kb,
    facility_types_kb,
    mine_resources_kb,
    sell_resources_kb,
)
from ..loader import bot
from ..services.ai import evaluators
from ..services.economy_service import EconomyError, build_facility, transfer_sale
from ..services.news_service import publish_news
from ..states import FacilityForm, SaleForm
from ..utils.formatting import render_economy_panel, render_reserves_panel
from ..utils.numbers import fa_money, fa_number, parse_amount
from .deps import NO_COUNTRY_TEXT, get_player_country

router = Router(name="economy")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
#  گزارش اقتصادی و ذخایر
# ============================================================
@router.callback_query(F.data == "econ:report")
async def cb_report(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    await call.message.edit_text(
        render_economy_panel(country), reply_markup=economy_menu_kb()
    )


@router.callback_query(F.data == "econ:reserves")
async def cb_reserves(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    reserves = await reserves_repo.list_reserves(session, country.id)
    await call.message.edit_text(
        render_reserves_panel(country, reserves), reply_markup=economy_menu_kb()
    )


# ============================================================
#  احداث تأسیسات
# ============================================================
@router.callback_query(F.data == "econ:build")
async def cb_build(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(FacilityForm.choosing_type)
    await call.message.edit_text(
        "🏗 نوع تأسیساتی که می‌خواهید احداث کنید را انتخاب کنید:",
        reply_markup=facility_types_kb(),
    )


@router.callback_query(FacilityForm.choosing_type, F.data.startswith("build_type:"))
async def cb_build_type(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    ftype = FacilityType(call.data.split(":")[1])
    await state.update_data(facility_type=ftype.value)
    cost = FACILITY_COST_USD[ftype]

    if ftype == FacilityType.MINE:
        # برای معدن باید نوع منبع انتخاب شود
        await state.set_state(FacilityForm.choosing_resource)
        await call.message.edit_text(
            f"⛏ معدن چه منبعی را می‌خواهید احداث کنید؟\n"
            f"💰 هزینه: {fa_money(cost)}",
            reply_markup=mine_resources_kb(),
        )
    else:
        # سایر تأسیسات مستقیم به مرحله‌ی محل می‌روند
        await state.update_data(resource=None)
        await state.set_state(FacilityForm.entering_location)
        await call.message.edit_text(
            f"🏭 احداث {FACILITY_FA[ftype]}\n"
            f"💰 هزینه: {fa_money(cost)}\n\n"
            "📍 محل احداث را وارد کنید:"
        )


@router.callback_query(FacilityForm.choosing_resource, F.data.startswith("mine_res:"))
async def cb_mine_resource(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    resource = call.data.split(":")[1]
    await state.update_data(resource=resource)
    await state.set_state(FacilityForm.entering_location)
    await call.message.edit_text(
        f"⛏ معدن {RESOURCE_FA[ResourceType(resource)]}\n\n📍 محل احداث را وارد کنید:"
    )


@router.message(FacilityForm.entering_location, F.text)
async def msg_location(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """ساخت نهایی تأسیسات."""
    data = await state.get_data()
    ftype = FacilityType(data["facility_type"])
    resource = data.get("resource")
    location = message.text.strip()

    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        await state.clear()
        return

    try:
        facility = await build_facility(session, country, ftype, resource, location)
    except EconomyError as exc:
        await message.answer(f"⚠️ {exc}")
        await state.clear()
        return

    await state.clear()
    unit = ""
    if facility.resource:
        try:
            unit = RESOURCE_UNIT_FA[ResourceType(facility.resource)]
        except (ValueError, KeyError):
            unit = ""
    await message.answer(
        f"✅ {FACILITY_FA[ftype]} با موفقیت در «{location}» احداث شد.\n"
        f"🏗 بازدهی: {fa_number(facility.yield_amount)} {unit} در هر ۲۴ ساعت\n"
        f"💰 بودجه‌ی باقی‌مانده: {fa_money(country.budget)}",
        reply_markup=economy_menu_kb(),
    )

    # خبر اقتصادی
    president = db_user.president_name or country.name_fa
    await publish_news(
        bot,
        NewsCategory.ECONOMY,
        f"کشور {country.flag} {country.name_fa} به ریاست‌جمهوری {president} "
        f"یک {FACILITY_FA[ftype]} جدید احداث کرد.",
    )


# ============================================================
#  فروش ذخیره به کشور دیگر (با کول‌داون ۶ ساعته)
# ============================================================
@router.callback_query(F.data == "econ:sell")
async def cb_sell(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return

    # بررسی کول‌داون فروش
    remaining = await cd_repo.remaining_seconds(
        session, country.id, "resource_sale", RESOURCE_SALE_COOLDOWN_HOURS
    )
    if remaining > 0:
        mins = int(remaining // 60)
        await call.message.edit_text(
            f"⏳ هر کشور هر {RESOURCE_SALE_COOLDOWN_HOURS} ساعت یک‌بار می‌تواند منبع بفروشد.\n"
            f"زمان باقی‌مانده: حدود {fa_number(mins)} دقیقه.",
            reply_markup=economy_menu_kb(),
        )
        return

    await state.set_state(SaleForm.choosing_resource)
    await call.message.edit_text(
        "💱 کدام منبع را می‌خواهید بفروشید؟", reply_markup=sell_resources_kb()
    )


@router.callback_query(SaleForm.choosing_resource, F.data.startswith("sell_res:"))
async def cb_sell_resource(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    resource = call.data.split(":")[1]
    await state.update_data(resource=resource)
    await state.set_state(SaleForm.entering_amount)
    unit = RESOURCE_UNIT_FA[ResourceType(resource)]
    await call.message.edit_text(
        f"مقدار {RESOURCE_FA[ResourceType(resource)]} برای فروش را وارد کنید (به {unit}):\n"
        "می‌توانید از پسوند k/m/b استفاده کنید (مثلاً 50k)."
    )


@router.message(SaleForm.entering_amount, F.text)
async def msg_sell_amount(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    amount = parse_amount(message.text)
    if amount is None or amount <= 0:
        await message.answer("لطفاً یک عدد معتبر وارد کنید.")
        return
    data = await state.get_data()
    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        await state.clear()
        return

    if not await reserves_repo.has_enough(session, country.id, data["resource"], amount):
        await message.answer("موجودی شما برای این مقدار کافی نیست.")
        return

    await state.update_data(amount=amount)
    await state.set_state(SaleForm.choosing_buyer)
    # لیست کشورهای دیگر (به‌جز خودِ کشور)
    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id]
    await message.answer(
        "کشور خریدار را انتخاب کنید:",
        reply_markup=countries_kb(others, prefix="sell_buyer", columns=2),
    )


@router.callback_query(SaleForm.choosing_buyer, F.data.startswith("sell_buyer:"))
async def cb_sell_buyer(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    buyer_id = int(call.data.split(":")[1])
    await state.update_data(buyer_id=buyer_id)
    await state.set_state(SaleForm.entering_price)
    await call.message.edit_text(
        "مبلغ فروش را به دلار وارد کنید (مثلاً 500m برای ۵۰۰ میلیون):"
    )


@router.message(SaleForm.entering_price, F.text)
async def msg_sell_price(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    price = parse_amount(message.text)
    if price is None or price <= 0:
        await message.answer("لطفاً یک مبلغ معتبر وارد کنید.")
        return
    data = await state.get_data()
    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        await state.clear()
        return

    resource = data["resource"]
    amount = data["amount"]
    buyer_id = data["buyer_id"]
    buyer = await countries_repo.get_country(session, buyer_id)
    if buyer is None:
        await message.answer("کشور خریدار یافت نشد.")
        await state.clear()
        return

    # ساخت رکورد فروش در حالت در انتظار تأیید خریدار
    sale = ResourceSale(
        seller_country=country.id,
        buyer_country=buyer_id,
        resource=resource,
        amount=amount,
        price=price,
        status=TradeStatus.PENDING,
    )
    sale = await trade_repo.add_sale(session, sale)
    await session.flush()
    await state.clear()

    unit = RESOURCE_UNIT_FA[ResourceType(resource)]
    rname = RESOURCE_FA[ResourceType(resource)]
    await message.answer(
        f"📨 پیشنهاد فروش برای {buyer.flag} {buyer.name_fa} ارسال شد:\n"
        f"{fa_number(amount)} {unit} {rname} به مبلغ {fa_money(price)}\n\n"
        "پس از تأیید خریدار، محموله توسط WTO ارسال می‌شود."
    )

    # ارسال پیشنهاد به مالک کشور خریدار
    if buyer.owner_user_id:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ خرید", callback_data=f"sale_accept:{sale.id}"
                    ),
                    InlineKeyboardButton(
                        text="❌ رد", callback_data=f"sale_reject:{sale.id}"
                    ),
                ]
            ]
        )
        try:
            await bot.send_message(
                buyer.owner_user_id,
                f"🛒 <b>پیشنهاد خرید منبع</b>\n\n"
                f"فروشنده: {country.flag} {country.name_fa}\n"
                f"منبع: {fa_number(amount)} {unit} {rname}\n"
                f"قیمت: {fa_money(price)}",
                reply_markup=kb,
            )
        except Exception:  # noqa: BLE001
            pass


@router.callback_query(F.data.startswith("sale_accept:"))
async def cb_sale_accept(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """تأیید خرید توسط خریدار: انتقال مالی و ارسال محموله توسط WTO."""
    sale_id = int(call.data.split(":")[1])
    sale = await trade_repo.get_sale(session, sale_id)
    if sale is None or sale.status != TradeStatus.PENDING:
        await call.answer("این پیشنهاد دیگر معتبر نیست.", show_alert=True)
        return

    buyer = await countries_repo.get_country(session, sale.buyer_country)
    if buyer is None or buyer.owner_user_id != db_user.telegram_id:
        await call.answer("شما مجاز به تأیید این خرید نیستید.", show_alert=True)
        return

    try:
        await transfer_sale(
            session, sale.seller_country, sale.buyer_country,
            sale.resource, sale.amount, sale.price,
        )
    except EconomyError as exc:
        await call.answer(str(exc), show_alert=True)
        return

    # تخمین زمان رسیدن محموله توسط AI
    seller = await countries_repo.get_country(session, sale.seller_country)
    rname = RESOURCE_FA[ResourceType(sale.resource)]
    eta_data = await evaluators.estimate_shipping_time(
        seller.name_fa if seller else "?", buyer.name_fa, rname, sale.amount
    )
    minutes = int(eta_data.get("shipping_minutes", 30) or 30)
    minutes = max(5, min(minutes, 120))
    sale.ship_eta = _utcnow() + timedelta(minutes=minutes)
    sale.status = TradeStatus.IN_TRANSIT

    # ثبت کول‌داون فروش برای فروشنده
    await cd_repo.touch(session, sale.seller_country, "resource_sale")

    await call.answer("خرید تأیید شد ✅")
    await call.message.edit_text(
        call.message.html_text
        + f"\n\n✅ <b>تأیید شد</b> — زمان رسیدن: حدود {fa_number(minutes)} دقیقه"
    )

    # اطلاع به فروشنده
    if seller and seller.owner_user_id:
        try:
            await bot.send_message(
                seller.owner_user_id,
                f"✅ {buyer.flag} {buyer.name_fa} پیشنهاد فروش شما را پذیرفت. "
                f"محموله در راه است.",
            )
        except Exception:  # noqa: BLE001
            pass

    # خبر WTO
    await publish_news(
        bot,
        NewsCategory.WTO,
        f"🚢 یک محموله‌ی تجاری شامل {rname} از {seller.name_fa if seller else '?'} "
        f"به مقصد {buyer.name_fa} حرکت کرد. زمان تقریبی رسیدن: {fa_number(minutes)} دقیقه.",
    )


@router.callback_query(F.data.startswith("sale_reject:"))
async def cb_sale_reject(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """رد پیشنهاد خرید."""
    sale_id = int(call.data.split(":")[1])
    sale = await trade_repo.get_sale(session, sale_id)
    if sale is None or sale.status != TradeStatus.PENDING:
        await call.answer("این پیشنهاد دیگر معتبر نیست.", show_alert=True)
        return
    sale.status = TradeStatus.REJECTED
    await call.answer("رد شد")
    await call.message.edit_text(call.message.html_text + "\n\n❌ <b>رد شد</b>")

    seller = await countries_repo.get_country(session, sale.seller_country)
    if seller and seller.owner_user_id:
        try:
            await bot.send_message(
                seller.owner_user_id, "❌ پیشنهاد فروش شما رد شد."
            )
        except Exception:  # noqa: BLE001
            pass
