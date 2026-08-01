"""
ساخت فرماندهان NPC برای همه‌ی کشورها (v1.10.6).

اجرا:
    PYTHONUTF8=1 python -m scripts.seed_commanders

هر کشور ۳ تا ۵ فرمانده می‌گیرد. اجرای چندباره بی‌خطر است: کشورهایی که
از قبل فرمانده دارند دست‌نخورده می‌مانند (مگر با --force).

گزینه‌ها:
    --force    فرماندهان موجود را پاک و از نو می‌سازد
"""

from __future__ import annotations

import asyncio
import json
import random
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from sqlalchemy import delete  # noqa: E402

from bot.constants import (  # noqa: E402
    COMMANDER_BONUS_PCT,
    COMMANDERS_PER_COUNTRY_MAX,
    COMMANDERS_PER_COUNTRY_MIN,
)
from bot.database.base import async_session_factory, engine, init_db  # noqa: E402
from bot.database.models import Commander  # noqa: E402
from bot.database.repositories import commanders as cmd_repo  # noqa: E402
from bot.database.repositories import countries as countries_repo  # noqa: E402
from bot.enums import CommanderRole  # noqa: E402

_DATA_FILE = _ROOT / "data" / "commanders.json"

# نگاشت تخصص به کلید درجه در فایل داده
_RANK_KEY: dict[CommanderRole, str] = {
    CommanderRole.GROUND: "ground",
    CommanderRole.AIR: "air",
    CommanderRole.NAVAL: "naval",
    CommanderRole.INTELLIGENCE: "intel",
    CommanderRole.NUCLEAR: "nuclear",
}

# ترتیب اولویت تخصص‌ها: هر کشور اول این سه را می‌گیرد، بعد بقیه
_CORE_ROLES = [CommanderRole.GROUND, CommanderRole.AIR, CommanderRole.INTELLIGENCE]
_EXTRA_ROLES = [CommanderRole.NAVAL, CommanderRole.NUCLEAR]


def _load_data() -> dict:
    return json.loads(_DATA_FILE.read_text(encoding="utf-8"))


async def seed_commanders(force: bool = False) -> dict[str, int]:
    """فرماندهان همه‌ی کشورها را می‌سازد. خروجی: آمار."""
    data = _load_data()
    ranks = data["ranks"]
    names_by_region = data["names_by_region"]
    rng = random.Random(20260801)  # ثابت تا اجرای دوباره نتیجه‌ی مشابه بدهد

    stats = {"countries": 0, "created": 0, "skipped": 0, "deleted": 0}

    async with async_session_factory() as session:
        countries = await countries_repo.list_countries(session)

        for country in countries:
            existing = await cmd_repo.count_for_country(session, country.id)

            if existing and not force:
                stats["skipped"] += 1
                continue

            if existing and force:
                await session.execute(
                    delete(Commander).where(Commander.country_id == country.id)
                )
                stats["deleted"] += existing

            # استخر نام متناسب با منطقه‌ی کشور
            pool = list(names_by_region.get(country.region) or names_by_region["europe"])
            rng.shuffle(pool)

            # کشور بدون دسترسی دریایی فرمانده‌ی نیروی دریایی نمی‌گیرد
            from bot.services import geo_service as geo

            roles = list(_CORE_ROLES)
            for role in _EXTRA_ROLES:
                if role is CommanderRole.NAVAL and geo.is_landlocked(country.name_en):
                    continue
                roles.append(role)

            count = rng.randint(COMMANDERS_PER_COUNTRY_MIN, COMMANDERS_PER_COUNTRY_MAX)
            chosen_roles = roles[:count]

            for index, role in enumerate(chosen_roles):
                rank_pool = ranks.get(_RANK_KEY[role], ["سرلشکر"])
                name = pool[index % len(pool)]
                commander = Commander(
                    country_id=country.id,
                    name=name,
                    rank_title=rng.choice(rank_pool),
                    role=role.value,
                    bonus_pct=COMMANDER_BONUS_PCT.get(role, 0.0),
                    is_alive=True,
                )
                session.add(commander)
                stats["created"] += 1

            stats["countries"] += 1

        await session.commit()

    return stats


async def main() -> int:
    force = "--force" in sys.argv

    print("=" * 60)
    print("ساخت فرماندهان نظامی")
    print("=" * 60)

    await init_db()
    stats = await seed_commanders(force=force)
    await engine.dispose()

    print(f"\n✅ کشورهای پردازش‌شده: {stats['countries']}")
    print(f"   فرماندهان ساخته‌شده: {stats['created']}")
    if stats["deleted"]:
        print(f"   فرماندهان حذف‌شده (force): {stats['deleted']}")
    if stats["skipped"]:
        print(f"   کشورهای دست‌نخورده (از قبل فرمانده داشتند): {stats['skipped']}")
        print("   برای بازسازی: python -m scripts.seed_commanders --force")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
