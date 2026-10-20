"""
تست جامع سیستم انتقال تکنولوژی تسلیحاتی و دیپلماسی کامل سازمان ملل متحد (UN).

بخش‌های تست:
۱. پوشش ۱۰۰٪ بانک اطلاعاتی کشورهای سازنده تجهیزات (data/equipment_origins.json)
۲. مسدودسازی خط تولید تجهیزات غیربومی در کارخانه نظامی بدون لایسنس
۳. چرخه کامل انتقال تکنولوژی (درخواست خریدار، تعیین قیمت فروشنده، صدور فاکتور، پرداخت و اعطای لایسنس)
۴. فعال‌سازی کامل امکانات دیپلماتیک سازمان ملل (بیانیه رسمی دبیرکل، پروازهای نیویورک، نامه گرافیکی، تماس و دکمه‌ها)
۵. تست پایان فصل و پاک‌سازی کلیدهای خارجی با اجبار PRAGMA foreign_keys=ON

اجرا:
    $env:PYTHONUTF8="1"; $env:BOT_TOKEN="123:test"; $env:DATABASE_URL="sqlite+aiosqlite:///:memory:"; $env:GROQ_API_KEY="gsk_test"; $env:OWNER_IDS="1"; $env:ADMIN_IDS="1"; python -m scripts.test_tech_transfer_and_un_diplomacy
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from bot.database.base import Base
from bot.database.models import (
    Country,
    TechLicense,
    TechTransferRequest,
    User,
)
from bot.database.repositories import countries as countries_repo
from bot.database.repositories import tech_transfer as tech_repo
from bot.keyboards.united_nations import un_main_menu_kb
from bot.services import geo_service as geo
from bot.services import season_service
from bot.services.letter_image_service import render_diplomatic_letter_image
from bot.services.tech_service import (
    can_produce_equipment,
    get_equipment_origin,
    is_native_equipment,
    load_equipment_origins,
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


async def test_1_equipment_origins_coverage() -> None:
    print("\n🔍 تست ۱: پوشش ۱۰۰٪ بانک اطلاعاتی تجهیزات (data/equipment_origins.json)")
    countries_file = _ROOT / "data" / "countries.json"
    with open(countries_file, "r", encoding="utf-8") as f:
        data_json = json.load(f)
    countries_data = data_json.get("countries", [])

    origins_db = load_equipment_origins()
    check("بانک تجهیزات لود شد", len(origins_db) > 0, f"تعداد: {len(origins_db)}")

    unmapped = []
    total_physical = 0

    for country in countries_data:
        c_name = country.get("name_en", "")
        for m in country.get("military", []):
            name = m.get("name", "")
            if not name or m.get("category") == "سرباز آماده نبرد" or "پرسنل" in name:
                continue
            total_physical += 1
            origin = get_equipment_origin(name)
            if not origin:
                unmapped.append((c_name, name))

    check(
        f"پوشش کامل تمام {total_physical} قلم تجهیزات فیزیکی تمام ۳۹ کشور",
        len(unmapped) == 0,
        f"تجهیزات بدون کشور سازنده: {unmapped[:5]}",
    )
    check("تجهیز ایرانی شاهد ۱۳۶ به ایران متصل است", get_equipment_origin("Shahed-136") == "Iran")
    check("تجهیز آمریکایی F-35 به آمریکا متصل است", get_equipment_origin("F-35A") == "USA")
    check("تجهیز روسی S-400 به روسیه متصل است", get_equipment_origin("S-400") == "Russia")


async def test_2_and_3_tech_transfer_lifecycle(session: AsyncSession) -> None:
    print("\n🏭 تست ۲ و ۳: فلوی قفل بازتولید، درخواست، صدور فاکتور و اعطای لایسنس")

    # ساخت دو کشور ایران و سوریه برای سناریوی تست
    iran = Country(
        id=1,
        name_en="Iran",
        name_fa="ایران",
        flag="🇮🇷",
        region="middle_east",
        budget=200_000_000.0,
        is_claimed=True,
    )
    syria = Country(
        id=2,
        name_en="Syria",
        name_fa="سوریه",
        flag="🇸🇾",
        region="middle_east",
        budget=100_000_000.0,
        is_claimed=True,
    )
    session.add_all([iran, syria])
    await session.commit()

    # تست ۲: سوریه بدون لایسنس نباید بتواند شاهد ۱۳۶ تولید کند
    can_prod, origin = await can_produce_equipment(session, syria, "Shahed-136")
    check("تولید سلاح غیربومی (شاهد ۱۳۶) توسط سوریه بدون لایسنس ممنوع است", not can_prod and origin == "Iran")

    # ایران خودش سازنده است و باید بتواند سلاح بومی خودش را تولید کند
    can_prod_native, _ = await can_produce_equipment(session, iran, "Shahed-136")
    check("تولید سلاح بومی توسط خود کشور سازنده (ایران) مجاز است", can_prod_native)

    # تست ۳: چرخه ارسال درخواست و صدور فاکتور
    # ۳.۱ سوریه درخواست خرید لایسنس را برای ایران ارسال می‌کند
    req = await tech_repo.create_request(
        session=session,
        buyer_country_id=syria.id,
        seller_country_id=iran.id,
        equipment_name="Shahed-136",
        branch="air_attack_systems",
        category="پهپاد انتحاری",
    )
    await session.commit()
    check("درخواست با وضعیت PENDING_MANUFACTURER ایجاد شد", req.status == "PENDING_MANUFACTURER")

    # ۳.۲ درخواست در لیست دریافتی‌های ایران دیده می‌شود
    incoming = await tech_repo.list_incoming_requests(session, iran.id, status="PENDING_MANUFACTURER")
    check("درخواست در کارتابل تکنولوژی ایران قرار گرفت", len(incoming) == 1 and incoming[0].id == req.id)

    # ۳.۳ ایران قیمت ۵۰ میلیون دلار را تعیین کرده و فاکتور صادر می‌کند
    await tech_repo.set_invoice_price(session, req.id, 50_000_000.0)
    await session.commit()
    await session.refresh(req)
    check("وضعیت درخواست به INVOICE_SENT تغییر یافت", req.status == "INVOICE_SENT")
    check("قیمت فاکتور ۵۰ میلیون دلار ثبت شد", req.license_price == 50_000_000.0)

    # ۳.۴ فاکتور در کارتابل فاکتورهای سوریه قرار می‌گیرد
    invoices = await tech_repo.list_outgoing_requests(session, syria.id, status="INVOICE_SENT")
    check("فاکتور آماده پرداخت برای سوریه نمایش داده می‌شود", len(invoices) == 1)

    # ۳.۵ سوریه فاکتور را تایید و پرداخت می‌کند
    req_done, lic = await tech_repo.complete_transfer(session, req.id)
    await session.commit()
    await session.refresh(syria)
    await session.refresh(iran)

    check("وضعیت درخواست COMPLETED شد", req_done.status == "COMPLETED")
    check("لایسنس رسمی TechLicense صادر شد", lic is not None and lic.holder_country_id == syria.id)
    check("کسر ۵۰ میلیون دلار از بودجه سوریه", syria.budget == 50_000_000.0)
    check("واریز ۵۰ میلیون دلار به بودجه ایران", iran.budget == 250_000_000.0)

    # ۳.۶ اکنون سوریه مجاز است شاهد ۱۳۶ را در کارخانه نظامی بازتولید کند
    can_prod_now, _ = await can_produce_equipment(session, syria, "Shahed-136")
    check("پس از دریافت لایسنس، خط تولید شاهد ۱۳۶ برای سوریه آزاد شد", can_prod_now)

    # ۳.۷ تست لغو دستی لایسنس توسط گاد مود
    revoked = await tech_repo.revoke_license(session, lic.id)
    await session.commit()
    check("لایسنس با موفقیت لغو شد", revoked)
    can_prod_revoked, _ = await can_produce_equipment(session, syria, "Shahed-136")
    check("پس از لغو لایسنس، مجدداً خط تولید قفل شد", not can_prod_revoked)

    # ۳.۸ تست اعطای دستی لایسنس توسط گاد مود
    lic_god = await tech_repo.grant_license(session, syria.id, iran.id, "Shahed-136", price_paid=0.0)
    await session.commit()
    can_prod_god, _ = await can_produce_equipment(session, syria, "Shahed-136")
    check("اعطای مستقیم لایسنس توسط گاد مود خط تولید را آزاد کرد", can_prod_god and lic_god.id is not None)


async def test_4_un_diplomacy(session: AsyncSession) -> None:
    print("\n🇺🇳 تست ۴: دیپلماسی کامل سازمان ملل متحد (UN)")

    # ۴.۱ بررسی مختصات سازمان ملل در نیویورک
    geo_data = geo.get_geo("UN")
    check("سازمان ملل متحد دارای دیتای جغرافیایی است", geo_data is not None)
    coords = geo_data.get("coords") if geo_data else None
    check(
        "مقر سازمان ملل دارای مختصات جغرافیایی نیویورک است",
        coords is not None and abs(coords[0] - 40.7489) < 0.1,
    )

    # ۴.۲ محاسبه مدت پرواز دیپلماتیک به/از نیویورک
    flight_mins = geo.compute_flight_duration("UN", "Iran")
    check("مدت پرواز دیپلماتیک نیویورک به تهران محاسبه می‌شود", flight_mins > 0, f"مدت پرواز: {flight_mins} دقیقه")

    # ۴.۳ دکمه‌های دیپلماتیک در پنل مجمع عمومی سازمان ملل
    kb = un_main_menu_kb()
    all_callbacks = [
        btn.callback_data
        for row in kb.inline_keyboard
        for btn in row
        if btn.callback_data
    ]
    check("دکمه بیانیه رسمی دبیرکل (dip:speech) در پنل UN موجود است", "dip:speech" in all_callbacks)
    check("دکمه دیدار حضوری سفر (dip:meeting) در پنل UN موجود است", "dip:meeting" in all_callbacks)
    check("دکمه تماس تلفنی ۵ دقیقه‌ای (dip:call) در پنل UN موجود است", "dip:call" in all_callbacks)
    check("دکمه نامه رسمی گرافیکی (dip:letter) در پنل UN موجود است", "dip:letter" in all_callbacks)

    # ۴.۴ تست رندر گرافیکی سند رسمی نامه سازمان ملل متحد
    img_bytes = render_diplomatic_letter_image(
        letter_id=999,
        sender_country_name="سازمان ملل متحد",
        sender_flag="🇺🇳",
        sender_leader_name="دبیرکل سازمان ملل متحد",
        recipient_country_name="ایران",
        recipient_flag="🇮🇷",
        letter_type="ابلاغیه رسمی بین‌المللی",
        body="این یک سند رسمی دیپلماتیک از سوی دبیرخانه سازمان ملل متحد جهت آزمایش سیستم است.",
    )
    check("سند گرافیکی نامه دیپلماتیک سازمان ملل تولید شد", len(img_bytes) > 1000)
    check("فرمت تصویر خروجی معتبر PNG است", img_bytes.startswith(b"\x89PNG\r\n\x1a\n"))


async def test_5_season_reset_with_foreign_keys(engine, session: AsyncSession) -> None:
    print("\n🔴 تست ۵: ریست فصل با اجبار کامل کلیدهای خارجی (PRAGMA foreign_keys=ON)")

    # اطمینان از وجود رکوردهای لایسنس و درخواست در دیتابیس قبل از ریست
    lic_count = (await session.execute(select(TechLicense))).scalars().all()
    req_count = (await session.execute(select(TechTransferRequest))).scalars().all()
    check("دیتابیس دارای لایسنس و درخواست قبل از ریست است", len(lic_count) > 0 and len(req_count) > 0)

    # اجرای reset_season
    try:
        await season_service.reset_season(session)
        check("متد reset_season بدون بروز خطای کلید خارجی با موفقیت اجرا شد", True)
    except Exception as e:
        check("متد reset_season بدون خطا اجرا شد", False, str(e))

    # بررسی خالی شدن کامل جدول‌ها
    remaining_lic = (await session.execute(select(TechLicense))).scalars().all()
    remaining_req = (await session.execute(select(TechTransferRequest))).scalars().all()
    check("جدول tech_licenses کاملاً تخلیه شد", len(remaining_lic) == 0)
    check("جدول tech_transfer_requests کاملاً تخلیه شد", len(remaining_req) == 0)


async def main() -> None:
    print("=" * 60)
    print("🧪 آغاز تست جامع: سیستم انتقال تکنولوژی و دیپلماسی سازمان ملل")
    print("=" * 60)

    # تست ۱: بدون نیاز به دیتابیس
    await test_1_equipment_origins_coverage()

    # دیتابیس حافظه‌ای با اجبار کلیدهای خارجی
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )

    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON;"))
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with async_session() as session:
        await session.execute(text("PRAGMA foreign_keys = ON;"))
        await test_2_and_3_tech_transfer_lifecycle(session)
        await test_4_un_diplomacy(session)
        await test_5_season_reset_with_foreign_keys(engine, session)

    await engine.dispose()

    print("\n" + "=" * 60)
    if _failed:
        print(f"❌ {_passed} تست موفق، {len(_failed)} تست ناموفق:")
        for f in _failed:
            print(f"  • {f}")
        sys.exit(1)
    else:
        print(f"🎉 تمام {_passed} بررسی با موفقیت کامل پاس شدند! بدون هیچ خطایی.")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
