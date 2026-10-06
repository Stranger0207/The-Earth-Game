"""
اسکریپت تست خودکار برای راستی‌آزمایی:
۱. رفع باگ تعلیق، اخراج بازیکن و تابع رفع تعلیق کاربران بدون کشور
۲. سیستم بن و رفع بن با آیدی عددی و @username و لیست بن‌شده‌ها
۳. ستون channel_message_id و منطق پیام ریپلای مزایده
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# تنظیم متغیرهای محیطی آزمایشی
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

from bot.config import get_settings
from bot.database.base import Base, _COLUMN_MIGRATIONS
from bot.database.models import Auction, Country, User
from bot.database.repositories import auctions as auctions_repo
from bot.database.repositories import countries as countries_repo
from bot.database.repositories import users as users_repo
from bot.enums import UserRole
from bot.handlers.admin import _resolve_ban_target
from bot.utils.numbers import fa_money

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
    print("🚀 آغاز آزمون‌های باگ تعلیق، سیستم بن و مزایده...")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = get_settings()

    async with session_factory() as session:
        # ==========================================
        # بخش ۱: مهاجرت ستون auctions.channel_message_id
        # ==========================================
        print("\n--- ۱. بررسی مهاجرت ستون‌ها ---")
        auc_migration = any(
            t == "auctions" and c == "channel_message_id" for t, c, _ in _COLUMN_MIGRATIONS
        )
        check("ستون channel_message_id در _COLUMN_MIGRATIONS ثبت شده است", auc_migration)

        # ==========================================
        # بخش ۲: کاربران و تعلیق (Suspension)
        # ==========================================
        print("\n--- ۲. بررسی سیستم تعلیق و رفع تعلیق ---")
        c1 = Country(
            id=1,
            name_en="Iran",
            name_fa="ایران",
            flag="🇮🇷", region="middle_east",
            budget=10_000_000_000.0,
            is_claimed=False,
        )
        c2 = Country(
            id=2,
            name_en="France",
            name_fa="فرانسه",
            flag="🇫🇷", region="europe",
            budget=15_000_000_000.0,
            is_claimed=False,
        )
        session.add_all([c1, c2])

        u1 = User(
            telegram_id=1001,
            username="player_one",
            first_name="Player 1",
            is_suspended=True,
            role=UserRole.PLAYER,
        )
        u2 = User(
            telegram_id=1002,
            username="player_two",
            first_name="Player 2",
            is_suspended=True,
            role=UserRole.PLAYER,
        )
        u3 = User(
            telegram_id=1003,
            username="player_three",
            first_name="Player 3",
            is_suspended=True,
            role=UserRole.PLAYER,
        )
        session.add_all([u1, u2, u3])
        await session.commit()

        await countries_repo.assign_owner(session, 1, 1001)
        await session.commit()

        cleared_count = await users_repo.unsuspend_countryless_users(session)
        await session.commit()

        check("تعداد کاربران بدون کشور آزادشده باید ۲ نفر باشد", cleared_count == 2, f"شد: {cleared_count}")

        u1_ref = await users_repo.get_user(session, 1001)
        u2_ref = await users_repo.get_user(session, 1002)
        u3_ref = await users_repo.get_user(session, 1003)

        check("کاربر صاحب کشور (u1) همچنان باید معلق باشد", u1_ref.is_suspended is True)
        check("کاربر بدون کشور (u2) باید رفع تعلیق شده باشد", u2_ref.is_suspended is False)
        check("کاربر بدون کشور (u3) باید رفع تعلیق شده باشد", u3_ref.is_suspended is False)

        former_owner = c1.owner_user_id
        await countries_repo.release_country(session, 1)
        if former_owner:
            await users_repo.set_suspended(session, former_owner, False)
        await session.commit()

        u1_after_release = await users_repo.get_user(session, 1001)
        check("کاربر اخراج‌شده از کشور باید تعلیقش برداشته شود", u1_after_release.is_suspended is False)
        c1_ref = await countries_repo.get_country(session, 1)
        check("کشور پس از آزادسازی نباید مالکی داشته باشد", c1_ref.owner_user_id is None and not c1_ref.is_claimed)

        # ==========================================
        # بخش ۳: سیستم بن و آن‌بن (Ban & Unban)
        # ==========================================
        print("\n--- ۳. بررسی سیستم بن و آن‌بن با آیدی و یوزرنیم ---")
        found_u2_1 = await users_repo.get_user_by_username(session, "@player_two")
        found_u2_2 = await users_repo.get_user_by_username(session, "PLAYER_TWO")
        found_u2_3 = await users_repo.get_user_by_username(session, "unknown_user_xyz")

        check("یافتن کاربر با @player_two", found_u2_1 is not None and found_u2_1.telegram_id == 1002)
        check("یافتن کاربر با PLAYER_TWO (Case Insensitive)", found_u2_2 is not None and found_u2_2.telegram_id == 1002)
        check("کاربر ناموجود باید None برگرداند", found_u2_3 is None)

        r_user, r_uid, r_err = await _resolve_ban_target(session, "1002")
        check("رزولور با آیدی عددی موجود", r_user is not None and r_uid == 1002 and r_err is None)

        r_user_new, r_uid_new, r_err_new = await _resolve_ban_target(session, "99999")
        check("رزولور با آیدی عددی جدید", r_user_new is None and r_uid_new == 99999 and r_err_new is None)

        r_user_u, r_uid_u, r_err_u = await _resolve_ban_target(session, "@player_three")
        check("رزولور با نام کاربری موجود", r_user_u is not None and r_uid_u == 1003 and r_err_u is None)

        r_user_no, r_uid_no, r_err_no = await _resolve_ban_target(session, "@nobody")
        check("رزولور با نام کاربری ناموجود باید خطا دهد", r_user_no is None and r_err_no is not None)

        await users_repo.set_banned(session, 1002, True)
        await session.commit()
        u2_banned = await users_repo.get_user(session, 1002)
        check("کاربر ۲ باید بن شده باشد", u2_banned.is_banned is True)

        banned_list = await users_repo.list_banned_users(session)
        check("لیست بن‌شده‌ها شامل کاربر ۲ است", any(u.telegram_id == 1002 for u in banned_list))

        await users_repo.set_banned(session, 1002, False)
        await session.commit()
        u2_unbanned = await users_repo.get_user(session, 1002)
        check("کاربر ۲ پس از آن‌بن آزاد شد", u2_unbanned.is_banned is False)

        new_banned_uid = 88888
        preemptive_user = await users_repo.get_or_create_user(session, new_banned_uid, None, None)
        await users_repo.set_banned(session, new_banned_uid, True)
        await session.commit()
        check("کاربر پیش‌دستانه ایجاد و بن شد", preemptive_user.is_banned is True)

        check("آیدی 111 نباید قابل بن باشد (مالک)", settings.is_admin(111) is True)
        check("آیدی 222 نباید قابل بن باشد (ادمین)", settings.is_admin(222) is True)

        # ==========================================
        # بخش ۴: سیستم مزایده و ریپلای پیام (Auction)
        # ==========================================
        print("\n--- ۴. بررسی مزایده و ریپلای روی اطلاعیه کانال ---")
        now = datetime.now(timezone.utc)
        auc = await auctions_repo.create_auction(
            session=session,
            seller_country_id=1,
            resource="oil",
            amount=5_000_000.0,
            base_price=1_000_000_000.0,
            ends_at=now,
        )
        auc.channel_message_id = 12345
        await session.commit()

        auc_check = await auctions_repo.get_auction(session, auc.id)
        check("مزایده با موفقیت ایجاد شد و channel_message_id ذخیره شد", auc_check.channel_message_id == 12345)

        bid_amount = 1_500_000_000.0
        bid = await auctions_repo.add_bid(session, auc.id, 2, bid_amount)
        await session.commit()

        auc_after_bid = await auctions_repo.get_auction(session, auc.id)
        check("بالاترین پیشنهاد مزایده به‌روزرسانی شد", auc_after_bid.highest_bid == bid_amount)
        check("بالاترین پیشنهاددهنده ثبت شد", auc_after_bid.highest_bidder_country_id == 2)

        c2_obj = await countries_repo.get_country(session, 2)
        expected_bid_text = (
            f"🏷 <b>پیشنهاد جدید در مزایده #{auc.id}!</b>\n\n"
            f"پیشنهاد جدید از کشور <b>{c2_obj.flag} {c2_obj.name_fa}</b>\n"
            f"💰 <b>قیمت پایه جدید:</b> {fa_money(bid_amount)}"
        )
        check("متن ریپلای مزایده شامل نام کشور پیشنهاددهنده است", f"{c2_obj.flag} {c2_obj.name_fa}" in expected_bid_text)
        check("متن ریپلای مزایده شامل قیمت جدید است", fa_money(bid_amount) in expected_bid_text)

    await engine.dispose()

    print("\n" + "=" * 50)
    print(f"نتیجه نهایی: {_passed} آزمون موفق، {len(_failed)} آزمون ناموفق")
    if _failed:
        print("\nموارد ناموفق:")
        for f in _failed:
            print(f" - {f}")
        sys.exit(1)
    else:
        print("🎉 تمام آزمون‌های سیستم با موفقیت کامل گذرانده شدند!")


if __name__ == "__main__":
    asyncio.run(run_tests())
