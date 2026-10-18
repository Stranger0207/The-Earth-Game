"""
تست جامع سیستم حمل‌ونقل دریایی، هوایی و زمینی + ژئوپلیتیک تنگه‌ها و اموال بلوکه‌شده (آپدیت‌های ۳ و ۱۱).

اجرا:
    python -m scripts.test_maritime_and_straits
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

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

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.constants import (
    AIR_TRANSPORT_FEE,
    FUEL_RESOURCES,
    LAND_TRANSPORT_FEE,
    LOCKABLE_FEATURES,
    SEA_TRANSPORT_FEE,
    STRAIT_HOLD_TIMEOUT_HOURS,
    STRAIT_TOLL_MAX,
)
from bot.database.base import Base
from bot.database.models import (
    BlockedCargo,
    Country,
    MilitarySale,
    Reserve,
    ResourceSale,
    StraitBlockRule,
    StraitConfig,
    User,
)
from bot.database.repositories import countries as countries_repo
from bot.database.repositories import reserves as reserves_repo
from bot.database.repositories import straits as straits_repo
from bot.database.repositories import trade as trade_repo
from bot.enums import (
    FeePayer,
    ResourceType,
    StraitBlockScope,
    TradeStatus,
    TransportMode,
)
from bot.services import economy_service
from bot.services import geo_service as geo
from bot.services import strait_service

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


async def setup_test_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    # اجبار بررسی کلیدهای خارجی برای شبیه‌سازی دقیق رفتار PostgreSQL
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON;"))
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    import bot.database.base as db_base
    import bot.scheduler.jobs as jobs_mod
    db_base.async_session_factory = session_factory
    jobs_mod.async_session_factory = session_factory

    return engine, session_factory


async def main():
    print("\n" + "=" * 65)
    print("🌊🚢 تست جامع آپدیت‌های ۳ و ۱۱: حمل‌ونقل و ژئوپلیتیک تنگه‌ها")
    print("=" * 65)

    # -------------------------------------------------------------
    # ۱. تست تعاریف تنگه‌ها و گراف دریایی (geo_service)
    # -------------------------------------------------------------
    print("\n[بخش ۱] بررسی تعاریف تنگه‌ها، کنترل‌کننده‌ها و مسیریابی دریایی:")

    straits = geo.list_all_strait_defs()
    check("تعداد تنگه‌های تعریف‌شده حداقل ۱۴ عدد است", len(straits) >= 14, f"len={len(straits)}")

    hormuz = geo.get_strait_def("hormuz")
    check("تنگه هرمز در لیست است و کنترل‌کننده آن ایران است", hormuz is not None and hormuz["controller"] == "Iran")

    suez = geo.get_strait_def("suez")
    check("کانال سوئز در لیست است و کنترل‌کننده آن مصر است", suez is not None and suez["controller"] == "Egypt")

    bab = geo.get_strait_def("bab_el_mandeb")
    check("تنگه باب‌المندب در لیست است و کنترل‌کننده آن یمن است", bab is not None and bab["controller"] == "Yemen")

    dover = geo.get_strait_def("dover")
    check("تنگه دوور در لیست است و کنترل‌کننده آن بریتانیا است", dover is not None and dover["controller"] == "Britain")

    gibraltar = geo.get_strait_def("gibraltar")
    check("تنگه جبل‌الطارق در لیست است و کنترل‌کننده آن اسپانیا است", gibraltar is not None and gibraltar["controller"] == "Spain")

    # بررسی دسترسی به دریا و کشورهای محصور در خشکی
    check("افغانستان محصور در خشکی است", geo.is_landlocked("Afghanistan"))
    check("سوئیس محصور در خشکی است", geo.is_landlocked("Switzerland"))
    check("ایران به دریا دسترسی دارد", not geo.is_landlocked("Iran"))
    check("آلمان به دریا دسترسی دارد", not geo.is_landlocked("Germany"))

    check("امکان حمل دریایی بین ایران و آلمان وجود دارد", geo.can_use_sea_transport("Iran", "Germany"))
    check("امکان حمل دریایی برای افغانستان وجود ندارد", not geo.can_use_sea_transport("Afghanistan", "Iran"))

    # مسیریابی دقیق تنگه‌ها در سفر دریایی
    # مسیر خلیج فارس به شمال اروپا: قطر/ایران به آلمان/بریتانیا
    route_straits = geo.get_route_straits("Qatar", "Germany")
    print(f"      مسیر قطر به آلمان: {route_straits}")
    check("مسیر دریایی قطر به آلمان شامل هرمز است", "hormuz" in route_straits)
    check("مسیر دریایی قطر به آلمان شامل باب‌المندب است", "bab_el_mandeb" in route_straits)
    check("مسیر دریایی قطر به آلمان شامل کانال سوئز است", "suez" in route_straits)
    check("مسیر دریایی قطر به آلمان شامل جبل‌الطارق است", "gibraltar" in route_straits)
    check("مسیر دریایی قطر به آلمان شامل دوور است", "dover" in route_straits)

    # مسیر روسیه (دریای آزوف/سیاه) به ایتالیا
    russia_route = geo.get_route_straits("Russia", "Italy")
    print(f"      مسیر روسیه به ایتالیا: {russia_route}")
    check("مسیر روسیه به ایتالیا شامل تنگه‌های کرچ یا بسفر/داردانل است", "bosphorus" in russia_route or "kerch" in russia_route)

    # مسیر محصور در خشکی هیچ مسیری ندارد
    afg_route = geo.get_route_straits("Afghanistan", "Iran")
    check("کشور محصور در خشکی هیچ تنگه دریایی را برنمی‌گرداند", afg_route == [])

    # -------------------------------------------------------------
    # ۲. تست قوانین انواع حمل‌ونقل و سوخت
    # -------------------------------------------------------------
    print("\n[بخش ۲] بررسی نرخ‌های عوارض و قوانین سوخت / زمین / هوا:")

    check("عوارض هوایی ۸ میلیون دلار است", AIR_TRANSPORT_FEE == 8_000_000)
    check("عوارض دریایی ۲ میلیون دلار است", SEA_TRANSPORT_FEE == 2_000_000)
    check("عوارض ترانزیت زمینی ۵ میلیون دلار است", LAND_TRANSPORT_FEE == 5_000_000)

    check("منابع سوختی شامل نفت، گاز، زغال‌سنگ و اورانیوم است",
          ResourceType.OIL in FUEL_RESOURCES and
          ResourceType.GAS in FUEL_RESOURCES and
          ResourceType.COAL in FUEL_RESOURCES and
          ResourceType.URANIUM in FUEL_RESOURCES)

    # شبیه‌سازی فرم انتخاب روش ارسال
    # الف) برای سوخت با کشور محصور در خشکی (عربستان به افغانستان):
    is_fuel = ResourceType.OIL in FUEL_RESOURCES
    is_coastal_possible = geo.can_use_sea_transport("Saudi Arabia", "Afghanistan")
    allowed_modes_fuel_landlocked = []
    if is_coastal_possible:
        allowed_modes_fuel_landlocked.append(TransportMode.SEA)
    if not is_fuel:
        allowed_modes_fuel_landlocked.append(TransportMode.AIR)
    allowed_modes_fuel_landlocked.append(TransportMode.LAND)

    check("برای سوخت به افغانستان، حمل هوایی ممنوع و حمل دریایی ناممکن است (فقط زمینی)",
          allowed_modes_fuel_landlocked == [TransportMode.LAND])

    # ب) برای منابع غیر سوختی با دو کشور ساحلی (فولاد از ایران به آلمان):
    is_fuel = ResourceType.STEEL in FUEL_RESOURCES
    is_coastal_possible = geo.can_use_sea_transport("Iran", "Germany")
    allowed_modes_steel_coastal = []
    if is_coastal_possible:
        allowed_modes_steel_coastal.append(TransportMode.SEA)
    if not is_fuel:
        allowed_modes_steel_coastal.append(TransportMode.AIR)
    allowed_modes_steel_coastal.append(TransportMode.LAND)

    # ج) برای سوخت بین دو کشور ساحلی (ایران به آلمان):
    is_fuel = ResourceType.OIL in FUEL_RESOURCES
    is_coastal_possible = geo.can_use_sea_transport("Iran", "Germany")
    allowed_modes_fuel_coastal = []
    if is_coastal_possible:
        allowed_modes_fuel_coastal.append(TransportMode.SEA)
    if not is_fuel:
        allowed_modes_fuel_coastal.append(TransportMode.AIR)
    if not is_fuel or (geo.is_landlocked("Iran") or geo.is_landlocked("Germany")):
        allowed_modes_fuel_coastal.append(TransportMode.LAND)

    check("برای سوخت بین دو کشور ساحلی، ترانزیت زمینی غیرفعال است (فقط دریایی مجاز است)",
          allowed_modes_fuel_coastal == [TransportMode.SEA])

    # -------------------------------------------------------------
    # ۳. تست پایگاه‌داده و مخازن تنگه‌ها (straits_repo)
    # -------------------------------------------------------------
    print("\n[بخش ۳] بررسی تنظیمات تنگه‌ها، مسدودسازی و عوارض عبور در دیتابیس:")

    engine, session_factory = await setup_test_engine()

    async with session_factory() as session:
        # ساخت کاربران و کشورهای تستی
        u1 = User(telegram_id=101, username="u101", first_name="Iran Leader")
        u2 = User(telegram_id=102, username="u102", first_name="Germany Leader")
        u3 = User(telegram_id=103, username="u103", first_name="Qatar Leader")
        session.add_all([u1, u2, u3])
        await session.flush()

        iran = Country(id=1, name_fa="ایران", name_en="Iran", flag="🇮🇷", region="middle_east", budget=100_000_000, owner_user_id=101)
        germany = Country(id=2, name_fa="آلمان", name_en="Germany", flag="🇩🇪", region="europe", budget=200_000_000, owner_user_id=102)
        qatar = Country(id=3, name_fa="قطر", name_en="Qatar", flag="🇶🇦", region="middle_east", budget=300_000_000, owner_user_id=103)
        session.add_all([iran, germany, qatar])
        await session.flush()

        # تست مقداردهی اولیه تنگه‌ها
        await straits_repo.ensure_default_straits(session)
        iran_straits = await straits_repo.list_straits_by_controller(session, "Iran")
        check("تنگه‌های تحت حاکمیت ایران بارگذاری شدند", len(iran_straits) >= 1 and iran_straits[0].strait_id == "hormuz")

        # تغییر عوارض عمومی تنگه هرمز
        hormuz_cfg = await straits_repo.get_strait_config(session, "hormuz")
        check("کانفیگ تنگه هرمز وجود دارد", hormuz_cfg is not None)
        await straits_repo.update_strait_config(session, "hormuz", default_toll=500_000)
        hormuz_cfg = await straits_repo.get_strait_config(session, "hormuz")
        check("عوارض عمومی هرمز به ۵۰۰ هزار دلار تغییر یافت", hormuz_cfg.default_toll == 500_000)

        # تعیین عوارض اختصاصی برای آلمان
        await straits_repo.set_block_rule(session, "hormuz", germany.id, is_blocked=False, custom_toll=1_200_000)
        tolls_map = await straits_repo.calculate_route_tolls(session, ["hormuz"], germany.id)
        total_toll = sum(tolls_map.values())
        check("عوارض اختصاصی آلمان در هرمز ۱.۲ میلیون دلار محاسبه شد", total_toll == 1_200_000)

        # مسدودسازی سفارشی برای یک کشور
        await straits_repo.update_strait_config(session, "hormuz", is_blocked=True, block_scope=StraitBlockScope.CUSTOM.value)
        await straits_repo.set_block_rule(session, "hormuz", germany.id, is_blocked=True)

        blocked_strait = await straits_repo.get_first_blocked_strait(
            session, ["hormuz"], seller_id=qatar.id, buyer_id=germany.id
        )
        check("تنگه هرمز برای کشور آلمان مسدود تشخیص داده شد", blocked_strait == "hormuz")

        blocked_strait_iran = await straits_repo.get_first_blocked_strait(
            session, ["hormuz"], seller_id=qatar.id, buyer_id=iran.id
        )
        check("تنگه هرمز برای کشور ایران مسدود نیست", blocked_strait_iran is None)

        # رفع انسداد
        await straits_repo.update_strait_config(session, "hormuz", is_blocked=False, block_scope=StraitBlockScope.NONE.value)
        blocked_after = await straits_repo.get_first_blocked_strait(
            session, ["hormuz"], seller_id=qatar.id, buyer_id=germany.id
        )
        check("پس از رفع انسداد، تنگه هرمز باز است", blocked_after is None)

        await session.commit()

    # -------------------------------------------------------------
    # ۴. تست تسویه مالی معامله (transfer_sale) با پرداخت‌کننده عوارض و واریز به حاکمان تنگه
    # -------------------------------------------------------------
    print("\n[بخش ۴] تست تسویه مالی معامله با عوارض حمل‌ونقل و تنگه‌ها:")

    async with session_factory() as session:
        iran = await session.get(Country, 1)
        germany = await session.get(Country, 2)
        qatar = await session.get(Country, 3)

        initial_iran_budget = iran.budget
        initial_qatar_budget = qatar.budget
        initial_germany_budget = germany.budget

        await reserves_repo.ensure_reserve(session, qatar.id, ResourceType.OIL.value)
        await reserves_repo.add_amount(session, qatar.id, ResourceType.OIL.value, 50_000)

        # ایجاد رکورد معامله تستی: قطر (فروشنده) به آلمان (خریدار)
        # حمل دریایی: عوارض ۲ میلیون دلار + عوارض هرمز ۵۰۰ هزار دلار
        # پرداخت‌کننده: فروشنده (قطر)
        # قیمت معامله: ۲۰ میلیون دلار
        sale_seller_pays = ResourceSale(
            id=10,
            seller_country=qatar.id,
            buyer_country=germany.id,
            resource=ResourceType.OIL.value,
            amount=5000,
            price=20_000_000,
            status=TradeStatus.PENDING.value,
            transport_mode="SEA",
            fee_payer="SELLER",
            transport_fee=2_000_000,
            strait_toll_fee=500_000,
        )
        session.add(sale_seller_pays)
        await session.flush()

        strait_tolls = {"hormuz": 500_000.0}

        # انجام انتقال
        await economy_service.transfer_sale(
            session,
            sale_seller_pays.seller_country,
            sale_seller_pays.buyer_country,
            sale_seller_pays.resource,
            sale_seller_pays.amount,
            sale_seller_pays.price,
            transport_fee=2_000_000,
            fee_payer="SELLER",
            strait_tolls=strait_tolls,
        )

        check("عوارض تنگه هرمز مستقیماً به خزانه ایران واریز شد", iran.budget == initial_iran_budget + 500_000)
        # خریدار (آلمان) مبلغ ۲۰ میلیون پرداخت کرده
        check("از خریدار فقط مبلغ معامله کسر شد", germany.budget == initial_germany_budget - 20_000_000)
        # فروشنده (قطر) مبلغ ۲۰ میلیون دریافت کرده ولی ۲ میلیون حمل + ۵۰۰ هزار عوارض پرداخت کرده (خالص: +۱۷.۵ میلیون)
        check("از فروشنده عوارض حمل‌ونقل و تنگه کسر شد", qatar.budget == initial_qatar_budget + 20_000_000 - 2_500_000)

        # تست حالت دوم: پرداخت عوارض توسط خریدار
        iran.budget = initial_iran_budget
        germany.budget = initial_germany_budget
        qatar.budget = initial_qatar_budget

        sale_buyer_pays = ResourceSale(
            id=11,
            seller_country=qatar.id,
            buyer_country=germany.id,
            resource=ResourceType.OIL.value,
            amount=5000,
            price=20_000_000,
            status=TradeStatus.PENDING.value,
            transport_mode="SEA",
            fee_payer="BUYER",
            transport_fee=2_000_000,
            strait_toll_fee=500_000,
        )
        session.add(sale_buyer_pays)
        await session.flush()

        await economy_service.transfer_sale(
            session,
            sale_buyer_pays.seller_country,
            sale_buyer_pays.buyer_country,
            sale_buyer_pays.resource,
            sale_buyer_pays.amount,
            sale_buyer_pays.price,
            transport_fee=2_000_000,
            fee_payer="BUYER",
            strait_tolls=strait_tolls,
        )

        check("عوارض تنگه در حالت پرداخت توسط خریدار به حاکم تنگه واریز شد", iran.budget == initial_iran_budget + 500_000)
        # خریدار: ۲۰ میلیون قیمت + ۲ میلیون حمل + ۵۰۰ هزار عوارض = ۲۲.۵ میلیون کسر شده
        check("از خریدار هم قیمت و هم عوارض حمل و تنگه کسر شد", germany.budget == initial_germany_budget - 22_500_000)
        # فروشنده: تمام ۲۰ میلیون قیمت را دریافت کرده
        check("فروشنده مبلغ کامل را بدون کسر عوارض دریافت کرد", qatar.budget == initial_qatar_budget + 20_000_000)

        await session.commit()

    # -------------------------------------------------------------
    # ۵. تست سیستم توقیف، انهدام، مصادره و اموال بلوکه‌شده در تنگه (strait_service)
    # -------------------------------------------------------------
    print("\n[بخش ۵] تست توقیف در تنگه، صدور اجازه عبور، انهدام و پنل اموال بلوکه‌شده:")

    fake_bot = AsyncMock()

    async with session_factory() as session:
        iran = await session.get(Country, 1)
        germany = await session.get(Country, 2)
        qatar = await session.get(Country, 3)

        # ساخت محموله در حال حرکت
        sale = ResourceSale(
            id=20,
            seller_country=qatar.id,
            buyer_country=germany.id,
            resource=ResourceType.OIL.value,
            amount=10_000,
            price=40_000_000,
            status=TradeStatus.IN_TRANSIT.value,
            transport_mode="SEA",
            ship_eta=_utcnow() + timedelta(hours=5),
        )
        session.add(sale)
        await session.flush()

        # ۱) توقیف محموله در تنگه هرمز توسط ایران
        await strait_service.hold_shipment_at_strait(fake_bot, session, sale, "hormuz")
        check("وضعیت محموله به HELD_AT_STRAIT تغییر یافت", sale.strait_status == "HELD_AT_STRAIT")
        check("شناسه تنگه توقیف‌کننده ثبت شد", sale.held_at_strait_id == "hormuz")
        check("زمان توقیف ثبت شد", sale.held_since is not None)

        # ۲) اقدام اول: صدور اجازه عبور
        res_allow = await strait_service.allow_passage(fake_bot, session, sale.id, "hormuz", iran)
        check("اجازه عبور صادر شد", res_allow["status"] == "allowed")
        check("وضعیت محموله به PASSED و IN_TRANSIT تغییر یافت", sale.strait_status == "PASSED" and sale.status == TradeStatus.IN_TRANSIT.value)

        # ۳) اقدام دوم: انهدام و غرق کشتی
        sale.strait_status = "HELD_AT_STRAIT"
        sale.held_at_strait_id = "hormuz"
        sale.held_since = _utcnow()
        sale.warning_count = 1
        await session.flush()

        # فرمان شلیک قبل از ۳ اخطار باید خطا دهد
        try:
            await strait_service.destroy_shipment(fake_bot, session, sale.id, "hormuz", iran)
            check("فرمان شلیک قبل از ۳ اخطار رد شد", False)
        except strait_service.StraitError:
            check("فرمان شلیک قبل از ۳ اخطار رد شد", True)

        # افزایش اخطار به ۳ و شلیک موفق
        sale.warning_count = 3
        await session.flush()
        res_destroy = await strait_service.destroy_shipment(fake_bot, session, sale.id, "hormuz", iran)
        check("کشتی پس از ۳ اخطار با موفقیت منهدم شد", res_destroy["status"] == "destroyed")
        check("وضعیت محموله DESTROYED و معامله REJECTED شد", sale.strait_status == "DESTROYED" and sale.status == TradeStatus.REJECTED.value)

        # پس از انهدام، ثبت اخطار یا دستورات دیگر باید خطا دهد
        try:
            await strait_service.issue_strait_warning(fake_bot, session, sale.id, "hormuz", iran)
            check("صدور اخطار به کشتی منهدم‌شده رد شد", False)
        except strait_service.StraitError:
            check("صدور اخطار به کشتی منهدم‌شده رد شد", True)

        # ۴) اقدام سوم: مصادره مستقیم به ذخایر خودی
        sale.strait_status = "HELD_AT_STRAIT"
        sale.held_at_strait_id = "hormuz"
        sale.held_since = _utcnow()
        sale.warning_count = 2
        await session.flush()

        # مصادره قبل از ۳ اخطار باید خطا دهد
        try:
            await strait_service.confiscate_shipment(fake_bot, session, sale.id, "hormuz", iran, to_blocked_assets=False)
            check("مصادره بار قبل از ۳ اخطار رد شد", False)
        except strait_service.StraitError:
            check("مصادره بار قبل از ۳ اخطار رد شد", True)

        # با ۳ اخطار مصادره موفق است
        sale.warning_count = 3
        await session.flush()
        res_confiscate_direct = await strait_service.confiscate_shipment(
            fake_bot, session, sale.id, "hormuz", iran, to_blocked_assets=False
        )
        check("کشتی با ۳ اخطار مستقیماً مصادره شد", res_confiscate_direct["status"] == "confiscated")
        iran_reserves = await reserves_repo.get_reserve(session, iran.id, ResourceType.OIL.value)
        check("نفت مصادره شده به ذخایر ایران افزوده شد", iran_reserves is not None and iran_reserves.amount >= 10_000)

        # ۵) اقدام چهارم: مصادره و انتقال به اموال بلوکه‌شده
        sale2 = ResourceSale(
            id=21,
            seller_country=qatar.id,
            buyer_country=germany.id,
            resource=ResourceType.STEEL.value,
            amount=3_000,
            price=15_000_000,
            status=TradeStatus.IN_TRANSIT.value,
            transport_mode="SEA",
            strait_status="HELD_AT_STRAIT",
            held_at_strait_id="hormuz",
            held_since=_utcnow(),
            warning_count=3,
        )
        session.add(sale2)
        await session.flush()

        res_confiscate_blocked = await strait_service.confiscate_shipment(
            fake_bot, session, sale2.id, "hormuz", iran, to_blocked_assets=True
        )
        check("کشتی به اموال بلوکه‌شده منتقل شد", res_confiscate_blocked["status"] == "confiscated" and res_confiscate_blocked["to_blocked"])

        blocked_list = await straits_repo.list_blocked_cargos_by_holding(session, iran.id)
        check("رکورد اموال بلوکه‌شده برای ایران ثبت شده است", len(blocked_list) >= 1)
        cargo_record = blocked_list[0]
        check("منبع بلوکه‌شده فولاد به میزان ۳۰۰۰ واحد است", cargo_record.resource == ResourceType.STEEL.value and cargo_record.amount == 3000)

        # ۶) تست ۳ دکمه پنل اموال بلوکه‌شده:
        # دکمه الف: ادعای مالکیت و انتقال به انبار خودی
        res_claim = await strait_service.claim_blocked_cargo_to_reserves(fake_bot, session, cargo_record.id, iran)
        check("مالکیت مال بلوکه‌شده ادعا و به انبار خودی منتقل شد", res_claim["status"] == "claimed")
        iran_steel = await reserves_repo.get_reserve(session, iran.id, ResourceType.STEEL.value)
        check("فولاد به ذخایر ایران افزوده شد", iran_steel is not None and iran_steel.amount >= 3000)

        # دکمه ب: عودت به کشور مبدأ (فروشنده)
        cargo_return = await straits_repo.add_blocked_cargo(
            session,
            holding_country_id=iran.id,
            source_country_id=qatar.id,
            dest_country_id=germany.id,
            resource=ResourceType.GAS.value,
            amount=8_000,
            strait_id="hormuz",
        )
        res_ret = await strait_service.return_blocked_cargo_to_source(fake_bot, session, cargo_return.id, iran)
        check("مال بلوکه‌شده با موفقیت به فروشنده (قطر) بازگردانده شد", res_ret["status"] == "returned")
        qatar_gas = await reserves_repo.get_reserve(session, qatar.id, ResourceType.GAS.value)
        check("گاز به ذخایر قطر عودت داده شد", qatar_gas is not None and qatar_gas.amount >= 8_000)

        # دکمه ج: امحا و نابودی مال بلوکه‌شده
        cargo_destroy = await straits_repo.add_blocked_cargo(
            session,
            holding_country_id=iran.id,
            source_country_id=qatar.id,
            dest_country_id=germany.id,
            resource=ResourceType.GOLD.value,
            amount=500,
            strait_id="hormuz",
        )
        res_dest_cargo = await strait_service.destroy_blocked_cargo(fake_bot, session, cargo_destroy.id, iran)
        check("مال بلوکه‌شده با موفقیت منهدم شد", res_dest_cargo["status"] == "destroyed")
        check("رکورد مال بلوکه‌شده از دیتابیس حذف گردید", await straits_repo.get_blocked_cargo(session, cargo_destroy.id) is None)

        await session.commit()

    # -------------------------------------------------------------
    # ۶. تست جاب اسکدولر (process_shipments) و مهلت ۲۴ ساعته
    # -------------------------------------------------------------
    print("\n[بخش ۶] تست اسکدولر تحویل محموله‌ها و عودت خودکار پس از ۲۴ ساعت توقیف:")

    from bot.scheduler.jobs import process_shipments

    async with session_factory() as session:
        # الف) محموله‌ای که هنوز در مهلت ۲۴ ساعت است (۲ ساعت گذشته)
        sale_held_recent = ResourceSale(
            id=30,
            seller_country=3,
            buyer_country=2,
            resource=ResourceType.OIL.value,
            amount=1000,
            price=5_000_000,
            status=TradeStatus.IN_TRANSIT.value,
            transport_mode="SEA",
            strait_status="HELD_AT_STRAIT",
            held_at_strait_id="hormuz",
            held_since=_utcnow() - timedelta(hours=2),
            ship_eta=_utcnow() - timedelta(hours=1),  # زمان ETA گذشته ولی در تنگه متوقف است!
        )
        # ب) محموله‌ای که بیش از ۲۴ ساعت در تنگه رها شده (۲۵ ساعت گذشته)
        sale_held_expired = ResourceSale(
            id=31,
            seller_country=3,
            buyer_country=2,
            resource=ResourceType.COAL.value,
            amount=2000,
            price=4_000_000,
            status=TradeStatus.IN_TRANSIT.value,
            transport_mode="SEA",
            strait_status="HELD_AT_STRAIT",
            held_at_strait_id="hormuz",
            held_since=_utcnow() - timedelta(hours=25),
            ship_eta=_utcnow() - timedelta(hours=20),
        )
        session.add_all([sale_held_recent, sale_held_expired])
        await session.commit()

    # اجرای جاب تحویل
    await process_shipments(fake_bot)

    async with session_factory() as session:
        s_recent = await session.get(ResourceSale, 30)
        s_expired = await session.get(ResourceSale, 31)

        check("محموله متوقف‌شده کمتر از ۲۴ ساعت تحویل داده نشد و همچنان متوقف ماند",
              s_recent.strait_status == "HELD_AT_STRAIT" and s_recent.status == TradeStatus.IN_TRANSIT.value)

        check("محموله متوقف‌شده بیش از ۲۴ ساعت به وضعیت RETURNED و REJECTED تغییر کرد",
              s_expired.strait_status == "RETURNED" and s_expired.status == TradeStatus.REJECTED.value)

        qatar_coal = await reserves_repo.get_reserve(session, 3, ResourceType.COAL.value)
        check("ذخایر محموله منقضی‌شده به کشور فروشنده (قطر) بازگردانده شد",
              qatar_coal is not None and qatar_coal.amount >= 2000)

    # -------------------------------------------------------------
    # ۷. تست ریست فصل و یکپارچگی کلیدهای خارجی (season_service)
    # -------------------------------------------------------------
    print("\n[بخش ۷] تست پاک‌سازی فصلی جدول‌های تنگه بدون خطای کلید خارجی:")

    from bot.services import season_service

    async with session_factory() as session:
        # درج رکوردهای اضافی
        cargo_dummy = BlockedCargo(
            holding_country_id=1,
            source_country_id=3,
            dest_country_id=2,
            resource=ResourceType.IRON.value,
            amount=1000,
            strait_id="hormuz",
        )
        rule_dummy = StraitBlockRule(
            strait_id="hormuz",
            target_country_id=2,
        )
        session.add_all([cargo_dummy, rule_dummy])
        await session.commit()

        # اجرای ریست فصل
        try:
            await season_service.reset_season(session)
            check("ریست فصل بدون نقض Foreign Key انجام شد", True)
        except Exception as exc:
            check("ریست فصل بدون نقض Foreign Key انجام شد", False, f"Exception: {exc}")

        # اطمینان از پاک شدن جدول‌ها
        res_cargos = await session.execute(select(BlockedCargo))
        res_rules = await session.execute(select(StraitBlockRule))
        res_configs = await session.execute(select(StraitConfig))

        check("جدول BlockedCargo به طور کامل پاک شد", len(res_cargos.scalars().all()) == 0)
        check("جدول StraitBlockRule به طور کامل پاک شد", len(res_rules.scalars().all()) == 0)
        check("جدول StraitConfig به طور کامل پاک شد", len(res_configs.scalars().all()) == 0)

    # -------------------------------------------------------------
    # ۸. تست سیستم رویارویی تنگه‌ها، اخطار سه‌گانه و تصمیمات تاکتیکی
    # -------------------------------------------------------------
    print("\n[بخش ۸] تست سیستم رویارویی تنگه‌ها، اخطار سه‌گانه و کنش‌های تاکتیکی:")

    async with session_factory() as session:
        # ۱) تست محاسبات هندسی پیشرفت تنگه و زمان دریانوردی
        qa_waypoints = geo.get_maritime_waypoints("Qatar", "India")
        check("تعداد وی‌پوینت‌های قطر به هند بیش از ۳ نقطه است", len(qa_waypoints) >= 3)

        prog_h = geo.get_strait_transit_progress(qa_waypoints, "hormuz")
        check("پیشرفت تنگه هرمز در مسیر قطر به هند شناسایی شد", prog_h is not None)
        if prog_h:
            check("درصد دهانه ورودی کمتر از درصد مرکز است", prog_h["approach_ratio"] <= prog_h["center_ratio"])
            check("درصد مرکز کمتر یا مساوی درصد خروجی است", prog_h["center_ratio"] <= prog_h["exit_ratio"])
            check("مختصات دهانه ورودی لنگرگاه معتبر است", len(prog_h["approach_coords"]) == 2)

        transit_min = geo.calculate_maritime_transit_minutes("Qatar", "India")
        check("زمان ناوبری قطر به هند حداقل ۶۰ دقیقه است", transit_min >= 60)

        # ۲) درج کشورهای تست و محموله
        qatar_c = await countries_repo.get_country_by_name(session, "Qatar")
        india_c = await countries_repo.get_country_by_name(session, "India")
        iran_c = await countries_repo.get_country_by_name(session, "Iran")

        sale_standoff = ResourceSale(
            id=50,
            seller_country=qatar_c.id if qatar_c else 3,
            buyer_country=india_c.id if india_c else 2,
            resource=ResourceType.GAS.value,
            amount=5000,
            price=20_000_000,
            status=TradeStatus.IN_TRANSIT.value,
            transport_mode="SEA",
            strait_status="APPROACHING",
            standoff_action="SAILING",
            warning_count=0,
            ship_eta=_utcnow() + timedelta(minutes=transit_min),
        )
        session.add(sale_standoff)
        await session.commit()

        # ۳) تست فعال‌سازی رویارویی در دهانه تنگه (trigger_strait_standoff)
        await strait_service.trigger_strait_standoff(fake_bot, session, sale_standoff, "hormuz")
        check("وضعیت پس از ورود به حریم دهانه HELD_AT_STRAIT شد", sale_standoff.strait_status == "HELD_AT_STRAIT")
        check("کنش رویارویی روی STANDOFF قرار گرفت", sale_standoff.standoff_action == "STANDOFF")
        check("زمان باقیمانده سفر قبل از توقف ذخیره شد", sale_standoff.remaining_seconds is not None and sale_standoff.remaining_seconds > 0)
        check("حین استندآف زمان رسیدن صفر/متوقف شد", sale_standoff.ship_eta is None)

        # ۴) تست توالی اخطارهای سه‌گانه حاکم تنگه
        warn1 = await strait_service.issue_strait_warning(fake_bot, session, sale_standoff.id, "hormuz", iran_c)
        check("اخطار اول با موفقیت ثبت شد", warn1["warning_count"] == 1 and sale_standoff.warning_count == 1)

        warn2 = await strait_service.issue_strait_warning(fake_bot, session, sale_standoff.id, "hormuz", iran_c)
        check("اخطار دوم با موفقیت ثبت شد", warn2["warning_count"] == 2 and sale_standoff.warning_count == 2)

        warn3 = await strait_service.issue_strait_warning(fake_bot, session, sale_standoff.id, "hormuz", iran_c)
        check("اخطار سوم (اولتیماتوم) با موفقیت ثبت شد", warn3["warning_count"] == 3 and sale_standoff.warning_count == 3)

        # اخطار چهارم باید رد شود چون سقف ۳ اخطار پر شده
        try:
            await strait_service.issue_strait_warning(fake_bot, session, sale_standoff.id, "hormuz", iran_c)
            check("اخطار بیش از ۳ بار رد شد", False)
        except strait_service.StraitError:
            check("اخطار بیش از ۳ بار رد شد", True)

        # ۵) تست تصمیم صاحب بار: توقف و لنگراندازی در دهانه (Hold)
        res_hold = await strait_service.owner_hold_at_strait(fake_bot, session, sale_standoff.id, qatar_c)
        check("دستور توقف و لنگراندازی اعمال شد", res_hold["status"] == "holding" and sale_standoff.standoff_action == "HOLD")

        # ۶) تست تصمیم صاحب بار: شکستن محاصره و تلاش برای عبور (Run)
        res_run = await strait_service.owner_run_blockade(fake_bot, session, sale_standoff.id, qatar_c)
        check("دستور ادامه مسیر و شکستن محاصره اعمال شد", res_run["status"] == "running" and sale_standoff.standoff_action == "RUNNING")
        check("زمان رسیدن پس از شروع حرکت مجدد فعال شد", sale_standoff.ship_eta is not None and sale_standoff.ship_eta > _utcnow())

        # ۷) تست صدور اجازه عبور و رفع باگ ETA
        res_allow_pass = await strait_service.allow_passage(fake_bot, session, sale_standoff.id, "hormuz", iran_c)
        check("اجازه عبور صادر شد", res_allow_pass["status"] == "allowed")
        check("وضعیت به PASSED تغییر یافت", sale_standoff.strait_status == "PASSED")
        check("باگ رفع شد: ship_eta در آینده تنظیم شد و None نیست", sale_standoff.ship_eta is not None and sale_standoff.ship_eta > _utcnow())

        # ۸) تست مصونیت پس از خروج از تنگه: حاکم دیگر نمی‌تواند شلیک کند
        try:
            await strait_service.fire_at_shipment(fake_bot, session, sale_standoff.id, "hormuz", iran_c)
            check("شلیک به کشتی عبور کرده با موفقیت مسدود شد (مصونیت)", False)
        except strait_service.StraitError:
            check("شلیک به کشتی عبور کرده با موفقیت مسدود شد (مصونیت)", True)

        # ۹) تست تصمیم صاحب بار: عقب‌نشینی به کشور مبدأ (Retreat)
        sale_retreat = ResourceSale(
            id=51,
            seller_country=qatar_c.id if qatar_c else 3,
            buyer_country=india_c.id if india_c else 2,
            resource=ResourceType.OIL.value,
            amount=2000,
            price=8_000_000,
            status=TradeStatus.IN_TRANSIT.value,
            transport_mode="SEA",
            strait_status="HELD_AT_STRAIT",
            standoff_action="STANDOFF",
            warning_count=2,
            held_at_strait_id="hormuz",
            held_since=_utcnow(),
        )
        session.add(sale_retreat)
        await session.commit()

        res_ret = await strait_service.owner_retreat_from_strait(fake_bot, session, sale_retreat.id, qatar_c)
        check("دستور عقب‌نشینی ثبت شد", res_ret["status"] == "returning" and sale_retreat.standoff_action == "RETURNING")
        check("وضعیت ترانزیت به RETURNING تغییر یافت", sale_retreat.strait_status == "RETURNING")

        # حاکم تنگه نباید بتواند به کشتی که تمکین کرده و در حال عقب‌نشینی است حمله کند
        try:
            await strait_service.fire_at_shipment(fake_bot, session, sale_retreat.id, "hormuz", iran_c)
            check("شلیک به کشتی در حال عقب‌نشینی رد شد", False)
        except strait_service.StraitError:
            check("شلیک به کشتی در حال عقب‌نشینی رد شد", True)

        # -------------------------------------------------------------
        # [بخش ۹] تست محموله دریایی امارات به هند و هندلر پذیرش معامله (رفع باگ لاگ و متغیر rname)
        # -------------------------------------------------------------
        print("\n[بخش ۹] تست محموله دریایی امارات به هند و لاگ معامله در گروه لاگ:")
        from bot.services import geo_service as geo_svc
        from unittest.mock import patch, MagicMock

        # ۱. تست گیت‌وی و عبور امارات به هند از تنگه هرمز
        straits_uae_in = geo_svc.get_route_straits("UAE", "India")
        check("مسیر دریایی امارات به هند شامل تنگه هرمز است", "hormuz" in straits_uae_in)

        straits_in_uae = geo_svc.get_route_straits("India", "UAE")
        check("مسیر دریایی هند به امارات شامل تنگه هرمز است", "hormuz" in straits_in_uae)

        wp_uae_in = geo_svc.get_maritime_waypoints("UAE", "India")
        check("وی‌پوینت‌های امارات به هند از مسیر آب‌های خلیج فارس عبور می‌کنند", len(wp_uae_in) >= 8)

        # ۲. ایجاد رکورد فروش امارات به هند برای تست cb_sale_accept
        u_uae = User(telegram_id=104, username="uae_leader", first_name="UAE Leader")
        u_india = User(telegram_id=105, username="india_leader", first_name="India Leader")
        session.add_all([u_uae, u_india])
        await session.commit()

        uae_c = Country(
            name_en="UAE",
            name_fa="امارات متحده عربی",
            flag="🇦🇪",
            region="middle_east",
            owner_user_id=104,
            budget=50_000_000.0,
        )
        india_c = Country(
            name_en="India",
            name_fa="هند",
            flag="🇮🇳",
            region="asia",
            owner_user_id=105,
            budget=50_000_000.0,
        )
        session.add_all([uae_c, india_c])
        await session.commit()

        # ذخایر نفت امارات
        res_oil = Reserve(country_id=uae_c.id, resource=ResourceType.OIL.value, amount=5000.0)
        session.add(res_oil)
        await session.commit()

        sale_sea = ResourceSale(
            seller_country=uae_c.id,
            buyer_country=india_c.id,
            resource=ResourceType.OIL.value,
            amount=1000.0,
            price=15_000_000.0,
            transport_mode="SEA",
            fee_payer="SELLER",
            transport_fee=2_000_000.0,
            status=TradeStatus.PENDING,
        )
        session.add(sale_sea)
        await session.commit()

        from bot.handlers.economy import cb_sale_accept

        call_mock = MagicMock()
        call_mock.data = f"sale_accept:{sale_sea.id}"
        call_mock.answer = AsyncMock()
        call_mock.message = MagicMock()
        call_mock.message.html_text = "پیشنهاد خرید نفت"

        mock_send_log = AsyncMock()
        mock_send_photo_news = AsyncMock()
        mock_safe_edit = AsyncMock()

        with patch("bot.handlers.economy.send_log", mock_send_log), \
             patch("bot.handlers.economy.send_photo_news", mock_send_photo_news), \
             patch("bot.handlers.economy.safe_edit", mock_safe_edit), \
             patch("bot.handlers.economy.bot.send_message", AsyncMock()):
            # فراخوانی هندلر با شیوه دریایی — نباید به خاطر متغیر rname یا unit_fa خطا دهد
            await cb_sale_accept(call_mock, session, u_india)

        await session.refresh(sale_sea)
        check("وضعیت محموله دریایی به IN_TRANSIT تغییر یافت", sale_sea.status == TradeStatus.IN_TRANSIT)
        check("تنگه هرمز در وضعیت تنگه‌ای محموله شناسایی شد", sale_sea.strait_status == "APPROACHING")
        check("لاگ خرید به گروه لاگ ارسال شد (send_log فراخوانی شد)", mock_send_log.called)
        
        # بررسی محتوای لاگ ارسال‌شده
        log_text = mock_send_log.call_args[0][1]
        check("متن لاگ شامل عنوان گزارش تجارت است", "گزارش تجارت" in log_text)
        check("متن لاگ شامل شیوه حمل دریایی است", "دریایی" in log_text)
        check("متن لاگ شامل نام نفت و بشکه است", "نفت" in log_text and "بشکه" in log_text)

        # بررسی کپشن سازمان WTO
        check("خبر WTO فراخوانی شد", mock_send_photo_news.called)
        wto_caption = mock_send_photo_news.call_args[0][3]
        check("خبر WTO شامل ایموجی کشتی 🚢 است", "🚢" in wto_caption)
        check("خبر WTO شامل واژه دریانوردی است", "دریانوردی" in wto_caption)
        # -------------------------------------------------------------
        # [بخش ۱۰] تست عدم امکان رهگیری محموله دریایی، پایداری ۱ ساعته درگیری و کریدورها
        # -------------------------------------------------------------
        print("\n[بخش ۱۰] تست غیرفعال‌سازی رهگیری دریایی، نمایش ۱ ساعته درگیری و کریدورها:")
        from bot.services import interception_service
        from bot.webapp import state as webapp_state

        # ۱) بررسی سرویس رهگیری برای محموله‌های دریایی
        intc_list = await interception_service.interceptable_shipments(session, iran_c.id)
        sea_in_intc = [s for s in intc_list if s.get("transport_mode") == "SEA"]
        check("هیچ محموله دریایی در لیست رهگیری قرار نمی‌گیرد", len(sea_in_intc) == 0)

        # ۲) بررسی کریدورهای دریایی بین‌المللی
        corridors = geo.get_all_maritime_corridor_segments()
        check("کریدورهای دریایی بین‌المللی استخراج شدند", len(corridors) > 0)
        check("هر قطعه کریدور دارای دو نقطه مختصات جغرافیایی است", len(corridors[0]) == 2 and len(corridors[0][0]) == 2)

        # ۳) ثبت دو محموله منهدم شده: یکی ۳۰ دقیقه پیش (زیر ۱ ساعت) و یکی ۹۰ دقیقه پیش (بالای ۱ ساعت)
        sale_conflict_recent = ResourceSale(
            id=60,
            seller_country=uae_c.id,
            buyer_country=india_c.id,
            resource=ResourceType.OIL.value,
            amount=500.0,
            price=5_000_000.0,
            transport_mode="SEA",
            status=TradeStatus.REJECTED.value,
            strait_status="DESTROYED",
            held_at_strait_id="hormuz",
            held_since=_utcnow() - timedelta(minutes=30),
        )
        sale_conflict_expired = ResourceSale(
            id=61,
            seller_country=uae_c.id,
            buyer_country=india_c.id,
            resource=ResourceType.OIL.value,
            amount=500.0,
            price=5_000_000.0,
            transport_mode="SEA",
            status=TradeStatus.REJECTED.value,
            strait_status="CONFISCATED",
            held_at_strait_id="hormuz",
            held_since=_utcnow() - timedelta(minutes=90),
        )
        session.add_all([sale_conflict_recent, sale_conflict_expired])
        await session.commit()

        # بررسی خروجی get_radar_state برای یک کاربر ناظر (مثلاً آلمان که هیچ نفعی در معامله نداشته)
        state_data = await webapp_state.get_radar_state(session, viewer_user_id=102)
        active_ids = [s["id"] for s in state_data["shipments"]]
        check("محموله درگیری زیر ۱ ساعت در رادار همه کشورها نمایش داده می‌شود", 60 in active_ids)
        check("محموله درگیری بالای ۱ ساعت از روی نقشه حذف شده است", 61 not in active_ids)

        conflict_shipment = next(s for s in state_data["shipments"] if s["id"] == 60)
        check("فلگ is_conflict برای محموله منهدم‌شده True است", conflict_shipment["is_conflict"] is True)
        check("محموله درگیری قابل رهگیری نیست", conflict_shipment["can_intercept"] is False)
        check("مختصات درگیری در مدخل تنگه تنظیم شده است", len(conflict_shipment["waypoints"]) >= 1)
        check("لیست کریدورهای دریایی در خروجی رادار ارسال می‌شود", "maritime_network" in state_data and len(state_data["maritime_network"]) > 0)

    # پایان تست‌ها و گزارش نهایی
    # -------------------------------------------------------------
    print("\n" + "=" * 65)
    print(f"نتیجه نهایی تست‌ها: {_passed} موفق | {len(_failed)} ناموفق")
    print("=" * 65)

    if _failed:
        print("\n❌ موارد ناموفق:")
        for fail in _failed:
            print(f"  - {fail}")
        sys.exit(1)
    else:
        print("\n🎉 تمامی بخش‌های آپدیت ۳ و ۱۱ با موفقیت پاس شدند!")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
