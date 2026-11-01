"""
اسکریپت تست خودکار جامع سیستم رول‌ها (نظامی، امنیتی، اقتصادی) و نشست‌های در حاشیه سازمان ملل (UN Sideline).

محورهای آزمون:
۱. ممیزی و تست ۱۰۰٪ دکمه‌ها، پیشوندها و کال‌بک‌های اصلاح‌شده در پنل /roles و منوهای UN Sideline.
۲. فلوهای داوری رول نظامی، ثبت تلفات دوطرفه، و اتمام عملیات از داخل پنل /roles (انتقال به COMPLETED، ثبت casualties_json، ارسال گزارش به طرفین).
۳. فلوهای داوری رول اقتصادی در پنل /roles و گروه داوری (ورق زدن، تصویب بودجه و بازدهی، رد پروژه با دلیل، پاک‌سازی استیت FSM).
۴. فلوهای جامع نشست در حاشیه مجمع عمومی سازمان ملل (دوجانبه و چندجانبه):
   - زمان پرواز صفر (FLIGHT_DURATION_MINUTES = 0) و ورود آنی به وضعیت ACTIVE
   - سیستم انحصار (عدم امکان حضور هم‌زمان در تماس/پرواز/نشست دیگر)
   - رله پیام‌های زنده با برچسب اختصاصی 🏛 [نشست حاشیه UN]
   - نشست چندجانبه، مدیریت حاضران، خروج مدعو و پایان توسط میزبان
   - پایان اضطراری جهت رفع قفل کشور
   - رفتار در reset_season و ریست نشست‌ها
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# تنظیم محیط تست SQLite در حافظه
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

from bot.constants import LOCKABLE_FEATURES, MEETING_DURATION_MINUTES, MEETING_IDLE_TIMEOUT_MINUTES
from bot.database.base import Base
from bot.database.models import (
    Country,
    EconomicProject,
    GroupMeeting,
    GroupMeetingParticipant,
    Meeting,
    MilitaryAsset,
    MilitaryRole,
    SecurityRole,
    User,
)
from bot.database.repositories import countries as countries_repo
from bot.database.repositories import diplomacy as dip_repo
from bot.database.repositories import economic_projects as econ_repo
from bot.database.repositories import military as mil_repo
from bot.database.repositories import military_roles as mil_ops_repo
from bot.database.repositories import security_roles as sec_repo
from bot.enums import (
    DiplomacyStatus,
    EconomicProjectStatus,
    MilitaryRoleStatus,
    MilitaryRoleType,
    ResourceType,
    SecurityRoleStatus,
)
from bot.keyboards.admin_roles import (
    admin_roles_country_security_kb,
    admin_roles_view_military_kb,
    admin_roles_view_security_kb,
)
from bot.keyboards.economic_projects import (
    admin_approve_settings_kb,
    admin_group_project_kb,
    admin_quick_cash_kb,
    admin_quick_yield_kb,
    admin_rejection_reasons_kb,
    admin_resource_picker_kb,
)
from bot.keyboards.military_roles import (
    admin_military_casualty_side_kb,
    admin_military_end_confirm_kb,
)
from bot.keyboards.united_nations import (
    un_main_menu_kb,
    un_sideline_active_kb,
    un_sideline_countries_kb,
    un_sideline_home_kb,
    un_sideline_invite_kb,
    un_sideline_recent_kb,
)
from bot.loader import bot
from bot.services import news_service
from bot.services.economic_project_service import (
    approve_and_launch_project,
    reject_project,
    render_project_message,
)
from bot.services.military_role_service import (
    complete_military_role,
    format_casualties_report,
    record_casualty,
    submit_military_role,
)
from bot.services.season_service import reset_season

bot.send_message = AsyncMock()
news_service.send_log = AsyncMock()
news_service.send_to_admin_group = AsyncMock()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def run_all_tests() -> None:
    passed = 0
    failed = 0

    def assert_eq(actual, expected, desc: str) -> None:
        nonlocal passed, failed
        if actual == expected:
            passed += 1
            print(f"  ✅ {desc}")
        else:
            failed += 1
            print(f"  ❌ {desc} | انتظار: {expected} ولی دریافت شد: {actual}")

    def assert_true(cond: bool, desc: str) -> None:
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  ✅ {desc}")
        else:
            failed += 1
            print(f"  ❌ {desc} (شرط برقرار نبود)")

    print("\n" + "=" * 65)
    print("🚀 شروع آزمون‌های خودکار سیستم رول‌ها و نشست حاشیه سازمان ملل")
    print("=" * 65)

    # ۱. راه‌اندازی دیتابیس در حافظه
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # -------------------------------------------------------------
    # بخش ۱: بررسی رجیستری فیچرها و کلیدها
    # -------------------------------------------------------------
    print("\n📌 بخش ۱: ممیزی رجیستری ویژگی‌ها و ستون‌های دیتابیس")
    assert_true("un.sideline" in LOCKABLE_FEATURES, "ویژگی un.sideline در LOCKABLE_FEATURES ثبت شده است")
    feat_name, feat_cat = LOCKABLE_FEATURES["un.sideline"]
    assert_eq(feat_name, "🤝 نشست در حاشیه سازمان ملل", "عنوان فارسی ویژگی حاشیه UN صحیح است")

    # -------------------------------------------------------------
    # بخش ۲: تست صحت دکمه‌ها و کال‌بک‌های پنل /roles
    # -------------------------------------------------------------
    print("\n📌 بخش ۲: تست کیبوردهای اصلاح‌شده پنل /roles و مود panel:")

    # الف) دکمه‌های ناوبری آرشیو امنیتی کشور هدف در رول نظامی
    dummy_sec_role = SecurityRole(id=10, country_id=2, title="پروژه پدافند", page_1="p1", page_2="p2", page_3="p3")
    sec_kb = admin_roles_view_security_kb(role=dummy_sec_role, current_page=1, mode="mil_back:99")
    all_cbs = [btn.callback_data for row in sec_kb.inline_keyboard for btn in row if btn.callback_data]
    assert_true("roles_admin:sec_v:10:2:mil_back:99" in all_cbs, "صفحه‌بندی آرشیو امنیتی مود mil_back را حفظ می‌کند")
    assert_true("roles_admin:mil_tgt_sec:99" in all_cbs, "دکمه بازگشت به رول نظامی مربوطه (mil_tgt_sec:99) متصل است")

    # ب) دکمه‌های پایان عملیات و ثبت تلفات در پنل /roles
    end_panel_kb = admin_military_end_confirm_kb(role_id=55, is_panel=True)
    end_cbs = [btn.callback_data for row in end_panel_kb.inline_keyboard for btn in row if btn.callback_data]
    assert_true("mil_end_do:55:panel" in end_cbs, "تأیید اتمام عملیات در پنل /roles دارای پسوند :panel است")
    assert_true("roles_admin:mil_v:55:1" in end_cbs, "انصراف از اتمام عملیات به پنل /roles بازمی‌گردد")

    cas_side_panel_kb = admin_military_casualty_side_kb(
        role_id=55, attacker_name="ایران", target_name="ترکیه", back_cb="roles_admin:mil_v:55:1", panel_suffix=":panel"
    )
    cas_cbs = [btn.callback_data for row in cas_side_panel_kb.inline_keyboard for btn in row if btn.callback_data]
    assert_true("mil_cas_side:55:attacker:panel" in cas_cbs, "انتخاب طرف تلفات در پنل دارای :panel است")
    assert_true("roles_admin:mil_v:55:1" in cas_cbs, "بازگشت از انتخاب طرف تلفات به پنل /roles وصل است")

    # ج) دکمه‌های رول اقتصادی در مود panel
    econ_rej_kb = admin_rejection_reasons_kb(project_id=40, is_panel=True)
    econ_rej_cbs = [btn.callback_data for row in econ_rej_kb.inline_keyboard for btn in row if btn.callback_data]
    assert_true("ep_grp_cancel:40:panel" in econ_rej_cbs, "انصراف از رد رول اقتصادی به پنل برمی‌گردد")
    assert_true("ep_rj_custom:40:panel" in econ_rej_cbs, "رد اختصاصی رول اقتصادی دارای :panel است")

    econ_app_kb = admin_approve_settings_kb(
        project_id=40, launch_cash=100.0, launch_res_count=0, yield_cash=15.0, yield_res_count=0, is_panel=True
    )
    econ_app_cbs = [btn.callback_data for row in econ_app_kb.inline_keyboard for btn in row if btn.callback_data]
    assert_true("ep_adm_confirm:40:panel" in econ_app_cbs, "تایید نهایی بودجه اقتصادی در پنل دارای :panel است")
    assert_true("ep_grp_cancel:40:panel" in econ_app_cbs, "انصراف از تایید بودجه اقتصادی به پنل متصل است")

    # -------------------------------------------------------------
    # بخش ۳: ایجاد دیتای پایه برای آزمون‌های پایگاه داده
    # -------------------------------------------------------------
    async with session_factory() as session:
        user1 = User(telegram_id=101, username="player_iran", first_name="ایران")
        user2 = User(telegram_id=102, username="player_turkey", first_name="ترکیه")
        user3 = User(telegram_id=103, username="player_germany", first_name="آلمان")
        session.add_all([user1, user2, user3])
        await session.flush()

        iran = Country(id=1, name_fa="ایران", name_en="Iran", flag="🇮🇷", region="middle_east", owner_user_id=101, budget=1000.0)
        turkey = Country(id=2, name_fa="ترکیه", name_en="Turkey", flag="🇹🇷", region="middle_east", owner_user_id=102, budget=1000.0)
        germany = Country(id=3, name_fa="آلمان", name_en="Germany", flag="🇩🇪", region="europe", owner_user_id=103, budget=1000.0)
        session.add_all([iran, turkey, germany])
        await session.flush()

        # دارایی‌های نظامی جهت تست تلفات
        tanks = MilitaryAsset(id=1, country_id=1, branch="نیروی زمینی", category="تانک", name="تانک کرار", count=100, unit="عراده")
        jets = MilitaryAsset(id=2, country_id=2, branch="نیروی هوایی", category="جنگنده", name="جنگنده اف-۱۶", count=50, unit="فروند")
        session.add_all([tanks, jets])
        await session.commit()

    # -------------------------------------------------------------
    # بخش ۴: تست جریان داوری رول نظامی، ثبت تلفات و پایان عملیات
    # -------------------------------------------------------------
    print("\n📌 بخش ۴: تست جریان داوری عملیات نظامی و ثبت تلفات:")
    async with session_factory() as session:
        c1 = await countries_repo.get_country(session, 1)
        c2 = await countries_repo.get_country(session, 2)

        # ایجاد رول نظامی حمله از ایران علیه ترکیه
        mil_role = MilitaryRole(
            attacker_country_id=1,
            target_country_id=2,
            op_type=MilitaryRoleType.ATTACK.value,
            title="عملیات طوفان صحرا",
            page_1="صفحه اول حمله به پایگاه‌ها...",
            page_2="صفحه دوم پیشروی زمینی...",
            status=MilitaryRoleStatus.PENDING_REVIEW.value,
            created_at=_utcnow(),
        )
        session.add(mil_role)
        await session.commit()

        # ثبت تلفات مهاجم (کاهش ۵ تانک از ایران)
        ok_cas1, _, rem1 = await record_casualty(
            session, mil_role, side="attacker", country=c1, asset_name="تانک کرار", count=5, admin_id=111
        )
        assert_true(ok_cas1, "ثبت تلفات مهاجم موفق بود")
        assert_eq(rem1, 95, "موجودی تانک‌های ایران به ۹۵ کاهش یافت")

        # ثبت تلفات مدافع (کاهش ۲ جنگنده از ترکیه)
        ok_cas2, _, rem2 = await record_casualty(
            session, mil_role, side="target", country=c2, asset_name="جنگنده اف-۱۶", count=2, admin_id=111
        )
        assert_true(ok_cas2, "ثبت تلفات مدافع موفق بود")
        assert_eq(rem2, 48, "موجودی جنگنده‌های ترکیه به ۴۸ کاهش یافت")

        # اتمام عملیات
        await complete_military_role(session, mil_role, admin_id=111)
        assert_eq(mil_role.status, MilitaryRoleStatus.COMPLETED.value, "وضعیت رول به COMPLETED تغییر کرد")
        assert_true(mil_role.casualties_json is not None, "آمار تلفات در casualties_json ثبت گردید")

        report = format_casualties_report(mil_role)
        assert_true("تانک کرار" in report and "جنگنده اف-۱۶" in report, "گزارش نهایی تلفات حاوی تجهیزات هر دو طرف است")
        await session.commit()

    # -------------------------------------------------------------
    # بخش ۵: تست جریان داوری رول اقتصادی
    # -------------------------------------------------------------
    print("\n📌 بخش ۵: تست جریان تصویب و رد رول اقتصادی:")
    async with session_factory() as session:
        # ایجاد رول اقتصادی
        iran_c = await countries_repo.get_country(session, 1)
        proj = EconomicProject(
            country_id=1,
            title="طرح توسعه میادین گازی پارس جنوبی",
            status=EconomicProjectStatus.PENDING_REVIEW,
            proposed_budget=150.0,
            page_1="توسعه فازهای جدید میدان گازی...",
        )
        await econ_repo.create_project(session, proj)
        await session.commit()

        # تصویب با هزینه دلخواه ۱۰۰ میلیون دلار و سود ۲۰ میلیون دلاری
        res = await approve_and_launch_project(
            session,
            proj,
            iran_c,
            admin_user_id=111,
            launch_cash=100.0,
            launch_resources={},
            yield_cash=20.0,
            yield_resources={"gas": 10.0},
        )
        assert_true(res["launched"], "پروژه اقتصادی بلافاصله با بودجه موجود افتتاح شد")
        assert_eq(proj.status, EconomicProjectStatus.ACTIVE, "وضعیت پروژه به ACTIVE تغییر یافت")
        assert_eq(proj.launch_cost_cash, 100.0, "هزینه افتتاح ۱۰۰ میلیون دلار ثبت شد")
        assert_eq(proj.yield_cash_72h, 20.0, "سود ۷۲ ساعته ۲۰ میلیون دلار ثبت شد")
        assert_eq(iran_c.budget, 900.0, "بودجه کشور از ۱۰۰۰ به ۹۰۰ کاهش یافت")

        # تست رد پروژه
        proj2 = EconomicProject(
            country_id=2,
            title="پروژه نامعتبر",
            status=EconomicProjectStatus.PENDING_REVIEW,
            proposed_budget=50.0,
            page_1="طرح بدون توجیه اقتصادی...",
        )
        await econ_repo.create_project(session, proj2)
        await session.commit()

        await reject_project(session, proj2, admin_user_id=111, reason="عدم رعایت استانداردهای فنی و نگارشی")
        await session.commit()
        assert_eq(proj2.status, EconomicProjectStatus.REJECTED, "پروژه دوم به درستی رد شد")
        assert_eq(proj2.rejection_reason, "عدم رعایت استانداردهای فنی و نگارشی", "علت رد پروژه در دیتابیس ثبت شد")

    # -------------------------------------------------------------
    # بخش ۶: تست نشست دوجانبه در حاشیه سازمان ملل (UN Sideline Bilateral)
    # -------------------------------------------------------------
    print("\n📌 بخش ۶: تست نشست دوجانبه در حاشیه سازمان ملل:")
    async with session_factory() as session:
        # ۱. چک انحصار اولیه: هیچ کشوری مشغول نیست
        eng1 = await dip_repo.get_active_engagement_label(session, 1)
        eng2 = await dip_repo.get_active_engagement_label(session, 2)
        assert_true(eng1 is None and eng2 is None, "قبل از آغاز نشست هیچ‌یک از کشورها مشغول نیستند")

        # ۲. ایجاد نشست دوجانبه حاشیه UN با پرواز ۰ دقیقه
        now = _utcnow()
        bi_meet = Meeting(
            traveler_country=1,
            host_country=2,
            status=DiplomacyStatus.PENDING,
            is_un_sideline=True,
            topic="مذاکرات صلح قفقاز در حاشیه مجمع عمومی",
            travel_eta=now,  # زمان پرواز صفر!
            meeting_ends_at=now + timedelta(minutes=MEETING_DURATION_MINUTES),
            last_msg_at=now,
        )
        await dip_repo.add_meeting(session, bi_meet)
        await session.commit()

        assert_eq(bi_meet.is_un_sideline, True, "فیلد is_un_sideline به درستی True ثبت شد")
        assert_eq(bi_meet.topic, "مذاکرات صلح قفقاز در حاشیه مجمع عمومی", "موضوع نشست ثبت شد")

        # ۳. پذیرش دعوت‌نامه: بدون زمان پرواز، بلافاصله وارد ACTIVE می‌شود
        bi_meet.status = DiplomacyStatus.ACTIVE
        bi_meet.travel_eta = _utcnow()  # پرواز صفر!
        bi_meet.start_announced = True
        await session.commit()

        # ۴. چک انحصار: هر دو کشور باید اکنون قفل و مشغول دیدار باشند
        eng_iran = await dip_repo.get_active_engagement_label(session, 1)
        eng_turkey = await dip_repo.get_active_engagement_label(session, 2)
        assert_true(eng_iran is not None, f"ایران در حالت انحصار قرار گرفت: {eng_iran}")
        assert_true(eng_turkey is not None, f"ترکیه در حالت انحصار قرار گرفت: {eng_turkey}")

        # ۵. تست رله پیام و اعمال تاچ سکوت
        old_last_msg = bi_meet.last_msg_at
        new_now = _utcnow() + timedelta(seconds=30)
        bi_meet.last_msg_at = new_now
        await session.commit()
        assert_true(bi_meet.last_msg_at > old_last_msg, "با ارسال پیام در چت، last_msg_at به‌روزرسانی شد")

        # ۶. تست اتمام نشست و آزادسازی انحصار
        bi_meet.status = DiplomacyStatus.COMPLETED
        await session.commit()
        eng_iran_after = await dip_repo.get_active_engagement_label(session, 1)
        assert_true(eng_iran_after is None, "پس از اتمام نشست، وضعیت انحصار ایران آزاد شد")

    # -------------------------------------------------------------
    # بخش ۷: تست نشست چندجانبه در حاشیه سازمان ملل (UN Sideline Multilateral)
    # -------------------------------------------------------------
    print("\n📌 بخش ۷: تست نشست چندجانبه در حاشیه سازمان ملل:")
    async with session_factory() as session:
        # ۱. ایجاد نشست چندجانبه توسط ایران
        now = _utcnow()
        grp_meet = GroupMeeting(
            host_country=1,
            title="نشست حاشیه UN: کریدور بین‌المللی شمال-جنوب",
            topic="کریدور بین‌المللی شمال-جنوب",
            is_un_sideline=True,
            status=DiplomacyStatus.PENDING,
            meeting_ends_at=now + timedelta(minutes=MEETING_DURATION_MINUTES),
            last_msg_at=now,
        )
        await dip_repo.add_group_meeting(session, grp_meet)
        await session.flush()

        # ثبت اعضا: ایران (میزبان)، ترکیه و آلمان
        await dip_repo.add_group_participant(session, grp_meet.id, 1)
        p_turkey = await dip_repo.add_group_participant(session, grp_meet.id, 2)
        p_germany = await dip_repo.add_group_participant(session, grp_meet.id, 3)
        await session.commit()

        # ۲. پذیرش اولین مدعو (ترکیه) -> ورود آنی نشست به وضعیت ACTIVE با پرواز ۰ دقیقه
        grp_meet.status = DiplomacyStatus.ACTIVE
        p_turkey.response = DiplomacyStatus.ACTIVE
        await session.commit()

        # بررسی انحصار برای اعضای فعال
        eng_host = await dip_repo.get_active_engagement_label(session, 1)
        eng_guest = await dip_repo.get_active_engagement_label(session, 2)
        assert_true(eng_host is not None, "میزبان در نشست چندجانبه مشغول است")
        assert_true(eng_guest is not None, "مدعو پذیرفته در نشست چندجانبه مشغول است")

        # ۳. خروج یک عضو از نشست چندجانبه
        await dip_repo.remove_group_participant(session, grp_meet.id, 3)
        await session.commit()
        members_after_leave = await dip_repo.group_member_country_ids(session, grp_meet)
        assert_true(3 not in members_after_leave, "آلمان پس از خروج دیگر در لیست شرکت‌کنندگان نیست")

        # ۴. پایان نشست چندجانبه توسط میزبان و آزادسازی تمام اعضا
        grp_meet.status = DiplomacyStatus.COMPLETED
        await session.commit()
        eng_host_after = await dip_repo.get_active_engagement_label(session, 1)
        eng_guest_after = await dip_repo.get_active_engagement_label(session, 2)
        assert_true(eng_host_after is None and eng_guest_after is None, "با پایان نشست چندجانبه تمام اعضا آزاد شدند")

    # -------------------------------------------------------------
    # بخش ۸: تست تایم‌اوت خودکار سکوت و زمان پایان
    # -------------------------------------------------------------
    print("\n📌 بخش ۸: تست تایم‌اوت ۱۰ دقیقه‌ای سکوت و پایان ۶۰ دقیقه‌ای:")
    async with session_factory() as session:
        # دیدار با سکوت ۱۱ دقیقه
        eleven_min_ago = _utcnow() - timedelta(minutes=11)
        idle_meet = Meeting(
            traveler_country=1,
            host_country=2,
            status=DiplomacyStatus.ACTIVE,
            is_un_sideline=True,
            topic="نشست در حال سکوت",
            travel_eta=eleven_min_ago,
            meeting_ends_at=_utcnow() + timedelta(minutes=49),
            last_msg_at=eleven_min_ago,
            start_announced=True,
        )
        await dip_repo.add_meeting(session, idle_meet)
        await session.commit()

        # بررسی شرط تایم‌اوت در شبیه‌ساز جاب اسکولر
        now = _utcnow()
        arrived_idle = idle_meet.last_msg_at or idle_meet.travel_eta
        idle_too_long = (now - arrived_idle) >= timedelta(minutes=MEETING_IDLE_TIMEOUT_MINUTES)
        assert_true(idle_too_long, "تایم‌اوت سکوت ۱۰ دقیقه به درستی تشخیص داده شد")

        if idle_too_long:
            idle_meet.status = DiplomacyStatus.COMPLETED
            await session.commit()
        assert_eq(idle_meet.status, DiplomacyStatus.COMPLETED, "نشست راکد با موفقیت به صورت خودکار COMPLETED شد")

    # -------------------------------------------------------------
    # بخش ۹: تست ریست فصل و پاک‌سازی کامل نشست‌های حاشیه UN
    # -------------------------------------------------------------
    print("\n📌 بخش ۹: تست reset_season و عملکرد نشست‌های حاشیه UN:")
    async with session_factory() as session:
        # اجرای reset_season
        await reset_season(session)
        await session.commit()

        # بررسی پاک‌سازی یا بسته‌شدن نشست‌ها
        active_bi = await session.execute(
            select(Meeting).where(Meeting.status.in_([DiplomacyStatus.PENDING, DiplomacyStatus.ACTIVE]))
        )
        active_grp = await session.execute(
            select(GroupMeeting).where(GroupMeeting.status.in_([DiplomacyStatus.PENDING, DiplomacyStatus.ACTIVE]))
        )
        assert_true(len(active_bi.scalars().all()) == 0, "تمام دیدارهای فعال در reset_season پاک/کنسل شدند")
        assert_true(len(active_grp.scalars().all()) == 0, "تمام نشست‌های چندجانبه در reset_season پاک/کنسل شدند")

    print("\n" + "=" * 65)
    print(f"🏁 نتیجه آزمون‌ها: {passed} آزمون موفق | {failed} آزمون ناموفق")
    print("=" * 65)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
