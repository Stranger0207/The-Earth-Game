"""
اسکریپت تست جامع مدیریت تیم (/team) و تعلیق زمان‌دار (/suspension و /unsuspend).

موارد بررسی:
۱. مدل کاربر و ستون‌های جدید: is_admin, is_owner, suspended_until, suspension_reason
۲. کش پویا در bot/config.py و یکپارچگی با Settings.is_admin و Settings.is_owner
۳. ریپازیتوری کاربران (users_repo):
   - تابع هوشمند get_user_by_username_or_id با آیدی، یوزرنیم با و بدون @
   - ثبت پیشاپیش کاربر با آیدی عددی
   - تنظیم و خلع ادمین و مالک در دیتابیس
   - تعلیق زمان‌دار (۶، ۱۲، ۲۴، ۴۸ ساعت) و لغو آن
   - دریافت کاربران معلق منقضی‌شده
۴. میدلور کاربر (UserMiddleware):
   - ممانعت از فعالیت کاربر معلق و محاسبه زمان باقی‌مانده به ساعت و دقیقه
   - رفع تعلیق خودکار در صورت اتمام زمان (now >= suspended_until)
   - رفع تعلیق خودکار در صورت نداشتن کشور
۵. گاردها و محافظت‌های امنیتی:
   - عدم امکان خلع مالک اصلی (.env) توسط هیچ‌کس
   - عدم امکان خلع مالک توسط ادمین عادی
   - عدم امکان خلع خود مدیر توسط خودش
   - عدم امکان تعلیق ادمین یا مالک ربات
۶. جاب زمان‌بند process_timed_suspensions:
   - رفع تعلیق کاربران منقضی‌شده و ارسال پیام خصوصی پایان تعلیق
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import (
    add_dynamic_admin,
    add_dynamic_owner,
    get_dynamic_admins,
    get_dynamic_owners,
    get_settings,
    remove_dynamic_admin,
    remove_dynamic_owner,
    set_dynamic_team,
)
from bot.database.base import Base, _apply_column_migrations
from bot.database.models import Country, User
from bot.database.repositories import users as users_repo
from bot.enums import UserRole
from bot.handlers.suspension import _apply_suspension, _execute_unsuspend
from bot.handlers.team import _execute_remove_admin, _execute_remove_owner
from bot.middlewares.user import UserMiddleware
from bot.scheduler.jobs import process_timed_suspensions


from aiogram.types import Message


def create_mock_message(text: str = ""):
    msg = MagicMock(spec=Message)
    msg.text = text
    msg.answer = AsyncMock()
    return msg


class DummyTgUser:
    def __init__(self, uid: int, username: str | None = None, first_name: str = "Test"):
        self.id = uid
        self.username = username
        self.first_name = first_name


total_checks = 0
passed_checks = 0


def assert_check(condition: bool, msg: str):
    global total_checks, passed_checks
    total_checks += 1
    if condition:
        passed_checks += 1
        print(f"  [PASS] {msg}")
    else:
        print(f"  [FAIL] {msg}")
        raise AssertionError(f"Check failed: {msg}")


async def run_all_tests():
    print("=" * 65)
    print("   شروع تست‌های جامع مدیریت تیم و تعلیق زمان‌دار")
    print("=" * 65)

    settings = get_settings()

    # ایجاد دیتابیس تستی SQLite درون حافظه
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_apply_column_migrations)

    print("\n--- بخش ۱: تست کش پویا و Settings ---")
    assert_check(settings.is_static_owner(111), "111 مالک استاتیک است")
    assert_check(not settings.is_static_owner(222), "222 مالک استاتیک نیست")
    assert_check(settings.is_owner(111), "111 مالک است")
    assert_check(settings.is_admin(111), "111 مدیر است (مالک = مدیر)")
    assert_check(settings.is_admin(222), "222 مدیر استاتیک است")
    assert_check(not settings.is_owner(222), "222 مالک نیست")
    assert_check(not settings.is_admin(333), "333 در ابتدا مدیر نیست")

    # افزودن و حذف ادمین پویا
    add_dynamic_admin(333)
    assert_check(settings.is_admin(333), "333 پس از add_dynamic_admin مدیر شناخته می‌شود")
    assert_check(not settings.is_owner(333), "333 مالک نشده است")
    remove_dynamic_admin(333)
    assert_check(not settings.is_admin(333), "333 پس از remove_dynamic_admin دیگر مدیر نیست")

    # افزودن و حذف مالک پویا
    add_dynamic_owner(444)
    assert_check(settings.is_owner(444), "444 مالک پویا است")
    assert_check(settings.is_admin(444), "444 به عنوان مالک خودکار مدیر نیز هست")
    assert_check(not settings.is_static_owner(444), "444 مالک استاتیک نیست (پویا است)")
    remove_dynamic_owner(444)
    assert_check(not settings.is_owner(444), "444 خلع شد")

    # بازنشانی گروهی تیم
    set_dynamic_team([501, 502], [601])
    assert_check(501 in get_dynamic_admins() and 502 in get_dynamic_admins(), "ادمین‌های پویا ثبت شدند")
    assert_check(601 in get_dynamic_owners(), "مالک پویا ثبت شد")
    assert_check(settings.is_admin(501) and settings.is_owner(601), "دسترسی‌ها در settings فعال هستند")
    set_dynamic_team([], [])  # ریست برای تست‌های بعدی

    print("\n--- بخش ۲: تست ریپازیتوری کاربران ---")
    async with session_factory() as session:
        # ایجاد کاربران آزمایشی
        u1 = await users_repo.get_or_create_user(session, 1001, "player_one", "Player 1")
        u2 = await users_repo.get_or_create_user(session, 1002, "player_two", "Player 2")
        await session.commit()

        # تست جستجوی کاربر
        found_u, uid, err = await users_repo.get_user_by_username_or_id(session, 1001)
        assert_check(found_u is not None and uid == 1001 and err is None, "یافتن با int id")

        found_u, uid, err = await users_repo.get_user_by_username_or_id(session, "1002")
        assert_check(found_u is not None and uid == 1002 and err is None, "یافتن با str id")

        found_u, uid, err = await users_repo.get_user_by_username_or_id(session, "@player_one")
        assert_check(found_u is not None and uid == 1001 and err is None, "یافتن با @username")

        found_u, uid, err = await users_repo.get_user_by_username_or_id(session, "PLAYER_TWO")
        assert_check(found_u is not None and uid == 1002 and err is None, "یافتن بدون @ حروف بزرگ/کوچک")

        # آیدی عددی که هنوز در دیتابیس نیست (preemptive registration)
        found_u, uid, err = await users_repo.get_user_by_username_or_id(session, "999999")
        assert_check(found_u is None and uid == 999999 and err is None, "آیدی عددی ناشناس آماده ثبت پیشاپیش")

        # یوزرنیم ناموجود
        found_u, uid, err = await users_repo.get_user_by_username_or_id(session, "@non_existent_ghost")
        assert_check(found_u is None and uid is None and err is not None, "یوزرنیم ناموجود پیام خطا می‌دهد")

        # انتصاب ادمین و مالک در DB
        await users_repo.set_user_admin(session, 1001, True)
        await users_repo.set_user_owner(session, 1002, True)
        await session.commit()

        admins, owners = await users_repo.list_team_members(session)
        assert_check(any(u.telegram_id == 1001 for u in admins), "1001 در لیست ادمین‌های دیتابیس است")
        assert_check(any(u.telegram_id == 1002 for u in owners), "1002 در لیست مالکان دیتابیس است")
        assert_check(any(u.telegram_id == 1002 for u in admins), "مالک 1002 به عنوان ادمین هم در دیتابیس است")

    print("\n--- بخش ۳: تست تعلیق زمان‌دار در ریپازیتوری ---")
    async with session_factory() as session:
        target_uid = 2001
        u = await users_repo.get_or_create_user(session, target_uid, "suspended_target", "Target")
        await session.commit()

        # تعلیق ۱۲ ساعته
        user_res, until = await users_repo.set_timed_suspension(
            session, target_uid, duration_hours=12, reason="تست قوانین"
        )
        await session.commit()
        assert_check(user_res.is_suspended is True, "وضعیت کاربر معلق شد")
        assert_check(user_res.suspension_reason == "تست قوانین", "علت تعلیق ثبت شد")
        assert_check(user_res.suspended_until is not None, "تاریخ پایان تعلیق ثبت شد")
        remaining_hours = (until - datetime.now(timezone.utc)).total_seconds() / 3600
        assert_check(11.9 <= remaining_hours <= 12.1, "مدت زمان دقیقاً ۱۲ ساعت تنظیم شده است")

        # بررسی لیست معلق‌ها
        all_suspended = await users_repo.list_suspended_users(session)
        assert_check(any(u.telegram_id == target_uid for u in all_suspended), "کاربر در لیست معلق‌ها وجود دارد")

        # کاربر منقضی نشده هنوز
        now_dt = datetime.now(timezone.utc)
        expired = await users_repo.get_expired_suspended_users(session, now_dt)
        assert_check(not any(u.telegram_id == target_uid for u in expired), "کاربر هنوز منقضی نشده است")

        # کاربر منقضی‌شده در آینده
        future_dt = now_dt + timedelta(hours=13)
        expired_future = await users_repo.get_expired_suspended_users(session, future_dt)
        assert_check(any(u.telegram_id == target_uid for u in expired_future), "در ۱۳ ساعت آینده منقضی محسوب می‌شود")

        # لغو دستی تعلیق
        await users_repo.lift_suspension(session, target_uid)
        await session.commit()
        u_lifted = await users_repo.get_user(session, target_uid)
        assert_check(u_lifted.is_suspended is False, "تعلیق لغو شد")
        assert_check(u_lifted.suspended_until is None, "تاریخ تعلیق پاک شد")
        assert_check(u_lifted.suspension_reason is None, "علت تعلیق پاک شد")

    print("\n--- بخش ۴: تست رفتارهای UserMiddleware و رفع تعلیق خودکار ---")
    async with session_factory() as session:
        # ساخت کشوری برای کاربر تستی تا کشوردار باشد
        mid_user_id = 3001
        await users_repo.get_or_create_user(session, mid_user_id, "mid_player", "Mid Player")
        country = Country(
            id=10,
            name_en="Iran",
            name_fa="ایران",
            flag="🇮🇷",
            region="middle_east",
            owner_user_id=mid_user_id,
        )
        session.add(country)
        await session.commit()

        # اعمال تعلیق ۶ ساعته
        await users_repo.set_timed_suspension(session, mid_user_id, 6, "رفتار مشکوک")
        await session.commit()

        middleware = UserMiddleware()
        dummy_msg = create_mock_message("/profile")
        dummy_tg_user = DummyTgUser(mid_user_id, "mid_player", "Mid Player")
        data = {"session": session, "event_from_user": dummy_tg_user}

        handler_called = False
        async def dummy_handler(event, data):
            nonlocal handler_called
            handler_called = True
            return "OK"

        # اجرای میدلور: باید بلاک کند و زمان باقی‌مانده و دلیل را پاسخ دهد
        res = await middleware(dummy_handler, dummy_msg, data)
        assert_check(res is None and not handler_called, "میدلور کاربر معلق فعال را مسدود کرد")
        assert_check(dummy_msg.answer.called, "پیام تعلیق برای کاربر ارسال شد")
        answer_text = dummy_msg.answer.call_args[0][0]
        assert_check("رفتار مشکوک" in answer_text, "علت تعلیق در پیام میدلور ذکر شد")
        assert_check("ساعت" in answer_text, "ساعت باقی‌مانده ذکر شد")

        # حالا شبیه‌سازی پایان زمان تعلیق: تنظیم suspended_until به ۱۰ دقیقه قبل
        past_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        u_mid = await users_repo.get_user(session, mid_user_id)
        u_mid.suspended_until = past_time
        await session.commit()

        # اجرای مجدد میدلور: باید خودکار تعلیق را بردارد و هندلر را صدا بزند
        handler_called = False
        dummy_msg.answer.reset_mock()
        res = await middleware(dummy_handler, dummy_msg, data)
        assert_check(handler_called, "با اتمام زمان تعلیق، میدلور خودکار قفل را باز کرد و اجازه داد")
        assert_check(u_mid.is_suspended is False, "در دیتابیس هم is_suspended برابر False شد")
        assert_check(u_mid.suspended_until is None, "suspended_until پاک شد")

    print("\n--- بخش ۵: تست گاردها و محافظت‌های امنیتی ---")
    async with session_factory() as session:
        caller_owner_id = 111  # مالک استاتیک
        caller_admin_id = 222  # ادمین استاتیک

        # تست ۱: عدم امکان خلع مالک اصلی (111) توسط هر کس
        ok, err = await _execute_remove_admin(session, caller_admin_id, "Admin", 111)
        assert_check(not ok and "امکان خلع مالک اصلی" in err, "ادمین نمی‌تواند مالک اصلی را خلع کند")

        ok, err = await _execute_remove_owner(session, caller_owner_id, "Owner", 111)
        assert_check(not ok and "مالک اصلی سیستم" in err, "حتی خود مالک هم نمی‌تواند مالک اصلی کانفیگ را خلع کند")

        # تست ۲: عدم امکان خلع خود
        ok, err = await _execute_remove_admin(session, caller_admin_id, "Admin", caller_admin_id)
        assert_check(not ok and "نمی‌توانید دسترسی خودتان را سلب کنید" in err, "عدم امکان خلع خود")

        # تست ۳: ادمین عادی نمی‌تواند مالک را عزل کند
        # ایجاد یک مالک پویا
        dyn_owner_id = 4001
        await users_repo.get_or_create_user(session, dyn_owner_id, "dyn_owner", "Dyn Owner")
        await users_repo.set_user_owner(session, dyn_owner_id, True)
        add_dynamic_owner(dyn_owner_id)
        await session.commit()

        ok, err = await _execute_remove_admin(session, caller_admin_id, "Admin", dyn_owner_id)
        assert_check(not ok and "فقط مالکان ربات می‌توانند" in err, "ادمین نمی‌تواند مالک پویا را عزل کند")

        # تست ۴: خلع مالک پویا توسط مالک اصلی
        with patch("bot.handlers.team.send_log", new=AsyncMock()), \
             patch("bot.handlers.team.bot.send_message", new=AsyncMock()):
            ok, msg = await _execute_remove_owner(session, caller_owner_id, "MainOwner", dyn_owner_id)
            assert_check(ok and "خلع شد" in msg, "مالک اصلی توانست مالک پویا را خلع کند")
            assert_check(dyn_owner_id not in get_dynamic_owners(), "مالک پویا از کش حذف شد")
            u_check = await users_repo.get_user(session, dyn_owner_id)
            assert_check(not u_check.is_owner and not u_check.is_admin, "در دیتابیس هم خلع شد")

        # تست ۵: عدم امکان تعلیق ادمین یا مالک
        ok, err = await _apply_suspension(session, caller_admin_id, "Admin", 111, 6, "تست")
        assert_check(not ok and "امکان تعلیق ادمین یا مالک" in err, "امکان تعلیق مالک وجود ندارد")

        ok, err = await _apply_suspension(session, caller_admin_id, "Admin", 222, 12, "تست")
        assert_check(not ok and "امکان تعلیق ادمین یا مالک" in err, "امکان تعلیق ادمین وجود ندارد")

        # تست ۶: تعلیق و رفع تعلیق موفق بازیکن عادی
        regular_id = 5001
        await users_repo.get_or_create_user(session, regular_id, "regular_p", "Regular")
        await session.commit()

        with patch("bot.handlers.suspension.send_log", new=AsyncMock()), \
             patch("bot.handlers.suspension.bot.send_message", new=AsyncMock()):
            ok, msg = await _apply_suspension(session, caller_admin_id, "Admin", regular_id, 24, "تخلف")
            assert_check(ok and "معلق شد" in msg, "تعلیق ۲۴ ساعته بازیکن عادی انجام شد")
            u_reg = await users_repo.get_user(session, regular_id)
            assert_check(u_reg.is_suspended is True and u_reg.suspension_reason == "تخلف", "اطلاعات در دیتابیس ثبت شد")

            ok, msg = await _execute_unsuspend(session, caller_admin_id, "Admin", regular_id)
            assert_check(ok and "لغو شد" in msg, "رفع تعلیق موفق بازیکن عادی")
            u_reg_after = await users_repo.get_user(session, regular_id)
            assert_check(u_reg_after.is_suspended is False, "تعلیق بازیکن برداشته شد")

    print("\n--- بخش ۶: تست زمان‌بند process_timed_suspensions ---")
    async with session_factory() as session:
        sched_user_id = 6001
        u_sched = await users_repo.get_or_create_user(session, sched_user_id, "sched_user", "Sched")
        # تنظیم زمان تعلیق به ۳۰ ثانیه قبل (منقضی شده)
        u_sched.is_suspended = True
        u_sched.suspended_until = datetime.now(timezone.utc) - timedelta(seconds=30)
        u_sched.suspension_reason = "تست زمان‌بند"
        await session.commit()

    mock_bot = AsyncMock()
    # جاب را با mock session factory تست می‌کنیم
    with patch("bot.scheduler.jobs.async_session_factory", session_factory):
        await process_timed_suspensions(mock_bot)

    async with session_factory() as session:
        u_sched_after = await users_repo.get_user(session, sched_user_id)
        assert_check(u_sched_after.is_suspended is False, "جاب زمان‌بند تعلیق منقضی را لغو کرد")
        assert_check(u_sched_after.suspended_until is None, "suspended_until توسط جاب پاک شد")
        assert_check(mock_bot.send_message.called, "پیام خصوصی پایان تعلیق برای بازیکن ارسال شد")
        first_call_args = mock_bot.send_message.call_args[0]
        assert_check(first_call_args[0] == sched_user_id, "گیرنده پیام خود بازیکن بود")
        assert_check("پایان دوره تعلیق" in first_call_args[1], "متن پیام پایان تعلیق صحیح است")

    await engine.dispose()

    print("\n" + "=" * 65)
    print(f"🎉 تمام {passed_checks} از {total_checks} بررسی با موفقیت کامل پاس شدند! ✅")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
