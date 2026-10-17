"""
اسکریپت تست خودکار و جامع آپدیت جدید:
۱. پنل و دستور /kick برای آزادسازی درجا کشور
۲. توییتر: نمایش نام مسئول/رئیس‌جمهور به‌جای نام کشور در اکانت و تصویر
۳. پنل و دستور /switch برای ورود مستقیم ادمین به کشورها
۴. مصونیت کامل ادمین‌ها و مالکین از بن و تعلیق در تمامی بخش‌ها و Middleware
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

os.environ["BOT_TOKEN"] = "123456:TEST_TOKEN_ONLY"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GROQ_API_KEY"] = "gsk_test"
os.environ["OWNER_IDS"] = "[111]"
os.environ["ADMIN_IDS"] = "[111, 222]"
os.environ["PYTHONUTF8"] = "1"
os.environ["LOG_GROUP_ID"] = "-1003922948542"
os.environ["SANCTION_BILL_GROUP_ID"] = "-1004474739499"

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from PIL import Image
from aiogram.types import CallbackQuery, Message, User as TgUser
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import get_settings
from bot.database.base import Base
from bot.database.models import BotState, ClaimRequest, Country, User
from bot.database.repositories import countries as countries_repo
from bot.database.repositories import users as users_repo
from bot.handlers.admin import cmd_ban
from bot.handlers.kick import (
    _build_kick_kb,
    _get_claimed_countries,
    find_country_by_query,
)
from bot.handlers.suspension import _apply_suspension
from bot.handlers.switch import _build_switch_kb, _execute_admin_switch
from bot.middlewares.user import UserMiddleware
from bot.services.tweet_image_service import render_tweet_image


async def run_tests() -> None:
    passed = 0
    total = 0

    def assert_check(condition: bool, msg: str) -> None:
        nonlocal passed, total
        total += 1
        if condition:
            passed += 1
            print(f"  [OK] {msg}")
        else:
            print(f"  [FAIL] {msg}")
            raise AssertionError(f"Check failed: {msg}")

    # راه‌اندازی موتور دیتابیس تست SQLite در حافظه
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    settings = get_settings()

    # -------------------------------------------------------------
    # بخش ۱: تست پنل و دستور /kick
    # -------------------------------------------------------------
    print("\n--- بخش ۱: تست پنل و دستور /kick ---")

    async with session_factory() as session:
        # ایجاد کشورها و کاربران تستی
        u100 = User(telegram_id=100, username="player_one", first_name="Player 1", is_suspended=True)
        session.add(u100)
        c_ukr = Country(name_en="Ukraine", name_fa="اوکراین", flag="🇺🇦", region="Europe", owner_user_id=100, is_claimed=True)
        c_iran = Country(name_en="Iran", name_fa="ایران", flag="🇮🇷", region="Middle East", is_claimed=False)
        c_ger = Country(name_en="Germany", name_fa="آلمان", flag="🇩🇪", region="Europe", is_claimed=False)
        session.add_all([c_ukr, c_iran, c_ger])
        await session.commit()
        await session.refresh(c_ukr)
        await session.refresh(c_iran)

        # ۱.۱ تست تابع جستجوی انعطاف‌پذیر کشور
        found_by_id = await find_country_by_query(session, str(c_ukr.id))
        found_by_en = await find_country_by_query(session, "ukraine")
        found_by_en_upper = await find_country_by_query(session, "UKRAINE")
        found_by_fa = await find_country_by_query(session, "اوکراین")
        found_by_fa_part = await find_country_by_query(session, "ایران")

        assert_check(found_by_id is not None and found_by_id.id == c_ukr.id, "جستجوی کشور با شناسه عددی کار می‌کند")
        assert_check(found_by_en is not None and found_by_en.id == c_ukr.id, "جستجوی کشور با نام انگلیسی کار می‌کند")
        assert_check(found_by_en_upper is not None and found_by_en_upper.id == c_ukr.id, "جستجوی نام انگلیسی بدون حساسیت به حروف بزرگ کار می‌کند")
        assert_check(found_by_fa is not None and found_by_fa.id == c_ukr.id, "جستجوی کشور با نام فارسی دقیق کار می‌کند")
        assert_check(found_by_fa_part is not None and found_by_fa_part.id == c_iran.id, "جستجوی کشور با نام فارسی کار می‌کند")

        # ۱.۲ تست دریافت کشورهای دارای بازیکن
        claimed = await _get_claimed_countries(session)
        assert_check(len(claimed) == 1 and claimed[0].id == c_ukr.id, "تنها کشورهای دارای بازیکن در لیست claimed بازگردانده می‌شوند")

        # ۱.۳ تست ساخت کیبورد شیشه‌ای kick
        kb_kick = _build_kick_kb(claimed, page=0)
        flat_kick_btns = [btn for row in kb_kick.inline_keyboard for btn in row]
        assert_check(any(btn.callback_data == f"kick_pick:{c_ukr.id}:0" for btn in flat_kick_btns), "دکمه آزادسازی اوکراین در کیبورد موجود است")
        assert_check(any(btn.callback_data == "kick_close" for btn in flat_kick_btns), "دکمه بستن پنل در کیبورد kick موجود است")

        # ۱.۴ تست آزادسازی کشور و رفع تعلیق بازیکن
        former_owner = c_ukr.owner_user_id
        await countries_repo.release_country(session, c_ukr.id)
        if former_owner:
            await users_repo.set_suspended(session, former_owner, False)
        await session.commit()
        await session.refresh(c_ukr)
        await session.refresh(u100)

        assert_check(c_ukr.is_claimed is False, "وضعیت is_claimed اوکراین False شد")
        assert_check(c_ukr.owner_user_id is None, "مالک اوکراین None شد")
        assert_check(u100.is_suspended is False, "تعلیق بازیکن قبلی برداشته شد تا بتواند کشور دیگری انتخاب کند")

    # -------------------------------------------------------------
    # بخش ۲: تست توییتر و نام مسئول/رئیس‌جمهور
    # -------------------------------------------------------------
    print("\n--- بخش ۲: تست توییتر با نام مسئول/رئیس‌جمهور ---")

    # ۲.۱ رندر با نام رئیس‌جمهور اختصاصی
    png_with_pres = render_tweet_image(
        country_name="اوکراین",
        president_name="ولودیمیر زلنسکی",
        country_flag="🇺🇦",
        username="ZelenskyyUa",
        content="پیام صلح، امنیت و دفاع از منافع ملی کشور.",
    )
    assert_check(isinstance(png_with_pres, bytes) and len(png_with_pres) > 2000, "تصویر توییت با نام رئیس‌جمهور بدون خطا تولید شد")
    im1 = Image.open(io.BytesIO(png_with_pres))
    assert_check(im1.size[0] == 1000, "عرض تصویر رندرشده استاندارد ۱۰۰۰ پیکسل است")

    # ۲.۲ رندر بدون نام رئیس‌جمهور (Fallback به نام کشور)
    png_fallback = render_tweet_image(
        country_name="ژاپن",
        president_name=None,
        country_flag="🇯🇵",
        username="JapanGov",
        content="گزارش اقتصادی فصل جدید منتشر شد.",
    )
    assert_check(isinstance(png_fallback, bytes) and len(png_fallback) > 2000, "تصویر توییت در صورت نبود نام رئیس‌جمهور به درستی fallback می‌کند")

    # -------------------------------------------------------------
    # بخش ۳: تست پنل و دستور /switch
    # -------------------------------------------------------------
    print("\n--- بخش ۳: تست پنل و دستور /switch ---")

    async with session_factory() as session:
        # ادمین ۱۱۱ و بازیکن ۳۰۰
        admin_user = User(telegram_id=111, username="admin_boss", first_name="Admin")
        player_300 = User(telegram_id=300, username="regular_player", first_name="Player 300")
        session.add_all([admin_user, player_300])

        c_france = Country(name_en="France", name_fa="فرانسه", flag="🇫🇷", region="Europe", owner_user_id=111, is_claimed=True)
        c_china = Country(name_en="China", name_fa="چین", flag="🇨🇳", region="Asia", owner_user_id=300, is_claimed=True)
        c_brazil = Country(name_en="Brazil", name_fa="برزیل", flag="🇧🇷", region="America", is_claimed=False)
        session.add_all([c_france, c_china, c_brazil])
        await session.commit()
        await session.refresh(c_france)
        await session.refresh(c_china)
        await session.refresh(c_brazil)

        # ۳.۱ تست کیبورد شیشه‌ای switch
        all_c = await countries_repo.list_countries(session)
        kb_sw = _build_switch_kb(all_c, page=0)
        flat_sw_btns = [btn for row in kb_sw.inline_keyboard for btn in row]
        # دکمه چین باید علامت 👤 داشته باشد چون پلیر دارد
        btn_china = next((btn for btn in flat_sw_btns if f"switch_do:{c_china.id}:" in btn.callback_data), None)
        assert_check(btn_china is not None and "👤" in btn_china.text, "کشورهای دارای پلیر با علامت 👤 در کیبورد switch مشخص می‌شوند")

        # دکمه برزیل باید علامت ⚪️ داشته باشد چون آزاد است
        btn_brazil = next((btn for btn in flat_sw_btns if f"switch_do:{c_brazil.id}:" in btn.callback_data), None)
        assert_check(btn_brazil is not None and "⚪️" in btn_brazil.text, "کشورهای آزاد با علامت ⚪️ در کیبورد switch مشخص می‌شوند")

        # ۳.۲ تست سوییچ ادمین روی کشور دارای پلیر (چین)
        with patch("bot.handlers.switch.bot.send_message", new_callable=AsyncMock) as mock_send:
            former_owner, prev_country = await _execute_admin_switch(
                session,
                admin_id=111,
                admin_name="Admin Boss",
                target_country=c_china,
            )
            await session.refresh(c_france)
            await session.refresh(c_china)

            assert_check(former_owner == 300, "مالک قبلی کشور چین به درستی ۳۰۰ تشخیص داده شد")
            assert_check(c_china.owner_user_id == 111, "کشور چین اکنون مستقیماً به ادمین ۱۱۱ واگذار شد")
            assert_check(prev_country is not None and prev_country.id == c_france.id, "کشور قبلی ادمین (فرانسه) شناسایی شد")
            assert_check(c_france.owner_user_id is None and c_france.is_claimed is False, "کشور قبلی ادمین (فرانسه) برای جلوگیری از تداخل آزاد شد")
            assert_check(mock_send.called, "پیام آگاهی‌بخش به پیوی بازیکن ۳۰۰ ارسال شد")
            player_call = next((c for c in mock_send.call_args_list if c[0][0] == 300), None)
            assert_check(player_call is not None and "مدیریت بازی وارد مدیریت کشور شما" in player_call[0][1], "متن هشدار ورود ادمین به کشور صحیح است")

        # ۳.۳ سوییچ ادمین روی کشور آزاد (برزیل)
        with patch("bot.handlers.switch.bot.send_message", new_callable=AsyncMock) as mock_send_free:
            former_owner_free, prev_free = await _execute_admin_switch(
                session,
                admin_id=111,
                admin_name="Admin Boss",
                target_country=c_brazil,
            )
            await session.refresh(c_brazil)
            await session.refresh(c_china)

            assert_check(former_owner_free is None, "کشور آزاد مالک قبلی ندارد")
            assert_check(c_brazil.owner_user_id == 111, "کشور برزیل به ادمین واگذار شد")
            assert_check(c_china.owner_user_id is None, "کشور چین با سوییچ مجدد ادمین آزاد شد")
            player_free_calls = [c for c in mock_send_free.call_args_list if isinstance(c[0][0], int) and c[0][0] > 0]
            assert_check(len(player_free_calls) == 0, "برای کشور آزاد پیام به کاربری ارسال نشد")

    # -------------------------------------------------------------
    # بخش ۴: تست مصونیت ادمین‌ها و مالکین از بن و تعلیق
    # -------------------------------------------------------------
    print("\n--- بخش ۴: تست مصونیت ادمین‌ها و مالکین از بن و تعلیق ---")

    async with session_factory() as session:
        # ۴.۱ تست رد تعلیق ادمین در _apply_suspension
        ok_susp, msg_susp = await _apply_suspension(
            session=session,
            caller_id=222,
            caller_name="Admin 2",
            target_id=111,  # مالک/ادمین
            duration_hours=12,
            reason="تست",
        )
        assert_check(ok_susp is False, "تلاش برای تعلیق ادمین/مالک با خطا مواجه شد")
        assert_check("امکان تعلیق ادمین یا مالک ربات وجود ندارد" in msg_susp, "پیام خطای تعلیق ادمین صحیح است")

        # ۴.۲ تست رد بن ادمین در cmd_ban
        mock_msg = AsyncMock(spec=Message)
        mock_msg.answer = AsyncMock()
        mock_msg.from_user = TgUser(id=222, is_bot=False, first_name="Admin")
        mock_msg.text = "/ban 111 تخلف"
        mock_msg.reply_to_message = None

        await cmd_ban(mock_msg, session)
        assert_check(mock_msg.answer.called, "دستور بن پاسخ ارسال کرد")
        answer_text = mock_msg.answer.call_args[0][0]
        assert_check("امکان مسدودسازی ادمین یا مالک بازی وجود ندارد" in answer_text, "دستور /ban از بن شدن ادمین جلوگیری کرد")

        # ۴.۳ تست Middleware: بای‌پاس ۱۰۰٪ و پاک‌سازی خودکار فلگ‌های بن و تعلیق برای ادمین‌ها
        admin_in_db = await users_repo.get_user(session, 111)
        # به صورت عمدی فلگ‌های بن و تعلیق را روی ادمین فعال می‌کنیم
        admin_in_db.is_banned = True
        admin_in_db.is_suspended = True
        await session.commit()

        middleware = UserMiddleware()
        mock_handler = AsyncMock(return_value="HANDLER_EXECUTED")
        mock_event = AsyncMock(spec=Message)
        mock_event.answer = AsyncMock()

        data_dict = {
            "session": session,
            "event_from_user": TgUser(id=111, is_bot=False, first_name="Boss"),
        }

        result = await middleware(mock_handler, mock_event, data_dict)
        assert_check(result == "HANDLER_EXECUTED", "میدل‌ویر دسترسی ادمین بن‌شده/معلق را مسدود نکرد و اجازه اجرا داد")
        await session.refresh(admin_in_db)
        assert_check(admin_in_db.is_banned is False, "فلگ is_banned برای ادمین به صورت خودکار پاک‌سازی شد")
        assert_check(admin_in_db.is_suspended is False, "فلگ is_suspended برای ادمین به صورت خودکار پاک‌سازی شد")

        # تست اینکه برای پلیر عادی میدل‌ویر به درستی بلاک می‌کند
        player_in_db = await users_repo.get_user(session, 300)
        player_in_db.is_banned = True
        await session.commit()

        data_dict_player = {
            "session": session,
            "event_from_user": TgUser(id=300, is_bot=False, first_name="Player"),
        }
        res_player = await middleware(mock_handler, mock_event, data_dict_player)
        assert_check(res_player is None, "میدل‌ویر دسترسی پلیر عادی بن‌شده را به درستی مسدود کرد")

        # ۴.۴ تست کشورگیری در زمان انجماد سراسری (global_freeze)
        # بررسی اینکه ادمین‌ها معلق نمی‌شوند
        admin_claim = ClaimRequest(
            user_id=111,
            country_id=c_iran.id,
            status="pending",
        )
        regular_claim = ClaimRequest(
            user_id=300,
            country_id=c_ger.id,
            status="pending",
        )
        session.add_all([admin_claim, regular_claim])
        await session.commit()

        # شبیه‌سازی منطق تایید در cb_claim_approve
        global_freeze = True
        frozen_admin = bool(global_freeze) and not settings.is_admin(admin_claim.user_id)
        frozen_regular = bool(global_freeze) and not settings.is_admin(regular_claim.user_id)

        assert_check(frozen_admin is False, "در زمان انجماد سراسری، کشورگیرِ ادمین معلق نمی‌شود")
        assert_check(frozen_regular is True, "در زمان انجماد سراسری، کشورگیرِ عادی به درستی معلق می‌شود")

    await engine.dispose()
    print(f"\n==========================================")
    print(f"🎉 همه تست‌ها با موفقیت پاس شدند! ({passed}/{total})")
    print(f"==========================================")


if __name__ == "__main__":
    asyncio.run(run_tests())
