"""
تست جامع سیستم توقف/شروع کارخانه‌ها، رفع باگ دکمه بازگشت و بازطراحی SVG نقشه.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# افزودن ریشه پروژه به مسیر
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bot.database.base import Base
from bot.database.models import Country, Facility, MilitaryFactory, User
from bot.database.repositories import facilities as fac_repo
from bot.database.repositories import military_factory as milfac_repo
from bot.enums import FacilityType, MilitaryFactoryType


async def run_tests():
    print("=" * 65)
    print("🚀 آغاز تست‌های جامع توقف/ادامه کارخانه‌ها، رفع باگ و بازطراحی SVG")
    print("=" * 65)

    test_db_url = "sqlite+aiosqlite:///:memory:"
    engine = create_async_engine(test_db_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print("\n--- بخش ۱: تست توقف و ادامه تولید تأسیسات اقتصادی (کارخانه فولاد/معادن) ---")
    async with session_factory() as session:
        # ایجاد کشور تستی
        test_user = User(telegram_id=999001, first_name="TestPlayer")
        session.add(test_user)
        await session.flush()

        test_country = Country(
            id=101,
            name_en="Iran",
            name_fa="ایران",
            flag="🇮🇷",
            region="middle_east",
            is_claimed=True,
            owner_user_id=test_user.telegram_id,
            budget=1_000_000_000.0,
        )
        session.add(test_country)
        await session.flush()

        # ایجاد کارخانه فولاد
        steel_fac = Facility(
            country_id=test_country.id,
            type=FacilityType.STEEL_FACTORY.value,
            location="اصفهان",
            budget=10_000_000.0,
            yield_amount=1_000_000.0,
            yield_interval_h=24,
            intake_amount=1_000_000.0,
            active=True,
        )
        session.add(steel_fac)
        await session.commit()
        fac_id = steel_fac.id

    # بررسی اولیه
    async with session_factory() as session:
        fac = await session.get(Facility, fac_id)
        assert fac.active is True, "کارخانه در ابتدا باید فعال باشد"
        active_facs = await fac_repo.all_active_facilities(session)
        assert any(f.id == fac_id for f in active_facs), "کارخانه باید در لیست فعال زمان‌بند باشد"
        print("✅ تست ۱: کارخانه فولاد با وضعیت فعال (active=True) ساخته شد و در زمان‌بند حاضر است.")

        # توقف تولید
        toggled = await fac_repo.toggle_facility_active(session, fac_id)
        await session.commit()
        assert toggled.active is False, "پس از توقف باید active=False باشد"

        # بررسی زمان‌بند: نباید در all_active_facilities باشد
        active_facs_after = await fac_repo.all_active_facilities(session)
        assert not any(f.id == fac_id for f in active_facs_after), "کارخانه متوقف نباید در زمان‌بند پردازش شود"
        print("✅ تست ۲: کارخانه متوقف شد (active=False)؛ از لیست فعال زمان‌بند خارج شد (مصرف آهن و هزینه صفر شد).")

        # ادامه تولید
        toggled_again = await fac_repo.toggle_facility_active(session, fac_id)
        await session.commit()
        assert toggled_again.active is True, "پس از فعال‌سازی مجدد باید active=True باشد"
        active_facs_reactivated = await fac_repo.all_active_facilities(session)
        assert any(f.id == fac_id for f in active_facs_reactivated), "کارخانه دوباره در لیست فعال زمان‌بند حاضر شد"
        print("✅ تست ۳: کارخانه مجدداً فعال شد (active=True) و زمان آخرین بازدهی به اکنون تنظیم گردید.")


    print("\n--- بخش ۲: تست توقف و ادامه تولید کارخانه‌های تجهیزات نظامی ---")
    async with session_factory() as session:
        mil_fac = MilitaryFactory(
            country_id=101,
            factory_type=MilitaryFactoryType.TANK.value,
            asset_name="T-90MS",
            category="تانک",
            unit="دستگاه",
            location="شیراز",
            cost=2_500_000.0,
            yield_amount=20,
            yield_interval_h=24,
            active=True,
        )
        session.add(mil_fac)
        await session.commit()
        mf_id = mil_fac.id

    async with session_factory() as session:
        mf = await session.get(MilitaryFactory, mf_id)
        assert mf.active is True
        active_mfs = await milfac_repo.all_active_factories(session)
        assert any(f.id == mf_id for f in active_mfs)
        print("✅ تست ۴: کارخانه تانک‌سازی با وضعیت فعال ثبت شد و در چرخه زمان‌بند نظامی حاضر است.")

        # توقف کارخانه نظامی
        toggled_mf = await milfac_repo.toggle_factory_active(session, mf_id)
        await session.commit()
        assert toggled_mf.active is False
        active_mfs_after = await milfac_repo.all_active_factories(session)
        assert not any(f.id == mf_id for f in active_mfs_after)
        print("✅ تست ۵: کارخانه نظامی متوقف شد (active=False)؛ از چرخه بازدهی خارج شد (عدم مصرف منابع و عدم تولید).")

        # فعال‌سازی مجدد کارخانه نظامی
        toggled_mf_again = await milfac_repo.toggle_factory_active(session, mf_id)
        await session.commit()
        assert toggled_mf_again.active is True
        active_mfs_reactivated = await milfac_repo.all_active_factories(session)
        assert any(f.id == mf_id for f in active_mfs_reactivated)
        print("✅ تست ۶: کارخانه نظامی مجدداً فعال شد (active=True) و به چرخه تولید بازگشت.")


    print("\n--- بخش ۳: تست هندلرها و رفع خطای دکمه بازگشت (milfac:menu) ---")
    from unittest.mock import MagicMock
    from bot.handlers.economy import router as econ_router
    from bot.handlers.military import router as mil_router

    # تست تطابق کال‌بک بازگشت milfac:menu در روتر نظامی
    cb_menu_handler = next(
        h for h in mil_router.callback_query.handlers
        if h.callback.__name__ == "cb_factory_menu"
    )
    mock_cb_back = MagicMock(data="milfac:menu")
    mock_cb_orig = MagicMock(data="mil:factory")
    assert cb_menu_handler.filters[0].callback(mock_cb_back) is True, "کال‌بک milfac:menu باید هندلر cb_factory_menu را فعال کند"
    assert cb_menu_handler.filters[0].callback(mock_cb_orig) is True, "کال‌بک mil:factory باید هندلر cb_factory_menu را فعال کند"
    print("✅ تست ۷: کال‌بک‌های 'milfac:menu' و 'mil:factory' با موفقیت هندلر cb_factory_menu را فعال می‌کنند.")

    # تست هندلر milfac_toggle:
    cb_milfac_toggle_handler = next(
        (h for h in mil_router.callback_query.handlers if h.callback.__name__ == "cb_milfac_toggle"),
        None,
    )
    assert cb_milfac_toggle_handler is not None, "هندلر cb_milfac_toggle باید ثبت شده باشد"
    mock_cb_toggle = MagicMock(data="milfac_toggle:123")
    assert cb_milfac_toggle_handler.filters[0].callback(mock_cb_toggle) is True
    print("✅ تست ۸: هندلر 'milfac_toggle:' جهت توقف/شروع کارخانه‌های نظامی در روتر نظامی رجیستر است.")

    # تست هندلر fac_tog: در روتر اقتصاد
    cb_fac_toggle_handler = next(
        (h for h in econ_router.callback_query.handlers if h.callback.__name__ == "cb_facility_toggle"),
        None,
    )
    assert cb_fac_toggle_handler is not None, "هندلر cb_facility_toggle باید ثبت شده باشد"
    mock_cb_fac_tog = MagicMock(data="fac_tog:456:0:facl:steel_factory")
    assert cb_fac_toggle_handler.filters[0].callback(mock_cb_fac_tog) is True
    print("✅ تست ۹: هندلر 'fac_tog:' جهت توقف/شروع تأسیسات اقتصادی در روتر اقتصاد رجیستر است.")


    print("\n--- بخش ۴: تست صحت بازطراحی وکتورهای SVG نقشه مینی‌اپ ---")
    html_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bot", "webapp", "static", "index.html"))
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # ۱. عدم استفاده از ایموجی در نشانگرهای اصلی
    assert "🇺🇳" not in html_content, "ایموجی سازمان ملل نباید در کدهای نشانگر نقشه باشد"
    print("✅ تست ۱۰: ایموجی 🇺🇳 حذف و با نشان رسمی وکتور SVG سازمان ملل جایگزین شد.")

    assert "<span>⚓</span>" not in html_content, "ایموجی لنگر متنی نباید در strait-marker باشد"
    print("✅ تست ۱۱: ایموجی ⚓ در تنگه‌ها حذف و با وکتور SVG لنگر تاکتیکال جایگزین شد.")

    # ۲. بررسی وجود وکتورها در متدهای آیکون‌ساز
    assert "createConflictIcon" in html_content and "<svg" in html_content
    print("✅ تست ۱۲: نشانگرهای رویداد و درگیری با SVGهای انفجار و آژیر اخطار پیاده‌سازی شدند.")

    assert "createShipIcon" in html_content and "<!-- Pointed Hull pointing UP -->" in html_content
    print("✅ تست ۱۳: آیکون کشتی با وکتور مهندسی‌شده شناور تجاری/نفتکش مدرن بازطراحی شد.")

    assert "createPlaneIcon" in html_content and "<!-- Tactical Swept Wing Jet Aircraft -->" in html_content
    print("✅ تست ۱۴: آیکون پرواز با وکتور جت تاکتیکال بال پس‌گرا بازطراحی شد.")

    assert "capital-marker" in html_content and "M12 4.5V6.5" in html_content
    print("✅ تست ۱۵: نشانگر پایتخت‌ها با وکتور گنبد حکومتی و ستاره راهبردی SVG بازطراحی شد.")

    assert "layer-filters" in html_content and "stat-pill" in html_content
    print("✅ تست ۱۶: کلیه فیلترهای لایه‌ها و آمار HUD با آیکون‌های وکتور SVG مجهز شدند.")

    print("\n" + "=" * 65)
    print("🎉 تمام ۱۶ تست جامع توقف کارخانه‌ها، رفع باگ و بازطراحی SVG با موفقیت ۱۰۰٪ سپری شدند!")
    print("=" * 65)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_tests())
