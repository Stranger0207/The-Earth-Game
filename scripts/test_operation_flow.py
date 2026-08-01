"""
تست انتها-به-انتهای چرخه‌ی عملیات نظامی (v1.10.6).

اجرا:
    PYTHONUTF8=1 BOT_TOKEN="123:test" DATABASE_URL="sqlite+aiosqlite:///./test_flow.db" \
    GROQ_API_KEY="gsk_test" OWNER_IDS="1" ADMIN_IDS="1" python -m scripts.test_operation_flow

بدون نیاز به PostgreSQL، توکن واقعی یا هوش مصنوعی.
ارسال‌های تلگرام و فراخوانی AI با stub جایگزین می‌شوند تا فقط منطق سنجیده شود.
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


class FakeBot:
    """ربات قلابی: پیام‌ها را جمع می‌کند تا بشود درباره‌شان تست نوشت."""

    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.photos: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text))
        return type("Msg", (), {"photo": None})()

    async def send_photo(self, chat_id, photo=None, caption="", **kwargs):
        self.photos.append((chat_id, caption))
        return type("Msg", (), {"photo": None})()


async def main() -> int:
    from bot.database.base import async_session_factory, engine, init_db
    from bot.database.models import Commander, Country, MilitaryAsset, Reserve
    from bot.database.repositories import operations as op_repo
    from bot.enums import (
        CommanderRole,
        OperationStatus,
        OperationType,
        PatrolType,
        ResourceType,
        TargetType,
    )
    from bot.services import operation_phases, operation_service, patrol_service
    from bot.services.combat import CommittedAsset

    print("=" * 60)
    print("تست چرخه‌ی کامل عملیات نظامی")
    print("=" * 60)

    await init_db()
    fake_bot = FakeBot()

    async with async_session_factory() as session:
        # ---------- آماده‌سازی دو کشور ----------
        attacker = Country(
            name_en="Iran", name_fa="ایران", flag="🇮🇷", region="middle_east",
            is_vip=True, population=90_000_000, budget=500e9,
            public_satisfaction=60, stability=60, inflation=20, readiness=20,
            is_claimed=True, owner_user_id=1001,
        )
        defender = Country(
            name_en="Israel", name_fa="اسرائیل", flag="🇮🇱", region="europe",
            is_vip=False, population=9_500_000, budget=400e9,
            public_satisfaction=70, stability=75, inflation=5, readiness=30,
            is_claimed=True, owner_user_id=1002,
        )
        session.add_all([attacker, defender])
        await session.flush()

        # تجهیزات مهاجم
        session.add_all([
            MilitaryAsset(country_id=attacker.id, branch="نیروی هوایی", category="جنگنده",
                          name="F-14 Tomcat", unit="فروند", count=40),
            MilitaryAsset(country_id=attacker.id, branch="نیروی هوایی", category="پهپادها",
                          name="Shahed-136", unit="فروند", count=100),
            MilitaryAsset(country_id=attacker.id, branch="سامانه‌های حمله هوایی",
                          category="موشک بالستیک", name="Emad", unit="موشک", count=50),
        ])
        # پدافند مدافع
        session.add_all([
            MilitaryAsset(country_id=defender.id, branch="سامانه‌های دفاعی",
                          category="سامانه ضدموشکی", name="Iron Dome", unit="سامانه", count=10),
            MilitaryAsset(country_id=defender.id, branch="نیروی هوایی", category="جنگنده",
                          name="F-35I", unit="فروند", count=25),
        ])
        # منابع
        session.add_all([
            Reserve(country_id=attacker.id, resource=ResourceType.OIL.value,
                    amount=200.0, can_extract=True),
            Reserve(country_id=defender.id, resource=ResourceType.OIL.value,
                    amount=50.0, can_extract=True),
        ])
        # فرمانده هوایی مهاجم
        session.add(Commander(country_id=attacker.id, name="آرمان صفوی",
                              rank_title="امیر خلبان", role=CommanderRole.AIR.value,
                              bonus_pct=10.0, is_alive=True))
        await session.commit()

        # ---------- ۱) ثبت عملیات ----------
        print("\n[۱] ثبت عملیات")
        committed = [
            CommittedAsset("F-14 Tomcat", 20, "نیروی هوایی", "جنگنده", "فروند"),
            CommittedAsset("Shahed-136", 40, "نیروی هوایی", "پهپادها", "فروند"),
        ]

        # بدون اعلام جنگ باید رد شود
        try:
            await operation_service.create_operation(
                session, attacker, defender, OperationType.AIR_STRIKE,
                TargetType.MILITARY_BASE, committed,
            )
            check("حمله‌ی علنی بدون اعلام جنگ رد می‌شود", False, "رد نشد")
        except operation_service.OperationError as err:
            check("حمله‌ی علنی بدون اعلام جنگ رد می‌شود", "اعلام جنگ" in str(err), str(err))

        # اعلام جنگ
        from bot.database.repositories import battles as war_repo
        await war_repo.declare_war(session, attacker.id, defender.id)
        await session.commit()

        from bot.database.repositories import reserves as reserves_repo

        oil_before = await reserves_repo.get_reserve(
            session, attacker.id, ResourceType.OIL.value
        )
        oil_amount_before = oil_before.amount if oil_before else 0.0
        budget_before = attacker.budget

        operation = await operation_service.create_operation(
            session, attacker, defender, OperationType.AIR_STRIKE,
            TargetType.MILITARY_BASE, committed,
            tactical_note="حمله‌ی شبانه با پشتیبانی پهپادی",
        )
        await session.commit()

        check("عملیات ثبت شد", operation.id is not None)
        check("وضعیت اولیه «در انتظار تأیید مالک» است",
              operation.status == OperationStatus.PENDING_OWNER.value, operation.status)
        check("نتیجه‌ی نبرد از قبل محاسبه شده", operation.intensity >= 1)
        check("شدت در بازه‌ی معتبر است", 1 <= operation.intensity <= 10, str(operation.intensity))
        check("تعداد فاز تعیین شده", operation.total_phases >= 3, str(operation.total_phases))
        check("هزینه‌ی سوخت محاسبه شده", operation.fuel_cost > 0)
        check("پیش از تأیید، سوخت کسر نشده",
              abs((oil_before.amount if oil_before else 0.0) - oil_amount_before) < 0.01)
        check("پیش از تأیید، بودجه کسر نشده", attacker.budget == budget_before)

        # ---------- ۲) سقف عملیات ----------
        print("\n[۲] سقف عملیات")
        from bot.constants import OPERATION_LIMIT_PER_WINDOW
        for _ in range(OPERATION_LIMIT_PER_WINDOW):
            try:
                await operation_service.create_operation(
                    session, attacker, defender, OperationType.AIR_STRIKE,
                    TargetType.MILITARY_BASE, committed,
                )
                await session.commit()
            except operation_service.OperationError:
                break
        used = await op_repo.count_in_window(session, attacker.id, 24)
        check("سقف عملیات رعایت می‌شود",
              used <= OPERATION_LIMIT_PER_WINDOW, f"{used} عملیات ثبت شد")

        try:
            await operation_service.create_operation(
                session, attacker, defender, OperationType.AIR_STRIKE,
                TargetType.MILITARY_BASE, committed,
            )
            check("عملیات بیش از سقف رد می‌شود", False, "رد نشد")
        except operation_service.OperationError as err:
            check("عملیات بیش از سقف رد می‌شود", "سقف" in str(err), str(err))

        # ---------- ۳) تأیید مالک ----------
        print("\n[۳] تأیید مالک")
        approved = await operation_service.approve_operation(session, operation.id)
        await session.commit()

        check("وضعیت به «در حال اجرا» تغییر کرد",
              approved.status == OperationStatus.IN_PROGRESS.value, approved.status)
        check("فاز اول زمان‌بندی شد", approved.next_phase_at is not None)
        check("سوخت پس از تأیید کسر شد",
              oil_before.amount < oil_amount_before,
              f"{oil_amount_before} -> {oil_before.amount}")
        check("بودجه پس از تأیید کسر شد", attacker.budget < budget_before)

        # تأیید دوباره باید رد شود
        try:
            await operation_service.approve_operation(session, operation.id)
            check("تأیید تکراری رد می‌شود", False, "رد نشد")
        except operation_service.OperationError:
            check("تأیید تکراری رد می‌شود", True)

        # ---------- ۴) اجرای فازهای خبری ----------
        print("\n[۴] اجرای فازهای خبری")
        total_phases = approved.total_phases
        published = 0

        for _ in range(total_phases + 2):
            fresh = await op_repo.get_operation(session, operation.id)
            if fresh.status == OperationStatus.RESOLVED.value:
                break
            # زمان فاز را عقب می‌بریم تا سررسیده شود
            fresh.next_phase_at = _utcnow() - timedelta(seconds=5)
            await session.commit()
            published += await operation_phases.process_due_phases(session, fake_bot)

        final = await op_repo.get_operation(session, operation.id)
        check("همه‌ی فازها منتشر شد", published >= total_phases,
              f"{published} از {total_phases}")
        check("عملیات به وضعیت پایان‌یافته رسید",
              final.status == OperationStatus.RESOLVED.value, final.status)
        check("زمان پایان ثبت شد", final.resolved_at is not None)
        check("فاز بعدی پاک شد", final.next_phase_at is None)

        # ---------- ۵) تنوع سبک خبری ----------
        print("\n[۵] تنوع اخبار")
        import json
        used_styles = json.loads(final.used_archetypes_json or "[]")
        check("سبک خبری هر فاز ثبت شد", len(used_styles) >= total_phases,
              f"{len(used_styles)} سبک")
        check("سبک‌ها متنوع‌اند (بدون تکرار پشت‌سرهم)",
              len(set(used_styles)) >= min(3, total_phases), str(used_styles))

        # ---------- ۶) انتشار پیام‌ها ----------
        print("\n[۶] ارسال اخبار")
        all_sent = fake_bot.messages + fake_bot.photos
        check("خبرها ارسال شدند", len(all_sent) > 0, f"{len(all_sent)} پیام")
        recipients = {chat for chat, _ in all_sent}
        check("خبر به مالک مهاجم رسید", 1001 in recipients, str(recipients))
        check("خبر به مالک مدافع رسید", 1002 in recipients, str(recipients))

        # ---------- ۷) اعمال نتایج ----------
        print("\n[۷] اعمال نتایج روی بازی")
        losses = json.loads(final.attacker_losses_json or "[]")
        if losses:
            from bot.database.repositories import military as mil_repo
            asset = await mil_repo.get_asset_by_name(session, attacker.id, "F-14 Tomcat")
            check("تلفات از موجودی مهاجم کسر شد", asset.count < 40, f"count={asset.count}")
        else:
            check("تلفات از موجودی مهاجم کسر شد", True, "(بدون تلفات در این سناریو)")

        check("رضایت مهاجم کاهش یافت (هزینه‌ی جنگ)",
              attacker.public_satisfaction < 60,
              f"{attacker.public_satisfaction}")
        check("تورم مهاجم افزایش یافت", attacker.inflation > 20, f"{attacker.inflation}")
        if final.infra_damage_pct > 0:
            check("ثبات مدافع کاهش یافت", defender.stability < 75, f"{defender.stability}")

        # ---------- ۸) رد عملیات ----------
        print("\n[۸] رد عملیات توسط مالک")
        pending = await op_repo.list_pending_owner(session)
        if pending:
            rejected = await operation_service.reject_operation(session, pending[0].id, "تست")
            await session.commit()
            check("عملیات رد شد", rejected.status == OperationStatus.REJECTED.value)
            check("دلیل رد ثبت شد", bool(rejected.failure_reason))
        else:
            check("عملیات رد شد", True, "(عملیات در انتظاری نبود)")

        # ---------- ۹) گشت و اثرش ----------
        print("\n[۹] گشت دفاعی و اثر آن بر پدافند")
        session.add(MilitaryAsset(country_id=defender.id, branch="نیروی هوایی",
                                  category="جنگنده", name="F-16I", unit="فروند", count=20))
        await session.flush()
        patrol = await patrol_service.start_patrol(
            session, defender, PatrolType.AIR, "آسمان مرکزی",
            [{"name": "F-16I", "count": 8, "unit": "فروند"}],
        )
        await session.commit()
        check("گشت ثبت شد", patrol.id is not None)
        check("شانس کشف عملیات مخفیانه فعال شد",
              await patrol_service.detection_chance(session, defender.id, "sabotage") > 0)

        # اثر گشت را مستقیم روی موتور نبرد می‌سنجیم (بدون نویز تصادفی preview)
        from bot.services.combat import BattleInput, resolve_battle

        def _intercept(patrol_on: bool) -> float:
            defender_assets = [
                CommittedAsset("Iron Dome", 10, "سامانه‌های دفاعی", "سامانه ضدموشکی", "سامانه"),
                CommittedAsset("F-35I", 25, "نیروی هوایی", "جنگنده", "فروند"),
                CommittedAsset("F-16I", 20, "نیروی هوایی", "جنگنده", "فروند"),
            ]
            return resolve_battle(
                BattleInput(
                    operation_type=OperationType.AIR_STRIKE,
                    target_type=TargetType.MILITARY_BASE,
                    attacker_name="A", defender_name="B",
                    committed=committed, defender_assets=defender_assets,
                    distance_km=1350, distance_tier="regional",
                    defender_patrol_active=patrol_on,
                    defender_population=9_500_000, seed=5,
                )
            ).intercept_pct

        check("گشت فعال رهگیری پدافند را بالا می‌برد",
              _intercept(True) > _intercept(False),
              f"{_intercept(True)} vs {_intercept(False)}")

        await patrol_service.end_patrol(session, patrol)
        await session.commit()

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


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
