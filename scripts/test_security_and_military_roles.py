"""
اسکریپت تست جامع سیستم رول‌های امنیتی، رول‌های نظامی و پنل مدیریتی /roles (آپدیت شماره ۲).

موارد بررسی:
۱. محدودیت سخت‌گیرانه سقف ۴۰۰۰ کاراکتری صفحات و سقف کمتر از ۹۶ کاراکتر برای سربرگ
۲. جریان کامل رول امنیتی: نگارش ۱ تا ۵ صفحه، کسر ۲۰M$، تایید توسط ادمین و ورود به آرشیو امنیتی کشور
۳. جریان رد رول امنیتی: عودت ۲۰ میلیون دلار به بودجه کشور و ثبت دلیل رد
۴. محدودیت صفحات رول‌های نظامی: خرابکاری (۲ ص)، ترور (۳ ص)، حمله (۵ ص)
۵. انتخاب کشور هدف و ممانعت از انتخاب کشور خود به عنوان هدف
۶. سیستم تلفات دوطرفه: کسر تلفات از مهاجم و مدافع با reduce_count و ذخیره در تاریخچه عملیات
۷. پایان عملیات: انتقال به COMPLETED و ساخت گزارش تلفات نهایی برای طرفین
۸. پنل مدیریتی /roles:
   - آرشیو پروژه‌های امنیتی کشورها
   - مدیریت و تایید رول‌های امنیتی معلق
   - مدیریت و تایید رول‌های اقتصادی معلق
   - مدیریت عملیات‌های نظامی باز
۹. پاک‌سازی کامل در ریست فصل (season_service.py) با اجبار PRAGMA foreign_keys = ON بدون خطای کلید خارجی
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# تنظیم محیط آزمایشی
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
    LOCKABLE_FEATURES,
    MAX_ROLE_PAGE_LEN,
    MILITARY_ROLE_ASSASSINATION_MAX_PAGES,
    MILITARY_ROLE_ATTACK_MAX_PAGES,
    MILITARY_ROLE_SABOTAGE_MAX_PAGES,
    ROLE_HEADER_MAX_LEN,
    SECURITY_ROLE_COST,
    SECURITY_ROLE_MAX_PAGES,
)
from bot.database.base import Base
from bot.database.models import (
    Country,
    EconomicProject,
    MilitaryAsset,
    MilitaryRole,
    SecurityRole,
    User,
)
from bot.database.repositories import economic_projects as econ_repo
from bot.database.repositories import military as mil_repo
from bot.database.repositories import military_roles as mil_ops_repo
from bot.database.repositories import security_roles as sec_repo
from bot.enums import (
    EconomicProjectStatus,
    MilitaryRoleStatus,
    MilitaryRoleType,
    SecurityRoleStatus,
)
from bot.loader import bot
from bot.services import news_service
from bot.services.military_role_service import (
    build_military_role_header,
    complete_military_role,
    format_casualties_report,
    record_casualty,
    render_military_role_message,
    submit_military_role,
)
from bot.services.season_service import reset_season
from bot.services.security_role_service import (
    approve_security_role,
    build_security_role_header,
    reject_security_role,
    render_security_role_message,
    submit_security_role,
    validate_role_page,
)

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

    def assert_true(cond: bool, desc: str) -> None:
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"✅ {desc}")
        else:
            failed += 1
            print(f"❌ {desc} | شرط برقرار نبود.")

    print("\n--- 🚀 شروع تست‌های جامع سیستم رول‌های امنیتی و نظامی (آپدیت ۲) ---")

    # ۱. بررسی ثابت‌ها و قفل‌ها
    assert_eq(SECURITY_ROLE_COST, 20_000_000.0, "هزینه رول امنیتی ۲۰ میلیون دلار")
    assert_eq(SECURITY_ROLE_MAX_PAGES, 5, "سقف رول امنیتی ۵ صفحه")
    assert_eq(MILITARY_ROLE_SABOTAGE_MAX_PAGES, 2, "سقف رول خرابکاری ۲ صفحه")
    assert_eq(MILITARY_ROLE_ASSASSINATION_MAX_PAGES, 3, "سقف رول ترور ۳ صفحه")
    assert_eq(MILITARY_ROLE_ATTACK_MAX_PAGES, 5, "سقف رول حمله ۵ صفحه")
    assert_true("security_roles" in LOCKABLE_FEATURES, "کلید security_roles در LOCKABLE_FEATURES")
    assert_true("military_roles" in LOCKABLE_FEATURES, "کلید military_roles در LOCKABLE_FEATURES")

    # ۲. اعتبارسنجی کاراکتری
    v_empty, _ = validate_role_page("")
    assert_eq(v_empty, False, "اعتبارسنجی: رد متن خالی")
    v_ok, _ = validate_role_page("متن تست صفحه رول" * 10)
    assert_eq(v_ok, True, "اعتبارسنجی: پذیرش متن استاندارد")
    v_long, _ = validate_role_page("A" * 4001)
    assert_eq(v_long, False, "اعتبارسنجی: رد متن بالای ۴۰۰۰ کاراکتر")

    # راه‌اندازی دیتابیس آزمایشی با Foreign Keys روشن
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async_session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON;"))
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        # ساخت کشورهای تستی
        c1 = Country(
            id=1,
            name_en="Iran",
            name_fa="ایران",
            flag="🇮🇷",
            region="middle_east",
            budget=100_000_000.0,
            economic_power=80.0,
            public_satisfaction=70.0,
            stability=65.0,
            inflation=12.0,
            unemployment=10.0,
        )
        c2 = Country(
            id=2,
            name_en="United States",
            name_fa="آمریکا",
            flag="🇺🇸",
            region="north_america",
            budget=500_000_000.0,
            economic_power=95.0,
            public_satisfaction=80.0,
            stability=85.0,
            inflation=3.0,
            unemployment=4.0,
        )
        session.add_all([c1, c2])

        # تجهیزات نظامی
        a1 = MilitaryAsset(id=1, country_id=1, branch="نیروی زمینی", category="تانک", name="تانک ذوالفقار", count=100, unit="عراده")
        a2 = MilitaryAsset(id=2, country_id=1, branch="نیروی هوایی", category="جنگنده", name="جنگنده کوثر", count=50, unit="فروند")
        a3 = MilitaryAsset(id=3, country_id=2, branch="نیروی زمینی", category="تانک", name="تانک آبرامز", count=200, unit="عراده")
        a4 = MilitaryAsset(id=4, country_id=2, branch="نیروی هوایی", category="جنگنده", name="F-35A", count=120, unit="فروند")
        session.add_all([a1, a2, a3, a4])
        await session.commit()

        # ============================================================
        # ۳. تست کامل رول امنیتی
        # ============================================================
        sec_role = SecurityRole(
            country_id=1,
            title="سامانه پدافند یکپارچه خلیج فارس",
            page_1="متن صفحه ۱ پدافند هوایی و رادارهای برد بلند",
            page_2="متن صفحه ۲ آشیانه‌های زیرزمینی و سامانه‌های فریب",
            page_3="متن صفحه ۳ پروتکل‌های ارتباط امن و ضدجاسوسی سایبری",
            status=SecurityRoleStatus.DRAFT.value,
        )
        await sec_repo.create_security_role(session, sec_role)
        await session.commit()

        assert_eq(sec_role.total_pages, 3, "رول امنیتی: شمارش صحیح ۳ صفحه")
        assert_true("متن صفحه ۲" in sec_role.get_page_text(2), "رول امنیتی: دریافت صحیح متن صفحه ۲")

        # تست سربرگ زیر ۹۶ کاراکتر
        hdr = build_security_role_header(sec_role, c1, 2)
        assert_true(len(hdr) <= ROLE_HEADER_MAX_LEN, f"طول سربرگ ({len(hdr)}) <= ۹۶ کاراکتر")

        # تست ارسال نهایی و کسر ۲۰M$
        ok_sub, msg_sub = await submit_security_role(session, sec_role, c1)
        assert_true(ok_sub, "ارسال رول امنیتی موفق")
        assert_eq(c1.budget, 80_000_000.0, "کسر ۲۰ میلیون دلار از خزانه ایران (۱۰۰M -> ۸۰M)")
        assert_eq(sec_role.status, SecurityRoleStatus.PENDING_REVIEW.value, "وضعیت رول به PENDING_REVIEW تغییر یافت")

        # تست تایید رول توسط ادمین
        await approve_security_role(session, sec_role, admin_id=111)
        await session.commit()
        assert_eq(sec_role.status, SecurityRoleStatus.APPROVED.value, "تایید رول: وضعیت APPROVED")
        assert_eq(sec_role.reviewed_by, 111, "تایید رول: ثبت شناسه ادمین ۱۱۱")

        # بررسی حضور در آرشیو امنیتی کشور
        approved_roles = await sec_repo.list_approved_by_country(session, 1)
        assert_eq(len(approved_roles), 1, "حضور رول در آرشیو امنیتی کشور ۱")
        arch_country_ids = await sec_repo.list_country_ids_with_approved_roles(session)
        assert_true(1 in arch_country_ids, "کشور ۱ در لیست کشورهای دارای آرشیو امنیتی")

        # تست رد رول امنیتی و عودت وجه
        sec_role_reject = SecurityRole(
            country_id=1,
            title="پروژه نامعتبر امنیتی",
            page_1="متن ضعیف",
            status=SecurityRoleStatus.DRAFT.value,
        )
        await sec_repo.create_security_role(session, sec_role_reject)
        await submit_security_role(session, sec_role_reject, c1)
        assert_eq(c1.budget, 60_000_000.0, "کسر ۲۰M برای پروژه دوم (۸۰M -> ۶۰M)")

        # رد با دلیل
        await reject_security_role(session, sec_role_reject, c1, admin_id=111, reason="عدم رعایت جزئیات دفاعی")
        await session.commit()
        assert_eq(sec_role_reject.status, SecurityRoleStatus.REJECTED.value, "وضعیت رول به REJECTED تغییر یافت")
        assert_eq(sec_role_reject.rejection_reason, "عدم رعایت جزئیات دفاعی", "ثبت دلیل رد رول")
        assert_eq(c1.budget, 80_000_000.0, "عودت ۲۰ میلیون دلار به خزانه ایران پس از رد رول (۶۰M -> ۸۰M)")

        # ============================================================
        # ۴. تست رول‌های نظامی ۳‌گانه و سقف صفحات
        # ============================================================
        mil_sabotage = MilitaryRole(
            attacker_country_id=1,
            target_country_id=2,
            op_type=MilitaryRoleType.SABOTAGE.value,
            title="خرابکاری در خطوط لوله",
            page_1="صفحه ۱ خرابکاری",
            page_2="صفحه ۲ خرابکاری",
            page_3="صفحه ۳ فراتر از سقف",
            status=MilitaryRoleStatus.DRAFT.value,
        )
        assert_eq(mil_sabotage.max_allowed_pages, 2, "سقف رول خرابکاری = ۲ صفحه")
        assert_eq(mil_sabotage.total_pages, 2, "محاسبه total_pages خرابکاری به سقف ۲ محدود است")

        mil_assassination = MilitaryRole(
            attacker_country_id=1,
            target_country_id=2,
            op_type=MilitaryRoleType.ASSASSINATION.value,
            title="عملیات ترور ژنرال",
            page_1="صفحه ۱ ترور",
            page_2="صفحه ۲ ترور",
            page_3="صفحه ۳ ترور",
            status=MilitaryRoleStatus.DRAFT.value,
        )
        assert_eq(mil_assassination.max_allowed_pages, 3, "سقف رول ترور = ۳ صفحه")
        assert_eq(mil_assassination.total_pages, 3, "محاسبه total_pages ترور = ۳")

        mil_attack = MilitaryRole(
            attacker_country_id=1,
            target_country_id=2,
            op_type=MilitaryRoleType.ATTACK.value,
            title="عملیات طوفان صحرا علیه پایگاه",
            page_1="صفحه ۱ تهاجم",
            page_2="صفحه ۲ نبرد زمینی",
            page_3="صفحه ۳ پشتیبانی هوایی",
            page_4="صفحه ۴ تثبیت مواضع",
            page_5="صفحه ۵ خروج نیروها",
            status=MilitaryRoleStatus.DRAFT.value,
        )
        await mil_ops_repo.create_military_role(session, mil_attack)
        await session.commit()
        assert_eq(mil_attack.max_allowed_pages, 5, "سقف رول حمله = ۵ صفحه")
        assert_eq(mil_attack.total_pages, 5, "محاسبه total_pages حمله = ۵")

        # ارسال نهایی عملیات حمله
        ok_mil_sub, _ = await submit_military_role(session, mil_attack)
        assert_true(ok_mil_sub, "ارسال نهایی عملیات حمله به ستاد")
        assert_eq(mil_attack.status, MilitaryRoleStatus.PENDING_REVIEW.value, "وضعیت عملیات حمله به PENDING_REVIEW تغییر یافت")

        # سربرگ پیام عملیات
        mil_hdr = build_military_role_header(mil_attack, c1, c2, 1)
        assert_true(len(mil_hdr) <= ROLE_HEADER_MAX_LEN, f"سربرگ رول نظامی ({len(mil_hdr)}) <= ۹۶ کاراکتر")

        # ============================================================
        # ۵. تست سیستم تلفات دوطرفه (مهاجم و مدافع)
        # ============================================================
        # ثبت تلفات روی مدافع (آمریکا: کسر تانک آبرامز از ۲۰۰ به ۱۹۰)
        ok_cas1, _, rem1 = await record_casualty(
            session, mil_attack, side="target", country=c2, asset_name="تانک آبرامز", count=10, admin_id=111
        )
        assert_true(ok_cas1, "ثبت تلفات روی کشور هدف (آمریکا)")
        assert_eq(rem1, 190, "موجودی تانک آبرامز آمریکا از ۲۰۰ به ۱۹۰ رسید")

        # ثبت تلفات روی مهاجم (ایران: کسر تانک ذوالفقار از ۱۰۰ به ۹۵)
        ok_cas2, _, rem2 = await record_casualty(
            session, mil_attack, side="attacker", country=c1, asset_name="تانک ذوالفقار", count=5, admin_id=111
        )
        assert_true(ok_cas2, "ثبت تلفات روی کشور مهاجم (ایران)")
        assert_eq(rem2, 95, "موجودی تانک ذوالفقار ایران از ۱۰۰ به ۹۵ رسید")

        # بررسی ذخیره‌سازی در سوابق عملیات
        cas_list = mil_attack.casualties_list
        assert_eq(len(cas_list), 2, "دو ردیف تلفات در عملیات ثبت شد")
        rep_text = format_casualties_report(mil_attack)
        assert_true("تانک آبرامز" in rep_text and "تانک ذوالفقار" in rep_text, "گزارش متنی شامل تلفات هر دو طرف است")

        # پایان عملیات
        await complete_military_role(session, mil_attack, admin_id=111)
        await session.commit()
        assert_eq(mil_attack.status, MilitaryRoleStatus.COMPLETED.value, "وضعیت عملیات به COMPLETED تغییر یافت")

        # ============================================================
        # ۶. تست پنل مدیریتی /roles
        # ============================================================
        # ایجاد رول اقتصادی معلق
        econ_p = EconomicProject(
            country_id=1,
            title="احداث مجتمع پتروشیمی نوین",
            page_1="طرح توسعه صنایع پتروشیمی",
            proposed_budget=50_000_000.0,
            status=EconomicProjectStatus.PENDING_REVIEW.value,
        )
        await econ_repo.create_project(session, econ_p)

        # ایجاد رول امنیتی معلق
        sec_pend = SecurityRole(
            country_id=2,
            title="پروژه سپر موشکی آلاسکا",
            page_1="طرح استقرار رادارهای باند ایکس",
            status=SecurityRoleStatus.PENDING_REVIEW.value,
        )
        await sec_repo.create_security_role(session, sec_pend)

        # ایجاد رول نظامی فعال/باز
        mil_open = MilitaryRole(
            attacker_country_id=2,
            target_country_id=1,
            op_type=MilitaryRoleType.ATTACK.value,
            title="عملیات ضدحمله عقاب",
            page_1="طرح عملیات هوایی",
            status=MilitaryRoleStatus.PENDING_REVIEW.value,
        )
        await mil_ops_repo.create_military_role(session, mil_open)
        await session.commit()

        # بررسی کوئری‌های پنل /roles
        pending_sec_all = await sec_repo.list_all_pending(session)
        assert_eq(len(pending_sec_all), 1, "پنل /roles: ۱ رول امنیتی در صف انتظار")
        assert_eq(pending_sec_all[0].title, "پروژه سپر موشکی آلاسکا", "عنوان رول امنیتی معلق")

        pending_econ_all = await econ_repo.list_all_pending(session)
        assert_eq(len(pending_econ_all), 1, "پنل /roles: ۱ رول اقتصادی در صف انتظار")
        assert_eq(pending_econ_all[0].title, "احداث مجتمع پتروشیمی نوین", "عنوان رول اقتصادی معلق")

        active_mil_all = await mil_ops_repo.list_all_pending(session)
        assert_eq(len(active_mil_all), 1, "پنل /roles: ۱ عملیات نظامی باز در صف اقدام")
        assert_eq(active_mil_all[0].title, "عملیات ضدحمله عقاب", "عنوان عملیات نظامی باز")

        # ============================================================
        # ۷. تست ریست فصل با اجبار کامل Foreign Keys (PRAGMA foreign_keys = ON)
        # ============================================================
        # اطمینان از وجود داده‌ها در جدول‌ها قبل از ریست
        roles_before = (await session.execute(select(SecurityRole))).scalars().all()
        mil_before = (await session.execute(select(MilitaryRole))).scalars().all()
        assert_true(len(roles_before) > 0 and len(mil_before) > 0, "جداول رول‌ها قبل از ریست دارای داده هستند")

        # اجرای ریست فصل
        await reset_season(session)
        await session.commit()

        roles_after = (await session.execute(select(SecurityRole))).scalars().all()
        mil_after = (await session.execute(select(MilitaryRole))).scalars().all()
        assert_eq(len(roles_after), 0, "جدول security_roles پس از ریست فصل کاملاً پاک شد")
        assert_eq(len(mil_after), 0, "جدول military_roles پس از ریست فصل کاملاً پاک شد")

    await engine.dispose()

    print("\n" + "=" * 60)
    print(f"📊 جمع‌بندی تست‌ها: {passed} موفق | {failed} ناموفق")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
