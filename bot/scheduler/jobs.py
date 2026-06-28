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
    from ..database.repositories import countries as countries_repo
    from ..enums import RESOURCE_FA, RESOURCE_UNIT_FA
    from ..utils.numbers import fa_number

    # v1.6: هنگام رسیدن محموله دیگر در کانال WTO خبری نمی‌رود؛ فقط پیوی خریدار و گروه لاگ
    from ..services.news_service import send_log

    log_notices: list[str] = []
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
            log_notices.append(
                "📦 <b>محموله تحویل شد</b>\n"
                f"فروشنده: {seller_name}\n"
                f"خریدار: {buyer_name}\n"
                f"منبع: {fa_number(sale.amount)} {unit} {rname}"
            )
            if buyer and buyer.owner_user_id:
                buyer_notices.append((
                    buyer.owner_user_id,
                    f"📦 محموله‌ی شما رسید: {fa_number(sale.amount)} {unit} {rname} "
                    f"به ذخایر کشورتان اضافه شد.",
                ))
        await session.commit()

    # اطلاع به خریدار (پیوی) و گروه لاگ پس از commit (نه کانال WTO)
    for owner_id, text in buyer_notices:
        try:
            await bot.send_message(owner_id, text)
        except Exception:  # noqa: BLE001 — خطای ارسال نباید scheduler را متوقف کند
            pass
    for text in log_notices:
        await send_log(bot, text)


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
    """رسیدن مسافر (اعلام شروع نشست) و پایان دیدارهای دوجانبه را مدیریت می‌کند."""
    from sqlalchemy import select

    from ..config import get_settings
    from ..constants import MEETING_DURATION_MINUTES
    from ..database.models import Meeting
    from ..database.repositories import countries as countries_repo
    from ..database.repositories import users as users_repo
    from ..services.media import send_photo_news

    settings = get_settings()
    # خبرهای شروع نشست (کپشن) برای ارسال پس از commit
    start_captions: list[str] = []
    # (owner_ids) دیدارهایی که تازه شروع شده‌اند تا دکمه‌ی «پایان نشست» برایشان برود
    started_owner_ids: list[int] = []

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
            # پایان جلسه
            if m.status == DiplomacyStatus.ACTIVE and meeting_ends and meeting_ends <= now:
                m.status = DiplomacyStatus.COMPLETED
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
                    "🤝 نشست آغاز شد. برای پایان دادن به نشست از دکمه‌ی زیر استفاده کنید.",
                    reply_markup=end_meeting_kb(),
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
    from ..constants import MEETING_DURATION_MINUTES
    from ..database.models import GroupMeeting, GroupMeetingParticipant
    from ..database.repositories import countries as countries_repo
    from ..services.media import send_photo_news

    settings = get_settings()
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
                f"🤝 | نشست دیپلماتیک چندجانبه «{meeting.title}» به میزبانی "
                f"{host.flag + ' ' + host.name_fa if host else '?'} با حضور کشورهای "
                f"{names} دقایقی پیش آغاز شد. پیش بینی میشود این کشورها در رابطه با "
                "مسائل دیپلماتیک با یکدیگر بحث و گفتگو داشته باشند.\n\n"
                f"⏳ | مدت زمان گفتگو {fa_number(MEETING_DURATION_MINUTES)} دقیقه پیش بینی شده. "
                "اطلاعات بیشتر در رابطه با این نشست بزودی اعلام خواهد شد."
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
    from ..keyboards.diplomacy import end_meeting_kb

    for owner_ids, notice, news in started_notices:
        for oid in owner_ids:
            try:
                await bot.send_message(oid, notice, reply_markup=end_meeting_kb())
            except Exception:  # noqa: BLE001
                pass
        if settings.news_diplomacy_channel_id is not None:
            await send_photo_news(bot, settings.news_diplomacy_channel_id, "meeting", news)


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


async def _tick(bot: Bot) -> None:
    """جاب اصلی که هر دقیقه همه‌ی پردازش‌های زمان‌دار را اجرا می‌کند."""
    try:
        await process_facility_yields(bot)
        await process_shipments(bot)
        await process_military_factories(bot)
        await process_military_shipments(bot)
        await process_attacks(bot)
        await process_meetings(bot)
        await process_group_meetings(bot)
        await process_calls()
        await process_investments(bot)
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
