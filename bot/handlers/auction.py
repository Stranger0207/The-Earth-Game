"""
هندلر سیستم مزایده منابع طبیعی (v2.2):
ایجاد مزایده، شرکت در مزایده با کارمزد ۲۰۰ میلیون دلاری، لغو مزایده و ارسال خودکار محموله WTO به برنده.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import AUCTION_ENTRY_FEE, AUCTION_MAX_HOURS, AUCTION_MIN_HOURS
from ..database.models import Auction, ResourceSale, User
from ..database.repositories import (
    auctions as auctions_repo,
    countries as countries_repo,
    reserves as reserves_repo,
)
from ..enums import (
    AuctionStatus,
    NewsCategory,
    RESOURCE_EMOJI,
    RESOURCE_FA,
    RESOURCE_UNIT_FA,
    ResourceType,
    TradeStatus,
)
from ..keyboards.common import confirm_cancel_kb
from ..keyboards.economy import (
    auction_durations_kb,
    auction_menu_kb,
    auction_resources_kb,
)
from ..loader import bot
from ..services.ai import evaluators
from ..services.news_service import publish_news, send_log
from ..states import AuctionBidForm, AuctionCreateForm
from ..utils.numbers import fa_money, fa_number, parse_amount
from ..utils.screens import safe_edit
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK
from .deps import NO_COUNTRY_TEXT, assert_feature, get_player_country

router = Router(name="auction")


def _back_auc_kb() -> InlineKeyboardMarkup:
    """دکمه‌ی بازگشت به منوی مزایده."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 بازگشت به مزایده", callback_data="econ:auction", style=STYLE_MAIN)]
        ]
    )


def _format_time_left(target: datetime) -> str:
    """فرمت فارسی زمان باقی‌مانده تا پایان مزایده."""
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


def _auction_info_text(auction: Auction, seller, winner, bid_count: int) -> str:
    """متن گزارش جامع وضعیت یک مزایده."""
    try:
        rtype = ResourceType(auction.resource)
        r_name = RESOURCE_FA[rtype]
        r_unit = RESOURCE_UNIT_FA[rtype]
        r_emoji = RESOURCE_EMOJI[rtype]
    except Exception:
        r_name, r_unit, r_emoji = auction.resource, "", "📦"

    seller_name = f"{seller.flag} {seller.name_fa}" if seller else "نامشخص"
    winner_name = f"{winner.flag} {winner.name_fa}" if winner else "هنوز پیشنهادی ثبت نشده"
    rem_time = _format_time_left(auction.ends_at)

    status_fa = {
        AuctionStatus.ACTIVE: "🟢 در حال برگزاری",
        AuctionStatus.COMPLETED: "🏁 به پایان رسیده",
        AuctionStatus.CANCELLED: "❌ لغوشده / منقضی",
    }.get(auction.status, auction.status)

    highest_bid_text = (
        fa_money(auction.highest_bid) if auction.highest_bid > 0 else "بدون پیشنهاد"
    )

    return (
        f"🏷 <b>مزایده شماره #{auction.id}</b>\n\n"
        f"وضعیت: <b>{status_fa}</b>\n"
        f"🏛 <b>فروشنده:</b> {seller_name}\n"
        f"📦 <b>منبع:</b> {r_emoji} {fa_number(auction.amount)} {r_unit} {r_name}\n"
        f"💵 <b>قیمت پایه:</b> {fa_money(auction.base_price)}\n"
        f"💰 <b>بالاترین پیشنهاد:</b> {highest_bid_text}\n"
        f"👑 <b>پیشنهاددهنده برتر:</b> {winner_name}\n"
        f"👥 <b>تعداد پیشنهادات:</b> {fa_number(bid_count)}\n"
        f"⏳ <b>زمان باقی‌مانده:</b> {rem_time}\n"
    )


# ============================================================
#  تسویه نهایی مزایده (اتمام و صدور محموله WTO)
# ============================================================
async def finalize_auction(session: AsyncSession, auction: Auction) -> None:
    """
    تسویه مزایده:
    - در صورت نبود پیشنهاد: عودت منبع به فروشنده.
    - در صورت وجود برنده: کسر وجه از برنده، واریز به فروشنده و ایجاد محموله WTO (in_transit).
    """
    if auction.status != AuctionStatus.ACTIVE:
        return

    now = datetime.now(timezone.utc)
    seller = await countries_repo.get_country(session, auction.seller_country_id)
    try:
        rtype = ResourceType(auction.resource)
        r_name = RESOURCE_FA[rtype]
        r_unit = RESOURCE_UNIT_FA[rtype]
        r_emoji = RESOURCE_EMOJI[rtype]
    except Exception:
        r_name, r_unit, r_emoji = auction.resource, "", "📦"

    # ۱. اگر هیچ پیشنهادی ثبت نشده باشد
    if not auction.highest_bidder_country_id or auction.highest_bid <= 0:
        auction.status = AuctionStatus.CANCELLED
        # عودت منبع به انبار فروشنده
        await reserves_repo.ensure_reserve(session, auction.seller_country_id, auction.resource)
        await reserves_repo.add_amount(
            session, auction.seller_country_id, auction.resource, auction.amount
        )

        if seller and seller.owner_user_id:
            try:
                await bot.send_message(
                    seller.owner_user_id,
                    f"🏷 مزایده شماره #{auction.id} ({fa_number(auction.amount)} {r_unit} {r_name}) "
                    f"بدون ثبت پیشنهاد به پایان رسید و منابع به انبار کشورتان بازگردانده شد.",
                )
            except Exception:
                pass

        await send_log(
            bot,
            f"🏷 <b>پایان مزایده بدون پیشنهاد</b>\n"
            f"شناسه مزایده: #{auction.id}\n"
            f"فروشنده: {seller.flag if seller else ''} {seller.name_fa if seller else '?'}\n"
            f"منابع عودت داده شد.",
        )
        return

    # ۲. اگر برنده وجود دارد
    winner = await countries_repo.get_country(session, auction.highest_bidder_country_id)
    auction.status = AuctionStatus.COMPLETED

    final_price = auction.highest_bid
    if winner:
        winner.budget = (winner.budget or 0.0) - final_price
    if seller:
        seller.budget = (seller.budget or 0.0) + final_price

    # تخمین زمان حمل و نقل توسط هوش مصنوعی
    eta_data = await evaluators.estimate_shipping_time(
        seller.name_fa if seller else "?",
        winner.name_fa if winner else "?",
        r_name,
        auction.amount,
    )
    minutes = int(eta_data.get("shipping_minutes", 30) or 30)
    minutes = max(5, min(minutes, 120))
    ship_eta = now + timedelta(minutes=minutes)

    # ایجاد رکورد رسمی فروش و محموله WTO
    sale = ResourceSale(
        seller_country=auction.seller_country_id,
        buyer_country=auction.highest_bidder_country_id,
        resource=auction.resource,
        amount=auction.amount,
        price=final_price,
        status=TradeStatus.IN_TRANSIT,
        ship_eta=ship_eta,
    )
    session.add(sale)

    seller_name = f"{seller.flag} {seller.name_fa}" if seller else "?"
    winner_name = f"{winner.flag} {winner.name_fa}" if winner else "?"

    # ارسال خبر رسمی در کانال اقتصاد
    news_text = (
        f"🏆 <b>پایان مزایده استراتژیک منابع طبیعی!</b>\n\n"
        f"📦 <b>کالای مزایده:</b> {r_emoji} {fa_number(auction.amount)} {r_unit} {r_name}\n"
        f"🏛 <b>فروشنده:</b> {seller_name}\n"
        f"👑 <b>برنده مزایده:</b> {winner_name}\n"
        f"💰 <b>مبلغ نهایی معامله:</b> {fa_money(final_price)}\n"
        f"🚢 محموله توسط <b>سازمان انتقالات جهانی (WTO)</b> بارگیری شده و ظرف حدود {fa_number(minutes)} دقیقه آینده تحویل داده خواهد شد."
    )
    await publish_news(bot, NewsCategory.ECONOMY, news_text)

    # اطلاع به خریدار (برنده)
    if winner and winner.owner_user_id:
        try:
            await bot.send_message(
                winner.owner_user_id,
                f"🎉 <b>تبریک! شما برنده مزایده #{auction.id} شدید.</b>\n\n"
                f"منبع: {fa_number(auction.amount)} {r_unit} {r_name}\n"
                f"مبلغ پرداختی: {fa_money(final_price)}\n"
                f"محموله شما توسط سازمان WTO ارسال گردید و تا {fa_number(minutes)} دقیقه دیگر به دست شما می‌رسد.",
            )
        except Exception:
            pass

    # اطلاع به فروشنده
    if seller and seller.owner_user_id:
        try:
            await bot.send_message(
                seller.owner_user_id,
                f"💰 <b>مزایده #{auction.id} با موفقیت به پایان رسید.</b>\n\n"
                f"خریدار: {winner_name}\n"
                f"مبلغ واریزی به خزانه‌تان: {fa_money(final_price)}\n"
                f"محموله با سازمان WTO به سمت مقصد حرکت کرد.",
            )
        except Exception:
            pass

    # لاگ مدیریت
    await send_log(
        bot,
        f"🏷 <b>تسویه مزایده #{auction.id}</b>\n"
        f"فروشنده: {seller_name}\n"
        f"برنده: {winner_name}\n"
        f"مبلغ: {fa_money(final_price)}\n"
        f"منبع: {fa_number(auction.amount)} {r_unit} {r_name}",
    )


# ============================================================
#  نمایش صفحه مزایده (قابل فراخوانی از دیپ‌لینک و دکمه)
# ============================================================
async def show_auction_details(
    event: Message | CallbackQuery,
    session: AsyncSession,
    db_user: User,
    auction_id: int,
) -> None:
    """نمایش مشخصات یک مزایده به کاربر همراه با دکمه‌های کنترلی متناسب."""
    country = await get_player_country(session, db_user)
    auction = await auctions_repo.get_auction(session, auction_id)

    if not auction:
        text = "⛔️ مزایده موردنظر یافت نشد یا حذف شده است."
        if isinstance(event, CallbackQuery):
            await safe_edit(event, text, reply_markup=_back_auc_kb())
        else:
            await event.answer(text, reply_markup=_back_auc_kb())
        return

    seller = await countries_repo.get_country(session, auction.seller_country_id)
    winner = (
        await countries_repo.get_country(session, auction.highest_bidder_country_id)
        if auction.highest_bidder_country_id
        else None
    )
    bid_count = await auctions_repo.count_bids(session, auction.id)
    card_text = _auction_info_text(auction, seller, winner, bid_count)

    builder = InlineKeyboardBuilder()

    # اگر کاربر، کشور نداشته باشد
    if not country:
        builder.button(text="🌍 کشورگیری برای شرکت", callback_data="claim:start", style=STYLE_MAIN)
        builder.button(text="🔙 بازگشت", callback_data="menu:main", style=STYLE_MAIN)
        builder.adjust(1, 1)
        if isinstance(event, CallbackQuery):
            await safe_edit(event, card_text + "\n\n<i>برای شرکت در مزایده باید کشوری داشته باشید.</i>", reply_markup=builder.as_markup())
        else:
            await event.answer(card_text + "\n\n<i>برای شرکت در مزایده باید کشوری داشته باشید.</i>", reply_markup=builder.as_markup())
        return

    is_seller = country.id == auction.seller_country_id

    if auction.status == AuctionStatus.ACTIVE:
        if is_seller:
            # اگر هیچ پیشنهادی ثبت نشده باشد، فروشنده می‌تواند مزایده را لغو کند
            if bid_count == 0:
                builder.button(text="❌ لغو مزایده و بازگشت منبع", callback_data=f"auc_cancel:{auction.id}", style=STYLE_NO)
            else:
                # اگر پیشنهاد ثبت شده باشد، می‌تواند پایان زودهنگام بزند
                builder.button(text="🏁 پایان زودهنگام مزایده", callback_data=f"auc_end:{auction.id}", style=STYLE_OK)
        else:
            builder.button(
                text="💰 شرکت و ثبت پیشنهاد (۲۰۰M کارمزد)",
                callback_data=f"auc_bid:{auction.id}",
                style=STYLE_OK,
            )

    builder.button(text="🔙 بازگشت به مزایده‌ها", callback_data="auc:active:0", style=STYLE_MAIN)
    builder.adjust(1, 1)

    if isinstance(event, CallbackQuery):
        await safe_edit(event, card_text, reply_markup=builder.as_markup())
    else:
        await event.answer(card_text, reply_markup=builder.as_markup())


# ============================================================
#  منوی اصلی مزایده
# ============================================================
@router.callback_query(F.data == "econ:auction")
async def cb_auction_menu(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    await state.clear()
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "econ.auction"):
        return

    text = (
        f"🏷 <b>سیستم مزایده منابع طبیعی {country.flag} {country.name_fa}</b>\n\n"
        "در این بخش می‌توانید منابع طبیعی خود را به بالاترین پیشنهاد قیمت به مزایده بگذارید "
        "یا در مزایده‌های سایر کشورها شرکت کنید.\n\n"
        "💡 <b>قوانین کلیدی:</b>\n"
        f"• هزینه ورود و ثبت پیشنهاد در هر مزایده <b>{fa_money(AUCTION_ENTRY_FEE)}</b> است که مستقیماً کسر و سوزانده می‌شود.\n"
        "• پس از پایان مزایده، مبلغ به حساب فروشنده واریز و منبع با محموله رسمی WTO برای برنده ارسال می‌گردد.\n"
        "• تا زمانی که پیشنهادی ثبت نشده باشد، فروشنده حق لغو مزایده را دارد."
    )
    await safe_edit(call, text, reply_markup=auction_menu_kb())


# ============================================================
#  مشاهده مزایده‌های فعال
# ============================================================
@router.callback_query(F.data.startswith("auc:active:"))
async def cb_active_auctions(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    page = int(call.data.split(":")[2])
    auctions = await auctions_repo.list_active_auctions(session)

    if not auctions:
        text = "🏷 <b>مزایده‌های فعال</b>\n\nدر حال حاضر هیچ مزایده‌ی فعالی در جریان نیست."
        builder = InlineKeyboardBuilder()
        builder.button(text="➕ ثبت اولین مزایده", callback_data="auc:create", style=STYLE_OK)
        builder.button(text="🔙 بازگشت", callback_data="econ:auction", style=STYLE_MAIN)
        builder.adjust(1, 1)
        await safe_edit(call, text, reply_markup=builder.as_markup())
        return

    per_page = 5
    total_pages = (len(auctions) + per_page - 1) // per_page
    page = max(0, min(page, total_pages - 1))
    slice_auctions = auctions[page * per_page : (page + 1) * per_page]

    builder = InlineKeyboardBuilder()
    for a in slice_auctions:
        r_name = RESOURCE_FA.get(ResourceType(a.resource), a.resource)
        r_unit = RESOURCE_UNIT_FA.get(ResourceType(a.resource), "")
        r_emoji = RESOURCE_EMOJI.get(ResourceType(a.resource), "📦")
        price_text = fa_money(a.highest_bid if a.highest_bid > 0 else a.base_price)
        builder.button(
            text=f"{r_emoji} #{a.id} {fa_number(a.amount)} {r_unit} {r_name} | {price_text}",
            callback_data=f"auc_view:{a.id}",
            style=STYLE_MAIN,
        )

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ صفحه قبلی", callback_data=f"auc:active:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="صفحه بعدی ▶️", callback_data=f"auc:active:{page + 1}"))
    if nav:
        builder.row(*nav)

    builder.row(InlineKeyboardButton(text="🔙 بازگشت به منوی مزایده", callback_data="econ:auction", style=STYLE_MAIN))
    builder.adjust(1)

    text = f"🏷 <b>فهرست مزایده‌های فعال جهانی (صفحه {fa_number(page + 1)} از {fa_number(total_pages)}):</b>"
    await safe_edit(call, text, reply_markup=builder.as_markup())


# ============================================================
#  مشاهده مزایده‌های من
# ============================================================
@router.callback_query(F.data.startswith("auc:mine:"))
async def cb_my_auctions(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    page = int(call.data.split(":")[2])
    auctions = await auctions_repo.list_seller_auctions(session, country.id, active_only=False)

    if not auctions:
        text = "📋 <b>مزایده‌های من</b>\n\nشما تاکنون هیچ مزایده‌ای ثبت نکرده‌اید."
        builder = InlineKeyboardBuilder()
        builder.button(text="➕ ثبت مزایده جدید", callback_data="auc:create", style=STYLE_OK)
        builder.button(text="🔙 بازگشت", callback_data="econ:auction", style=STYLE_MAIN)
        builder.adjust(1, 1)
        await safe_edit(call, text, reply_markup=builder.as_markup())
        return

    per_page = 5
    total_pages = (len(auctions) + per_page - 1) // per_page
    page = max(0, min(page, total_pages - 1))
    slice_auctions = auctions[page * per_page : (page + 1) * per_page]

    builder = InlineKeyboardBuilder()
    for a in slice_auctions:
        r_name = RESOURCE_FA.get(ResourceType(a.resource), a.resource)
        r_unit = RESOURCE_UNIT_FA.get(ResourceType(a.resource), "")
        status_icon = "🟢" if a.status == AuctionStatus.ACTIVE else ("🏁" if a.status == AuctionStatus.COMPLETED else "❌")
        builder.button(
            text=f"{status_icon} #{a.id} {fa_number(a.amount)} {r_unit} {r_name}",
            callback_data=f"auc_view:{a.id}",
            style=STYLE_MAIN,
        )

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ صفحه قبلی", callback_data=f"auc:mine:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="صفحه بعدی ▶️", callback_data=f"auc:mine:{page + 1}"))
    if nav:
        builder.row(*nav)

    builder.row(InlineKeyboardButton(text="🔙 بازگشت به منوی مزایده", callback_data="econ:auction", style=STYLE_MAIN))
    builder.adjust(1)

    text = f"📋 <b>مزایده‌های ثبت‌شده توسط شما (صفحه {fa_number(page + 1)} از {fa_number(total_pages)}):</b>"
    await safe_edit(call, text, reply_markup=builder.as_markup())


# ============================================================
#  مشاهده جزئیات یک مزایده
# ============================================================
@router.callback_query(F.data.startswith("auc_view:"))
async def cb_auction_view(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    await call.answer()
    auction_id = int(call.data.split(":")[1])
    await show_auction_details(call, session, db_user, auction_id)


# ============================================================
#  ایجاد مزایده جدید
# ============================================================
@router.callback_query(F.data == "auc:create")
async def cb_auction_create_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    await state.clear()
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "econ.auction"):
        return

    await state.set_state(AuctionCreateForm.choosing_resource)
    await safe_edit(
        call,
        "➕ <b>ایجاد مزایده جدید منابع طبیعی</b>\n\n"
        "کدام منبع طبیعی خود را می‌خواهید به مزایده بگذارید؟",
        reply_markup=auction_resources_kb(),
    )


@router.callback_query(AuctionCreateForm.choosing_resource, F.data.startswith("auc_res:"))
async def cb_auction_res_picked(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    resource_key = call.data.split(":")[1]
    reserve = await reserves_repo.get_reserve(session, country.id, resource_key)
    current_stock = reserve.amount if reserve else 0.0

    if current_stock <= 0:
        await call.answer("شما هیچ ذخیره‌ای از این منبع در انبار خود ندارید.", show_alert=True)
        return

    r_name = RESOURCE_FA.get(ResourceType(resource_key), resource_key)
    r_unit = RESOURCE_UNIT_FA.get(ResourceType(resource_key), "")

    await state.update_data(resource=resource_key, max_stock=current_stock)
    await state.set_state(AuctionCreateForm.entering_amount)
    await call.message.edit_text(
        f"📦 <b>تعیین مقدار منبع برای مزایده</b>\n\n"
        f"منبع انتخابی: <b>{r_name}</b>\n"
        f"موجودی انبار شما: <b>{fa_number(current_stock)} {r_unit}</b>\n\n"
        f"چه مقداری از این منبع را می‌خواهید به مزایده بگذارید؟ (عدد وارد کنید)",
        reply_markup=_back_auc_kb(),
    )


@router.message(AuctionCreateForm.entering_amount, F.text)
async def msg_auction_amount(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    raw = parse_amount(message.text)
    if raw is None or raw <= 0:
        await message.answer("لطفاً یک عدد مثبت و معتبر وارد کنید.")
        return

    data = await state.get_data()
    max_stock = data.get("max_stock", 0.0)
    if raw > max_stock:
        await message.answer(
            f"⛔️ مقدار واردشده بیشتر از موجودی انبار شما ({fa_number(max_stock)}) است.\n"
            "لطفاً مقدار کمتری وارد فرمایید:",
            reply_markup=_back_auc_kb(),
        )
        return

    await state.update_data(amount=raw)
    await state.set_state(AuctionCreateForm.entering_base_price)
    await message.answer(
        "💵 <b>تعیین قیمت پایه مزایده</b>\n\n"
        "حداقل قیمت اولیه برای شروع مزایده چقدر باشد؟ (به دلار، مثلاً 100m یا 1b):",
        reply_markup=_back_auc_kb(),
    )


@router.message(AuctionCreateForm.entering_base_price, F.text)
async def msg_auction_base_price(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    price = parse_amount(message.text)
    if price is None or price <= 0:
        await message.answer("لطفاً یک مبلغ دلاری معتبر وارد کنید (مثلاً 500m یا 2b).")
        return

    await state.update_data(base_price=price)
    await state.set_state(AuctionCreateForm.entering_duration)
    await message.answer(
        "⏱ <b>تعیین مدت زمان مزایده</b>\n\n"
        "مزایده تا چند ساعت فعال باشد؟ (بین ۱ تا ۷۲ ساعت، یا انتخاب گزینه‌های زیر):",
        reply_markup=auction_durations_kb(),
    )


@router.callback_query(AuctionCreateForm.entering_duration, F.data.startswith("auc_dur:"))
async def cb_auction_duration_pick(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    await call.answer()
    hours = int(call.data.split(":")[1])
    await _proceed_to_auction_confirm(call.message, state, session, db_user, hours)


@router.message(AuctionCreateForm.entering_duration, F.text)
async def msg_auction_duration_text(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    try:
        hours = int(message.text.strip())
    except ValueError:
        await message.answer("لطفاً یک عدد صحیح بین ۱ تا ۷۲ وارد کنید.")
        return
    if hours < AUCTION_MIN_HOURS or hours > AUCTION_MAX_HOURS:
        await message.answer(
            f"مدت زمان مزایده باید بین {fa_number(AUCTION_MIN_HOURS)} تا {fa_number(AUCTION_MAX_HOURS)} ساعت باشد."
        )
        return
    await _proceed_to_auction_confirm(message, state, session, db_user, hours)


async def _proceed_to_auction_confirm(
    target_msg: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    hours: int,
) -> None:
    country = await get_player_country(session, db_user)
    if country is None:
        await target_msg.answer(NO_COUNTRY_TEXT)
        return

    data = await state.get_data()
    resource_key = data["resource"]
    amount = data["amount"]
    base_price = data["base_price"]

    await state.update_data(duration_hours=hours)
    await state.set_state(AuctionCreateForm.confirming)

    r_name = RESOURCE_FA.get(ResourceType(resource_key), resource_key)
    r_unit = RESOURCE_UNIT_FA.get(ResourceType(resource_key), "")

    text = (
        f"❓ <b>تأیید نهایی ایجاد مزایده</b>\n\n"
        f"📦 <b>منبع:</b> {fa_number(amount)} {r_unit} {r_name}\n"
        f"💵 <b>قیمت پایه:</b> {fa_money(base_price)}\n"
        f"⏳ <b>مدت زمان:</b> {fa_number(hours)} ساعت\n\n"
        "⚠️ <i>توجه: مقدار فوق بلافاصله در انبار شما مسدود/رزرو می‌شود تا مزایده به اتمام برسد. "
        "در صورتی که هیچ پیشنهادی ثبت نشود، منبع به انبار شما عودت داده خواهد شد.</i>\n\n"
        "آیا با آغاز این مزایده موافقید؟"
    )
    await target_msg.answer(text, reply_markup=confirm_cancel_kb("auc:confirm"))


@router.callback_query(AuctionCreateForm.confirming, F.data == "auc:confirm")
async def cb_auction_create_confirm(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    await call.answer()
    data = await state.get_data()
    await state.clear()

    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return

    resource_key = data["resource"]
    amount = float(data["amount"])
    base_price = float(data["base_price"])
    hours = int(data["duration_hours"])

    # اعتبارسنجی مجدد انبار
    reserve = await reserves_repo.get_reserve(session, country.id, resource_key)
    if not reserve or reserve.amount < amount:
        await call.message.edit_text("⛔️ موجودی انبار شما برای آغاز مزایده کافی نیست.", reply_markup=_back_auc_kb())
        return

    # ۱. کسر منبع از انبار فروشنده جهت بلوکه شدن
    await reserves_repo.add_amount(session, country.id, resource_key, -amount)

    # ۲. ایجاد رکورد مزایده
    now = datetime.now(timezone.utc)
    ends_at = now + timedelta(hours=hours)

    auction = await auctions_repo.create_auction(
        session=session,
        seller_country_id=country.id,
        resource=resource_key,
        amount=amount,
        base_price=base_price,
        ends_at=ends_at,
    )

    r_name = RESOURCE_FA.get(ResourceType(resource_key), resource_key)
    r_unit = RESOURCE_UNIT_FA.get(ResourceType(resource_key), "")
    r_emoji = RESOURCE_EMOJI.get(ResourceType(resource_key), "📦")

    # ۳. ارسال خبر در کانال اخبار اقتصادی همراه با دکمه دیپ‌لینک
    settings = get_settings()
    bot_info = await bot.get_me()

    channel_text = (
        f"📢 <b>مزایده جدید منابع استراتژیک!</b>\n\n"
        f"کشور <b>{country.flag} {country.name_fa}</b> مقدار <b>{fa_number(amount)} {r_unit} {r_name}</b> {r_emoji} را به مزایده عمومی گذاشت.\n\n"
        f"💵 <b>قیمت پایه:</b> {fa_money(base_price)}\n"
        f"⏳ <b>مهلت شرکت در مزایده:</b> {fa_number(hours)} ساعت\n\n"
        f"<i>جهت ثبت پیشنهاد و شرکت در مزایده، دکمه‌ی زیر را لمس کنید:</i>"
    )

    deep_link_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏷 شرکت در مزایده",
                    url=f"https://t.me/{bot_info.username}?start=auc_{auction.id}",
                )
            ]
        ]
    )

    if settings.news_economy_channel_id:
        try:
            msg = await bot.send_message(
                settings.news_economy_channel_id, channel_text, reply_markup=deep_link_kb
            )
            auction.channel_message_id = msg.message_id
        except Exception:
            pass

    await call.message.edit_text(
        f"✅ <b>مزایده با موفقیت ثبت و آغاز گردید!</b>\n\n"
        f"شناسه مزایده: #{auction.id}\n"
        f"کالا: {fa_number(amount)} {r_unit} {r_name}\n"
        f"قیمت پایه: {fa_money(base_price)}\n"
        f"اطلاعیه در کانال اقتصاد منتشر شد.",
        reply_markup=_back_auc_kb(),
    )

    await send_log(
        bot,
        f"🏷 <b>ثبت مزایده جدید</b>\n"
        f"شناسه: #{auction.id}\n"
        f"فروشنده: {country.flag} {country.name_fa}\n"
        f"منبع: {fa_number(amount)} {r_unit} {r_name}\n"
        f"قیمت پایه: {fa_money(base_price)}",
    )


# ============================================================
#  لغو مزایده توسط فروشنده (قبل از ثبت پیشنهاد)
# ============================================================
@router.callback_query(F.data.startswith("auc_cancel:"))
async def cb_auction_cancel(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    await call.answer()
    auction_id = int(call.data.split(":")[1])
    country = await get_player_country(session, db_user)
    auction = await auctions_repo.get_auction(session, auction_id)

    if not auction or auction.status != AuctionStatus.ACTIVE:
        await call.message.edit_text("این مزایده دیگر فعال نیست.", reply_markup=_back_auc_kb())
        return

    if country is None or auction.seller_country_id != country.id:
        await call.answer("شما فقط مجاز به لغو مزایده‌های خودتان هستید.", show_alert=True)
        return

    bid_count = await auctions_repo.count_bids(session, auction.id)
    if bid_count > 0:
        await call.answer("این مزایده دارای پیشنهاد فعال است و امکان لغو ندارد.", show_alert=True)
        return

    # لغو مزایده و بازگرداندن منابع
    auction.status = AuctionStatus.CANCELLED
    await reserves_repo.ensure_reserve(session, country.id, auction.resource)
    await reserves_repo.add_amount(session, country.id, auction.resource, auction.amount)

    r_name = RESOURCE_FA.get(ResourceType(auction.resource), auction.resource)
    r_unit = RESOURCE_UNIT_FA.get(ResourceType(auction.resource), "")

    await call.message.edit_text(
        f"✅ مزایده #{auction.id} با موفقیت لغو شد و {fa_number(auction.amount)} {r_unit} {r_name} به انبار شما بازگردانده شد.",
        reply_markup=_back_auc_kb(),
    )

    await send_log(
        bot,
        f"❌ <b>لغو مزایده توسط فروشنده</b>\n"
        f"مزایده: #{auction.id}\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"منابع بازگردانده شد.",
    )


# ============================================================
#  پایان زودهنگام مزایده توسط فروشنده
# ============================================================
@router.callback_query(F.data.startswith("auc_end:"))
async def cb_auction_end_early(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    await call.answer()
    auction_id = int(call.data.split(":")[1])
    country = await get_player_country(session, db_user)
    auction = await auctions_repo.get_auction(session, auction_id)

    if not auction or auction.status != AuctionStatus.ACTIVE:
        await call.message.edit_text("این مزایده دیگر فعال نیست.", reply_markup=_back_auc_kb())
        return

    if country is None or auction.seller_country_id != country.id:
        await call.answer("شما مالک این مزایده نیستید.", show_alert=True)
        return

    await finalize_auction(session, auction)
    await call.message.edit_text(
        f"🏁 مزایده #{auction.id} به پایان رسید و مراحل انتقال کالا و وجه آغاز شد.",
        reply_markup=_back_auc_kb(),
    )


# ============================================================
#  شرکت در مزایده و ثبت پیشنهاد قیمت (Bidding)
# ============================================================
@router.callback_query(F.data.startswith("auc_bid:"))
async def cb_auction_bid_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    await call.answer()
    auction_id = int(call.data.split(":")[1])
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    auction = await auctions_repo.get_auction(session, auction_id)
    if not auction or auction.status != AuctionStatus.ACTIVE:
        await call.message.edit_text("این مزایده دیگر فعال نیست.", reply_markup=_back_auc_kb())
        return

    if auction.seller_country_id == country.id:
        await call.answer("شما نمی‌توانید در مزایده‌ی خودتان شرکت کنید!", show_alert=True)
        return

    # بررسی موجودی برای کارمزد ورودی ۲۰۰ میلیون دلاری
    if (country.budget or 0.0) < AUCTION_ENTRY_FEE:
        await call.answer(
            f"⛔️ بودجه‌ی شما برای پرداخت کارمزد ورودی ({fa_money(AUCTION_ENTRY_FEE)}) کافی نیست.",
            show_alert=True,
        )
        return

    min_required = auction.highest_bid if auction.highest_bid > 0 else auction.base_price

    await state.set_state(AuctionBidForm.entering_bid)
    await state.update_data(auction_id=auction.id, min_req=min_required)
    await call.message.edit_text(
        f"💰 <b>شرکت در مزایده #{auction.id}</b>\n\n"
        f"⚠️ <b>هزینه ورودی شرکت در مزایده:</b> {fa_money(AUCTION_ENTRY_FEE)} (غیرقابل استرداد)\n"
        f"💵 <b>حداقل مبلغ مجاز برای پیشنهاد:</b> بیشتر از {fa_money(min_required)}\n"
        f"خزانه فعلی شما: {fa_money(country.budget)}\n\n"
        "لطفاً مبلغ پیشنهادی خود را وارد کنید (مثلاً 1.5b یا 2t):",
        reply_markup=_back_auc_kb(),
    )


@router.message(AuctionBidForm.entering_bid, F.text)
async def msg_auction_bid_amount(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    bid_amount = parse_amount(message.text)
    if bid_amount is None or bid_amount <= 0:
        await message.answer("لطفاً یک مبلغ معتبر وارد کنید.")
        return

    country = await get_player_country(session, db_user)
    if country is None:
        await state.clear()
        await message.answer(NO_COUNTRY_TEXT)
        return

    data = await state.get_data()
    min_req = data.get("min_req", 0.0)

    if bid_amount <= min_req:
        await message.answer(
            f"⛔️ مبلغ پیشنهادی باید اکیداً بیشتر از بالاترین پیشنهاد قبلی ({fa_money(min_req)}) باشد.\n"
            "لطفاً مبلغ بالاتری وارد کنید:",
            reply_markup=_back_auc_kb(),
        )
        return

    # بررسی بودجه خریدار (کارمزد + مبلغ پیشنهاد)
    total_needed = bid_amount + AUCTION_ENTRY_FEE
    if (country.budget or 0.0) < total_needed:
        await message.answer(
            f"⛔️ موجودی شما کافی نیست!\n"
            f"مبلغ پیشنهاد: {fa_money(bid_amount)}\n"
            f"کارمزد ورودی: {fa_money(AUCTION_ENTRY_FEE)}\n"
            f"مجموع موردنیاز: {fa_money(total_needed)}\n"
            f"موجودی شما: {fa_money(country.budget)}",
            reply_markup=_back_auc_kb(),
        )
        return

    await state.update_data(bid_amount=bid_amount)
    await state.set_state(AuctionBidForm.confirming)
    await message.answer(
        f"❓ <b>تأییدیه ثبت پیشنهاد قیمت</b>\n\n"
        f"مبلغ پیشنهادی شما: {fa_money(bid_amount)}\n"
        f"کارمزد ورودی کسرشونده: {fa_money(AUCTION_ENTRY_FEE)}\n\n"
        "آیا مطمئن هستید که می‌خواهید با کسر کارمزد، این پیشنهاد را به ثبت برسانید؟",
        reply_markup=confirm_cancel_kb("auc:bid_confirm"),
    )


@router.callback_query(AuctionBidForm.confirming, F.data == "auc:bid_confirm")
async def cb_auction_bid_confirm(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    await call.answer()
    data = await state.get_data()
    await state.clear()

    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return

    auction_id = data.get("auction_id")
    bid_amount = float(data.get("bid_amount", 0))

    auction = await auctions_repo.get_auction(session, auction_id)
    if not auction or auction.status != AuctionStatus.ACTIVE:
        await call.message.edit_text("متأسفانه این مزایده دیگر فعال نیست.", reply_markup=_back_auc_kb())
        return

    # اعتبارسنجی بالاتر بودن نسبت به آخرین وضعیت
    min_req = auction.highest_bid if auction.highest_bid > 0 else auction.base_price
    if bid_amount <= min_req:
        await call.message.edit_text(
            f"⛔️ در این فاصله پیشنهاد بالاتری ({fa_money(min_req)}) ثبت شده است. پیشنهاد شما پذیرفته نشد.",
            reply_markup=_back_auc_kb(),
        )
        return

    total_needed = bid_amount + AUCTION_ENTRY_FEE
    if (country.budget or 0.0) < total_needed:
        await call.message.edit_text("⛔️ بودجه‌ی شما برای ثبت این پیشنهاد کافی نیست.", reply_markup=_back_auc_kb())
        return

    prev_bidder_id = auction.highest_bidder_country_id

    # ۱. کسر کارمزد شرکت در مزایده (سوزانده می‌شود)
    country.budget -= AUCTION_ENTRY_FEE

    # ۲. ثبت پیشنهاد در دیتابیس
    await auctions_repo.add_bid(session, auction.id, country.id, bid_amount, AUCTION_ENTRY_FEE)

    await call.message.edit_text(
        f"✅ <b>پیشنهاد شما با موفقیت ثبت گردید!</b>\n\n"
        f"مبلغ پیشنهادی: {fa_money(bid_amount)}\n"
        f"کارمزد ورودی ({fa_money(AUCTION_ENTRY_FEE)}) از خزانه‌تان کسر شد.\n"
        f"موجودی فعلی خزانه: {fa_money(country.budget)}\n\n"
        "در صورت پیروزی در مزایده، محموله به شکل خودکار برای شما ارسال خواهد شد.",
        reply_markup=_back_auc_kb(),
    )

    # ۳. اطلاع‌رسانی به پیشنهاددهنده قبلی که اوت‌بید شده است
    if prev_bidder_id and prev_bidder_id != country.id:
        prev_country = await countries_repo.get_country(session, prev_bidder_id)
        if prev_country and prev_country.owner_user_id:
            try:
                await bot.send_message(
                    prev_country.owner_user_id,
                    f"⚠️ <b>پیشنهاد شما در مزایده #{auction.id} پشت سر گذاشته شد!</b>\n\n"
                    f"کشور دیگری پیشنهاد بالاتری به مبلغ {fa_money(bid_amount)} ثبت کرد.\n"
                    f"جهت افزایش پیشنهاد می‌توانید مجدداً اقدام نمایید.",
                )
            except Exception:
                pass

    # ۴. اطلاع‌رسانی به فروشنده
    seller = await countries_repo.get_country(session, auction.seller_country_id)
    if seller and seller.owner_user_id:
        try:
            await bot.send_message(
                seller.owner_user_id,
                f"📈 <b>پیشنهاد جدید برای مزایده #{auction.id} شما ثبت شد!</b>\n\n"
                f"پیشنهاددهنده: {country.flag} {country.name_fa}\n"
                f"مبلغ جدید: {fa_money(bid_amount)}",
            )
        except Exception:
            pass

    # ۵. لاگ سیستم
    await send_log(
        bot,
        f"💰 <b>پیشنهاد جدید در مزایده #{auction.id}</b>\n"
        f"پیشنهاددهنده: {country.flag} {country.name_fa}\n"
        f"مبلغ: {fa_money(bid_amount)}\n"
        f"کارمزد ورودی دریافت شد.",
    )
