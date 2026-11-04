"""
تست جامع ریپلای ادمین در گروه لاگ به گفتگوهای نشست (v2.12.0):
۱. ثبت نگاشت MeetingLogRelay هنگام ارسال پیام به گروه لاگ.
۲. ریپلای ادمین روی پیام دیدار دوجانبه → ارسال برای هر دو کشور.
۳. ریپلای ادمین روی پیام نشست چندجانبه → ارسال برای میزبان و تمام کشورهای حاضر.
۴. قالب‌بندی دقیق پیام و پالایش امن کاراکترهای HTML (html.escape).
۵. نادیده گرفتن بی‌صدای ریپلای روی پیام‌های نامربوط (بدون نگاشت).
۶. مدیریت نشست‌های پایان‌یافته و در حال پرواز.
۷. عدم پذیرش ریپلای از کاربران غیرادمین.
۸. مدیریت خطای بلاک بودن یک گیرنده و ارسال گزارش جزئی به ادمین.
۹. عدم تمدید last_msg_at با پیام ادمین.
۱۰. عملکرد سرخط _reply_prefix هنگام ریپلای بازیکن به پیام ادمین در پیوی.
۱۱. پاک‌سازی نگاشت‌های منقضی‌شده و تست ریست فصل.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# متغیرهای محیطی آزمایشی
os.environ["BOT_TOKEN"] = "123456:TEST_ADMIN_REPLY"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GROQ_API_KEY"] = "gsk_test"
os.environ["OWNER_IDS"] = "[111]"
os.environ["ADMIN_IDS"] = "[111, 222]"
os.environ["LOG_GROUP_ID"] = "-100111222333"
os.environ["PYTHONUTF8"] = "1"

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import get_settings
from bot.database.base import Base
from bot.database.models import (
    Country,
    GroupMeeting,
    GroupMeetingParticipant,
    Meeting,
    MeetingLogRelay,
    User,
)
from bot.database.repositories import diplomacy as dip_repo
from bot.enums import DiplomacyStatus
from bot.handlers.admin_meeting_reply import on_admin_meeting_log_reply
from bot.handlers.diplomacy import _reply_prefix
from bot.services.season_service import reset_season

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


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def run_tests() -> None:
    print("\n🔍 شروع تست‌های سیستم ریپلای ادمین به نشست‌ها (v2.12.0)...")

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    now = _utcnow()

    async with session_factory() as session:
        # ساخت کاربران و کشورهای پایه برای تست
        user_iran = User(telegram_id=1001, username="leader_iran", first_name="Iran Leader")
        user_turkey = User(telegram_id=1002, username="leader_turkey", first_name="Turkey Leader")
        user_germany = User(telegram_id=1003, username="leader_germany", first_name="Germany Host")
        user_france = User(telegram_id=1004, username="leader_france", first_name="France Leader")
        user_admin = User(telegram_id=222, username="admin_arash", first_name="Admin Arash")
        session.add_all([user_iran, user_turkey, user_germany, user_france, user_admin])
        await session.flush()

        country_iran = Country(id=1, name_en="Iran", name_fa="ایران", flag="🇮🇷", region="middle_east", owner_user_id=1001)
        country_turkey = Country(id=2, name_en="Turkey", name_fa="ترکیه", flag="🇹🇷", region="middle_east", owner_user_id=1002)
        country_germany = Country(id=3, name_en="Germany", name_fa="آلمان", flag="🇩🇪", region="europe", owner_user_id=1003)
        country_france = Country(id=4, name_en="France", name_fa="فرانسه", flag="🇫🇷", region="europe", owner_user_id=1004)
        session.add_all([country_iran, country_turkey, country_germany, country_france])
        await session.flush()

        # ۱) تست ثبت و دریافت نگاشت MeetingLogRelay
        print("\n[بخش ۱] تست ثبت و واکشی نگاشت MeetingLogRelay")
        relay_bi = await dip_repo.record_meeting_log_relay(
            session=session,
            log_chat_id=-100111222333,
            log_message_id=5001,
            meeting_kind="bilateral",
            meeting_id=10,
            sender_country_id=1,
            sender_user_id=1001,
            preview_text="🇮🇷 ایران: سلام برادر",
        )
        await session.commit()

        fetched = await dip_repo.get_meeting_log_relay(session, -100111222333, 5001)
        check("نگاشت دوجانبه در دیتابیس ثبت شد", fetched is not None)
        check("آی‌دی نشست در نگاشت صحیح است", fetched.meeting_id == 10)
        check("نوع نشست دوجانبه است", fetched.meeting_kind == "bilateral")
        check("فرستنده ایران است", fetched.sender_country_id == 1)

        # ۲) تست نشست دوجانبه فعال و ریپلای ادمین
        print("\n[بخش ۲] ریپلای ادمین روی دیدار دوجانبه")
        bi_meeting = Meeting(
            id=10,
            traveler_country=1,  # ایران مسافر
            host_country=2,      # ترکیه میزبان
            status=DiplomacyStatus.ACTIVE,
            travel_eta=now - timedelta(minutes=10),      # رسیده است
            meeting_ends_at=now + timedelta(minutes=50), # ۵۰ دقیقه مانده
            last_msg_at=now - timedelta(minutes=5),
        )
        session.add(bi_meeting)
        await session.commit()

        mock_bot = AsyncMock()
        mock_bot_user = MagicMock()
        mock_bot_user.id = 99999
        mock_bot_user.is_bot = True
        mock_bot.get_me.return_value = mock_bot_user

        # ساخت آبجکت پیام ریپلای ادمین
        admin_reply_msg = MagicMock()
        admin_reply_msg.chat.id = -100111222333
        admin_reply_msg.from_user.id = 222
        admin_reply_msg.from_user.full_name = "Arash"
        admin_reply_msg.text = "سلام، لطفاً مفاد را روشن‌تر کنید."
        admin_reply_msg.caption = None
        admin_reply_msg.photo = None
        admin_reply_msg.react = AsyncMock()

        replied_msg = MagicMock()
        replied_msg.message_id = 5001
        replied_msg.from_user.id = 99999
        replied_msg.from_user.is_bot = True
        admin_reply_msg.reply_to_message = replied_msg

        initial_last_msg_at = bi_meeting.last_msg_at

        await on_admin_meeting_log_reply(admin_reply_msg, session, mock_bot)

        # بررسی ارسال به هر دو کشور
        check("پیام به ۲ کشور ارسال شد", mock_bot.send_message.call_count == 2)
        sent_targets = [call[0][0] for call in mock_bot.send_message.call_args_list]
        check("پیام به پیوی ایران (1001) ارسال شد", 1001 in sent_targets)
        check("پیام به پیوی ترکیه (1002) ارسال شد", 1002 in sent_targets)

        # بررسی قالب پیام
        sent_body = mock_bot.send_message.call_args_list[0][0][1]
        check("سرخط در پاسخ به در پیام موجود است", "↩️ در پاسخ به «🇮🇷 ایران: سلام برادر»" in sent_body)
        check("نام ادمین در پیام درج شده است", "👮‍♂️ ادمین Arash:" in sent_body)
        check("متن ادمین در پیام درج شده است", "سلام، لطفاً مفاد را روشن‌تر کنید." in sent_body)
        check("واکنش تایید روی پیام ادمین زده شد", admin_reply_msg.react.called)

        # بررسی عدم تمدید last_msg_at نشست با پیام ادمین
        await session.refresh(bi_meeting)
        check(
            "پیام ادمین last_msg_at را تمدید نکرد",
            _aware(bi_meeting.last_msg_at) == _aware(initial_last_msg_at),
            f"current={_aware(bi_meeting.last_msg_at)} vs initial={_aware(initial_last_msg_at)}"
        )

        # ۳) تست نشست چندجانبه فعال
        print("\n[بخش ۳] ریپلای ادمین روی نشست چندجانبه")
        grp_meeting = GroupMeeting(
            id=20,
            host_country=3,      # آلمان میزبان
            title="نشست برلین",
            status=DiplomacyStatus.ACTIVE,
            start_at=now - timedelta(minutes=10),
            meeting_ends_at=now + timedelta(minutes=50),
            last_msg_at=now - timedelta(minutes=3),
        )
        session.add(grp_meeting)
        await session.flush()

        part_france = GroupMeetingParticipant(
            meeting_id=20,
            country_id=4,
            response=DiplomacyStatus.ACTIVE,
        )
        session.add(part_france)
        await session.commit()

        # ثبت نگاشت لاگ نشست چندجانبه
        await dip_repo.record_meeting_log_relay(
            session=session,
            log_chat_id=-100111222333,
            log_message_id=5002,
            meeting_kind="group",
            meeting_id=20,
            sender_country_id=4,
            sender_user_id=1004,
            preview_text="🇫🇷 فرانسه: ما آماده توافق هستیم",
        )
        await session.commit()

        mock_bot.send_message.reset_mock()
        admin_reply_msg.react.reset_mock()
        replied_msg.message_id = 5002
        admin_reply_msg.text = "موافقت دولت‌ها ثبت شد."

        await on_admin_meeting_log_reply(admin_reply_msg, session, mock_bot)

        check("پیام چندجانبه برای میزبان و حاضرین ارسال شد (۲ کشور)", mock_bot.send_message.call_count == 2)
        sent_grp_targets = [call[0][0] for call in mock_bot.send_message.call_args_list]
        check("میزبان آلمان (1003) پیام را دریافت کرد", 1003 in sent_grp_targets)
        check("فرانسه (1004) پیام را دریافت کرد", 1004 in sent_grp_targets)

        # ۴) تست پالایش امن HTML
        print("\n[بخش ۴] بررسی پالایش کاراکترهای خطرناک HTML (html.escape)")
        mock_bot.send_message.reset_mock()
        admin_reply_msg.text = "<script>alert('xss')</script> & <b>تست</b>"
        await on_admin_meeting_log_reply(admin_reply_msg, session, mock_bot)
        escaped_body = mock_bot.send_message.call_args_list[0][0][1]
        check("تگ اسکریپت خنثی شد", "&lt;script&gt;" in escaped_body)
        check("علامت امپرسند خنثی شد", "&amp;" in escaped_body)
        check("تگ b خام در متن کاربر وجود ندارد", "<b>تست</b>" not in escaped_body)

        # ۵) تست ریپلای روی پیام بدون نگاشت (نادیده گرفتن بی‌صدا)
        print("\n[بخش ۵] پیام بدون نگاشت در گروه لاگ")
        mock_bot.send_message.reset_mock()
        admin_reply_msg.reply = AsyncMock()
        replied_msg.message_id = 99999  # شناسه ناموجود
        await on_admin_meeting_log_reply(admin_reply_msg, session, mock_bot)
        check("روی پیام بدون نگاشت ارسالی به کشورها انجام نشد", mock_bot.send_message.call_count == 0)
        check("به ادمین پاسخی داده نشد (بیصدا رد شد)", not admin_reply_msg.reply.called)

        # ۶) تست نشست پایان‌یافته
        print("\n[بخش ۶] ریپلای روی نشست پایان‌یافته")
        bi_meeting.status = DiplomacyStatus.COMPLETED
        await session.commit()
        replied_msg.message_id = 5001

        await on_admin_meeting_log_reply(admin_reply_msg, session, mock_bot)
        check("روی نشست پایان‌یافته به حاضران پیام نرفت", mock_bot.send_message.call_count == 0)
        check("به ادمین اعلام شد نشست پایان یافته است", admin_reply_msg.reply.called)
        check("متن پیام اعلام پایان نشست است", "این نشست پایان یافته است" in admin_reply_msg.reply.call_args[0][0])

        # ۷) تست ریپلای کاربر غیرادمین
        print("\n[بخش ۷] ریپلای کاربر غیرادمین")
        admin_reply_msg.from_user.id = 555  # غیرادمین
        admin_reply_msg.reply.reset_mock()
        mock_bot.send_message.reset_mock()
        await on_admin_meeting_log_reply(admin_reply_msg, session, mock_bot)
        check("ریپلای غیرادمین کاملاً نادیده گرفته شد", not admin_reply_msg.reply.called and not mock_bot.send_message.called)
        admin_reply_msg.from_user.id = 222  # برگرداندن به ادمین

        # ۸) تست شکست ارسال برای یک گیرنده و گزارش جزئی
        print("\n[بخش ۸] شکست ارسال برای یک کشور و گزارش جزئی به ادمین")
        bi_meeting.status = DiplomacyStatus.ACTIVE
        await session.commit()
        replied_msg.message_id = 5001
        admin_reply_msg.reply.reset_mock()

        # ارسال به ترکیه پرتاب خطا کند
        async def mock_send_with_error(chat_id, text, **kwargs):
            if chat_id == 1002:
                raise Exception("Bot was blocked by user")
            return MagicMock()

        mock_bot.send_message.side_effect = mock_send_with_error
        await on_admin_meeting_log_reply(admin_reply_msg, session, mock_bot)

        check("در صورت خطای یک گیرنده، گزارش جزئی به ادمین آمد", admin_reply_msg.reply.called)
        report_text = admin_reply_msg.reply.call_args[0][0]
        check("نام کشور ناموفق در گزارش هست", "ترکیه" in report_text)
        mock_bot.send_message.side_effect = None

        # ۹) تست _reply_prefix هنگام ریپلای بازیکن به پیام ادمین
        print("\n[بخش ۹] تست سرخط _reply_prefix روی پیام ادمین")
        player_msg_to_admin = MagicMock()
        mock_admin_msg = MagicMock()
        mock_admin_msg.text = (
            "↩️ در پاسخ به «🇮🇷 ایران: سلام برادر»\n"
            "👮‍♂️ ادمین Arash: لطفاً بند شماره دو را اصلاح کنید."
        )
        mock_admin_msg.caption = None
        player_msg_to_admin.reply_to_message = mock_admin_msg

        prefix = _reply_prefix(player_msg_to_admin)
        check("سرخط اختصاصی ادمین تولید شد", "↩️ در پاسخ به «👮‍♂️ ادمین Arash: لطفاً بند شماره دو را اصلاح کنید.»:\n" == prefix)

        # ۱۰) تست پاکسازی نگاشت‌ها و ریست فصل
        print("\n[بخش ۱۰] پاکسازی رکوردهای منقضی و ریست فصل")
        # افزودن یک رکورد قدیمی‌تر از ۴۸ ساعت
        old_relay = MeetingLogRelay(
            log_chat_id=-100111222333,
            log_message_id=4001,
            meeting_kind="bilateral",
            meeting_id=1,
            created_at=now - timedelta(hours=50),
        )
        session.add(old_relay)
        await session.commit()

        deleted_count = await dip_repo.cleanup_meeting_log_relays(session, max_age_hours=48)
        check("رکورد قدیمی‌تر از ۴۸ ساعت پاک شد", deleted_count == 1)

        # تست ریست فصل
        try:
            await reset_season(session)
            check("ریست فصل بدون خطای Foreign Key اجرا شد", True)
            remaining_relays = (await session.execute(select(MeetingLogRelay))).scalars().all()
            check("تمامی نگاشت‌های لاگ در ریست فصل پاکسازی شدند", len(remaining_relays) == 0)
        except Exception as exc:
            check("ریست فصل بدون خطای Foreign Key اجرا شد", False, str(exc))

    print("\n" + "=" * 50)
    print(f"📊 نتیجه نهایی تست‌ها: {_passed} تست موفق، {len(_failed)} خطا.")
    if _failed:
        print("❌ موارد شکست‌خورده:")
        for f in _failed:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("🎉 تمامی تست‌های سیستم ریپلای ادمین با موفقیت پاس شدند.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(run_tests())
