"""هندلر بخش اقتصاد: گزارش، ذخایر، احداث تأسیسات و فروش ذخیره."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    BUILD_LIMIT_COUNT,
    BUILD_LIMIT_WINDOW_HOURS,
    FACILITY_COST_USD,
    RESOURCE_SALE_COOLDOWN_HOURS,
)
from ..database.models import User
from ..database.repositories import cooldowns as cd_repo
from ..database.repositories import countries as countries_repo
from ..database.repositories import facilities as fac_repo
from ..database.repositories import reserves as reserves_repo
from ..database.repositories import tariff as tariff_repo
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
from ..config import get_settings
from ..loader import bot
from ..services.ai import evaluators
from ..services.economy_service import EconomyError, build_facility, transfer_sale
from ..services.media import send_photo_news
from ..services.news_service import publish_news, send_log
from ..states import FacilityForm, SaleForm, TariffForm
from ..utils.formatting import render_economy_panel, render_reserves_panel
from ..utils.numbers import fa_money, fa_number, parse_amount
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK
from .deps import NO_COUNTRY_TEXT, get_player_country

router = Router(name="economy")
settings = get_settings()


def _is_usa(country) -> bool:
    """آیا این کشور آمریکاست؟ (قابلیت تعرفه انحصاری)."""
    return country is not None and country.name_en == "USA"


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


@router.callback_query(F.data == "econ:facilities")
async def cb_my_facilities(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """فهرست تأسیسات احداث‌شده‌ی کشور (v1.7)."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    facilities = await fac_repo.list_facilities(session, country.id)
    if not facilities:
        await call.message.edit_text(
            "🏭 هنوز تأسیساتی احداث نکرده‌اید.", reply_markup=facility_types_kb()
        )
        return
    lines = ["🏭 <b>تأسیسات شما</b>", ""]
    for f in facilities:
        try:
            fa = FACILITY_FA[FacilityType(f.type)]
        except (ValueError, KeyError):
            fa = f.type
        unit = ""
        if f.resource:
            try:
                unit = RESOURCE_UNIT_FA[ResourceType(f.resource)]
            except (ValueError, KeyError):
                unit = ""
        lines.append(
            f"• {fa} — 📍 {f.location or '—'}\n"
            f"   🏗 بازدهی: {fa_number(f.yield_amount)} {unit}/۲۴ساعت | 💰 {fa_money(f.budget)}"
        )
    await call.message.edit_text("\n".join(lines), reply_markup=facility_types_kb())


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
            "📍 محل احداث را وارد کنید:",
            reply_markup=_back_kb("facback:type"),
        )


@router.callback_query(StateFilter(FacilityForm), F.data == "facback:type")
async def cb_facility_back_type(call: CallbackQuery, state: FSMContext) -> None:
    """بازگشت به انتخاب نوع تأسیسات."""
    await call.answer()
    await state.set_state(FacilityForm.choosing_type)
    await call.message.edit_text(
        "🏗 نوع تأسیساتی که می‌خواهید احداث کنید را انتخاب کنید:",
        reply_markup=facility_types_kb(),
    )


@router.callback_query(FacilityForm.choosing_resource, F.data.startswith("mine_res:"))
async def cb_mine_resource(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    resource = call.data.split(":")[1]
    await state.update_data(resource=resource)
    await state.set_state(FacilityForm.entering_location)
    await call.message.edit_text(
        f"⛏ معدن {RESOURCE_FA[ResourceType(resource)]}\n\n📍 محل احداث را وارد کنید:",
        reply_markup=_back_kb("mine_back"),
    )


@router.callback_query(StateFilter(FacilityForm), F.data == "mine_back")
async def cb_mine_back(call: CallbackQuery, state: FSMContext) -> None:
    """بازگشت به انتخاب منبع معدن."""
    await call.answer()
    await state.set_state(FacilityForm.choosing_resource)
    await call.message.edit_text(
        "⛏ معدن چه منبعی را می‌خواهید احداث کنید؟",
        reply_markup=mine_resources_kb(),
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

    # محدودیت ساخت: حداکثر ۳ ساخت (تأسیسات + کارخانه) در هر ۱۲ ساعت (v1.9)
    since = _utcnow() - timedelta(hours=BUILD_LIMIT_WINDOW_HOURS)
    recent = await fac_repo.count_builds_since(session, country.id, since)
    if recent >= BUILD_LIMIT_COUNT:
        await state.clear()
        await message.answer(
            f"⏳ شما در هر {fa_number(BUILD_LIMIT_WINDOW_HOURS)} ساعت حداکثر "
            f"{fa_number(BUILD_LIMIT_COUNT)} تأسیسات/کارخانه می‌توانید بسازید. "
            "لطفاً بعداً دوباره تلاش کنید.",
            reply_markup=economy_menu_kb(),
        )
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

    # v1.7: خبر احداث تأسیسات در کانال عمومی منتشر نمی‌شود؛ فقط لاگ مدیران
    # v1.9: نوع منبع تأسیسات معدنی هم در لاگ نوشته می‌شود (مثلاً «معدن آهن»)
    fac_label = FACILITY_FA[ftype]
    if facility.resource:
        try:
            fac_label = f"{FACILITY_FA[ftype]} {RESOURCE_FA[ResourceType(facility.resource)]}"
        except (ValueError, KeyError):
            pass
    await send_log(
        bot,
        "🏗 <b>احداث تأسیسات</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"تأسیسات: {fac_label}\n"
        f"محل: {location}",
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


def _back_kb(callback_data: str) -> InlineKeyboardMarkup:
    """کیبورد تک‌دکمه‌ای بازگشت به مرحله‌ی قبل (v1.8)."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=callback_data, style=STYLE_MAIN)
    ]])


async def _ask_sale_amount(target: CallbackQuery | Message, state: FSMContext, resource: str) -> None:
    """نمایش پرسش مقدار فروش با دکمه‌ی بازگشت به انتخاب منبع."""
    await state.set_state(SaleForm.entering_amount)
    unit = RESOURCE_UNIT_FA[ResourceType(resource)]
    text = (
        f"مقدار {RESOURCE_FA[ResourceType(resource)]} برای فروش را وارد کنید (به {unit}):\n"
        "می‌توانید از پسوند k/m/b استفاده کنید (مثلاً 50k)."
    )
    kb = _back_kb("sback:res")
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.callback_query(SaleForm.choosing_resource, F.data.startswith("sell_res:"))
async def cb_sell_resource(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    resource = call.data.split(":")[1]
    await state.update_data(resource=resource)
    await _ask_sale_amount(call, state, resource)


@router.callback_query(StateFilter(SaleForm), F.data == "sback:res")
async def cb_sale_back_resource(call: CallbackQuery, state: FSMContext) -> None:
    """بازگشت به انتخاب منبع فروش."""
    await call.answer()
    await state.set_state(SaleForm.choosing_resource)
    await call.message.edit_text(
        "💱 کدام منبع را می‌خواهید بفروشید؟", reply_markup=sell_resources_kb()
    )


@router.callback_query(StateFilter(SaleForm), F.data == "sback:amt")
async def cb_sale_back_amount(call: CallbackQuery, state: FSMContext) -> None:
    """بازگشت به وارد کردن مقدار فروش."""
    await call.answer()
    data = await state.get_data()
    await _ask_sale_amount(call, state, data["resource"])


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
    await _show_sale_buyers(message, state, session, country.id)


async def _show_sale_buyers(
    target: CallbackQuery | Message, state: FSMContext, session: AsyncSession, country_id: int
) -> None:
    """نمایش فهرست خریداران با دکمه‌ی بازگشت به مرحله‌ی مقدار."""
    await state.set_state(SaleForm.choosing_buyer)
    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country_id]
    kb = countries_kb(others, prefix="sell_buyer", columns=2, back_data="sback:amt")
    if isinstance(target, CallbackQuery):
        await target.message.edit_text("کشور خریدار را انتخاب کنید:", reply_markup=kb)
    else:
        await target.answer("کشور خریدار را انتخاب کنید:", reply_markup=kb)


@router.callback_query(SaleForm.choosing_buyer, F.data.startswith("sell_buyer:"))
async def cb_sell_buyer(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    buyer_id = int(call.data.split(":")[1])
    await state.update_data(buyer_id=buyer_id)
    await state.set_state(SaleForm.entering_price)
    await call.message.edit_text(
        "مبلغ فروش را به دلار وارد کنید (مثلاً 500m برای ۵۰۰ میلیون):",
        reply_markup=_back_kb("sback:buyer"),
    )


@router.callback_query(StateFilter(SaleForm), F.data == "sback:buyer")
async def cb_sale_back_buyer(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """بازگشت به انتخاب کشور خریدار."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    await _show_sale_buyers(call, state, session, country.id)


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
                        text="✅ خرید", callback_data=f"sale_accept:{sale.id}", style=STYLE_OK
                    ),
                    InlineKeyboardButton(
                        text="❌ رد", callback_data=f"sale_reject:{sale.id}", style=STYLE_NO
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
        sale_info = await transfer_sale(
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

    # اطلاع به فروشنده (در صورت کسر تعرفه‌ی آمریکا، مبلغ آن اعلام می‌شود)
    if seller and seller.owner_user_id:
        duty = sale_info.get("duty", 0) if sale_info else 0
        tariff_note = ""
        if duty and duty > 0:
            tariff_note = (
                f"\n⚠️ تعرفه‌ی {fa_number(sale_info.get('tariff_percent', 0))}٪ آمریکا "
                f"({fa_money(duty)}) کسر شد. خالص دریافتی: {fa_money(sale_info.get('net_to_seller', 0))}."
            )
        try:
            await bot.send_message(
                seller.owner_user_id,
                f"✅ {buyer.flag} {buyer.name_fa} پیشنهاد فروش شما را پذیرفت. "
                f"محموله در راه است.{tariff_note}",
            )
        except Exception:  # noqa: BLE001
            pass

    # لاگ تعرفه‌ی اجراشده: به آمریکا (پیوی) و گروه لاگ (v1.6)
    duty = sale_info.get("duty", 0) if sale_info else 0
    if duty and duty > 0 and seller is not None:
        usa = await countries_repo.get_country_by_name(session, "USA")
        y = f"{seller.flag} {seller.name_fa}"
        if usa and usa.owner_user_id:
            try:
                await bot.send_message(
                    usa.owner_user_id,
                    f"💵 شما {fa_money(duty)} از بابت تعرفۀ کشور {y} بدست آوردید.",
                )
            except Exception:  # noqa: BLE001
                pass
        await send_log(bot, f"🇺🇸 آمریکا {fa_money(duty)} بابت تعرفه اجرایی روی کشور {y} بدست آورد.")

    # خبر فوری ارسال محموله در کانال WTO: عکس تصادفی + فرمت جدید اطلاع‌رسانی
    unit = RESOURCE_UNIT_FA[ResourceType(sale.resource)]
    seller_name = f"{seller.flag} {seller.name_fa}" if seller else "?"
    buyer_name = f"{buyer.flag} {buyer.name_fa}"
    if settings.wto_channel_id is not None:
        caption = (
            "🔵 | اطلاع رسانی سازمان نقل و انتقالات جهانی\n\n"
            f"✈ | یک محموله تجاری کشور {seller_name} را به مقصد کشور {buyer_name} ترک کرد.\n"
            f"⏳ | مدت زمان پرواز: {fa_number(minutes)} دقیقه"
        )
        await send_photo_news(bot, settings.wto_channel_id, "wto", caption)

    # لاگ تجارت به گروه لاگ مدیران: فروشنده، خریدار، منبع و مقدار، قیمت
    # + دکمه‌ی «تحویل فوری» برای مدیران (v1.8)
    deliver_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="⚡️ تحویل فوری محموله", callback_data=f"gdeliver:res:{sale.id}", style=STYLE_OK
        )
    ]])
    await send_log(
        bot,
        "🧾 <b>گزارش تجارت</b>\n"
        f"فروشنده: {seller_name}\n"
        f"خریدار: {buyer_name}\n"
        f"منبع: {fa_number(sale.amount)} {unit} {rname}\n"
        f"قیمت: {fa_money(sale.price)}",
        reply_markup=deliver_kb,
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


# ============================================================
#  🇺🇸 سیستم تعرفه‌ی بین‌المللی آمریکا (v1.5) — قابلیت انحصاری
# ============================================================
def _tariff_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ تعیین/تغییر تعرفه", callback_data="tariff:add", style=STYLE_MAIN)],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu:economy", style=STYLE_MAIN)],
    ])


@router.callback_query(F.data == "econ:tariffs")
async def cb_tariffs(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """نمایش پنل تعرفه‌ها (فقط برای آمریکا)."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if not _is_usa(country):
        await call.message.edit_text(
            "⛔️ وضع تعرفه یک قابلیت انحصاری است و فقط آمریکا می‌تواند از آن استفاده کند.",
            reply_markup=economy_menu_kb(),
        )
        return

    tariffs = await tariff_repo.list_tariffs(session)
    lines = [
        "🇺🇸 <b>تعرفه‌های بین‌المللی آمریکا</b>",
        f"🏦 عوارض جمع‌آوری‌شده: {fa_money(country.international_duties)}",
        "",
    ]
    if tariffs:
        lines.append("<b>تعرفه‌های فعال:</b>")
        for t in tariffs:
            tc = await countries_repo.get_country(session, t.target_country)
            if tc:
                lines.append(f"• {tc.flag} {tc.name_fa}: {fa_number(t.percent)}٪")
    else:
        lines.append("هیچ تعرفه‌ی فعالی وجود ندارد.")
    await call.message.edit_text("\n".join(lines), reply_markup=_tariff_menu_kb())


@router.callback_query(F.data == "tariff:add")
async def cb_tariff_add(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """انتخاب کشور برای تعیین تعرفه."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if not _is_usa(country):
        await call.answer("فقط آمریکا مجاز است.", show_alert=True)
        return
    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id]
    await call.message.edit_text(
        "کدام کشور را تعرفه‌گذاری می‌کنید؟",
        reply_markup=countries_kb(others, prefix="tariff_pick", columns=2, back_data="econ:tariffs"),
    )


@router.callback_query(F.data.startswith("tariff_pick:"))
async def cb_tariff_pick(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """درخواست درصد تعرفه برای کشور انتخاب‌شده."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if not _is_usa(country):
        await call.answer("فقط آمریکا مجاز است.", show_alert=True)
        return
    target_id = int(call.data.split(":")[1])
    target = await countries_repo.get_country(session, target_id)
    await state.update_data(target_id=target_id)
    await state.set_state(TariffForm.entering_percent)
    await call.message.edit_text(
        f"درصد تعرفه برای {target.flag} {target.name_fa} را وارد کنید (۰ تا ۱۰۰).\n"
        "عدد ۰ یعنی حذف تعرفه.",
        reply_markup=_back_kb("econ:tariffs"),
    )


@router.message(TariffForm.entering_percent, F.text)
async def msg_tariff_percent(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """ثبت درصد تعرفه."""
    country = await get_player_country(session, db_user)
    if not _is_usa(country):
        await state.clear()
        return
    percent = parse_amount(message.text)
    if percent is None or percent < 0 or percent > 100:
        await message.answer("لطفاً عددی بین ۰ تا ۱۰۰ وارد کنید.")
        return
    data = await state.get_data()
    target = await countries_repo.get_country(session, data["target_id"])
    await state.clear()
    await tariff_repo.set_tariff(session, data["target_id"], percent)

    if percent <= 0:
        await message.answer(
            f"✅ تعرفه‌ی {target.flag} {target.name_fa} حذف شد.",
            reply_markup=economy_menu_kb(is_usa=True),
        )
    else:
        await message.answer(
            f"✅ تعرفه‌ی {fa_number(percent)}٪ برای {target.flag} {target.name_fa} ثبت شد.\n"
            "این درصد از هر فروش آن کشور کسر و به خزانه‌ی آمریکا واریز می‌شود.",
            reply_markup=economy_menu_kb(is_usa=True),
        )
        # لاگ وضع تعرفه به گروه لاگ (v1.6)
        await send_log(
            bot,
            f"🇺🇸 <b>تعرفه جدید</b>\n"
            f"کشور: {target.flag} {target.name_fa}\n"
            f"درصد تعرفه اجرایی: {fa_number(percent)}٪",
        )
        # خبر تعرفه در کانال اقتصاد: عکس ترامپ + متن (v1.6)
        if settings.news_economy_channel_id is not None:
            caption = (
                "❌تعرفه❌\n\n"
                f" 🇺🇸 | رئیس جمهوری ایالات متحدۀ امریکا، دونالد ترامپ یک تعرفۀ "
                f"{fa_number(percent)} درصدی بر واردات کشور {target.flag} {target.name_fa} وضع کرد!!!\n"
                "⚪ | اطلاعات بیشتر مربوط به این تعرفۀ وضع شده بزودی منتشر میگردد..."
            )
            await send_photo_news(bot, settings.news_economy_channel_id, "trump", caption)
