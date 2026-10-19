"""
تست جامع آپدیت:
۱. سیستم جوین اجباری کانال در استارت و میدلور + دستور /setchannel
۲. اصلاح پیام تأیید کشورگیری عادی و VIP + کامند /folder و /setfolder
۳. سیستم ارسال پیام همگانی متنی/تصویری به کل کاربران (users_repo.list_all_user_telegram_ids)
۴. پایداری ستون‌ها و حفظ در ریست فصل
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# متغیرهای محیطی آزمایشی
os.environ["BOT_TOKEN"] = "123456:TEST_TOKEN_ONLY"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GROQ_API_KEY"] = "gsk_test"
os.environ["OWNER_IDS"] = "[111]"
os.environ["ADMIN_IDS"] = "[111, 222]"
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
from bot.database.base import Base, _COLUMN_MIGRATIONS
from bot.database.models import BotState, Country, User
from bot.database.repositories import bot_state as bot_state_repo
from bot.database.repositories import users as users_repo
from bot.enums import UserRole
from bot.middlewares.user import UserMiddleware
from bot.services.channel_service import (
    FORCE_JOIN_TEXT,
    check_user_channel_subscription,
    force_join_kb,
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


async def run_tests() -> None:
    print("\n🚀 آغاز آزمون‌های سیستم جوین اجباری، لینک فولدر و پیام همگانی...\n")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        # ============================================================
        # بخش ۱: بررسی ستون‌ها و مدل دیتابیس
        # ============================================================
        print("🔹 ۱. بررسی ستون‌های مهاجرت و مدل BotState:")
        mig_cols = {(table, col) for table, col, _ in _COLUMN_MIGRATIONS}
        check(
            "مهاجرت force_join_enabled در _COLUMN_MIGRATIONS",
            ("bot_state", "force_join_enabled") in mig_cols,
        )
        check(
            "مهاجرت force_join_chat_id در _COLUMN_MIGRATIONS",
            ("bot_state", "force_join_chat_id") in mig_cols,
        )
        check(
            "مهاجرت force_join_invite_link در _COLUMN_MIGRATIONS",
            ("bot_state", "force_join_invite_link") in mig_cols,
        )
        check(
            "مهاجرت game_folder_link در _COLUMN_MIGRATIONS",
            ("bot_state", "game_folder_link") in mig_cols,
        )

        bstate = await bot_state_repo.get_state(session)
        check("وجود فیلد force_join_enabled در BotState", hasattr(bstate, "force_join_enabled"))
        check("مقدار اولیه force_join_enabled برابر False", bstate.force_join_enabled is False)
        check("وجود فیلد force_join_chat_id در BotState", hasattr(bstate, "force_join_chat_id"))
        check("وجود فیلد force_join_invite_link در BotState", hasattr(bstate, "force_join_invite_link"))
        check("وجود فیلد game_folder_link در BotState", hasattr(bstate, "game_folder_link"))

        # تست به‌روزرسانی ستون‌های تنظیمات
        await bot_state_repo.update_state(
            session,
            force_join_enabled=True,
            force_join_chat_id="-1001234567890",
            force_join_invite_link="https://t.me/+testinvite",
            game_folder_link="https://t.me/addlist/testfolder",
        )
        await session.commit()

        bstate2 = await bot_state_repo.get_state(session)
        check("ذخیره و بازیابی force_join_enabled", bstate2.force_join_enabled is True)
        check("ذخیره و بازیابی force_join_chat_id", bstate2.force_join_chat_id == "-1001234567890")
        check("ذخیره و بازیابی force_join_invite_link", bstate2.force_join_invite_link == "https://t.me/+testinvite")
        check("ذخیره و بازیابی game_folder_link", bstate2.game_folder_link == "https://t.me/addlist/testfolder")

        # ============================================================
        # بخش ۲: تست سرویس بررسی عضویت در کانال
        # ============================================================
        print("\n🔹 ۲. تست سرویس بررسی عضویت در کانال:")
        mock_bot = MagicMock()

        # حالت عضو بودن
        mock_member = MagicMock()
        mock_member.status = "member"
        mock_bot.get_chat_member = AsyncMock(return_value=mock_member)

        sub_ok = await check_user_channel_subscription(mock_bot, "-1001234567890", 12345)
        check("تشخیص عضو رسمی (member)", sub_ok is True)

        # حالت ادمین بودن
        mock_member.status = "administrator"
        sub_admin = await check_user_channel_subscription(mock_bot, "-1001234567890", 12345)
        check("تشخیص مدیر کانال (administrator)", sub_admin is True)

        # حالت مالک کانال بودن
        mock_member.status = "creator"
        sub_creator = await check_user_channel_subscription(mock_bot, "-1001234567890", 12345)
        check("تشخیص سازنده کانال (creator)", sub_creator is True)

        # حالت خارج شده یا غیرعضو
        mock_member.status = "left"
        sub_left = await check_user_channel_subscription(mock_bot, "-1001234567890", 12345)
        check("تشخیص غیرعضو (left)", sub_left is False)

        # حالت بروز خطا (مانند بلاک یا پیدا نشدن کانال)
        mock_bot.get_chat_member = AsyncMock(side_effect=Exception("Chat not found"))
        sub_err = await check_user_channel_subscription(mock_bot, "-1001234567890", 12345)
        check("مدیریت امن استثنا در بررسی عضویت", sub_err is False)

        # بررسی ساختار کیبورد جوین اجباری
        kb = force_join_kb("https://t.me/+testinvite")
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        url_btns = [b for b in buttons if b.url == "https://t.me/+testinvite"]
        cb_btns = [b for b in buttons if b.callback_data == "check_force_join"]
        check("دکمه لینک ورود به کانال با URL صحیح", len(url_btns) == 1)
        check("دکمه «عضو شدم» با کال‌بک check_force_join", len(cb_btns) == 1)

        # ============================================================
        # بخش ۳: تست میدلور UserMiddleware و مسدودسازی غیرعضو
        # ============================================================
        print("\n🔹 ۳. تست میدلور UserMiddleware و فیلتر جوین اجباری:")
        middleware = UserMiddleware()
        next_handler = AsyncMock(return_value="PASSED")

        # ساخت رویداد پیام تستی از کاربر عادی
        regular_tg_user = MagicMock(id=999001, username="player_one", first_name="Player")
        mock_chat = MagicMock(type="private")
        mock_msg = MagicMock(chat=mock_chat, from_user=regular_tg_user)
        mock_msg.answer = AsyncMock()

        data_ctx = {"session": session, "event_from_user": regular_tg_user}

        # با ماک کردن bot در loader
        with patch("bot.loader.bot.get_chat_member", new_callable=AsyncMock) as mocked_get_member:
            # ۱. وقتی کاربر عضو نیست
            mock_member_left = MagicMock(status="left")
            mocked_get_member.return_value = mock_member_left

            res = await middleware(next_handler, mock_msg, data_ctx)
            check("مسدود شدن کاربر غیرعضو در میدلور", res is None)
            check("فراخوانی نشدن هندلر بعدی برای غیرعضو", next_handler.call_count == 0)
            mock_msg.answer.assert_called_once()
            args, kwargs = mock_msg.answer.call_args
            check("ارسال متن عضویت اجباری به کاربر", FORCE_JOIN_TEXT in args[0])

            # ۲. کاربر در جدول users ثبت شده باشد (حتی اگر غیرعضو باشد!)
            saved_u = await users_repo.get_user(session, 999001)
            check("ثبت کاربر در دیتابیس users حتی در صورت بلاک جوین اجباری", saved_u is not None)

            # ۳. وقتی کاربر عضو می‌شود
            next_handler.reset_mock()
            mock_msg.answer.reset_mock()
            mock_member_ok = MagicMock(status="member")
            mocked_get_member.return_value = mock_member_ok

            res_ok = await middleware(next_handler, mock_msg, data_ctx)
            check("عبور کاربر پس از عضویت در کانال", res_ok == "PASSED")
            check("فراخوانی هندلر بعدی برای کاربر عضو", next_handler.call_count == 1)

            # ۴. بایپس شدن میدلور برای ادمین/مالک
            admin_tg_user = MagicMock(id=111, username="admin_boss", first_name="Admin")
            admin_msg = MagicMock(chat=mock_chat, from_user=admin_tg_user)
            admin_ctx = {"session": session, "event_from_user": admin_tg_user}
            next_handler.reset_mock()

            # حتی اگر وضعیت ادمین در کانال left باشد
            mocked_get_member.return_value = mock_member_left
            res_admin = await middleware(next_handler, admin_msg, admin_ctx)
            check("بایپس کامل جوین اجباری برای ادمین/مالک ربات", res_admin == "PASSED")

            # ۵. اجازه عبور کال‌بک check_force_join به هندلر
            next_handler.reset_mock()
            mock_cb = MagicMock(data="check_force_join", from_user=regular_tg_user)
            mock_cb.message = MagicMock(chat=mock_chat)
            cb_ctx = {"session": session, "event_from_user": regular_tg_user}
            res_cb = await middleware(next_handler, mock_cb, cb_ctx)
            check("اجازه عبور کال‌بک check_force_join از میدلور به هندلر", res_cb == "PASSED")

        # ============================================================
        # بخش ۴: تست کال‌بک check_force_join در handlers/start.py
        # ============================================================
        print("\n🔹 ۴. تست عملکرد هندلر دکمه «عضو شدم» (check_force_join):")
        from bot.handlers.start import cb_check_force_join

        call_mock = MagicMock(from_user=regular_tg_user)
        call_mock.answer = AsyncMock()
        call_mock.message = MagicMock()
        call_mock.message.delete = AsyncMock()
        call_mock.message.answer = AsyncMock()

        with patch("bot.loader.bot.get_chat_member", new_callable=AsyncMock) as mocked_get_member:
            # الف) اگر هنوز عضو نشده باشد: پاپ‌آپ هشدار
            mocked_get_member.return_value = MagicMock(status="left")
            await cb_check_force_join(call_mock, session, saved_u)
            call_mock.answer.assert_called_with(
                "❌ شما هنوز در کانال عضو نشده‌اید! لطفاً ابتدا وارد کانال شوید و سپس دوباره امتحان کنید.",
                show_alert=True,
            )

            # ب) اگر عضو شده باشد: تایید و باز شدن استارت
            call_mock.answer.reset_mock()
            mocked_get_member.return_value = MagicMock(status="member")
            await cb_check_force_join(call_mock, session, saved_u)
            check("تایید عضویت در پاپ‌آپ", "تأیید شد" in call_mock.answer.call_args[0][0])
            call_mock.message.delete.assert_called_once()
            call_mock.message.answer.assert_called_once()
            start_reply = call_mock.message.answer.call_args[0][0]
            check("نمایش متن آغازین و کشورگیری پس از تایید عضویت", "به بازی کره زمین خوش آمدید" in start_reply)

        # ============================================================
        # بخش ۵: تست کامند /folder و پیام تایید کشورگیری
        # ============================================================
        print("\n🔹 ۵. تست کامند /folder و متن جدید تأیید کشورگیری:")
        from bot.handlers.start import cmd_folder

        folder_msg = MagicMock(from_user=regular_tg_user)
        folder_msg.answer = AsyncMock()

        # اجرای /folder
        await cmd_folder(folder_msg, session)
        folder_msg.answer.assert_called_once()
        f_text = folder_msg.answer.call_args[0][0]
        f_kb = folder_msg.answer.call_args[1]["reply_markup"]
        check("نمایش متن فولدر کانال‌های بازی", "فولدر اختصاصی کانال‌های بازی کره زمین" in f_text)
        check("درج لینک مستقیم فولدر در متن", "https://t.me/addlist/testfolder" in f_text)
        check("دکمه شیشه‌ای حاوی لینک فولدر", f_kb.inline_keyboard[0][0].url == "https://t.me/addlist/testfolder")

        # تست پیام تایید کشورگیری در admin.py
        country = Country(
            id=10,
            name_en="Iran",
            name_fa="ایران",
            flag="🇮🇷",
            region="middle_east",
            is_claimed=False,
            is_vip=False,
        )
        session.add(country)
        await session.flush()

        expected_approval_part = (
            f"🎉 <b>کشورگیری شما با موفقیت تایید شد!</b> (کشور: {country.flag} {country.name_fa})\n\n"
            "📁 جهت عضویت در فولدر کانال‌های بازی، دستور /folder را بزنید.\n"
            "🏛 جهت دیدن پنل کشور، دستور /start را بزنید."
        )
        # بررسی سورس هندلرهای cb_approve و cb_vip_claim_approve در admin.py
        admin_src = Path(_ROOT / "bot" / "handlers" / "admin.py").read_text(encoding="utf-8")
        check(
            "متن دقیق تأیید کشورگیری عادی شامل /folder و /start در cb_approve",
            "🎉 <b>کشورگیری شما با موفقیت تایید شد!</b>" in admin_src
            and "📁 جهت عضویت در فولدر کانال‌های بازی، دستور /folder را بزنید." in admin_src
            and "🏛 جهت دیدن پنل کشور، دستور /start را بزنید." in admin_src,
        )

        # ============================================================
        # بخش ۶: تست جامعه هدف کل کاربران (list_all_user_telegram_ids)
        # ============================================================
        print("\n🔹 ۶. تست استخراج تمام کاربران (دارای کشور و بدون کشور):")
        # افزودن چند کاربر در حالت‌های مختلف
        u1 = await users_repo.get_or_create_user(session, 10001, "user1", "U1")  # کاربر بدون کشور
        u2 = await users_repo.get_or_create_user(session, 10002, "user2", "U2")  # کاربر دارای کشور
        u3 = await users_repo.get_or_create_user(session, 10003, "user3", "U3")  # کاربر بن‌شده
        u3.is_banned = True
        u4 = await users_repo.get_or_create_user(session, 10004, "user4", "U4")  # کاربر معلق
        u4.is_suspended = True
        country.owner_user_id = 10002
        country.is_claimed = True
        await session.commit()

        all_ids = await users_repo.list_all_user_telegram_ids(session)
        check("شناسایی کاربر بدون کشور در لیست همگانی", 10001 in all_ids)
        check("شناسایی کاربر دارای کشور در لیست همگانی", 10002 in all_ids)
        check("شناسایی کاربر بن‌شده در لیست همگانی", 10003 in all_ids)
        check("شناسایی کاربر معلق در لیست همگانی", 10004 in all_ids)
        check("شناسایی کاربر اولیه استارت‌کننده", 999001 in all_ids)
        check("مرتب‌بودن شناسه‌ها بر اساس آیدی عددی", all_ids == sorted(all_ids))

        # ============================================================
        # بخش ۷: تست شبیه‌سازی موتور ارسال پیام همگانی (Broadcast)
        # ============================================================
        print("\n🔹 ۷. تست موتور ارسال پیام همگانی متنی و عکس‌دار:")
        from bot.handlers.broadcast import cb_broadcast_confirm

        bcast_call = MagicMock(from_user=admin_tg_user)
        bcast_call.answer = AsyncMock()
        bcast_status_msg = MagicMock()
        bcast_status_msg.edit_text = AsyncMock()
        bcast_call.message = MagicMock()
        bcast_call.message.answer = AsyncMock(return_value=bcast_status_msg)

        state_mock = AsyncMock()
        state_mock.get_data.return_value = {
            "content_type": "photo",
            "photo_file_id": "AgACAgQAAxkBA...",
            "caption": "📢 پیام مهم برای همه بازیکنان کره زمین!",
        }

        # تست ارسال موفق برای اکثر کاربران و شبیه‌سازی خطای بلاک/دیلیت برای یک نفر
        sent_targets: list[int] = []

        async def fake_send_photo(chat_id, photo, caption):
            if chat_id == 10003:  # شبیه‌سازی کاربری که ربات را بلاک کرده
                raise Exception("Forbidden: bot was blocked by the user")
            sent_targets.append(chat_id)

        with patch("bot.loader.bot.send_photo", side_effect=fake_send_photo), \
             patch("bot.loader.bot.send_message", new_callable=AsyncMock), \
             patch("bot.handlers.broadcast.send_to_admin_group", new_callable=AsyncMock) as mock_send_log:

            await cb_broadcast_confirm(bcast_call, state_mock, session)

            check("عدم توقف حلقه ارسال در اثر خطای بلاک کاربر", 10003 not in sent_targets)
            check("ارسال به تمام کاربران فعال جامعه هدف", len(sent_targets) == len(all_ids) - 1)
            bcast_status_msg.edit_text.assert_called_once()
            final_report = bcast_status_msg.edit_text.call_args[0][0]
            check("گزارش تعداد ارسال موفق در پایان", "ارسال موفق" in final_report)
            check("گزارش تعداد ناموفق/بلاک‌شده (۱ نفر)", "ناموفق (بلاک/حذف اکانت)" in final_report and "۱" in final_report)
            mock_send_log.assert_called_once()
            check("ثبت گزارش رسمی ارسال در گروه لاگ اصلی", "گزارش ارسال پیام همگانی" in mock_send_log.call_args[0][2])

        # ============================================================
        # بخش ۸: تست حفظ تنظیمات در ریست فصل (/endseason)
        # ============================================================
        print("\n🔹 ۸. بررسی حفظ تنظیمات جدول bot_state در ریست فصل:")
        from bot.services.season_service import reset_season

        # ریست فصل
        await reset_season(session)

        # استخراج وضعیت bot_state پس از ریست
        bstate_after_reset = await bot_state_repo.get_state(session)
        check("حفظ force_join_enabled پس از ریست فصل", bstate_after_reset.force_join_enabled is True)
        check("حفظ force_join_chat_id پس از ریست فصل", bstate_after_reset.force_join_chat_id == "-1001234567890")
        check("حفظ force_join_invite_link پس از ریست فصل", bstate_after_reset.force_join_invite_link == "https://t.me/+testinvite")
        check("حفظ game_folder_link پس از ریست فصل", bstate_after_reset.game_folder_link == "https://t.me/addlist/testfolder")

    print(f"\n{'='*55}")
    print(f"نتیجه نهایی: {_passed} تست موفق، {len(_failed)} خطا.")
    if _failed:
        print("خطاها:")
        for err in _failed:
            print(f"  - {err}")
        sys.exit(1)
    else:
        print("🎉 تمامی تست‌ها با موفقیت ۱۰۰٪ پاس شدند!")


if __name__ == "__main__":
    asyncio.run(run_tests())
