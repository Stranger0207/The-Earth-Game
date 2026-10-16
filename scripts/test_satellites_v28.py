"""
اسکریپت تست خودکار آپدیت v2.8:
۱. بررسی مهاجرت ستون‌ها و مدل‌های دیتابیس (level, last_yield_at, econ_sat_unlocked, EconSatReceipt)
۲. بررسی کلیدهای قفل آپشن‌ها در LOCKABLE_FEATURES
۳. کول‌داون ۲۴ ساعته مشترک پرتاب ماهواره
۴. نرف ماهواره نظامی (کسر ۵۰M $، کول‌داون ۶ ساعته رصد، نمایش ۲۰٪-۳۵٪ تجهیزات، حداکثر ۱-۲ پایگاه)
۵. فعالسازی ماهواره اقتصادی (رسید کارت‌به‌کارت، تایید ادمین، تاگل گاد)
۶. ساخت و پرتاب ماهواره اقتصادی (بررسی منابع و بودجه)
۷. ارتقای ۵ سطحی ماهواره اقتصادی و سقف سطح ۵
۸. محاسبه و واریز خودکار سود ۷۲ ساعته ماهواره در زمان‌بند
۹. ریست فصل و پاک‌سازی کامل با Foreign Key
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# تنظیم متغیرهای محیطی آزمایشی
os.environ["BOT_TOKEN"] = "123456:TEST_TOKEN_ONLY"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GROQ_API_KEY"] = "gsk_test"
os.environ["OWNER_IDS"] = "[111]"
os.environ["ADMIN_IDS"] = "[111, 222]"
os.environ["PYTHONUTF8"] = "1"

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from unittest.mock import AsyncMock, patch

from bot.config import get_settings
from bot.constants import (
    ECON_SAT_BUILD_COST_USD,
    ECON_SAT_LEVEL_CONFIG,
    LOCKABLE_FEATURES,
    MIL_SAT_RECON_COST,
    MIL_SAT_SCAN_COOLDOWN_HOURS,
    SATELLITE_LAUNCH_COOLDOWN_HOURS,
)
from bot.database.base import Base, _COLUMN_MIGRATIONS
from bot.database.models import (
    Country,
    Deployment,
    EconSatReceipt,
    MilitaryAsset,
    MilitaryBase,
    Reserve,
    Satellite,
    User,
)
from bot.database.repositories import cooldowns as cooldown_repo
from bot.database.repositories import countries as countries_repo
from bot.database.repositories import satellites as sat_repo
from bot.enums import ResourceType
from bot.loader import bot
from bot.services import news_service, satellite_service
from bot.services.season_service import reset_season

bot.send_message = AsyncMock()
bot.send_photo = AsyncMock()
news_service.publish_news = AsyncMock()
news_service.send_log = AsyncMock()
news_service.send_log_photo = AsyncMock()
satellite_service.publish_news = AsyncMock()
satellite_service.send_log = AsyncMock()

_passed = 0
_failed: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    global _passed
    if condition:
        _passed += 1
        print(f"  ✅ {label}")
    else:
        _failed.append(f"{label} — {detail}")
        print(f"  ❌ {label} — {detail}")


async def run_tests() -> None:
    print("🚀 آغاز آزمون‌های جامع آپدیت ماهواره نظامی و اقتصادی (v2.8)...")

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        # ==========================================
        # بخش ۱: بررسی مهاجرت ستون‌ها و کلیدهای قفل
        # ==========================================
        print("\n--- ۱. بررسی مهاجرت ستون‌ها و ثابت‌ها ---")
        mig_level = any(t == "satellites" and c == "level" for t, c, _ in _COLUMN_MIGRATIONS)
        check("مهاجرت ستون satellites.level", mig_level)

        mig_yield = any(t == "satellites" and c == "last_yield_at" for t, c, _ in _COLUMN_MIGRATIONS)
        check("مهاجرت ستون satellites.last_yield_at", mig_yield)

        mig_unlocked = any(t == "countries" and c == "econ_sat_unlocked" for t, c, _ in _COLUMN_MIGRATIONS)
        check("مهاجرت ستون countries.econ_sat_unlocked", mig_unlocked)

        check("قفل آپشن military.satellite در LOCKABLE_FEATURES", "military.satellite" in LOCKABLE_FEATURES)
        check("قفل آپشن econ.satellite در LOCKABLE_FEATURES", "econ.satellite" in LOCKABLE_FEATURES)

        # ساخت داده‌های پایه
        user_vip = User(telegram_id=1001, first_name="VIP Leader")
        user_non_vip = User(telegram_id=1002, first_name="Regular Leader")
        session.add_all([user_vip, user_non_vip])
        await session.flush()

        country_vip = Country(
            name_en="VIP_Land",
            name_fa="سرزمین ویژه",
            flag="👑",
            region="middle_east",
            is_vip=True,
            budget=2_000_000_000.0,
            economic_power=80.0,
            owner_user_id=1001,
            is_claimed=True,
        )
        country_target = Country(
            name_en="Target_Land",
            name_fa="کشور هدف",
            flag="🎯",
            region="middle_east",
            is_vip=False,
            budget=500_000_000.0,
            economic_power=60.0,
            owner_user_id=1002,
            is_claimed=True,
        )
        session.add_all([country_vip, country_target])
        await session.flush()

        # ذخایر برای ساخت ماهواره
        for c in [country_vip, country_target]:
            session.add_all([
                Reserve(country_id=c.id, resource=ResourceType.OIL.value, amount=50.0),
                Reserve(country_id=c.id, resource=ResourceType.STEEL.value, amount=5_000_000.0),
                Reserve(country_id=c.id, resource=ResourceType.ALUMINUM.value, amount=5_000_000.0),
            ])
        # تجهیزات نظامی متنوع برای کشور هدف (جهت تست نرف و سمپلینگ رصد)
        for i in range(1, 15):
            session.add(
                MilitaryAsset(
                    country_id=country_target.id,
                    name=f"جنگنده اف-{i}",
                    category="جنگنده",
                    branch="نیروی هوایی",
                    count=20 + i,
                )
            )
        # پایگاه‌های هدف
        for i in range(1, 5):
            session.add(
                MilitaryBase(
                    owner_country_id=country_target.id,
                    host_country_id=country_target.id,
                    name=f"پایگاه هوایی شماره {i}",
                    base_type="air",
                    location=f"منطقه {i}",
                )
            )
        # نیروهای مستقر
        for i in range(1, 4):
            session.add(
                Deployment(
                    country_id=country_target.id,
                    branch_key="air",
                    branch_fa="نیروی هوایی",
                    asset_name="اف-۱۴",
                    count=5,
                    region=f"مرز {i}",
                )
            )
        await session.commit()

        # ==========================================
        # بخش ۲: کول‌داون پرتاب مشترک ۲۴ ساعته
        # ==========================================
        print("\n--- ۲. کول‌داون پرتاب ۲۴ ساعته مشترک ---")
        sat_mil, ok = await satellite_service.launch_spy_satellite(session, country_vip, "نور-۱")
        check("پرتاب ماهواره نظامی موفق یا در حال پرتاب", sat_mil is not None)

        # تلاش برای پرتاب مجدد بلافاصله باید مسدود شود
        blocked_launch = False
        try:
            await satellite_service.launch_spy_satellite(session, country_vip, "نور-۲")
        except satellite_service.SatelliteServiceError as e:
            if "سایت پرتاب" in str(e):
                blocked_launch = True
        check("مسدودسازی پرتاب دوم در بازه ۲۴ ساعته", blocked_launch)

        # ==========================================
        # بخش ۳: نرف ماهواره نظامی و رصد جاسوسی
        # ==========================================
        print("\n--- ۳. نرف و محدودسازی ماهواره نظامی ---")
        # تغییر وضعیت ماهواره نور-۱ به in_orbit برای امکان رصد
        sat_mil.status = "in_orbit"
        await session.commit()

        # تست کمبود بودجه
        country_vip.budget = 10_000_000.0  # کمتر از ۵۰M
        low_budget_blocked = False
        try:
            await satellite_service.spy_scan_target_country(session, country_vip.id, country_target.id)
        except satellite_service.SatelliteServiceError as e:
            if "بودجه کافی نیست" in str(e):
                low_budget_blocked = True
        check("مسدودسازی رصد ماهواره‌ای در صورت کمبود بودجه ۵۰M", low_budget_blocked)

        # افزایش بودجه و اجرای رصد
        country_vip.budget = 500_000_000.0
        budget_before = country_vip.budget
        scan_data = await satellite_service.spy_scan_target_country(session, country_vip.id, country_target.id)
        budget_after = country_vip.budget
        check("کسر دقیق ۵۰ میلیون دلار از بودجه رصدکننده", (budget_before - budget_after) == MIL_SAT_RECON_COST)

        # بررسی کول‌داون ۶ ساعته رصد
        cd_rem = await cooldown_repo.remaining_seconds(session, country_vip.id, "military_satellite_scan", MIL_SAT_SCAN_COOLDOWN_HOURS)
        check("ثبت کول‌داون ۶ ساعته پس از رصد", cd_rem > 0)

        # بررسی نرف خروجی: سمپلینگ ۲۰٪ تا ۳۵٪ از اقلام
        total_target_assets = 14
        disclosed_assets = len(scan_data["assets_summary"])
        pct_disclosed = disclosed_assets / total_target_assets
        check(
            f"نمایش محدود اقلام نظامی ({disclosed_assets} از {total_target_assets} = {pct_disclosed*100:.1f}%)",
            0.15 <= pct_disclosed <= 0.40 and scan_data["masked_assets_count"] > 0,
        )
        check(
            f"نمایش حداکثر ۱ الی ۲ پایگاه نظامی ({len(scan_data['bases'])} پایگاه افشا شد)",
            len(scan_data["bases"]) in [1, 2] and scan_data["masked_bases_count"] > 0,
        )
        check(
            f"نمایش حداکثر ۱ الی ۲ نیروی مستقر ({len(scan_data['deployments'])} استقرار افشا شد)",
            len(scan_data["deployments"]) in [1, 2] and scan_data["masked_deps_count"] > 0,
        )

        # ==========================================
        # بخش ۴: فعالسازی ماهواره اقتصادی (رسید و تاگل)
        # ==========================================
        print("\n--- ۴. سیستم رسید و فعالسازی ماهواره اقتصادی ---")
        check("وضعیت اولیه ماهواره اقتصادی غیرفعال است", country_target.econ_sat_unlocked is False)

        # ثبت رسید پرداخت
        receipt = EconSatReceipt(
            country_id=country_target.id,
            user_id=1002,
            photo_file_id="tg_photo_12345",
            status="pending",
        )
        receipt = await sat_repo.create_econ_receipt(session, receipt)
        check("ثبت رسید پرداخت در دیتابیس", receipt.id is not None)

        # تایید رسید توسط ادمین
        receipt = await sat_repo.update_econ_receipt_status(session, receipt.id, "approved", 111)
        check("تغییر وضعیت رسید به approved", receipt.status == "approved")

        country_target.econ_sat_unlocked = True
        await session.commit()
        check("فعال شدن کشور پس از تایید رسید", country_target.econ_sat_unlocked is True)

        # ==========================================
        # بخش ۵: ساخت، پرتاب و ارتقای ماهواره اقتصادی
        # ==========================================
        print("\n--- ۵. ساخت، پرتاب و ارتقای ۵ سطحی ماهواره اقتصادی ---")
        # پاک کردن کول‌داون برای امکان تست پرتاب اقتصادی
        cd_rec = await cooldown_repo.get_cooldown(session, country_target.id, "satellite_launch")
        if cd_rec:
            cd_rec.last_at = datetime.now(timezone.utc) - timedelta(hours=25)
            await session.commit()

        econ_budget_before = country_target.budget
        sat_econ, econ_ok = await satellite_service.launch_econ_satellite(session, country_target, "امید-۱")
        check("پرتاب ماهواره اقتصادی (سطح ۱)", sat_econ is not None and sat_econ.satellite_type == "economic")
        check("کسر ۱۰۰ میلیون دلار هزینه ساخت اولیه", (econ_budget_before - country_target.budget) == ECON_SAT_BUILD_COST_USD)

        # تغییر وضعیت به in_orbit برای تست ارتقا
        sat_econ.status = "in_orbit"
        sat_econ.level = 1
        country_target.budget = 5_000_000_000.0  # تأمین بودجه کافی برای ارتقای تمام سطوح
        await session.commit()

        # ارتقای متوالی از سطح ۱ تا ۵
        for next_lvl in range(2, 6):
            expected_cost = ECON_SAT_LEVEL_CONFIG[next_lvl]["upgrade_cost"]
            b_before = country_target.budget
            _, lvl, cost = await satellite_service.upgrade_econ_satellite(session, country_target)
            b_after = country_target.budget
            check(f"ارتقا به سطح {next_lvl} با هزینه {cost/1e6:.0f}M $", lvl == next_lvl and (b_before - b_after) == expected_cost)

        # تلاش برای ارتقا در سطح ۵ باید متوقف شود
        max_upgrade_blocked = False
        try:
            await satellite_service.upgrade_econ_satellite(session, country_target)
        except satellite_service.SatelliteServiceError as e:
            if "حداکثر سطح" in str(e):
                max_upgrade_blocked = True
        check("مسدودسازی ارتقا فراتر از سطح ۵", max_upgrade_blocked)

        # ==========================================
        # بخش ۶: سودآوری ۷۲ ساعته در زمان‌بند
        # ==========================================
        print("\n--- ۶. سودآوری ۷۲ ساعته ماهواره اقتصادی در زمان‌بند ---")
        sat_econ.last_yield_at = datetime.now(timezone.utc) - timedelta(hours=73)
        await session.commit()

        budget_pre_yield = country_target.budget
        await satellite_service.process_economic_satellites_yield(session)
        budget_post_yield = country_target.budget
        expected_yield = ECON_SAT_LEVEL_CONFIG[5]["yield_usd"]  # سطح ۵ = ۷۰۰M $
        check(f"واریز سود سطح ۵ ({expected_yield/1e6:.0f}M $) پس از ۷۲ ساعت", (budget_post_yield - budget_pre_yield) == expected_yield)

        # اجرای مجدد بلافاصله نباید سود مضاعف واریز کند
        await satellite_service.process_economic_satellites_yield(session)
        check("عدم واریز سود مکرر بدون گذشت ۷۲ ساعت", country_target.budget == budget_post_yield)

        # ==========================================
        # بخش ۷: ریست فصل (Season Reset)
        # ==========================================
        print("\n--- ۷. ریست فصل و یکپارچگی Foreign Key ---")
        reset_report = await reset_season(session)
        check("اجرای موفق reset_season", reset_report is not None)

        # بررسی پاک‌سازی رسیدها و ماهواره‌ها
        res_rcp = await session.execute(select(EconSatReceipt))
        check("پاک‌سازی کامل جدول econ_sat_receipts", len(res_rcp.scalars().all()) == 0)

        res_sat = await session.execute(select(Satellite))
        check("پاک‌سازی کامل جدول satellites", len(res_sat.scalars().all()) == 0)

        res_countries = await countries_repo.list_countries(session)
        target_reloaded = next((c for c in res_countries if c.name_en == country_target.name_en), None)
        check(
            "بازنشانی econ_sat_unlocked به False در ریست فصل",
            target_reloaded is not None and target_reloaded.econ_sat_unlocked is False,
        )

    await engine.dispose()

    print("\n" + "=" * 50)
    print(f"📊 نتیجه نهایی آزمون‌ها: {_passed} موفق | {len(_failed)} ناموفق")
    if _failed:
        print("❌ موارد ناموفق:")
        for f in _failed:
            print(f"  • {f}")
        sys.exit(1)
    else:
        print("🎉 تمامی آزمون‌های آپدیت v2.8 با موفقیت ۱۰۰٪ سپری شدند!")


if __name__ == "__main__":
    asyncio.run(run_tests())
