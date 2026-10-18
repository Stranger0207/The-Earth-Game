"""
تست جامع مینی‌اپ رادار زنده استراتژیک جهان (Live Strategic Radar).
بررسی وب‌سرور aiohttp، احراز هویت HMAC-SHA256، اندپوینت /api/radar-state،
مسیریابی ژئوپلیتیک دریایی، قانون محرمانگی بارنامه و امکان رهگیری.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

# اطمینان از خروجی UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

os.environ["BOT_TOKEN"] = "123456:TEST_BOT_TOKEN_FOR_RADAR"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GROQ_API_KEY"] = "gsk_test"
os.environ["PYTHONUTF8"] = "1"

from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.base import Base, async_session_factory, engine, init_db
from bot.database.models import (
    Country,
    Meeting,
    MilitarySale,
    ResourceSale,
    User,
)
from bot.enums import DiplomacyStatus, TradeStatus, TransportMode
from bot.loader import bot
from bot.services import geo_service as geo
from bot.webapp.auth import extract_telegram_id, validate_init_data
from bot.webapp.server import create_webapp
from bot.webapp.state import get_radar_state

logging.basicConfig(level=logging.ERROR)


def make_telegram_init_data(user_dict: dict, bot_token: str) -> str:
    """تولید یک رشته معتبر initData تلگرام با امضای معتبر HMAC-SHA256."""
    user_json = json.dumps(user_dict, separators=(",", ":"))
    auth_date = str(int(datetime.now(timezone.utc).timestamp()))
    params = {
        "auth_date": auth_date,
        "query_id": "AAHdF6IQAAAAAN0XohD123",
        "user": user_json,
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    sig = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"auth_date={auth_date}&query_id={params['query_id']}&user={user_json}&hash={sig}"


async def run_tests() -> None:
    print("=" * 65)
    print("🚀 آغاز تست‌های جامع مینی‌اپ رادار زنده استراتژیک جهان (Live Radar)")
    print("=" * 65)

    test_count = 0

    def assert_true(condition: bool, msg: str) -> None:
        nonlocal test_count
        test_count += 1
        if not condition:
            print(f"❌ شکست در تست #{test_count}: {msg}")
            raise AssertionError(f"Test #{test_count} failed: {msg}")
        print(f"✅ تست #{test_count}: {msg}")

    # ----------------------------------------------------
    # بخش ۱: تست هندسه و مختصات تنگه‌ها و نقاط مسیر
    # ----------------------------------------------------
    print("\n--- بخش ۱: تست هندسه، تنگه‌ها و ژئومسیریابی ---")
    strait_defs = geo.list_all_strait_defs()
    assert_true(len(strait_defs) == 14, "تعداد ۱۴ تنگه استراتژیک در تعاریف موجود است.")

    for s in strait_defs:
        coords = s.get("coords")
        assert_true(
            isinstance(coords, list) and len(coords) == 2,
            f"مختصات معتبر [lat, lon] برای تنگه {s['name_fa']} تعریف شده است.",
        )
        lat, lon = coords
        assert_true(-90 <= lat <= 90 and -180 <= lon <= 180, f"مختصات {s['id']} در محدوده کروی زمین است.")

    # تست مسیر دریایی ایران به آلمان (باید از تنگه‌ها رد شود)
    sea_pts = geo.get_maritime_waypoints("Iran", "Germany")
    assert_true(len(sea_pts) > 2, "مسیر دریایی ایران به آلمان شامل تنگه‌های واسط است.")
    assert_true(sea_pts[0] == geo.get_geo("Iran")["coords"], "نقطه شروع مسیر، مبدأ است.")
    assert_true(sea_pts[-1] == geo.get_geo("Germany")["coords"], "نقطه پایان مسیر، مقصد است.")

    # تست مسیر هوایی چین به آمریکا
    air_pts = geo.get_air_waypoints("China", "USA")
    assert_true(len(air_pts) == 2, "مسیر هوایی چین به آمریکا دو نقطه مستقیم مبدأ و مقصد است.")

    # ----------------------------------------------------
    # بخش ۲: تست امنیت و احراز هویت HMAC-SHA256
    # ----------------------------------------------------
    print("\n--- بخش ۲: تست امنیت و اعتبارسنجی Telegram initData ---")
    token = os.environ["BOT_TOKEN"]
    test_user = {"id": 987654321, "first_name": "Ali", "username": "ali_leader"}
    valid_init_data = make_telegram_init_data(test_user, token)

    val_res = validate_init_data(valid_init_data, token)
    assert_true(val_res is not None, "رشته معتبر initData با امضای HMAC تأیید شد.")
    assert_true(val_res.get("user", {}).get("id") == 987654321, "شناسه تلگرام کاربر به درستی استخراج شد.")

    uid_extracted = extract_telegram_id(valid_init_data, token)
    assert_true(uid_extracted == 987654321, "متد extract_telegram_id شناسه عددی را برگرداند.")

    # دستکاری در رشته (باید رد شود)
    tampered_init_data = valid_init_data.replace("987654321", "111111111")
    tampered_res = validate_init_data(tampered_init_data, token)
    assert_true(tampered_res is None, "رشته دستکاری‌شده initData با خطا رد شد (حفظ امنیت).")

    # تست حالت Bypass توسعه
    dev_res = validate_init_data("test_uid_55555", token)
    assert_true(dev_res is not None and dev_res["user"]["id"] == 55555, "حالت Bypass تست توسعه فعال است.")

    # ----------------------------------------------------
    # بخش ۳: ساخت دیتابیس آزمایشی و سناریوی زنده
    # ----------------------------------------------------
    print("\n--- بخش ۳: تست تجمیع داده‌ها، دیتابیس و حفظ محرمانگی بارنامه ---")
    await init_db()

    now = datetime.now(timezone.utc)

    async with async_session_factory() as session:
        # ایجاد کاربران
        u_iran = User(telegram_id=1001, first_name="Reza", president_name="دکتر رضایی")
        u_china = User(telegram_id=1002, first_name="Xi", president_name="شی جین‌پینگ")
        u_germany = User(telegram_id=1003, first_name="Olaf", president_name="اولاف شولتز")
        session.add_all([u_iran, u_china, u_germany])
        await session.flush()

        # ایجاد کشورها
        c_iran = Country(
            name_en="Iran",
            name_fa="ایران",
            flag="🇮🇷",
            region="middle_east",
            owner_user_id=1001,
            is_claimed=True,
            economic_power=70.0,
        )
        c_china = Country(
            name_en="China",
            name_fa="چین",
            flag="🇨🇳",
            region="east_asia",
            owner_user_id=1002,
            is_claimed=True,
            economic_power=92.0,
        )
        c_germany = Country(
            name_en="Germany",
            name_fa="آلمان",
            flag="🇩🇪",
            region="europe",
            owner_user_id=1003,
            is_claimed=True,
            economic_power=85.0,
        )
        session.add_all([c_iran, c_china, c_germany])
        await session.flush()

        # ایجاد پرواز دیپلماتیک فعال (سفر هیئت ایران به چین با زمان پرواز ۳۰ دقیقه)
        m_flight = Meeting(
            traveler_country=c_iran.id,
            host_country=c_china.id,
            status=DiplomacyStatus.ACTIVE,
            start_announced=False,
            created_at=now - timedelta(minutes=10),
            travel_eta=now + timedelta(minutes=20),
        )
        session.add(m_flight)

        # ایجاد محموله دریایی نفت (فروشنده ایران -> خریدار چین)
        sale_sea = ResourceSale(
            seller_country=c_iran.id,
            buyer_country=c_china.id,
            resource="oil",
            amount=5000.0,
            price=350_000.0,
            status=TradeStatus.IN_TRANSIT,
            transport_mode=TransportMode.SEA.value,
            escort_power=80.0,
            ship_eta=now + timedelta(hours=2),
            created_at=now - timedelta(hours=1),
        )

        # ایجاد محموله تسلیحاتی هوایی (چین به آلمان)
        sale_mil = MilitarySale(
            seller_country=c_china.id,
            buyer_country=c_germany.id,
            category="جنگنده",
            branch="نیروی هوایی",
            name="J-20 Mighty Dragon",
            count=12,
            unit="فروند",
            price=1_200_000_000.0,
            status=TradeStatus.IN_TRANSIT,
            transport_mode=TransportMode.AIR.value,
            escort_power=0.0,
            ship_eta=now + timedelta(hours=1),
            created_at=now - timedelta(minutes=30),
        )
        session.add_all([sale_sea, sale_mil])
        await session.commit()

    # ۱. استعلام توسط فروشنده (ایران): بارنامه باید آشکار باشد
    async with async_session_factory() as session:
        state_seller = await get_radar_state(session, viewer_user_id=1001)

    assert_true(len(state_seller["diplomatic_flights"]) == 1, "پرواز دیپلماتیک در رادار شناسایی شد.")
    f_info = state_seller["diplomatic_flights"][0]
    assert_true(f_info["from_country"]["name_en"] == "Iran", "مبدأ پرواز ایران است.")
    assert_true(f_info["to_country"]["name_en"] == "China", "مقصد پرواز چین است.")
    assert_true(0 <= f_info["progress_pct"] <= 100, "درصد پیشرفت پرواز در محدوده مجاز است.")

    assert_true(len(state_seller["shipments"]) == 2, "هر دو محموله فعال در رادار حاضر هستند.")
    oil_shipment = next(s for s in state_seller["shipments"] if s["sale_type"] == "resource")

    assert_true(
        not oil_shipment["is_confidential"],
        "قانون محرمانگی: برای فروشنده بارنامه آشکار است (is_confidential=False).",
    )
    assert_true("نفت" in oil_shipment["content"], "محتوای بار نفت به درستی به فروشنده نمایش داده می‌شود.")
    assert_true(oil_shipment["has_escort"] is True, "وضعیت اسکورت محموله ثبت شده است.")

    # ۲. استعلام توسط کشور ثالث (آلمان): بارنامه باید محرمانه باشد
    async with async_session_factory() as session:
        state_third_party = await get_radar_state(session, viewer_user_id=1003)

    oil_shipment_tp = next(s for s in state_third_party["shipments"] if s["sale_type"] == "resource")
    assert_true(
        oil_shipment_tp["is_confidential"] is True,
        "قانون محرمانگی: برای کشور ثالث بارنامه طبقه‌بندی شده است (is_confidential=True).",
    )
    assert_true(
        oil_shipment_tp["content"] == "🔒 محرمانه (بارنامه طبقه‌بندی‌شده)",
        "متن بارنامه برای کشور ثالث دقیقاً '🔒 محرمانه (بارنامه طبقه‌بندی‌شده)' است.",
    )

    # ----------------------------------------------------
    # بخش ۴: تست وب‌سرور سبک aiohttp و اندپوینت‌ها
    # ----------------------------------------------------
    print("\n--- بخش ۴: تست روت‌های وب‌سرور aiohttp و پاسخ HTTP ---")
    app = create_webapp(bot)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()

    try:
        # تست ارائه صفحه اصلی index.html
        resp_index = await client.get("/")
        assert_true(resp_index.status == 200, "صفحه اصلی مینی‌اپ با کد وضعیت 200 ارائه شد.")
        html_text = await resp_index.text()
        assert_true("رادار استراتژیک جهان" in html_text, "عنوان و المان‌های رادار در HTML موجود است.")
        assert_true("leaflet" in html_text.lower(), "اسکریپت نقشه Leaflet در HTML لود شده است.")

        # تست دریافت JSON اندپوینت /api/radar-state
        resp_api = await client.get("/api/radar-state")
        assert_true(resp_api.status == 200, "اندپوینت /api/radar-state با کد وضعیت 200 پاسخ داد.")
        json_data = await resp_api.json()
        assert_true("countries" in json_data, "کلید countries در پاسخ JSON موجود است.")
        assert_true("shipments" in json_data, "کلید shipments در پاسخ JSON موجود است.")
        assert_true("diplomatic_flights" in json_data, "کلید diplomatic_flights در پاسخ JSON موجود است.")
        assert_true("straits" in json_data, "کلید straits در پاسخ JSON موجود است.")
        assert_true(len(json_data["straits"]) == 14, "لیست هر ۱۴ تنگه در خروجی API رادار استراتژیک قرار دارد.")

        # تست ارسال با هدر X-Test-User-Id برای شبیه‌سازی ورود بازیکن
        resp_auth = await client.get("/api/radar-state", headers={"X-Test-User-Id": "1001"})
        json_auth = await resp_auth.json()
        assert_true(
            json_auth["viewer"]["telegram_id"] == 1001,
            "احراز هویت کلاینت شناسه بازیکن را به درستی تشخیص داد.",
        )
        assert_true(
            json_auth["viewer"]["country_name"] == "ایران",
            "کشور بازیکن (ایران) در اطلاعات بیننده ثبت شد.",
        )

    finally:
        if client.session and not client.session.closed:
            await client.session.close()
        await client.close()
        await server.close()
        await asyncio.sleep(0.1)

    print("\n" + "=" * 65)
    print(f"🎉 کلیه {test_count} تست مینی‌اپ رادار زنده استراتژیک جهان با موفقیت پاس شدند!")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(run_tests())
