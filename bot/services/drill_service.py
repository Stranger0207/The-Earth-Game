"""
سرویس رزمایش نظامی (v1.10.6).

رزمایش «آمادگی رزمی» (readiness) کشور را بالا می‌برد که مستقیماً در موتور
نبرد به افزایش قدرت تبدیل می‌شود. آمادگی روزانه افت می‌کند، پس بازیکن باید
مرتب رزمایش برگزار کند — این همان «سر گرم شدن پلیرها» است.

رزمایش مشترک برای هر دو کشور بونوس دارد و پیام سیاسی هم می‌فرستد.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    DRILL_BUDGET_COST,
    DRILL_COOLDOWN_HOURS,
    DRILL_DURATION_HOURS,
    DRILL_FUEL_COST,
    DRILL_READINESS_DECAY_PER_DAY,
    DRILL_READINESS_GAIN_JOINT,
    DRILL_READINESS_GAIN_SOLO,
    DRILL_READINESS_MAX,
    DRILL_SATISFACTION_GAIN,
)
from ..database.models import Country, Drill
from ..database.repositories import drills as drill_repo
from ..database.repositories import military as mil_repo
from ..database.repositories import reserves as reserves_repo
from ..enums import DrillType, ResourceType

logger = logging.getLogger(__name__)


class DrillError(Exception):
    """خطای قابل‌نمایش به بازیکن هنگام برگزاری رزمایش."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def available_assets(session: AsyncSession, country_id: int) -> list[dict]:
    """همه‌ی تجهیزات کشور — رزمایش با هر شاخه‌ای ممکن است."""
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
        if a.count > 0
    ]


async def start_drill(
    session: AsyncSession,
    country: Country,
    drill_type: DrillType,
    title: str,
    area: str,
    assets: list[dict],
    *,
    partner: Country | None = None,
) -> Drill:
    """
    ثبت یک رزمایش جدید.

    رزمایش مشترک تا پذیرش شریک اجرا نمی‌شود ولی هزینه‌اش همان ابتدا کسر می‌شود
    (مثل بقیه‌ی درخواست‌های بازی).
    """
    recent = await drill_repo.count_since(session, country.id, DRILL_COOLDOWN_HOURS)
    if recent > 0:
        raise DrillError(
            f"⏳ در هر {DRILL_COOLDOWN_HOURS} ساعت فقط یک رزمایش می‌توانید برگزار کنید."
        )

    if drill_type is DrillType.JOINT and partner is None:
        raise DrillError("برای رزمایش مشترک باید کشور شریک را انتخاب کنید.")
    if partner is not None and partner.id == country.id:
        raise DrillError("کشور شریک نمی‌تواند خودتان باشد.")

    total_units = sum(int(a.get("count", 0)) for a in assets)
    if total_units <= 0:
        raise DrillError("هیچ تجهیزاتی برای رزمایش انتخاب نشده است.")

    if not await reserves_repo.has_enough(session, country.id, ResourceType.OIL, DRILL_FUEL_COST):
        raise DrillError(
            f"⛽️ سوخت کافی ندارید. رزمایش به {DRILL_FUEL_COST} میلیون بشکه نفت نیاز دارد."
        )
    if (country.budget or 0.0) < DRILL_BUDGET_COST:
        raise DrillError(
            f"💰 بودجه‌ی کافی ندارید. هزینه‌ی رزمایش {DRILL_BUDGET_COST / 1e9:,.1f} میلیارد دلار است."
        )

    await reserves_repo.add_amount(session, country.id, ResourceType.OIL, -DRILL_FUEL_COST)
    country.budget = max(0.0, (country.budget or 0.0) - DRILL_BUDGET_COST)

    now = _utcnow()
    drill = Drill(
        country_id=country.id,
        partner_country_id=partner.id if partner else None,
        drill_type=drill_type.value,
        title=title[:120],
        area=area[:120],
        assets_json=json.dumps(assets, ensure_ascii=False),
        fuel_cost=DRILL_FUEL_COST,
        budget_cost=DRILL_BUDGET_COST,
        readiness_gain=(
            DRILL_READINESS_GAIN_JOINT if drill_type is DrillType.JOINT else DRILL_READINESS_GAIN_SOLO
        ),
        partner_accepted=drill_type is DrillType.SOLO,
        is_completed=False,
        started_at=now,
        ends_at=now + timedelta(hours=DRILL_DURATION_HOURS),
    )
    return await drill_repo.add_drill(session, drill)


async def accept_joint_drill(session: AsyncSession, drill: Drill) -> None:
    """پذیرش دعوت رزمایش مشترک توسط کشور شریک."""
    if drill.partner_accepted:
        raise DrillError("این رزمایش قبلاً پذیرفته شده است.")
    drill.partner_accepted = True
    # شمارش مدت از لحظه‌ی پذیرش
    drill.started_at = _utcnow()
    drill.ends_at = _utcnow() + timedelta(hours=DRILL_DURATION_HOURS)
    await session.flush()


async def reject_joint_drill(session: AsyncSession, drill: Drill) -> None:
    """رد دعوت رزمایش مشترک (رزمایش لغو می‌شود)."""
    drill.is_completed = True
    drill.readiness_gain = 0.0
    await session.flush()


def apply_readiness(country: Country, gain: float) -> float:
    """
    افزایش آمادگی رزمی یک کشور با رعایت سقف.
    خروجی: مقدار واقعی افزوده‌شده (ممکن است به‌خاطر سقف کمتر باشد).
    """
    current = float(getattr(country, "readiness", 0.0) or 0.0)
    new_value = min(DRILL_READINESS_MAX, current + gain)
    country.readiness = new_value
    return new_value - current


async def complete_drill(session: AsyncSession, drill: Drill) -> dict:
    """
    پایان رزمایش و اعمال اثرات آن.

    خروجی: {"country_gain": float, "partner_gain": float} برای گزارش به بازیکنان.
    """
    from ..database.repositories import countries as countries_repo

    result = {"country_gain": 0.0, "partner_gain": 0.0}

    country = await countries_repo.get_country(session, drill.country_id)
    if country is not None:
        result["country_gain"] = apply_readiness(country, drill.readiness_gain)
        country.public_satisfaction = min(
            100.0, (country.public_satisfaction or 0.0) + DRILL_SATISFACTION_GAIN
        )

    if drill.partner_country_id and drill.partner_accepted:
        partner = await countries_repo.get_country(session, drill.partner_country_id)
        if partner is not None:
            result["partner_gain"] = apply_readiness(partner, drill.readiness_gain)
            partner.public_satisfaction = min(
                100.0, (partner.public_satisfaction or 0.0) + DRILL_SATISFACTION_GAIN
            )

    drill.is_completed = True
    await session.flush()
    return result


def decay_readiness(country: Country, now: datetime | None = None) -> float:
    """
    افت طبیعی آمادگی رزمی با گذشت زمان.
    خروجی: مقدار افت‌کرده (برای گزارش).
    """
    moment = now or _utcnow()
    current = float(getattr(country, "readiness", 0.0) or 0.0)
    if current <= 0:
        country.last_readiness_decay_at = moment
        return 0.0

    last = _aware(getattr(country, "last_readiness_decay_at", None))
    if last is None:
        country.last_readiness_decay_at = moment
        return 0.0

    days = (moment - last).total_seconds() / 86400.0
    if days < 1.0:
        return 0.0

    drop = min(current, DRILL_READINESS_DECAY_PER_DAY * days)
    country.readiness = max(0.0, current - drop)
    country.last_readiness_decay_at = moment
    return drop


def parse_assets(drill: Drill) -> list[dict]:
    """تجهیزات یک رزمایش را از JSON بازمی‌خواند."""
    try:
        return json.loads(drill.assets_json or "[]")
    except (ValueError, TypeError):
        return []
