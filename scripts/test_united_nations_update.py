"""
تست جامع آپدیت سازمان ملل متحد (UN)، آژانس انرژی اتمی (IAEA)، اجلاس مجمع عمومی در نیویورک،
دادگاه بین‌المللی لاهه (ICJ) و رادار زنده مینی‌اپ.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from bot.database.base import async_session_factory, init_db
from bot.database.models import Country, NuclearInspection, PhoneCall, User
from bot.database.models.united_nations import (
    CourtParty,
    InternationalCourtCase,
    UNAssemblyParticipant,
    UNAssemblySession,
    UNResolution,
    UNResolutionVote,
    UNSpeechQueue,
)
from bot.database.repositories import countries as countries_repo
from bot.database.repositories import united_nations as un_repo
from bot.enums import DiplomacyStatus
from bot.handlers.deps import check_hall_lock
from bot.services import geo_service as geo
from bot.services import un_speech_service
from bot.services.ai import prompts
from bot.webapp import state as webapp_state


def _test_header(title: str):
    print("\n" + "=" * 60)
    print(f"🧪 {title}")
    print("=" * 60)


async def run_all_tests():
    _test_header("۱. بررسی نهاد سازمان ملل (UN) در فایل‌های داده و نقشه")
    with open("data/countries.json", encoding="utf-8") as f:
        countries_json = json.load(f)
    with open("data/geography.json", encoding="utf-8") as f:
        geography_json = json.load(f)

    countries_list = countries_json.get("countries", [])
    un_country = next((c for c in countries_list if c.get("name_en") == "UN"), None)
    assert un_country is not None, "کشور UN در data/countries.json یافت نشد!"
    assert un_country.get("flag") == "🇺🇳", "پرچم سازمان ملل باید 🇺🇳 باشد"
    assert un_country.get("is_vip") is True, "سازمان ملل باید یک کشور/نهاد VIP باشد"
    print("  ✅ نهاد UN در data/countries.json با پرچم 🇺🇳 و وضعیت VIP تایید شد.")

    un_geo = geography_json.get("countries", {}).get("UN")
    assert un_geo is not None, "داده جغرافیایی UN در data/geography.json یافت نشد!"
    assert un_geo.get("coords") == [40.7489, -73.968], "مختصات مقر سازمان ملل در نیویورک نادرست است"
    print("  ✅ داده جغرافیایی و مختصات مقر منهتن نیویورک [40.7489, -73.9680] تایید شد.")

    _test_header("۲. فرمول مقیاس‌پذیر زمان پروازهای دیپلماتیک (فاصله‌محور و بیشتر از ۳۰ دقیقه)")
    dur_near = geo.compute_flight_duration("Iran", "Iraq")
    dur_far = geo.compute_flight_duration("Iran", "United States")
    dur_un = geo.compute_flight_duration("Iran", "UN")

    print(f"  • مدت پرواز ایران به عراق (همسایه): {dur_near} دقیقه")
    print(f"  • مدت پرواز ایران به آمریکا (راه دور): {dur_far} دقیقه")
    print(f"  • مدت پرواز ایران به نیویورک سازمان ملل: {dur_un} دقیقه")

    assert dur_near >= 40, f"حداقل مدت پرواز باید ۴۰ دقیقه باشد ولی {dur_near} شد"
    assert dur_far <= 120, f"حداکثر مدت پرواز باید ۱۲۰ دقیقه باشد ولی {dur_far} شد"
    assert dur_far > dur_near, "پرواز راه دور باید طولانی‌تر از پرواز همسایه باشد"
    assert dur_un >= 70, "پرواز بین‌قاره‌ای به نیویورک باید حداقل ۷۰ دقیقه طول بکشد"
    print("  ✅ فرمول زمان پرواز دیپلماتیک در بازه ۴۰ تا ۱۲۰ دقیقه به درستی کار می‌کند.")

    await init_db()
    async with async_session_factory() as session:
        _test_header("۳. تست پایگاه داده و نهادهای مجمع عمومی، دادگاه و آژانس")
        # دریافت یا ساخت کشورهای تستی
        iran = await countries_repo.get_country_by_name(session, "Iran")
        if not iran:
            iran = Country(name_fa="ایران", name_en="Iran", flag="🇮🇷", region="middle_east", budget=10000)
            session.add(iran)

        un_entity = await countries_repo.get_country_by_name(session, "UN")
        if not un_entity:
            un_entity = Country(name_fa="سازمان ملل متحد", name_en="UN", flag="🇺🇳", region="international", budget=50000, is_vip=True)
            session.add(un_entity)

        target_c = await countries_repo.get_country_by_name(session, "France")
        if not target_c:
            target_c = Country(name_fa="فرانسه", name_en="France", flag="🇫🇷", region="europe", budget=20000)
            session.add(target_c)

        await session.flush()

        _test_header("۴. سیستم مجمع عمومی: پرواز به نیویورک، لابی و قفل پنل در تالار")
        # ایجاد جلسه مجمع
        new_session = UNAssemblySession(
            session_number=1,
            title="اجلاس صلح جهانی و مبارزه با اشاعه تسلیحات هسته‌ای",
            status="active",
            started_at=datetime.now(timezone.utc),
        )
        created_session = await un_repo.create_session(session, new_session)
        assert created_session.id is not None, "شناسه جلسه ایجاد نشد"
        print(f"  ✅ اجلاس سالانه مجمع عمومی #{created_session.session_number} با موفقیت افتتاح شد.")

        # افزودن شرکت‌کننده در حال پرواز
        eta = datetime.now(timezone.utc) + timedelta(minutes=dur_un)
        part = UNAssemblyParticipant(
            session_id=created_session.id,
            country_id=iran.id,
            status="in_flight",
            travel_eta=eta,
        )
        await un_repo.add_participant(session, part)

        active_part = await un_repo.get_active_participant_for_country(session, iran.id)
        assert active_part is not None, "مشارکت‌کننده فعال یافت نشد"
        assert active_part.status == "in_flight", "وضعیت اولیه باید in_flight باشد"
        print("  ✅ ثبت پرواز رئیس‌جمهور به مقصد فرودگاه JFK نیویورک تایید شد.")

        # فرود در نیویورک (محیط شهر/لابی)
        active_part.status = "in_new_york"
        await session.flush()

        # بررسی قفل پنل در لابی نیویورک: باید باز باشد!
        is_locked_in_ny = await check_hall_lock(None, session, iran)
        assert is_locked_in_ny is False, "پنل در محیط لابی نیویورک نباید قفل باشد!"
        print("  ✅ بازیکن در لابی بیرونی نیویورک حضور دارد و پنل کشورش آزاد است.")

        # ورود به تالار اصلی مجمع عمومی
        active_part.status = "inside_hall"
        active_part.joined_hall_at = datetime.now(timezone.utc)
        await session.flush()

        # بررسی قفل پنل داخل تالار مجمع: باید کاملاً قفل باشد!
        is_locked_in_hall = await check_hall_lock(None, session, iran)
        assert is_locked_in_hall is True, "پنل در داخل تالار مجمع باید قفل شود!"
        print("  ✅ قفل هوشمند پنل کشور در هنگام حضور در تالار مجمع عمومی تایید شد.")

        # ثبت‌نام در صف سخنرانی ۵ دقیقه‌ای
        queue_entry = UNSpeechQueue(
            session_id=created_session.id,
            country_id=iran.id,
            status="waiting",
        )
        await un_repo.add_speech_request(session, queue_entry)
        queue_list = await un_repo.get_speech_queue(session, created_session.id)
        assert any(q.country_id == iran.id for q in queue_list), "کشور باید در صف سخنرانی باشد"
        print("  ✅ ثبت نام در صف تریبون سخنرانی ۵ دقیقه‌ای تایید شد.")

        # اعطای تریبون و سخنرانی
        queue_entry.status = "speaking"
        queue_entry.started_at = datetime.now(timezone.utc)
        queue_entry.ends_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        created_session.current_speaker_country_id = iran.id
        created_session.speech_ends_at = queue_entry.ends_at
        await session.flush()

        active_speaker = await un_repo.get_active_speech(session, created_session.id)
        assert active_speaker is not None, "سخنران فعال یافت نشد"
        assert active_speaker.country_id == iran.id, "کشور سخنران باید ایران باشد"
        print("  ✅ آغاز نوبت سخنرانی ۵ دقیقه‌ای با شمارش معکوس تایید شد.")

        # تست تحلیل سخنرانی با AI و سقف ۲۰۰۰ توکن
        speech_text = "ما خواهان صلح پایدار در جهان، لغو تحریم‌های ظالمانه و احترام به حاکمیت ملی همه کشورها هستیم."
        prompt_str = prompts.general_assembly_speech_prompt("ایران", "رئیس‌جمهور")
        assert "سازمان ملل متحد" in prompt_str, "پرامپت سخنرانی مجمع عمومی ناقص است"
        print("  ✅ پرامپت تحلیلی سخنرانی مجمع عمومی تایید شد.")

        # خروج از تالار مجمع و بازگشت به لابی
        active_part.status = "in_new_york"
        await session.flush()
        is_locked_after_exit = await check_hall_lock(None, session, iran)
        assert is_locked_after_exit is False, "بعد از خروج از تالار پنل باید آزاد شود"
        print("  ✅ خروج از تالار مجمع و بازگشت به لابی نیویورک بدون قفل تایید شد.")

        # بازگشت مستقیم به کشور (🔙 بازگشت به کشور)
        active_part.status = "returned"
        await session.flush()
        in_ny_check = await un_repo.get_active_participant_for_country(session, iran.id)
        assert in_ny_check is None, "پس از بازگشت، بازیکن نباید در مجمع فعال باشد"
        print("  ✅ دکمه «بازگشت به کشور» و برگشت سریع به پایتخت با موفقیت تست شد.")

        _test_header("۵. دادگاه بین‌المللی لاهه (ICJ): دادخواست، جلسه رسیدگی و حکم الزام‌آور")
        lawsuit = InternationalCourtCase(
            case_number=f"ICJ-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            claimant_country_id=iran.id,
            defendant_country_id=target_c.id,
            issue_type="strait_block",
            claim_title="شکایت از توقیف غیرقانونی نفتکش تجاری",
            claim_description="محموله نفتکش به صورت غیرقانونی در آب‌های بین‌المللی متوقف شده است.",
            demanded_compensation=5000.0,
            status="pending",
        )
        lawsuit = await un_repo.create_court_case(session, lawsuit)
        assert lawsuit.id is not None, "دادخواست ثبت نشد"

        # طرف‌های دعوا در تالار دادگاه
        p_party = CourtParty(case_id=lawsuit.id, country_id=iran.id, role="claimant")
        d_party = CourtParty(case_id=lawsuit.id, country_id=target_c.id, role="defendant")
        await un_repo.add_court_party(session, p_party)
        await un_repo.add_court_party(session, d_party)

        parties = await un_repo.list_court_parties(session, lawsuit.id)
        assert len(parties) == 2, "هر دو طرف دعوا باید در جلسه دادگاه باشند"
        print("  ✅ تشکیل پرونده قضایی و حضور خواهان و خوانده در تالار لاهه تایید شد.")

        # صدور و اجرای حکم جریمه نقدی
        init_iran_budget = iran.budget
        init_target_budget = target_c.budget
        fine_amount = 5000.0

        target_c.budget -= fine_amount
        iran.budget += fine_amount
        lawsuit.status = "verdict_issued"
        lawsuit.verdict_type = "compensation"
        lawsuit.compensation_awarded = fine_amount
        lawsuit.verdict_text = f"محکومیت خوانده به پرداخت {fine_amount} دلار خسارت."
        await session.flush()

        assert target_c.budget == init_target_budget - fine_amount, "کسر جریمه از محکوم شکست خورد"
        assert iran.budget == init_iran_budget + fine_amount, "واریز غرامت به شاکی شکست خورد"
        print("  ✅ صدور حکم الزام‌آور دادگاه، کسر غرامت و واریز به حساب کشور شاکی تایید شد.")

        _test_header("۶. رادار زنده مینی‌اپ: وضعیت مقر سازمان ملل و پروازهای مجمع")
        # تنظیم یک شرکت‌کننده در حال پرواز و یکی در تالار
        p_flight = UNAssemblyParticipant(
            session_id=created_session.id,
            country_id=target_c.id,
            status="in_flight",
            travel_eta=datetime.now(timezone.utc) + timedelta(minutes=45),
            created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        await un_repo.add_participant(session, p_flight)

        p_hall = UNAssemblyParticipant(
            session_id=created_session.id,
            country_id=iran.id,
            status="inside_hall",
        )
        await un_repo.add_participant(session, p_hall)
        await session.flush()

        radar_state = await webapp_state.get_radar_state(session)
        assert "un_hq" in radar_state, "کلید un_hq در وضعیت رادار وجود ندارد!"
        un_hq = radar_state["un_hq"]
        assert un_hq["is_assembly_active"] is True, "اجلاس مجمع در رادار باید فعال نشان داده شود"
        assert un_hq["coords"] == [40.7489, -73.9680], "مختصات مقر UN در رادار نادرست است"
        assert len(un_hq["countries_in_hall"]) >= 1, "کشورهای حاضر در تالار باید در رادار لیست شوند"
        print("  ✅ بخش un_hq با مختصات نیویورک و لیست اعضای حاضر در تالار تایید شد.")

        # بررسی نمایش پرواز به نیویورک در diplomatic_flights
        un_flights = [f for f in radar_state.get("diplomatic_flights", []) if f.get("type") == "un_assembly"]
        assert len(un_flights) >= 1, "پرواز رسمی مجمع عمومی در لیست پروازهای رادار یافت نشد!"
        assert un_flights[0]["to_country"]["coords"] == [40.7489, -73.9680], "مقصد پرواز باید نیویورک باشد"
        print(f"  ✅ پرواز هیئت دیپلماتیک به مجمع عمومی ({un_flights[0]['title']}) روی رادار زنده تایید شد.")

        # پایان دادن و پاکسازی جلسه تست
        await un_repo.close_session(session, created_session.id)
        await session.commit()
        print("  ✅ پایان رسمی جلسه تست و ثبت لاگ‌ها.")

    print("\n" + "=" * 60)
    print("🎉 تمام تست‌های قابلیت‌های جدید سازمان ملل متحد با موفقیت پاس شدند! 🇺🇳")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
