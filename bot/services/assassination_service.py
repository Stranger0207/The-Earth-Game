"""
سرویس ترور (v1.10.6).

دو نوع هدف:
۱. **فرمانده NPC** — بونوس شاخه‌ی تخصصی‌اش تا انتصاب جانشین از بین می‌رود.
۲. **رئیس‌جمهور بازیکن** — شانس موفقیت بسیار کم؛ در صورت موفقیت کشور هدف
   وارد «بحران رهبری» می‌شود و چند ساعت نمی‌تواند عملیات ثبت کند.

گشت فعال کشور هدف می‌تواند عملیات را خنثی کند. شکست عملیات به احتمال زیاد
افشا می‌شود و بحران دیپلماتیک برای مهاجم می‌سازد.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    ASSASSINATION_BASE_SUCCESS_PCT,
    ASSASSINATION_EXPOSURE_ON_FAIL_PCT,
    ASSASSINATION_EXPOSURE_ON_SUCCESS_PCT,
    ASSASSINATION_FAIL_DIPLOMATIC_HIT,
    ASSASSINATION_PRESIDENT_SUCCESS_PCT,
    COMMANDER_REPLACEMENT_HOURS,
    LEADERSHIP_CRISIS_HOURS,
    LEADERSHIP_CRISIS_STABILITY_HIT,
)
from ..database.models import Commander, Country
from ..database.repositories import commanders as cmd_repo
from ..enums import COMMANDER_ROLE_FA, CommanderRole
from . import patrol_service

logger = logging.getLogger(__name__)


class AssassinationError(Exception):
    """خطای قابل‌نمایش به بازیکن."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def list_targets(session: AsyncSession, target_country_id: int) -> list[Commander]:
    """فرماندهان زنده‌ی کشور هدف (اهداف ممکن ترور)."""
    return list(await cmd_repo.list_alive(session, target_country_id))


async def resolve_assassination(
    session: AsyncSession,
    attacker: Country,
    target_country: Country,
    *,
    commander: Commander | None = None,
    target_president: bool = False,
    intel_bonus: float = 0.0,
    seed: int | None = None,
) -> dict:
    """
    اجرای یک عملیات ترور و اعمال نتایجش.

    خروجی dict شامل:
        success, detected, exposed, target_label, effect_note

    - `detected`: گشت کشور هدف عملیات را پیش از اجرا خنثی کرد
    - `exposed`: هویت مهاجم فاش شد (تنش دیپلماتیک)
    """
    rng = random.Random(seed)

    if not target_president and commander is None:
        raise AssassinationError("هدف ترور مشخص نشده است.")

    target_label = (
        f"رئیس‌جمهور {target_country.name_fa}"
        if target_president
        else f"{commander.rank_title} {commander.name}"
    )

    result = {
        "success": False,
        "detected": False,
        "exposed": False,
        "target_label": target_label,
        "effect_note": "",
    }

    # ---------- ۱) گشت کشور هدف ممکن است عملیات را خنثی کند ----------
    detected = await patrol_service.try_detect(
        session, target_country.id, "assassination", rng
    )
    if detected:
        result["detected"] = True
        result["exposed"] = True  # خنثی‌سازی یعنی عوامل دستگیر شده‌اند
        _apply_failure_cost(attacker)
        result["effect_note"] = (
            "🛡 گشت امنیتی کشور هدف عوامل نفوذی را پیش از اجرای عملیات شناسایی و بازداشت کرد."
        )
        await session.flush()
        return result

    # ---------- ۲) تاس موفقیت ----------
    base = (
        ASSASSINATION_PRESIDENT_SUCCESS_PCT
        if target_president
        else ASSASSINATION_BASE_SUCCESS_PCT
    )
    # بونوس اطلاعاتی مهاجم (فرمانده اطلاعات + ماهواره)
    chance = min(90.0, base + intel_bonus)
    success = rng.uniform(0.0, 100.0) <= chance
    result["success"] = success

    # ---------- ۳) افشا ----------
    exposure_chance = (
        ASSASSINATION_EXPOSURE_ON_SUCCESS_PCT if success else ASSASSINATION_EXPOSURE_ON_FAIL_PCT
    )
    result["exposed"] = rng.uniform(0.0, 100.0) <= exposure_chance

    # ---------- ۴) اعمال نتیجه ----------
    if success:
        if target_president:
            crisis_until = _utcnow() + timedelta(hours=LEADERSHIP_CRISIS_HOURS)
            target_country.leadership_crisis_until = crisis_until
            target_country.stability = max(
                0.0, (target_country.stability or 0.0) + LEADERSHIP_CRISIS_STABILITY_HIT
            )
            target_country.public_satisfaction = max(
                0.0, (target_country.public_satisfaction or 0.0) - 10.0
            )
            result["effect_note"] = (
                f"🚨 کشور هدف تا {LEADERSHIP_CRISIS_HOURS} ساعت در «بحران رهبری» است و "
                "نمی‌تواند عملیات نظامی ثبت کند."
            )
        else:
            replacement_at = _utcnow() + timedelta(hours=COMMANDER_REPLACEMENT_HOURS)
            await cmd_repo.kill_commander(session, commander, replacement_at)
            try:
                role_fa = COMMANDER_ROLE_FA[CommanderRole(commander.role)]
            except (ValueError, KeyError):
                role_fa = commander.role
            target_country.stability = max(0.0, (target_country.stability or 0.0) - 3.0)
            result["effect_note"] = (
                f"🎖 بونوس «{role_fa}» کشور هدف تا {COMMANDER_REPLACEMENT_HOURS} ساعت "
                "(انتصاب جانشین) از بین رفت."
            )
    else:
        _apply_failure_cost(attacker)
        result["effect_note"] = "❌ عملیات به نتیجه نرسید."

    # افشا هزینه‌ی دیپلماتیک اضافه دارد
    if result["exposed"]:
        attacker.public_satisfaction = max(
            0.0, (attacker.public_satisfaction or 0.0) + ASSASSINATION_FAIL_DIPLOMATIC_HIT
        )

    await session.flush()
    return result


def _apply_failure_cost(attacker: Country) -> None:
    """هزینه‌ی داخلی شکست عملیات برای مهاجم."""
    attacker.public_satisfaction = max(
        0.0, (attacker.public_satisfaction or 0.0) + ASSASSINATION_FAIL_DIPLOMATIC_HIT
    )
    attacker.stability = max(0.0, (attacker.stability or 0.0) - 1.5)


async def restore_due_commanders(session: AsyncSession) -> list[tuple[int, str]]:
    """
    فرماندهانی که زمان انتصاب جانشین‌شان رسیده را دوباره فعال می‌کند.

    خروجی: [(country_id, نام فرمانده جدید)] برای اطلاع به بازیکنان.
    """
    restored: list[tuple[int, str]] = []
    for commander in await cmd_repo.list_due_replacements(session):
        commander.is_alive = True
        commander.killed_at = None
        commander.replacement_at = None
        restored.append((commander.country_id, f"{commander.rank_title} {commander.name}"))
    if restored:
        await session.flush()
    return restored


async def intel_bonus_for(session: AsyncSession, country_id: int) -> float:
    """
    بونوس اطلاعاتی مهاجم برای عملیات مخفیانه:
    فرمانده‌ی اطلاعات + ماهواره‌ی فعال.
    """
    bonus = await cmd_repo.bonus_for_role(session, country_id, CommanderRole.INTELLIGENCE)

    try:
        from ..database.repositories import satellites as sat_repo

        if await sat_repo.list_active_orbit_satellites(session, country_id):
            bonus += 10.0
    except Exception as exc:  # noqa: BLE001 — نبود ماهواره نباید عملیات را بشکند
        logger.debug("satellite intel bonus unavailable: %s", exc)

    return bonus
