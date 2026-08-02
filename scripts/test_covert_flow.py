"""
تست جاسوسی، ترور و رهگیری با اسکورت (v1.10.7).

اجرا:
    PYTHONUTF8=1 BOT_TOKEN="123:test" DATABASE_URL="sqlite+aiosqlite:///./tcov.db" \
    GROQ_API_KEY="gsk_test" OWNER_IDS="1" ADMIN_IDS="1" python -m scripts.test_covert_flow

بدون نیاز به PostgreSQL، توکن واقعی یا هوش مصنوعی.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

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


async def main() -> int:
    from bot.constants import ASSASSINATION_MIN_INTEL_QUALITY, ESCORT_MAX_UNITS
    from bot.database.base import async_session_factory, engine, init_db
    from bot.database.models import (
        Commander,
        Country,
        MilitaryAsset,
        Reserve,
        ResourceSale,
    )
    from bot.database.repositories import commander_intel as intel_repo
    from bot.enums import CommanderRole, ResourceType, TradeStatus
    from bot.services import assassination_service as assn
    from bot.services import escort_service as esc
    from bot.services import espionage_service as spy
    from bot.services import interception_service as intc
    from bot.services.combat import CommittedAsset

    print("=" * 60)
    print("تست جاسوسی، ترور و اسکورت")
    print("=" * 60)

    await init_db()

    async with async_session_factory() as session:
        # ---------- آماده‌سازی ----------
        spy_c = Country(
            name_en="Iran", name_fa="ایران", flag="🇮🇷", region="middle_east",
            population=90_000_000, budget=500e9, public_satisfaction=60,
            stability=60, is_claimed=True, owner_user_id=1001,
        )
        target_c = Country(
            name_en="Israel", name_fa="اسرائیل", flag="🇮🇱", region="europe",
            population=9_500_000, budget=400e9, public_satisfaction=70,
            stability=75, is_claimed=True, owner_user_id=1002,
        )
        seller = Country(
            name_en="Russia", name_fa="روسیه", flag="🇷🇺", region="europe",
            population=144_000_000, budget=900e9, public_satisfaction=55,
            stability=60, is_claimed=True,
        )
        buyer = Country(
            name_en="India", name_fa="هند", flag="🇮🇳", region="middle_east",
            population=1_400_000_000, budget=600e9, public_satisfaction=60,
            stability=60, is_claimed=True,
        )
        far = Country(
            name_en="Brazil", name_fa="برزیل", flag="🇧🇷", region="americas",
            population=215_000_000, budget=300e9, public_satisfaction=60,
            stability=60, is_claimed=True,
        )
        session.add_all([spy_c, target_c, seller, buyer, far])
        await session.flush()

        for c in (spy_c, seller):
            session.add(Reserve(
                country_id=c.id, resource=ResourceType.OIL.value,
                amount=300.0, can_extract=True,
            ))
            session.add_all([
                MilitaryAsset(country_id=c.id, branch="نیروی دریایی",
                              category="ناوشکن", name="ناوشکن", unit="فروند", count=15),
                MilitaryAsset(country_id=c.id, branch="نیروی هوایی",
                              category="جنگنده", name="F-14", unit="فروند", count=40),
                MilitaryAsset(country_id=c.id, branch="خودروهای زمینی",
                              category="تانک", name="T-72", unit="دستگاه", count=100),
            ])

        commander = Commander(
            country_id=target_c.id, name="کوهن", rank_title="سرلشکر",
            role=CommanderRole.AIR.value, bonus_pct=10.0, is_alive=True,
        )
        session.add(commander)
        await session.commit()

        # ============================================================
        #  ۱) ترور بدون جاسوسی
        # ============================================================
        print("\n[۱] ترور بدون اطلاعات جاسوسی")
        try:
            await assn.resolve_assassination(
                session, spy_c, target_c, commander=commander, seed=1
            )
            check("ترور بدون جاسوسی رد می‌شود", False, "رد نشد")
        except assn.AssassinationError as err:
            check("ترور بدون جاسوسی رد می‌شود", "اطلاعات" in str(err), str(err)[:40])

        # ============================================================
        #  ۲) عملیات جاسوسی
        # ============================================================
        print("\n[۲] عملیات جاسوسی")
        assets_before = spy_c.budget
        result = await spy.run_espionage(session, spy_c, target_c, commander, seed=7)
        await session.commit()

        check("هزینه‌ی جاسوسی کسر شد", spy_c.budget < assets_before)
        check("عملیات نتیجه برگرداند", isinstance(result, dict))

        if result["success"]:
            check("محل فرمانده کشف شد", bool(result["location"]))
            check("الگوی رفتاری کشف شد", bool(result["routine"]))
            check("کیفیت اطلاعات در بازه‌ی معتبر است",
                  0 < result["quality"] <= 100, str(result["quality"]))
            check("برچسب کیفیت تولید شد", bool(result["quality_label"]))
            check("اطلاعات در دیتابیس ذخیره شد",
                  await intel_repo.get_valid_intel(session, spy_c.id, commander.id) is not None)
        else:
            check("عملیات ناموفق اطلاعات نمی‌سازد",
                  await intel_repo.get_valid_intel(session, spy_c.id, commander.id) is None)

        # کول‌داون
        try:
            await spy.assert_can_spy(session, spy_c)
            check("کول‌داون جاسوسی فعال است", False, "کول‌داون کار نکرد")
        except spy.EspionageError:
            check("کول‌داون جاسوسی فعال است", True)

        # ============================================================
        #  ۳) وضعیت اطلاعاتی اهداف
        # ============================================================
        print("\n[۳] وضعیت اطلاعاتی اهداف")
        rows = await spy.targets_with_intel_status(session, spy_c.id, target_c.id)
        check("فهرست اهداف تولید شد", len(rows) == 1, f"{len(rows)} هدف")
        if rows:
            check("وضعیت اطلاعات هر هدف مشخص است", "has_intel" in rows[0])
            check("برچسب کیفیت برای نمایش آماده است", bool(rows[0]["quality_label"]))

        # کشور بدون جاسوسی نباید اطلاعات ببیند
        other_rows = await spy.targets_with_intel_status(session, seller.id, target_c.id)
        check("اطلاعات بین کشورها به اشتراک گذاشته نمی‌شود",
              not any(r["has_intel"] for r in other_rows))

        # ============================================================
        #  ۴) ترور با اطلاعات
        # ============================================================
        print("\n[۴] ترور با اطلاعات معتبر")
        intel = await intel_repo.get_valid_intel(session, spy_c.id, commander.id)
        if intel is None:
            # جاسوسی ناموفق بود؛ برای ادامه‌ی تست اطلاعات دستی می‌سازیم
            from bot.database.models import CommanderIntel

            intel = await intel_repo.add_intel(session, CommanderIntel(
                spy_country_id=spy_c.id, commander_id=commander.id,
                target_country_id=target_c.id, quality=70.0,
                known_location="پایگاه هوایی", routine_note="تردد ثابت",
                expires_at=_utcnow() + timedelta(hours=48),
            ))
            await session.commit()

        bonus_before = await _air_bonus(session, target_c.id)
        outcome = await assn.resolve_assassination(
            session, spy_c, target_c, commander=commander, seed=3
        )
        await session.commit()

        check("ترور با اطلاعات اجرا شد", isinstance(outcome, dict))
        check("کیفیت اطلاعات در نتیجه ثبت شد", outcome["intel_quality"] > 0)
        check("اطلاعات پس از عملیات مصرف شد",
              await intel_repo.get_valid_intel(session, spy_c.id, commander.id) is None)

        if outcome["success"]:
            bonus_after = await _air_bonus(session, target_c.id)
            check("بونوس فرمانده ترورشده صفر شد",
                  bonus_after < bonus_before, f"{bonus_before} → {bonus_after}")
            check("اثر عملیات توضیح داده شد", bool(outcome["effect_note"]))

        # ============================================================
        #  ۵) اسکورت محموله
        # ============================================================
        print("\n[۵] تخصیص اسکورت")
        sale = ResourceSale(
            seller_country=seller.id, buyer_country=buyer.id,
            resource=ResourceType.OIL.value, amount=50.0, price=1e9,
            status=TradeStatus.IN_TRANSIT,
            ship_eta=_utcnow() + timedelta(hours=2),
        )
        session.add(sale)
        await session.flush()

        allowed = await esc.available_escort_assets(session, seller.id)
        names = {a["name"] for a in allowed}
        check("تجهیزات دریایی مجاز اسکورت‌اند", "ناوشکن" in names)
        check("تجهیزات هوایی مجاز اسکورت‌اند", "F-14" in names)
        check("تانک مجاز اسکورت نیست", "T-72" not in names, str(names))

        escort_payload = [{
            "name": "ناوشکن", "count": 6, "unit": "فروند",
            "category": "ناوشکن", "branch": "نیروی دریایی",
        }]
        power = await esc.attach_escort(session, seller, sale, escort_payload)
        await session.commit()

        check("قدرت اسکورت محاسبه شد", power > 0, str(power))
        check("قدرت روی محموله ذخیره شد", sale.escort_power == power)
        check("برچسب اسکورت تولید شد", "اسکورت" in intc.escort_label(power))
        check("آستانه‌ی شکستن بیشتر از قدرت اسکورت است",
              intc.required_power(power) > power)

        # سقف اسکورت
        try:
            await esc.validate_escort(session, seller, [{
                "name": "ناوشکن", "count": ESCORT_MAX_UNITS + 10,
                "unit": "فروند", "category": "ناوشکن", "branch": "نیروی دریایی",
            }])
            check("سقف اسکورت رعایت می‌شود", False, "سقف کار نکرد")
        except esc.EscortError:
            check("سقف اسکورت رعایت می‌شود", True)

        # ============================================================
        #  ۶) فهرست محموله‌های قابل رهگیری
        # ============================================================
        print("\n[۶] محموله‌های قابل رهگیری")
        mine = await intc.interceptable_shipments(session, spy_c)
        check("کشور روی مسیر محموله را می‌بیند", len(mine) == 1, f"{len(mine)}")
        if mine:
            check("وضعیت اسکورت در فهرست هست", mine[0]["escort_power"] == power)
            check("حداقل قدرت لازم اعلام شده", mine[0]["required_power"] > 0)

        check("کشور خارج از مسیر محموله را نمی‌بیند",
              len(await intc.interceptable_shipments(session, far)) == 0)
        check("فروشنده محموله‌ی خودش را رهگیری نمی‌کند",
              len(await intc.interceptable_shipments(session, seller)) == 0)
        check("خریدار محموله‌ی خودش را رهگیری نمی‌کند",
              len(await intc.interceptable_shipments(session, buyer)) == 0)

        # ============================================================
        #  ۷) رهگیری با نیروی ناکافی
        # ============================================================
        print("\n[۷] رهگیری با نیروی ناکافی")
        weak = [CommittedAsset("F-14", 2, "نیروی هوایی", "جنگنده", "فروند")]
        weak_result = await intc.resolve_interception(
            session, spy_c, sale, committed=weak, seed=5
        )
        await session.commit()

        check("نیروی ناکافی دفع می‌شود", weak_result["repulsed"] is True)
        check("رهگیری ناموفق است", weak_result["success"] is False)
        check("رهگیر تلفات می‌دهد", len(weak_result["interceptor_losses"]) > 0)
        check("محموله سالم می‌ماند", sale.status == TradeStatus.IN_TRANSIT)

        # ============================================================
        #  ۸) رهگیری با نیروی کافی
        # ============================================================
        print("\n[۸] رهگیری با نیروی کافی")
        sale.status = TradeStatus.IN_TRANSIT
        await session.flush()

        strong = [
            CommittedAsset("ناوشکن", 12, "نیروی دریایی", "ناوشکن", "فروند"),
            CommittedAsset("F-14", 25, "نیروی هوایی", "جنگنده", "فروند"),
        ]
        strong_result = await intc.resolve_interception(
            session, spy_c, sale, committed=strong, seed=2
        )
        await session.commit()

        check("نیروی کافی اسکورت را می‌شکند", strong_result["success"] is True)
        check("قدرت حمله بیشتر از آستانه بود",
              strong_result["attack_power"] >= intc.required_power(power))
        check("اسکورت تلفات می‌دهد", len(strong_result["escort_losses"]) > 0)
        check("محموله به مقصد نمی‌رسد", sale.status != TradeStatus.IN_TRANSIT)
        check("سرنوشت محموله اعلام شد", bool(strong_result["effect_note"]))

        # ============================================================
        #  ۹) محموله‌ی بدون اسکورت
        # ============================================================
        print("\n[۹] محموله‌ی بدون اسکورت")
        plain = ResourceSale(
            seller_country=seller.id, buyer_country=buyer.id,
            resource=ResourceType.OIL.value, amount=20.0, price=5e8,
            status=TradeStatus.IN_TRANSIT,
            ship_eta=_utcnow() + timedelta(hours=3),
        )
        session.add(plain)
        await session.flush()

        listed = await intc.interceptable_shipments(session, spy_c)
        unescorted = [s for s in listed if s["sale_id"] == plain.id]
        check("محموله‌ی بی‌اسکورت در فهرست است", len(unescorted) == 1)
        if unescorted:
            check("برچسب «بدون اسکورت» درست است",
                  "بدون اسکورت" in unescorted[0]["escort_label"])
            check("آستانه‌ی شکستن صفر است", unescorted[0]["required_power"] == 0)

        plain_result = await intc.resolve_interception(session, spy_c, plain, seed=1)
        await session.commit()
        check("رهگیری بدون نیرو ممکن است", isinstance(plain_result["success"], bool))
        check("بدون اسکورت، تلفات اسکورت وجود ندارد",
              len(plain_result["escort_losses"]) == 0)

        # ============================================================
        #  ۱۰) محموله‌ی خارج از مسیر
        # ============================================================
        print("\n[۱۰] محموله‌ی خارج از مسیر")
        off_route = ResourceSale(
            seller_country=far.id, buyer_country=buyer.id,
            resource=ResourceType.OIL.value, amount=10.0, price=1e8,
            status=TradeStatus.IN_TRANSIT,
            ship_eta=_utcnow() + timedelta(hours=4),
        )
        session.add(off_route)
        await session.flush()

        try:
            await intc.resolve_interception(session, spy_c, off_route, seed=1)
            check("محموله‌ی خارج از مسیر رد می‌شود", False, "رد نشد")
        except intc.InterceptionError as err:
            check("محموله‌ی خارج از مسیر رد می‌شود", "مسیر" in str(err), str(err)[:40])

        await session.commit()

    await engine.dispose()

    print("\n" + "=" * 60)
    total = _passed + len(_failed)
    if _failed:
        print(f"❌ {len(_failed)} از {total} بررسی شکست خورد:")
        for item in _failed:
            print(f"   • {item}")
        return 1
    print(f"✅ همه‌ی {total} بررسی موفق بود.")
    return 0


async def _air_bonus(session, country_id: int) -> float:
    """بونوس فرمانده‌ی نیروی هوایی یک کشور."""
    from bot.database.repositories import commanders as cmd_repo
    from bot.enums import CommanderRole

    return await cmd_repo.bonus_for_role(session, country_id, CommanderRole.AIR)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
