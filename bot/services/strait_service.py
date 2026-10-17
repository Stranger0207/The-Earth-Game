"""
سرویس عملیات ژئوپلیتیک تنگه‌ها، اخطار عبور، حمله، تخریب، مصادره و اموال بلوکه‌شده (آپدیت ۳ و ۱۱).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import STRAIT_TOLL_MAX
from ..database.models import Country, ResourceSale
from ..database.repositories import countries as countries_repo
from ..database.repositories import reserves as reserves_repo
from ..database.repositories import straits as straits_repo
from ..database.repositories import trade as trade_repo
from ..enums import (
    NewsCategory,
    RESOURCE_FA,
    RESOURCE_UNIT_FA,
    ResourceType,
    StraitBlockScope,
    TradeStatus,
)
from ..keyboards.straits import strait_intercept_alert_kb
from ..services.geo_service import STRAITS_DEFINITIONS, get_strait_def
from ..services.news_service import publish_news, send_log
from ..utils.numbers import fa_number

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StraitError(Exception):
    """خطای منطقی سیستم تنگه‌ها."""


async def hold_shipment_at_strait(
    bot: Bot,
    session: AsyncSession,
    sale: ResourceSale,
    strait_id: str,
) -> None:
    """
    متوقف کردن محموله در تنگه مسدودشده و ارسال اخطار به پیوی کشور کنترل‌کننده تنگه.
    """
    s_def = get_strait_def(strait_id)
    if not s_def:
        return

    strait_name_fa = s_def["name_fa"]
    ctrl_country_name = s_def["controller"]
    ctrl_country = await countries_repo.get_country_by_name(session, ctrl_country_name)
    if not ctrl_country:
        return

    seller = await countries_repo.get_country(session, sale.seller_country)
    buyer = await countries_repo.get_country(session, sale.buyer_country)

    sale.strait_status = "HELD_AT_STRAIT"
    sale.held_at_strait_id = strait_id
    sale.held_since = _utcnow()
    await session.flush()

    try:
        rtype = ResourceType(sale.resource)
        rname = RESOURCE_FA[rtype]
        unit = RESOURCE_UNIT_FA[rtype]
    except (ValueError, KeyError):
        rname = sale.resource
        unit = ""

    seller_title = f"{seller.flag} {seller.name_fa}" if seller else "?"
    buyer_title = f"{buyer.flag} {buyer.name_fa}" if buyer else "?"

    # ارسال اخطار به پیوی کنترل‌کننده تنگه
    if ctrl_country.owner_user_id:
        alert_text = (
            f"🚨 <b>اخطار مرزبانی دریایی در {strait_name_fa}!</b>\n\n"
            f"یک کشتی تجاری حامل محموله قصد عبور از آبراه مسدودشده‌ی <b>{strait_name_fa}</b> را دارد!\n\n"
            f"🚢 <b>مبدأ (فروشنده):</b> {seller_title}\n"
            f"🎯 <b>مقصد (خریدار):</b> {buyer_title}\n"
            f"📦 <b>بار کشتی:</b> {fa_number(sale.amount)} {unit} {rname}\n\n"
            "<i>دستور شما برای این شناور چیست؟</i>"
        )
        try:
            await bot.send_message(
                ctrl_country.owner_user_id,
                alert_text,
                reply_markup=strait_intercept_alert_kb(sale.id, strait_id),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to send strait alert to controller: %s", exc)

    # لاگ به گروه مدیران
    await send_log(
        bot,
        f"🚨 <b>توقیف محموله در تنگه مسدود</b>\n"
        f"تنگه: {strait_name_fa} (کنترل: {ctrl_country.flag} {ctrl_country.name_fa})\n"
        f"مسیر: {seller_title} ⬅️ {buyer_title}\n"
        f"بار: {fa_number(sale.amount)} {unit} {rname}",
    )


async def allow_passage(
    bot: Bot,
    session: AsyncSession,
    sale_id: int,
    strait_id: str,
    controller_country: Country,
) -> dict:
    """صدور اجازه عبور برای کشتی از تنگه."""
    sale = await trade_repo.get_sale(session, sale_id)
    if not sale or sale.strait_status != "HELD_AT_STRAIT":
        raise StraitError("این محموله دیگر در انتظار تصمیم‌گیری در تنگه نیست.")

    s_def = get_strait_def(strait_id)
    strait_name_fa = s_def["name_fa"] if s_def else strait_id

    sale.strait_status = "PASSED"
    sale.held_at_strait_id = None
    sale.held_since = None
    sale.status = TradeStatus.IN_TRANSIT.value
    await session.flush()

    seller = await countries_repo.get_country(session, sale.seller_country)
    buyer = await countries_repo.get_country(session, sale.buyer_country)

    notice = (
        f"🟢 <b>اجازه عبور صادر شد</b>\n\n"
        f"کشور {controller_country.flag} {controller_country.name_fa} به کشتی محموله در <b>{strait_name_fa}</b> "
        "اجازه عبور داد. محموله به سمت مقصد ادامه مسیر می‌دهد."
    )

    if seller and seller.owner_user_id:
        try:
            await bot.send_message(seller.owner_user_id, notice)
        except Exception:  # noqa: BLE001
            pass

    if buyer and buyer.owner_user_id:
        try:
            await bot.send_message(buyer.owner_user_id, notice)
        except Exception:  # noqa: BLE001
            pass

    await send_log(
        bot,
        f"🟢 <b>صدور اجازه عبور در تنگه</b>\n"
        f"تنگه: {strait_name_fa}\n"
        f"کنترل‌کننده: {controller_country.flag} {controller_country.name_fa}\n"
        f"محموله: #{sale.id}",
    )

    return {"status": "allowed", "strait_name_fa": strait_name_fa}


async def destroy_shipment(
    bot: Bot,
    session: AsyncSession,
    sale_id: int,
    strait_id: str,
    controller_country: Country,
) -> dict:
    """حمله و انهدام کامل کشتی و محموله در تنگه."""
    sale = await trade_repo.get_sale(session, sale_id)
    if not sale or sale.strait_status != "HELD_AT_STRAIT":
        raise StraitError("این محموله دیگر در انتظار تصمیم‌گیری در تنگه نیست.")

    s_def = get_strait_def(strait_id)
    strait_name_fa = s_def["name_fa"] if s_def else strait_id

    sale.strait_status = "DESTROYED"
    sale.status = TradeStatus.REJECTED.value
    sale.held_at_strait_id = None
    sale.held_since = None
    await session.flush()

    seller = await countries_repo.get_country(session, sale.seller_country)
    buyer = await countries_repo.get_country(session, sale.buyer_country)

    try:
        rtype = ResourceType(sale.resource)
        rname = RESOURCE_FA[rtype]
        unit = RESOURCE_UNIT_FA[rtype]
    except (ValueError, KeyError):
        rname = sale.resource
        unit = ""

    seller_title = f"{seller.flag} {seller.name_fa}" if seller else "?"
    buyer_title = f"{buyer.flag} {buyer.name_fa}" if buyer else "?"

    msg_text = (
        f"💥 <b>انهدام کشتی تجاری در {strait_name_fa}!</b>\n\n"
        f"نیروهای دریایی {controller_country.flag} {controller_country.name_fa} به کشتی تجاری حامل "
        f"<b>{fa_number(sale.amount)} {unit} {rname}</b> (مبدأ: {seller_title}، مقصد: {buyer_title}) "
        f"حمله کرده و کشتی به همراه کل محموله و خدمه آن به قعر دریا رفتند!"
    )

    if seller and seller.owner_user_id:
        try:
            await bot.send_message(seller.owner_user_id, msg_text)
        except Exception:  # noqa: BLE001
            pass

    if buyer and buyer.owner_user_id:
        try:
            await bot.send_message(buyer.owner_user_id, msg_text)
        except Exception:  # noqa: BLE001
            pass

    # انتشار خبر در کانال نظامی و لاگ
    await publish_news(bot, NewsCategory.MILITARY, msg_text)
    await send_log(
        bot,
        f"💥 <b>حمله و انهدام کشتی در تنگه</b>\n"
        f"تنگه: {strait_name_fa}\n"
        f"مهاجم: {controller_country.flag} {controller_country.name_fa}\n"
        f"محموله: {fa_number(sale.amount)} {unit} {rname} از {seller_title} به {buyer_title}",
    )

    return {"status": "destroyed", "strait_name_fa": strait_name_fa}


async def confiscate_shipment(
    bot: Bot,
    session: AsyncSession,
    sale_id: int,
    strait_id: str,
    controller_country: Country,
    *,
    to_blocked_assets: bool = False,
) -> dict:
    """مصادره و توقیف بار کشتی توسط کشور کنترل‌کننده تنگه."""
    sale = await trade_repo.get_sale(session, sale_id)
    if not sale or sale.strait_status != "HELD_AT_STRAIT":
        raise StraitError("این محموله دیگر در انتظار تصمیم‌گیری در تنگه نیست.")

    s_def = get_strait_def(strait_id)
    strait_name_fa = s_def["name_fa"] if s_def else strait_id

    seller = await countries_repo.get_country(session, sale.seller_country)
    buyer = await countries_repo.get_country(session, sale.buyer_country)

    try:
        rtype = ResourceType(sale.resource)
        rname = RESOURCE_FA[rtype]
        unit = RESOURCE_UNIT_FA[rtype]
    except (ValueError, KeyError):
        rname = sale.resource
        unit = ""

    sale.strait_status = "CONFISCATED"
    sale.status = TradeStatus.REJECTED.value
    sale.held_at_strait_id = None
    sale.held_since = None

    if to_blocked_assets:
        # انتقال به اموال بلوکه‌شده
        await straits_repo.add_blocked_cargo(
            session,
            holding_country_id=controller_country.id,
            source_country_id=sale.seller_country,
            dest_country_id=sale.buyer_country,
            resource=sale.resource,
            amount=sale.amount,
            strait_id=strait_id,
            original_sale_id=sale.id,
        )
        dest_action_text = "به «اموال بلوکه‌شده» کشور منتقل شد تا بعداً درباره آن تصمیم‌گیری شود."
    else:
        # افزودن مستقیم به ذخایر خودی
        await reserves_repo.ensure_reserve(session, controller_country.id, sale.resource)
        await reserves_repo.add_amount(
            session, controller_country.id, sale.resource, sale.amount
        )
        dest_action_text = "مستقیماً به موجودی ذخایر کشور کنترل‌کننده تنگه اضافه شد."

    await session.flush()

    seller_title = f"{seller.flag} {seller.name_fa}" if seller else "?"
    buyer_title = f"{buyer.flag} {buyer.name_fa}" if buyer else "?"

    msg_text = (
        f"⚓ <b>توقیف و مصادره کشتی در {strait_name_fa}!</b>\n\n"
        f"نیروهای مرزبانی دریایی {controller_country.flag} {controller_country.name_fa} کشتی حامل "
        f"<b>{fa_number(sale.amount)} {unit} {rname}</b> (مبدأ: {seller_title}، مقصد: {buyer_title}) را "
        f"متوقف و بار آن را به طور کامل مصادره کردند.\n"
        "خدمه کشتی دستگیر و به کشور خود بازگردانده شدند."
    )

    if seller and seller.owner_user_id:
        try:
            await bot.send_message(seller.owner_user_id, msg_text)
        except Exception:  # noqa: BLE001
            pass

    if buyer and buyer.owner_user_id:
        try:
            await bot.send_message(buyer.owner_user_id, msg_text)
        except Exception:  # noqa: BLE001
            pass

    await publish_news(bot, NewsCategory.MILITARY, msg_text)
    await send_log(
        bot,
        f"⚓ <b>مصادره بار کشتی در تنگه</b>\n"
        f"تنگه: {strait_name_fa}\n"
        f"کشور مصادره‌کننده: {controller_country.flag} {controller_country.name_fa}\n"
        f"بار: {fa_number(sale.amount)} {unit} {rname}\n"
        f"وضعیت: {dest_action_text}",
    )

    return {
        "status": "confiscated",
        "strait_name_fa": strait_name_fa,
        "to_blocked": to_blocked_assets,
    }


# ============================================================
#  عملیات سه‌گانه پنل اموال بلوکه‌شده
# ============================================================

async def destroy_blocked_cargo(
    bot: Bot,
    session: AsyncSession,
    cargo_id: int,
    holding_country: Country,
) -> dict:
    """تخریب و نابودی اموال بلوکه‌شده."""
    cargo = await straits_repo.get_blocked_cargo(session, cargo_id)
    if not cargo or cargo.holding_country_id != holding_country.id:
        raise StraitError("محموله بلوکه‌شده یافت نشد.")

    s_def = get_strait_def(cargo.strait_id)
    strait_name = s_def["name_fa"] if s_def else cargo.strait_id

    try:
        rtype = ResourceType(cargo.resource)
        rname = RESOURCE_FA[rtype]
        unit = RESOURCE_UNIT_FA[rtype]
    except (ValueError, KeyError):
        rname = cargo.resource
        unit = ""

    source_c = await countries_repo.get_country(session, cargo.source_country_id)
    amount = cargo.amount

    await straits_repo.delete_blocked_cargo(session, cargo_id)

    if source_c and source_c.owner_user_id:
        try:
            await bot.send_message(
                source_c.owner_user_id,
                f"🗑 محموله بلوکه‌شده شما ({fa_number(amount)} {unit} {rname}) که در {strait_name} توقیف شده بود، "
                f"توسط {holding_country.flag} {holding_country.name_fa} کاملاً تخریب و نابود شد.",
            )
        except Exception:  # noqa: BLE001
            pass

    await send_log(
        bot,
        f"🗑 <b>تخریب اموال بلوکه‌شده</b>\n"
        f"کشور: {holding_country.flag} {holding_country.name_fa}\n"
        f"بار نابودشده: {fa_number(amount)} {unit} {rname}\n"
        f"مالک اصلی: {source_c.flag} {source_c.name_fa if source_c else '?'}",
    )

    return {"status": "destroyed", "resource_fa": rname, "amount": amount, "unit": unit}


async def claim_blocked_cargo_to_reserves(
    bot: Bot,
    session: AsyncSession,
    cargo_id: int,
    holding_country: Country,
) -> dict:
    """انتقال اموال بلوکه‌شده به ذخایر کشور خودی."""
    cargo = await straits_repo.get_blocked_cargo(session, cargo_id)
    if not cargo or cargo.holding_country_id != holding_country.id:
        raise StraitError("محموله بلوکه‌شده یافت نشد.")

    try:
        rtype = ResourceType(cargo.resource)
        rname = RESOURCE_FA[rtype]
        unit = RESOURCE_UNIT_FA[rtype]
    except (ValueError, KeyError):
        rname = cargo.resource
        unit = ""

    amount = cargo.amount
    resource = cargo.resource

    await reserves_repo.ensure_reserve(session, holding_country.id, resource)
    await reserves_repo.add_amount(session, holding_country.id, resource, amount)

    await straits_repo.delete_blocked_cargo(session, cargo_id)

    await send_log(
        bot,
        f"📥 <b>ترخیص اموال بلوکه‌شده به ذخایر خودی</b>\n"
        f"کشور: {holding_country.flag} {holding_country.name_fa}\n"
        f"بار: {fa_number(amount)} {unit} {rname} به ذخایر افزوده شد.",
    )

    return {"status": "claimed", "resource_fa": rname, "amount": amount, "unit": unit}


async def return_blocked_cargo_to_source(
    bot: Bot,
    session: AsyncSession,
    cargo_id: int,
    holding_country: Country,
) -> dict:
    """بازگرداندن اموال بلوکه‌شده به کشور فرستنده اصلی."""
    cargo = await straits_repo.get_blocked_cargo(session, cargo_id)
    if not cargo or cargo.holding_country_id != holding_country.id:
        raise StraitError("محموله بلوکه‌شده یافت نشد.")

    s_def = get_strait_def(cargo.strait_id)
    strait_name = s_def["name_fa"] if s_def else cargo.strait_id

    try:
        rtype = ResourceType(cargo.resource)
        rname = RESOURCE_FA[rtype]
        unit = RESOURCE_UNIT_FA[rtype]
    except (ValueError, KeyError):
        rname = cargo.resource
        unit = ""

    source_c = await countries_repo.get_country(session, cargo.source_country_id)
    amount = cargo.amount
    resource = cargo.resource

    if source_c:
        await reserves_repo.ensure_reserve(session, source_c.id, resource)
        await reserves_repo.add_amount(session, source_c.id, resource, amount)

    await straits_repo.delete_blocked_cargo(session, cargo_id)

    if source_c and source_c.owner_user_id:
        try:
            await bot.send_message(
                source_c.owner_user_id,
                f"🚢 <b>بازگشت اموال بلوکه‌شده</b>\n\n"
                f"محموله توقیفی شما شامل <b>{fa_number(amount)} {unit} {rname}</b> در {strait_name}، "
                f"توسط دولت {holding_country.flag} {holding_country.name_fa} آزاد شده و مجدداً به ذخایر کشورتان بازگشت.",
            )
        except Exception:  # noqa: BLE001
            pass

    await send_log(
        bot,
        f"🚢 <b>عودت اموال بلوکه‌شده به مبدأ</b>\n"
        f"از طرف: {holding_country.flag} {holding_country.name_fa}\n"
        f"به مقصد: {source_c.flag} {source_c.name_fa if source_c else '?'}\n"
        f"بار: {fa_number(amount)} {unit} {rname}",
    )

    return {"status": "returned", "resource_fa": rname, "amount": amount, "unit": unit}
