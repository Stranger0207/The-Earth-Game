"""
اسکریپت تست جامع ۵ محور آپدیت Earth Game Bot:
۱. ممیزی سراسری کال‌بک‌ها و حل مشکل دکمه‌های منقضی‌شده / ورود دستی سود رول اقتصادی
۲. لیست بازدهی روزانه و ترازنامه درآمد ۲۴ ساعته (تأسیسات مشترک، سرمایه‌گذاری، رول‌ها، ماهواره، کارخانه‌ها)
۳. حذف محدودیت کف/سقف قیمت نرخ جهانی برای ادمین و نرمال‌سازی ارقام فارسی/عربی
۴. محدودیت‌های زمانی سهمیه (قوانین ۲ در ۱۲ساعت، رول اقتصادی ۲ در ۲۴ساعت، رول نظامی ۱ در ۲۴ساعت با شمارش منصفانه)
۵. دکمه‌های انصراف و بازگشت در فرم‌های چندمرحله‌ای
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
    ECON_ROLE_LIMIT_COUNT,
    ECON_ROLE_LIMIT_HOURS,
    LEGISLATION_LIMIT_COUNT,
    LEGISLATION_LIMIT_HOURS,
    MIL_ROLE_LIMIT_COUNT,
    MIL_ROLE_LIMIT_HOURS,
    LOCKABLE_FEATURES,
    OIL_PLATFORM_OUTPUT_PER_24H,
    STEEL_FACTORY_IRON_INTAKE_PER_24H,
    STEEL_FACTORY_OUTPUT_PER_24H,
)
from bot.database.base import Base
from bot.database.models import (
    Country,
    EconomicProject,
    Facility,
    Investment,
    Law,
    MarketPrice,
    MilitaryFactory,
    MilitaryRole,
    Satellite,
    User,
)
from bot.database.repositories import (
    countries as countries_repo,
    economic_projects as proj_repo,
    governance as gov_repo,
    military_roles as mil_ops_repo,
)
from bot.enums import (
    EconomicProjectStatus,
    FacilityType,
    LawStatus,
    MilitaryFactoryType,
    MilitaryRoleStatus,
    MilitaryRoleType,
    ResourceType,
)
from bot.keyboards.economy import daily_yield_kb, bank_menu_kb, economy_menu_kb
from bot.services.market_service import update_price
from bot.services.yield_service import compute_country_daily_yield, format_daily_yield_report
from bot.utils.numbers import _FA_TO_EN, normalize_number_input, parse_amount


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine, session_factory


# ============================================================
# تست ۱: نرمال‌سازی ارقام فارسی، عربی، کاما و پیشوندها
# ============================================================
def test_number_normalization():
    print("\n--- تست ۱: نرمال‌سازی ارقام و مقادیر ورودی ---")
    
    # ارقام فارسی
    val1 = parse_amount("۵۰۰۰۰۰")
    assert val1 == 500000.0, f"Expected 500000.0, got {val1}"
    
    # ارقام عربی
    val2 = parse_amount("٥٠٠٠٠٠")
    assert val2 == 500000.0, f"Expected 500000.0, got {val2}"
    
    # همراه با کامای فارسی و انگلیسی و فاصله
    val3 = parse_amount(" ۵۰۰،۰۰۰ ")
    assert val3 == 500000.0, f"Expected 500000.0, got {val3}"
    
    val4 = parse_amount("500,000")
    assert val4 == 500000.0, f"Expected 500000.0, got {val4}"
    
    # پسوندهای عددی
    assert parse_amount("50M") == 50_000_000.0
    assert parse_amount("2.5B") == 2_500_000_000.0
    assert parse_amount("100k") == 100_000.0
    
    # alias normalize_number_input
    assert normalize_number_input("۱۲۳") == 123.0
    print("✅ تست ۱ با موفقیت پاس شد.")


# ============================================================
# تست ۲: تعیین نرخ جهانی بدون محدودیت سقف و کف توسط ادمین
# ============================================================
async def test_admin_market_bounds(session: AsyncSession):
    print("\n--- تست ۲: تعیین نرخ جهانی توسط ادمین (حذف سقف/کف و هماهنگی base_price) ---")
    
    # ایجاد قیمت اولیه نفت
    mp = MarketPrice(
        resource=ResourceType.OIL.value,
        current_price=3_000_000.0,
        base_price=3_000_000.0,
        previous_price=3_000_000.0,
        change_pct=0.0,
        trend="STABLE",
        last_reason_code="INITIAL",
        last_reason_text="initial",
        updated_at=_utcnow(),
    )
    session.add(mp)
    await session.commit()
    
    # ۱. تلاش برای تغییر به ۵۰۰،۰۰۰ بدون override ادمین -> معمولاً به کف قیمت برخورد می‌کند
    # ۲. تغییر با is_admin_override=True به ۵۰۰،۰۰۰ دلار
    target = 500_000.0
    updated_price = await update_price(
        session,
        ResourceType.OIL,
        absolute_price=target,
        is_admin_override=True,
    )
    await session.commit()
    
    stmt = select(MarketPrice).where(MarketPrice.resource == ResourceType.OIL.value)
    res = await session.execute(stmt)
    saved_mp = res.scalar_one()
    
    assert saved_mp.current_price == 500_000.0, f"Expected current_price 500000, got {saved_mp.current_price}"
    assert saved_mp.base_price == 500_000.0, f"Expected base_price 500000, got {saved_mp.base_price}"
    print(f"✅ قیمت نفت با موفقیت توسط ادمین روی {saved_mp.current_price:,.0f} دلار و base_price متناظر ست شد.")
    print("✅ تست ۲ با موفقیت پاس شد.")


# ============================================================
# تست ۳: ترازنامه بازدهی روزانه و محاسبات ۲۴ ساعته
# ============================================================
async def test_daily_yield_balance_sheet(session: AsyncSession):
    print("\n--- تست ۳: ترازنامه بازدهی روزانه کشور (تأسیسات مشترک، سرمایه‌گذاری، رول، ماهواره، کارخانه) ---")
    
    # ایجاد دو کشور
    c1 = Country(name_en="Country A", name_fa="کشور الف", flag="🇦", region="middle_east", population=10_000_000, budget=100_000_000.0)
    c2 = Country(name_en="Country B", name_fa="کشور ب", flag="🇧", region="middle_east", population=5_000_000, budget=100_000_000.0)
    session.add_all([c1, c2])
    await session.commit()
    
    # تأسیسات ۱: دکل نفت ۱۰۰٪ خودی فعال
    f1 = Facility(
        country_id=c1.id,
        type=FacilityType.OIL_PLATFORM.value,
        yield_amount=OIL_PLATFORM_OUTPUT_PER_24H,
        active=True,
    )
    # تأسیسات ۲: کارخانه فولاد مشترک (کشور الف سازنده، کشور ب شریک ۴۰٪) -> سهم کشور الف ۶۰٪
    f2 = Facility(
        country_id=c1.id,
        type=FacilityType.STEEL_FACTORY.value,
        yield_amount=STEEL_FACTORY_OUTPUT_PER_24H,
        partner_country=c2.id,
        partner_percent=40.0,
        active=True,
    )
    # تأسیسات ۳: کارخانه متوقف شده (active=False)
    f3 = Facility(
        country_id=c1.id,
        type=FacilityType.MINE.value,
        resource=ResourceType.GOLD.value,
        yield_amount=100.0,
        active=False,
    )
    session.add_all([f1, f2, f3])
    
    # سرمایه‌گذاری فعال داخلی: ۱۰۰ میلیون دلار با سود ۵٪ در روز -> ۵ میلیون دلار
    inv = Investment(
        investor_country=c1.id,
        target_country=c1.id,
        category="تکنولوژی",
        amount=100_000_000.0,
        profit_pct=5.0,
        active=True,
    )
    session.add(inv)
    
    # رول اقتصادی تاییدشده و فعال: سود ۷۲ ساعته ۹۰ میلیون دلار (۳۰ میلیون در ۲۴ ساعت)
    proj = EconomicProject(
        country_id=c1.id,
        title="توسعه بنادر تجاری",
        page_1="متن صفحه اول",
        status=EconomicProjectStatus.ACTIVE.value,
        yield_cash_72h=90_000_000.0,
        yield_resources_dict={"uranium": 3.0},  # ۱ کیلو در روز
    )
    session.add(proj)
    
    # ماهواره اقتصادی سطح ۲ در مدار (سود ۷۲ ساعته ۲۵۰ میلیون دلار -> ۸۳,۳۳۳,۳۳۳.۳۳ در روز)
    sat = Satellite(
        country_id=c1.id,
        name="ماهواره اقتصادی ۱",
        satellite_type="economic",
        status="in_orbit",
        level=2,
        orbit_at=_utcnow() - timedelta(hours=10),
    )
    session.add(sat)
    
    # کارخانه نظامی فعال: تولید تانک با چرخه ۲۴ ساعته و مصرف آهن
    mf = MilitaryFactory(
        country_id=c1.id,
        factory_type=MilitaryFactoryType.TANK.value,
        asset_name="خط تولید تانک T-90",
        yield_amount=5,
        yield_interval_h=24,
        unit="دستگاه",
        active=True,
    )
    session.add(mf)
    await session.commit()
    
    # محاسبه ترازنامه بازدهی
    report_data = await compute_country_daily_yield(session, c1)
    
    # بررسی‌ها:
    assert report_data["stopped_facs_count"] == 1, "Expected 1 stopped facility"
    assert report_data["daily_inv_cash"] == 5_000_000.0, f"Expected 5M inv cash, got {report_data['daily_inv_cash']}"
    assert report_data["daily_proj_cash"] == 30_000_000.0, f"Expected 30M proj cash, got {report_data['daily_proj_cash']}"
    assert report_data["sat_info"] is not None, "Expected active satellite info"
    assert report_data["sat_info"]["level"] == 2
    
    # سهم کارخانه فولاد مشترک ۶۰٪
    # تولید ناخالص فولاد روزانه: STEEL_FACTORY_OUTPUT_PER_24H * 0.6
    # مصرف فولاد کارخانه تانک: ۱۸۰,۰۰۰
    expected_net_steel = (STEEL_FACTORY_OUTPUT_PER_24H * 0.6) - 180_000.0
    assert abs(report_data["net_resources"].get("steel", 0.0) - expected_net_steel) < 0.01
    
    # مصرف آهن = آهن مصرفی کارخانه فولاد (۶۰٪) + آهن مصرفی کارخانه تانک
    net_iron = report_data["net_resources"].get("iron", 0.0)
    assert net_iron < 0, f"Expected net negative iron due to factories, got {net_iron}"
    
    # رندر گزارش متنی
    report_text = format_daily_yield_report(c1, report_data)
    assert "ترازنامه درآمد و بازدهی روزانه" in report_text
    assert "جمع کل خالص بازدهی روزانه" in report_text
    assert "دکل نفت" in report_text
    assert "کارخانه فولاد (سهم: ۶۰٪)" in report_text
    assert "۱ واحد متوقف‌شده" in report_text
    assert "توسعه بنادر تجاری" in report_text
    assert "ماهواره سطح ۲" in report_text
    
    print("✅ خروجی گزارش ترازنامه با موفقیت رندر شد:")
    print("-" * 50)
    print("\n".join(report_text.splitlines()[:25]))
    print("...\n" + "\n".join(report_text.splitlines()[-10:]))
    print("-" * 50)
    print("✅ تست ۳ با موفقیت پاس شد.")


# ============================================================
# تست ۴: محدودیت‌های زمانی سهمیه و شمارش منصفانه
# ============================================================
async def test_rate_limits_and_fair_counting(session: AsyncSession):
    print("\n--- تست ۴: محدودیت‌های زمانی سهمیه (لوایح، رول اقتصادی، رول نظامی) ---")
    
    c = Country(name_en="Country Limits", name_fa="کشور تست سهمیه", flag="🏳", region="middle_east", population=1_000_000, budget=100_000_000.0)
    session.add(c)
    await session.commit()
    
    now = _utcnow()
    since_12h = now - timedelta(hours=LEGISLATION_LIMIT_HOURS)
    since_24h = now - timedelta(hours=ECON_ROLE_LIMIT_HOURS)
    
    # ۱. سهمیه لوایح پارلمان (۲ در ۱۲ ساعت)
    l1 = Law(country_id=c.id, title="لایحه ۱", body="متن ۱", status=LawStatus.IN_PARLIAMENT.value, created_at=now - timedelta(hours=1))
    l2 = Law(country_id=c.id, title="لایحه ۲", body="متن ۲", status=LawStatus.APPROVED.value, created_at=now - timedelta(hours=2))
    l_rej = Law(country_id=c.id, title="لایحه ردشده", body="متن رد", status=LawStatus.REJECTED.value, created_at=now - timedelta(hours=3))
    l_old = Law(country_id=c.id, title="لایحه قدیمی", body="متن قدیم", status=LawStatus.APPROVED.value, created_at=now - timedelta(hours=15))
    session.add_all([l1, l2, l_rej, l_old])
    await session.commit()
    
    count_laws = await gov_repo.count_laws_by_country_since(session, c.id, since_12h)
    assert count_laws == 2, f"Expected 2 active/enacted laws in 12h (excluding rejected and old), got {count_laws}"
    assert count_laws >= LEGISLATION_LIMIT_COUNT, "Should have reached legislation limit"
    
    # ۲. سهمیه رول‌های اقتصادی (۲ در ۲۴ ساعت - DRAFT و REJECTED و CANCELLED شمرده نمی‌شوند)
    ep1 = EconomicProject(country_id=c.id, title="پروژه ۱", page_1="صفحه ۱", status=EconomicProjectStatus.PENDING_REVIEW.value, created_at=now - timedelta(hours=2))
    ep2 = EconomicProject(country_id=c.id, title="پروژه ۲", page_1="صفحه ۱", status=EconomicProjectStatus.ACTIVE.value, created_at=now - timedelta(hours=4))
    ep_draft = EconomicProject(country_id=c.id, title="پیش‌نویس", page_1="صفحه ۱", status=EconomicProjectStatus.DRAFT.value, created_at=now - timedelta(hours=1))
    ep_rej = EconomicProject(country_id=c.id, title="ردشده", page_1="صفحه ۱", status=EconomicProjectStatus.REJECTED.value, created_at=now - timedelta(hours=3))
    ep_canc = EconomicProject(country_id=c.id, title="لغوشده", page_1="صفحه ۱", status=EconomicProjectStatus.CANCELLED.value, created_at=now - timedelta(hours=5))
    session.add_all([ep1, ep2, ep_draft, ep_rej, ep_canc])
    await session.commit()
    
    count_projs = await proj_repo.count_projects_by_country_since(session, c.id, since_24h)
    assert count_projs == 2, f"Expected 2 economic projects in 24h, got {count_projs}"
    assert count_projs >= ECON_ROLE_LIMIT_COUNT, "Should have reached econ role limit"
    
    # ۳. سهمیه رول‌های نظامی (۱ در ۲۴ ساعت - DRAFT و CANCELLED شمرده نمی‌شوند)
    mr1 = MilitaryRole(attacker_country_id=c.id, target_country_id=999, op_type="attack", title="عملیات طوفان", page_1="صفحه ۱", status=MilitaryRoleStatus.PENDING_REVIEW.value, created_at=now - timedelta(hours=1))
    mr_draft = MilitaryRole(attacker_country_id=c.id, target_country_id=999, op_type="sabotage", title="پیش‌نویس عملیات", page_1="صفحه ۱", status=MilitaryRoleStatus.DRAFT.value, created_at=now - timedelta(hours=2))
    session.add_all([mr1, mr_draft])
    await session.commit()
    
    count_mil = await mil_ops_repo.count_roles_by_attacker_since(session, c.id, since_24h)
    assert count_mil == 1, f"Expected 1 military role in 24h, got {count_mil}"
    assert count_mil >= MIL_ROLE_LIMIT_COUNT, "Should have reached military role limit"
    
    print("✅ تست ۴ با موفقیت پاس شد.")


# ============================================================
# تست ۵: بررسی صحت کیبوردها و دکمه‌های انصراف
# ============================================================
def test_keyboards_and_cancel_buttons():
    print("\n--- تست ۵: بررسی کیبوردها و دکمه‌های انصراف / بازگشت ---")
    
    # کیبورد روزانه بازدهی
    kb_yield = daily_yield_kb("menu:economy")
    buttons_text = [b.text for row in kb_yield.inline_keyboard for b in row]
    buttons_cb = [b.callback_data for row in kb_yield.inline_keyboard for b in row]
    assert "🔄 به‌روزرسانی ترازنامه" in buttons_text
    assert "🔙 بازگشت" in buttons_text
    assert "econ:daily_yield:refresh" in buttons_cb
    assert "menu:economy" in buttons_cb
    
    # کیبورد بانک دارای میانبر بازدهی روزانه
    kb_bank = bank_menu_kb()
    bank_cbs = [b.callback_data for row in kb_bank.inline_keyboard for b in row]
    assert "econ:daily_yield:bank" in bank_cbs
    
    # کیبورد اصلی اقتصاد دارای میانبر بازدهی روزانه
    kb_econ = economy_menu_kb()
    econ_cbs = [b.callback_data for row in kb_econ.inline_keyboard for b in row]
    assert "econ:daily_yield" in econ_cbs
    
    print("✅ تست ۵ با موفقیت پاس شد.")


async def main():
    print("=" * 60)
    print("🚀 شروع اجرای تست‌های جامع ۵ محور آپدیت Earth Game Bot")
    print("=" * 60)
    
    test_number_normalization()
    test_keyboards_and_cancel_buttons()
    
    engine, session_factory = await setup_db()
    async with session_factory() as session:
        await test_admin_market_bounds(session)
        await test_daily_yield_balance_sheet(session)
        await test_rate_limits_and_fair_counting(session)
    
    await engine.dispose()
    print("\n" + "=" * 60)
    print("🎉 تمامی تست‌ها با موفقیت ۱۰۰٪ پاس شدند!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
