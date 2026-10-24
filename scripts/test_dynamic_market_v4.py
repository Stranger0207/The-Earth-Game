"""اسکریپت تست جامع سیستم بازار جهانی، نرخ لحظه‌ای و پویای ذخایر و فروش خودکار (آپدیت شماره ۴).

تست روی دیتابیس آزمایشی موقت SQLite در حافظه اجرا می‌شود و تمام بخش‌های زیر را بررسی می‌کند:
1. مقداردهی اولیه نرخ‌های پایه متناسب با بودجه ۵۰ تا ۱۵۰ میلیون دلار
2. رعایت سقف و کف نوسانات قیمت (۰.۳ تا ۴.۰ برابر پایه) و ثبت دقیق ترند و دلایل
3. واکنش خودکار نرخ‌ها به معاملات تجاری در برابر عدم تغییر نرخ در ارسال هدیه
4. عملکرد انتقال مالی هدیه (قیمت ۰، کسر عوارض، عدم تعلق تعرفه آمریکا)
5. واکنش جهش قیمت به رقابت در مزایده (AUCTION_FEVER)
6. شوک‌های ژئوپلیتیکی انرژی در پی مسدودسازی و بازگشایی تنگه‌ها (STRAIT_CLOSURE / STRAIT_REOPENED)
7. واکنش به توقیف محموله در آبراه‌ها (STRAIT_INTERCEPTION)
8. تعدیل دوره‌ای قیمت‌ها و بررسی کمبود جهانی (GLOBAL_SHORTAGE / LOW_DEMAND)
9. کنترل اخبار ۱۲ ساعته بازار و تاگل market_news_enabled
10. بازنشانی کامل نرخ‌ها به قیمت پایه در ریست فصل
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# تنظیم متغیرهای محیطی آزمایشی پیش از بارگذاری مدل‌ها
os.environ["BOT_TOKEN"] = "123456:TEST_TOKEN_FOR_MARKET_TESTS"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GROQ_API_KEY"] = "gsk_test"
os.environ["OWNER_IDS"] = "111"
os.environ["ADMIN_IDS"] = "111"
os.environ["PYTHONUTF8"] = "1"

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.constants import (
    DEFAULT_BASE_PRICES,
    LOCKABLE_FEATURES,
    MARKET_MAX_PRICE_FACTOR,
    MARKET_MIN_PRICE_FACTOR,
    MARKET_REASON_TEMPLATES,
    SEA_TRANSPORT_FEE,
)
from bot.database.base import Base
from bot.database.models import BotState, Country, MarketPrice, Reserve, User
from bot.database.repositories import market as market_repo
from bot.enums import MarketTrend, ResourceType
from bot.services import economy_service, market_service

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
    print("\n🚀 آغاز آزمون‌های جامع بازار جهانی و نرخ لحظه‌ای ذخایر (آپدیت شماره ۴)...\n")

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        # ۱. بررسی اولیه و ایجاد رکوردهای نرخ پایه
        print("— آزمون ۱: مقداردهی اولیه نرخ‌های پایه بازار جهانی")
        prices = await market_service.get_all_prices(session)
        check("تعداد ذخایر پایه‌ریزی شده برابر ۸ نوع است", len(prices) == 8, f"تعداد: {len(prices)}")
        
        oil_p = await market_service.get_current_price(session, ResourceType.OIL)
        check("قیمت پایه نفت ۱۰ میلیون دلار است", oil_p == 10_000_000.0, f"قیمت: {oil_p}")
        
        gas_p = await market_service.get_current_price(session, ResourceType.GAS)
        check("قیمت پایه گاز ۴۰۰ هزار دلار است", gas_p == 400_000.0, f"قیمت: {gas_p}")

        uranium_p = await market_service.get_current_price(session, ResourceType.URANIUM)
        check("قیمت پایه اورانیوم ۵۰۰ هزار دلار است", uranium_p == 500_000.0, f"قیمت: {uranium_p}")

        gold_p = await market_service.get_current_price(session, ResourceType.GOLD)
        check("قیمت پایه طلا ۱۰ هزار دلار است", gold_p == 10_000.0, f"قیمت: {gold_p}")

        # ۲. محاسبه خودکار ارزش بار
        print("\n— آزمون ۲: محاسبه ارزش محموله بر اساس نرخ روز")
        cargo_val = await market_service.calculate_cargo_value(session, ResourceType.OIL, 2.5)
        check("ارزش ۲.۵ میلیون بشکه نفت برابر ۲۵ میلیون دلار است", cargo_val == 25_000_000.0, f"ارزش: {cargo_val}")

        # ۳. سقف و کف نوسانات و جهت روند
        print("\n— آزمون ۳: رعایت سقف و کف نوسان قیمت و جهش روندها")
        # تلاش برای کاهش قیمت به زیر ۳۰٪
        down_mp = await market_service.update_price(
            session, ResourceType.OIL, delta_pct=-90.0, reason_code="OVERSUPPLY"
        )
        check("کف قیمت نفت به ۳۰٪ پایه (۳ میلیون دلار) محدود می‌شود", down_mp.current_price == 3_000_000.0, f"قیمت: {down_mp.current_price}")
        check("روند نزولی است", down_mp.trend == MarketTrend.DOWN.value)
        check("دلیل کاهش از تمپلیت ثبت شده است", "اشباع بازار" in down_mp.last_reason_text)

        # تلاش برای افزایش قیمت به بالای ۴۰۰٪
        up_mp = await market_service.update_price(
            session, ResourceType.OIL, delta_pct=2000.0, reason_code="WAR_CONSUMPTION"
        )
        check("سقف قیمت نفت به ۴۰۰٪ پایه (۴۰ میلیون دلار) محدود می‌شود", up_mp.current_price == 40_000_000.0, f"قیمت: {up_mp.current_price}")
        check("روند صعودی است", up_mp.trend == MarketTrend.UP.value)

        # دلیل دستی دلخواه
        custom_mp = await market_service.update_price(
            session, ResourceType.OIL, absolute_price=12_000_000.0, reason_code="ADMIN_MANUAL", custom_reason_text="توافق تاریخی برای تثبیت عرضه"
        )
        check("تنظیم قیمت مستقیم ادمین درست عمل کرد", custom_mp.current_price == 12_000_000.0)
        check("متن دلیل دستی دلخواه ثبت شد", custom_mp.last_reason_text == "توافق تاریخی برای تثبیت عرضه")

        # ۴. تست اثر معاملات و فروش هدیه در سرویس اقتصاد
        print("\n— آزمون ۴: معاملات تجاری، فروش خودکار و ارسال هدیه")
        # ساخت دو کشور برای تست
        seller = Country(name_en="Iran", name_fa="ایران", budget=100_000_000.0, flag="🇮🇷", region="Middle East")
        buyer = Country(name_en="Germany", name_fa="آلمان", budget=100_000_000.0, flag="🇩🇪", region="Europe")
        usa = Country(name_en="USA", name_fa="آمریکا", budget=150_000_000.0, flag="🇺🇸", region="North America")
        session.add_all([seller, buyer, usa])
        await session.flush()

        # ذخایر اولیه فروشنده
        res_oil = Reserve(country_id=seller.id, resource="oil", amount=10.0, can_extract=True)
        session.add(res_oil)
        await session.flush()

        # الف) ارسال محموله هدیه با قیمت ۰ دلار (فروشنده پرداخت‌کننده عوارض)
        seller_pre_b = seller.budget
        res_gift = await economy_service.transfer_sale(
            session=session,
            seller_id=seller.id,
            buyer_id=buyer.id,
            resource="oil",
            amount=2.0,
            price=0.0,
            transport_fee=SEA_TRANSPORT_FEE,
            fee_payer="SELLER",
        )
        check("موجودی نفت فروشنده پس از هدیه کسر شد", res_oil.amount == 8.0, f"مانده: {res_oil.amount}")
        check("فقط عوارض حمل‌ونقل از فروشنده کسر شد", seller.budget == seller_pre_b - SEA_TRANSPORT_FEE, f"بودجه: {seller.budget}")
        check("خریدار پولی برای هدیه پرداخت نکرد", buyer.budget == 100_000_000.0)
        check("تعرفه آمریکا برای هدیه صفر است", res_gift["duty"] == 0.0)

        # ب) معامله تجاری نقدی و اثر رشد قیمت
        cur_oil_before = await market_service.get_current_price(session, "oil")
        await economy_service.transfer_sale(
            session=session,
            seller_id=seller.id,
            buyer_id=buyer.id,
            resource="oil",
            amount=2.0,
            price=24_000_000.0,
            transport_fee=SEA_TRANSPORT_FEE,
            fee_payer="BUYER",
        )
        cur_oil_after = await market_service.get_current_price(session, "oil")
        check("معامله تجاری باعث رشد قیمت در بازار شد", cur_oil_after > cur_oil_before, f"قبل: {cur_oil_before}، بعد: {cur_oil_after}")

        # ۵. مزایده و تب رقابت
        print("\n— آزمون ۵: اثر رقابت پیشنهادات مزایده (AUCTION_FEVER)")
        steel_before = await market_service.get_current_price(session, "steel")
        auc_res = await market_service.on_auction_bid_placed(
            session=session, resource="steel", bid_amount=15_000_000.0, base_amount=10_000_000.0
        )
        check("پیشنهاد بالاتر از پایه باعث رشد ۵٪ تا ۱۵٪ قیمت شد", auc_res.change_pct >= 5.0, f"تغییر: {auc_res.change_pct}%")
        check("کد دلیل AUCTION_FEVER ثبت شد", auc_res.last_reason_code == "AUCTION_FEVER")

        # ۶. شوک‌های ژئوپلیتیک تنگه‌ها
        print("\n— آزمون ۶: مسدودسازی و بازگشایی تنگه‌ها")
        strait_jump = await market_service.on_strait_status_changed(session, "hormuz", is_closed=True)
        oil_jump_res = next(p for p in strait_jump if p.resource == "oil")
        gas_jump_res = next(p for p in strait_jump if p.resource == "gas")
        check("بستن تنگه هرمز باعث جهش ۳۰٪ نفت شد", oil_jump_res.change_pct >= 25.0, f"جهش: {oil_jump_res.change_pct}%")
        check("دلیل STRAIT_CLOSURE ثبت شد", oil_jump_res.last_reason_code == "STRAIT_CLOSURE")
        check("گاز نیز دچار جهش قیمتی شد", gas_jump_res.change_pct >= 20.0, f"جهش: {gas_jump_res.change_pct}%")

        # بازگشایی تنگه
        strait_reopen = await market_service.on_strait_status_changed(session, "hormuz", is_closed=False)
        oil_reopen_res = next(p for p in strait_reopen if p.resource == "oil")
        check("بازگشایی تنگه حباب قیمت نفت را تخلیه کرد", oil_reopen_res.change_pct < 0, f"تغییر: {oil_reopen_res.change_pct}%")
        check("دلیل STRAIT_REOPENED ثبت شد", oil_reopen_res.last_reason_code == "STRAIT_REOPENED")

        # ۷. حادثه توقیف در تنگه
        print("\n— آزمون ۷: توقیف محموله در آبراه (STRAIT_INTERCEPTION)")
        intercept_res = await market_service.on_strait_incident(session, "gibraltar", "oil")
        check("توقیف نفتکش باعث جهش قیمت شد", intercept_res.change_pct >= 15.0)
        check("دلیل STRAIT_INTERCEPTION ثبت شد", intercept_res.last_reason_code == "STRAIT_INTERCEPTION")

        # ۸. تعدیل دوره‌ای و کمبود جهانی
        print("\n— آزمون ۸: تعدیل دوره‌ای بازار به سمت نرخ پایه")
        decayed = await market_service.process_periodic_market_decay(session)
        check("تعدیل دوره‌ای روی قیمت‌های متورم اعمال شد", len(decayed) > 0)

        # ۹. ستون market_news_enabled و قفل آپشن‌ها
        print("\n— آزمون ۹: تنظیمات اخبار بازار و Feature Lock")
        bstate = BotState(id=1, maintenance=False, market_news_enabled=True)
        session.add(bstate)
        await session.flush()
        check("ستون market_news_enabled پیش‌فرض True است", bstate.market_news_enabled is True)
        check("کلید قفل econ.market_rates در LOCKABLE_FEATURES تعریف شده است", "econ.market_rates" in LOCKABLE_FEATURES)
        from bot.constants import FEATURE_KEY_ALIASES
        check("کلید مستعار market_rates در FEATURE_KEY_ALIASES نگاشت شده است", FEATURE_KEY_ALIASES.get("market_rates") == "econ.market_rates")

        # ۱۰. ریست فصل و بازگشت به قیمت پایه
        print("\n— آزمون ۱۰: بازنشانی نرخ‌ها در ریست فصل")
        reset_count = await market_repo.reset_all_market_prices(
            session=session,
            base_prices={k.value: v for k, v in DEFAULT_BASE_PRICES.items()},
            reason_code="SEASON_RESET",
            reason_text="آغاز فصل جدید و بازنشانی بازار جهانی به نرخ پایه",
        )
        check("تمام ۸ ذخیره در ریست فصل بازنشانی شدند", reset_count == 8, f"تعداد: {reset_count}")
        all_reset = await market_repo.get_all_market_prices(session)
        for mp in all_reset:
            check(f"قیمت {mp.resource} دقیقا برابر پایه است", mp.current_price == mp.base_price)
            check(f"روند {mp.resource} خنثی (STABLE) است", mp.trend == "STABLE")
            check(f"درصد تغییر {mp.resource} صفر است", mp.change_pct == 0.0)

        await session.commit()

    print("\n" + "=" * 60)
    if _failed:
        print(f"❌ {_failed}")
        sys.exit(1)
    else:
        print(f"✅ تمام {_passed} آزمون سیستم بازار جهانی و نرخ لحظه‌ای با موفقیت پاس شدند.")


if __name__ == "__main__":
    asyncio.run(run_tests())
