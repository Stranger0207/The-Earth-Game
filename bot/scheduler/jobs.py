"""
کارهای زمان‌بندی‌شده‌ی بازی:
- بازدهی تأسیسات (هر ۲۴ ساعت به ذخایر اضافه می‌شود)
- رسیدن محموله‌های WTO
- رسیدن مسافر دیدار حضوری و پایان جلسه
- پایان تماس تلفنی
- اعلام نتیجه‌ی حملات

یک جاب اصلی هر دقیقه اجرا می‌شود و موارد سررسیدشده را پردازش می‌کند.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..constants import (
    STEEL_FACTORY_IRON_INTAKE_PER_24H,
    STEEL_FACTORY_OUTPUT_PER_24H,
)
from ..database.base import async_session_factory
from ..database.repositories import facilities as fac_repo
from ..database.repositories import reserves as reserves_repo
from ..database.repositories import trade as trade_repo
from ..enums import (
    DiplomacyStatus,
    FacilityType,
    NewsCategory,
    ResourceType,
    TradeStatus,
)
from ..services.news_service import publish_news  # noqa: F401 (سازگاری)
from ..utils.numbers import fa_number

logger = logging.getLogger(__name__)

# نمونه‌ی سراسری زمان‌بند
scheduler = AsyncIOScheduler(timezone="UTC")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """تضمین آگاه‌بودن datetime از منطقه‌ی زمانی (UTC)."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def process_facility_yields(bot: Bot) -> None:
    """به ازای هر تأسیسات سررسیدشده، بازدهی را به ذخایر اضافه و به مالک پیام می‌دهد (v1.9).

    تأسیسات مشترک (v1.9): بازدهی بین کشور سازنده و شریک به نسبت درصد تقسیم می‌شود.
    """
    from ..database.repositories import countries as countries_repo
    from ..enums import FACILITY_FA, RESOURCE_UNIT_FA

    pings: list[tuple[int, str]] = []  # (owner_user_id, متن پیام بازدهی)

    async with async_session_factory() as session:
        facilities = await fac_repo.all_active_facilities(session)
        now = _utcnow()
        for f in facilities:
            # v1.10.5: هر تأسیسات مستقل پردازش می‌شود تا یک ردیف خراب کل بازدهی را نیندازد
            try:
                if not fac_repo.is_due(f, now):
                    continue

                partner_pct = float(getattr(f, "partner_percent", 0) or 0)
                partner_id = getattr(f, "partner_country", None)
                owner_share = (100.0 - partner_pct) / 100.0
                partner_share = partner_pct / 100.0

                produced_label = ""
                if f.type == FacilityType.STEEL_FACTORY.value:
                    # کارخانه فولاد: آهن مصرف و فولاد تولید می‌کند
                    has_iron = await reserves_repo.has_enough(
                        session, f.country_id, ResourceType.IRON, STEEL_FACTORY_IRON_INTAKE_PER_24H
                    )
                    if has_iron:
                        await reserves_repo.add_amount(
                            session, f.country_id, ResourceType.IRON,
                            -STEEL_FACTORY_IRON_INTAKE_PER_24H,
                        )
                        out = STEEL_FACTORY_OUTPUT_PER_24H
                        if partner_id and partner_pct > 0:
                            await reserves_repo.add_amount(session, f.country_id, ResourceType.STEEL, out * owner_share)
                            await reserves_repo.ensure_reserve(session, partner_id, ResourceType.STEEL.value)
                            await reserves_repo.add_amount(session, partner_id, ResourceType.STEEL, out * partner_share)
                        else:
                            await reserves_repo.add_amount(session, f.country_id, ResourceType.STEEL, out)
                        produced_label = f"{fa_number(out)} {RESOURCE_UNIT_FA[ResourceType.STEEL]} فولاد"
                elif f.resource:
                    # معدن/سکو: منبع مربوطه را اضافه می‌کند
                    total = f.yield_amount
                    if partner_id and partner_pct > 0:
                        await reserves_repo.add_amount(session, f.country_id, f.resource, total * owner_share)
                        await reserves_repo.ensure_reserve(session, partner_id, f.resource)
                        await reserves_repo.add_amount(session, partner_id, f.resource, total * partner_share)
                    else:
                        await reserves_repo.add_amount(session, f.country_id, f.resource, total)
                    try:
                        unit = RESOURCE_UNIT_FA[ResourceType(f.resource)]
                    except (ValueError, KeyError):
                        unit = ""
                    produced_label = f"{fa_number(total)} {unit}"

                f.last_yield_at = now

                # پیام بازدهی به مالک (v1.9)
                if produced_label:
                    try:
                        fac_fa = FACILITY_FA[FacilityType(f.type)]
                    except (ValueError, KeyError):
                        fac_fa = f.type
                    owner_country = await countries_repo.get_country(session, f.country_id)
                    if owner_country and owner_country.owner_user_id:
                        pings.append((
                            owner_country.owner_user_id,
                            f"🏭 شما از «{fac_fa}» به اندازه‌ی {produced_label} بازدهی دریافت کردید.\n"
                            f"⏳ زمان بازدهی بعدی: {fa_number(f.yield_interval_h)} ساعت",
                        ))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Facility yield failed (id=%s): %s", getattr(f, "id", None), exc)
                continue

        await session.commit()

    for owner_id, text in pings:
        try:
            await bot.send_message(owner_id, text)
        except Exception:  # noqa: BLE001
            pass


async def process_investments(bot: Bot) -> None:
    """
    سود ۲۴ساعته‌ی سرمایه‌گذاری‌ها را به سرمایه‌گذار واریز می‌کند و در سرمایه‌گذاری خارجی،
    اثرات اجتماعی را روی کشور هدف اعمال می‌کند. به سرمایه‌گذار پیام بازدهی می‌فرستد (v1.9).
    """
    from ..constants import (
        FOREIGN_INVEST_INFLATION_DROP,
        FOREIGN_INVEST_SATISFACTION_GAIN,
        FOREIGN_INVEST_UNEMPLOYMENT_DROP,
        INVEST_SATISFACTION_GAIN,
        INVESTMENT_CATEGORIES,
        INVESTMENT_YIELD_INTERVAL_H,
    )
    from ..database.repositories import countries as countries_repo
    from ..database.repositories import investments as inv_repo
    from ..utils.numbers import fa_money

    pings: list[tuple[int, str]] = []

    async with async_session_factory() as session:
        items = await inv_repo.all_active(session)
        now = _utcnow()
        for inv in items:
            last = _aware(inv.last_yield_at)
            if last is not None and (now - last).total_seconds() / 3600 < INVESTMENT_YIELD_INTERVAL_H:
                continue
            profit = inv.amount * inv.profit_pct / 100.0
            investor = await countries_repo.get_country(session, inv.investor_country)
            if investor is None:
                continue
            investor.budget = (investor.budget or 0.0) + profit
            target = await countries_repo.get_country(session, inv.target_country)
            if inv.target_country == inv.investor_country:
                investor.public_satisfaction = min(100.0, (investor.public_satisfaction or 0.0) + INVEST_SATISFACTION_GAIN)
            elif target is not None:
                # اثرات اجتماعی سرمایه‌گذاری خارجی روی کشور هدف
                target.public_satisfaction = min(100.0, (target.public_satisfaction or 0.0) + FOREIGN_INVEST_SATISFACTION_GAIN)
                target.unemployment = max(0.0, (target.unemployment or 0.0) - FOREIGN_INVEST_UNEMPLOYMENT_DROP)
                target.inflation = max(0.0, (target.inflation or 0.0) - FOREIGN_INVEST_INFLATION_DROP)

            inv.last_yield_at = now

            fa, _pct = INVESTMENT_CATEGORIES.get(inv.category, (inv.category, 0.0))
            if investor.owner_user_id:
                pings.append((
                    investor.owner_user_id,
                    f"📈 شما از سرمایه‌گذاری در «{fa}» به اندازه‌ی {fa_money(profit)} سود کردید.\n"
                    f"⏳ زمان سود بعد: {fa_number(INVESTMENT_YIELD_INTERVAL_H)} ساعت",
                ))
        await session.commit()

    for owner_id, text in pings:
        try:
            await bot.send_message(owner_id, text)
        except Exception:  # noqa: BLE001
            pass


async def process_shipments(bot: Bot) -> None:
    """محموله‌های WTO که زمان رسیدنشان فرارسیده را تحویل می‌دهد."""
    from ..constants import STRAIT_HOLD_TIMEOUT_HOURS
    from ..database.repositories import countries as countries_repo
    from ..database.repositories import straits as straits_repo
    from ..enums import RESOURCE_FA, RESOURCE_UNIT_FA
    from ..services import geo_service as geo
    from ..services import strait_service
    from ..services.news_service import send_log
    from ..utils.numbers import fa_number

    log_notices: list[str] = []
    user_notices: list[tuple[int, str]] = []  # (owner_user_id, متن)

    async with async_session_factory() as session:
        sales = await trade_repo.list_in_transit(session)
        now = _utcnow()
        for sale in sales:
            # ۱. بررسی تحویل بار بازگشتی به مبدأ
            if getattr(sale, "standoff_action", None) == "RETURNING":
                ret_eta = _aware(sale.ship_eta)
                if ret_eta and now >= ret_eta:
                    sale.strait_status = "RETURNED"
                    sale.status = TradeStatus.REJECTED.value
                    sale.standoff_action = "RETURNED"
                    await reserves_repo.ensure_reserve(session, sale.seller_country, sale.resource)
                    await reserves_repo.add_amount(
                        session, sale.seller_country, sale.resource, sale.amount
                    )
                    seller = await countries_repo.get_country(session, sale.seller_country)
                    try:
                        rtype = ResourceType(sale.resource)
                        rname = RESOURCE_FA[rtype]
                        unit = RESOURCE_UNIT_FA[rtype]
                    except (ValueError, KeyError):
                        rname, unit = sale.resource, ""

                    if seller and seller.owner_user_id:
                        user_notices.append((
                            seller.owner_user_id,
                            f"🚢 <b>بازگشت ایمن محموله به کشور:</b>\n\n"
                            f"کشتی محموله حامل <b>{fa_number(sale.amount)} {unit} {rname}</b> با موفقیت به بندر مبدأ بازگشت و بار مجدداً به موجودی ذخایر کشورتان اضافه شد.",
                        ))
                    log_notices.append(
                        f"🚢 <b>بازگشت موفق محموله به کشور مبدأ</b>\n"
                        f"کشور: {seller.flag if seller else ''} {seller.name_fa if seller else ''}\n"
                        f"بار: {fa_number(sale.amount)} {unit} {rname}"
                    )
                continue

            # ۲. بررسی توقیف طولانی‌مدت در تنگه (تایم‌اوت ۲۴ ساعته)
            if getattr(sale, "strait_status", None) == "HELD_AT_STRAIT":
                held_since = _aware(getattr(sale, "held_since", None))
                if held_since and (now - held_since).total_seconds() >= STRAIT_HOLD_TIMEOUT_HOURS * 3600:
                    sale.strait_status = "RETURNED"
                    sale.status = TradeStatus.REJECTED.value
                    sale.standoff_action = "RETURNED"
                    await reserves_repo.ensure_reserve(session, sale.seller_country, sale.resource)
                    await reserves_repo.add_amount(
                        session, sale.seller_country, sale.resource, sale.amount
                    )

                    s_def = geo.get_strait_def(sale.held_at_strait_id) if sale.held_at_strait_id else None
                    strait_name_fa = s_def["name_fa"] if s_def else "تنگه"

                    seller = await countries_repo.get_country(session, sale.seller_country)
                    buyer = await countries_repo.get_country(session, sale.buyer_country)
                    try:
                        rtype = ResourceType(sale.resource)
                        rname = RESOURCE_FA[rtype]
                        unit = RESOURCE_UNIT_FA[rtype]
                    except (ValueError, KeyError):
                        rname, unit = sale.resource, ""

                    timeout_msg = (
                        f"⏳ <b>پایان مهلت تصمیم‌گیری در {strait_name_fa}</b>\n\n"
                        f"کشتی حامل {fa_number(sale.amount)} {unit} {rname} پس از ۲۴ ساعت توقیف در تنگه، "
                        f"به علت عدم اقدام کشور کنترل‌کننده، آزاد شد و محموله به کشور مبدأ "
                        f"({seller.flag if seller else ''} {seller.name_fa if seller else ''}) عودت یافت."
                    )
                    if seller and seller.owner_user_id:
                        user_notices.append((seller.owner_user_id, timeout_msg))
                    if buyer and buyer.owner_user_id:
                        user_notices.append((buyer.owner_user_id, timeout_msg))
                    log_notices.append(f"🌊⚓ <b>پایان توقیف در {strait_name_fa}:</b>\n{timeout_msg}")
                continue

            if getattr(sale, "strait_status", None) in ("DESTROYED", "CONFISCATED", "RETURNED"):
                continue

            # ۳. پایش خروج امن از تنگه برای کشتی در حال عبور (RUNNING)
            if getattr(sale, "standoff_action", None) == "RUNNING" and sale.held_at_strait_id:
                seller = await countries_repo.get_country(session, sale.seller_country)
                buyer = await countries_repo.get_country(session, sale.buyer_country)
                if seller and buyer:
                    waypoints = geo.get_maritime_waypoints(seller.name_en, buyer.name_en)
                    progress_info = geo.get_strait_transit_progress(waypoints, sale.held_at_strait_id)
                    if progress_info:
                        started = _aware(sale.created_at) or now
                        eta_val = _aware(sale.ship_eta)
                        ratio = max(0.0, min(1.0, (now - started).total_seconds() / (eta_val - started).total_seconds())) if (eta_val and eta_val > started) else 0.0
                        if ratio >= progress_info["exit_ratio"]:
                            s_def = geo.get_strait_def(sale.held_at_strait_id)
                            strait_name_fa = s_def["name_fa"] if s_def else "تنگه"
                            sale.strait_status = "PASSED"
                            sale.standoff_action = "SAILING"
                            sale.held_at_strait_id = None
                            sale.held_since = None
                            if seller and seller.owner_user_id:
                                user_notices.append((
                                    seller.owner_user_id,
                                    f"🛡 <b>خروج موفق از حریم امنیتی {strait_name_fa}:</b>\n\n"
                                    "کشتی شما از برد عملیاتی تنگه خارج شده و وارد آب‌های آزاد بین‌المللی گردید. حاکم تنگه دیگر نمی‌تواند به شناور شما حمله کند.",
                                ))

            # ۴. پایش ورود کشتی به محدوده دهانه تنگه مسدود (STANDOFF Proximity Trigger)
            mode = (sale.transport_mode or "SEA").upper()
            if mode == "SEA" and getattr(sale, "strait_status", None) not in ("PASSED", "HELD_AT_STRAIT"):
                seller = await countries_repo.get_country(session, sale.seller_country)
                buyer = await countries_repo.get_country(session, sale.buyer_country)
                if seller and buyer:
                    strait_ids = geo.get_route_straits(seller.name_en, buyer.name_en)
                    if strait_ids:
                        blocked_sid = await straits_repo.get_first_blocked_strait(
                            session, strait_ids, sale.seller_country, sale.buyer_country
                        )
                        if blocked_sid:
                            waypoints = geo.get_maritime_waypoints(seller.name_en, buyer.name_en)
                            progress_info = geo.get_strait_transit_progress(waypoints, blocked_sid)
                            if progress_info:
                                started = _aware(sale.created_at) or now
                                eta_val = _aware(sale.ship_eta)
                                ratio = max(0.0, min(1.0, (now - started).total_seconds() / (eta_val - started).total_seconds())) if (eta_val and eta_val > started) else 0.0
                                if ratio >= progress_info["approach_ratio"]:
                                    await strait_service.trigger_strait_standoff(bot, session, sale, blocked_sid)
                                    continue

            eta = _aware(sale.ship_eta)
            if eta is None or eta > now:
                continue
            # افزودن منبع به ذخایر خریدار
            await reserves_repo.ensure_reserve(session, sale.buyer_country, sale.resource)
            await reserves_repo.add_amount(
                session, sale.buyer_country, sale.resource, sale.amount
            )
            sale.status = TradeStatus.DELIVERED

            # آماده‌سازی متن خبر با جزئیات (کشورها + منبع + مقدار)
            seller = await countries_repo.get_country(session, sale.seller_country)
            buyer = await countries_repo.get_country(session, sale.buyer_country)
            try:
                rtype = ResourceType(sale.resource)
                rname = RESOURCE_FA[rtype]
                unit = RESOURCE_UNIT_FA[rtype]
            except (ValueError, KeyError):
                rname, unit = sale.resource, ""
            seller_name = f"{seller.flag} {seller.name_fa}" if seller else "?"
            buyer_name = f"{buyer.flag} {buyer.name_fa}" if buyer else "?"
            log_notices.append(
                "📦 <b>محموله تحویل شد</b>\n"
                f"فروشنده: {seller_name}\n"
                f"خریدار: {buyer_name}\n"
                f"منبع: {fa_number(sale.amount)} {unit} {rname}"
            )
            if buyer and buyer.owner_user_id:
                user_notices.append((
                    buyer.owner_user_id,
                    f"📦 محموله‌ی شما رسید: {fa_number(sale.amount)} {unit} {rname} "
                    f"به ذخایر کشورتان اضافه شد.",
                ))
        await session.commit()

    # اطلاع به کاربران (پیوی) و گروه لاگ پس از commit (نه کانال WTO)
    for owner_id, text in user_notices:
        try:
            await bot.send_message(owner_id, text)
        except Exception:  # noqa: BLE001 — خطای ارسال نباید scheduler را متوقف کند
            pass
    for text in log_notices:
        await send_log(bot, text)



async def process_meetings(bot: Bot) -> None:
    """رسیدن مسافر (اعلام شروع نشست) و پایان دیدارهای دوجانبه را مدیریت می‌کند.

    v1.10.1: علاوه بر پایان ۶۰ دقیقه‌ای، نشست‌هایی که ۱۰ دقیقه هیچ پیامی نداشته‌اند نیز
    خودکار بسته می‌شوند و به طرفین اطلاع داده می‌شود.
    """
    from sqlalchemy import select

    from ..config import get_settings
    from ..constants import MEETING_DURATION_MINUTES, MEETING_IDLE_TIMEOUT_MINUTES
    from ..database.models import Meeting
    from ..database.repositories import countries as countries_repo
    from ..database.repositories import users as users_repo
    from ..services.media import send_photo_news

    settings = get_settings()
    # خبرهای شروع نشست (کپشن) برای ارسال پس از commit
    start_captions: list[str] = []
    # (owner_ids) دیدارهایی که تازه شروع شده‌اند تا دکمه‌ی «پایان نشست» برایشان برود
    started_owner_ids: list[int] = []
    # (owner_ids) دیدارهایی که خودکار بسته شدند تا پیام پایان برایشان برود
    ended_owner_ids: list[int] = []

    async def _pres(session, country) -> str:
        if country and country.owner_user_id:
            u = await users_repo.get_user(session, country.owner_user_id)
            if u and u.president_name:
                return u.president_name
        return country.name_fa if country else "—"

    async with async_session_factory() as session:
        result = await session.execute(
            select(Meeting).where(
                Meeting.status.in_([DiplomacyStatus.PENDING, DiplomacyStatus.ACTIVE])
            )
        )
        meetings = list(result.scalars().all())
        now = _utcnow()
        for m in meetings:
            travel_eta = _aware(m.travel_eta)
            meeting_ends = _aware(m.meeting_ends_at)
            # رسیدن مسافر → اعلام شروع نشست (یک‌بار)
            if (
                m.status == DiplomacyStatus.ACTIVE
                and not m.start_announced
                and travel_eta
                and travel_eta <= now
            ):
                m.start_announced = True
                m.last_msg_at = now  # شروع شمارش تایم‌اوت سکوت از لحظه‌ی رسیدن (v1.10.1)
                traveler = await countries_repo.get_country(session, m.traveler_country)
                host = await countries_repo.get_country(session, m.host_country)
                for c in (traveler, host):
                    if c and c.owner_user_id:
                        started_owner_ids.append(c.owner_user_id)
                k = await _pres(session, traveler)
                o = await _pres(session, host)
                x = f"{traveler.flag} {traveler.name_fa}" if traveler else "?"
                b = f"{host.flag} {host.name_fa}" if host else "?"
                start_captions.append(
                    f"🤝 | نشست دیپلماتیک بین جناب {k} و جناب {o} رئسای جمهور کشور "
                    f"{x} و {b} دقایقی پیش شروع شد. پیش بینی میشود این دو کشور در رابطه با "
                    "مسائل دیپلماتیک با یکدیگر بحث و گفتگو داشته باشند.\n\n"
                    f"⏳ | مدت زمان گفتگو {fa_number(MEETING_DURATION_MINUTES)} دقیقه پیش بینی شده. "
                    "اطلاعات بیشتر در رابطه با این نشست بزودی اعلام خواهد شد."
                )
            # پایان جلسه: یا اتمام ۶۰ دقیقه، یا سکوت ۱۰ دقیقه پس از رسیدن (v1.10.1)
            if m.status == DiplomacyStatus.ACTIVE and travel_eta and travel_eta <= now:
                arrived_idle = _aware(m.last_msg_at) or travel_eta
                idle_too_long = now - arrived_idle >= timedelta(
                    minutes=MEETING_IDLE_TIMEOUT_MINUTES
                )
                time_up = meeting_ends and meeting_ends <= now
                if time_up or idle_too_long:
                    m.status = DiplomacyStatus.COMPLETED
                    for cid in (m.traveler_country, m.host_country):
                        c = await countries_repo.get_country(session, cid)
                        if c and c.owner_user_id:
                            ended_owner_ids.append(c.owner_user_id)
        await session.commit()

    if settings.news_diplomacy_channel_id is not None:
        for caption in start_captions:
            await send_photo_news(bot, settings.news_diplomacy_channel_id, "meeting", caption)

    # ارسال دکمه‌ی «پایان نشست» به شرکت‌کنندگان دیدار دوجانبه‌ی تازه‌شروع‌شده (v1.8)
    if started_owner_ids:
        from ..keyboards.diplomacy import end_meeting_kb

        for oid in started_owner_ids:
            try:
                await bot.send_message(
                    oid,
                    "🤝 نشست آغاز شد. برای پایان دادن به نشست از دکمه‌ی زیر استفاده کنید.\n"
                    "💬 می‌توانید روی پیام طرف مقابل ریپلای کنید.",
                    reply_markup=end_meeting_kb(),
                )
            except Exception:  # noqa: BLE001
                pass

    # اطلاع پایان خودکار نشست به طرفین (v1.10.1)
    for oid in ended_owner_ids:
        try:
            await bot.send_message(
                oid,
                "🔚 نشست شما به‌صورت خودکار پایان یافت (اتمام زمان یا سکوت طولانی). "
                "اکنون می‌توانید نشست/تماس جدید داشته باشید.",
            )
        except Exception:  # noqa: BLE001
            pass


async def process_group_meetings(bot: Bot) -> None:
    """
    نشست‌های چندجانبه را مدیریت می‌کند (v1.5):
    - وقتی زمان شروع (رسیدن آخرین کشور) فرارسید، نشست را فعال و به همه اعلام می‌کند.
    - نشست‌هایی که زمانشان تمام شده را می‌بندد.
    """
    from sqlalchemy import select

    from ..config import get_settings
    from ..constants import MEETING_DURATION_MINUTES, MEETING_IDLE_TIMEOUT_MINUTES
    from ..database.models import GroupMeeting, GroupMeetingParticipant
    from ..database.repositories import countries as countries_repo
    from ..services.media import send_photo_news

    settings = get_settings()
    started_notices: list[tuple[list[int], str, str]] = []  # (owner_ids, notice, news)
    ended_owner_ids: list[int] = []  # نشست‌های چندجانبه‌ی خودکار بسته‌شده (v1.10.1)

    async with async_session_factory() as session:
        now = _utcnow()
        # فعال‌سازی نشست‌هایی که زمان شروعشان رسیده
        result = await session.execute(
            select(GroupMeeting).where(GroupMeeting.status == DiplomacyStatus.PENDING)
        )
        for meeting in result.scalars().all():
            start_at = _aware(meeting.start_at)
            if start_at is None or start_at > now:
                continue
            meeting.status = DiplomacyStatus.ACTIVE
            meeting.meeting_ends_at = now + timedelta(minutes=MEETING_DURATION_MINUTES)
            meeting.last_msg_at = now  # شروع شمارش تایم‌اوت سکوت (v1.10.1)

            host = await countries_repo.get_country(session, meeting.host_country)
            pres = await session.execute(
                select(GroupMeetingParticipant).where(
                    GroupMeetingParticipant.meeting_id == meeting.id,
                    GroupMeetingParticipant.response == DiplomacyStatus.ACTIVE,
                )
            )
            members = [host] if host else []
            for p in pres.scalars().all():
                c = await countries_repo.get_country(session, p.country_id)
                if c:
                    members.append(c)
            names = "، ".join(f"{c.flag} {c.name_fa}" for c in members if c)
            owner_ids = [c.owner_user_id for c in members if c and c.owner_user_id]
            notice = (
                f"👥 <b>نشست «{meeting.title}» آغاز شد</b>\n\n"
                f"همه‌ی کشورها به میزبان رسیدند.\n"
                f"شرکت‌کنندگان: {names}\n"
                f"⏱ مدت نشست: {MEETING_DURATION_MINUTES} دقیقه.\n\n"
                "💬 هر پیامی بنویسید برای همه‌ی کشورهای حاضر در نشست ارسال می‌شود.\n"
                "📜 برای عقد قرارداد با یکی از حاضران از دستور /contract استفاده کنید."
            )
            news = (
                f"🤝 | نشست دیپلماتیک چندجانبه «{meeting.title}» به میزبانی "
                f"{host.flag + ' ' + host.name_fa if host else '?'} با حضور کشورهای "
                f"{names} دقایقی پیش آغاز شد. پیش بینی میشود این کشورها در رابطه با "
                "مسائل دیپلماتیک با یکدیگر بحث و گفتگو داشته باشند.\n\n"
                f"⏳ | مدت زمان گفتگو {fa_number(MEETING_DURATION_MINUTES)} دقیقه پیش بینی شده. "
                "اطلاعات بیشتر در رابطه با این نشست بزودی اعلام خواهد شد."
            )
            started_notices.append((owner_ids, notice, news))

        # بستن نشست‌های پایان‌یافته: اتمام زمان یا سکوت ۱۰ دقیقه (v1.10.1)
        result = await session.execute(
            select(GroupMeeting).where(GroupMeeting.status == DiplomacyStatus.ACTIVE)
        )
        for meeting in result.scalars().all():
            ends = _aware(meeting.meeting_ends_at)
            last = _aware(meeting.last_msg_at) or ends
            time_up = ends and ends <= now
            idle_too_long = last and (now - last >= timedelta(minutes=MEETING_IDLE_TIMEOUT_MINUTES))
            if time_up or idle_too_long:
                meeting.status = DiplomacyStatus.COMPLETED
                host = await countries_repo.get_country(session, meeting.host_country)
                if host and host.owner_user_id:
                    ended_owner_ids.append(host.owner_user_id)
                pres = await session.execute(
                    select(GroupMeetingParticipant).where(
                        GroupMeetingParticipant.meeting_id == meeting.id,
                        GroupMeetingParticipant.response == DiplomacyStatus.ACTIVE,
                    )
                )
                for p in pres.scalars().all():
                    c = await countries_repo.get_country(session, p.country_id)
                    if c and c.owner_user_id:
                        ended_owner_ids.append(c.owner_user_id)
        await session.commit()

    # ارسال اعلان‌ها پس از commit
    from ..keyboards.diplomacy import end_meeting_kb

    for owner_ids, notice, news in started_notices:
        for oid in owner_ids:
            try:
                await bot.send_message(oid, notice, reply_markup=end_meeting_kb())
            except Exception:  # noqa: BLE001
                pass
        if settings.news_diplomacy_channel_id is not None:
            await send_photo_news(bot, settings.news_diplomacy_channel_id, "meeting", news)

    # اطلاع پایان خودکار نشست چندجانبه به اعضا (v1.10.1)
    for oid in ended_owner_ids:
        try:
            await bot.send_message(
                oid,
                "🔚 نشست چندجانبه‌ی شما به‌صورت خودکار پایان یافت (اتمام زمان یا سکوت طولانی). "
                "اکنون می‌توانید نشست/تماس جدید داشته باشید.",
            )
        except Exception:  # noqa: BLE001
            pass


async def process_calls() -> None:
    """تماس‌های تلفنی که زمانشان تمام شده را می‌بندد."""
    from sqlalchemy import select

    from ..database.models import PhoneCall

    async with async_session_factory() as session:
        result = await session.execute(
            select(PhoneCall).where(PhoneCall.status == DiplomacyStatus.ACTIVE)
        )
        calls = list(result.scalars().all())
        now = _utcnow()
        for call in calls:
            ends = _aware(call.ends_at)
            if ends and ends <= now:
                call.status = DiplomacyStatus.COMPLETED
        await session.commit()


async def process_military_factories(bot: Bot) -> None:
    """
    کارخانه‌های نظامی سررسیدشده را پردازش می‌کند (v1.7):
    اگر منابع مصرفی هر چرخه کافی باشد، آن‌ها را کسر و تعداد بازدهی را به
    قلم تجهیزات مربوطه اضافه می‌کند. به مالک پیام بازدهی می‌دهد (v1.9).
    """
    from ..constants import MIL_FACTORY_INTAKE
    from ..database.models import MilitaryAsset
    from ..database.repositories import countries as countries_repo
    from ..database.repositories import military as mil_repo
    from ..database.repositories import military_factory as milfac_repo
    from ..enums import MilitaryFactoryType

    pings: list[tuple[int, str]] = []

    async with async_session_factory() as session:
        factories = await milfac_repo.all_active_factories(session)
        now = _utcnow()
        for f in factories:
            # v1.10.5: هر کارخانه مستقل پردازش می‌شود تا یک ردیف خراب کل بازدهی را نیندازد
            try:
                if not milfac_repo.is_due(f, now):
                    continue
                try:
                    intake = MIL_FACTORY_INTAKE[MilitaryFactoryType(f.factory_type)]
                except (ValueError, KeyError):
                    intake = {}
                # بررسی کافی‌بودن همه‌ی منابع مصرفی این چرخه
                enough = True
                for key, amount in intake.items():
                    if not await reserves_repo.has_enough(session, f.country_id, key, amount):
                        enough = False
                        break
                if not enough:
                    # منابع کافی نیست؛ این چرخه تولیدی ندارد (زمان بازدهی هم جلو نمی‌رود)
                    continue
                for key, amount in intake.items():
                    await reserves_repo.add_amount(session, f.country_id, key, -amount)

                asset = await mil_repo.get_asset_by_name(session, f.country_id, f.asset_name)
                if asset is not None:
                    asset.count += f.yield_amount
                else:
                    session.add(MilitaryAsset(
                        country_id=f.country_id,
                        category=f.category,
                        branch="",
                        name=f.asset_name,
                        unit=f.unit,
                        count=f.yield_amount,
                    ))
                f.last_yield_at = now

                # پیام بازدهی به مالک (v1.9)
                owner_country = await countries_repo.get_country(session, f.country_id)
                if owner_country and owner_country.owner_user_id:
                    pings.append((
                        owner_country.owner_user_id,
                        f"🏭 شما از کارخانه‌ی «{f.asset_name}» به اندازه‌ی {fa_number(f.yield_amount)} "
                        f"{f.unit} بازدهی دریافت کردید.\n"
                        f"⏳ زمان بازدهی بعدی: {fa_number(f.yield_interval_h)} ساعت",
                    ))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Military factory yield failed (id=%s): %s", getattr(f, "id", None), exc)
                continue
        await session.commit()

    for owner_id, text in pings:
        try:
            await bot.send_message(owner_id, text)
        except Exception:  # noqa: BLE001
            pass


async def process_military_shipments(bot: Bot) -> None:
    """محموله‌های نظامی WTO که زمان رسیدنشان فرارسیده را تحویل می‌دهد (v1.7)."""
    from ..config import get_settings
    from ..database.models import MilitaryAsset
    from ..database.repositories import countries as countries_repo
    from ..database.repositories import military as mil_repo
    from ..database.repositories import military_sale as milsale_repo
    from ..services.news_service import send_log

    settings = get_settings()
    buyer_notices: list[tuple[int, str]] = []
    log_notices: list[str] = []

    async with async_session_factory() as session:
        sales = await milsale_repo.list_in_transit(session)
        now = _utcnow()
        for sale in sales:
            eta = _aware(sale.ship_eta)
            if eta is None or eta > now:
                continue
            # افزودن تجهیزات به موجودی خریدار (در صورت نبود، ساخت قلم جدید)
            asset = await mil_repo.get_asset_by_name(session, sale.buyer_country, sale.name)
            if asset is not None:
                asset.count += sale.count
            else:
                session.add(MilitaryAsset(
                    country_id=sale.buyer_country,
                    category=sale.category,
                    branch=sale.branch,
                    name=sale.name,
                    unit=sale.unit,
                    count=sale.count,
                ))
            sale.status = TradeStatus.DELIVERED

            seller = await countries_repo.get_country(session, sale.seller_country)
            buyer = await countries_repo.get_country(session, sale.buyer_country)
            seller_name = f"{seller.flag} {seller.name_fa}" if seller else "?"
            buyer_name = f"{buyer.flag} {buyer.name_fa}" if buyer else "?"
            log_notices.append(
                "🪖 <b>محموله نظامی تحویل شد</b>\n"
                f"فروشنده: {seller_name}\n"
                f"خریدار: {buyer_name}\n"
                f"تجهیزات: {fa_number(sale.count)} {sale.unit} {sale.name}"
            )
            if buyer and buyer.owner_user_id:
                buyer_notices.append((
                    buyer.owner_user_id,
                    f"🪖 محموله‌ی نظامی شما رسید: {fa_number(sale.count)} {sale.unit} {sale.name} "
                    "به تجهیزات کشورتان اضافه شد.",
                ))
        await session.commit()

    for owner_id, text in buyer_notices:
        try:
            await bot.send_message(owner_id, text)
        except Exception:  # noqa: BLE001
            pass
    for text in log_notices:
        await send_log(bot, text)


async def process_economic_projects(bot: Bot | None = None, session_override: AsyncSession | None = None) -> None:
    """پردازش سود و بازدهی ۷۲ ساعته پروژه‌های فعال اقتصادی (آپدیت شماره ۹)."""
    from ..database.repositories import countries as countries_repo
    from ..database.repositories import economic_projects as proj_repo
    from ..services.economic_project_service import format_resources_dict, process_project_payout
    from ..services.news_service import send_log
    from ..utils.numbers import fa_money

    now = _utcnow()
    pings: list[tuple[int, str]] = []
    log_msgs: list[str] = []

    async def _process(session: AsyncSession) -> None:
        active_projects = await proj_repo.list_all_active(session)
        for proj in active_projects:
            next_at = _aware(proj.next_yield_at)
            if next_at and now < next_at:
                continue

            country = await countries_repo.get_country(session, proj.country_id)
            if not country:
                continue

            payout = await process_project_payout(session, proj, country, now)

            cash_str = fa_money(payout["cash"])
            res_str = format_resources_dict(payout["resources"])
            res_line = f"\n📦 بازدهی ذخایر: {res_str}" if payout["resources"] else ""

            log_msgs.append(
                f"🏗 <b>واریز سود ۷۲ ساعته پروژه اقتصادی</b>\n"
                f"کشور: {country.flag} {country.name_fa}\n"
                f"پروژه: <b>{proj.title}</b>\n"
                f"مبلغ سود: {cash_str}{res_line}\n"
                f"موعد بعدی: ۷۲ ساعت دیگر"
            )

            if country.owner_user_id:
                pings.append((
                    country.owner_user_id,
                    f"🏗 <b>گزارش بازدهی ۷۲ ساعته پروژه «{proj.title}»:</b>\n\n"
                    f"💰 مبلغ <b>{cash_str}</b> به خزانه کشور واریز شد.{res_line}\n\n"
                    f"⏳ بازدهی بعدی: ۷۲ ساعت دیگر",
                ))

        await session.commit()

    if session_override is not None:
        await _process(session_override)
    else:
        async with async_session_factory() as session:
            await _process(session)

    if bot is not None:
        for owner_id, text in pings:
            try:
                await bot.send_message(owner_id, text)
            except Exception:
                pass
        for text in log_msgs:
            try:
                await send_log(bot, text)
            except Exception:
                pass


async def process_satellites(bot: Bot | None = None) -> None:
    from ..services import satellite_service
    async with async_session_factory() as session:
        await satellite_service.process_satellite_launches(session)
        await satellite_service.process_economic_satellites_yield(session, bot)


async def process_taxes(bot: Bot) -> None:
    from sqlalchemy import select
    from ..constants import TAX_YIELD_INTERVAL_H
    from ..database.models import Country
    from ..services.governance_service import compute_tax_revenue, tax_satisfaction_delta
    from ..utils.numbers import fa_money, fa_number

    pings: list[tuple[int, str]] = []

    async with async_session_factory() as session:
        result = await session.execute(select(Country).where(Country.is_claimed == True))
        countries = list(result.scalars().all())
        now = _utcnow()
        for c in countries:
            last = _aware(c.last_tax_collected_at)
            if last is not None and (now - last).total_seconds() / 3600 < TAX_YIELD_INTERVAL_H:
                continue

            revenue = compute_tax_revenue(c)
            sat_delta = tax_satisfaction_delta(c.tax_rate)

            c.budget = (c.budget or 0.0) + revenue
            c.public_satisfaction = max(0.0, min(100.0, (c.public_satisfaction or 0.0) + sat_delta))
            c.last_tax_collected_at = now

            if c.owner_user_id and revenue > 0:
                sat_sign = "+" if sat_delta >= 0 else ""
                pings.append((
                    c.owner_user_id,
                    f"💰 درآمد مالیاتی دریافت شد: {fa_money(revenue)}\n"
                    f"تأثیر بر رضایت عمومی: {sat_sign}{fa_number(sat_delta, 1)}\n"
                    f"⏳ زمان جمع‌آوری بعدی: {fa_number(TAX_YIELD_INTERVAL_H)} ساعت"
                ))
        await session.commit()

    for owner_id, text in pings:
        try:
            await bot.send_message(owner_id, text)
        except Exception:
            pass


async def process_protests(bot: Bot) -> None:
    from sqlalchemy import select
    from ..database.models import Country
    from ..database.repositories import governance as gov_repo
    from ..services.governance_service import maybe_generate_protest, apply_active_protest_effects
    from ..enums import PROTEST_FA

    pings: list[tuple[int, str]] = []
    
    PROTEST_CHECK_INTERVAL_H = 24

    async with async_session_factory() as session:
        result = await session.execute(select(Country).where(Country.is_claimed == True))
        countries = list(result.scalars().all())
        now = _utcnow()

        for c in countries:
            last_check = _aware(c.last_protest_check_at)
            if last_check is None or (now - last_check).total_seconds() / 3600 >= PROTEST_CHECK_INTERVAL_H:
                active_protests = await gov_repo.get_active_protests(session, c.id)
                if active_protests:
                    apply_active_protest_effects(c, len(active_protests))
                    if c.owner_user_id:
                        pings.append((
                            c.owner_user_id,
                            f"⚠️ به دلیل وجود {len(active_protests)} اعتراض فعال، ثبات و رضایت عمومی کشور شما کاهش یافت!"
                        ))

                new_protest = maybe_generate_protest(c)
                if new_protest:
                    ptype, title, desc, severity = new_protest
                    await gov_repo.create_protest(session, c.id, ptype.value, title, severity, desc)
                    fa = PROTEST_FA.get(ptype, ptype.value)
                    if c.owner_user_id:
                        pings.append((
                            c.owner_user_id,
                            f"🚨 <b>اعتراض جدید شکل گرفت!</b>\n"
                            f"عنوان: {title}\nنوع: {fa}\n\nبرای رسیدگی به بخش حاکمیت > اعتراضات مراجعه کنید."
                        ))

                c.last_protest_check_at = now

        await session.commit()

    for owner_id, text in pings:
        try:
            await bot.send_message(owner_id, text)
        except Exception:
            pass



async def process_nuclear(bot: Bot) -> None:
    """پردازش زمان‌دار برنامه‌های هسته‌ای (v1.10.4):

    ۱. اتمام ساخت تأسیسات و اتمام تحقیقات
    ۲. اتمام چرخه‌ی تولید سانتریفیوژ
    ۳. زنجیره‌ی سوخت ۲۴ساعته (آسیاب کیک زرد + تبدیل UF6)
    ۴. تیک غنی‌سازی (مدل SWU) + گزارش رسیدن به هر رده
    ۵. اتمام مونتاژ کلاهک
    ۶. اجرای آزمایش هسته‌ای سررسیدشده (خبر عمومی)
    ۷. تاس کشف برنامه بر اساس شاخص افشا (خبر «گزارش آژانس»)
    """
    import random as _random

    from ..constants import (
        CENTRIFUGE_BATCH_SIZE,
        CONVERSION_UF6_PER_24H,
        CONVERSION_YELLOWCAKE_INTAKE_PER_24H,
        MILL_URANIUM_INTAKE_PER_24H,
        MILL_YELLOWCAKE_PER_24H,
        NUCLEAR_DETECTION_CHANCE_FACTOR,
    )
    from ..database.repositories import countries as countries_repo
    from ..database.repositories import nuclear as nuc_repo
    from ..enums import (
        NuclearFacilityStatus,
        NuclearFacilityType,
        NuclearTechType,
        WarheadStatus,
    )
    from ..services import nuclear_service
    from ..services.news_service import publish_news as _publish, send_log
    from ..constants import NUCLEAR_TECHS

    now = _utcnow()
    owner_pings: list[tuple[int, str]] = []      # (owner_user_id, text)
    public_news: list[str] = []                  # کانال نظامی
    diplo_news: list[str] = []                   # کانال دیپلماسی (کشف برنامه)
    log_msgs: list[str] = []

    async with async_session_factory() as session:
        # کش کشورها برای پیام‌دادن
        async def _country(cid: int):
            return await countries_repo.get_country(session, cid)

        # ---------- ۱a. اتمام ساخت تأسیسات ----------
        for fac in await nuc_repo.list_building_facilities(session):
            if nuclear_service.facility_done_at(fac) <= now:
                fac.status = NuclearFacilityStatus.ACTIVE.value
                fac.built_at = now
                c = await _country(fac.country_id)
                if c and c.owner_user_id:
                    owner_pings.append((
                        c.owner_user_id,
                        f"☢️ <b>اطلاعیه‌ی برنامه‌ی هسته‌ای:</b> ساخت «{fac.name}» "
                        f"در {fac.location or 'محل نامشخص'} به پایان رسید و اکنون فعال است."
                        + (" (تأسیسات زیرزمینی 🕳)" if fac.is_underground else ""),
                    ))
                if c:
                    log_msgs.append(
                        f"☢️ اتمام ساخت تأسیسات هسته‌ای — {c.flag} {c.name_fa}: {fac.name}"
                        f"{' (زیرزمینی)' if fac.is_underground else ''}"
                    )

        # ---------- ۱b. اتمام تحقیقات ----------
        for tech in await nuc_repo.list_pending_techs(session):
            if nuclear_service.tech_done_at(tech) <= now:
                tech.is_done = True
                tech.done_at = now
                c = await _country(tech.country_id)
                tech_fa = NUCLEAR_TECHS[NuclearTechType(tech.tech_type)][0]
                if c and c.owner_user_id:
                    owner_pings.append((
                        c.owner_user_id,
                        f"🧪 <b>تحقیقات کامل شد:</b> فناوری «{tech_fa}» در دسترس است.",
                    ))
                if c:
                    log_msgs.append(f"🧪 اتمام تحقیق هسته‌ای — {c.flag} {c.name_fa}: {tech_fa}")

        # ---------- پردازش برنامه‌های فعال ----------
        for program in await nuc_repo.list_active_programs(session):
            c = await _country(program.country_id)
            if c is None:
                continue

            # ۲. اتمام چرخه‌ی سانتریفیوژ
            batch_done = _aware(program.centrifuge_batch_done_at)
            if batch_done is not None and batch_done <= now:
                program.centrifuges += CENTRIFUGE_BATCH_SIZE
                program.centrifuge_batch_done_at = None
                if c.owner_user_id:
                    owner_pings.append((
                        c.owner_user_id,
                        f"⚙️ <b>چرخه‌ی تولید سانتریفیوژ تکمیل شد:</b> {fa_number(CENTRIFUGE_BATCH_SIZE)} "
                        f"سانتریفیوژ جدید (مجموع: {fa_number(program.centrifuges)}).",
                    ))

            # ۳. زنجیره‌ی سوخت ۲۴ساعته (آسیاب + تبدیل)
            last_chain = _aware(program.last_chain_tick_at)
            if last_chain is None:
                program.last_chain_tick_at = now
            elif (now - last_chain).total_seconds() / 3600.0 >= 24.0:
                program.last_chain_tick_at = now
                chain_notes: list[str] = []

                # آسیاب: سنگ اورانیوم → کیک زرد
                mills = await nuc_repo.list_active_facilities(
                    session, program.country_id, NuclearFacilityType.MILL
                )
                for mill in mills:
                    eff = mill.integrity_pct / 100.0
                    intake = MILL_URANIUM_INTAKE_PER_24H * eff
                    if await reserves_repo.has_enough(
                        session, program.country_id, ResourceType.URANIUM, intake
                    ):
                        await reserves_repo.add_amount(
                            session, program.country_id, ResourceType.URANIUM, -intake
                        )
                        made = MILL_YELLOWCAKE_PER_24H * eff
                        program.yellowcake_tons += made
                        chain_notes.append(
                            f"🟡 آسیاب: {made:.1f} تن کیک زرد (انبار: {program.yellowcake_tons:.1f} تن)"
                        )

                # تبدیل: کیک زرد → UF6
                convs = await nuc_repo.list_active_facilities(
                    session, program.country_id, NuclearFacilityType.CONVERSION
                )
                for conv in convs:
                    eff = conv.integrity_pct / 100.0
                    intake = CONVERSION_YELLOWCAKE_INTAKE_PER_24H * eff
                    if program.yellowcake_tons >= intake:
                        program.yellowcake_tons -= intake
                        made = CONVERSION_UF6_PER_24H * eff
                        program.uf6_tons += made
                        chain_notes.append(
                            f"💨 تبدیل: {made:.1f} تن UF6 (انبار: {program.uf6_tons:.1f} تن)"
                        )

                if chain_notes and c.owner_user_id:
                    owner_pings.append((
                        c.owner_user_id,
                        "☢️ <b>گزارش ۲۴ساعته‌ی زنجیره‌ی سوخت هسته‌ای:</b>\n" + "\n".join(chain_notes)
                        + "\n⏳ چرخه‌ی بعدی: ۲۴ ساعت دیگر",
                    ))

            # ۴. تیک غنی‌سازی
            if program.enrich_tier is not None:
                tier_key = program.enrich_tier
                before = nuclear_service.tier_stock_kg(program, tier_key)
                produced = nuclear_service.enrichment_tick(program, now)
                if produced > 0:
                    after = nuclear_service.tier_stock_kg(program, tier_key)
                    tier_fa = nuclear_service.tier_info(tier_key)[1]
                    # پیام فقط وقتی از مرزهای مهم عبور می‌کند (هر ۱۰ کیلوگرم) تا اسپم نشود
                    if int(before // 10) != int(after // 10) and c.owner_user_id:
                        owner_pings.append((
                            c.owner_user_id,
                            f"⚛️ <b>پیشرفت غنی‌سازی:</b> موجودی رده‌ی {tier_fa} "
                            f"به {after:.1f} کیلوگرم رسید.",
                        ))
                # اگر خوراک تمام شد، غنی‌سازی خودکار متوقف شود
                feed_empty = (
                    program.uf6_tons <= 0.0005
                    if nuclear_service.tier_info(tier_key)[4] is None
                    else nuclear_service.tier_stock_kg(
                        program, nuclear_service.tier_info(tier_key)[4]
                    ) <= 0.0005
                )
                if feed_empty:
                    tier_fa = nuclear_service.tier_info(tier_key)[1]
                    program.enrich_tier = None
                    program.enrich_centrifuges = 0
                    program.swu_accumulated = 0.0
                    if c.owner_user_id:
                        owner_pings.append((
                            c.owner_user_id,
                            f"⏸ <b>غنی‌سازی متوقف شد:</b> خوراک رده‌ی {tier_fa} تمام شد. "
                            "زنجیره‌ی تولید خوراک را تقویت کنید.",
                        ))

            # ۷. تاس کشف برنامه (فقط برنامه‌های هنوز مخفی)
            if not program.is_discovered and program.exposure > 0:
                chance = program.exposure * NUCLEAR_DETECTION_CHANCE_FACTOR
                if _random.uniform(0.0, 100.0) <= chance:
                    program.is_discovered = True
                    program.discovered_at = now
                    diplo_news.append(
                        "🔴 <b>گزارش فوق‌محرمانه‌ی آژانس بین‌المللی انرژی اتمی!!</b>\n\n"
                        f"🛰 تصاویر ماهواره‌ای و اسناد اطلاعاتی تازه نشان می‌دهد کشور "
                        f"{c.flag} <b>{c.name_fa}</b> به‌صورت مخفیانه در حال توسعه‌ی "
                        "برنامه‌ی هسته‌ای است!\n"
                        "⚠️ شورای امنیت خواستار توضیح فوری این کشور و دسترسی بازرسان شد. "
                        "احتمال تحریم‌های بین‌المللی وجود دارد."
                    )
                    if c.owner_user_id:
                        owner_pings.append((
                            c.owner_user_id,
                            "🚨 <b>هشدار امنیتی:</b> برنامه‌ی هسته‌ای شما توسط سرویس‌های اطلاعاتی "
                            "<b>کشف شد</b> و در رسانه‌های جهانی منتشر گردید! منتظر واکنش‌های دیپلماتیک باشید.",
                        ))
                    log_msgs.append(
                        f"🚨 کشف برنامه‌ی هسته‌ای — {c.flag} {c.name_fa} (شاخص افشا: {program.exposure:.0f})"
                    )

        # ---------- ۵. اتمام مونتاژ کلاهک ----------
        for wh in await nuc_repo.list_assembling_warheads(session):
            if nuclear_service.warhead_done_at(wh) <= now:
                wh.status = WarheadStatus.ASSEMBLED.value
                wh.assembled_at = now
                c = await _country(wh.country_id)
                if c and c.owner_user_id:
                    owner_pings.append((
                        c.owner_user_id,
                        f"☢️ <b>کلاهک هسته‌ای آماده شد:</b> «{wh.name}» با قدرت "
                        f"{wh.yield_kt:.0f} کیلوتن به زرادخانه‌ی شما افزوده شد.",
                    ))
                if c:
                    log_msgs.append(
                        f"☢️ کلاهک هسته‌ای مونتاژ شد — {c.flag} {c.name_fa}: «{wh.name}» ({wh.yield_kt:.0f}kt)"
                    )

        # ---------- ۶. اجرای آزمایش‌های سررسیدشده ----------
        for test in await nuc_repo.list_pending_tests(session):
            sched = _aware(test.scheduled_at)
            if sched is not None and sched <= now:
                test.status = "done"
                test.done_at = now
                c = await _country(test.country_id)
                if c is None:
                    continue
                program = await nuc_repo.get_program(session, test.country_id)
                if program is not None:
                    nuclear_service.apply_test_effects(program, c)
                public_news.append(
                    "🔴 <b>خبر فوری — آزمایش هسته‌ای!!</b>\n\n"
                    f"💥 لرزه‌نگارهای سراسر جهان دقایقی پیش انفجاری با قدرت "
                    f"<b>{test.yield_kt:.0f} کیلوتن</b> را در منطقه‌ی "
                    f"{test.site_name or 'نامشخص'} کشور {c.flag} <b>{c.name_fa}</b> ثبت کردند!\n"
                    f"☢️ {c.name_fa} رسماً به باشگاه قدرت‌های هسته‌ای جهان پیوست.\n"
                    "⚠️ واکنش‌های شدید بین‌المللی در راه است."
                )
                if c.owner_user_id:
                    owner_pings.append((
                        c.owner_user_id,
                        f"💥 <b>آزمایش هسته‌ای با موفقیت انجام شد!</b> قدرت انفجار: {test.yield_kt:.0f} کیلوتن.\n"
                        "☢️ کشور شما اکنون یک قدرت هسته‌ای شناخته‌شده است (+رضایت عمومی، −ثبات).",
                    ))
                log_msgs.append(
                    f"💥 آزمایش هسته‌ای — {c.flag} {c.name_fa}: {test.yield_kt:.0f}kt در {test.site_name}"
                )

        await session.commit()

    # ---------- ارسال پیام‌ها (خارج از session) ----------
    from ..config import get_settings as _get_settings
    from ..services.media import send_photo_news

    _settings = _get_settings()

    for owner_id, text in owner_pings:
        try:
            await bot.send_message(owner_id, text)
        except Exception:  # noqa: BLE001
            pass
    # اخبار بزرگ هسته‌ای با عکس مخصوص (دسته‌ی nuclear) منتشر می‌شوند
    for text in public_news:
        try:
            if _settings.news_military_channel_id:
                await send_photo_news(bot, _settings.news_military_channel_id, "nuclear", text)
            else:
                await _publish(bot, NewsCategory.MILITARY, text)
        except Exception:  # noqa: BLE001
            pass
    for text in diplo_news:
        try:
            if _settings.news_diplomacy_channel_id:
                await send_photo_news(bot, _settings.news_diplomacy_channel_id, "nuclear", text)
            else:
                await _publish(bot, NewsCategory.DIPLOMACY, text)
        except Exception:  # noqa: BLE001
            pass
    for text in log_msgs:
        try:
            await send_log(bot, text)
        except Exception:  # noqa: BLE001
            pass


async def process_bank_loans(bot: Bot | None = None, session_override: AsyncSession | None = None) -> None:
    """بررسی وضعیت بازپرداخت وام‌های بانکی و اخطارها/تنزیل رتبه به بدحساب (v2.2 / v3.0)."""
    from ..constants import LOAN_DEFAULT_PENALTY_RATE
    from ..database.repositories import bank_loans as loans_repo
    from ..database.repositories import countries as countries_repo
    from ..enums import CreditRating, LoanStatus
    from ..utils.numbers import fa_money

    now = _utcnow()
    notifications: list[tuple[int, str]] = []  # (owner_user_id, text)
    log_msgs: list[str] = []

    async def _process(session: AsyncSession) -> None:
        loans = await loans_repo.list_active_loans(session)
        for loan in loans:
            deadline = _aware(loan.deadline)
            if deadline is None:
                continue

            country = await countries_repo.get_country(session, loan.country_id)
            if not country:
                continue

            # ۱. اگر موعد ۷ روزه منقضی شده است -> معوقه و بدحسابی
            if now >= deadline:
                loan.status = LoanStatus.DEFAULTED
                country.credit_rating = CreditRating.DEFAULTER
                penalty = round(loan.remaining_amount * LOAN_DEFAULT_PENALTY_RATE, 2)
                loan.remaining_amount += penalty
                country.public_satisfaction = max(0.0, country.public_satisfaction - 3.0)
                country.stability = max(0.0, country.stability - 3.0)
                country.inflation = min(100.0, country.inflation + 1.5)

                log_msgs.append(
                    f"🚨 <b>معوق‌شدن وام بانکی و اعمال جریمه</b>\n"
                    f"کشور: {country.flag} {country.name_fa}\n"
                    f"مبلغ مانده اولیه: {fa_money(loan.remaining_amount - penalty)}\n"
                    f"جریمه دیرکرد ({int(LOAN_DEFAULT_PENALTY_RATE * 100)}٪): {fa_money(penalty)}\n"
                    f"مجموع بدهی معوقه: {fa_money(loan.remaining_amount)}\n"
                    f"شناسه وام: #{loan.id}\n"
                    f"رتبه اعتباری کشور به <b>بدحساب (مسدود)</b> تنزیل یافت."
                )
                if country.owner_user_id:
                    notifications.append((
                        country.owner_user_id,
                        f"🚨 <b>اخطار بانکی: مهلت ۷ روزه بازپرداخت وام به پایان رسید!</b>\n\n"
                        f"وام شماره #{loan.id} به موقع تسویه نشد.\n"
                        f"⚠️ جریمه دیرکرد ۱۰٪ به مبلغ {fa_money(penalty)} به بدهی شما افزوده شد (مانده جدید: {fa_money(loan.remaining_amount)}).\n"
                        f"رتبه اعتباری شما به <b>بدحساب (مسدود)</b> تنزیل یافت و تا زمان تسویه کامل بدهی، "
                        f"امکان دریافت وام جدید مسدود می‌باشد.\n"
                        f"💡 پس از تسویه این وام معوقه، سقف وام شما ۵۰ میلیون دلار خواهد شد.",
                    ))
                continue

            # ۲. اخطار روز ششم (کمتر از ۲۴ ساعت مانده)
            if not loan.warned_6d and now >= deadline - timedelta(days=1):
                loan.warned_6d = True
                if country.owner_user_id:
                    notifications.append((
                        country.owner_user_id,
                        f"⚠️ <b>هشدار مهم بانکی:</b> تنها کمتر از ۲۴ ساعت تا پایان مهلت بازپرداخت وام "
                        f"شماره #{loan.id} به مبلغ {fa_money(loan.remaining_amount)} باقی مانده است.\n"
                        f"در صورت عدم تسویه، حساب بانکی شما مسدود و بدحساب خواهد شد.",
                    ))
                continue

            # ۳. یادآوری روز پنجم (کمتر از ۴۸ ساعت مانده)
            if not loan.warned_5d and now >= deadline - timedelta(days=2):
                loan.warned_5d = True
                if country.owner_user_id:
                    notifications.append((
                        country.owner_user_id,
                        f"⏳ <b>یادآوری بازپرداخت وام بانکی:</b> حدود ۲ روز تا مهلت نهایی وام "
                        f"شماره #{loan.id} (مانده: {fa_money(loan.remaining_amount)}) باقی است.",
                    ))

        await session.commit()

    if session_override is not None:
        await _process(session_override)
    else:
        async with async_session_factory() as session:
            await _process(session)

    if bot is not None:
        for owner_id, text in notifications:
            try:
                await bot.send_message(owner_id, text)
            except Exception:
                pass

        for log_text in log_msgs:
            try:
                await send_log(bot, log_text)
            except Exception:
                pass


async def process_auctions(bot: Bot) -> None:
    """بررسی مزایده‌های به پایان‌رسیده و تسویه خودکار آن‌ها (v2.2)."""
    from ..database.repositories import auctions as auctions_repo
    from ..handlers.auction import finalize_auction

    now = _utcnow()
    async with async_session_factory() as session:
        active_auctions = await auctions_repo.list_active_auctions(session)
        for auction in active_auctions:
            ends_at = _aware(auction.ends_at)
            if ends_at and now >= ends_at:
                await finalize_auction(session, auction)
        await session.commit()


async def process_timed_suspensions(bot: Bot) -> None:
    """بررسی پایان دوره تعلیق‌های زمان‌دار و اطلاع‌رسانی به بازیکن."""
    from ..database.repositories import users as users_repo

    now = _utcnow()
    async with async_session_factory() as session:
        expired_users = await users_repo.get_expired_suspended_users(session, now)
        for user in expired_users:
            user.is_suspended = False
            user.suspended_until = None
            user.suspension_reason = None
            try:
                await bot.send_message(
                    user.telegram_id,
                    "🟢 <b>پایان دوره تعلیق</b>\n\n"
                    "دوره تعلیق موقت حساب کاربری شما به پایان رسید و دسترسی شما به مدیریت کشور مجدداً فعال شد.\n"
                    "می‌توانید با دستور /start یا منوی بازی فعالیت خود را ادامه دهید.",
                )
            except Exception as exc:
                logger.debug("Failed to send suspension expiry notification to %s: %s", user.telegram_id, exc)

        if expired_users:
            await session.commit()


_last_market_decay_at: datetime | None = None


async def process_market_decay() -> None:
    """بررسی دوره‌ای تعادل بازار جهانی و کمبود ذخایر (آپدیت شماره ۴)."""
    global _last_market_decay_at
    now = _utcnow()
    if _last_market_decay_at is None or (now - _last_market_decay_at).total_seconds() >= 3600:
        _last_market_decay_at = now
        from ..services import market_service

        async with async_session_factory() as session:
            try:
                await market_service.process_periodic_market_decay(session)
                await market_service.process_global_shortage_check(session)
                await session.commit()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Market decay/shortage check failed: %s", exc)


async def broadcast_market_rates(bot: Bot, force: bool = False) -> bool:
    """ارسال گزارش رسمی ۱۲ ساعته تابلوی بورس و نرخ لحظه‌ای بازار جهانی به کانال اقتصاد (آپدیت شماره ۴)."""
    from sqlalchemy import select
    from ..database.models.bot_state import BotState
    from ..enums import RESOURCE_EMOJI, RESOURCE_FA, RESOURCE_UNIT_FA, ResourceType
    from ..services import market_service
    from ..services.news_service import publish_news
    from ..utils.numbers import fa_money, fa_number

    async with async_session_factory() as session:
        res = await session.execute(select(BotState).where(BotState.id == 1))
        bstate = res.scalar_one_or_none()
        if not force and bstate is not None:
            if not getattr(bstate, "market_news_enabled", True):
                logger.info("Market news broadcast skipped: market_news_enabled is False.")
                return False
            if bstate.maintenance or bstate.global_freeze:
                logger.info("Market news broadcast skipped: maintenance or global_freeze is True.")
                return False

        prices = await market_service.get_all_prices(session)

    if not prices:
        return False

    report_lines = [
        "📊 <b>تابلوی رسمی بورس و شاخص قیمت ذخایر جهانی (WTO)</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        "<i>گزارش تحلیلی ۱۲ ساعته نوسانات بازار بین‌المللی:</i>\n",
    ]
    for p in prices:
        try:
            rtype = ResourceType(p.resource)
            emoji = RESOURCE_EMOJI.get(rtype, "📦")
            name = RESOURCE_FA.get(rtype, p.resource)
            unit = RESOURCE_UNIT_FA.get(rtype, "واحد")
        except Exception:
            emoji, name, unit = "📦", p.resource, "واحد"

        trend_icon = "⚪️"
        sign = ""
        if p.trend == "UP" or p.change_pct > 0.05:
            trend_icon = "🟢"
            sign = "+"
        elif p.trend == "DOWN" or p.change_pct < -0.05:
            trend_icon = "🔴"

        change_str = f"{trend_icon} {sign}{fa_number(p.change_pct, 1)}٪"
        price_str = f"{fa_money(p.current_price)} / {unit}"
        reason = p.last_reason_text or "تعادل عرضه و تقاضای بین‌المللی"

        report_lines.append(f"{emoji} <b>{name}:</b> {price_str} ({change_str})")
        report_lines.append(f"   ▫️ <i>علت: {reason}</i>\n")

    report_lines.append("━━━━━━━━━━━━━━━━━━━━")
    report_lines.append("🌐 <i>مرکز مبادلات تجاری سازمان تجارت جهانی — به‌روزرسانی بعدی ۱۲ ساعت دیگر</i>")

    news_text = "\n".join(report_lines).strip()
    await publish_news(bot, NewsCategory.ECONOMY, news_text)
    return True


async def process_un_assembly(bot: Bot) -> None:
    """
    مدیریت پروازهای اجلاس مجمع عمومی به نیویورک و تایمر ۵ دقیقه‌ای نوبت سخنرانی.
    """
    from sqlalchemy import select
    from ..constants import UN_ASSEMBLY_SPEECH_DURATION_MINUTES
    from ..database.models.united_nations import UNAssemblyParticipant, UNAssemblySession, UNSpeechQueue
    from ..database.repositories import countries as countries_repo
    from ..database.repositories import united_nations as un_repo
    from ..keyboards.united_nations import assembly_hall_kb, assembly_ny_lobby_kb
    from ..services.un_speech_service import analyze_and_publish_speech

    now = _utcnow()
    arrivals: list[tuple[int, int, str]] = []  # (owner_user_id, session_id, country_name)
    speech_transitions: list[dict] = []

    async with async_session_factory() as session:
        active_s = await un_repo.get_active_session(session)
        if not active_s:
            return

        # ۱) بررسی پروازهای رسیده به نیویورک
        res = await session.execute(
            select(UNAssemblyParticipant).where(
                UNAssemblyParticipant.session_id == active_s.id,
                UNAssemblyParticipant.status == "in_flight",
            )
        )
        for part in res.scalars().all():
            eta = _aware(part.travel_eta)
            if eta and eta <= now:
                part.status = "in_new_york"
                c = await countries_repo.get_country(session, part.country_id)
                if c and c.owner_user_id:
                    arrivals.append((c.owner_user_id, part.session_id, c.name_fa))

        # ۲) بررسی تایمر ۵ دقیقه‌ای سخنرانی
        if active_s.status == "active" and active_s.current_speaker_country_id:
            speech_end = _aware(active_s.speech_ends_at)
            if speech_end and speech_end <= now:
                curr = await un_repo.get_active_speech(session, active_s.id)
                if curr:
                    await un_repo.set_speaker_done(session, curr.id)
                    old_c = await countries_repo.get_country(session, curr.country_id)
                    pname = old_c.name_fa if old_c else "—"
                    if old_c and old_c.owner_user_id:
                        from ..database.repositories import users as users_repo
                        u = await users_repo.get_user(session, old_c.owner_user_id)
                        if u and u.president_name:
                            pname = u.president_name

                    speech_transitions.append({
                        "type": "ended",
                        "country_fa": old_c.name_fa if old_c else "",
                        "president_name": pname,
                        "transcript": curr.speech_transcript,
                        "is_vip": old_c.is_vip if old_c else False,
                    })

                nxt = await un_repo.get_next_speaker(session, active_s.id)
                if nxt:
                    nxt.status = "speaking"
                    nxt.started_at = now
                    nxt.ends_at = now + timedelta(minutes=UN_ASSEMBLY_SPEECH_DURATION_MINUTES)
                    active_s.current_speaker_country_id = nxt.country_id
                    active_s.speech_ends_at = nxt.ends_at
                    nxt_c = await countries_repo.get_country(session, nxt.country_id)
                    speech_transitions.append({
                        "type": "started",
                        "session_id": active_s.id,
                        "speaker_country_id": nxt.country_id,
                        "speaker_name": nxt_c.name_fa if nxt_c else "",
                        "speaker_flag": nxt_c.flag if nxt_c else "",
                    })
                else:
                    active_s.current_speaker_country_id = None
                    active_s.speech_ends_at = None

        await session.commit()

    # ارسال اعلان‌های فرود پس از کامیت
    for uid, sid, cname in arrivals:
        try:
            await bot.send_message(
                uid,
                f"🛬 <b>فرود در فرودگاه بین‌المللی JFK نیویورک:</b>\n\n"
                f"هیئت رسمی کشور {cname} به سلامت در نیویورک فرود آمد.\n"
                "شما هم‌اکنون در شهر نیویورک حضور دارید. برای ورود به صحن علنی، روی دکمه «🏛 ورود به ساختمان تالار مجمع» کلیک کنید.",
                reply_markup=assembly_ny_lobby_kb(sid),
            )
        except Exception:
            pass

    # پردازش تغییرات سخنرانی و ارسال خبر
    for tr in speech_transitions:
        if tr["type"] == "ended":
            try:
                await analyze_and_publish_speech(
                    bot,
                    country_fa=tr["country_fa"],
                    president_name=tr["president_name"],
                    speech_transcript=tr["transcript"],
                    is_vip=tr["is_vip"],
                )
            except Exception:
                pass
        elif tr["type"] == "started":
            try:
                async with async_session_factory() as s2:
                    hall_parts = await un_repo.list_participants_by_status(s2, tr["session_id"], "inside_hall")
                    txt = (
                        f"🎙 <b>تریبون مجمع عمومی سازمان ملل متحد:</b>\n\n"
                        f"هم‌اکنون نوبت سخنرانی ۵ دقیقه‌ای کشور {tr['speaker_flag']} <b>{tr['speaker_name']}</b> آغاز شد.\n"
                        "ارسال متن و تصویر توسط سخنران برای کلیه حاضران رله خواهد شد."
                    )
                    for p in hall_parts:
                        c = await countries_repo.get_country(s2, p.country_id)
                        if c and c.owner_user_id:
                            is_spk = (c.id == tr["speaker_country_id"])
                            try:
                                await bot.send_message(
                                    c.owner_user_id,
                                    txt,
                                    reply_markup=assembly_hall_kb(tr["session_id"], is_speaker=is_spk),
                                )
                            except Exception:
                                pass
            except Exception:
                pass


async def _tick(bot: Bot) -> None:
    """جاب اصلی که هر دقیقه همه‌ی پردازش‌های زمان‌دار را اجرا می‌کند.

    v1.10.5: هر پردازش در try/except مستقل اجرا می‌شود تا خطای یکی از جاب‌ها
    (مثلاً بازدهی تأسیسات) بقیه‌ی جاب‌ها را در همان تیک متوقف نکند.
    """
    jobs = (
        ("process_facility_yields", lambda: process_facility_yields(bot)),
        ("process_shipments", lambda: process_shipments(bot)),
        ("process_military_factories", lambda: process_military_factories(bot)),
        ("process_military_shipments", lambda: process_military_shipments(bot)),
        ("process_meetings", lambda: process_meetings(bot)),
        ("process_group_meetings", lambda: process_group_meetings(bot)),
        ("process_calls", lambda: process_calls()),
        ("process_investments", lambda: process_investments(bot)),
        ("process_bank_loans", lambda: process_bank_loans(bot)),
        ("process_auctions", lambda: process_auctions(bot)),
        ("process_satellites", lambda: process_satellites(bot)),
        ("process_economic_projects", lambda: process_economic_projects(bot)),
        ("process_nuclear", lambda: process_nuclear(bot)),
        ("process_taxes", lambda: process_taxes(bot)),
        ("process_protests", lambda: process_protests(bot)),
        ("process_timed_suspensions", lambda: process_timed_suspensions(bot)),
        ("process_market_decay", lambda: process_market_decay()),
        ("process_un_assembly", lambda: process_un_assembly(bot)),
    )
    for name, run in jobs:
        try:
            await run()
        except Exception as exc:  # noqa: BLE001 — خطای یک جاب نباید بقیه را متوقف کند
            logger.exception("Scheduler job '%s' failed: %s", name, exc)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """زمان‌بند را پیکربندی و اجرا می‌کند (تیک هر ۶۰ ثانیه + ارسال ۱۲ ساعته اخبار بازار)."""
    scheduler.add_job(
        _tick,
        trigger="interval",
        seconds=60,
        args=[bot],
        id="main_tick",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        broadcast_market_rates,
        trigger="interval",
        hours=12,
        args=[bot],
        id="market_rates_broadcast",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info("Scheduler started.")
    return scheduler
