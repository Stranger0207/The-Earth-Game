"""
سرویس جاسوسی (v1.10.7) — پیش‌نیاز عملیات ترور.

منطق بازی: نمی‌توانی کورکورانه فرمانده دشمن را ترور کنی. اول باید عملیات
جاسوسی اجرا کنی تا محل و برنامه‌ی روزانه‌ی او را پیدا کنی. کیفیت اطلاعاتی
که به دست می‌آوری مستقیماً روی شانس موفقیت ترور اثر می‌گذارد.

اطلاعات بعد از ۴۸ ساعت منقضی می‌شود (هدف جابه‌جا می‌شود) و پس از استفاده
در ترور مصرف می‌گردد.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    ESPIONAGE_BASE_SUCCESS_PCT,
    ESPIONAGE_COMMANDER_QUALITY_FACTOR,
    ESPIONAGE_COOLDOWN_HOURS,
    ESPIONAGE_COST_USD,
    ESPIONAGE_DETECTION_BASE_PCT,
    ESPIONAGE_INTEL_VALID_HOURS,
    ESPIONAGE_QUALITY_MAX,
    ESPIONAGE_QUALITY_MIN,
    ESPIONAGE_SATELLITE_QUALITY_BONUS,
)
from ..database.models import Commander, CommanderIntel, Country
from ..database.repositories import commander_intel as intel_repo
from ..database.repositories import commanders as cmd_repo
from ..enums import CommanderRole
from . import patrol_service

logger = logging.getLogger(__name__)


class EspionageError(Exception):
    """خطای قابل‌نمایش به بازیکن هنگام عملیات جاسوسی."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------- بانک متن برای واقع‌گرایی گزارش اطلاعاتی ----------
_LOCATIONS: dict[str, list[str]] = {
    CommanderRole.GROUND.value: [
        "قرارگاه فرماندهی نیروی زمینی در حاشیه‌ی پایتخت",
        "پادگان مرکزی آموزش زرهی",
        "مقر عملیاتی منطقه‌ی مرزی",
        "ستاد لشکر مکانیزه در شهر صنعتی",
    ],
    CommanderRole.AIR.value: [
        "پایگاه هوایی اصلی — بخش فرماندهی عملیات",
        "مرکز کنترل پرواز پایگاه شمالی",
        "قرارگاه پدافند هوایی مرکزی",
        "آشیانه‌ی فرماندهی اسکادران یکم",
    ],
    CommanderRole.NAVAL.value: [
        "مقر فرماندهی ناوگان در بندر جنوبی",
        "پایگاه دریایی اصلی — عرشه‌ی ناو پرچم‌دار",
        "ستاد عملیات دریایی در بندر تجاری",
        "مرکز فرماندهی زیردریایی‌ها",
    ],
    CommanderRole.INTELLIGENCE.value: [
        "ساختمان بی‌نشان در منطقه‌ی اداری پایتخت",
        "مقر سازمان اطلاعات — طبقه‌ی محافظت‌شده",
        "خانه‌ی امن در حاشیه‌ی شهر",
        "مرکز شنود در ارتفاعات اطراف پایتخت",
    ],
    CommanderRole.NUCLEAR.value: [
        "مجتمع تحقیقاتی محافظت‌شده",
        "آزمایشگاه فیزیک هسته‌ای دانشگاه ملی",
        "تأسیسات زیرزمینی در منطقه‌ی کوهستانی",
        "شهرک علمی با حفاظت نظامی",
    ],
}

_ROUTINES: list[str] = [
    "هر روز صبح با کاروان سه‌خودرویی و مسیر ثابت تردد می‌کند",
    "جلسات هفتگی با فرماندهان ارشد در روزهای مشخص برگزار می‌کند",
    "شب‌ها در اقامتگاه سازمانی با حفاظت سبک حضور دارد",
    "هفته‌ای دو بار به بازدید میدانی می‌رود؛ مسیر قابل پیش‌بینی است",
    "از خودروی شخصی بدون اسکورت برای ترددهای کوتاه استفاده می‌کند",
    "برنامه‌ی سفر او دو روز قبل به رده‌های پایین اطلاع داده می‌شود",
]


def _quality_label(quality: float) -> str:
    """برچسب فارسی کیفیت اطلاعات."""
    if quality >= 75:
        return "🟢 عالی"
    if quality >= 55:
        return "🟡 خوب"
    if quality >= 35:
        return "🟠 ناقص"
    return "🔴 بسیار ضعیف"


async def _intel_bonus(session: AsyncSession, country_id: int) -> float:
    """بونوس اطلاعاتی کشور: فرمانده‌ی اطلاعات + ماهواره‌ی فعال."""
    bonus = 0.0

    commander_bonus = await cmd_repo.bonus_for_role(
        session, country_id, CommanderRole.INTELLIGENCE
    )
    bonus += commander_bonus * ESPIONAGE_COMMANDER_QUALITY_FACTOR

    try:
        from ..database.repositories import satellites as sat_repo

        if await sat_repo.list_active_orbit_satellites(session, country_id):
            bonus += ESPIONAGE_SATELLITE_QUALITY_BONUS
    except Exception as exc:  # noqa: BLE001 — نبود ماهواره نباید عملیات را بشکند
        logger.debug("satellite bonus unavailable: %s", exc)

    return bonus


async def assert_can_spy(session: AsyncSession, country: Country) -> None:
    """بررسی مجوز اجرای عملیات جاسوسی (کول‌داون و بودجه)."""
    recent = await intel_repo.count_recent_operations(
        session, country.id, ESPIONAGE_COOLDOWN_HOURS
    )
    if recent > 0:
        raise EspionageError(
            f"⏳ سرویس اطلاعاتی شما در حال بازسازی شبکه است. "
            f"هر {ESPIONAGE_COOLDOWN_HOURS} ساعت یک عملیات جاسوسی ممکن است."
        )

    if (country.budget or 0.0) < ESPIONAGE_COST_USD:
        raise EspionageError(
            f"💰 بودجه‌ی کافی ندارید. هزینه‌ی عملیات جاسوسی "
            f"{ESPIONAGE_COST_USD / 1e9:,.1f} میلیارد دلار است."
        )


async def run_espionage(
    session: AsyncSession,
    spy: Country,
    target_country: Country,
    commander: Commander,
    *,
    seed: int | None = None,
) -> dict:
    """
    اجرای یک عملیات جاسوسی روی یک فرمانده‌ی خارجی.

    خروجی dict:
        success, detected, quality, quality_label, location, routine, expires_at

    این تابع بودجه را کسر می‌کند (موفق یا ناموفق — هزینه پرداخت شده است).
    """
    rng = random.Random(seed)

    if commander.country_id != target_country.id:
        raise EspionageError("این فرمانده متعلق به کشور هدف نیست.")
    if not commander.is_alive:
        raise EspionageError("این فرمانده پیش‌تر ترور شده است.")

    # هزینه در هر حالت پرداخت می‌شود
    spy.budget = max(0.0, (spy.budget or 0.0) - ESPIONAGE_COST_USD)

    bonus = await _intel_bonus(session, spy.id)

    result = {
        "success": False,
        "detected": False,
        "quality": 0.0,
        "quality_label": "",
        "location": "",
        "routine": "",
        "expires_at": None,
        "commander_name": f"{commander.rank_title} {commander.name}",
    }

    # ---------- گشت کشور هدف می‌تواند شبکه‌ی جاسوسی را کشف کند ----------
    caught = await patrol_service.try_detect(session, target_country.id, "sabotage", rng)
    if caught:
        result["detected"] = True
        spy.public_satisfaction = max(0.0, (spy.public_satisfaction or 0.0) - 2.0)
        await session.flush()
        return result

    # ---------- تاس موفقیت ----------
    chance = min(92.0, ESPIONAGE_BASE_SUCCESS_PCT + bonus * 0.5)
    if rng.uniform(0.0, 100.0) > chance:
        # ناموفق — ممکن است لو هم برود
        result["detected"] = rng.uniform(0.0, 100.0) <= ESPIONAGE_DETECTION_BASE_PCT
        if result["detected"]:
            spy.public_satisfaction = max(0.0, (spy.public_satisfaction or 0.0) - 1.5)
        await session.flush()
        return result

    # ---------- موفقیت: تولید اطلاعات ----------
    quality = rng.uniform(ESPIONAGE_QUALITY_MIN, ESPIONAGE_QUALITY_MAX) + bonus
    quality = max(0.0, min(100.0, quality))

    locations = _LOCATIONS.get(commander.role) or _LOCATIONS[CommanderRole.GROUND.value]
    location = rng.choice(locations)
    routine = rng.choice(_ROUTINES)
    expires_at = _utcnow() + timedelta(hours=ESPIONAGE_INTEL_VALID_HOURS)

    # اطلاعات قبلی روی همین فرمانده جای خود را به اطلاعات تازه می‌دهد
    existing = await intel_repo.get_valid_intel(session, spy.id, commander.id)
    if existing is not None:
        await session.delete(existing)
        await session.flush()

    await intel_repo.add_intel(
        session,
        CommanderIntel(
            spy_country_id=spy.id,
            commander_id=commander.id,
            target_country_id=target_country.id,
            quality=quality,
            known_location=location,
            routine_note=routine,
            was_detected=False,
            expires_at=expires_at,
        ),
    )

    # حتی در موفقیت، شانس کمی لو رفتن هست
    result["detected"] = rng.uniform(0.0, 100.0) <= ESPIONAGE_DETECTION_BASE_PCT * 0.4

    result.update({
        "success": True,
        "quality": quality,
        "quality_label": _quality_label(quality),
        "location": location,
        "routine": routine,
        "expires_at": expires_at,
    })
    await session.flush()
    return result


async def targets_with_intel_status(
    session: AsyncSession, spy_country_id: int, target_country_id: int
) -> list[dict]:
    """
    فرماندهان زنده‌ی کشور هدف همراه با وضعیت اطلاعاتی ما روی هرکدام.

    خروجی: [{"commander", "intel", "has_intel", "quality"}]
    برای ساخت کیبورد انتخاب هدف ترور استفاده می‌شود.
    """
    commanders = await cmd_repo.list_alive(session, target_country_id)
    intel_rows = await intel_repo.list_valid_for_target(
        session, spy_country_id, target_country_id
    )
    intel_map = {row.commander_id: row for row in intel_rows}

    out: list[dict] = []
    for commander in commanders:
        intel = intel_map.get(commander.id)
        out.append({
            "commander": commander,
            "intel": intel,
            "has_intel": intel is not None,
            "quality": intel.quality if intel else 0.0,
            "quality_label": _quality_label(intel.quality) if intel else "❔ بدون اطلاعات",
        })
    return out


def quality_label(quality: float) -> str:
    """برچسب عمومی کیفیت (برای استفاده در هندلرها)."""
    return _quality_label(quality)
