"""
اسکریپت تست جامع و خودکار سامانه نوین روادید (ویزا) و کنترل مرزها:
۱. تست داشبورد اصلی و آمار تفکیک‌شده (ویزای اجباری، لغو روادید اعطایی، لغو روادید دریافتی، عادی)
۲. تست استعلام و مشاهده لیست‌ها (کیا دارن / کیا ندارن) با صفحه‌بندی
۳. تست وضع ویزای اجباری بر تمامی کشورهای جهان (سراسری)
۴. تست وضع ویزای منطقه‌ای و تکی/چندتایی
۵. تست رفع ویزای اجباری (تکی و سراسری)
۶. تست یکپارچگی با لغو روادید در نشست‌های حضوری (Visa Waiver) و تخفیف ۵۰٪ حمل‌ونقل
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

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

from aiogram.types import CallbackQuery, User as TgUser
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.database.base import Base
from bot.database.models import Country, User, VisaRequirement
from bot.database.models.diplomacy import VisaWaiver
from bot.database.repositories import countries as countries_repo
from bot.database.repositories import diplomacy as dip_repo
from bot.database.repositories import governance as gov_repo
from bot.handlers.governance import (
    _build_visa_dashboard_data,
    _format_visa_dashboard_text,
    cb_visa_all_confirm,
    cb_visa_bulk_menu,
    cb_visa_law,
    cb_visa_region_do,
    cb_visa_rm_all_confirm,
    cb_visa_rm_do,
    cb_visa_status,
    cb_visa_view,
)


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

    # ساخت دیتابیس تست SQLite در رم
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    print("\n--- بخش ۱: آماده‌سازی داده‌های تست ---")
    async with session_factory() as session:
        u_iran = User(telegram_id=10, username="iran_leader", first_name="Iran Leader")
        u_germany = User(telegram_id=20, username="germany_leader", first_name="Germany Leader")
        u_france = User(telegram_id=30, username="france_leader", first_name="France Leader")
        u_china = User(telegram_id=40, username="china_leader", first_name="China Leader")
        u_brazil = User(telegram_id=50, username="brazil_leader", first_name="Brazil Leader")
        u_japan = User(telegram_id=60, username="japan_leader", first_name="Japan Leader")
        session.add_all([u_iran, u_germany, u_france, u_china, u_brazil, u_japan])

        c_iran = Country(id=1, name_en="Iran", name_fa="ایران", flag="🇮🇷", region="middle_east", owner_user_id=10, is_claimed=True, budget=100_000_000.0, stability=80.0, public_satisfaction=80.0)
        c_ger = Country(id=2, name_en="Germany", name_fa="آلمان", flag="🇩🇪", region="europe", owner_user_id=20, is_claimed=True, budget=100_000_000.0, stability=80.0, public_satisfaction=80.0)
        c_fra = Country(id=3, name_en="France", name_fa="فرانسه", flag="🇫🇷", region="europe", owner_user_id=30, is_claimed=True, budget=100_000_000.0, stability=80.0, public_satisfaction=80.0)
        c_chn = Country(id=4, name_en="China", name_fa="چین", flag="🇨🇳", region="east_asia", owner_user_id=40, is_claimed=True, budget=100_000_000.0, stability=80.0, public_satisfaction=80.0)
        c_brz = Country(id=5, name_en="Brazil", name_fa="برزیل", flag="🇧🇷", region="americas", owner_user_id=50, is_claimed=True, budget=100_000_000.0, stability=80.0, public_satisfaction=80.0)
        c_jpn = Country(id=6, name_en="Japan", name_fa="ژاپن", flag="🇯🇵", region="east_asia", owner_user_id=60, is_claimed=True, budget=100_000_000.0, stability=80.0, public_satisfaction=80.0)
        session.add_all([c_iran, c_ger, c_fra, c_chn, c_brz, c_jpn])
        await session.commit()
        assert_check(True, "کشورها و کاربران آزمایشی ایجاد شدند")

    print("\n--- بخش ۲: تست داشبورد اصلی و تفکیک آمار مرزها ---")
    async with session_factory() as session:
        # ایران برای آلمان ویزای اجباری وضع می‌کند
        await gov_repo.add_visa(session, country_id=1, target_country_id=2)
        # ایران به فرانسه لغو روادید اعطا می‌کند
        await dip_repo.add_visa_waiver(session, country_id=1, target_country_id=3)
        # چین به ایران لغو روادید اعطا می‌کند (ایران دریافت‌کننده است)
        await dip_repo.add_visa_waiver(session, country_id=4, target_country_id=1)
        await session.commit()

        # بررسی آمار داشبورد
        data = await _build_visa_dashboard_data(session, c_iran)
        assert_check(data["req_count"] == 1, "تعداد ویزای اجباری صحیح است (۱ کشور: آلمان)")
        assert_check(data["granted_count"] == 1, "تعداد لغو روادید اعطایی صحیح است (۱ کشور: فرانسه)")
        assert_check(data["rec_count"] == 1, "تعداد لغو روادید دریافتی صحیح است (۱ کشور: چین)")
        # کل کشورهای دیگر = ۵، آلمان (req) و فرانسه (granted) کم شوند -> ۳ کشور عادی (چین، برزیل، ژاپن)
        assert_check(data["normal_count"] == 3, "تعداد روابط عادی صحیح است (۳ کشور)")

        # بررسی متن داشبورد
        text = _format_visa_dashboard_text(c_iran, data)
        assert_check("سامانه جامع روادید (ویزا) و مدیریت مرزها" in text, "هدر داشبورد شامل عنوان استاندارد است")
        assert_check("ویزای اجباری وضع‌شده:</b> ۱ کشور" in text, "آمار ویزای اجباری در متن درج شده است")
        assert_check("توافق لغو روادید اعطایی (مرز باز):</b> ۱ کشور" in text, "آمار لغو روادید اعطایی در متن درج شده است")

    print("\n--- بخش ۳: تست استعلام و فیلتر (کیا دارن / کیا ندارن) ---")
    async with session_factory() as session:
        mock_call = AsyncMock(spec=CallbackQuery)
        mock_call.answer = AsyncMock()
        mock_call.message = AsyncMock()
        mock_call.message.photo = None
        mock_call.message.document = None
        mock_call.message.edit_text = AsyncMock()

        # ۳.۱ مشاهده کشورهای نیازمند ویزا (req)
        mock_call.data = "gov_vview:req:0"
        await cb_visa_view(mock_call, session, u_iran)
        assert_check(mock_call.message.edit_text.called, "صفحه لیست ویزاهای اجباری با موفقیت رندر شد")
        call_text = mock_call.message.edit_text.call_args[0][0]
        assert_check("آلمان" in call_text, "کشور آلمان در لیست کشورهای نیازمند ویزا حاضر است")

        # ۳.۲ مشاهده کشورهای لغو روادید اعطایی (waiver)
        mock_call.data = "gov_vview:waiver:0"
        await cb_visa_view(mock_call, session, u_iran)
        call_text = mock_call.message.edit_text.call_args[0][0]
        assert_check("فرانسه" in call_text, "کشور فرانسه در لیست لغو روادید اعطایی حاضر است")

        # ۳.۳ مشاهده کشورهای لغو روادید دریافتی (rec)
        mock_call.data = "gov_vview:rec:0"
        await cb_visa_view(mock_call, session, u_iran)
        call_text = mock_call.message.edit_text.call_args[0][0]
        assert_check("چین" in call_text, "کشور چین در لیست لغو روادید دریافتی حاضر است")

        # ۳.۴ مشاهده کشورهای دارای مرز عادی (none)
        mock_call.data = "gov_vview:none:0"
        await cb_visa_view(mock_call, session, u_iran)
        call_text = mock_call.message.edit_text.call_args[0][0]
        assert_check("برزیل" in call_text and "ژاپن" in call_text, "کشورهای برزیل و ژاپن در لیست مرز عادی حاضرند")

    print("\n--- بخش ۴: تست وضع ویزای سراسری بر تمامی کشورهای جهان ---")
    async with session_factory() as session:
        with patch("bot.handlers.governance.send_to_admin_group", new_callable=AsyncMock) as mock_admin_log:
            mock_call.data = "gov:visa_all_confirm"
            await cb_visa_all_confirm(mock_call, session, u_iran)
            assert_check(mock_call.message.edit_text.called, "پیام تایید وضع ویزای سراسری ارسال شد")
            call_text = mock_call.message.edit_text.call_args[0][0]
            assert_check("ویزای اجباری ورود برای تمامی کشورهای جهان با موفقیت وضع گردید" in call_text, "متن تایید وضع ویزای سراسری صحیح است")
            assert_check(mock_admin_log.called, "گزارش رسمی به گروه تحریم و لایحه ارسال شد")

            # استعلام تعداد ویزاهای وضع‌شده توسط ایران
            iran_visas = await gov_repo.get_visa_list(session, country_id=1)
            assert_check(len(iran_visas) == 5, "تمامی ۵ کشور دیگر دارای ویزای ورود شدند")
            # بررسی اینکه ایران برای خودش ویزا وضع نکرده است
            assert_check(all(v.target_country_id != 1 for v in iran_visas), "کشور خود کاربر از ویزای اجباری مستثنی است")

    print("\n--- بخش ۵: تست رفع ویزای اجباری (تکی و سراسری) ---")
    async with session_factory() as session:
        # ۵.۱ رفع ویزای تکی ژاپن
        with patch("bot.handlers.governance.send_to_admin_group", new_callable=AsyncMock):
            mock_call.data = "gov_vrm_do:6:0"  # ژاپن id=6
            await cb_visa_rm_do(mock_call, session, u_iran)
            has_jpn_visa = await gov_repo.has_visa(session, country_id=1, target_country_id=6)
            assert_check(has_jpn_visa is False, "ویزای ژاپن به صورت تکی با موفقیت حذف شد")

        # ۵.۲ رفع ویزای سراسری (عادی‌سازی مرزها)
        with patch("bot.handlers.governance.send_to_admin_group", new_callable=AsyncMock):
            mock_call.data = "gov_vrm_all_confirm"
            await cb_visa_rm_all_confirm(mock_call, session, u_iran)
            iran_visas_after = await gov_repo.get_visa_list(session, country_id=1)
            assert_check(len(iran_visas_after) == 0, "کلیه ویزاهای اجباری با عملیات رفع سراسری حذف شدند")

    print("\n--- بخش ۶: تست وضع ویزای منطقه‌ای (قاره‌ای) ---")
    async with session_factory() as session:
        # وضع ویزا برای تمام کشورهای منطقه europe (آلمان و فرانسه)
        with patch("bot.handlers.governance.send_to_admin_group", new_callable=AsyncMock):
            mock_call.data = "gov_vreg_do:europe"
            await cb_visa_region_do(mock_call, session, u_iran)

            has_ger = await gov_repo.has_visa(session, country_id=1, target_country_id=2)
            has_fra = await gov_repo.has_visa(session, country_id=1, target_country_id=3)
            has_chn = await gov_repo.has_visa(session, country_id=1, target_country_id=4)

            assert_check(has_ger is True, "ویزای آلمان در منطقه اروپا وضع شد")
            assert_check(has_fra is True, "ویزای فرانسه در منطقه اروپا وضع شد")
            assert_check(has_chn is False, "کشور چین خارج از منطقه اروپا دست‌نخورده باقی ماند")

    print("\n--- بخش ۷: تست یکپارچگی لغو روادید نشست حضوری و تخفیف حمل‌ونقل ---")
    async with session_factory() as session:
        # ایران برای آلمان ویزا داشت. حالا فرض کنیم در نشست با آلمان توافق لغو ویزا ثبت می‌شود
        # افزودن توافق لغو ویزا و حذف ویزای اجباری
        await dip_repo.add_visa_waiver(session, country_id=1, target_country_id=2)
        await gov_repo.remove_visa(session, country_id=1, target_country_id=2)
        await session.commit()

        # بررسی تخفیف عوارض لجستیک:
        is_waived = await dip_repo.is_shipping_visa_waived(session, origin_country_id=1, dest_country_id=2)
        assert_check(is_waived is True, "تخفیف ۵۰٪ عوارض لجستیک برای مسیر ایران-آلمان فعال شد")

        # بررسی داشبورد پس از توافق نشست:
        data_updated = await _build_visa_dashboard_data(session, c_iran)
        assert_check(2 in data_updated["granted_target_ids"], "آلمان اکنون در دسته لغو روادید اعطایی قرار دارد")
        assert_check(await gov_repo.has_visa(session, 1, 2) is False, "ویزای اجباری آلمان برداشته شده است")

    print("\n==========================================")
    print(f"🎉 تمامی تست‌های سامانه ویزا با موفقیت پاس شدند! ({passed}/{total})")
    print("==========================================")


if __name__ == "__main__":
    asyncio.run(run_tests())
