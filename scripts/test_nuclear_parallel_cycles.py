"""
تست جامع چرخه‌های موازی تولید سانتریفیوژ در سالن‌های غنی‌سازی (v2.11.0).

سناریوهای تحت پوشش:
۱. وجود ۲ سالن غنی‌سازی → راه‌اندازی همزمان ۲ چرخه‌ی موازی (مجموعاً ۱,۰۰۰ سانتریفیوژ)
۲. کسر دقیق و مستقل هزینه‌ها (۲ برابر بودجه، فولاد و آلومینیوم) فقط یک‌بار
۳. رعایت سقف ظرفیت سالن‌ها (عدم تجاوز مجموع سانتریفیوژها + تولید جاری از ظرفیت)
۴. منابع ناکافی برای یکی از سالن‌ها (راه‌اندازی به اندازه‌ی توان و گزارش علت)
۵. جلوگیری از شروع مجدد در سالن‌های دارای چرخه‌ی فعال و پیشگیری از دوبار کلیک
۶. تحویل مستقل و Idempotent در زمان‌بند (scheduler) با جهش زمانی
۷. ادامه و تحویل امن چرخه‌ی قدیمی (Legacy Cycle) در NuclearProgram
۸. پاکسازی و ریست فصلی جدول‌ها (season_service)
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.constants import (
    CENTRIFUGE_BATCH_ALUMINUM,
    CENTRIFUGE_BATCH_COST_USD,
    CENTRIFUGE_BATCH_HOURS,
    CENTRIFUGE_BATCH_SIZE,
    CENTRIFUGE_BATCH_STEEL,
    ENRICHMENT_HALL_CENTRIFUGE_CAPACITY,
)
from bot.database.base import async_session_factory, init_db
from bot.database.models import Country, Reserve
from bot.database.models.nuclear import (
    NuclearFacility,
    NuclearProgram,
    NuclearTech,
)
from bot.database.repositories import nuclear as nuc_repo
from bot.database.repositories import reserves as reserves_repo
from bot.enums import (
    NuclearFacilityStatus,
    NuclearFacilityType,
    NuclearTechType,
    ResourceType,
)
from bot.scheduler.jobs import process_nuclear
from bot.services import nuclear_service, season_service
from bot.utils.ui import render_progress_bar

PASS_COUNT = 0
FAIL_COUNT = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASS_COUNT, FAIL_COUNT
    if condition:
        print(f"  ✅ {label}")
        PASS_COUNT += 1
    else:
        print(f"  ❌ {label} {detail}")
        FAIL_COUNT += 1


class DummyBot:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent_messages.append((chat_id, text))


async def run_all_tests() -> None:
    print("=" * 70)
    print("☢️ آغاز تست‌های جامع چرخه‌های موازی تولید سانتریفیوژ")
    print("=" * 70)

    # حذف دیتابیس تستی قبلی در صورت وجود برای تضمین idempotency
    db_path = Path("test_parallel.db")
    if db_path.exists():
        try:
            db_path.unlink()
        except Exception:
            pass

    await init_db()

    async with async_session_factory() as session:
        # ساخت کشور آزمایشی
        country = Country(
            name_en="NukeLand",
            name_fa="آزمون‌هسته‌ای",
            flag="☢️",
            region="middle_east",
            is_vip=True,
            budget=100_000_000.0,  # ۱۰۰ میلیون دلار
            economic_power=80.0,
            public_satisfaction=60.0,
            stability=60.0,
            owner_user_id=999888,
        )
        session.add(country)
        await session.flush()

        # ثبت ذخایر فولاد و آلومینیوم فراوان
        session.add(Reserve(country_id=country.id, resource=ResourceType.STEEL.value, amount=1_000_000.0))
        session.add(Reserve(country_id=country.id, resource=ResourceType.ALUMINUM.value, amount=1_000_000.0))
        await session.flush()

        # ساخت برنامه هسته‌ای
        program = NuclearProgram(country_id=country.id, centrifuges=4000, phase=3)
        session.add(program)
        await session.flush()

        # ساخت ۲ سالن غنی‌سازی فعال
        hall1 = NuclearFacility(
            country_id=country.id,
            facility_type=NuclearFacilityType.ENRICHMENT_HALL.value,
            name="سالن غنی‌سازی شماره ۱",
            location="نطنز",
            status=NuclearFacilityStatus.ACTIVE.value,
            integrity_pct=100.0,
        )
        hall2 = NuclearFacility(
            country_id=country.id,
            facility_type=NuclearFacilityType.ENRICHMENT_HALL.value,
            name="سالن غنی‌سازی شماره ۲",
            location="فردو",
            status=NuclearFacilityStatus.ACTIVE.value,
            integrity_pct=100.0,
        )
        session.add_all([hall1, hall2])
        await session.commit()

        print("\n🔹 تست ۱: ظرفیت کل سالن‌ها و محاسبه برنامه‌ریزی تولید")
        capacity = await nuc_repo.enrichment_capacity(session, country.id)
        check("ظرفیت کل ۲ سالن ۱۲,۰۰۰ است", capacity == 12000, f"(فعلی: {capacity})")

        plan = await nuclear_service.plan_centrifuge_production(session, country)
        check("تعداد سالن‌های آزاد ۲ است", len(plan.free_halls) == 2)
        check("تعداد چرخه‌های قابل اجرا ۲ است", plan.executable_count == 2)

        print("\n🔹 تست ۲: راه‌اندازی همزمان ۲ چرخه و کسر دوبرابر هزینه‌ها")
        budget_before = country.budget
        steel_res = await reserves_repo.get_reserve(session, country.id, ResourceType.STEEL)
        steel_before = steel_res.amount if steel_res else 0.0
        alum_res = await reserves_repo.get_reserve(session, country.id, ResourceType.ALUMINUM)
        alum_before = alum_res.amount if alum_res else 0.0

        res = await nuclear_service.produce_centrifuges(session, country)
        await session.commit()

        check("تعداد چرخه‌های آغازشده ۲ عدد است", res.started_cycles == 2)
        check("سالن ۱ دارای تاریخ اتمام است", hall1.centrifuge_batch_done_at is not None)
        check("سالن ۲ دارای تاریخ اتمام است", hall2.centrifuge_batch_done_at is not None)
        check("کسر دقیق دوبرابر بودجه ($4M)", country.budget == budget_before - (2 * CENTRIFUGE_BATCH_COST_USD))

        steel_res_after = await reserves_repo.get_reserve(session, country.id, ResourceType.STEEL)
        steel_after = steel_res_after.amount if steel_res_after else 0.0
        alum_res_after = await reserves_repo.get_reserve(session, country.id, ResourceType.ALUMINUM)
        alum_after = alum_res_after.amount if alum_res_after else 0.0
        check("کسر دقیق دوبرابر فولاد (160k تن)", steel_after == steel_before - (2 * CENTRIFUGE_BATCH_STEEL))
        check("کسر دقیق دوبرابر آلومینیوم (120k تن)", alum_after == alum_before - (2 * CENTRIFUGE_BATCH_ALUMINUM))

        print("\n🔹 تست ۳: تلاش برای شروع مجدد حین فعال بودن چرخه‌ها (جلوگیری از دابل کلیک)")
        try:
            await nuclear_service.produce_centrifuges(session, country)
            check("خطا در شروع چرخه تکراری", False, "(چرخه مجدد راه افتاد!)")
        except nuclear_service.NuclearError as exc:
            check("رد صحیح درخواست شروع مجدد با خطای مناسب", "دارای چرخه‌ی فعال هستند" in str(exc))

        print("\n🔹 تست ۴: تحویل در زمان‌بند (Scheduler) و Idempotency")
        dummy_bot = DummyBot()
        # جهش زمانی به ۵ ساعت بعد (هنوز تمام نشده)
        past_time = datetime.now(timezone.utc) + timedelta(hours=5)
        # زمان‌بند اجرا می‌شود ولی نباید تحویل دهد
        await process_nuclear(dummy_bot)
        check("قبل از سررسید سانتریفیوژ اضافه نشد", program.centrifuges == 4000)

        # جهش زمانی به ۶.۵ ساعت بعد (چرخه‌ها سررسید شده‌اند)
        hall1.centrifuge_batch_done_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        hall2.centrifuge_batch_done_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        await session.commit()

        await process_nuclear(dummy_bot)
        await session.refresh(program)
        await session.refresh(hall1)
        await session.refresh(hall2)
        check("افزایش ۱,۰۰۰ سانتریفیوژ با تحویل هر ۲ سالن", program.centrifuges == 5000, f"(فعلی: {program.centrifuges})")
        check("چرخه‌های سالن‌ها پاک شدند (None)", hall1.centrifuge_batch_done_at is None and hall2.centrifuge_batch_done_at is None)

        # اجرای مجدد زمان‌بند (بررسی Idempotency)
        await process_nuclear(dummy_bot)
        await session.refresh(program)
        check("اجرای مجدد زمان‌بند مقداری اضافه نکرد (Idempotent)", program.centrifuges == 5000)

        print("\n🔹 تست ۵: محدودیت منابع برای یکی از دو سالن")
        # کاهش بودجه به ۳ میلیون دلار (کافی فقط برای ۱ چرخه ۲ میلیونی)
        country.budget = 3_000_000.0
        await session.commit()

        plan5 = await nuclear_service.plan_centrifuge_production(session, country)
        check("سالن‌های آزاد ۲ تاست ولی قابل اجرا ۱ است", plan5.executable_count == 1)
        check("دلیل محدودیت کسری بودجه است", "کسری بودجه" in plan5.limit_reason)

        res5 = await nuclear_service.produce_centrifuges(session, country)
        await session.commit()
        check("فقط ۱ چرخه آغاز شد", res5.started_cycles == 1)
        check("سالن ۱ چرخه فعال دارد ولی سالن ۲ آزاد ماند", hall1.centrifuge_batch_done_at is not None and hall2.centrifuge_batch_done_at is None)
        check("کسر بودجه فقط برای ۱ چرخه ($2M)", country.budget == 1_000_000.0)

        # پاک کردن چرخه برای تست بعدی
        hall1.centrifuge_batch_done_at = None
        await session.commit()

        print("\n🔹 تست ۶: محدودیت سقف ظرفیت سالن‌ها")
        # افزایش موجودی به ۱۱,۸۰۰ (ظرفیت ۱۲,۰۰۰، فقط ۲۰۰ تا جا هست و چرخه ۵۰۰ تایی جا نمی‌شود)
        program.centrifuges = 11_800
        country.budget = 50_000_000.0
        await session.commit()

        plan6 = await nuclear_service.plan_centrifuge_production(session, country)
        check("چرخه قابل اجرا به دلیل تکمیل ظرفیت ۰ است", plan6.executable_count == 0)
        try:
            await nuclear_service.produce_centrifuges(session, country)
            check("خطا در شروع چرخه با ظرفیت تکمیل", False)
        except nuclear_service.NuclearError as exc:
            check("رد صحیح به دلیل سقف ظرفیت", "ظرفیت سالن‌های غنی‌سازی تکمیل است" in str(exc))

        print("\n🔹 تست ۷: پشتیبانی از چرخه‌ی قدیمی (Legacy Cycle)")
        program.centrifuges = 4000
        program.centrifuge_batch_done_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        hall1.centrifuge_batch_done_at = None
        hall2.centrifuge_batch_done_at = None
        await session.commit()

        await process_nuclear(dummy_bot)
        await session.refresh(program)
        check("چرخه‌ی قدیمی تحویل داده شد (+500)", program.centrifuges == 4500)
        check("فیلد چرخه‌ی قدیمی پاک شد (None)", program.centrifuge_batch_done_at is None)

        print("\n🔹 تست ۸: نوار پیشرفت متنی و هلپر UI")
        pb0 = render_progress_bar(0.0, 5)
        pb50 = render_progress_bar(0.5, 5)
        pb60 = render_progress_bar(0.6, 5)
        pb100 = render_progress_bar(1.0, 5)
        check("نوار ۰٪: ▱▱▱▱▱", pb0 == "▱▱▱▱▱")
        check("نوار ۵۰٪: ▰▰▱▱▱", pb50 == "▰▰▱▱▱")
        check("نوار ۶۰٪: ▰▰▰▱▱", pb60 == "▰▰▰▱▱")
        check("نوار ۱۰۰٪: ▰▰▰▰▰", pb100 == "▰▰▰▰▰")

        print("\n🔹 تست ۹: ریست فصل (Season Reset)")
        await season_service.reset_season(session)
        # اطمینان از پاک شدن تاسیسات هسته‌ای و برنامه
        facs = await nuc_repo.list_active_facilities(session, country.id, NuclearFacilityType.ENRICHMENT_HALL)
        check("سالن‌های غنی‌سازی در ریست فصل پاک شدند", len(facs) == 0)
        progs = await nuc_repo.list_active_programs(session)
        check("برنامه‌های هسته‌ای در ریست فصل پاک شدند", len(progs) == 0)

    print("\n" + "=" * 70)
    print(f"📊 نتیجه نهایی تست سانتریفیوژ: {PASS_COUNT} موفق | {FAIL_COUNT} ناموفق")
    print("=" * 70)
    if FAIL_COUNT > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
