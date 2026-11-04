"""
تست جامع سیستم گزارش تراز جهانی و داشبورد آماری ادمین (Global Economic Ledger).

اجرا:
    PYTHONUTF8=1 python -m scripts.test_global_report

نیازی به دیتابیس خارجی یا تلگرام واقعی ندارد (روی SQLite درون‌حافظه‌ای اجرا می‌شود).
"""

from __future__ import annotations

import asyncio
import io
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot.database.base import Base
from bot.database.models import (
    Country,
    Deployment,
    Facility,
    GlobalReport,
    MarketPrice,
    MilitaryFactory,
    NuclearFacility,
    Reserve,
    ResourceSale,
    Satellite,
)
from bot.database.repositories import global_reports as global_reports_repo
from bot.enums import (
    FacilityType,
    MilitaryFactoryType,
    NuclearFacilityType,
    ResourceType,
    TradeStatus,
    TransportMode,
)
from bot.keyboards.admin_report import global_report_back_kb, global_report_dashboard_kb
from bot.services.global_report_service import (
    generate_csv_reports,
    generate_global_report,
    render_full_report,
    render_market_trades_report,
    render_short_report,
    render_top_holders_report,
)

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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def main() -> int:
    print("\n🧪 تست سیستم گزارش تراز جهانی و داشبورد آماری ادمین\n")

    # ۱. ایجاد دیتابیس درون‌حافظه‌ای
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print("— ۱. لایه پایگاه‌داده و ریپازیتوری GlobalReport")
    async with session_factory() as session:
        # افزودن گزارش آزمایشی
        now = _utcnow()
        rep1 = GlobalReport(
            period_hours=72,
            period_start=now - timedelta(hours=72),
            period_end=now,
            generated_at=now,
            payload_json='{"stocks": {"iron": 1000.0}}',
            short_text="گزارش آزمایشی",
        )
        saved = await global_reports_repo.add_report(session, rep1)
        await session.commit()

        check("ثبت موفق گزارش در جدول global_reports", saved.id is not None)

        fetched = await global_reports_repo.get_report_by_id(session, saved.id)
        check("واکشی گزارش با get_report_by_id", fetched is not None and fetched.period_hours == 72)

        last_rep = await global_reports_repo.get_last_report(session, period_hours=72)
        check("واکشی آخرین گزارش با get_last_report", last_rep is not None and last_rep.id == saved.id)

        near_rep = await global_reports_repo.get_report_near(session, target_time=now, period_hours=72)
        check("واکشی نزدیک‌ترین گزارش با get_report_near", near_rep is not None and near_rep.id == saved.id)

        rep_list = await global_reports_repo.list_recent_reports(session, limit=5)
        check("فهرست‌گیری گزارش‌ها با list_recent_reports", len(rep_list) == 1)

    print("\n— ۲. ایجاد داده‌های آزمایشی کلان سرور (کشورها، تأسیسات، کارخانه‌ها و رویدادها)")
    async with session_factory() as session:
        # ساخت ۳ کشور
        c1 = Country(
            name_en="Iran",
            name_fa="ایران",
            flag="🇮🇷",
            region="middle_east",
            is_vip=True,
            population=85_000_000,
            budget=150_000_000.0,
            govt_debt=20_000_000.0,
            credit_rating="good",
            public_satisfaction=75.0,
            stability=80.0,
        )
        c2 = Country(
            name_en="China",
            name_fa="چین",
            flag="🇨🇳",
            region="east_asia",
            is_vip=True,
            population=1_400_000_000,
            budget=500_000_000.0,
            govt_debt=100_000_000.0,
            credit_rating="normal",
            public_satisfaction=65.0,
            stability=70.0,
        )
        c3 = Country(
            name_en="Germany",
            name_fa="آلمان",
            flag="🇩🇪",
            region="europe",
            is_vip=False,
            population=83_000_000,
            budget=300_000_000.0,
            govt_debt=50_000_000.0,
            credit_rating="normal",
            public_satisfaction=60.0,
            stability=65.0,
        )
        session.add_all([c1, c2, c3])
        await session.flush()

        # ذخایر ۸ منبع
        for rtype in ResourceType:
            session.add(Reserve(country_id=c1.id, resource=rtype.value, amount=100_000.0))
            session.add(Reserve(country_id=c2.id, resource=rtype.value, amount=200_000.0))
            session.add(Reserve(country_id=c3.id, resource=rtype.value, amount=50_000.0))

        # تأسیسات:
        # الف) معدن آهن فعال ایران (تولید ۲۴ ساعته: ۶۰,۰۰۰ تن -> در ۸ ساعت: ۲۰,۰۰۰ تن)
        session.add(
            Facility(
                country_id=c1.id,
                type=FacilityType.MINE.value,
                resource="iron",
                yield_amount=60_000.0,
                yield_interval_h=24,
                active=True,
            )
        )
        # ب) کارخانه فولاد فعال چین (تولید ۲۴ ساعته: ۱۲,۰۰۰ فولاد، مصرف: ۴۰,۰۰۰ آهن -> در ۸ ساعت: ۴,۰۰۰ فولاد، ۱۳,۳۳۳.۳ آهن)
        session.add(
            Facility(
                country_id=c2.id,
                type=FacilityType.STEEL_FACTORY.value,
                resource="steel",
                yield_amount=12_000.0,
                yield_interval_h=24,
                intake_amount=40_000.0,
                active=True,
            )
        )
        # ج) سکوی نفتی متوقف (باید صفر حساب شود)
        session.add(
            Facility(
                country_id=c1.id,
                type=FacilityType.OIL_PLATFORM.value,
                resource="oil",
                yield_amount=10.0,
                yield_interval_h=24,
                active=False,
            )
        )

        # کارخانه نظامی فعال: تانک در ایران (مصرف فولاد ۱۸۰,۰۰۰، آهن ۱۲۰,۰۰۰، نفت ۰.۰۸، گاز ۰.۰۶ در ۲۴ ساعت -> تقسیم بر ۳ در ۸ ساعت)
        session.add(
            MilitaryFactory(
                country_id=c1.id,
                factory_type=MilitaryFactoryType.TANK.value,
                asset_name="Karrar Tank",
                category="تانک",
                yield_amount=20,
                yield_interval_h=24,
                active=True,
                created_at=now - timedelta(days=2),
            )
        )

        # مصارف ایونت‌محور در بازه:
        # ۱) پرتاب ماهواره
        session.add(
            Satellite(
                country_id=c1.id,
                satellite_type="spy",
                name="Omid-2",
                status="in_orbit",
                created_at=now - timedelta(hours=2),
            )
        )
        # ۲) استقرار نیرو با هزینه نفت
        session.add(
            Deployment(
                country_id=c2.id,
                branch_key="navy",
                branch_fa="دریایی",
                asset_name="Destroyer Type 055",
                count=2,
                region="Persian Gulf",
                oil_cost=3.5,
                active=True,
                created_at=now - timedelta(hours=3),
            )
        )
        # ۳) تأسیسات هسته‌ای در پنجره
        session.add(
            NuclearFacility(
                country_id=c1.id,
                facility_type=NuclearFacilityType.CENTRIFUGE_PLANT.value,
                name="Natanz Plant",
                status="active",
                created_at=now - timedelta(hours=4),
            )
        )

        # نرخ بازار
        session.add(
            MarketPrice(
                resource="oil",
                base_price=10_000_000.0,
                current_price=12_000_000.0,
                previous_price=10_000_000.0,
                change_pct=20.0,
                trend="UP",
                updated_at=now,
            )
        )

        # یک معامله WTO
        session.add(
            ResourceSale(
                seller_country=c1.id,
                buyer_country=c3.id,
                resource="steel",
                amount=5_000.0,
                price=500_000.0,
                status=TradeStatus.DELIVERED.value,
                transport_mode=TransportMode.SEA.value,
                created_at=now - timedelta(hours=1),
            )
        )

        await session.commit()

    print("\n— ۳. تست هسته محاسباتی تراز جهانی (generate_global_report)")
    async with session_factory() as session:
        report, data = await generate_global_report(session, period_hours=8)
        await session.commit()

        check("تولید موفق شیء GlobalReport و دیکشنری payload", report is not None and isinstance(data, dict))

        # موجودی کل
        stocks = data.get("stocks", {})
        check("موجودی کل آهن برابر با ۳۵۰,۰۰۰ تن", stocks.get("iron") == 350_000.0)
        check("پوشش کامل ۸ منبع در موجودی کل", len(stocks) == 8)

        # سهم ۳ دارنده برتر
        top_iron = data.get("top_holders", {}).get("iron", {})
        check(
            "رتبه اول آهن چین با سهم ۵۷.۱٪",
            top_iron.get("list", [])[0]["name"] == "چین" and round(top_iron["list"][0]["share_pct"], 1) == 57.1,
        )
        check("مجموع سهم ۳ کشور برتر آهن برابر با ۱۰۰٪", top_iron.get("top3_share_pct") == 100.0)

        # تولید ۸ ساعته
        prod = data.get("production", {})
        check("تولید ۲۰,۰۰۰ تن آهن در بازه ۸ ساعته", round(prod.get("iron", 0), 1) == 20_000.0)
        check("تولید ۴,۰۰۰ تن فولاد در بازه ۸ ساعته", round(prod.get("steel", 0), 1) == 4_000.0)
        check("عدم تولید نفت به دلیل غیرفعال بودن سکو", prod.get("oil", 0) == 0.0)

        # مصرف
        cons = data.get("consumption", {})
        iron_cons = cons.get("iron", {})
        check(
            "مصرف صنعتی آهن کارخانه فولاد (حدود ۱۳,۳۳۳ تن)",
            round(iron_cons.get("industrial", 0), 0) == 13_333.0,
        )
        check(
            "مصرف نظامی آهن کارخانه تانک (۴۰,۰۰۰ تن در ۸ ساعت)",
            round(iron_cons.get("military", 0), 0) == 40_000.0,
        )

        # مصارف ایونت‌محور
        oil_cons = cons.get("oil", {})
        check(
            "مصرف نفت ماهواره (۲M) + استقرار نیرو (۳.۵M) = ۵.۵M بشکه",
            round(oil_cons.get("events", 0), 1) == 5.5,
        )

        # خالص جریان و پرچم ریسک
        net = data.get("net_flow", {})
        risk = data.get("risk_flags", {})
        check("محاسبه درست خالص جریان آهن (تولید - مصرف)", round(net.get("iron", 0), 0) == -33333.0)
        check("پرچم ریسک آهن با کسری بالای ۵۰٪ (CRITICAL_DEFICIT)", risk.get("iron", {}).get("code") == "CRITICAL_DEFICIT")

        # شاخص‌های کلان
        macro = data.get("macro", {})
        check("نقدینگی کل سرور برابر با ۹۵۰ میلیون دلار", macro.get("total_budget") == 950_000_000.0)
        check("بدهی کل دولت‌ها برابر با ۱۷۰ میلیون دلار", macro.get("total_debt") == 170_000_000.0)
        check("میانگین رضایت عمومی برابر با ۶۶.۷٪", macro.get("mean_sat") == 66.7)
        check("میانه رضایت عمومی برابر با ۶۵.۰٪", macro.get("median_sat") == 65.0)

        # بازار و WTO
        market = data.get("market", {})
        check("ثبت نرخ لحظه‌ای نفت ۱۲ میلیون دلار با ضریب ۱.۲x", market.get("oil", {}).get("current") == 12_000_000.0)
        trades = data.get("trades", [])
        check("واکشی معامله فولاد ایران به آلمان در فهرست معاملات WTO", len(trades) == 1 and trades[0]["resource"] == "steel")

        # حسابرسی اسنپشات اول
        audit = data.get("audit", {})
        check("شناسایی اسنپشات اول به عنوان پایه (is_baseline = True)", audit.get("is_baseline") is True)

    print("\n— ۴. تست حسابرسی انحراف داده (Audit Delta Check) در اجرای دوم")
    async with session_factory() as session:
        # تغییر دستی در دیتابیس (مثلاً گادمود ۱۰۰۰ تن طلا اضافه کرده)
        gold_res = await session.execute(select(Reserve).where(Reserve.resource == "gold"))
        first_gold = gold_res.scalars().first()
        if first_gold:
            first_gold.amount += 1000.0
            await session.commit()

        # اجرای مجدد گزارش تراز جهانی
        report2, data2 = await generate_global_report(session, period_hours=8)
        await session.commit()

        audit2 = data2.get("audit", {})
        check("شناسایی اسنپشات دوم به عنوان مقایسه‌ای (is_baseline = False)", audit2.get("is_baseline") is False)
        check("کشف موفق انحراف داده (has_drift = True)", audit2.get("has_drift") is True)

        gold_delta = audit2.get("delta_details", {}).get("gold", {})
        check("محاسبه دقیق انحراف ۱۰۰۰ کیلوگرم در طلا", gold_delta.get("delta") == 1000.0)

    print("\n— ۵. تست قالب‌های خروجی متنی (Short, Full, Top Holders, Market)")
    short_txt = render_short_report(data)
    check("رندر قالب کوتاه بدون خطا و غیرخالی", bool(short_txt) and "گزارش تراز کلان جهانی" in short_txt)
    check("عدم عبور قالب کوتاه از سقف تلگرام (<3000 کاراکتر)", len(short_txt) < 3000)

    full_parts = render_full_report(data)
    check("رندر قالب کامل به صورت بخش‌بندی‌شده", len(full_parts) in (1, 2))
    check("کنترل سقف کاراکتر هر بخش از گزارش کامل (<3900 کاراکتر)", all(len(p) < 3900 for p in full_parts))

    top_txt = render_top_holders_report(data)
    check("رندر گزارش تمرکز ذخایر ۳ دارنده برتر", "تمرکز ذخایر ۳ دارنده برتر" in top_txt and "چین" in top_txt)

    mkt_txt = render_market_trades_report(data)
    check("رندر گزارش بازار و معاملات اخیر", "وضعیت بازار جهانی" in mkt_txt and "معامله اخیر" in mkt_txt)

    print("\n— ۶. تست تولید فایل‌های سه‌گانه CSV در حافظه رم با UTF-8-SIG")
    csv_dict = generate_csv_reports(data)
    check("تولید دقیق ۳ فایل CSV در رم", len(csv_dict) == 3)

    for fname in ("global_resources_ledger.csv", "country_stocks.csv", "wto_trades.csv"):
        fbytes = csv_dict.get(fname, b"")
        check(f"وجود فایل {fname} با بایتهای معتبر", len(fbytes) > 0)
        check(f"وجود UTF-8 BOM در ابتدای فایل {fname}", fbytes.startswith(b"\xef\xbb\xbf"))

    print("\n— ۷. تست کیبورد شیشه‌ای ۵ ردیفه و ناوبری ادمین")
    dash_kb = global_report_dashboard_kb(current_hours=8)
    check("ساختار ۵ ردیفه کیبورد داشبورد", len(dash_kb.inline_keyboard) == 5)
    check("ردیف ۱ شامل ۳ دکمه خلاصه ۸، ۲۴ و ۷۲ ساعته", len(dash_kb.inline_keyboard[0]) == 3)
    check("ردیف ۲ شامل ۳ دکمه گزارش کامل ۸، ۲۴ و ۷۲ ساعته", len(dash_kb.inline_keyboard[1]) == 3)
    check("ردیف ۳ شامل تمرکز منابع و بازار", len(dash_kb.inline_keyboard[2]) == 2)
    check("ردیف ۴ شامل دریافت CSV ۸ و ۲۴ ساعته", len(dash_kb.inline_keyboard[3]) == 2)
    check("ردیف ۵ دکمه بازگشت به god:home", dash_kb.inline_keyboard[4][0].callback_data == "god:home")

    back_kb = global_report_back_kb(hours=8)
    check("کیبورد بازگشت زیرصفحات شامل دو دکمه بازگشت به داشبورد و پنل مدیریت", len(back_kb.inline_keyboard[0]) == 2)

    await engine.dispose()

    print("\n" + "=" * 60)
    if _failed:
        print(f"❌ {_failed}")
        print(f"نتیجه: {_passed} موفق، {len(_failed)} ناموفق.")
        return 1
    print(f"✅ همه‌ی {_passed} بررسی با موفقیت کامل پاس شدند.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
