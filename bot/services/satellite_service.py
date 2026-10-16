"""منطق کسب‌وکار پرتاب، رصد و ارتقای ماهواره‌های فضایی (v2.8)."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import (
    ECON_SAT_ACTIVATION_PRICE_TOMAN,
    ECON_SAT_ALUMINUM_COST,
    ECON_SAT_BUILD_COST_USD,
    ECON_SAT_FAILURE_RATE,
    ECON_SAT_LEVEL_CONFIG,
    ECON_SAT_OIL_COST,
    ECON_SAT_STEEL_COST,
    ECON_SAT_YIELD_INTERVAL_HOURS,
    MIL_SAT_RECON_COST,
    MIL_SAT_SCAN_COOLDOWN_HOURS,
    SATELLITE_LAUNCH_COOLDOWN_HOURS,
    SATELLITE_ORBIT_TIME_MINUTES,
    SPY_SATELLITE_ALUMINUM_COST,
    SPY_SATELLITE_COST_USD,
    SPY_SATELLITE_LIFESPAN_DAYS,
    SPY_SATELLITE_OIL_COST,
    SPY_SATELLITE_STEEL_COST,
)
from ..database.models import Country, Satellite
from ..database.repositories import cooldowns as cooldown_repo
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
    محاسبه احتمال موفقیت پرتاب ماهواره نظامی (بر اساس قدرت اقتصادی و سابقه موفقیت).
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
    پرتاب ماهواره جاسوسی (ویژه VIP).
    بررسی کول‌داون مشترک ۲۴ ساعته + بودجه + منابع -> کسر منابع -> تاس شانس موفقیت.

    خروجی: (ماهواره، آیا پرتاب موفقیت‌آمیز وارد فاز پرواز شد؟)
    """
    if not country.is_vip:
        raise SatelliteServiceError("فقط کشورهای VIP به برنامه فضایی ماهواره‌ای دسترسی دارند.")

    # ۰. بررسی کول‌داون پرتاب مشترک ۲۴ ساعته
    rem_launch = await cooldown_repo.remaining_seconds(
        session, country.id, "satellite_launch", SATELLITE_LAUNCH_COOLDOWN_HOURS
    )
    if rem_launch > 0:
        hrs = int(rem_launch // 3600)
        mins = int((rem_launch % 3600) // 60)
        raise SatelliteServiceError(
            f"سایت پرتاب فضایی در حال بازیابی و آماده‌سازی مجدد است. زمان باقی‌مانده: {hrs} ساعت و {mins} دقیقه."
        )

    # ۱. بررسی بودجه
    if country.budget < SPY_SATELLITE_COST_USD:
        raise SatelliteServiceError(
            f"بودجه کافی نیست. هزینه برنامه پرتاب {SPY_SATELLITE_COST_USD / 1e6:.0f} میلیون دلار است."
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

    # ثبت کول‌داون پرتاب ۲۴ ساعته
    await cooldown_repo.touch(session, country.id, "satellite_launch")

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
        level=1,
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
        "📡 **گزارش پرتاب ماهواره نظامی**\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"نام ماهواره: {satellite_name}\n"
        f"شانس موفقیت: {success_rate:.1f}%\n"
        f"نتیجه: {'موفقیت‌آمیز (در راه مدار)' if is_success else 'شکست پرتاب'}",
    )

    return sat, is_success


async def launch_econ_satellite(
    session: AsyncSession, country: Country, satellite_name: str
) -> tuple[Satellite, bool]:
    """
    پرتاب ماهواره اقتصادی تجاری.
    - نیازمند باز بودن آپشن با کارت‌به‌کارت (country.econ_sat_unlocked).
    - بررسی کول‌داون پرتاب مشترک ۲۴ ساعته.
    - بررسی بودجه ۱۰۰ میلیون دلار + ۳۰۰ هزار تن فولاد + ۵۰۰ هزار تن آلومینیوم + ۱ میلیون بشکه نفت.
    - شانس خطای ۱۸٪.
    """
    if not country.econ_sat_unlocked:
        raise SatelliteServiceError(
            "آپشن ماهواره اقتصادی برای کشور شما فعال نشده است. ابتدا باید هزینه فعالسازی را پرداخت نمایید."
        )

    # ۰. بررسی کول‌داون پرتاب ۲۴ ساعته
    rem_launch = await cooldown_repo.remaining_seconds(
        session, country.id, "satellite_launch", SATELLITE_LAUNCH_COOLDOWN_HOURS
    )
    if rem_launch > 0:
        hrs = int(rem_launch // 3600)
        mins = int((rem_launch % 3600) // 60)
        raise SatelliteServiceError(
            f"سایت پرتاب فضایی در حال بازیابی و آماده‌سازی مجدد است. زمان باقی‌مانده: {hrs} ساعت و {mins} دقیقه."
        )

    # ۱. بررسی بودجه
    if country.budget < ECON_SAT_BUILD_COST_USD:
        raise SatelliteServiceError(
            f"بودجه کافی نیست. هزینه ساخت و پرتاب ماهواره تجاری {ECON_SAT_BUILD_COST_USD / 1e6:.0f} میلیون دلار است."
        )

    # ۲. بررسی منابع
    if not await reserves_repo.has_enough(session, country.id, ResourceType.OIL, ECON_SAT_OIL_COST):
        raise SatelliteServiceError(f"کمبود سوخت موشک! نیاز به {ECON_SAT_OIL_COST} میلیون بشکه نفت است.")

    if not await reserves_repo.has_enough(session, country.id, ResourceType.STEEL, ECON_SAT_STEEL_COST):
        raise SatelliteServiceError(f"کمبود فولاد! نیاز به {ECON_SAT_STEEL_COST:,.0f} تن فولاد است.")

    if not await reserves_repo.has_enough(session, country.id, ResourceType.ALUMINUM, ECON_SAT_ALUMINUM_COST):
        raise SatelliteServiceError(f"کمبود آلومینیوم! نیاز به {ECON_SAT_ALUMINUM_COST:,.0f} تن آلومینیوم است.")

    # کسر منابع و بودجه
    country.budget -= ECON_SAT_BUILD_COST_USD
    await reserves_repo.add_amount(session, country.id, ResourceType.OIL, -ECON_SAT_OIL_COST)
    await reserves_repo.add_amount(session, country.id, ResourceType.STEEL, -ECON_SAT_STEEL_COST)
    await reserves_repo.add_amount(session, country.id, ResourceType.ALUMINUM, -ECON_SAT_ALUMINUM_COST)

    # ثبت کول‌داون پرتاب
    await cooldown_repo.touch(session, country.id, "satellite_launch")

    # تاس شانس خطا ۱۸٪ (شانس موفقیت ۸۲٪)
    success_rate = 100.0 - ECON_SAT_FAILURE_RATE
    roll = random.uniform(0.0, 100.0)
    is_success = roll <= success_rate

    now = _utcnow()
    orbit_time = now + timedelta(minutes=SATELLITE_ORBIT_TIME_MINUTES)
    status = "launching" if is_success else "failed"

    sat = Satellite(
        country_id=country.id,
        satellite_type="economic",
        name=satellite_name,
        status=status,
        level=1,
        launch_success_pct=success_rate,
        launch_at=now,
        orbit_at=orbit_time if is_success else None,
        expires_at=None,
        cost_usd=ECON_SAT_BUILD_COST_USD,
    )
    sat = await sat_repo.create_satellite(session, sat)

    # اخبار و لاگ
    if is_success:
        news_text = (
            "🛰 **خبر اقتصادی-فضایی!!**\n\n"
            f"کشور {country.flag} {country.name_fa} دقایقی پیش ماهواره تجاری و مخابراتی "
            f"«**{satellite_name}**» را با موفقیت به فضا پرتاب کرد!\n"
            f"📡 این ماهواره تا ۳۰ دقیقه دیگر در مدار تجاری مستقر خواهد شد و فروش داده‌های هواشناسی و ناوبری آن آغاز می‌شود."
        )
    else:
        news_text = (
            "🛰 **سانحه فضایی!!**\n\n"
            f"پرتاب ماهواره تجاری کشور {country.flag} {country.name_fa} با نام «**{satellite_name}**» "
            "به دلیل نقص در احتراق موشک حامل شکست خورد و بقایای آن در اقیانوس سقوط کرد!"
        )

    await publish_news(bot, NewsCategory.ECONOMY, news_text)
    await send_log(
        bot,
        "💰 **گزارش پرتاب ماهواره اقتصادی**\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"نام ماهواره: {satellite_name}\n"
        f"نتیجه: {'موفقیت‌آمیز (در راه مدار)' if is_success else 'شکست پرتاب'}",
    )

    return sat, is_success


async def upgrade_econ_satellite(
    session: AsyncSession, country: Country
) -> tuple[Satellite, int, float]:
    """
    ارتقای ماهواره اقتصادی در مدار به سطح بالاتر (تا لول ۵).
    خروجی: (ماهواره، لول جدید، هزینه پرداخت‌شده)
    """
    sat = await sat_repo.get_active_economic_satellite(session, country.id)
    if not sat or sat.status != "in_orbit":
        raise SatelliteServiceError("شما ماهواره اقتصادی فعالی در مدار زمین ندارید.")

    curr_level = getattr(sat, "level", 1) or 1
    if curr_level >= 5:
        raise SatelliteServiceError("ماهواره اقتصادی شما هم‌اکنون در حداکثر سطح ممکن (سطح ۵) قرار دارد.")

    next_level = curr_level + 1
    cfg = ECON_SAT_LEVEL_CONFIG.get(next_level)
    if not cfg:
        raise SatelliteServiceError("سطح ارتقای نامعتبر.")

    cost = cfg["upgrade_cost"]
    if country.budget < cost:
        raise SatelliteServiceError(
            f"بودجه ناکافی است. هزینه ارتقا به سطح {next_level} مبلغ {cost / 1e6:.0f} میلیون دلار است."
        )

    country.budget -= cost
    sat.level = next_level
    await session.flush()

    await send_log(
        bot,
        "⚡️ **ارتقای ماهواره اقتصادی**\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"ماهواره: {sat.name}\n"
        f"سطح جدید: {next_level}\n"
        f"هزینه ارتقا: {cost / 1e6:.0f} میلیون دلار\n"
        f"سود جدید هر ۷۲ ساعت: {cfg['yield_usd'] / 1e6:.0f} میلیون دلار",
    )
    return sat, next_level, cost


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
                    if sat.satellite_type == "economic":
                        msg = (
                            f"📡 **اطلاعیه فضایی:** ماهواره تجاری و اقتصادی «**{sat.name}**» "
                            "با موفقیت در مدار تجاری زمین مستقر شد!\n"
                            "از هم‌اکنون چرخه سودآوری ۷۲ ساعته آغاز شده و قابلیت ارتقا در پنل ماهواره فعال است."
                        )
                    else:
                        msg = (
                            f"📡 **اطلاعیه فضایی:** ماهواره جاسوسی «**{sat.name}**» با موفقیت در مدار زمین قرار گرفت! "
                            "هم‌اکنون می‌توانید از طریق پنل ماهواره اقدام به رصد پایگاه‌های نظامی سایر کشورها نمایید."
                        )
                    await bot.send_message(country.owner_user_id, msg)
                except Exception:
                    pass
    await session.commit()


async def process_economic_satellites_yield(session: AsyncSession, bot_instance=None) -> None:
    """
    پردازش سود ۷۲ ساعته ماهواره‌های اقتصادی فعال در مدار.
    """
    from ..utils.numbers import fa_money

    active_sats = await sat_repo.list_active_economic_satellites_in_orbit(session)
    now = _utcnow()
    target_bot = bot_instance or bot

    for sat in active_sats:
        ref_time = sat.last_yield_at or sat.orbit_at or sat.launch_at
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        # گذشت ۷۲ ساعت
        if (now - ref_time).total_seconds() >= ECON_SAT_YIELD_INTERVAL_HOURS * 3600:
            level = getattr(sat, "level", 1) or 1
            cfg = ECON_SAT_LEVEL_CONFIG.get(level, {"yield_usd": 100_000_000.0})
            yield_usd = cfg["yield_usd"]

            country = await countries_repo.get_country(session, sat.country_id)
            if country:
                country.budget += yield_usd
                sat.last_yield_at = now
                await session.flush()

                # اطلاع به مالک
                if country.owner_user_id and target_bot:
                    try:
                        await target_bot.send_message(
                            country.owner_user_id,
                            f"💰 **گزارش بازدهی ماهواره اقتصادی (سطح {level}):**\n\n"
                            f"🛰 ماهواره «**{sat.name}**» مبلغ **{fa_money(yield_usd)}** "
                            f"سود خالص حاصل از فروش داده‌های تجاری و هواشناسی را به خزانه کشور واریز کرد.\n"
                            f"⏱ واریز بعدی: ۷۲ ساعت دیگر.",
                        )
                    except Exception:
                        pass

                if target_bot:
                    await send_log(
                        target_bot,
                        "💰 **واریز سود ماهواره اقتصادی**\n"
                        f"کشور: {country.flag} {country.name_fa}\n"
                        f"ماهواره: {sat.name} (سطح {level})\n"
                        f"مبلغ سود: {yield_usd / 1e6:.0f} میلیون دلار",
                    )
    await session.commit()


async def spy_scan_target_country(
    session: AsyncSession, owner_country_id: int, target_country_id: int
) -> dict:
    """
    رصد و اطلاعات جاسوسی ماهواره‌ای از کشور هدف (نرف‌شده در v2.8).
    - نیازمند حداقل ۱ ماهواره فعال جاسوسی در مدار است.
    - کسر ۵۰ میلیون دلار هزینه رصد از بودجه.
    - کول‌داون ۶ ساعته رصد جاسوسی.
    - خروجی ناقص و رندوم: تنها ۲۰٪ الی ۳۵٪ از اقلام تجهیزات نظامی (با خطای تخمینی جزئی) نمایش داده می‌شود.
    - حداکثر ۱ تا ۲ پایگاه و نیروی مستقر افشا شده و بقیه با پوشش ابری پنهان می‌مانند.
    - تأسیسات هسته‌ای زیرزمینی همچنان پنهان می‌مانند.
    """
    owner = await countries_repo.get_country(session, owner_country_id)
    if not owner or not owner.is_vip:
        raise SatelliteServiceError("فقط کشورهای VIP به رصد جاسوسی ماهواره‌ای دسترسی دارند.")

    active_sats = await sat_repo.list_active_orbit_satellites(session, owner_country_id)
    if not active_sats:
        raise SatelliteServiceError("شما هیچ ماهواره جاسوسی فعالی در مدار زمین ندارید.")

    # ۱. بررسی بودجه ۵۰ میلیون دلاری
    if owner.budget < MIL_SAT_RECON_COST:
        raise SatelliteServiceError(
            f"بودجه کافی نیست. هزینه هر بار عکسبرداری و رصد اطلاعاتی {MIL_SAT_RECON_COST / 1e6:.0f} میلیون دلار است."
        )

    # ۲. بررسی کول‌داون ۶ ساعته رصد جاسوسی
    rem_scan = await cooldown_repo.remaining_seconds(
        session, owner.id, "military_satellite_scan", MIL_SAT_SCAN_COOLDOWN_HOURS
    )
    if rem_scan > 0:
        hrs = int(rem_scan // 3600)
        mins = int((rem_scan % 3600) // 60)
        raise SatelliteServiceError(
            f"سیستم مخابراتی ماهواره در حال بازیابی زاویه مداری است. زمان تا رصد بعدی: {hrs} ساعت و {mins} دقیقه."
        )

    target = await countries_repo.get_country(session, target_country_id)
    if not target:
        raise SatelliteServiceError("کشور هدف یافت نشد.")

    # کسر هزینه و ثبت کول‌داون
    owner.budget -= MIL_SAT_RECON_COST
    await cooldown_repo.touch(session, owner.id, "military_satellite_scan")

    # ۱. پایگاه‌های نظامی (حداکثر ۱ یا ۲ مورد تصادفی)
    bases = await base_repo.list_bases_by_host(session, target.id)
    base_data = []
    for b in bases:
        b_owner = await countries_repo.get_country(session, b.owner_country_id)
        eqs = [{"name": eq.asset_name, "count": eq.count} for eq in b.equipments]
        base_data.append({
            "name": b.name,
            "type": b.base_type,
            "location": b.location,
            "owner": b_owner.name_fa if b_owner else "نامشخص",
            "equipments": eqs,
        })
    num_bases = min(len(base_data), random.choice([1, 2])) if base_data else 0
    sampled_bases = random.sample(base_data, num_bases) if base_data else []
    masked_bases_count = len(base_data) - len(sampled_bases)

    # ۲. نیروهای مستقر (حداکثر ۱ یا ۲ مورد تصادفی)
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
    num_deps = min(len(dep_data), random.choice([1, 2])) if dep_data else 0
    sampled_deps = random.sample(dep_data, num_deps) if dep_data else []
    masked_deps_count = len(dep_data) - len(sampled_deps)

    # ۳. خلاصه تجهیزات کلی (۲۰٪ الی ۳۵٪ تصادفی با تخمین)
    assets = await mil_repo.list_assets(session, target.id)
    asset_data = [{"name": a.name, "count": a.count, "branch": a.branch} for a in assets if a.count > 0]
    sampled_assets = []
    masked_assets_count = 0
    if asset_data:
        pct = random.uniform(0.20, 0.35)
        k = max(1, int(len(asset_data) * pct))
        raw_sampled = random.sample(asset_data, min(k, len(asset_data)))
        for a in raw_sampled:
            est = max(1, int(a["count"] * random.uniform(0.85, 1.0)))
            sampled_assets.append({
                "name": a["name"],
                "count": est,
                "branch": a["branch"],
            })
        masked_assets_count = len(asset_data) - len(sampled_assets)

    # ۴. تأسیسات هسته‌ای رویِ زمین
    from ..database.repositories import nuclear as nuc_repo
    from ..enums import NUCLEAR_FACILITY_STATUS_FA, NuclearFacilityStatus

    nuclear_data = []
    nuc_facilities = await nuc_repo.list_facilities(session, target.id)
    for f in nuc_facilities:
        if f.is_underground:
            continue
        nuclear_data.append({
            "name": f.name,
            "location": f.location,
            "status": NUCLEAR_FACILITY_STATUS_FA.get(
                NuclearFacilityStatus(f.status), f.status
            ),
        })

    hidden_count = sum(1 for f in nuc_facilities if f.is_underground)

    await send_log(
        bot,
        "🔭 <b>گزارش رصد ماهواره‌ای</b>\n"
        f"رصدکننده: {owner.flag} {owner.name_fa}\n"
        f"کشور هدف: {target.flag} {target.name_fa}\n"
        f"هزینه کسرشده: {MIL_SAT_RECON_COST / 1e6:.0f} میلیون دلار\n"
        f"اقلام کشف‌شده: {len(sampled_assets)} قلم (از مجموع {len(asset_data)})",
    )

    return {
        "target_country": f"{target.flag} {target.name_fa}",
        "bases": sampled_bases,
        "masked_bases_count": masked_bases_count,
        "deployments": sampled_deps,
        "masked_deps_count": masked_deps_count,
        "assets_summary": sampled_assets,
        "masked_assets_count": masked_assets_count,
        "nuclear_facilities": nuclear_data,
        "nuclear_hidden_count": hidden_count,
    }
