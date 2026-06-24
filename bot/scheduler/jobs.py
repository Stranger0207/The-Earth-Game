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
    AttackStatus,
    DiplomacyStatus,
    FacilityType,
    NewsCategory,
    ResourceType,
    TradeStatus,
)
from ..services.news_service import publish_news

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


async def process_facility_yields() -> None:
    """به ازای هر تأسیسات سررسیدشده، بازدهی را به ذخایر اضافه می‌کند."""
    async with async_session_factory() as session:
        facilities = await fac_repo.all_active_facilities(session)
        now = _utcnow()
        for f in facilities:
            if not fac_repo.is_due(f, now):
                continue

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
                    await reserves_repo.add_amount(
                        session, f.country_id, ResourceType.STEEL,
                        STEEL_FACTORY_OUTPUT_PER_24H,
                    )
            elif f.resource:
                # معدن/سکو: منبع مربوطه را اضافه می‌کند
                await reserves_repo.add_amount(
                    session, f.country_id, f.resource, f.yield_amount
                )

            f.last_yield_at = now

        await session.commit()


async def process_shipments(bot: Bot) -> None:
    """محموله‌های WTO که زمان رسیدنشان فرارسیده را تحویل می‌دهد."""
    from ..database.repositories import countries as countries_repo
    from ..enums import RESOURCE_FA, RESOURCE_UNIT_FA
    from ..utils.numbers import fa_number

    # خبرهای تحویل را همراه جزئیات جمع می‌کنیم تا پس از بستن session منتشر شوند
    delivery_news: list[str] = []
    buyer_notices: list[tuple[int, str]] = []  # (owner_user_id, متن)

    async with async_session_factory() as session:
        sales = await trade_repo.list_in_transit(session)
        now = _utcnow()
        for sale in sales:
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
            delivery_news.append(
                f"✅ محموله‌ی تجاری شامل <b>{fa_number(sale.amount)} {unit} {rname}</b> "
                f"از {seller_name} با موفقیت به مقصد {buyer_name} رسید و تحویل داده شد."
            )
            if buyer and buyer.owner_user_id:
                buyer_notices.append((
                    buyer.owner_user_id,
                    f"📦 محموله‌ی شما رسید: {fa_number(sale.amount)} {unit} {rname} "
                    f"به ذخایر کشورتان اضافه شد.",
                ))
        await session.commit()

    # اعلام در کانال WTO و اطلاع به خریدار پس از commit
    for text in delivery_news:
        await publish_news(bot, NewsCategory.WTO, text)
    for owner_id, text in buyer_notices:
        try:
            await bot.send_message(owner_id, text)
        except Exception:  # noqa: BLE001 — خطای ارسال نباید scheduler را متوقف کند
            pass


async def process_attacks(bot: Bot) -> None:
    """
    حملاتی که زمان اعلام نتیجه‌شان رسیده را نهایی می‌کند و نتیجه‌ی دقیق را به
    گروه لاگ مدیران می‌فرستد (v1.5: نه کانال نظامی) تا مالک دستی اعلام کند.
    همچنین به مهاجم و مدافع اطلاع داده می‌شود.
    """
    from sqlalchemy import select

    from ..database.models import Attack
    from ..database.repositories import countries as countries_repo
    from ..services.news_service import send_log

    # (متن لاگ، آی‌دی مالک مهاجم، آی‌دی مالک مدافع)
    to_announce: list[tuple[str, int | None, int | None]] = []

    async with async_session_factory() as session:
        result = await session.execute(
            select(Attack).where(Attack.status == AttackStatus.IN_PROGRESS)
        )
        attacks = list(result.scalars().all())
        now = _utcnow()
        for atk in attacks:
            eta = _aware(atk.resolve_eta)
            if eta is None or eta > now:
                continue
            atk.status = AttackStatus.RESOLVED
            attacker = await countries_repo.get_country(session, atk.attacker_country)
            defender = await countries_repo.get_country(session, atk.defender_country)
            to_announce.append((
                atk.result or "نتیجه‌ی حمله ثبت شد.",
                attacker.owner_user_id if attacker else None,
                defender.owner_user_id if defender else None,
            ))
        await session.commit()

    for report, attacker_owner, defender_owner in to_announce:
        # اعلام دقیق به گروه لاگ مدیران
        await send_log(bot, report)
        # اطلاع به طرفین
        for owner_id in (attacker_owner, defender_owner):
            if owner_id:
                try:
                    await bot.send_message(
                        owner_id,
                        "📋 نتیجه‌ی نهایی حمله آماده شد و به مدیریت بازی اعلام گردید.",
                    )
                except Exception:  # noqa: BLE001
                    pass


async def process_meetings(bot: Bot) -> None:
    """رسیدن مسافر و پایان دیدارهای حضوری را مدیریت می‌کند."""
    from sqlalchemy import select

    from ..database.models import Meeting

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
            # پایان جلسه
            if m.status == DiplomacyStatus.ACTIVE and meeting_ends and meeting_ends <= now:
                m.status = DiplomacyStatus.COMPLETED
        await session.commit()


async def process_group_meetings(bot: Bot) -> None:
    """
    نشست‌های چندجانبه را مدیریت می‌کند (v1.5):
    - وقتی زمان شروع (رسیدن آخرین کشور) فرارسید، نشست را فعال و به همه اعلام می‌کند.
    - نشست‌هایی که زمانشان تمام شده را می‌بندد.
    """
    from sqlalchemy import select

    from ..constants import MEETING_DURATION_MINUTES
    from ..database.models import GroupMeeting, GroupMeetingParticipant
    from ..database.repositories import countries as countries_repo
    from ..services.news_service import publish_news

    started_notices: list[tuple[list[int], str, str]] = []  # (owner_ids, notice, news)

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
                f"👥 نشست چندجانبه‌ای با عنوان «{meeting.title}» به میزبانی "
                f"{host.name_fa if host else '?'} با حضور چند کشور آغاز شد."
            )
            started_notices.append((owner_ids, notice, news))

        # بستن نشست‌های پایان‌یافته
        result = await session.execute(
            select(GroupMeeting).where(GroupMeeting.status == DiplomacyStatus.ACTIVE)
        )
        for meeting in result.scalars().all():
            ends = _aware(meeting.meeting_ends_at)
            if ends and ends <= now:
                meeting.status = DiplomacyStatus.COMPLETED
        await session.commit()

    # ارسال اعلان‌ها پس از commit
    for owner_ids, notice, news in started_notices:
        for oid in owner_ids:
            try:
                await bot.send_message(oid, notice)
            except Exception:  # noqa: BLE001
                pass
        await publish_news(bot, NewsCategory.DIPLOMACY, news)


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


async def _tick(bot: Bot) -> None:
    """جاب اصلی که هر دقیقه همه‌ی پردازش‌های زمان‌دار را اجرا می‌کند."""
    try:
        await process_facility_yields()
        await process_shipments(bot)
        await process_attacks(bot)
        await process_meetings(bot)
        await process_group_meetings(bot)
        await process_calls()
    except Exception as exc:  # noqa: BLE001 — خطای یک تیک نباید زمان‌بند را متوقف کند
        logger.exception("Scheduler tick failed: %s", exc)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """زمان‌بند را پیکربندی و اجرا می‌کند (تیک هر ۶۰ ثانیه)."""
    scheduler.add_job(
        _tick,
        trigger="interval",
        seconds=60,
        args=[bot],
        id="main_tick",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info("Scheduler started.")
    return scheduler
