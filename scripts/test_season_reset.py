"""
تست ریست فصل (`/endseason`) — رگرسیون باگ کلید خارجی commander_intel (v1.11.3).

اجرا:
    PYTHONUTF8=1 BOT_TOKEN="123:test" DATABASE_URL="sqlite+aiosqlite:///./test_season.db" \
    GROQ_API_KEY="gsk_test" OWNER_IDS="1" ADMIN_IDS="1" python -m scripts.test_season_reset

بدون نیاز به PostgreSQL، توکن واقعی یا هوش مصنوعی.

باگی که این تست جلوی برگشتش را می‌گیرد:
    `reset_season` جدول `commanders` را پاک می‌کرد ولی `commander_intel` را نه؛
    چون `commander_intel.commander_id` کلید خارجی دارد، PostgreSQL روی
    `DELETE FROM commanders` خطای ForeignKeyViolation می‌داد و کل `/endseason`
    می‌شکست. SQLite به‌صورت پیش‌فرض کلید خارجی را اجبار نمی‌کند، پس این تست
    عمداً `PRAGMA foreign_keys=ON` را روی همه‌ی اتصال‌ها فعال می‌کند تا
    رفتار PostgreSQL را بازتولید کند.

سه لایه‌ی بررسی:
    ۱) ساختاری — برای هر جدولی که ریست فصل پاک می‌کند، هر جدول ارجاع‌دهنده به آن
       هم باید پاک شود و *قبل* از آن. این لایه مدل‌های آینده را خودکار می‌گیرد.
    ۲) پوشش — هیچ جدولی از قلم نیفتاده باشد (مگر آن‌ها که عمداً باید بمانند).
    ۳) انتها-به-انتها — ریست واقعی روی SQLite با اجبار کلید خارجی.
"""

from __future__ import annotations

import asyncio
import re
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


# جدول‌هایی که ریست فصل عمداً پاک نمی‌کند (و دلیلش)
_PRESERVED: dict[str, str] = {
    "users": "حساب بازیکنان بین فصل‌ها می‌ماند",
    "countries": "به‌جای حذف، به مقدار اولیه‌ی countries.json برمی‌گردد",
    "bot_state": "وضعیت سراسری ربات (حالت تعمیر) به فصل ربطی ندارد",
    "reserves": "به‌تفکیک کشور حذف و از countries.json دوباره درج می‌شود",
    "military_assets": "به‌تفکیک کشور حذف و از countries.json دوباره درج می‌شود",
}


def _deletion_order() -> list[str]:
    """ترتیب جدول‌هایی که `reset_season` پاک می‌کند را از سورس بیرون می‌کشد.

    از روی متن سورس خوانده می‌شود (نه لیست دستی) تا با هر تغییر در
    `season_service` خودکار همگام بماند.
    """
    from bot.database import models as M

    src = (_ROOT / "bot" / "services" / "season_service.py").read_text(encoding="utf-8")
    body = src.split("async def reset_season", 1)[1]

    order: list[str] = []
    for cls_name in re.findall(r"delete\((\w+)\)", body):
        model = getattr(M, cls_name, None)
        table = getattr(model, "__tablename__", None)
        if table and table not in order:
            order.append(table)
    return order


def test_structure() -> None:
    """لایه‌ی ۱ و ۲: گراف کلید خارجی و پوشش کامل جدول‌ها."""
    from bot.database.base import Base
    from bot.database import models  # noqa: F401 — ثبت همه‌ی جدول‌ها در متادیتا

    order = _deletion_order()
    purged = set(order)
    all_tables = set(Base.metadata.tables)

    check(
        "سورس reset_season قابل تجزیه است",
        len(order) > 20,
        f"فقط {len(order)} جدول پیدا شد",
    )

    # --- لایه ۱: هر ارجاع‌دهنده به یک جدولِ پاک‌شونده، باید قبل از آن پاک شود ---
    for table_name, table in Base.metadata.tables.items():
        for fk in table.foreign_keys:
            parent = fk.column.table.name
            if parent not in purged or parent == table_name:
                continue  # والد پاک نمی‌شود، یا ارجاع به خودش (تک‌دستوری بی‌خطر است)

            check(
                f"«{table_name}» (ارجاع به «{parent}») هم پاک می‌شود",
                table_name in purged,
                f"{table_name}.{fk.parent.name} → {parent} — "
                f"delete({parent}) روی PostgreSQL خطای ForeignKeyViolation می‌دهد",
            )
            if table_name in purged:
                check(
                    f"«{table_name}» قبل از «{parent}» پاک می‌شود",
                    order.index(table_name) < order.index(parent),
                    f"ترتیب فعلی: {parent} در جایگاه {order.index(parent)}، "
                    f"{table_name} در جایگاه {order.index(table_name)}",
                )

    # --- لایه ۲: هیچ جدولی از قلم نیفتاده ---
    uncovered = sorted(all_tables - purged - set(_PRESERVED))
    check(
        "همه‌ی جدول‌ها در ریست فصل پوشش داده شده‌اند",
        not uncovered,
        f"جدول‌های پوشش‌داده‌نشده: {uncovered} — یا به reset_season اضافه کن "
        f"یا با دلیل به _PRESERVED در همین فایل",
    )

    # نگهبان صریح برای همان باگی که این تست به‌خاطرش نوشته شد
    check("commander_intel در فهرست پاک‌سازی است", "commander_intel" in purged)
    check(
        "commander_intel قبل از commanders پاک می‌شود",
        "commander_intel" in purged
        and "commanders" in purged
        and order.index("commander_intel") < order.index("commanders"),
    )


async def test_end_to_end() -> None:
    """لایه ۳: ریست واقعی با اجبار کلید خارجی (بازتولید رفتار PostgreSQL)."""
    from contextlib import asynccontextmanager

    from sqlalchemy import func, select, text
    from sqlalchemy.exc import IntegrityError

    from bot.database.base import async_session_factory, engine, init_db
    from bot.database.models import (
        Alliance,
        AllianceMember,
        BaseEquipment,
        Commander,
        CommanderIntel,
        Country,
        GroupMeeting,
        GroupMeetingParticipant,
        Letter,
        MilitaryBase,
        PhoneCall,
        PhoneCallMessage,
    )
    from bot.services.season_service import reset_season

    is_sqlite = engine.dialect.name == "sqlite"

    @asynccontextmanager
    async def fk_session():
        """سشن با اجبار کلید خارجی.

        SQLite این اجبار را پیش‌فرض خاموش دارد؛ بدون روشن‌کردنش این تست
        باگی که به‌خاطرش نوشته شده را *نمی‌بیند* (PostgreSQL همیشه اجبار می‌کند).
        """
        async with async_session_factory() as session:
            if is_sqlite:
                await session.execute(text("PRAGMA foreign_keys=ON"))
            yield session

    await init_db()

    async with fk_session() as session:
        n_countries = (await session.execute(select(func.count()).select_from(Country))).scalar()
        check("دیتابیس تست کشور دارد (اول scripts.seed را اجرا کن)", (n_countries or 0) >= 2,
              f"تعداد کشور: {n_countries}")
        if (n_countries or 0) < 2:
            return

        countries = (await session.execute(select(Country).limit(2))).scalars().all()
        c1, c2 = countries[0], countries[1]

        # اجبار کلید خارجی واقعاً روشن است؟ (وگرنه بقیه‌ی تست بی‌معنی است)
        fk_enforced = False
        try:
            session.add(CommanderIntel(
                spy_country_id=c1.id, commander_id=10**9, target_country_id=c2.id,
            ))
            await session.flush()
        except IntegrityError:
            fk_enforced = True
        await session.rollback()
        check("اجبار کلید خارجی در تست فعال است", fk_enforced,
              "بدون این، تست باگ اصلی را نمی‌دید")

    async with fk_session() as session:
        countries = (await session.execute(select(Country).limit(2))).scalars().all()
        c1, c2 = countries[0], countries[1]

        # --- ساخت داده‌ی فصل، با تمرکز روی جدول‌های وابسته (فرزندِ کلید خارجی) ---
        c1.is_claimed = True
        c1.budget = 1.0
        c1.readiness = 33.0

        cmd = Commander(country_id=c1.id, name="فرمانده تست", role="ground",
                        rank_title="سرلشکر", bonus_pct=5.0)
        session.add(cmd)
        await session.flush()

        # این ردیف دقیقاً همان چیزی است که ریست فصل را می‌شکست
        session.add(CommanderIntel(
            spy_country_id=c2.id, commander_id=cmd.id, target_country_id=c1.id,
            quality=80.0, known_location="پایگاه تست",
            expires_at=_utcnow() + timedelta(hours=6),
        ))

        base = MilitaryBase(owner_country_id=c1.id, host_country_id=c1.id,
                            base_type="air", name="پایگاه تست", location="تست")
        session.add(base)
        await session.flush()
        session.add(BaseEquipment(base_id=base.id, asset_name="F-16",
                                  branch="نیروی هوایی", count=4))

        alliance = Alliance(name="اتحاد تست", owner_country=c1.id)
        session.add(alliance)
        await session.flush()
        session.add(AllianceMember(alliance_id=alliance.id, country_id=c1.id))

        pc = PhoneCall(caller_country=c1.id, callee_country=c2.id)
        session.add(pc)
        await session.flush()
        session.add(PhoneCallMessage(call_id=pc.id, sender_country=c1.id, text="الو"))

        gm = GroupMeeting(host_country=c1.id)
        session.add(gm)
        await session.flush()
        session.add(GroupMeetingParticipant(meeting_id=gm.id, country_id=c2.id))

        # نامه + پاسخ (کلید خارجی به خودِ جدول letters)
        letter = Letter(sender_country=c1.id, recipient_country=c2.id, body="سلام")
        session.add(letter)
        await session.flush()
        session.add(Letter(sender_country=c2.id, recipient_country=c1.id,
                           body="پاسخ", parent_id=letter.id))

        await session.commit()
        c1_id, c1_name = c1.id, c1.name_en

    # --- اجرای ریست فصل ---
    async with fk_session() as session:
        raised: Exception | None = None
        result: dict[str, int] = {}
        try:
            result = await reset_season(session)
        except Exception as exc:  # noqa: BLE001
            raised = exc
            await session.rollback()

        check("reset_season بدون خطا اجرا شد", raised is None,
              f"{type(raised).__name__}: {raised}")
        if raised is not None:
            return

        check("همه‌ی کشورها ریست شدند", result.get("countries_reset", 0) >= 2,
              str(result))
        check("فرماندهان بازسازی شدند", result.get("commanders_created", 0) > 0,
              str(result))

    # --- بررسی وضعیت پس از ریست ---
    async with fk_session() as session:
        for model, name in (
            (CommanderIntel, "commander_intel"),
            (BaseEquipment, "base_equipments"),
            (AllianceMember, "alliance_members"),
            (Alliance, "alliances"),
            (PhoneCallMessage, "phone_call_messages"),
            (PhoneCall, "phone_calls"),
            (GroupMeetingParticipant, "group_meeting_participants"),
            (GroupMeeting, "group_meetings"),
            (Letter, "letters"),
            (MilitaryBase, "military_bases"),
        ):
            n = (await session.execute(select(func.count()).select_from(model))).scalar()
            check(f"«{name}» خالی شد", n == 0, f"{n} ردیف باقی مانده")

        n_cmd = (await session.execute(select(func.count()).select_from(Commander))).scalar()
        check("فرماندهان جدید ساخته شدند", (n_cmd or 0) > 0, f"تعداد: {n_cmd}")

        country = (await session.execute(
            select(Country).where(Country.id == c1_id)
        )).scalar_one()
        check("مالکیت کشور آزاد شد",
              country.is_claimed is False and country.owner_user_id is None)
        check("آمادگی رزمی صفر شد", country.readiness == 0.0,
              f"readiness={country.readiness}")
        check("بودجه از countries.json بازسازی شد", country.budget != 1.0,
              f"budget={country.budget} (نام: {c1_name})")


async def main() -> int:
    print("\n🧪 تست ریست فصل (/endseason)\n")
    print("— لایه‌ی ساختاری: گراف کلید خارجی و پوشش جدول‌ها")
    test_structure()
    print("\n— لایه‌ی انتها-به-انتها: ریست واقعی با اجبار کلید خارجی")
    await test_end_to_end()

    print(f"\n{'=' * 60}")
    if _failed:
        print(f"❌ {len(_failed)} بررسی ناموفق از {_passed + len(_failed)}:\n")
        for item in _failed:
            print(f"   • {item}")
        return 1
    print(f"✅ همه‌ی {_passed} بررسی موفق بود.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
