"""
هندلر جامع سیستم انتقال تکنولوژی و لایسنس تسلیحاتی (Tech Transfer & Licensing).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database.models import MilitaryAsset, User
from ..database.repositories import countries as countries_repo
from ..database.repositories import military as mil_repo
from ..database.repositories import tech_transfer as tech_repo
from ..loader import bot
from ..services.news_service import send_log
from ..services.tech_service import get_equipment_origin, is_native_equipment
from ..states import TechTransferForm
from ..utils.numbers import fa_money, fa_number, parse_amount
from ..utils.screens import safe_edit
from ..utils.ui import DIVIDER, STYLE_MAIN, STYLE_NO, STYLE_OK, header
from .deps import NO_COUNTRY_TEXT, assert_feature, get_player_country

logger = logging.getLogger(__name__)
router = Router(name="tech_transfer")
settings = get_settings()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _back_tech_kb(callback_data: str = "tech:menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🔙 بازگشت", callback_data=callback_data, style=STYLE_MAIN)
        ]]
    )


# ============================================================
#  🔬 پنل اصلی تکنولوژی نظامی در ستاد فرماندهی
# ============================================================


@router.callback_query(F.data == "tech:menu")
async def cb_tech_menu(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """منوی اصلی تکنولوژی نظامی و لایسنس‌ها."""
    await call.answer()
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "tech_transfer"):
        return

    my_licenses = await tech_repo.list_licenses_for_country(session, country.id)
    granted_licenses = await tech_repo.list_granted_licenses_by_country(session, country.id)
    incoming_reqs = await tech_repo.list_incoming_requests(session, country.id, status="PENDING_MANUFACTURER")
    unpaid_invoices = await tech_repo.list_outgoing_requests(session, country.id, status="INVOICE_SENT")
    outgoing_reqs = await tech_repo.list_outgoing_requests(session, country.id, status="PENDING_MANUFACTURER")

    text = (
        header("پنل تکنولوژی و لایسنس تسلیحاتی", "🔬") + "\n\n"
        f"🏴 کشور: {country.flag} <b>{country.name_fa}</b>\n"
        f"{DIVIDER}\n"
        f"📜 لایسنس‌های خریداری‌شده شما: <b>{fa_number(len(my_licenses))}</b> مورد\n"
        f"🏭 لایسنس‌های واگذارشده به دیگران: <b>{fa_number(len(granted_licenses))}</b> مورد\n"
        f"📥 درخواست‌های خرید جدید (در انتظار قیمت): <b>{fa_number(len(incoming_reqs))}</b> مورد\n"
        f"🧾 فاکتورهای آماده پرداخت: <b>{fa_number(len(unpaid_invoices))}</b> مورد\n"
        f"📤 درخواست‌های ارسالی شما: <b>{fa_number(len(outgoing_reqs))}</b> مورد\n\n"
        "بخش مورد نظر را انتخاب نمایید:"
    )

    builder = InlineKeyboardBuilder()
    in_badge = f" ({fa_number(len(incoming_reqs))})" if incoming_reqs else ""
    inv_badge = f" ({fa_number(len(unpaid_invoices))})" if unpaid_invoices else ""

    builder.button(
        text="🔬 درخواست لایسنس جدید (از تجهیزات شما)",
        callback_data="tech:from_assets",
        style=STYLE_OK,
    )
    builder.button(
        text=f"📥 درخواست‌های خرید دریافتی{in_badge}",
        callback_data="tech:incoming",
        style=STYLE_OK if incoming_reqs else STYLE_MAIN,
    )
    builder.button(
        text=f"🧾 فاکتورهای آماده پرداخت{inv_badge}",
        callback_data="tech:invoices",
        style=STYLE_OK if unpaid_invoices else STYLE_MAIN,
    )
    builder.button(
        text="📤 درخواست‌های ارسالی من",
        callback_data="tech:outgoing",
        style=STYLE_MAIN,
    )
    builder.button(
        text="📜 لایسنس‌های دریافتی من",
        callback_data="tech:my_licenses",
        style=STYLE_MAIN,
    )
    builder.button(
        text="🏭 لایسنس‌های صادرشده توسط من",
        callback_data="tech:granted_licenses",
        style=STYLE_MAIN,
    )
    builder.button(text="🔙 بازگشت به ستاد فرماندهی", callback_data="menu:military", style=STYLE_MAIN)
    builder.adjust(1)

    await safe_edit(call, text, reply_markup=builder.as_markup())


# ============================================================
#  🔬 درخواست لایسنس جدید از روی لیست تجهیزات ارتش
# ============================================================


@router.callback_query(F.data == "tech:from_assets")
async def cb_tech_from_assets(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """مشاهده لیست تجهیزات غیربومی ارتش جهت درخواست لایسنس."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "tech_transfer"):
        return

    assets = await mil_repo.list_assets(session, country.id)
    # فیلتر کردن تجهیزات غیربومی (که کشور سازنده‌شان کشور خود بازیکن نیست)
    foreign_items: list[tuple[MilitaryAsset, Country | None]] = []
    for asset in assets:
        if not asset.name or asset.category == "سرباز آماده نبرد" or "پرسنل" in asset.name:
            continue
        origin_code = get_equipment_origin(asset.name)
        if origin_code and origin_code != country.name_en:
            origin_c = await countries_repo.get_country_by_name(session, origin_code)
            foreign_items.append((asset, origin_c))

    if not foreign_items:
        text = (
            header("درخواست لایسنس تکنولوژی (از تجهیزات)", "🔬") + "\n\n"
            f"🏴 کشور: {country.flag} <b>{country.name_fa}</b>\n"
            f"{DIVIDER}\n"
            "✅ <b>تمامی تجهیزات موجود در ارتش شما بومی هستند!</b>\n\n"
            "هیچ سلاح غیربومی نیازمند دریافت لایسنس در زرادخانه کشور شما یافت نشد. "
            "شما می‌توانید تمامی تجهیزات فعلی خود را بدون نیاز به مجوز در کارخانه نظامی بازتولید کنید."
        )
        await safe_edit(call, text, reply_markup=_back_tech_kb("tech:menu"))
        return

    text = (
        header("درخواست لایسنس تکنولوژی (از تجهیزات)", "🔬") + "\n\n"
        f"🏴 کشور: {country.flag} <b>{country.name_fa}</b>\n"
        f"{DIVIDER}\n"
        "در زیر لیست تجهیزات ساخت کشورهای دیگر در ارتش شما آورده شده است.\n"
        "برای مشاهده وضعیت لایسنس یا ارسال درخواست خرید تکنولوژی به کشور سازنده، روی هر قلم کلیک کنید:\n"
    )

    builder = InlineKeyboardBuilder()
    for asset, origin_c in foreign_items:
        origin_flag = origin_c.flag if origin_c else "🏳"
        origin_name = origin_c.name_fa if origin_c else (get_equipment_origin(asset.name) or "نامشخص")

        has_lic = await tech_repo.has_license(session, country.id, asset.name)
        active_req = await tech_repo.get_active_request(session, country.id, asset.name)

        if has_lic:
            btn_text = f"✅ {asset.name} (دارای لایسنس)"
            style = STYLE_OK
        elif active_req and active_req.status == "INVOICE_SENT":
            btn_text = f"🧾 {asset.name} (فاکتور آماده: {fa_money(active_req.license_price)})"
            style = STYLE_OK
        elif active_req and active_req.status == "PENDING_MANUFACTURER":
            btn_text = f"⏳ {asset.name} (در انتظار تعیین قیمت)"
            style = STYLE_MAIN
        else:
            btn_text = f"⚠️ {asset.name} [{origin_flag} {origin_name}]"
            style = STYLE_MAIN

        builder.button(
            text=btn_text,
            callback_data=f"tech_ast_info:{asset.id}",
            style=style,
        )

    builder.button(text="🔙 بازگشت به پنل تکنولوژی", callback_data="tech:menu", style=STYLE_MAIN)
    builder.adjust(1)
    await safe_edit(call, text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("tech_ast_info:"))
async def cb_tech_ast_info(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """نمایش کارت جزئیات تجهیزات و وضعیت لایسنس."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    asset_id = int(call.data.split(":")[1])
    asset = await mil_repo.get_asset(session, asset_id)
    if asset is None or asset.country_id != country.id:
        await call.answer("تجهیزات یافت نشد یا متعلق به شما نیست.", show_alert=True)
        return

    origin_code = get_equipment_origin(asset.name)
    origin_country = await countries_repo.get_country_by_name(session, origin_code) if origin_code else None
    origin_display = f"{origin_country.flag} {origin_country.name_fa}" if origin_country else (origin_code or "نامشخص")

    has_lic = await tech_repo.has_license(session, country.id, asset.name)
    active_req = await tech_repo.get_active_request(session, country.id, asset.name)

    builder = InlineKeyboardBuilder()

    if has_lic:
        st_text = "دارای لایسنس رسمی بازتولید ✅"
        desc = (
            "✅ <b>لایسنس فعال:</b> شما مجوز رسمی بازتولید این سلاح را در اختیار دارید "
            "و می‌توانید خط تولید آن را در کارخانه نظامی احداث کنید."
        )
        builder.button(text="🏭 احداث کارخانه نظامی برای این سلاح", callback_data="milfac:build", style=STYLE_OK)
    elif active_req and active_req.status == "INVOICE_SENT":
        st_text = f"فاکتور رسمی صادر شده (مبلغ: {fa_money(active_req.license_price)}) 🧾"
        desc = (
            f"🧾 کشور سازنده ({origin_display}) فاکتور رسمی به مبلغ <b>{fa_money(active_req.license_price)}</b> صادر کرده است. "
            "با پرداخت این فاکتور، لایسنس فوراً فعال خواهد شد."
        )
        builder.button(text="✅ تایید و پرداخت فاکتور", callback_data=f"tech_inv_pay:{active_req.id}", style=STYLE_OK)
        builder.button(text="❌ رد فاکتور و انصراف", callback_data=f"tech_inv_cancel:{active_req.id}", style=STYLE_NO)
    elif active_req and active_req.status == "PENDING_MANUFACTURER":
        st_text = "درخواست ارسال شده (در انتظار تعیین قیمت توسط سازنده) ⏳"
        desc = (
            f"⏳ درخواست خرید تکنولوژی برای رهبر کشور <b>{origin_display}</b> ارسال شده است. "
            "به محض مشخص شدن قیمت، فاکتور برای شما ارسال می‌گردد."
        )
        builder.button(text="❌ لغو درخواست خرید", callback_data=f"tech_req_cancel_buyer:{active_req.id}", style=STYLE_NO)
    else:
        st_text = "فاقد لایسنس بازتولید ❌"
        desc = (
            f"⚠️ این تجهیزات ساخت کشور <b>{origin_display}</b> است و شما دانش فنی و لایسنس ساخت آن را ندارید.\n\n"
            f"📩 آیا می‌خواهید درخواست دریافت لایسنس تکنولوژی را برای کشور سازنده ({origin_display}) ارسال کنید؟"
        )
        builder.button(
            text=f"✅ ارسال درخواست لایسنس به {origin_display}",
            callback_data=f"tech_ast_send:{asset.id}",
            style=STYLE_OK,
        )

    builder.button(text="🔙 بازگشت به لیست تجهیزات", callback_data="tech:from_assets", style=STYLE_MAIN)
    builder.adjust(1)

    text = (
        header("جزئیات لایسنس تکنولوژی نظامی", "🔬") + "\n\n"
        f"🔹 نام تجهیزات: <b>{asset.name}</b>\n"
        f"🔹 شاخه: <b>{asset.branch}</b> | رسته: <b>{asset.category}</b>\n"
        f"🔹 کشور سازنده اصلی: <b>{origin_display}</b>\n"
        f"🔹 موجودی در ارتش شما: <b>{fa_number(asset.count)} {asset.unit}</b>\n"
        f"🔹 وضعیت لایسنس: <b>{st_text}</b>\n"
        f"{DIVIDER}\n"
        f"{desc}"
    )

    await safe_edit(call, text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("tech_ast_send:"))
async def cb_tech_ast_send(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """ارسال مستقیم درخواست لایسنس به کشور سازنده از لیست تجهیزات."""
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "tech_transfer"):
        return

    asset_id = int(call.data.split(":")[1])
    asset = await mil_repo.get_asset(session, asset_id)
    if asset is None or asset.country_id != country.id:
        await call.answer("تجهیزات یافت نشد.", show_alert=True)
        return

    origin_code = get_equipment_origin(asset.name)
    if not origin_code or origin_code == country.name_en:
        await call.answer("این سلاح بومی کشور شماست و نیازی به لایسنس ندارد.", show_alert=True)
        return

    seller_country = await countries_repo.get_country_by_name(session, origin_code)
    if seller_country is None:
        await call.answer("کشور سازنده در بازی تعریف نشده است.", show_alert=True)
        return

    # بررسی عدم وجود لایسنس قبلی یا درخواست باز
    if await tech_repo.has_license(session, country.id, asset.name):
        await call.answer("شما قبلاً لایسنس این تجهیزات را دریافت کرده‌اید.", show_alert=True)
        return

    active_req = await tech_repo.get_active_request(session, country.id, asset.name)
    if active_req is not None:
        await call.answer("یک درخواست باز برای این تجهیزات در سیستم ثبت شده است.", show_alert=True)
        return

    req = await tech_repo.create_request(
        session=session,
        buyer_country_id=country.id,
        seller_country_id=seller_country.id,
        equipment_name=asset.name,
        branch=asset.branch,
        category=asset.category,
    )
    await session.commit()

    # ارسال اعلان به پیوی کشور سازنده در صورت وجود مالک
    if seller_country.owner_user_id:
        seller_text = (
            "🔬 <b>درخواست خرید لایسنس تکنولوژی نظامی</b>\n\n"
            f"کشور <b>{country.flag} {country.name_fa}</b> درخواست دریافت لایسنس تکنولوژی و خط تولید <b>{asset.name}</b> را برای شما ارسال کرده است."
        )
        builder = InlineKeyboardBuilder()
        builder.button(
            text="💵 تعیین قیمت لایسنس و ارسال فاکتور",
            callback_data=f"tech_inv_start:{req.id}",
            style=STYLE_OK,
        )
        builder.button(
            text="❌ رد درخواست انتقال تکنولوژی",
            callback_data=f"tech_req_reject:{req.id}",
            style=STYLE_NO,
        )
        builder.adjust(1)
        try:
            await bot.send_message(
                seller_country.owner_user_id,
                seller_text,
                reply_markup=builder.as_markup(),
            )
        except Exception as e:
            logger.warning(f"Could not message seller country owner: {e}")

    await call.answer("درخواست با موفقیت ارسال شد ✅", show_alert=True)

    text = (
        header("درخواست لایسنس ارسال شد", "✅") + "\n\n"
        f"درخواست دریافت لایسنس و خط تولید <b>{asset.name}</b> برای کشور سازنده ({seller_country.flag} <b>{seller_country.name_fa}</b>) ارسال گردید.\n\n"
        "به محض اینکه کشور سازنده قیمت لایسنس را مشخص کند، فاکتور رسمی در پیوی و در کارتابل فاکتورهای شما قرار خواهد گرفت."
    )
    b = InlineKeyboardBuilder()
    b.button(text="🔙 بازگشت به لیست تجهیزات", callback_data="tech:from_assets", style=STYLE_MAIN)
    b.button(text="🔬 پنل تکنولوژی نظامی", callback_data="tech:menu", style=STYLE_MAIN)
    b.adjust(1)
    await safe_edit(call, text, reply_markup=b.as_markup())

    await send_log(
        bot,
        "🔬 <b>درخواست لایسنس تکنولوژی نظامی (از تجهیزات)</b>\n"
        f"متقاضی: {country.flag} {country.name_fa}\n"
        f"سازنده: {seller_country.flag} {seller_country.name_fa}\n"
        f"سلاح: {asset.name}",
    )


# ============================================================
#  📥 درخواست‌های دریافتی برای کشور سازنده (تعیین قیمت یا رد)
# ============================================================


@router.callback_query(F.data == "tech:incoming")
async def cb_tech_incoming(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """مشاهده لیست درخواست‌های خرید ارسال‌شده به این کشور."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    reqs = await tech_repo.list_incoming_requests(session, country.id, status="PENDING_MANUFACTURER")
    if not reqs:
        await safe_edit(
            call,
            "📥 هیچ درخواست خرید لایسنسی در حال حاضر برای تجهیزات کشور شما ثبت نشده است.",
            reply_markup=_back_tech_kb(),
        )
        return

    lines = [
        header("درخواست‌های خرید تکنولوژی دریافتی", "📥"),
        "",
        "کشورهای زیر متقاضی خرید لایسنس بازتولید تجهیزات شما هستند:",
        DIVIDER,
    ]
    builder = InlineKeyboardBuilder()
    for idx, r in enumerate(reqs, start=1):
        buyer = r.buyer_country
        b_name = f"{buyer.flag} {buyer.name_fa}" if buyer else "—"
        lines.append(
            f"{fa_number(idx)}. تجهیز: <b>{r.equipment_name}</b>\n"
            f"   متقاضی: <b>{b_name}</b> | دسته: {r.category or 'نظامی'}"
        )
        builder.button(
            text=f"💵 قیمت‌گذاری #{fa_number(idx)} ({r.equipment_name[:12]})",
            callback_data=f"tech_inv_start:{r.id}",
            style=STYLE_OK,
        )
        builder.button(
            text=f"❌ رد #{fa_number(idx)}",
            callback_data=f"tech_req_reject:{r.id}",
            style=STYLE_NO,
        )

    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="tech:menu", style=STYLE_MAIN))
    await safe_edit(call, "\n".join(lines), reply_markup=builder.as_markup())


# ============================================================
#  🧾 فاکتورهای آماده پرداخت برای خریدار
# ============================================================


@router.callback_query(F.data == "tech:invoices")
async def cb_tech_invoices(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """مشاهده فاکتورهای صادرشده توسط سازندگان و منتظر پرداخت."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    reqs = await tech_repo.list_outgoing_requests(session, country.id, status="INVOICE_SENT")
    if not reqs:
        await safe_edit(
            call,
            "🧾 هیچ فاکتور در انتظار پرداختی برای کشور شما وجود ندارد.",
            reply_markup=_back_tech_kb(),
        )
        return

    lines = [
        header("فاکتورهای رسمی انتقال تکنولوژی", "🧾"),
        "",
        f"💰 بودجه کشور شما: <b>{fa_money(country.budget)}</b>",
        DIVIDER,
    ]
    builder = InlineKeyboardBuilder()
    for idx, r in enumerate(reqs, start=1):
        seller = r.seller_country
        s_name = f"{seller.flag} {seller.name_fa}" if seller else "—"
        lines.append(
            f"{fa_number(idx)}. تجهیز: <b>{r.equipment_name}</b>\n"
            f"   سازنده: <b>{s_name}</b> | 💰 قیمت لایسنس: <b>{fa_money(r.license_price)}</b>"
        )
        builder.button(
            text=f"✅ تایید و پرداخت #{fa_number(idx)} ({fa_money(r.license_price)})",
            callback_data=f"tech_inv_pay:{r.id}",
            style=STYLE_OK,
        )
        builder.button(
            text=f"❌ انصراف #{fa_number(idx)}",
            callback_data=f"tech_inv_cancel:{r.id}",
            style=STYLE_NO,
        )

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="tech:menu", style=STYLE_MAIN))
    await safe_edit(call, "\n".join(lines), reply_markup=builder.as_markup())


# ============================================================
#  📤 درخواست‌های ارسالی من
# ============================================================


@router.callback_query(F.data == "tech:outgoing")
async def cb_tech_outgoing(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """مشاهده درخواست‌های در حال بررسی کشور به سازندگان دیگر."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    reqs = await tech_repo.list_outgoing_requests(session, country.id)
    # فیلتر کردن موارد پایان‌یافته یا لغو‌شده جهت جلوگیری از شلوغی
    active_reqs = [r for r in reqs if r.status in ("PENDING_MANUFACTURER", "INVOICE_SENT")]
    if not active_reqs:
        await safe_edit(
            call,
            "📤 شما هیچ درخواست باز یا در حال انتظاری به کشورهای سازنده ندارید.",
            reply_markup=_back_tech_kb(),
        )
        return

    lines = [
        header("درخواست‌های ارسالی خرید لایسنس", "📤"),
        "",
        DIVIDER,
    ]
    builder = InlineKeyboardBuilder()
    for idx, r in enumerate(active_reqs, start=1):
        seller = r.seller_country
        s_name = f"{seller.flag} {seller.name_fa}" if seller else "—"
        status_fa = "⏳ در انتظار قیمت‌گذاری سازنده" if r.status == "PENDING_MANUFACTURER" else f"🧾 فاکتور صادر شده ({fa_money(r.license_price)})"
        lines.append(
            f"{fa_number(idx)}. تجهیز: <b>{r.equipment_name}</b>\n"
            f"   سازنده: <b>{s_name}</b> | وضعیت: {status_fa}"
        )
        builder.button(
            text=f"🗑 لغو درخواست #{fa_number(idx)}",
            callback_data=f"tech_inv_cancel:{r.id}",
            style=STYLE_NO,
        )

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="tech:menu", style=STYLE_MAIN))
    await safe_edit(call, "\n".join(lines), reply_markup=builder.as_markup())


# ============================================================
#  📜 لایسنس‌های دریافتی من
# ============================================================


@router.callback_query(F.data == "tech:my_licenses")
async def cb_tech_my_licenses(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """فهرست تمام لایسنس‌های معتبر و فعال کشور."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    licenses = await tech_repo.list_licenses_for_country(session, country.id)
    if not licenses:
        await safe_edit(
            call,
            "📜 کشور شما هنوز هیچ لایسنس تسلیحاتی خارجی خریداری نکرده است.\n\n"
            "<i>(تسلیحات بومی کشور شما نیازی به لایسنس ندارند).</i>",
            reply_markup=_back_tech_kb(),
        )
        return

    lines = [
        header("لایسنس‌های فعال کشور شما", "📜"),
        "",
        f"تعداد کل تکنولوژی‌های مجاز: <b>{fa_number(len(licenses))}</b> قلم",
        DIVIDER,
    ]
    for idx, lic in enumerate(licenses, start=1):
        origin = lic.origin_country
        o_name = f"{origin.flag} {origin.name_fa}" if origin else "—"
        lines.append(
            f"{fa_number(idx)}. <b>{lic.equipment_name}</b> ({lic.category or 'نظامی'})\n"
            f"   🔹 کشور سازنده اصلی: <b>{o_name}</b> | 💰 هزینه پرداختی: {fa_money(lic.price_paid)}"
        )

    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[:3900] + "\n…"
    await safe_edit(call, text, reply_markup=_back_tech_kb())


# ============================================================
#  🏭 لایسنس‌های صادرشده توسط من
# ============================================================


@router.callback_query(F.data == "tech:granted_licenses")
async def cb_tech_granted_licenses(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """فهرست تکنولوژی‌هایی که این کشور به دیگران فروخته است."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    licenses = await tech_repo.list_granted_licenses_by_country(session, country.id)
    if not licenses:
        await safe_edit(
            call,
            "🏭 کشور شما تاکنون لایسنس تولید هیچ سلاحی را به کشورهای دیگر واگذار نکرده است.",
            reply_markup=_back_tech_kb(),
        )
        return

    lines = [
        header("لایسنس‌های واگذارشده به سایر کشورها", "🏭"),
        "",
        f"تعداد کل قراردادهای انتقال فناوری: <b>{fa_number(len(licenses))}</b> فقره",
        DIVIDER,
    ]
    for idx, lic in enumerate(licenses, start=1):
        holder = lic.holder_country
        h_name = f"{holder.flag} {holder.name_fa}" if holder else "—"
        lines.append(
            f"{fa_number(idx)}. <b>{lic.equipment_name}</b>\n"
            f"   🔸 خریدار: <b>{h_name}</b> | 💰 عایدی لایسنس: {fa_money(lic.price_paid)}"
        )

    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[:3900] + "\n…"
    await safe_edit(call, text, reply_markup=_back_tech_kb())


# ============================================================
#  📩 ارسال اولیه درخواست خرید تکنولوژی (از کارخانه نظامی)
# ============================================================


@router.callback_query(F.data.startswith("tech_req_send:"))
async def cb_tech_req_send(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """ارسال درخواست خرید لایسنس به کشور سازنده پس از خطای کارخانه."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    try:
        asset_idx = int(call.data.split(":")[1])
    except (IndexError, ValueError):
        await call.answer("خطا در شناسایی قلم انتخابی.", show_alert=True)
        return

    data = await state.get_data()
    assets = data.get("assets", [])
    if asset_idx >= len(assets):
        await call.answer("اطلاعات قلم انتخابی منقضی شده است.", show_alert=True)
        return

    asset_name = assets[asset_idx]["name"]
    origin_en = get_equipment_origin(asset_name)
    if not origin_en or origin_en == country.name_en:
        await call.answer("این سلاح بومی است یا نیازی به لایسنس ندارد.", show_alert=True)
        return

    seller_country = await countries_repo.get_country_by_name(session, origin_en)
    if seller_country is None:
        await safe_edit(
            call,
            "⚠️ کشور سازنده این سلاح در حال حاضر در دیتابیس یافت نشد.",
            reply_markup=_back_tech_kb(),
        )
        return

    # بررسی عدم وجود درخواست فعال مشابه
    existing = await tech_repo.get_active_request(session, country.id, asset_name)
    if existing is not None:
        await safe_edit(
            call,
            f"⚠️ شما در حال حاضر یک درخواست فعال یا فاکتور باز برای «{asset_name}» دارید.\n"
            "لطفاً از پنل تکنولوژی وضعیت آن را بررسی نمایید.",
            reply_markup=_back_tech_kb(),
        )
        return

    req = await tech_repo.create_request(
        session=session,
        buyer_country_id=country.id,
        seller_country_id=seller_country.id,
        equipment_name=asset_name,
        branch=data.get("branch", ""),
        category=data.get("category", ""),
    )

    # اطلاع به پیوی مالک کشور سازنده
    if seller_country.owner_user_id:
        seller_text = (
            "🔬 <b>درخواست خرید لایسنس تکنولوژی نظامی</b>\n\n"
            f"کشور <b>{country.flag} {country.name_fa}</b> درخواست دریافت لایسنس تکنولوژی و خط تولید <b>{asset_name}</b> را برای شما ارسال کرده است."
        )
        builder = InlineKeyboardBuilder()
        builder.button(
            text="💵 تعیین قیمت لایسنس و ارسال فاکتور",
            callback_data=f"tech_inv_start:{req.id}",
            style=STYLE_OK,
        )
        builder.button(
            text="❌ رد درخواست انتقال تکنولوژی",
            callback_data=f"tech_req_reject:{req.id}",
            style=STYLE_NO,
        )
        builder.adjust(1)
        try:
            await bot.send_message(
                seller_country.owner_user_id,
                seller_text,
                reply_markup=builder.as_markup(),
            )
        except Exception as e:
            logger.warning(f"Could not message seller country owner: {e}")

    await safe_edit(
        call,
        "✅ <b>درخواست خرید لایسنس ارسال شد!</b>\n\n"
        f"درخواست انتقال تکنولوژی <b>{asset_name}</b> برای کشور سازنده ({seller_country.flag} {seller_country.name_fa}) ارسال گردید.\n"
        "به محض اینکه کشور سازنده قیمت لایسنس را تعیین کند، فاکتور رسمی به پیوی شما ارسال خواهد شد.",
        reply_markup=_back_tech_kb(),
    )

    await send_log(
        bot,
        "🔬 <b>درخواست لایسنس تکنولوژی نظامی</b>\n"
        f"متقاضی: {country.flag} {country.name_fa}\n"
        f"سازنده: {seller_country.flag} {seller_country.name_fa}\n"
        f"سلاح: {asset_name}",
    )


# ============================================================
#  💵 مرحله تعیین قیمت و صدور فاکتور توسط سازنده
# ============================================================


@router.callback_query(F.data.startswith("tech_inv_start:"))
async def cb_tech_inv_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """ورود سازنده به فرم تعیین قیمت دلاری لایسنس."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    req_id = int(call.data.split(":")[1])
    req = await tech_repo.get_request(session, req_id)
    if req is None or req.seller_country_id != country.id:
        await call.answer("درخواست نامعتبر است یا شما مالک سازنده نیستید.", show_alert=True)
        return
    if req.status != "PENDING_MANUFACTURER":
        await call.answer("این درخواست قبلاً تعیین تکلیف شده است.", show_alert=True)
        return

    buyer = req.buyer_country
    b_name = f"{buyer.flag} {buyer.name_fa}" if buyer else "کشور متقاضی"

    await state.set_state(TechTransferForm.entering_price)
    await state.update_data(tech_req_id=req_id)

    prompt = (
        "💵 <b>تعیین قیمت فروش لایسنس تکنولوژی</b>\n\n"
        f"🔹 تجهیزات: <b>{req.equipment_name}</b>\n"
        f"🔹 کشور خریدار: <b>{b_name}</b>\n\n"
        "لطفاً مبلغ پیشنهادی خود برای واگذاری لایسنس بازتولید این سلاح را به دلار وارد کنید (مثلاً: <code>50M</code> یا <code>50000000</code>):"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ انصراف", callback_data="tech:menu", style=STYLE_NO)
    await safe_edit(call, prompt, reply_markup=builder.as_markup())


@router.message(TechTransferForm.entering_price, F.text)
async def msg_tech_entering_price(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """دریافت قیمت و ارسال فاکتور رسمی به خریدار."""
    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        return

    data = await state.get_data()
    req_id = data.get("tech_req_id")
    if not req_id:
        await state.clear()
        await message.answer("خطا در بازیابی اطلاعات درخواست.")
        return

    price = parse_amount(message.text)
    if price is None or price <= 0:
        await message.answer("⚠️ لطفاً یک مبلغ عددی معتبر و بزرگتر از صفر وارد کنید:")
        return

    req = await tech_repo.set_invoice_price(session, req_id, price)
    await state.clear()
    if req is None:
        await message.answer("درخواست موردنظر یافت نشد یا وضعیت آن تغییر کرده است.")
        return

    buyer = req.buyer_country
    await message.answer(
        f"✅ <b>فاکتور رسمی لایسنس صادر شد!</b>\n\n"
        f"مبلغ <b>{fa_money(price)}</b> برای واگذاری دانش فنی «{req.equipment_name}» به کشور "
        f"{buyer.flag} {buyer.name_fa} ابلاغ گردید.",
        reply_markup=_back_tech_kb(),
    )

    # ارسال فاکتور به پیوی خریدار
    if buyer and buyer.owner_user_id:
        invoice_text = (
            "🧾 <b>فاکتور رسمی انتقال تکنولوژی نظامی</b>\n\n"
            f"🔹 تجهیزات: <b>{req.equipment_name}</b>\n"
            f"🔹 کشور صادرکننده لایسنس: <b>{country.flag} {country.name_fa}</b>\n"
            f"💰 قیمت تعیین‌شده برای لایسنس: <b>{fa_money(price)}</b>\n\n"
            "آیا صدور این فاکتور و پرداخت مبلغ را تایید می‌کنید؟"
        )
        builder = InlineKeyboardBuilder()
        builder.button(
            text="✅ تایید و پرداخت فاکتور",
            callback_data=f"tech_inv_pay:{req.id}",
            style=STYLE_OK,
        )
        builder.button(
            text="❌ رد فاکتور و انصراف",
            callback_data=f"tech_inv_cancel:{req.id}",
            style=STYLE_NO,
        )
        builder.adjust(1)
        try:
            await bot.send_message(
                buyer.owner_user_id,
                invoice_text,
                reply_markup=builder.as_markup(),
            )
        except Exception as e:
            logger.warning(f"Could not send invoice to buyer: {e}")

    await send_log(
        bot,
        "🧾 <b>صدور فاکتور تکنولوژی نظامی</b>\n"
        f"سازنده: {country.flag} {country.name_fa}\n"
        f"خریدار: {buyer.flag} {buyer.name_fa if buyer else '—'}\n"
        f"سلاح: {req.equipment_name}\n"
        f"مبلغ: {fa_money(price)}",
    )


# ============================================================
#  ✅ تایید و پرداخت فاکتور توسط خریدار
# ============================================================


@router.callback_query(F.data.startswith("tech_inv_pay:"))
async def cb_tech_inv_pay(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """تایید و پرداخت فاکتور توسط خریدار و صدور لایسنس."""
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    req_id = int(call.data.split(":")[1])
    req = await tech_repo.get_request(session, req_id)
    if req is None or req.buyer_country_id != country.id:
        await call.answer("فاکتور نامعتبر است یا متعلق به شما نیست.", show_alert=True)
        return
    if req.status != "INVOICE_SENT":
        await call.answer("این فاکتور قبلاً پرداخت یا لغو شده است.", show_alert=True)
        return

    # بررسی کافی بودن بودجه
    if country.budget < req.license_price:
        await call.answer(
            f"⛔️ بودجه کافی ندارید!\nموجودی: {fa_money(country.budget)}\nمبلغ فاکتور: {fa_money(req.license_price)}",
            show_alert=True,
        )
        return

    seller = req.seller_country
    if seller is None:
        await call.answer("کشور فروشنده یافت نشد.", show_alert=True)
        return

    res = await tech_repo.complete_transfer(session, req_id)
    if res is None:
        await call.answer("خطا در تکمیل فرآیند صدور لایسنس.", show_alert=True)
        return

    await call.answer("لایسنس با موفقیت خریداری شد ✅", show_alert=True)

    success_msg = (
        "🎉 <b>لایسنس تکنولوژی با موفقیت فعال شد!</b>\n\n"
        f"دانش فنی و لایسنس بازتولید <b>{req.equipment_name}</b> به کشور شما منتقل گردید.\n"
        f"💰 مبلغ {fa_money(req.license_price)} از خزانه‌ی شما کسر شد.\n\n"
        "هم‌اکنون می‌توانید از بخش «کارخانه نظامی» خط تولید این تجهیزات را احداث نمایید!"
    )
    await safe_edit(call, success_msg, reply_markup=_back_tech_kb())

    # اطلاع به فروشنده
    if seller.owner_user_id:
        try:
            await bot.send_message(
                seller.owner_user_id,
                f"💰 <b>فروش موفق لایسنس تکنولوژی نظامی</b>\n\n"
                f"کشور <b>{country.flag} {country.name_fa}</b> فاکتور لایسنس <b>{req.equipment_name}</b> را پرداخت کرد.\n"
                f"مبلغ <b>{fa_money(req.license_price)}</b> به خزانه‌ی کشور شما واریز گردید.",
            )
        except Exception:
            pass

    await send_log(
        bot,
        "🤝 <b>تکمیل انتقال تکنولوژی نظامی</b>\n"
        f"خریدار: {country.flag} {country.name_fa}\n"
        f"فروشنده: {seller.flag} {seller.name_fa}\n"
        f"تجهیز: {req.equipment_name}\n"
        f"مبلغ لایسنس: {fa_money(req.license_price)}",
    )


# ============================================================
#  ❌ رد یا لغو درخواست و فاکتور
# ============================================================


@router.callback_query(F.data.startswith("tech_req_reject:"))
async def cb_tech_req_reject(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """رد درخواست توسط کشور سازنده."""
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    req_id = int(call.data.split(":")[1])
    req = await tech_repo.get_request(session, req_id)
    if req is None or req.seller_country_id != country.id:
        await call.answer("درخواست نامعتبر است.", show_alert=True)
        return

    await tech_repo.reject_request(session, req_id)
    await call.answer("درخواست رد شد ❌")
    await safe_edit(
        call,
        f"❌ درخواست خرید لایسنس «{req.equipment_name}» رد گردید.",
        reply_markup=_back_tech_kb(),
    )

    buyer = req.buyer_country
    if buyer and buyer.owner_user_id:
        try:
            await bot.send_message(
                buyer.owner_user_id,
                f"❌ <b>رد درخواست لایسنس تکنولوژی</b>\n\n"
                f"کشور سازنده ({country.flag} {country.name_fa}) درخواست شما برای دریافت لایسنس «{req.equipment_name}» را رد کرد.",
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("tech_inv_cancel:") | F.data.startswith("tech_req_cancel_buyer:"))
async def cb_tech_inv_cancel(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """لغو درخواست یا فاکتور توسط خریدار."""
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    req_id = int(call.data.split(":")[1])
    req = await tech_repo.get_request(session, req_id)
    if req is None or req.buyer_country_id != country.id:
        await call.answer("فاکتور نامعتبر است.", show_alert=True)
        return

    await tech_repo.cancel_request(session, req_id)
    await call.answer("فاکتور لغو شد.")
    await safe_edit(
        call,
        f"❌ فرآیند خرید لایسنس «{req.equipment_name}» لغو گردید.",
        reply_markup=_back_tech_kb(),
    )
