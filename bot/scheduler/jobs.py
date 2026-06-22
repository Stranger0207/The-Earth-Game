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
from datetime import datetime, timezone

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
    async with async_session_factory() as session:
        sales = await trade_repo.list_in_transit(session)
        now = _utcnow()
        delivered = []
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
            delivered.append(sale)
        await session.commit()

    # اعلام در کانال WTO پس از commit
    for sale in delivered:
        await publish_news(
            bot,
            NewsCategory.WTO,
            f"✅ یک محموله‌ی تجاری با موفقیت به مقصد رسید و تحویل داده شد.",
        )


async def process_attacks(bot: Bot) -> None:
    """حملاتی که زمان اعلام نتیجه‌شان رسیده را نهایی و در کانال نظامی اعلام می‌کند."""
    from sqlalchemy import select

    from ..database.models import Attack

    async with async_session_factory() as session:
        result = await session.execute(
            select(Attack).where(Attack.status == AttackStatus.IN_PROGRESS)
        )
        attacks = list(result.scalars().all())
        now = _utcnow()
        resolved = []
        for atk in attacks:
            eta = _aware(atk.resolve_eta)
            if eta is None or eta > now:
                continue
            atk.status = AttackStatus.RESOLVED
            resolved.append(atk)
        await session.commit()

    for atk in resolved:
        report = atk.result or "نتیجه‌ی حمله ثبت شد."
        await publish_news(bot, NewsCategory.MILITARY, report)


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
