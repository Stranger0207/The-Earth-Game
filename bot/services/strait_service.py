"""
سرویس عملیات ژئوپلیتیک تنگه‌ها، اخطار عبور، حمله، تخریب، مصادره و اموال بلوکه‌شده (آپدیت ۳ و ۱۱).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

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
from ..keyboards.straits import (
    strait_intercept_alert_kb,
    strait_standoff_ctrl_kb,
    strait_standoff_owner_kb,
)
from ..services.geo_service import (
    STRAITS_DEFINITIONS,
    calculate_maritime_transit_minutes,
    get_strait_def,
    get_strait_transit_progress,
)
from ..services.news_service import publish_news, send_log
from ..utils.numbers import fa_number

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StraitError(Exception):
    """خطای منطقی سیستم تنگه‌ها."""


async def trigger_strait_standoff(
    bot: Bot,
    session: AsyncSession,
    sale: ResourceSale,
    strait_id: str,
) -> None:
    """
    رویداد رویارویی در دهانه تنگه:
    کشتی به آستانه ورودی تنگه مسدودشده رسیده و متوقف می‌شود.
    ارسال اخطار اولیه و دکمه‌های کنترل به کشور کنترل‌کننده تنگه.
    ارسال هشدار موقعیت و گزینه‌های تصمیم‌گیری (توقف، عقب‌نشینی، عبور) به کشور فرستنده محموله.
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

    now = _utcnow()
    sale.strait_status = "HELD_AT_STRAIT"
    sale.held_at_strait_id = strait_id
    sale.held_since = now
    sale.standoff_action = "STANDOFF"
    sale.warning_count = 0

    # ذخیره زمان باقیمانده ترانزیت پیش از توقف
    if sale.ship_eta and sale.ship_eta > now:
        sale.remaining_seconds = max(60.0, (sale.ship_eta - now).total_seconds())
    else:
        seller_en = seller.name_en if seller else ""
        buyer_en = buyer.name_en if buyer else ""
        total_min = calculate_maritime_transit_minutes(seller_en, buyer_en) if seller_en and buyer_en else 60
        sale.remaining_seconds = float(max(20, total_min // 2) * 60)

    # حین رویارویی، زمان رسیدن موقتاً متوقف می‌شود
    sale.ship_eta = None
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

    # ۱. پیام به کشور کنترل‌کننده تنگه
    if ctrl_country.owner_user_id:
        ctrl_alert = (
            f"🚨 <b>اخطار مرزبانی دریایی در {strait_name_fa}!</b>\n\n"
            f"یک کشتی تجاری به حریم امنیتی آبراه مسدودشده‌ی <b>{strait_name_fa}</b> نزدیک شده است!\n\n"
            f"🚢 <b>مبدأ (فروشنده):</b> {seller_title}\n"
            f"🎯 <b>مقصد (خریدار):</b> {buyer_title}\n"
            f"📦 <b>بار کشتی:</b> {fa_number(sale.amount)} {unit} {rname}\n\n"
            f"⚠️ <b>وضعیت اخطارها:</b> ۰ از ۳\n\n"
            "<i>می‌توانید به کشتی تا ۳ اخطار صادر کنید، در صورت تمرد به آن شلیک کنید، یا اجازه عبور بدهید:</i>"
        )
        try:
            await bot.send_message(
                ctrl_country.owner_user_id,
                ctrl_alert,
                reply_markup=strait_standoff_ctrl_kb(sale.id, strait_id, warning_count=0, is_running=False),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to send standoff alert to strait controller: %s", exc)

    # ۲. پیام به صاحب محموله (فروشنده)
    if seller and seller.owner_user_id:
        owner_alert = (
            f"⚠️ <b>هشدار ناوبری دریایی: تنگه مسدود!</b>\n\n"
            f"کشتی تجاری شما حامل <b>{fa_number(sale.amount)} {unit} {rname}</b> در مسیر {buyer_title}، "
            f"به دهانه ورودی آبراه مسدودشده‌ی <b>{strait_name_fa}</b> (تحت حاکمیت {ctrl_country.flag} {ctrl_country.name_fa}) رسیده است.\n\n"
            "👮‍♂️ <b>دستور شما برای کاپیتان کشتی چیست؟</b>\n"
            "۱. <b>توقف در محل:</b> لنگراندازی در آب‌های بین‌المللی دهانه تنگه جهت مذاکره دیپلماتیک.\n"
            "۲. <b>عقب‌نشینی:</b> دور زدن و بازگرداندن ایمن محموله به کشور خود.\n"
            "۳. <b>ادامه مسیر:</b> تلاش برای عبور با ریسک شلیک و انهدام توسط مرزبانی تنگه."
        )
        try:
            await bot.send_message(
                seller.owner_user_id,
                owner_alert,
                reply_markup=strait_standoff_owner_kb(sale.id, strait_id, current_action="STANDOFF"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to send standoff alert to cargo owner: %s", exc)

    await send_log(
        bot,
        f"🚨 <b>آغاز رویارویی دریایی در تنگه مسدود</b>\n"
        f"تنگه: {strait_name_fa} (کنترل: {ctrl_country.flag} {ctrl_country.name_fa})\n"
        f"شناور: {seller_title} ⬅️ {buyer_title}\n"
        f"بار: {fa_number(sale.amount)} {unit} {rname}",
    )


async def hold_shipment_at_strait(
    bot: Bot,
    session: AsyncSession,
    sale: ResourceSale,
    strait_id: str,
) -> None:
    """متوقف کردن محموله در تنگه مسدودشده (سازگاری با کدهای پیشین)."""
    await trigger_strait_standoff(bot, session, sale, strait_id)


async def issue_strait_warning(
    bot: Bot,
    session: AsyncSession,
    sale_id: int,
    strait_id: str,
    controller_country: Country,
) -> dict:
    """صدور اخطار رادیویی رسمی از سوی کنترل‌کننده تنگه به کشتی تجاری (۱ تا ۳ اخطار)."""
    sale = await trade_repo.get_sale(session, sale_id)
    if not sale:
        raise StraitError("محموله یافت نشد.")

    if sale.strait_status == "PASSED":
        raise StraitError("این کشتی از محدوده عملیاتی تنگه عبور کرده و وارد آب‌های آزاد شده است. صدور اخطار ممکن نیست.")

    if sale.standoff_action == "RETURNING":
        raise StraitError("کشتی به اخطارها تمکین کرده و در حال بازگشت به کشور مبدأ است. نیازی به اخطار مجدد نیست.")

    if sale.warning_count >= 3:
        raise StraitError("حداکثر ۳ اخطار به این شناور داده شده است. اکنون می‌توانید در صورت لزوم دستور شلیک صادر کنید.")

    sale.warning_count += 1
    w_count = sale.warning_count
    await session.flush()

    s_def = get_strait_def(strait_id)
    strait_name_fa = s_def["name_fa"] if s_def else strait_id

    seller = await countries_repo.get_country(session, sale.seller_country)

    try:
        rtype = ResourceType(sale.resource)
        rname = RESOURCE_FA[rtype]
        unit = RESOURCE_UNIT_FA[rtype]
    except (ValueError, KeyError):
        rname = sale.resource
        unit = ""

    cargo_desc = f"{fa_number(sale.amount)} {unit} {rname}"

    if w_count == 1:
        warn_text = (
            f"📢 <b>اخطار اول از مرزبانی دریایی {controller_country.flag} {controller_country.name_fa} در {strait_name_fa}:</b>\n\n"
            f"شناور تجاری حامل <b>{cargo_desc}</b>!\n"
            f"آبراه <b>{strait_name_fa}</b> به دستور دولت مسدود است. شما مجوز عبور ندارید. "
            "فوراً در محل متوقف شوید یا تغییر مسیر داده و به مبدأ خود بازگردید!"
        )
    elif w_count == 2:
        warn_text = (
            f"🚨📢 <b>اخطار دوم (هشدار جدی) مرزبانی {controller_country.flag} {controller_country.name_fa} در {strait_name_fa}:</b>\n\n"
            f"شناور تجاری حامل <b>{cargo_desc}</b>!\n"
            f"این دومین اخطار رسمی است. هرگونه پیشروی به سمت گلویی تنگه، نقض حاکمیت ملی تلقی شده "
            "و شناور شما هدف آتش مستقیم توپخانه ساحلی و موشک‌های ضدکشتی قرار خواهد گرفت!"
        )
    else:
        warn_text = (
            f"🔴🚨 <b>اخطار سوم (اولتیماتوم نهایی) در {strait_name_fa}:</b>\n\n"
            f"شناور تجاری حامل <b>{cargo_desc}</b>!\n"
            "این آخرین اخطار قبل از شلیک است! شما متجاوز دریایی شناخته شده‌اید. "
            "فوراً موتورها را خاموش کرده یا عقب‌نشینی کنید؛ در غیر این صورت تا لحظاتی دیگر غرق خواهید شد!"
        )

    # ارسال اخطار به پیوی صاحب بار
    if seller and seller.owner_user_id:
        try:
            await bot.send_message(
                seller.owner_user_id,
                warn_text,
                reply_markup=strait_standoff_owner_kb(sale.id, strait_id, current_action=sale.standoff_action),
            )
        except Exception:  # noqa: BLE001
            pass

    # لاگ به گروه مدیران
    await send_log(
        bot,
        f"📢 <b>صدور اخطار {fa_number(w_count)} در {strait_name_fa}</b>\n"
        f"کنترل‌کننده: {controller_country.flag} {controller_country.name_fa}\n"
        f"شناور: {seller.flag if seller else ''} {seller.name_fa if seller else ''}\n"
        f"بار: {cargo_desc}",
    )

    return {
        "status": "warned",
        "warning_count": w_count,
        "strait_name_fa": strait_name_fa,
    }


async def owner_hold_at_strait(
    bot: Bot,
    session: AsyncSession,
    sale_id: int,
    owner_country: Country,
) -> dict:
    """توقف و لنگراندازی کشتی توسط مالک بار در دهانه تنگه."""
    sale = await trade_repo.get_sale(session, sale_id)
    if not sale or sale.seller_country != owner_country.id:
        raise StraitError("محموله مربوط به کشور شما نیست.")

    if sale.strait_status == "PASSED":
        raise StraitError("کشتی از تنگه عبور کرده است و امکان توقف وجود ندارد.")

    sale.standoff_action = "HOLD"
    now = _utcnow()
    if sale.ship_eta and sale.ship_eta > now:
        sale.remaining_seconds = max(60.0, (sale.ship_eta - now).total_seconds())
    sale.ship_eta = None
    await session.flush()

    s_def = get_strait_def(sale.held_at_strait_id or "")
    strait_name_fa = s_def["name_fa"] if s_def else "تنگه"

    ctrl_country = None
    if s_def:
        ctrl_country = await countries_repo.get_country_by_name(session, s_def["controller"])

    if ctrl_country and ctrl_country.owner_user_id:
        try:
            await bot.send_message(
                ctrl_country.owner_user_id,
                f"⚓ <b>شناور تجاری لنگر انداخت:</b>\n\n"
                f"کشتی {owner_country.flag} {owner_country.name_fa} در مدخل <b>{strait_name_fa}</b> موتورهای خود را خاموش کرد "
                "و در آب‌های بین‌المللی متوقف شد تا تصمیم نهایی اتخاذ گردد.",
                reply_markup=strait_standoff_ctrl_kb(
                    sale.id, sale.held_at_strait_id or "", warning_count=sale.warning_count, is_running=False
                ),
            )
        except Exception:  # noqa: BLE001
            pass

    return {"status": "holding", "strait_name_fa": strait_name_fa}


async def owner_retreat_from_strait(
    bot: Bot,
    session: AsyncSession,
    sale_id: int,
    owner_country: Country,
) -> dict:
    """عقب‌نشینی کشتی و بازگشت محموله به کشور مبدأ."""
    sale = await trade_repo.get_sale(session, sale_id)
    if not sale or sale.seller_country != owner_country.id:
        raise StraitError("محموله مربوط به کشور شما نیست.")

    if sale.strait_status == "PASSED":
        raise StraitError("کشتی از تنگه عبور کرده است و امکان عقب‌نشینی وجود ندارد.")

    s_def = get_strait_def(sale.held_at_strait_id or "")
    strait_name_fa = s_def["name_fa"] if s_def else "تنگه"

    ctrl_country = None
    if s_def:
        ctrl_country = await countries_repo.get_country_by_name(session, s_def["controller"])

    now = _utcnow()
    elapsed = max(900.0, (now - sale.created_at).total_seconds()) if sale.created_at else 1800.0
    return_seconds = min(3600.0, elapsed)

    sale.standoff_action = "RETURNING"
    sale.strait_status = "RETURNING"
    sale.created_at = now
    sale.ship_eta = now + timedelta(seconds=return_seconds)
    sale.held_at_strait_id = None
    sale.held_since = None
    await session.flush()

    if ctrl_country and ctrl_country.owner_user_id:
        try:
            await bot.send_message(
                ctrl_country.owner_user_id,
                f"🔄 <b>عقب‌نشینی شناور تجاری از {strait_name_fa}:</b>\n\n"
                f"شناور متعلق به {owner_country.flag} {owner_country.name_fa} به اخطارهای مرزبانی تمکین نموده، "
                f"دور زد و در حال بازگشت به کشور خود است. شناور دیگر در محدوده مسدود تنگه حضور ندارد.",
            )
        except Exception:  # noqa: BLE001
            pass

    return {"status": "returning", "strait_name_fa": strait_name_fa}


async def owner_run_blockade(
    bot: Bot,
    session: AsyncSession,
    sale_id: int,
    owner_country: Country,
) -> dict:
    """تلاش برای عبور و شکستن محاصره تنگه توسط مالک بار."""
    sale = await trade_repo.get_sale(session, sale_id)
    if not sale or sale.seller_country != owner_country.id:
        raise StraitError("محموله مربوط به کشور شما نیست.")

    if sale.strait_status == "PASSED":
        raise StraitError("کشتی پیشتر از تنگه عبور کرده است.")

    sale.standoff_action = "RUNNING"
    now = _utcnow()
    rem = sale.remaining_seconds if (sale.remaining_seconds and sale.remaining_seconds > 0) else 1800.0
    sale.ship_eta = now + timedelta(seconds=rem)
    await session.flush()

    s_def = get_strait_def(sale.held_at_strait_id or "")
    strait_name_fa = s_def["name_fa"] if s_def else "تنگه"

    ctrl_country = None
    if s_def:
        ctrl_country = await countries_repo.get_country_by_name(session, s_def["controller"])

    if ctrl_country and ctrl_country.owner_user_id:
        try:
            await bot.send_message(
                ctrl_country.owner_user_id,
                f"🚨💥 <b>هشدار امنیتی: تمرد شناور تجاری در {strait_name_fa}!</b>\n\n"
                f"شناور {owner_country.flag} {owner_country.name_fa} اخطارهای مرزبانی را نادیده گرفته و با حداکثر سرعت "
                f"در حال پیشروی در آبراه مسدود <b>{strait_name_fa}</b> است!\n\n"
                "<i>دستور آتش صادر می‌کنید یا اجازه عبور می‌دهید؟</i>",
                reply_markup=strait_standoff_ctrl_kb(
                    sale.id, sale.held_at_strait_id or "", warning_count=max(1, sale.warning_count), is_running=True
                ),
            )
        except Exception:  # noqa: BLE001
            pass

    return {"status": "running", "strait_name_fa": strait_name_fa}


async def allow_passage(
    bot: Bot,
    session: AsyncSession,
    sale_id: int,
    strait_id: str,
    controller_country: Country,
) -> dict:
    """صدور اجازه عبور برای کشتی از تنگه."""
    sale = await trade_repo.get_sale(session, sale_id)
    if not sale or (sale.strait_status != "HELD_AT_STRAIT" and sale.standoff_action not in ("STANDOFF", "HOLD", "RUNNING")):
        raise StraitError("این محموله دیگر در انتظار تصمیم‌گیری در تنگه نیست.")

    s_def = get_strait_def(strait_id)
    strait_name_fa = s_def["name_fa"] if s_def else strait_id

    now = _utcnow()
    if sale.remaining_seconds and sale.remaining_seconds > 0:
        rem_sec = sale.remaining_seconds
    else:
        seller = await countries_repo.get_country(session, sale.seller_country)
        buyer = await countries_repo.get_country(session, sale.buyer_country)
        total_min = calculate_maritime_transit_minutes(seller.name_en, buyer.name_en) if seller and buyer else 60
        rem_sec = float(max(20, total_min // 2) * 60)

    sale.strait_status = "PASSED"
    sale.standoff_action = "SAILING"
    sale.held_at_strait_id = None
    sale.held_since = None
    sale.status = TradeStatus.IN_TRANSIT.value
    sale.ship_eta = now + timedelta(seconds=rem_sec)
    sale.remaining_seconds = None
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
    if not sale or (sale.strait_status != "HELD_AT_STRAIT" and sale.standoff_action not in ("STANDOFF", "HOLD", "RUNNING")):
        raise StraitError("این محموله دیگر در انتظار تصمیم‌گیری یا تیررس در تنگه نیست.")

    if sale.standoff_action == "RETURNING":
        raise StraitError("شناور به اخطارها تمکین کرده و در حال عقب‌نشینی به کشور مبدأ است. امکان حمله به آن وجود ندارد!")

    if sale.strait_status == "PASSED":
        raise StraitError("شناور از محدوده عملیاتی تنگه عبور کرده و وارد آب‌های آزاد شده است. امکان حمله وجود ندارد!")

    s_def = get_strait_def(strait_id)
    strait_name_fa = s_def["name_fa"] if s_def else strait_id

    sale.strait_status = "DESTROYED"
    sale.status = TradeStatus.REJECTED.value
    sale.standoff_action = "DESTROYED"
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


async def fire_at_shipment(
    bot: Bot,
    session: AsyncSession,
    sale_id: int,
    strait_id: str,
    controller_country: Country,
) -> dict:
    """شلیک موشکی/نظامی به کشتی متخلف در تنگه."""
    return await destroy_shipment(bot, session, sale_id, strait_id, controller_country)


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

    # شوک ناامنی و افزایش قیمت منبع در بازار جهانی (آپدیت شماره ۴)
    try:
        from . import market_service
        await market_service.on_strait_incident(session, strait_id, sale.resource)
    except Exception:
        pass

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
