"""
منطق سیستم حاکمیت: تغییر نظام، مالیات، اعتراضات (v1.10.2).
مستقل از تلگرام — قابل‌تست با SQLite.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    GOVERNMENT_BONUSES,
    GOVT_MAX_CHANGES,
    PARLIAMENT_REFERRAL_SATISFACTION_GAIN,
    PARLIAMENT_REFERRAL_STABILITY_GAIN,
    PROTEST_ACTIVE_SATISFACTION_DROP,
    PROTEST_ACTIVE_STABILITY_DROP,
    PROTEST_CHANCE_PER_TICK,
    PROTEST_SATISFACTION_THRESHOLD,
    PROTEST_TAX_THRESHOLD,
    SUPPRESS_SATISFACTION_DROP,
    SUPPRESS_STABILITY_GAIN,
    TAX_MAX_RATE,
    TAX_MIN_RATE,
    TAX_REVENUE_PER_CAPITA,
    TAX_SATISFACTION_THRESHOLDS,
)
from ..database.models import Country
from ..database.repositories import governance as gov_repo
from ..enums import GovernmentType, ProtestType


class GovernanceError(Exception):
    """خطای منطقی حاکمیت."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


# ============================================================
#  تغییر نظام حاکمیتی
# ============================================================

async def change_government(
    session: AsyncSession,
    country: Country,
    new_type: GovernmentType,
) -> dict[str, float]:
    """
    نظام حاکمیتی کشور را تغییر می‌دهد و بونوس‌های مربوطه را اعمال می‌کند.
    خروجی: دیکشنری بونوس‌های اعمال‌شده.
    """
    if country.govt_changes_left <= 0:
        raise GovernanceError("شما قبلاً هر دو بار حق تغییر نظام خود را استفاده کرده‌اید.")

    old_type = country.government_type
    # اگر نظام قبلی داشت، بونوس قبلی را ریورس کن
    if old_type:
        try:
            old_bonuses = GOVERNMENT_BONUSES.get(GovernmentType(old_type), {})
            _apply_bonuses(country, old_bonuses, reverse=True)
        except ValueError:
            pass  # نوع قبلی نامعتبر — نادیده بگیر

    # نظام جدید
    country.government_type = new_type.value
    country.govt_changes_left -= 1

    # اعمال بونوس جدید
    bonuses = GOVERNMENT_BONUSES.get(new_type, {})
    _apply_bonuses(country, bonuses, reverse=False)

    await session.flush()
    return bonuses


def _apply_bonuses(country: Country, bonuses: dict[str, float], *, reverse: bool) -> None:
    """بونوس‌های نظام را روی شاخص‌های کشور اعمال یا ریورس می‌کند."""
    factor = -1 if reverse else 1
    for key, val in bonuses.items():
        delta = val * factor
        if key == "satisfaction":
            country.public_satisfaction = _clamp(country.public_satisfaction + delta)
        elif key == "stability":
            country.stability = _clamp(country.stability + delta)
        elif key == "unemployment":
            country.unemployment = _clamp(country.unemployment + delta)
        elif key == "inflation":
            country.inflation = _clamp(country.inflation + delta, lo=-100.0)
        elif key == "economic_power":
            country.economic_power = _clamp(country.economic_power + delta)


# ============================================================
#  مالیات
# ============================================================

async def set_tax_rate(
    session: AsyncSession, country: Country, rate: float
) -> float:
    """نرخ مالیات را تنظیم می‌کند. مقدار clamped برمی‌گردد."""
    rate = _clamp(rate, TAX_MIN_RATE, TAX_MAX_RATE)
    country.tax_rate = rate
    await session.flush()
    return rate


def compute_tax_revenue(country: Country) -> float:
    """درآمد مالیاتی ۲۴ ساعته را محاسبه می‌کند."""
    return (country.tax_rate / 100.0) * country.population * TAX_REVENUE_PER_CAPITA


def tax_satisfaction_delta(tax_rate: float) -> float:
    """تغییر رضایت ناشی از مالیات (هر ۲۴ ساعت)."""
    for threshold, delta in TAX_SATISFACTION_THRESHOLDS:
        if tax_rate <= threshold:
            return delta
    # بالاتر از آخرین آستانه
    return TAX_SATISFACTION_THRESHOLDS[-1][1]


# ============================================================
#  سرکوب / ارجاع اعتراض
# ============================================================

async def suppress_protest(
    session: AsyncSession, country: Country, protest_id: int
) -> None:
    """سرکوب اعتراض: ثبات بالا می‌رود ولی رضایت کم می‌شود."""
    p = await gov_repo.update_protest_status(session, protest_id, "suppressed", "سرکوب شد")
    if p is None:
        raise GovernanceError("اعتراض یافت نشد.")
    country.stability = _clamp(country.stability + SUPPRESS_STABILITY_GAIN)
    country.public_satisfaction = _clamp(country.public_satisfaction - SUPPRESS_SATISFACTION_DROP)
    await session.flush()


async def refer_to_parliament(
    session: AsyncSession, country: Country, protest_id: int
) -> None:
    """ارجاع اعتراض به مجلس: رضایت و ثبات کمی بالا می‌رود."""
    p = await gov_repo.update_protest_status(session, protest_id, "in_parliament", "ارجاع به مجلس")
    if p is None:
        raise GovernanceError("اعتراض یافت نشد.")
    country.stability = _clamp(country.stability + PARLIAMENT_REFERRAL_STABILITY_GAIN)
    country.public_satisfaction = _clamp(
        country.public_satisfaction + PARLIAMENT_REFERRAL_SATISFACTION_GAIN
    )
    await session.flush()


# ============================================================
#  تولید اعتراض تصادفی (برای scheduler)
# ============================================================

# عناوین تصادفی اعتراضات بر اساس نوع
_PROTEST_TITLES: dict[ProtestType, list[str]] = {
    ProtestType.ECONOMIC: [
        "اعتراضات مردمی به وضعیت اقتصادی",
        "تجمع بازاریان در اعتراض به مالیات",
        "اعتراض صنف‌های تجاری به سیاست‌های مالی",
        "تظاهرات مردم علیه تورم و گرانی",
    ],
    ProtestType.POLITICAL: [
        "تظاهرات سیاسی علیه حاکمیت",
        "اعتراض نخبگان به سیاست‌های داخلی",
        "حرکت اعتراضی دانشجویان",
        "تجمع آزادی‌خواهان در مرکز شهر",
    ],
    ProtestType.SOCIAL: [
        "اعتراض اجتماعی به نابرابری",
        "تظاهرات حقوق شهروندی",
        "تجمع فعالان مدنی",
        "اعتراض گسترده‌ی شهروندان به شرایط زندگی",
    ],
    ProtestType.LABOR: [
        "اعتصاب کارگران صنعتی",
        "اعتراض معدنکاران به شرایط کاری",
        "اعتصاب سراسری کارگران حمل‌ونقل",
        "تجمع کارگران ساختمانی",
    ],
}


def maybe_generate_protest(country: Country) -> tuple[ProtestType, str, str, float] | None:
    """
    بر اساس شرایط کشور، شاید یک اعتراض تصادفی تولید کند.
    خروجی: (نوع، عنوان، توضیح، شدت) یا None.
    """
    if not country.is_claimed:
        return None  # کشور بدون بازیکن

    reasons: list[tuple[ProtestType, str]] = []

    # رضایت پایین
    if country.public_satisfaction < PROTEST_SATISFACTION_THRESHOLD:
        reasons.append((ProtestType.POLITICAL, "نارضایتی عمومی گسترده"))
        reasons.append((ProtestType.SOCIAL, "شرایط نامساعد اجتماعی"))

    # مالیات بالا
    tax = getattr(country, "tax_rate", 10.0)
    if tax > PROTEST_TAX_THRESHOLD:
        reasons.append((ProtestType.ECONOMIC, f"مالیات بالای {int(tax)}٪"))
        reasons.append((ProtestType.LABOR, "فشار مالیاتی بر کارگران"))

    # بیکاری بالا
    if country.unemployment > 20:
        reasons.append((ProtestType.LABOR, f"بیکاری {int(country.unemployment)}٪"))

    # ثبات پایین
    if country.stability < 25:
        reasons.append((ProtestType.POLITICAL, "بی‌ثباتی سیاسی شدید"))

    if not reasons:
        return None

    # احتمال تولید
    if random.random() > PROTEST_CHANCE_PER_TICK:
        return None

    ptype, reason = random.choice(reasons)
    title = random.choice(_PROTEST_TITLES[ptype])
    severity = round(random.uniform(3.0, 9.0), 1)
    desc = f"علت: {reason}"
    return ptype, title, desc, severity


def apply_active_protest_effects(country: Country, active_count: int) -> None:
    """اثر اعتراضات فعال بر ثبات و رضایت (هر تیک ۲۴ ساعته)."""
    if active_count <= 0:
        return
    country.stability = _clamp(
        country.stability - (PROTEST_ACTIVE_STABILITY_DROP * active_count)
    )
    country.public_satisfaction = _clamp(
        country.public_satisfaction - (PROTEST_ACTIVE_SATISFACTION_DROP * active_count)
    )
