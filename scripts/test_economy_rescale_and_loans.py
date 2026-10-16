"""
اسکریپت تست جامع:
۱. تنظیم وفور آلومینیوم و فولاد
۲. اصلاح مقیاس ارزش پول در کل بازی (بودجه ۵۰ تا ۱۵۰ میلیون دلار و هزینه‌ها)
۳. عملکرد و چرخه حیات سیستم وام بانکی (سقف ۱۰۰ و ۲۰۰ میلیون، سود ۵٪، خوش‌حسابی و جریمه ۱۰٪)
۴. سلامت کامل reset_season در پایگاه داده SQLite با فعال بودن Foreign Keys

اجرا:
    python -m scripts.test_economy_rescale_and_loans
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# تنظیم پایگاه داده تستی موقت SQLite
TEST_DB_FILE = ROOT / "test_temp_economy.db"
if TEST_DB_FILE.exists():
    try:
        TEST_DB_FILE.unlink()
    except Exception:
        pass

os.environ["BOT_TOKEN"] = "123456:TEST_TOKEN_FOR_TESTING_ONLY"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_FILE.as_posix()}"
os.environ["GROQ_API_KEY"] = "gsk_test"
os.environ["OWNER_IDS"] = "111"
os.environ["ADMIN_IDS"] = "111"
os.environ["PYTHONUTF8"] = "1"

from sqlalchemy import func, select, text  # noqa: E402

from bot.constants import (  # noqa: E402
    AUCTION_ENTRY_FEE,
    AUCTION_MIN_BID_STEP,
    BUILD_LIMIT_GROUPS,
    DEFAULT_BASE_YIELD,
    FACILITY_COST_USD,
    FACILITY_TOTAL_LIMIT_NON_VIP,
    LOAN_COOLDOWN_DAYS,
    LOAN_DEFAULT_PENALTY_RATE,
    LOAN_DURATION_DAYS,
    LOAN_GOOD_CREDIT_DAYS,
    LOAN_INTEREST_RATE,
    LOAN_LIMIT_BAD_CREDIT,
    LOAN_LIMIT_GOOD,
    LOAN_LIMIT_NORMAL,
    LOCKABLE_FEATURES,
    MIL_FACTORY_COST_USD,
    MINE_COST_USD,
    MINE_YIELD_PER_24H,
    NUCLEAR_FACILITIES,
    SPY_SATELLITE_COST_USD,
    STEEL_FACTORY_COST_USD,
    STEEL_FACTORY_IRON_INTAKE_PER_24H,
    STEEL_FACTORY_OUTPUT_PER_24H,
)
from bot.database.base import async_session_factory, engine, init_db  # noqa: E402
from bot.database.models import BankLoan, Country, Reserve, User  # noqa: E402
from bot.database.repositories import bank_loans as loans_repo  # noqa: E402
from bot.database.repositories import countries as countries_repo  # noqa: E402
from bot.enums import CreditRating, FacilityType, LoanStatus, ResourceType  # noqa: E402
from bot.scheduler.jobs import process_bank_loans  # noqa: E402
from bot.services.season_service import reset_season  # noqa: E402
from scripts.seed import seed_countries  # noqa: E402

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


def test_constants_and_economics() -> None:
    print("\n--- ۱. آزمون ثوابت اقتصادی، مقیاس بودجه‌ها و وفور آلومینیوم و فولاد ---")

    # بررسی سقف و کف وام و نرخ بهره
    check("سقف وام عادی ۱۰۰ میلیون دلار است", LOAN_LIMIT_NORMAL == 100_000_000.0, f"مقدار: {LOAN_LIMIT_NORMAL}")
    check("سقف وام خوش‌حساب ۲۰۰ میلیون دلار است", LOAN_LIMIT_GOOD == 200_000_000.0, f"مقدار: {LOAN_LIMIT_GOOD}")
    check("سقف وام بدحساب ۵۰ میلیون دلار است", LOAN_LIMIT_BAD_CREDIT == 50_000_000.0, f"مقدار: {LOAN_LIMIT_BAD_CREDIT}")
    check("نرخ بهره وام ۵ درصد است", LOAN_INTEREST_RATE == 0.05, f"مقدار: {LOAN_INTEREST_RATE}")
    check("نرخ جریمه دیرکرد ۱۰ درصد است", LOAN_DEFAULT_PENALTY_RATE == 0.10, f"مقدار: {LOAN_DEFAULT_PENALTY_RATE}")
    check("کلید قفل وام در LOCKABLE_FEATURES ثبت شده است", "econ.loan" in LOCKABLE_FEATURES)

    # بررسی بازدهی و مصرف فولاد و آلومینیوم
    check("بازدهی معدن آلومینیوم ۸۵,۰۰۰ واحد در ۲۴ ساعت است", MINE_YIELD_PER_24H[ResourceType.ALUMINUM] == 85_000.0)
    check("بازدهی معدن آهن ۱۲۰,۰۰۰ واحد در ۲۴ ساعت است", MINE_YIELD_PER_24H[ResourceType.IRON] == 120_000.0)
    check("بازدهی کارخانه فولاد ۸۰,۰۰۰ واحد است", STEEL_FACTORY_OUTPUT_PER_24H == 80_000.0)
    check("مصرف سنگ‌آهن کارخانه فولاد ۴۰,۰۰۰ واحد است", STEEL_FACTORY_IRON_INTAKE_PER_24H == 40_000.0)
    check("تولید فولاد دو برابر مصرف سنگ‌آهن آن است", STEEL_FACTORY_OUTPUT_PER_24H >= 2 * STEEL_FACTORY_IRON_INTAKE_PER_24H)

    # بازدهی اولیه در DEFAULT_BASE_YIELD
    check("بازدهی اولیه آلومینیوم ۲۵,۰۰۰ است", DEFAULT_BASE_YIELD["aluminum"] == 25_000.0)
    check("بازدهی اولیه آهن ۴۰,۰۰۰ است", DEFAULT_BASE_YIELD["iron"] == 40_000.0)

    # بررسی هزینه‌ها در مقیاس میلیون دلار
    check("هزینه احداث معدن ۳ میلیون دلار است", MINE_COST_USD == 3_000_000.0)
    check("هزینه کارخانه فولاد ۵ میلیون دلار است", STEEL_FACTORY_COST_USD == 5_000_000.0)
    check("هزینه سکوی نفتی ۱۵ میلیون دلار است", FACILITY_COST_USD[FacilityType.OIL_PLATFORM] == 15_000_000.0)
    check("هزینه کارخانه‌های نظامی در بازه ۵۰۰ هزار تا ۱۵ میلیون دلار است",
          all(500_000.0 <= cost <= 15_000_000.0 for cost in MIL_FACTORY_COST_USD.values()))
    check("هزینه ماهواره جاسوسی ۱۵ میلیون دلار است", SPY_SATELLITE_COST_USD == 15_000_000.0)
    check("هزینه تأسیسات هسته‌ای در مقیاس میلیون دلار است (حداکثر ۲۵ میلیون)",
          all(fac[1] <= 25_000_000.0 for fac in NUCLEAR_FACILITIES.values()))
    check("کارمزد ورودی مزایده ۲۰۰ هزار دلار است", AUCTION_ENTRY_FEE == 200_000.0)
    check("حداقل گام افزایش مزایده ۱۰۰ هزار دلار است", AUCTION_MIN_BID_STEP == 100_000.0)

    # سقف ساخت
    group_map = {g[0]: g[2] for g in BUILD_LIMIT_GROUPS}
    check("سقف ساخت معدن به ۸ ارتقا یافته است", group_map.get("mining") == 8)
    check("سقف ساخت کارخانه فولاد به ۴ ارتقا یافته است", group_map.get("steel") == 4)
    check("سقف مجموع ساخت غیر VIP به ۱۵ ارتقا یافته است", FACILITY_TOTAL_LIMIT_NON_VIP == 15)


def test_countries_json_integrity() -> None:
    print("\n--- ۲. آزمون صحت و مقادیر countries.json ---")
    data_file = ROOT / "data" / "countries.json"
    data = json.loads(data_file.read_text(encoding="utf-8"))
    countries = data["countries"]

    check("تعداد کشورها دقیقاً ۳۹ است", len(countries) == 39)

    usa = next((c for c in countries if c["name_en"] == "USA"), None)
    check("کشور آمریکا در داده‌ها وجود دارد", usa is not None)
    if usa:
        check("بودجه آمریکا دقیقاً ۱۵۰ میلیون دلار است", usa["economy"]["budget"] == 150_000_000.0, f"بودجه: {usa['economy']['budget']}")
        check("بدهی آمریکا متناسب‌سازی شده است (۷۸۵ میلیون)", usa["economy"]["govt_debt"] == 785_000_000.0)

    yemen = next((c for c in countries if c["name_en"] == "Yemen"), None)
    afghanistan = next((c for c in countries if c["name_en"] == "Afghanistan"), None)
    if yemen:
        check("کف بودجه برای یمن ۵۰ میلیون دلار است", yemen["economy"]["budget"] == 50_000_000.0)
    if afghanistan:
        check("کف بودجه برای افغانستان ۵۰ میلیون دلار است", afghanistan["economy"]["budget"] == 50_000_000.0)

    # بررسی بازه بودجه همه کشورها
    all_budgets = [c["economy"]["budget"] for c in countries]
    check("تمام بودجه‌ها بین ۵۰ میلیون تا ۱۵۰ میلیون دلار هستند",
          all(50_000_000.0 <= b <= 150_000_000.0 for b in all_budgets),
          f"کمترین: {min(all_budgets):,}, بیشترین: {max(all_budgets):,}")

    # بررسی وفور آلومینیوم و آهن در ذخایر
    extractable_al = sum(1 for c in countries if c.get("reserves", {}).get("aluminum", {}).get("can_extract") is True)
    extractable_iron = sum(1 for c in countries if c.get("reserves", {}).get("iron", {}).get("can_extract") is True)
    check("آلومینیوم در تمام ۳۹ کشور قابل استخراج است", extractable_al == 39, f"تعداد: {extractable_al}")
    check("آهن در تمام ۳۹ کشور قابل استخراج است", extractable_iron == 39, f"تعداد: {extractable_iron}")

    # بررسی ذخایر اولیه حداقل ۲۵ میلیون برای آلومینیوم و ۳۰ میلیون برای فولاد
    al_reserves = [c["reserves"]["aluminum"]["amount"] for c in countries if "aluminum" in c.get("reserves", {})]
    steel_reserves = [c["reserves"]["steel"]["amount"] for c in countries if "steel" in c.get("reserves", {})]
    iron_reserves = [c["reserves"]["iron"]["amount"] for c in countries if "iron" in c.get("reserves", {})]

    check("ذخایر آلومینیوم همه کشورها حداقل ۲۵,۰۰۰,۰۰۰ است", min(al_reserves) >= 25_000_000.0, f"کمترین: {min(al_reserves)}")
    check("ذخایر فولاد همه کشورها حداقل ۳۰,۰۰۰,۰۰۰ است", min(steel_reserves) >= 30_000_000.0, f"کمترین: {min(steel_reserves)}")
    check("ذخایر آهن همه کشورها حداقل ۶۰,۰۰۰,۰۰۰ است", min(iron_reserves) >= 60_000_000.0, f"کمترین: {min(iron_reserves)}")


async def test_loans_lifecycle() -> None:
    print("\n--- ۳. آزمون چرخه حیات وام بانکی و خوش‌حسابی ---")
    now = datetime.now(timezone.utc)

    async with async_session_factory() as session:
        await session.execute(text("PRAGMA foreign_keys=ON"))

        # ساخت کاربر و کشور
        user1 = User(telegram_id=2001, username="test_pres")
        session.add(user1)
        await session.flush()

        country1 = Country(
            name_en="Iran_Test",
            name_fa="ایران تستی",
            flag="🇮🇷",
            region="middle_east",
            owner_user_id=user1.telegram_id,
            is_claimed=True,
            budget=80_000_000.0,
            govt_debt=10_000_000.0,
            credit_rating=CreditRating.NORMAL,
            public_satisfaction=60.0,
            stability=60.0,
            inflation=15.0,
        )
        session.add(country1)
        await session.commit()

        cid = country1.id

        # ۱) بررسی سقف وام اولیه (عادی = ۱۰۰ میلیون)
        max_allowed = loans_repo.get_max_loan_for_rating(country1.credit_rating)
        check("سقف اولیه وام برای رتبه عادی ۱۰۰ میلیون است", max_allowed == 100_000_000.0)

        # ۲) دریافت وام ۱۰۰ میلیونی با ۵٪ بهره
        requested_loan = 100_000_000.0
        total_loan_due = requested_loan * (1.0 + LOAN_INTEREST_RATE)  # 105,000,000.0

        country1.budget += requested_loan
        country1.govt_debt += total_loan_due
        loan = await loans_repo.create_loan(
            session,
            country_id=cid,
            amount=requested_loan,
            deadline=now + timedelta(days=LOAN_DURATION_DAYS),
            reward_deadline=now + timedelta(days=LOAN_GOOD_CREDIT_DAYS),
            remaining_amount=total_loan_due,
        )
        await session.commit()

        check("وام با موفقیت ثبت شد", loan.id is not None)
        check("مبلغ اولیه وام ۱۰۰ میلیون است", loan.amount == 100_000_000.0)
        check("مبلغ بازپرداخت وام با احتساب سود ۵٪ برابر ۱۰۵ میلیون است", loan.remaining_amount == 105_000_000.0)
        check("بودجه کشور ۱۰۰ میلیون اضافه شد (۱۸۰ میلیون)", country1.budget == 180_000_000.0)
        check("بدهی دولتی کشور ۱۰۵ میلیون اضافه شد (۱۱۵ میلیون)", country1.govt_debt == 115_000_000.0)

        # ۳) تلاش برای دریافت وام دوم در حین وام فعال (باید وام فعال داشته باشد)
        active_loan = await loans_repo.get_active_loan(session, cid)
        check("کشور دارای یک وام فعال است", active_loan is not None and active_loan.status == LoanStatus.ACTIVE)

        # ۴) بازپرداخت به‌موقع و زودهنگام وام (در کمتر از ۳ روز)
        repay_amount = loan.remaining_amount
        country1.budget -= repay_amount
        country1.govt_debt = max(0.0, country1.govt_debt - repay_amount)

        # منطق بازپرداخت و ارتقا به خوش‌حسابی
        loan.status = LoanStatus.PAID
        loan.paid_at = now
        loan.remaining_amount = 0.0

        if now <= loan.reward_deadline:
            country1.credit_rating = CreditRating.GOOD

        await session.commit()

        check("وام به وضعیت PAID تغییر کرد", loan.status == LoanStatus.PAID)
        check("رتبه اعتباری کشور به خوش‌حساب (good) ارتقا یافت", country1.credit_rating == CreditRating.GOOD)

        # ۵) بررسی سقف جدید برای کشور خوش‌حساب (۲۰۰ میلیون)
        new_max = loans_repo.get_max_loan_for_rating(country1.credit_rating)
        check("سقف وام کشور خوش‌حساب ۲۰۰ میلیون دلار شد", new_max == 200_000_000.0)

        # ۶) دریافت وام جدید با سقف خوش‌حسابی (مثلاً ۲۰۰ میلیون)
        loan2_amount = 200_000_000.0
        loan2_due = loan2_amount * (1.0 + LOAN_INTEREST_RATE)  # 210,000,000.0
        loan2 = await loans_repo.create_loan(
            session,
            country_id=cid,
            amount=loan2_amount,
            deadline=now + timedelta(days=LOAN_DURATION_DAYS),
            reward_deadline=now + timedelta(days=LOAN_GOOD_CREDIT_DAYS),
            remaining_amount=loan2_due,
        )
        await session.commit()
        check("وام دوم ۲۰۰ میلیون دلاری برای کشور خوش‌حساب با موفقیت ثبت شد", loan2 is not None)

        # ۷) تست تاخیر در بازپرداخت و نکول وام (Default) با فرا رسیدن موعد و اجرای process_bank_loans
        # موعد وام دوم را به گذشته می‌بریم (۸ روز گذشته، ۱ روز دیرکرد)
        loan2.taken_at = now - timedelta(days=8)
        loan2.deadline = now - timedelta(days=1)
        loan2.reward_deadline = now - timedelta(days=5)
        await session.commit()

        # اجرای جاب زمان‌بندی بررسی وام‌ها
        bot_dummy = None
        await process_bank_loans(bot_dummy, session_override=session)

        # بازخوانی کشور و وام از دیتابیس
        await session.refresh(country1)
        await session.refresh(loan2)

        check("وضعیت وام دوم به DEFAULTED تغییر کرد", loan2.status == LoanStatus.DEFAULTED)
        check("جریمه ۱۰ درصدی دیرکرد روی باقیمانده وام اعمال شد",
              abs(loan2.remaining_amount - (loan2_due * 1.10)) < 1.0,
              f"مبلغ با جریمه: {loan2.remaining_amount:,.0f} در برابر انتظار: {loan2_due * 1.10:,.0f}")
        check("رتبه اعتباری کشور به بدحساب (defaulter) تنزل یافت و مسدود شد", country1.credit_rating == CreditRating.DEFAULTER)
        check("سقف وام در وضعیت مسدود صفر است",
              loans_repo.get_max_loan_for_rating(country1.credit_rating) == 0.0)
        check("شاخص‌های اجتماعی-اقتصادی کشور کاهش یافتند",
              country1.public_satisfaction == 57.0 and country1.stability == 57.0 and country1.inflation == 16.5)

        # ۸) تسویه وام معوقه و تبدیل رتبه به bad_credit با سقف ۵۰ میلیون
        country1.credit_rating = CreditRating.BAD_CREDIT
        check("سقف وام برای بدحسابِ تسویه‌شده ۵۰ میلیون دلار است",
              loans_repo.get_max_loan_for_rating(country1.credit_rating) == 50_000_000.0)


async def test_season_reset_integrity() -> None:
    print("\n--- ۴. آزمون سلامت کامل reset_season با Foreign Keys ---")

    await seed_countries()

    async with async_session_factory() as session:
        await session.execute(text("PRAGMA foreign_keys=ON"))

        # بررسی کشورها بعد از سید
        c_list = await countries_repo.list_countries(session)
        # ۳۹ کشور سید شده + ۱ کشور تستی که قبلا اضافه شد
        check("حداقل ۳۹ کشور در دیتابیس موجود است", len(c_list) >= 39, f"تعداد: {len(c_list)}")

        c_usa = await countries_repo.get_country_by_name(session, "USA")
        check("کشور آمریکا در دیتابیس یافت شد", c_usa is not None)
        if c_usa:
            check("بودجه اولیه آمریکا ۱۵۰ میلیون دلار است", c_usa.budget == 150_000_000.0)

        # تغییر بودجه و ثبت وام برای شبیه‌سازی فعالیت فصل
        c_usa.budget = 999.0
        c_usa.credit_rating = CreditRating.GOOD
        await loans_repo.create_loan(
            session,
            country_id=c_usa.id,
            amount=50_000_000.0,
            deadline=datetime.now(timezone.utc) + timedelta(days=7),
            reward_deadline=datetime.now(timezone.utc) + timedelta(days=3),
        )
        await session.commit()

        # بررسی وجود وام
        loans_count = (await session.execute(select(BankLoan))).scalars().all()
        check("وام فعال برای آمریکا ثبت شد", len(loans_count) >= 1)

        # اجرای reset_season
        stats = await reset_season(session)
        await session.commit()

        check("اجرای reset_season بدون خطای کلید خارجی کامل شد", stats is not None)

        # بررسی پاک شدن وام‌ها
        loans_after = (await session.execute(select(BankLoan))).scalars().all()
        check("جدول وام‌ها پس از ریست فصل کاملاً پاک شد", len(loans_after) == 0)

        # بازخوانی آمریکا
        await session.refresh(c_usa)
        check("بودجه آمریکا به ۱۵۰ میلیون دلار اولیه بازگشت", c_usa.budget == 150_000_000.0)
        check("رتبه اعتباری به normal بازنشانی شد", c_usa.credit_rating == "normal")

        # بررسی ذخایر آلومینیوم آمریکا بعد از ریست
        res_al = (await session.execute(
            select(Reserve).where(Reserve.country_id == c_usa.id, Reserve.resource == "aluminum")
        )).scalar_one_or_none()
        check("ذخیره آلومینیوم آمریکا پس از ریست قابل استخراج است", res_al is not None and res_al.can_extract is True)
        check("بازدهی آلومینیوم ۲۵,۰۰۰ ثبت شده است", res_al.base_yield == 25_000.0)


async def main() -> None:
    print("=" * 60)
    print("🚀 آغاز مجموعه تست‌های یکپارچه: اقتصاد جدید، وفور منابع و وام بانکی")
    print("=" * 60)

    try:
        await init_db()
        test_constants_and_economics()
        test_countries_json_integrity()
        await test_loans_lifecycle()
        await test_season_reset_integrity()
    finally:
        await engine.dispose()
        if TEST_DB_FILE.exists():
            try:
                TEST_DB_FILE.unlink()
            except Exception:
                pass

    print("\n" + "=" * 60)
    print(f"نتایج نهایی تست‌ها: {_passed} موفق | {len(_failed)} ناموفق")
    print("=" * 60)

    if _failed:
        print("\n❌ موارد شکست خورده:")
        for f in _failed:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("\n🎉 تمامی تست‌ها با موفقیت ۱۰۰٪ پاس شدند!")


if __name__ == "__main__":
    asyncio.run(main())
