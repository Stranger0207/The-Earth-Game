"""
اسکریپت تست جامع سیستم رول‌ها و پروژه‌های اقتصادی (آپدیت شماره ۹).

موارد بررسی:
۱. محدودیت سخت‌گیرانه سقف ۴۰۰۰ کاراکتری صفحات و سقف کمتر از ۹۶ کاراکتر برای سربرگ
۲. ثبت، اعتبارسنجی و خواندن پیش‌نویس ۱ و ۲ صفحه‌ای
۳. بررسی ثابت‌ها، کلیدهای قفل و شمارش‌گرها
۴. عملکرد ریپازیتوری‌های اختصاصی
۵. جریان رد رول همراه با درج دلیل توسط مدیریت
۶. جریان تایید رول در حالت کمبود منابع و انتقال به APPROVED_AWAITING_LAUNCH
۷. جریان افتتاح دستی پس از تأمین موجودی
۸. جریان تایید و افتتاح مستقیم با کسر بودجه و ذخایر (ACTIVE)
۹. واریز خودکار سود ۷۲ ساعته در زمان‌بند (jobs.py)
۱۰. پاک‌سازی کامل در ریست فصل (season_service.py) با PRAGMA foreign_keys=ON
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# تنظیم محیط تست
os.environ["BOT_TOKEN"] = "123456:TEST_TOKEN_ONLY"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GROQ_API_KEY"] = "gsk_test"
os.environ["OWNER_IDS"] = "[111]"
os.environ["ADMIN_IDS"] = "[111, 222]"
os.environ["PYTHONUTF8"] = "1"

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.constants import (
    ECON_PROJECT_HEADER_MAX_LEN,
    ECON_PROJECT_YIELD_INTERVAL_HOURS,
    LOCKABLE_FEATURES,
    MAX_ROLE_PAGE_LEN,
)
from bot.database.base import Base
from bot.database.models import Country, EconomicProject, Reserve, User
from bot.database.repositories import economic_projects as proj_repo
from bot.database.repositories import reserves as reserves_repo
from bot.enums import (
    ECONOMIC_PROJECT_STATUS_FA,
    EconomicProjectStatus,
    ResourceType,
)
from bot.keyboards.economic_projects import (
    admin_approve_settings_kb,
    admin_group_project_kb,
    admin_rejection_reasons_kb,
    econ_projects_home_kb,
    project_draft_view_kb,
    project_list_kb,
)
from bot.loader import bot
from bot.scheduler.jobs import process_economic_projects
from bot.services import news_service
from bot.services.economic_project_service import (
    approve_and_launch_project,
    build_project_header,
    format_resources_dict,
    launch_awaiting_project,
    process_project_payout,
    reject_project,
    render_project_message,
    validate_role_page,
)
from bot.services.season_service import reset_season

bot.send_message = AsyncMock()
news_service.send_log = AsyncMock()
news_service.send_to_admin_group = AsyncMock()


async def run_all_tests() -> None:
    passed = 0
    failed = 0

    def assert_eq(actual, expected, desc: str) -> None:
        nonlocal passed, failed
        if actual == expected:
            passed += 1
            print(f"✅ {desc}")
        else:
            failed += 1
            print(f"❌ {desc} | انتظار: {expected} ولی دریافت شد: {actual}")

    def assert_true(condition: bool, desc: str) -> None:
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"✅ {desc}")
        else:
            failed += 1
            print(f"❌ {desc} | شرط برقرار نبود.")

    print("\n" + "=" * 60)
    print("🚀 آغاز تست‌های جامع سیستم رول‌های اقتصادی (آپدیت شماره ۹)")
    print("=" * 60 + "\n")

    # ----------------------------------------------------
    # بخش ۱: تست سقف کاراکتر و سربرگ ۹۶ کاراکتری
    # ----------------------------------------------------
    print("--- ۱. بررسی سقف کاراکتر صفحات و سربرگ ۹۶ کاراکتری ---")
    assert_eq(MAX_ROLE_PAGE_LEN, 4000, "سقف کاراکتر صفحه رول باید دقیقا ۴۰۰۰ باشد")
    assert_eq(ECON_PROJECT_HEADER_MAX_LEN, 96, "سقف رزروشده سربرگ ربات باید ۹۶ باشد")

    # تست اعتبارسنجی طول متن
    ok_4000, msg_4000 = validate_role_page("a" * 4000)
    assert_true(ok_4000, "متن دقیقا ۴۰۰۰ کاراکتری مجاز است")

    ok_4001, msg_4001 = validate_role_page("a" * 4001)
    assert_true(not ok_4001, "متن ۴۰۰۱ کاراکتری باید خطا بدهد")
    assert_true("سقف کاراکتر" in msg_4001, "متن خطا حاوی اخطار سقف کاراکتر است")

    # ساخت شیء فرضی برای تست سربرگ
    dummy_country = Country(
        id=1,
        name_fa="جمهوری فدرال آلمان",
        name_en="Germany",
        flag="🇩🇪",
        region="europe",
        budget=100_000_000.0,
    )
    dummy_user = User(
        telegram_id=12345,
        username="test_pres",
        president_name="دکتر والتر اشتاین‌مایر ارشد",
    )
    dummy_project = EconomicProject(
        id=1,
        country_id=1,
        title="توسعه زیرساخت فیبر نوری سراسری و دیتاسنترها",
        page_1="متن صفحه اول",
        page_2="متن صفحه دوم",
        proposed_budget=500_000_000.0,
        status=EconomicProjectStatus.DRAFT.value,
    )

    header_text = build_project_header(dummy_country, dummy_project, 1, dummy_user)
    header_len = len(header_text)
    print(f"طول سربرگ تولیدشده: {header_len} کاراکتر")
    assert_true(header_len <= 96, f"طول سربرگ ({header_len}) باید کمتر یا مساوی ۹۶ کاراکتر باشد")
    assert_true(header_len + 4000 <= 4096, "مجموع سربرگ و متن ۴۰۰۰ کاراکتری از سقف ۴۰۹۶ تلگرام رد نمی‌شود")

    full_msg = render_project_message(dummy_country, dummy_project, 1, dummy_user)
    assert_true(dummy_project.title[:20] in full_msg, "متن رندرشده شامل عنوان پروژه است")

    # ----------------------------------------------------
    # بخش ۲: تست ثابت‌ها و کلیدهای قفل
    # ----------------------------------------------------
    print("\n--- ۲. بررسی ثابت‌ها، کلیدهای قفل و شمارش‌گرها ---")
    assert_eq(ECON_PROJECT_YIELD_INTERVAL_HOURS, 72, "چرخه بازدهی پروژه باید ۷۲ ساعت باشد")
    assert_true("econ.projects" in LOCKABLE_FEATURES, "کلید econ.projects در LOCKABLE_FEATURES موجود است")
    from bot.constants import FEATURE_KEY_ALIASES
    assert_eq(FEATURE_KEY_ALIASES.get("econ_projects"), "econ.projects", "کلید مستعار econ_projects به econ.projects نگاشت می‌شود")

    # شمارش‌گرهای وضعیت
    for st in [
        EconomicProjectStatus.DRAFT,
        EconomicProjectStatus.PENDING_REVIEW,
        EconomicProjectStatus.APPROVED_AWAITING_LAUNCH,
        EconomicProjectStatus.ACTIVE,
        EconomicProjectStatus.REJECTED,
        EconomicProjectStatus.CANCELLED,
    ]:
        assert_true(st in ECONOMIC_PROJECT_STATUS_FA, f"عنوان فارسی وضعیت {st} موجود است")

    # ----------------------------------------------------
    # بخش ۳: راه‌اندازی دیتابیس درون‌حافظه‌ای و تست ORM
    # ----------------------------------------------------
    print("\n--- ۳. راه‌اندازی دیتابیس SQLite و بررسی CRUD ---")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON;"))
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user_owner = User(telegram_id=999, username="japan_owner")
        session.add(user_owner)

        country = Country(
            id=10,
            name_fa="ژاپن",
            name_en="Japan",
            flag="🇯🇵",
            region="east_asia",
            budget=200_000_000.0,
            owner_user_id=999,
            is_claimed=True,
        )
        session.add(country)

        # ایجاد ذخایر فولاد و نفت برای کشور
        res_steel = Reserve(country_id=10, resource="steel", amount=100_000.0, can_extract=True)
        res_oil = Reserve(country_id=10, resource="oil", amount=10.0, can_extract=True)
        session.add_all([res_steel, res_oil])
        await session.commit()

        # تست ۱: ساخت پیش‌نویس ۲ صفحه‌ای
        p1 = EconomicProject(
            country_id=10,
            title="پروژه نیمه‌هادی پیشرفته",
            page_1="متن صفحه اول رول تا ۴۰۰۰ کاراکتر",
            page_2="متن صفحه دوم اختیاری",
            proposed_budget=80_000_000.0,
            status=EconomicProjectStatus.DRAFT.value,
        )
        await proj_repo.create_project(session, p1)
        await session.commit()

        assert_eq(p1.total_pages, 2, "پروژه دو صفحه‌ای شناسایی شد")
        assert_eq(p1.get_page_text(1), "متن صفحه اول رول تا ۴۰۰۰ کاراکتر", "دریافت متن صفحه ۱")
        assert_eq(p1.get_page_text(2), "متن صفحه دوم اختیاری", "دریافت متن صفحه ۲")

        # تست لیست پیش‌نویس‌ها
        drafts = await proj_repo.list_drafts_by_country(session, 10)
        assert_eq(len(drafts), 1, "یک پیش‌نویس برای کشور یافت شد")

        # تست ۲: رد کردن رول با دلیل توسط ادمین
        await reject_project(session, p1, admin_user_id=111, reason="عدم تناسب مقیاس رول")
        await session.commit()
        assert_eq(p1.status, EconomicProjectStatus.REJECTED.value, "وضعیت به REJECTED تغییر یافت")
        assert_eq(p1.rejection_reason, "عدم تناسب مقیاس رول", "دلیل رد ثبت شد")
        assert_eq(p1.reviewed_by, 111, "آیدی ادمین ثبت شد")

        # تست ۳: پروژه جدید با تایید در حالت کمبود منابع (APPROVED_AWAITING_LAUNCH)
        p2 = EconomicProject(
            country_id=10,
            title="توسعه مزارع خورشیدی",
            page_1="متن یک صفحه‌ای",
            page_2=None,
            proposed_budget=300_000_000.0,
            status=EconomicProjectStatus.PENDING_REVIEW.value,
        )
        await proj_repo.create_project(session, p2)
        await session.commit()
        assert_eq(p2.total_pages, 1, "پروژه تک‌صفحه‌ای درست شناخته شد")

        # ادمین هزینه‌ای بیشتر از بودجه کشور (مثلاً ۲۵۰ میلیون در حالی که بودجه ۲۰۰ است) تعیین می‌کند
        launch_res = {"steel": 150_000.0}  # کشور فقط ۱۰۰ هزار تا دارد
        res_approve = await approve_and_launch_project(
            session=session,
            project=p2,
            country=country,
            admin_user_id=111,
            launch_cash=250_000_000.0,
            launch_resources=launch_res,
            yield_cash=30_000_000.0,
            yield_resources={"oil": 0.2},
        )
        await session.commit()

        assert_eq(res_approve["launched"], False, "به دلیل کمبود نقدینگی و ذخایر، پروژه درجا افتتاح نشد")
        assert_eq(p2.status, EconomicProjectStatus.APPROVED_AWAITING_LAUNCH.value, "پروژه به وضعیت در انتظار افتتاح رفت")
        assert_eq(country.budget, 200_000_000.0, "بودجه کشور دست نخورده باقی ماند")

        # تست افتتاح دستی ناموفق (هنوز بودجه و ذخایر تامین نشده)
        res_fail_launch = await launch_awaiting_project(session, p2, country)
        assert_eq(res_fail_launch["success"], False, "افتتاح با بودجه ناکافی شکست می‌خورد")

        # اکنون بودجه و ذخایر کشور را افزایش می‌دهیم
        country.budget += 100_000_000.0  # بودجه شد ۳۰۰M
        await reserves_repo.add_amount(session, country.id, "steel", 100_000.0)  # موجودی فولاد شد ۲۰۰K
        await session.commit()

        # تست افتتاح دستی موفق
        res_ok_launch = await launch_awaiting_project(session, p2, country)
        await session.commit()
        assert_eq(res_ok_launch["success"], True, "افتتاح دستی با موجودی کافی موفقیت‌آمیز بود")
        assert_eq(p2.status, EconomicProjectStatus.ACTIVE.value, "وضعیت پروژه ACTIVE شد")
        assert_eq(country.budget, 50_000_000.0, "هزینه ۲۵۰ میلیون از بودجه کسر شد (مانده: ۵۰M)")
        res_steel_cur = await reserves_repo.get_reserve(session, country.id, "steel")
        assert_eq(res_steel_cur.amount, 50_000.0, "۱۵۰ هزار تن فولاد کسر شد (مانده: ۵۰K)")
        assert_true(p2.next_yield_at is not None, "موعد واریز بعدی ۷۲ ساعته تنظیم شد")

        # ----------------------------------------------------
        # بخش ۴: تست تایید مستقیم با موجودی کافی (ACTIVE درجا)
        # ----------------------------------------------------
        print("\n--- ۴. تست تایید مستقیم و افتتاح فوری (ACTIVE) ---")
        p3 = EconomicProject(
            country_id=10,
            title="صنایع رباتیک پیشرفته",
            page_1="متن پروژه رباتیک",
            proposed_budget=20_000_000.0,
            status=EconomicProjectStatus.PENDING_REVIEW.value,
        )
        await proj_repo.create_project(session, p3)
        await session.commit()

        res_direct = await approve_and_launch_project(
            session=session,
            project=p3,
            country=country,
            admin_user_id=111,
            launch_cash=10_000_000.0,
            launch_resources={"steel": 10_000.0},
            yield_cash=2_000_000.0,
            yield_resources={},
        )
        await session.commit()

        assert_eq(res_direct["launched"], True, "افتتاح مستقیم موفق شد")
        assert_eq(p3.status, EconomicProjectStatus.ACTIVE.value, "پروژه درجا ACTIVE شد")
        assert_eq(country.budget, 40_000_000.0, "۱۰ میلیون دلار افتتاح کسر شد (مانده: ۴۰M)")

        # ----------------------------------------------------
        # بخش ۵: تست زمان‌بند بازدهی ۷۲ ساعته (jobs.py)
        # ----------------------------------------------------
        print("\n--- ۵. بررسی عملکرد زمان‌بند بازدهی ۷۲ ساعته ---")
        # برای تست، زمان موعد واریز p2 را به ۱ دقیقه قبل عقب می‌بریم تا سررسید شود
        now = datetime.now(timezone.utc)
        p2.next_yield_at = now - timedelta(minutes=5)
        # موعد p3 را روی ۷۲ ساعت بعد می‌گذاریم تا سررسید نشود
        p3.next_yield_at = now + timedelta(hours=72)
        await session.commit()

        initial_budget = country.budget
        res_oil_before = (await reserves_repo.get_reserve(session, country.id, "oil")).amount

        # اجرای جاب زمان‌بند
        await process_economic_projects(bot=bot, session_override=session)
        await session.refresh(country)
        await session.refresh(p2)
        await session.refresh(p3)

        # سود p2 مبلغ ۳۰ میلیون نقدینگی و ۰.۲ نفت بود
        assert_eq(country.budget, initial_budget + 30_000_000.0, "سود ۳۰ میلیون دلاری ۷۲ ساعته واریز شد")
        res_oil_after = (await reserves_repo.get_reserve(session, country.id, "oil")).amount
        assert_eq(round(res_oil_after - res_oil_before, 2), 0.2, "سود ۰.۲ میلیون بشکه نفت به ذخایر اضافه شد")
        p2_next = p2.next_yield_at if p2.next_yield_at.tzinfo else p2.next_yield_at.replace(tzinfo=timezone.utc)
        assert_true(p2_next > now, "موعد بعدی واریز p2 به ۷۲ ساعت آینده تغییر کرد")

        # ----------------------------------------------------
        # بخش ۶: تست کیبوردهای تعاملی
        # ----------------------------------------------------
        print("\n--- ۶. بررسی رندر کیبوردهای تعاملی ---")
        kb_home = econ_projects_home_kb()
        assert_true(len(kb_home.inline_keyboard) >= 5, "کیبورد منوی اصلی دارای ۵ گزینه است")

        kb_draft = project_draft_view_kb(p1, 1)
        assert_true(any("ارسال نهایی" in btn.text for row in kb_draft.inline_keyboard for btn in row), "دکمه ارسال نهایی در پیش‌نویس موجود است")

        kb_grp = admin_group_project_kb(p1, 1)
        assert_true(any("تایید رول" in btn.text for row in kb_grp.inline_keyboard for btn in row), "دکمه تایید رول در گروه رول اقتصادی موجود است")
        assert_true(any("رد کردن" in btn.text for row in kb_grp.inline_keyboard for btn in row), "دکمه رد رول در گروه رول اقتصادی موجود است")

        kb_settings = admin_approve_settings_kb(p1.id, 50_000_000.0, 1, 10_000_000.0, 0)
        assert_true(any("صدور تأییدیه" in btn.text for row in kb_settings.inline_keyboard for btn in row), "دکمه صدور تاییدیه ادمین موجود است")

        # ----------------------------------------------------
        # بخش ۷: تست ریست کامل فصل (Foreign Key Integrity)
        # ----------------------------------------------------
        print("\n--- ۷. بررسی ریست فصل با اجبار Foreign Key ---")
        # افزودن داده‌های جانبی برای اطمینان از پاک‌سازی کامل
        active_projs = await proj_repo.list_all_active(session)
        assert_true(len(active_projs) >= 2, "پروژه‌های فعال قبل از ریست وجود دارند")

        # فراخوانی reset_season
        await reset_season(session)

        # بررسی پاک شدن پروژه‌ها
        res_after_reset = await session.execute(select(EconomicProject))
        remaining = list(res_after_reset.scalars().all())
        assert_eq(len(remaining), 0, "تمامی پروژه‌های اقتصادی در ریست فصل پاک شدند")

        # بررسی کشور پس از ریست
        c_after = await session.get(Country, 10)
        assert_eq(c_after.is_claimed, False, "مالکیت کشور آزاد شد")

    await engine.dispose()

    print("\n" + "=" * 60)
    print(f"📊 نتیجه نهایی تست‌ها: {passed} موفق | {failed} ناموفق")
    print("=" * 60 + "\n")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
