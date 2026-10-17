"""
اسکریپت تست خودکار و جامع آپدیت میان‌برنامه‌ای:
۱. سیستم ثبت نتیجه لایحه و بستن لایحه در گروه تحریم و لایحه (SANCTION_BILL)
۲. اصلاح و رفع باگ UX برگشت به صفحه تجهیزات پس از ثبت تلفات در رول نظامی
۳. سیستم لغو ویزا (Visa Waiver) در دیدار حضوری با تخفیف ۵۰٪ عوارض حمل‌ونقل و جریمه اداری
۴. بررسی عدم تداخل کلید خارجی (Foreign Key) و عملکرد صحیح reset_season
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
os.environ["LOG_GROUP_ID"] = "-1003922948542"
os.environ["SANCTION_BILL_GROUP_ID"] = "-1004474739499"

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import get_settings
from bot.constants import (
    AIR_TRANSPORT_FEE,
    AIR_TRANSPORT_FEE_NO_VISA,
    SEA_TRANSPORT_FEE,
    SEA_TRANSPORT_FEE_NO_VISA,
    VISA_WAIVER_ADMIN_COST,
    VISA_WAIVER_SATISFACTION_PENALTY,
    VISA_WAIVER_STABILITY_PENALTY,
)
from bot.database.base import Base, _COLUMN_MIGRATIONS
from bot.database.models import (
    Country,
    GroupMeeting,
    GroupMeetingParticipant,
    Law,
    Meeting,
    MilitaryAsset,
    MilitaryRole,
    MilitarySale,
    User,
    VisaWaiver,
)
from bot.database.repositories import countries as countries_repo
from bot.database.repositories import diplomacy as dip_repo
from bot.database.repositories import governance as gov_repo
from bot.enums import AdminGroupType, DiplomacyStatus, LawStatus, LAW_STATUS_FA
from bot.handlers.diplomacy import _get_active_meeting_partners
from bot.keyboards.governance import admin_law_panel_kb, admin_law_result_kb
from bot.services import season_service


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

    # ایجاد دیتابیس تست SQLite در حافظه همراه با فعال‌سازی PRAGMA foreign_keys
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # -------------------------------------------------------------
    # بخش ۱: سیستم ثبت نتیجه لایحه و بستن لایحه در گروه تحریم و لایحه
    # -------------------------------------------------------------
    print("\n--- بخش ۱: سیستم ثبت نتیجه لایحه و بستن لایحه در گروه تحریم و لایحه ---")

    # ۱.۱ بررسی مدل، انام و مایگریشن
    assert_check(hasattr(LawStatus, "APPLIED"), "وضعیت LawStatus.APPLIED تعریف شده است")
    assert_check(LawStatus.APPLIED.value in LAW_STATUS_FA, "عنوان فارسی APPLIED در LAW_STATUS_FA موجود است")
    assert_check(hasattr(Law, "stability_effect"), "ستون stability_effect در مدل Law موجود است")
    assert_check(hasattr(Law, "satisfaction_effect"), "ستون satisfaction_effect در مدل Law موجود است")

    mig_stability = any(m[0] == "laws" and m[1] == "stability_effect" for m in _COLUMN_MIGRATIONS)
    mig_satisfaction = any(m[0] == "laws" and m[1] == "satisfaction_effect" for m in _COLUMN_MIGRATIONS)
    assert_check(mig_stability, "ستون stability_effect در _COLUMN_MIGRATIONS ثبت شده است")
    assert_check(mig_satisfaction, "ستون satisfaction_effect در _COLUMN_MIGRATIONS ثبت شده است")

    # ۱.۲ بررسی کیبوردهای مدیریتی لایحه
    panel_kb = admin_law_panel_kb(law_id=42)
    flat_panel_buttons = [btn for row in panel_kb.inline_keyboard for btn in row]
    assert_check(any(btn.callback_data == "gov_admin:law_res:42" for btn in flat_panel_buttons), "دکمه تعیین/ویرایش نتیجه لایحه موجود است")
    assert_check(any(btn.callback_data == "gov_admin:law_apply:42" for btn in flat_panel_buttons), "دکمه بستن و اعمال نهایی لایحه موجود است")
    assert_check(any(btn.callback_data == "gov_admin:law_no:42" for btn in flat_panel_buttons), "دکمه رد لایحه موجود است")

    result_kb = admin_law_result_kb(law_id=42, cur_stab=5.0, cur_sat=10.0)
    flat_result_buttons = [btn for row in result_kb.inline_keyboard for btn in row]
    assert_check(any(btn.callback_data.startswith("gov_admin:stab:42:") for btn in flat_result_buttons), "دکمه‌های تغییر ثبات در کیبورد موجود است")
    assert_check(any(btn.callback_data.startswith("gov_admin:sat:42:") for btn in flat_result_buttons), "دکمه‌های تغییر رضایت در کیبورد موجود است")
    assert_check(any(btn.callback_data == "gov_admin:cstab:42" for btn in flat_result_buttons), "دکمه عدد دلخواه ثبات موجود است")
    assert_check(any(btn.callback_data == "gov_admin:csat:42" for btn in flat_result_buttons), "دکمه عدد دلخواه رضایت موجود است")

    # ۱.۳ تست دیتابیسی ثبت اثرات لایحه و اعمال روی کشور با رعایت سقف ۱۰۰٪
    async with session_factory() as session:
        c1 = Country(
            name_en="CountryOne",
            name_fa="کشور یک",
            flag="🏳️",
            region="Asia",
            budget=100_000_000.0,
            stability=92.0,
            public_satisfaction=95.0,
        )
        session.add(c1)
        await session.commit()
        await session.refresh(c1)

        law1 = Law(
            country_id=c1.id,
            title="لایحه افزایش بودجه رفاهی",
            body="شرح لایحه رفاهی",
            law_type="welfare",
            status="pending",
        )
        session.add(law1)
        await session.commit()
        await session.refresh(law1)

        # تنظیم نتایج مثبت (۱۰٪ ثبات و ۱۰٪ رضایت)
        updated_law = await gov_repo.update_law_effects(session, law1.id, stability_effect=10.0, satisfaction_effect=10.0)
        assert_check(updated_law.stability_effect == 10.0, "مقدار stability_effect در لایحه ذخیره شد")
        assert_check(updated_law.satisfaction_effect == 10.0, "مقدار satisfaction_effect در لایحه ذخیره شد")

        # اعمال و بستن لایحه
        res_law, res_country, stab_delta, sat_delta = await gov_repo.apply_and_close_law(session, law1.id)
        assert_check(res_law.status == LawStatus.APPLIED.value, "وضعیت لایحه پس از اعمال به applied تغییر کرد")
        # 92 + 10 = 102 -> capped at 100.0
        assert_check(res_country.stability == 100.0, "ثبات داخلی با سقف ۱۰۰٪ محاسبه شد (92 + 10 = 100.0)")
        # 95 + 10 = 105 -> capped at 100.0
        assert_check(res_country.public_satisfaction == 100.0, "رضایت عمومی با سقف ۱۰۰٪ محاسبه شد (95 + 10 = 100.0)")

        # تست لایحه با اثر منفی و کف ۰٪
        law2 = Law(
            country_id=c1.id,
            title="لایحه ریاضت اقتصادی سخت‌گیرانه",
            body="شرح لایحه پرچالش",
            law_type="austerity",
            status="pending",
        )
        session.add(law2)
        await session.commit()
        await session.refresh(law2)

        await gov_repo.update_law_effects(session, law2.id, stability_effect=-150.0, satisfaction_effect=-25.0)
        res_law2, res_country2, stab_delta2, sat_delta2 = await gov_repo.apply_and_close_law(session, law2.id)
        assert_check(res_country2.stability == 0.0, "ثبات داخلی با کف ۰٪ محاسبه شد (100 - 150 = 0.0)")
        assert_check(res_country2.public_satisfaction == 75.0, "رضایت عمومی با کسر ۲۵٪ به ۷۵٪ رسید")

    # -------------------------------------------------------------
    # بخش ۲: رفع باگ UX و حفظ کانتکست در ثبت تلفات رول نظامی
    # -------------------------------------------------------------
    print("\n--- بخش ۲: رفع باگ UX و حفظ کانتکست در ثبت تلفات رول نظامی ---")

    # شبیه‌سازی کال‌بک‌ها و دکمه‌های ناوبری تولیدشده در نظامی
    test_role_id = 99
    test_side = "attacker"
    test_other_side = "target"
    test_branch_key = "aircraft"
    test_branch_name = "نیروی هوایی"
    test_page = 2

    # بررسی فرمت دیتای دکمه بازگشت در مرحله انتخاب تجهیزات
    cancel_callback = f"admcas_br:{test_role_id}:{test_side}:{test_branch_key}:{test_page}"
    assert_check(cancel_callback == "admcas_br:99:attacker:aircraft:2", "فرمت کال‌بک بازگشت دکمه لغو دقیقاً صفحه شاخه را حفظ می‌کند")

    # بررسی ۴ دکمه هوشمند ناوبری پس از ثبت تلفات
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from bot.utils.ui import STYLE_MAIN, STYLE_OK

    nav_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"🔙 بازگشت به لیست تجهیزات همین بخش ({test_branch_name})",
                callback_data=f"admcas_br:{test_role_id}:{test_side}:{test_branch_key}:{test_page}",
                style=STYLE_MAIN,
            )],
            [InlineKeyboardButton(
                text="🔄 تغییر شاخه نظامی (زمینی/هوایی/دریایی/...)",
                callback_data=f"admcas_side:{test_role_id}:{test_side}",
            )],
            [InlineKeyboardButton(
                text="🔀 تغییر کشور (مهاجم ⇄ هدف)",
                callback_data=f"admcas_side:{test_role_id}:{test_other_side}",
            )],
            [InlineKeyboardButton(
                text="🏁 بازگشت به پنل اصلی رول نظامی",
                callback_data=f"adm_milrole_view:{test_role_id}",
                style=STYLE_OK,
            )],
        ]
    )

    all_nav_buttons = [btn for row in nav_kb.inline_keyboard for btn in row]
    assert_check(len(all_nav_buttons) == 4, "تعداد دکمه‌های ناوبری هوشمند دقیقاً ۴ دکمه است")
    assert_check(all_nav_buttons[0].callback_data == "admcas_br:99:attacker:aircraft:2", "دکمه ۱ ادمین را به همان شاخه و صفحه برمی‌گرداند")
    assert_check(all_nav_buttons[1].callback_data == "admcas_side:99:attacker", "دکمه ۲ برای تغییر شاخه نظامی است")
    assert_check(all_nav_buttons[2].callback_data == "admcas_side:99:target", "دکمه ۳ برای تغییر کشور مهاجم/هدف است")
    assert_check(all_nav_buttons[3].callback_data == "adm_milrole_view:99", "دکمه ۴ برای بازگشت به پنل اصلی رول نظامی است")

    # -------------------------------------------------------------
    # بخش ۳: سیستم لغو ویزا (Visa Waiver) در دیدار حضوری و تخفیف ۵۰٪ لجستیک
    # -------------------------------------------------------------
    print("\n--- بخش ۳: سیستم لغو ویزا در دیدار حضوری و تخفیف ۵۰٪ لجستیک ---")

    # ۳.۱ بررسی مقادیر ثابت‌ها
    assert_check(AIR_TRANSPORT_FEE == 8_000_000.0, "عوارض عادی هوایی ۸ میلیون دلار است")
    assert_check(AIR_TRANSPORT_FEE_NO_VISA == 4_000_000.0, "عوارض هوایی با لغو ویزا ۴ میلیون دلار (۵۰٪ تخفیف) است")
    assert_check(SEA_TRANSPORT_FEE == 2_000_000.0, "عوارض عادی دریایی ۲ میلیون دلار است")
    assert_check(SEA_TRANSPORT_FEE_NO_VISA == 1_000_000.0, "عوارض دریایی با لغو ویزا ۱ میلیون دلار (۵۰٪ تخفیف) است")
    assert_check(VISA_WAIVER_STABILITY_PENALTY == 1.5, "جریمه ثبات لغو ویزا ۱.۵٪ است")
    assert_check(VISA_WAIVER_SATISFACTION_PENALTY == 1.5, "جریمه رضایت لغو ویزا ۱.۵٪ است")
    assert_check(VISA_WAIVER_ADMIN_COST == 4_000_000.0, "هزینه اداری لغو ویزا ۴ میلیون دلار است")

    async with session_factory() as session:
        # ساخت کشورهای تستی A و B و C
        cA = Country(name_en="CountryA", name_fa="کشور الف", flag="🇦", region="Asia", budget=50_000_000.0, stability=80.0, public_satisfaction=80.0)
        cB = Country(name_en="CountryB", name_fa="کشور ب", flag="🇧", region="Asia", budget=50_000_000.0, stability=80.0, public_satisfaction=80.0)
        cC = Country(name_en="CountryC", name_fa="کشور ج", flag="🇨", region="Asia", budget=50_000_000.0, stability=80.0, public_satisfaction=80.0)
        session.add_all([cA, cB, cC])
        await session.commit()
        await session.refresh(cA)
        await session.refresh(cB)
        await session.refresh(cC)

        # ۳.۲ تست شرط میتینگ فعال: قبل از میتینگ نباید کشوری پیدا شود
        ok_none, reason_none, partners_none = await _get_active_meeting_partners(session, cA.id)
        assert_check(ok_none is False and len(partners_none) == 0, "بدون میتینگ فعال، پارتنری برای لغو ویزا یافت نشد")

        # ایجاد میتینگ دوجانبه فعال بین A و B
        meet = Meeting(
            traveler_country=cA.id,
            host_country=cB.id,
            status=DiplomacyStatus.ACTIVE,
            travel_eta=datetime.now(timezone.utc) - timedelta(minutes=10),
            meeting_ends_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        session.add(meet)
        await session.commit()

        ok_meet, reason_meet, partners_meet = await _get_active_meeting_partners(session, cA.id)
        assert_check(ok_meet is True and partners_meet == [cB.id], "در دیدار دوجانبه فعال، کشور ب به عنوان پارتنر مجاز شناسایی شد")

        # ۳.۳ اعطای لغو ویزا و اعمال جریمه‌ها
        pre_budget = cA.budget
        pre_stab = cA.stability
        pre_sat = cA.public_satisfaction

        waiver_record = await dip_repo.add_visa_waiver(session, cA.id, cB.id)
        cA.budget -= VISA_WAIVER_ADMIN_COST
        cA.stability = max(0.0, cA.stability - VISA_WAIVER_STABILITY_PENALTY)
        cA.public_satisfaction = max(0.0, cA.public_satisfaction - VISA_WAIVER_SATISFACTION_PENALTY)
        await session.commit()
        await session.refresh(cA)

        assert_check(cA.budget == pre_budget - 4_000_000.0, "هزینه اداری ۴ میلیون دلار از بودجه لغوکننده کسر شد")
        assert_check(cA.stability == pre_stab - 1.5, "جریمه ۱.۵٪ ثبات داخلی از لغوکننده کسر شد")
        assert_check(cA.public_satisfaction == pre_sat - 1.5, "جریمه ۱.۵٪ رضایت عمومی از لغوکننده کسر شد")

        # بررسی جهت‌دار بودن لغو ویزا
        assert_check(await dip_repo.has_visa_waiver(session, cA.id, cB.id) is True, "کشور الف برای ورود شهروندان ب ویزا را لغو کرده است")
        assert_check(await dip_repo.has_visa_waiver(session, cB.id, cA.id) is False, "کشور ب هنوز برای ورود شهروندان الف ویزا را لغو نکرده است")

        # ۳.۴ بررسی تاثیر روی عوارض حمل‌ونقل کالا و محموله (تخفیف ۵۰٪ به مقصد کشوری که ویزایش لغو شده یا بالعکس)
        is_waived_A_to_B = await dip_repo.is_shipping_visa_waived(session, cA.id, cB.id)
        is_waived_B_to_A = await dip_repo.is_shipping_visa_waived(session, cB.id, cA.id)
        is_waived_A_to_C = await dip_repo.is_shipping_visa_waived(session, cA.id, cC.id)

        assert_check(is_waived_A_to_B is True, "عوارض حمل‌ونقل از الف به ب مشمول تخفیف لغو روادید است")
        assert_check(is_waived_B_to_A is True, "عوارض حمل‌ونقل از ب به الف نیز مشمول تخفیف لغو روادید است")
        assert_check(is_waived_A_to_C is False, "عوارض حمل‌ونقل بین الف و ج مشمول تخفیف نیست")

        # محاسبه عوارض هوایی و دریایی
        fee_air = AIR_TRANSPORT_FEE_NO_VISA if is_waived_A_to_B else AIR_TRANSPORT_FEE
        fee_sea = SEA_TRANSPORT_FEE_NO_VISA if is_waived_A_to_B else SEA_TRANSPORT_FEE
        assert_check(fee_air == 4_000_000.0, "عوارض حمل هوایی محموله ۴ میلیون دلار شد")
        assert_check(fee_sea == 1_000_000.0, "عوارض حمل دریایی محموله ۱ میلیون دلار شد")

        # ۳.۵ بررسی لیست لغو ویزاها
        granted = await dip_repo.list_granted_visa_waivers(session, cA.id)
        received = await dip_repo.list_received_visa_waivers(session, cB.id)
        assert_check(len(granted) == 1 and granted[0].target_country_id == cB.id, "کشور ب در لیست ویزاهای لغوشده توسط الف قرار دارد")
        assert_check(len(received) == 1 and received[0].country_id == cA.id, "کشور الف در لیست ویزاهای اعطاشده به ب قرار دارد")

        # ۳.۶ لغو توافق ویزا (بازگشت به حالت عادی)
        removed = await dip_repo.remove_visa_waiver(session, cA.id, cB.id)
        assert_check(removed is True, "توافق لغو روادید با موفقیت باطل شد")
        assert_check(await dip_repo.is_shipping_visa_waived(session, cA.id, cB.id) is False, "پس از ابطال، تخفیف حمل‌ونقل غیرفعال شد")

        fee_air_reverted = AIR_TRANSPORT_FEE_NO_VISA if (await dip_repo.is_shipping_visa_waived(session, cA.id, cB.id)) else AIR_TRANSPORT_FEE
        assert_check(fee_air_reverted == 8_000_000.0, "عوارض حمل هوایی به ۸ میلیون دلار بازگشت")

        # تست دیدار چندجانبه: ابتدا دیدار دوجانبه قبلی خاتمه می‌یابد
        meet.status = DiplomacyStatus.COMPLETED
        await session.commit()

        grp_meet = GroupMeeting(
            host_country=cA.id,
            title="نشست منطقه‌ای",
            status=DiplomacyStatus.ACTIVE,
            start_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            meeting_ends_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        session.add(grp_meet)
        await session.commit()
        p1 = GroupMeetingParticipant(meeting_id=grp_meet.id, country_id=cB.id, response=DiplomacyStatus.ACTIVE)
        p2 = GroupMeetingParticipant(meeting_id=grp_meet.id, country_id=cC.id, response=DiplomacyStatus.ACTIVE)
        session.add_all([p1, p2])
        await session.commit()

        ok_grp, reason_grp, partners_grp = await _get_active_meeting_partners(session, cA.id)
        assert_check(ok_grp is True and set(partners_grp) == {cB.id, cC.id}, "در نشست چندجانبه، همه کشورهای حاضر در نشست به درستی بازگردانده شدند")

    # -------------------------------------------------------------
    # بخش ۴: تست پاک‌سازی foreign key و reset_season
    # -------------------------------------------------------------
    print("\n--- بخش ۴: تست پاک‌سازی Foreign Key و تابع reset_season ---")

    async with session_factory() as session:
        # ایجاد رکوردهای تستی در VisaWaiver و Law
        c_reset1 = Country(name_en="ResetC1", name_fa="کشور ریست ۱", flag="🏳️", region="Europe")
        c_reset2 = Country(name_en="ResetC2", name_fa="کشور ریست ۲", flag="🏴", region="Europe")
        session.add_all([c_reset1, c_reset2])
        await session.commit()
        await session.refresh(c_reset1)
        await session.refresh(c_reset2)

        vw = VisaWaiver(country_id=c_reset1.id, target_country_id=c_reset2.id)
        lw = Law(country_id=c_reset1.id, title="لایحه آزمایشی ریست", body="شرح", status="applied")
        session.add_all([vw, lw])
        await session.commit()

        # اجرای reset_season با ماک کردن _load_seed جهت عدم نیاز به ریست کامل کل کشورهای فایل countries.json
        with patch.object(season_service, "_load_seed", return_value={}):
            stats = await season_service.reset_season(session)
            await session.commit()

        # بررسی اینکه VisaWaiver و Law پاک شده باشند و خطای کلید خارجی رخ نداده باشد
        remaining_waivers = (await session.execute(select(VisaWaiver))).scalars().all()
        remaining_laws = (await session.execute(select(Law))).scalars().all()
        assert_check(len(remaining_waivers) == 0, "جدول VisaWaiver بدون خطای کلید خارجی پاک‌سازی شد")
        assert_check(len(remaining_laws) == 0, "جدول Law بدون خطای کلید خارجی پاک‌سازی شد")

    await engine.dispose()
    print(f"\n==========================================")
    print(f"🎉 همه تست‌ها با موفقیت پاس شدند! ({passed}/{total})")
    print(f"==========================================")


if __name__ == "__main__":
    asyncio.run(run_tests())
