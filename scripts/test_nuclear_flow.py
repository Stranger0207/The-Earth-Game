"""
تست یکپارچه‌ی برنامه‌ی هسته‌ای (v1.10.4) روی SQLite.

فلوی کامل فاز ۱ تا ۵ را با جهش زمانی شبیه‌سازی می‌کند:
تحقیقات ← تأسیسات ← زنجیره‌ی سوخت ← سانتریفیوژ ← غنی‌سازی ۴ رده ← کلاهک ← آزمایش.

اجرا:
    BOT_TOKEN=... DATABASE_URL="sqlite+aiosqlite:///./test_nuc.db" python -m scripts.test_nuclear_flow
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.constants import (  # noqa: E402
    CENTRIFUGE_BATCH_SIZE,
    CONVERSION_UF6_PER_24H,
    MILL_YELLOWCAKE_PER_24H,
    WARHEAD_HEU_REQUIRED_KG,
)
from bot.database.base import async_session_factory, init_db  # noqa: E402
from bot.database.models import Country, Reserve  # noqa: E402
from bot.database.repositories import nuclear as nuc_repo  # noqa: E402
from bot.enums import (  # noqa: E402
    DeliverySystem,
    NuclearFacilityStatus,
    NuclearFacilityType,
    NuclearTechType,
    ResourceType,
    WarheadStatus,
)
from bot.services import nuclear_service  # noqa: E402

OK = "✅"
BAD = "❌"
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    """ثبت نتیجه‌ی یک بررسی."""
    if condition:
        print(f"  {OK} {label}")
    else:
        print(f"  {BAD} {label} {detail}")
        failures.append(label)


async def main() -> None:
    await init_db()

    async with async_session_factory() as session:
        # --- ساخت کشور آزمایشی VIP با بودجه و منابع فراوان ---
        country = Country(
            name_en="TestNukeLand",
            name_fa="آزمون‌ستان",
            flag="🏳",
            region="test",
            is_vip=True,
            population=1_000_000,
            budget=500_000_000_000_000.0,
            economic_power=90.0,
            public_satisfaction=60.0,
            stability=60.0,
        )
        session.add(country)
        await session.flush()

        for rtype, amount in (
            (ResourceType.URANIUM, 5000.0),
            (ResourceType.STEEL, 50_000_000.0),
            (ResourceType.ALUMINUM, 50_000_000.0),
            (ResourceType.COAL, 50_000_000.0),
            (ResourceType.GOLD, 500_000.0),
        ):
            session.add(
                Reserve(
                    country_id=country.id,
                    resource=rtype.value,
                    amount=amount,
                    can_extract=True,
                )
            )
        await session.commit()
        print(f"\n🏳 کشور آزمایشی ساخته شد (VIP، بودجه‌ی فراوان)\n")

        # ============================================================
        print("── ۱) تحقیقات: زنجیره‌ی پنج‌گانه ──")
        # پیش‌نیاز باید رعایت شود
        try:
            await nuclear_service.research_tech(session, country, NuclearTechType.CENTRIFUGE)
            check("پیش‌نیاز تحقیق رعایت می‌شود", False, "(بدون پیش‌نیاز اجازه داد!)")
        except nuclear_service.NuclearError:
            check("تحقیق بدون پیش‌نیاز رد می‌شود", True)

        for ttype in NuclearTechType:
            tech = await nuclear_service.research_tech(session, country, ttype)
            # جهش زمانی: تحقیق را تمام‌شده فرض می‌کنیم
            tech.is_done = True
            tech.done_at = datetime.now(timezone.utc)
        await session.commit()
        done_count = sum(1 for t in await nuc_repo.list_techs(session, country.id) if t.is_done)
        check(f"هر ۵ فناوری تحقیق شد ({done_count}/۵)", done_count == 5)

        program = await nuc_repo.get_program(session, country.id)
        check("برنامه‌ی هسته‌ای ساخته شد و وارد فاز ۱ شد", program is not None and program.phase >= 1)

        # ============================================================
        print("\n── ۲) تأسیسات: احداث کل زنجیره ──")
        built = {}
        for ftype in NuclearFacilityType:
            underground = ftype == NuclearFacilityType.ENRICHMENT_HALL
            fac = await nuclear_service.build_nuclear_facility(
                session, country, ftype, "منطقه‌ی آزمایشی", underground
            )
            # جهش زمانی: ساخت را تمام‌شده می‌کنیم
            fac.status = NuclearFacilityStatus.ACTIVE.value
            fac.built_at = datetime.now(timezone.utc)
            built[ftype] = fac
            # سقف ساخت ۱۲ساعته را دور می‌زنیم تا کل زنجیره در یک تست ساخته شود
            fac.created_at = datetime.now(timezone.utc) - timedelta(hours=24)
        await session.commit()
        check(f"هر ۶ نوع تأسیسات ساخته شد ({len(built)}/۶)", len(built) == 6)
        check(
            "سالن غنی‌سازی زیرزمینی ثبت شد",
            built[NuclearFacilityType.ENRICHMENT_HALL].is_underground,
        )

        # سقف تعداد باید رعایت شود (آزمایشگاه تسلیحاتی: حداکثر ۱)
        try:
            await nuclear_service.build_nuclear_facility(
                session, country, NuclearFacilityType.WEAPONS_LAB, "جای دوم", False
            )
            check("سقف تعداد تأسیسات رعایت می‌شود", False, "(دومی را هم ساخت!)")
        except nuclear_service.NuclearError:
            check("ساخت بیش از سقف مجاز رد می‌شود", True)

        # ============================================================
        print("\n── ۳) زنجیره‌ی سوخت: اورانیوم ← کیک زرد ← UF6 ──")
        program = await nuc_repo.get_program(session, country.id)
        # شبیه‌سازی چند چرخه‌ی ۲۴ساعته‌ی زنجیره
        from bot.database.repositories import reserves as reserves_repo

        for _cycle in range(30):
            mills = await nuc_repo.list_active_facilities(
                session, country.id, NuclearFacilityType.MILL
            )
            for mill in mills:
                from bot.constants import MILL_URANIUM_INTAKE_PER_24H

                if await reserves_repo.has_enough(
                    session, country.id, ResourceType.URANIUM, MILL_URANIUM_INTAKE_PER_24H
                ):
                    await reserves_repo.add_amount(
                        session, country.id, ResourceType.URANIUM, -MILL_URANIUM_INTAKE_PER_24H
                    )
                    program.yellowcake_tons += MILL_YELLOWCAKE_PER_24H
            convs = await nuc_repo.list_active_facilities(
                session, country.id, NuclearFacilityType.CONVERSION
            )
            for _conv in convs:
                from bot.constants import CONVERSION_YELLOWCAKE_INTAKE_PER_24H

                if program.yellowcake_tons >= CONVERSION_YELLOWCAKE_INTAKE_PER_24H:
                    program.yellowcake_tons -= CONVERSION_YELLOWCAKE_INTAKE_PER_24H
                    program.uf6_tons += CONVERSION_UF6_PER_24H
        await session.commit()
        check(f"کیک زرد تولید شد ({program.yellowcake_tons:.1f} تن)", program.yellowcake_tons > 0)
        check(f"گاز UF6 تولید شد ({program.uf6_tons:.1f} تن)", program.uf6_tons > 0)

        # ============================================================
        print("\n── ۴) سانتریفیوژ ──")
        await nuclear_service.produce_centrifuges(session, country)
        program.centrifuge_batch_done_at = None
        program.centrifuges += CENTRIFUGE_BATCH_SIZE
        # چند چرخه برای رسیدن به تعداد کافی
        for _ in range(9):
            program.centrifuges += CENTRIFUGE_BATCH_SIZE
        await session.commit()
        check(f"سانتریفیوژ تولید شد ({program.centrifuges:,} عدد)", program.centrifuges >= 5000)

        capacity = await nuc_repo.enrichment_capacity(session, country.id)
        check(f"ظرفیت سالن غنی‌سازی محاسبه شد ({capacity:,})", capacity > 0)

        # ============================================================
        print("\n── ۵) غنی‌سازی: چهار رده تا HEU ۹۰٪ ──")
        tier_labels = {
            "u235_35": "۳.۵٪",
            "u235_20": "۲۰٪",
            "u235_60": "۶۰٪",
            "u235_90": "۹۰٪ (تسلیحاتی)",
        }
        now = datetime.now(timezone.utc)
        for tier_key in ("u235_35", "u235_20", "u235_60", "u235_90"):
            alloc = min(program.centrifuges, capacity)
            await nuclear_service.start_enrichment(session, country, tier_key, alloc)
            # شبیه‌سازی گذر زمان: هر گام ۲۴ ساعت جلو می‌رود
            for step in range(40):
                now = now + timedelta(hours=24)
                nuclear_service.enrichment_tick(program, now)
            stock = nuclear_service.tier_stock_kg(program, tier_key)
            check(f"رده‌ی {tier_labels[tier_key]} تولید شد ({stock:.1f} kg)", stock > 0)
            await nuclear_service.stop_enrichment(session, country)
            program.last_enrich_tick_at = now
        await session.commit()

        heu = program.heu_90_kg
        check(
            f"HEU کافی برای کلاهک انباشته شد ({heu:.1f} از {WARHEAD_HEU_REQUIRED_KG} kg)",
            heu >= WARHEAD_HEU_REQUIRED_KG,
        )

        # ============================================================
        print("\n── ۶) کلاهک و سامانه‌ی حمل ──")
        warhead = await nuclear_service.assemble_warhead(session, country, "آزمون-۱")
        await session.commit()
        check("مونتاژ کلاهک آغاز شد", warhead.status == WarheadStatus.ASSEMBLING.value)
        check(
            f"HEU مصرف شد ({WARHEAD_HEU_REQUIRED_KG} kg کسر شد)",
            abs((heu - program.heu_90_kg) - WARHEAD_HEU_REQUIRED_KG) < 0.01,
        )

        # جهش زمانی: مونتاژ تمام شد
        warhead.status = WarheadStatus.ASSEMBLED.value
        warhead.assembled_at = datetime.now(timezone.utc)
        await session.commit()

        await nuclear_service.mount_warhead(session, country, warhead.id, DeliverySystem.BALLISTIC)
        await session.commit()
        check("کلاهک روی موشک بالستیک نصب شد", warhead.status == WarheadStatus.MOUNTED.value)

        ready = await nuc_repo.count_ready_warheads(session, country.id)
        deterrence = await nuclear_service.deterrence_defense_pct(session, country.id)
        check(f"بازدارندگی فعال شد ({deterrence:.0f}٪ کاهش خسارت، {ready} کلاهک)", deterrence > 0)

        # ============================================================
        print("\n── ۷) آزمایش هسته‌ای ──")
        sat_before = country.public_satisfaction
        test = await nuclear_service.schedule_nuclear_test(session, country, warhead.id)
        await session.commit()
        check("آزمایش زمان‌بندی شد", test.status == "pending")
        check("کلاهک در آزمایش مصرف شد", warhead.status == WarheadStatus.TESTED.value)

        nuclear_service.apply_test_effects(program, country)
        await session.commit()
        check("برنامه پس از آزمایش کاملاً افشا شد", program.is_discovered and program.exposure == 100.0)
        check(
            f"رضایت عمومی افزایش یافت ({sat_before:.0f} ← {country.public_satisfaction:.0f})",
            country.public_satisfaction > sat_before,
        )

        # ============================================================
        print("\n── ۸) پنهان‌کاری و خرابکاری ──")
        program.is_discovered = False
        program.exposure = 50.0
        program.civilian_cover = True
        before_exp = program.exposure
        nuclear_service.add_exposure(program, 10.0)
        check(
            f"پوشش صلح‌آمیز افشا را کم می‌کند (+{program.exposure - before_exp:.0f} به‌جای +۱۰)",
            (program.exposure - before_exp) < 10.0,
        )

        # با پوشش فعال، غنی‌سازی بالای ۲۰٪ باید رد شود
        try:
            await nuclear_service.start_enrichment(session, country, "u235_90", 100)
            check("پوشش صلح‌آمیز سقف ۲۰٪ را اعمال می‌کند", False, "(اجازه‌ی ۹۰٪ داد!)")
        except nuclear_service.NuclearError:
            check("با پوشش صلح‌آمیز، غنی‌سازی ۹۰٪ رد می‌شود", True)

        cent_before = program.centrifuges
        lost = await nuclear_service.apply_sabotage_damage(session, country.id, 0.4)
        check(
            f"خرابکاری سایبری {lost:,} سانتریفیوژ را نابود کرد",
            lost > 0 and program.centrifuges < cent_before,
        )

        hall = built[NuclearFacilityType.ENRICHMENT_HALL]
        await nuclear_service.apply_strike_damage(session, hall, 80.0)
        check(
            f"تأسیسات زیرزمینی نصف خسارت گرفت (سلامت: {hall.integrity_pct:.0f}٪)",
            hall.integrity_pct == 60.0,
        )
        await session.commit()

        # ============================================================
        print("\n── ۹) دسترسی غیر VIP ──")
        plain = Country(
            name_en="TestPlain",
            name_fa="عادی‌ستان",
            flag="🏳",
            region="test",
            is_vip=False,
            budget=1e15,
        )
        session.add(plain)
        await session.flush()
        try:
            await nuclear_service.ensure_program(session, plain)
            check("دسترسی غیر VIP مسدود است", False, "(اجازه داد!)")
        except nuclear_service.NuclearError:
            check("کشور غیر VIP به برنامه‌ی هسته‌ای دسترسی ندارد", True)

        await session.rollback()

    print("\n" + "=" * 50)
    if failures:
        print(f"{BAD} {len(failures)} بررسی ناموفق:")
        for f in failures:
            print(f"   - {f}")
        sys.exit(1)
    print(f"{OK} همه‌ی بررسی‌ها موفق بودند — فلوی فاز ۱ تا ۵ سالم است.")


if __name__ == "__main__":
    asyncio.run(main())
