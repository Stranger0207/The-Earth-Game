"""
سرویس گشت دفاعی (v1.10.6).

گشت فعال اثر واقعی روی بازی دارد:
- بونوس رهگیری پدافند در برابر حمله (در موتور نبرد اعمال می‌شود)
- شانس کشف خرابکاری و خنثی‌سازی ترور علیه کشور
- بونوس شانس رهگیری محموله‌های عبوری از قلمرو

گشت در سقف عملیات شمرده نمی‌شود؛ فقط سوخت مصرف می‌کند.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    PATROL_DETECT_ASSASSINATION_PCT,
    PATROL_DETECT_SABOTAGE_PCT,
    PATROL_DURATION_HOURS,
    PATROL_FUEL_BY_TYPE,
    PATROL_MAX_ACTIVE_PER_COUNTRY,
    PATROL_REQUIRED_BRANCHES,
)
from ..database.models import Country, Patrol
from ..database.repositories import military as mil_repo
from ..database.repositories import patrols as patrol_repo
from ..database.repositories import reserves as reserves_repo
from ..enums import PatrolType, ResourceType

logger = logging.getLogger(__name__)


class PatrolError(Exception):
    """خطای قابل‌نمایش به بازیکن هنگام ثبت گشت."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def available_assets(
    session: AsyncSession, country_id: int, patrol_type: PatrolType
) -> list[dict]:
    """تجهیزات کشور که برای این نوع گشت قابل‌استفاده‌اند."""
    allowed = PATROL_REQUIRED_BRANCHES.get(patrol_type, frozenset())
    assets = await mil_repo.list_assets(session, country_id)
    return [
        {
            "name": a.name,
            "count": a.count,
            "unit": a.unit,
            "category": a.category,
            "branch": a.branch,
        }
        for a in assets
        if a.count > 0 and a.branch in allowed
    ]


async def start_patrol(
    session: AsyncSession,
    country: Country,
    patrol_type: PatrolType,
    area: str,
    assets: list[dict],
) -> Patrol:
    """
    ثبت یک گشت جدید.

    assets: [{"name","count","unit"}] — تجهیزاتی که بازیکن اختصاص داده است.
    """
    active = await patrol_repo.count_active(session, country.id)
    if active >= PATROL_MAX_ACTIVE_PER_COUNTRY:
        raise PatrolError(
            f"⚠️ حداکثر {PATROL_MAX_ACTIVE_PER_COUNTRY} گشت هم‌زمان می‌توانید داشته باشید. "
            "ابتدا یکی از گشت‌های فعال را پایان دهید."
        )

    total_units = sum(int(a.get("count", 0)) for a in assets)
    if total_units <= 0:
        raise PatrolError("هیچ تجهیزاتی به این گشت اختصاص داده نشده است.")

    # بررسی موجودی واقعی
    for item in assets:
        asset = await mil_repo.get_asset_by_name(session, country.id, item["name"])
        if asset is None or asset.count < int(item["count"]):
            available = asset.count if asset else 0
            raise PatrolError(f"موجودی «{item['name']}» کافی نیست (موجودی: {available}).")

    fuel_cost = PATROL_FUEL_BY_TYPE.get(patrol_type, 0.8)
    if not await reserves_repo.has_enough(session, country.id, ResourceType.OIL, fuel_cost):
        raise PatrolError(
            f"⛽️ سوخت کافی ندارید. این گشت به {fuel_cost} میلیون بشکه نفت نیاز دارد."
        )

    await reserves_repo.add_amount(session, country.id, ResourceType.OIL, -fuel_cost)

    now = _utcnow()
    patrol = Patrol(
        country_id=country.id,
        patrol_type=patrol_type.value,
        area=area[:120],
        assets_json=json.dumps(assets, ensure_ascii=False),
        total_units=total_units,
        fuel_cost=fuel_cost,
        is_active=True,
        started_at=now,
        ends_at=now + timedelta(hours=PATROL_DURATION_HOURS),
    )
    return await patrol_repo.add_patrol(session, patrol)


async def end_patrol(session: AsyncSession, patrol: Patrol) -> None:
    """پایان دادن به یک گشت (دستی یا خودکار)."""
    patrol.is_active = False
    await session.flush()


async def detection_chance(
    session: AsyncSession, country_id: int, threat: str
) -> float:
    """
    شانس کشف یک تهدید مخفیانه توسط گشت‌های فعال کشور.

    threat: "sabotage" یا "assassination"
    خروجی: درصد (۰ تا ۱۰۰). اگر گشتی فعال نباشد، صفر.
    """
    active = await patrol_repo.list_active(session, country_id)
    if not active:
        return 0.0

    base = (
        PATROL_DETECT_SABOTAGE_PCT
        if threat == "sabotage"
        else PATROL_DETECT_ASSASSINATION_PCT
    )
    # گشت زمینی برای کشف نفوذ زمینی مؤثرتر است؛ تنوع گشت‌ها شانس را بالا می‌برد
    variety = len({p.patrol_type for p in active})
    return min(base * (1.0 + 0.15 * (variety - 1)), 85.0)


async def try_detect(
    session: AsyncSession, country_id: int, threat: str, rng: random.Random | None = None
) -> bool:
    """
    تاس کشف تهدید توسط گشت. در صورت موفقیت، شمارنده‌ی کشف گشت افزایش می‌یابد.
    """
    chance = await detection_chance(session, country_id, threat)
    if chance <= 0:
        return False

    generator = rng or random
    if generator.uniform(0.0, 100.0) > chance:
        return False

    # ثبت کشف روی اولین گشت فعال (برای گزارش به بازیکن)
    active = await patrol_repo.list_active(session, country_id)
    if active:
        active[0].detections += 1
        await session.flush()
    return True


async def intercept_bonus(session: AsyncSession, country_id: int) -> float:
    """بونوس شانس رهگیری محموله بابت گشت دریایی/هوایی فعال."""
    from ..constants import PATROL_INTERCEPT_BONUS_PCT

    types = await patrol_repo.active_types(session, country_id)
    if PatrolType.NAVAL.value in types or PatrolType.AIR.value in types:
        return PATROL_INTERCEPT_BONUS_PCT
    return 0.0


def parse_assets(patrol: Patrol) -> list[dict]:
    """تجهیزات یک گشت را از JSON بازمی‌خواند."""
    try:
        return json.loads(patrol.assets_json or "[]")
    except (ValueError, TypeError):
        return []
