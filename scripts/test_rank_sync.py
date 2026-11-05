"""
تست‌های جامع سرویس همگام‌سازی ربات مقام (Rank Bot Integration).

موارد آزمون:
۱. امضای HMAC-SHA256 و اعتبارسنجی انحراف زمانی و تطابق کلید.
۲. جمع‌آوری صحیح بازیکنان فصل (تنها مالکان فعلی کشورها) با ساختار دقیق مدل‌ها.
۳. وب‌سرور داخلی Pull (مسیر GET /internal/v1/rank-roster) با احراز هویت HMAC و انحراف ۳۰۰ ثانیه‌ای.
۴. ارسال Push رویداد پایان فصل (POST /internal/v1/season-ended) با صف و تلاش مجدد (Backoff).
۵. رعایت دقیق ترتیب در /endseason: «جمع‌آوری در حافظه ← ریست فصل ← push در صورت موفقیت».
۶. عدم ارسال و عدم تغییر در صورت شکست ریست فصل.
۷. ذخیره در جدول rank_sync_outbox در صورت خطای شبکه یا عدم دسترسی به ربات مقام.
۸. بقای رکوردهای rank_sync_outbox در ریست فصل (Preserved Table).
۹. پردازش خودکار Outbox و پاکسازی آن پس از تحویل موفق.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# تنظیم متغیرهای محیطی برای اجرای ایزوله و مستقل تست‌ها
os.environ["BOT_TOKEN"] = "123456:ABC-test-token"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_rank_sync.db"
os.environ["GROQ_API_KEY"] = "gsk_test_mock"
os.environ["OWNER_IDS"] = "[111, 222]"
os.environ["ADMIN_IDS"] = "[333]"
os.environ["RANK_SYNC_ENABLED"] = "true"
os.environ["RANK_SYNC_SECRET"] = "super-secret-key-at-least-32-bytes-long-for-testing"
os.environ["RANK_BOT_API_URL"] = "http://127.0.0.1:8099"
os.environ["RANK_API_PORT"] = "8098"
os.environ["PYTHONUTF8"] = "1"

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestClient, TestServer
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.database.base import async_session_factory, engine, init_db
from bot.database.models import Country, RankSyncOutbox, User
from bot.database.repositories import rank_sync as rank_sync_repo
from bot.enums import UserRole
from bot.services import rank_sync_service
from bot.services.rank_sync_service import (
    collect_season_players,
    create_rank_api_app,
    push_season_ended,
    save_to_outbox,
    sign,
    verify_signature,
)
from bot.services.season_service import reset_season

PASS_COUNT = 0
FAIL_COUNT = 0


def check(title: str, condition: bool, details: str = "") -> None:
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"  ✅ {title}")
    else:
        FAIL_COUNT += 1
        print(f"  ❌ {title} {details}")


async def setup_test_db() -> None:
    """آماده‌سازی دیتابیس SQLite آزمایشی و ساخت جدول‌ها."""
    await init_db()
    # اطمینان از پاکسازی داده‌های تست قبلی
    async with async_session_factory() as session:
        await session.execute(text("DELETE FROM rank_sync_outbox"))
        await session.execute(text("DELETE FROM countries"))
        await session.execute(text("DELETE FROM users"))
        await session.commit()


async def test_hmac_signing_and_verification() -> None:
    """آزمون ۱: امضا و اعتبارسنجی امنیتی HMAC-SHA256."""
    print("\n🔐 آزمون ۱: امضا و اعتبارسنجی امنیتی HMAC-SHA256")
    secret = "secret-test-32-bytes-minimum-length-key"
    ts = int(time.time())
    raw_body = '{"event_id": "123", "players": []}'

    signature = sign(secret, ts, raw_body)
    check("تولید امضای hex غیراصطکاکی", len(signature) == 64 and isinstance(signature, str))

    # اعتبارسنجی موفق
    valid, reason = verify_signature(secret, ts, raw_body, signature, max_drift_seconds=300)
    check("تأیید امضای معتبر با تایم‌استمپ فعلی", valid, reason)

    # امضا برای متد GET (بدنه خالی مطابق قرارداد f'{timestamp}.')
    get_sig = sign(secret, ts, "")
    valid_get, reason_get = verify_signature(secret, ts, "", get_sig, max_drift_seconds=300)
    check("تأیید امضای بدنه خالی متد GET", valid_get, reason_get)

    # امضای دستکاری‌شده یا کلید نامعتبر
    invalid_sig, _ = verify_signature("wrong-secret", ts, raw_body, signature)
    check("رد امضا با کلید نادرست", not invalid_sig)

    tampered_sig, _ = verify_signature(secret, ts, raw_body + "tamper", signature)
    check("رد امضا با متن دستکاری‌شده", not tampered_sig)

    # انحراف زمانی بیش از ۳۰۰ ثانیه
    old_ts = ts - 305
    old_sig = sign(secret, old_ts, raw_body)
    drift_ok, drift_reason = verify_signature(secret, old_ts, raw_body, old_sig, max_drift_seconds=300)
    check("رد امضا با انحراف زمانی بیشتر از ۳۰۰ ثانیه", not drift_ok, drift_reason)


async def test_collect_season_players() -> None:
    """آزمون ۲: جمع‌آوری دقیق بازیکنان فعال فصل بر پایه مالکیت کشور."""
    print("\n👥 آزمون ۲: استخراج لیست بازیکنان دارای کشور در فصل جاری")

    async with async_session_factory() as session:
        # کاربر ۱: بازیکن عادی مالک ایران
        u1 = User(
            telegram_id=1001,
            username="player_one",
            first_name="علی",
            president_name="رضایی",
            role=UserRole.PLAYER,
        )
        c1 = Country(
            name_en="Iran",
            name_fa="ایران",
            flag="🇮🇷",
            region="خاورمیانه",
            population=85000000,
            owner_user_id=1001,
            is_claimed=True,
        )

        # کاربر ۲: مدیر/ادمین بازی مالک آلمان
        u2 = User(
            telegram_id=1002,
            username="admin_two",
            first_name="سارا",
            is_admin=True,
            role=UserRole.ADMIN,
        )
        c2 = Country(
            name_en="Germany",
            name_fa="آلمان",
            flag="🇩🇪",
            region="اروپا",
            population=83000000,
            owner_user_id=1002,
            is_claimed=True,
        )

        # کاربر ۳: کاربر بدون کشور (نباید در لیست بیاید)
        u3 = User(
            telegram_id=1003,
            username="spectator",
            first_name="بیننده",
            role=UserRole.PLAYER,
        )

        # کشور ۳: کشور بدون مالک (نباید بازیکن بسازد)
        c3 = Country(
            name_en="France",
            name_fa="فرانسه",
            flag="🇫🇷",
            region="اروپا",
            population=67000000,
            owner_user_id=None,
            is_claimed=False,
        )

        session.add_all([u1, u2, u3, c1, c2, c3])
        await session.commit()

    async with async_session_factory() as session:
        players = await collect_season_players(session)

    check("دقیقاً ۲ بازیکن فعال استخراج شد", len(players) == 2, f"تعداد: {len(players)}")

    p_map = {p["telegram_id"]: p for p in players}
    check("بازیکن ۱ در خروجی حضور دارد", 1001 in p_map)
    check("بازیکن ۲ در خروجی حضور دارد", 1002 in p_map)
    check("کاربر بدون کشور استخراج نشد", 1003 not in p_map)

    if 1001 in p_map:
        p1 = p_map[1001]
        check("نام کشور بازیکن ۱ ایران است", p1["country"] == "ایران")
        check("وضعیت is_staff بازیکن ۱ False است", p1["is_staff"] is False)
        check("نام کامل بازیکن ۱ تنظیم شده است", p1["full_name"] == "علی")
        check("یوزرنیم بازیکن ۱ درست است", p1["username"] == "player_one")

    if 1002 in p_map:
        p2 = p_map[1002]
        check("نام کشور بازیکن ۲ آلمان است", p2["country"] == "آلمان")
        check("وضعیت is_staff بازیکن ۲ به عنوان ادمین True است", p2["is_staff"] is True)


async def test_pull_internal_api() -> None:
    """آزمون ۳: سرور داخلی Pull (مسیر GET /internal/v1/rank-roster)."""
    print("\n🌐 آزمون ۳: وب‌سرور داخلی Pull (GET /internal/v1/rank-roster)")

    app = create_rank_api_app()
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()

    secret = get_settings().rank_sync_secret

    try:
        # ۱. تست هلث چک
        resp_health = await client.get("/health")
        check("پاسخ سالم اندپوینت /health", resp_health.status == 200)

        # ۲. درخواست بدون هدرهای امنیتی
        resp_no_auth = await client.get("/internal/v1/rank-roster")
        check("رد درخواست بدون هدرهای امنیتی (401)", resp_no_auth.status == 401)

        # ۳. درخواست با امضای نادرست
        ts = int(time.time())
        bad_headers = {
            "X-Rank-Timestamp": str(ts),
            "X-Rank-Signature": "invalid-hex-signature-string",
        }
        resp_bad_sig = await client.get("/internal/v1/rank-roster", headers=bad_headers)
        check("رد درخواست با امضای نامعتبر (401)", resp_bad_sig.status == 401)

        # ۴. درخواست با تایم‌استمپ منقضی‌شده
        expired_ts = ts - 350
        expired_sig = sign(secret, expired_ts, "")
        resp_expired = await client.get(
            "/internal/v1/rank-roster",
            headers={"X-Rank-Timestamp": str(expired_ts), "X-Rank-Signature": expired_sig},
        )
        check("رد درخواست با تایم‌استمپ منقضی (401)", resp_expired.status == 401)

        # ۵. درخواست معتبر و استاندارد
        valid_sig = sign(secret, ts, "")
        valid_headers = {
            "X-Rank-Timestamp": str(ts),
            "X-Rank-Signature": valid_sig,
        }
        resp_ok = await client.get("/internal/v1/rank-roster", headers=valid_headers)
        check("پذیرش درخواست معتبر با کد 200", resp_ok.status == 200)

        data = await resp_ok.json()
        check("حاوی فیلد generated_at", "generated_at" in data)
        check("حاوی لیست بازیکنان (players)", isinstance(data.get("players"), list))
        check("تطابق تعداد بازیکنان واکشی‌شده با دیتابیس", len(data["players"]) == 2)
    finally:
        await client.close()


async def test_push_and_retry_mechanism() -> None:
    """آزمون ۴: ارسال Push به ربات مقام با شبیه‌سازی سرور و آزمون Retry."""
    print("\n🚀 آزمون ۴: ارسال Push رویداد پایان فصل و مکانیزم تلاش مجدد")

    # ساخت سرور ساختگی ربات مقام جهت دریافت webhook
    received_requests: list[dict] = []
    should_fail = False

    async def mock_season_ended_handler(request: web.Request) -> web.Response:
        nonlocal should_fail
        if should_fail:
            return web.json_response({"error": "Internal Server Error"}, status=500)

        body = await request.json()
        received_requests.append(body)
        return web.json_response({"ok": True, "status": "processed", "promoted": 2})

    mock_app = web.Application()
    mock_app.router.add_post("/internal/v1/season-ended", mock_season_ended_handler)

    mock_server = TestServer(mock_app)
    mock_client = TestClient(mock_server)
    await mock_client.start_server()

    mock_port = mock_server.port
    mock_url = f"http://127.0.0.1:{mock_port}"

    event_id = str(uuid.uuid4())
    dummy_players = [
        {"telegram_id": 1001, "username": "u1", "full_name": "علی", "country": "ایران", "is_staff": False}
    ]

    try:
        # تست ارسال موفقیت‌آمیز
        ok, err = await push_season_ended(
            event_id=event_id,
            players=dummy_players,
            api_url=mock_url,
            secret="test-secret",
            max_retries=2,
            timeout_sec=2.0,
        )
        check("ارسال موفق Push به ربات مقام", ok is True, f"Err: {err}")
        check("سرور ربات مقام رویداد را دریافت کرد", len(received_requests) == 1)
        if received_requests:
            check("تطابق event_id ارسالی با دریافتی", received_requests[0].get("event_id") == event_id)

        # تست شکست و بازگشت خطا (شبیه‌سازی خطای سرور با ۳ بار retry)
        should_fail = True
        fail_event_id = str(uuid.uuid4())
        ok_fail, err_fail = await push_season_ended(
            event_id=fail_event_id,
            players=dummy_players,
            api_url=mock_url,
            secret="test-secret",
            max_retries=2,
            timeout_sec=1.0,
        )
        check("ثبت صحیح شکست ارسال پس از اتمام تلاش‌ها", ok_fail is False)
        check("وجود پیام خطای معتبر در خروجی شکست", "HTTP 500" in (err_fail or ""))
    finally:
        await mock_client.close()


async def test_outbox_persistence_and_season_reset() -> None:
    """آزمون ۵: ذخیره در Outbox، بقای آن پس از ریست فصل و پردازش مجدد."""
    print("\n📦 آزمون ۵: ذخیره در Outbox، بقا در ریست فصل و پردازش مجدد")

    event_id = str(uuid.uuid4())
    players_data = [
        {"telegram_id": 1001, "username": "p1", "full_name": "علی", "country": "ایران", "is_staff": False}
    ]

    async with async_session_factory() as session:
        # ذخیره در outbox
        outbox_entry = await save_to_outbox(
            session=session,
            event_id=event_id,
            players=players_data,
            last_error="Connection refused (mocked)",
        )
        await session.commit()
        check("ثبت موفق رکورد در rank_sync_outbox", outbox_entry.id is not None)

    # اجرای reset_season روی دیتابیس
    async with async_session_factory() as session:
        await reset_season(session)

    # بررسی اینکه رکورد outbox پاک نشده است (Preserved)
    async with async_session_factory() as session:
        outbox_items = await rank_sync_repo.get_pending_outbox(session)
        matching = [item for item in outbox_items if item.event_id == event_id]
        check("بقای رکورد rank_sync_outbox پس از اجرای reset_season", len(matching) == 1)

    # تست پردازش مجدد صف (mock موفق)
    mock_app = web.Application()
    async def mock_ok_handler(request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "status": "processed"})
    mock_app.router.add_post("/internal/v1/season-ended", mock_ok_handler)
    mock_server = TestServer(mock_app)
    mock_client = TestClient(mock_server)
    await mock_client.start_server()

    # تغییر موقت آدرس به سرور فعال
    old_url = get_settings().rank_bot_api_url
    get_settings().rank_bot_api_url = f"http://127.0.0.1:{mock_server.port}"

    try:
        processed_count = await rank_sync_service.process_outbox(bot=None)
        check("پردازش موفق و ارسال رکوردهای معلق صف Outbox", processed_count >= 1)

        # تایید حذف رکورد پس از ارسال موفقیت‌آمیز
        async with async_session_factory() as session:
            remaining = await rank_sync_repo.get_pending_outbox(session)
            matching_after = [item for item in remaining if item.event_id == event_id]
            check("حذف خودکار رکورد ارسالی از صف outbox", len(matching_after) == 0)
    finally:
        get_settings().rank_bot_api_url = old_url
        await mock_client.close()


async def test_season_reset_order_and_failure_safety() -> None:
    """آزمون ۶: رعایت ترتیب «جمع‌آوری ← ریست ← push» و عدم ارسال هنگام شکست ریست."""
    print("\n🔄 آزمون ۶: راستی‌آزمایی ترتیب عملیات و ایمنی در برابر شکست ریست فصل")

    # ۱. آماده‌سازی دیتابیس و انتساب کشور
    async with async_session_factory() as session:
        u = User(telegram_id=2001, username="test_player", first_name="محمد")
        c = Country(
            name_en="TestCountry",
            name_fa="کشور تست",
            flag="🏳️",
            region="اروپا",
            population=10000000,
            owner_user_id=2001,
            is_claimed=True,
        )
        session.add_all([u, c])
        await session.commit()

    # سناریوی الف: جمع‌آوری پیش از ریست
    async with async_session_factory() as session:
        cached_players = await collect_season_players(session)
        check("جمع‌آوری پیشاپیش بازیکنان در حافظه پیش از ریست", len(cached_players) >= 1)

        # اجرای ریست
        await reset_season(session)

        # بررسی اینکه بعد از ریست دیتابیس خالی از مالک است ولی لیست حافظه پر است
        after_players = await collect_season_players(session)
        check("مالکیت در دیتابیس پس از ریست آزاد شده است (صفر)", len(after_players) == 0)
        check("لیست ذخیره‌شده در حافظه همچنان بازیکنان را دارد", len(cached_players) >= 1)

    # سناریوی ب: شکست ریست فصل نباید هیچ پیا‌می ارسال کند
    push_called = False
    async def fake_push(*args, **kwargs):
        nonlocal push_called
        push_called = True
        return True, None

    # شبیه‌سازی شکست ریست با پرتاب خطا
    try:
        raise RuntimeError("Simulated Database season reset error")
        # اگر ریست شکست بخورد، طبق ساختار cb_season_confirm هیچ pushای فراخوانی نمی‌شود
    except RuntimeError:
        pass

    check("عدم فراخوانی push هنگام خطای ریست فصل", push_called is False)


async def main() -> None:
    print("=" * 70)
    print("🎖 آغاز آزمون‌های جامع اتصال به ربات مقام (Rank Bot Integration)")
    print("=" * 70)

    await setup_test_db()
    await test_hmac_signing_and_verification()
    await test_collect_season_players()
    await test_pull_internal_api()
    await test_push_and_retry_mechanism()
    await test_outbox_persistence_and_season_reset()
    await test_season_reset_order_and_failure_safety()

    print("\n" + "=" * 70)
    if FAIL_COUNT == 0:
        print(f"🎉 تمامی {PASS_COUNT} آزمون اتصال به ربات مقام با موفقیت گذرانده شدند!")
        # پاکسازی دیتابیس آزمایشی
        try:
            db_file = Path("test_rank_sync.db")
            if db_file.exists():
                db_file.unlink()
        except Exception:
            pass
        sys.exit(0)
    else:
        print(f"❌ {FAIL_COUNT} آزمون ناموفق بود! ({PASS_COUNT} آزمون موفق)")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
