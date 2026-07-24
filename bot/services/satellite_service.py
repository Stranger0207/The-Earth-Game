"""منطق کسب‌وکار پرتاب و رصد ماهواره‌های جاسوسی."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import (
    SATELLITE_ORBIT_TIME_MINUTES,
    SPY_SATELLITE_ALUMINUM_COST,
    SPY_SATELLITE_COST_USD,
    SPY_SATELLITE_LIFESPAN_DAYS,
    SPY_SATELLITE_OIL_COST,
    SPY_SATELLITE_STEEL_COST,
)
from ..database.models import Country, Satellite
from ..database.repositories import countries as countries_repo
from ..database.repositories import deployments as dep_repo
from ..database.repositories import military as mil_repo
from ..database.repositories import military_bases as base_repo
from ..database.repositories import reserves as reserves_repo
from ..database.repositories import satellites as sat_repo
from ..enums import ResourceType
from ..loader import bot
from ..services.news_service import publish_news, send_log, NewsCategory

settings = get_settings()


class SatelliteServiceError(Exception):
    """خطای سرویس ماهواره."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def calculate_launch_success_rate(
    session: AsyncSession, country: Country
) -> float:
    """
    محاسبه احتمال موفقیت پرتاب ماهواره (بر اساس قدرت اقتصادی و سابقه موفقیت).
    - قدرت اقتصادی بالا -> احتمال بیشتر
    - هر پرتاب موفق قبلی -> +۳٪ تجربه
    - حداکثر ۹۵٪ (هیچ‌گاه ۱۰۰٪ نیست!)
    """
    econ = country.economic_power
    if econ >= 70:
        base_rate = 85.0
    elif econ >= 50:
        base_rate = 65.0
    else:
        base_rate = 45.0

    prev_successes = await sat_repo.count_successful_launches(session, country.id)
    rate = base_rate + (prev_successes * 3.0)
    return min(95.0, max(20.0, rate))


async def launch_spy_satellite(
    session: AsyncSession, country: Country, satellite_name: str
) -> tuple[Satellite, bool]:
    """
    پرتاب ماهواره جاسوسی.
    بررسی بودجه + منابع (نفت، فولاد، آلومینیوم) -> کسر منابع -> تاس شانس موفقیت.

    خروجی: (ماهواره، آیا پرتاب موفقیت‌آمیز وارد فاز پرواز شد؟)
    """
    if not country.is_vip:
        raise SatelliteServiceError("فقط کشورهای VIP به برنامه فضایی ماهواره‌ای دسترسی دارند.")

    # ۱. بررسی بودجه
    if country.budget < SPY_SATELLITE_COST_USD:
        raise SatelliteServiceError(
            f"بودجه کافی نیست. هزینه برنامه پرتاب {SPY_SATELLITE_COST_USD / 1e9:.1f} میلیارد دلار است."
        )

    # ۲. بررسی منابع
    if not await reserves_repo.has_enough(session, country.id, ResourceType.OIL, SPY_SATELLITE_OIL_COST):
        raise SatelliteServiceError(f"کمبود سوخت موشک! نیاز به {SPY_SATELLITE_OIL_COST} میلیون بشکه نفت است.")

    if not await reserves_repo.has_enough(session, country.id, ResourceType.STEEL, SPY_SATELLITE_STEEL_COST):
        raise SatelliteServiceError(f"کمبود فولاد! نیاز به {SPY_SATELLITE_STEEL_COST:,.0f} تن فولاد است.")

    if not await reserves_repo.has_enough(session, country.id, ResourceType.ALUMINUM, SPY_SATELLITE_ALUMINUM_COST):
        raise SatelliteServiceError(f"کمبود آلومینیوم سازه! نیاز به {SPY_SATELLITE_ALUMINUM_COST:,.0f} تن آلومینیوم است.")

    # کسر منابع و بودجه
    country.budget -= SPY_SATELLITE_COST_USD
    await reserves_repo.add_amount(session, country.id, ResourceType.OIL, -SPY_SATELLITE_OIL_COST)
    await reserves_repo.add_amount(session, country.id, ResourceType.STEEL, -SPY_SATELLITE_STEEL_COST)
    await reserves_repo.add_amount(session, country.id, ResourceType.ALUMINUM, -SPY_SATELLITE_ALUMINUM_COST)

    # محاسبه شانس موفقیت
    success_rate = await calculate_launch_success_rate(session, country)
    roll = random.uniform(0.0, 100.0)
    is_success = roll <= success_rate

    now = _utcnow()
    orbit_time = now + timedelta(minutes=SATELLITE_ORBIT_TIME_MINUTES)
    expire_time = orbit_time + timedelta(days=SPY_SATELLITE_LIFESPAN_DAYS)

    status = "launching" if is_success else "failed"

    sat = Satellite(
        country_id=country.id,
        satellite_type="spy",
        name=satellite_name,
        status=status,
        launch_success_pct=success_rate,
        launch_at=now,
        orbit_at=orbit_time if is_success else None,
        expires_at=expire_time if is_success else None,
        cost_usd=SPY_SATELLITE_COST_USD,
    )

    sat = await sat_repo.create_satellite(session, sat)

    # انتشار خبر پرتاب در کانال نظامی
    if is_success:
        news_text = (
            "🔴 **خبر فوری فضایی!!**\n\n"
            f"🚀 سازمان صنایع فضایی کشور {country.flag} {country.name_fa} دقایقی پیش ماهواره جاسوسی "
            f"«**{satellite_name}**» را با موفقیت به فضا پرتاب کرد!\n"
            f"📡 این ماهواره در حال طی مراحل خروج از جو بوده و تا ۳۰ دقیقه دیگر در مدار زمین مستقر خواهد شد."
        )
    else:
        news_text = (
            "🔴 **خبر فوری فضایی!!**\n\n"
            f"💥 پرتاب ماهواره فضایی کشور {country.flag} {country.name_fa} به دلیل نقص فنی در مرحله دوم جداکننده "
            f"موتور با شکست مواجه شد و موشک حامل ماهواره «**{satellite_name}**» متلاشی گردید!"
        )

    await publish_news(bot, NewsCategory.MILITARY, news_text)
    await send_log(
        bot,
        "📡 **گزارش پرتاب ماهواره**\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"نام ماهواره: {satellite_name}\n"
        f"شانس موفقیت: {success_rate:.1f}%\n"
        f"نتیجه: {'موفقیت‌آمیز (در راه مدار)' if is_success else 'شکست پرتاب'}",
    )

    return sat, is_success


async def process_satellite_launches(session: AsyncSession) -> None:
    """بررسی ماهواره‌های در حال پرتاب و تغییر وضعیت به in_orbit پس از اتمام زمان پرواز."""
    pending = await sat_repo.list_pending_launch_satellites(session)
    now = _utcnow()

    for sat in pending:
        if sat.orbit_at and sat.orbit_at <= now:
            sat.status = "in_orbit"
            country = await countries_repo.get_country(session, sat.country_id)
            if country and country.owner_user_id:
                try:
                    await bot.send_message(
                        country.owner_user_id,
                        f"📡 **اطلاعیه فضایی:** ماهواره جاسوسی «**{sat.name}**» با موفقیت در مدار زمین قرار گرفت! "
                        "هم‌اکنون می‌توانید از طریق پنل ماهواره اقدام به رصد پایگاه‌های نظامی سایر کشورها نمایید.",
                    )
                except Exception:
                    pass
    await session.commit()


async def spy_scan_target_country(
    session: AsyncSession, owner_country_id: int, target_country_id: int
) -> dict:
    """
    رصد و اطلاعات جاسوسی ماهواره‌ای از کشور هدف.
    نیازمند حداقل ۱ ماهواره active in_orbit است.
    """
    active_sats = await sat_repo.list_active_orbit_satellites(session, owner_country_id)
    if not active_sats:
        raise SatelliteServiceError("شما هیچ ماهواره جاسوسی فعالی در مدار زمین ندارید.")

    target = await countries_repo.get_country(session, target_country_id)
    if not target:
        raise SatelliteServiceError("کشور هدف یافت نشد.")

    # ۱. لیست پایگاه‌های نظامی و تجهیزات داخل آن‌ها
    bases = await base_repo.list_bases_by_host(session, target.id)
    base_data = []
    for b in bases:
        owner = await countries_repo.get_country(session, b.owner_country_id)
        eqs = [{"name": eq.asset_name, "count": eq.count} for eq in b.equipments]
        base_data.append({
            "name": b.name,
            "type": b.base_type,
            "location": b.location,
            "owner": owner.name_fa if owner else "نامشخص",
            "equipments": eqs,
        })

    # ۲. نیروهای مستقر
    deployments = await dep_repo.list_active(session, target.id)
    dep_data = [
        {
            "branch": d.branch_fa,
            "asset_name": d.asset_name,
            "count": d.count,
            "region": d.region,
        }
        for d in deployments
    ]

    # ۳. خلاصه تجهیزات کلی کشور
    assets = await mil_repo.list_assets(session, target.id)
    asset_data = [{"name": a.name, "count": a.count, "branch": a.branch} for a in assets if a.count > 0]

    return {
        "target_country": f"{target.flag} {target.name_fa}",
        "bases": base_data,
        "deployments": dep_data,
        "assets_summary": asset_data,
    }
