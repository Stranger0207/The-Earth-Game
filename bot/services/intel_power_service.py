"""
سرویس قدرت اطلاعاتی (v2.1) — پایه‌ی نامتقارن‌سازی جاسوسی و ترور.

**مسئله‌ی قبلی:** شانس جاسوسی برای همه‌ی ۳۹ کشور ۵۵٪ ثابت بود؛ افغانستان دقیقاً
مثل آمریکا جاسوسی می‌کرد و ترور فرمانده ارزان تمام می‌شد.

**قاعده‌ی جدید:** هر کشور یک «قدرت اطلاعاتی» (۰ تا ۱۰۰) در `INTEL_POWER` دارد.
همه‌چیز از **اختلاف** قدرت اطلاعاتی دو طرف (`gap`) محاسبه می‌شود:

- اختلاف مثبت (جاسوس قوی‌تر) → شانس و کیفیت بالاتر
- اختلاف منفی (جاسوس ضعیف‌تر) → شانس و کیفیت پایین‌تر
- اختلاف بدتر از `INTEL_BLOCK_GAP` → عملیات **اصلاً ممکن نیست**

این ماژول مستقل از تلگرام و دیتابیس است (فقط رشته‌ی `name_en` می‌گیرد) تا
کامل قابل‌تست باشد.
"""

from __future__ import annotations

from ..constants import (
    ESPIONAGE_BASE_SUCCESS_PCT,
    ESPIONAGE_QUALITY_MAX,
    ESPIONAGE_QUALITY_MIN,
    INTEL_ASSASSINATION_FACTOR_MAX,
    INTEL_ASSASSINATION_FACTOR_MIN,
    INTEL_ASSASSINATION_GAP_DIVISOR,
    INTEL_BLOCK_GAP,
    INTEL_ESPIONAGE_CHANCE_MAX,
    INTEL_ESPIONAGE_CHANCE_MIN,
    INTEL_ESPIONAGE_GAP_FACTOR,
    INTEL_POWER,
    INTEL_POWER_DEFAULT,
    INTEL_PRESIDENT_GAP_FACTOR,
    INTEL_QUALITY_GAP_FACTOR,
    INTEL_TIERS,
)


def _clamp(value: float, low: float, high: float) -> float:
    """مقدار را داخل بازه‌ی [low, high] نگه می‌دارد."""
    return max(low, min(high, value))


def intel_power(name_en: str | None) -> float:
    """قدرت اطلاعاتی یک کشور (۰ تا ۱۰۰)؛ کشور ناشناس مقدار پیش‌فرض می‌گیرد."""
    if not name_en:
        return INTEL_POWER_DEFAULT
    return INTEL_POWER.get(name_en, INTEL_POWER_DEFAULT)


def tier_label(name_en: str | None) -> str:
    """برچسب فارسی رده‌ی اطلاعاتی (⭐ نخبه / 🔵 قوی / 🟡 متوسط / 🔴 ضعیف)."""
    power = intel_power(name_en)
    for threshold, label in INTEL_TIERS:
        if power >= threshold:
            return label
    return INTEL_TIERS[-1][1]


def tier_text(name_en: str | None) -> str:
    """رده + عدد، برای نمایش در پنل‌ها: «⭐ نخبه (۹۸)»."""
    from ..utils.numbers import fa_number

    return f"{tier_label(name_en)} ({fa_number(intel_power(name_en))})"


def gap(spy_name_en: str | None, target_name_en: str | None) -> float:
    """
    اختلاف قدرت اطلاعاتی جاسوس و هدف.

    مثبت = جاسوس برتر است. مثال: آمریکا (۹۸) علیه یمن (۲۲) → +۷۶.
    """
    return intel_power(spy_name_en) - intel_power(target_name_en)


def is_blocked(spy_name_en: str | None, target_name_en: str | None) -> bool:
    """آیا اختلاف قدرت آن‌قدر زیاد است که عملیات ممکن نباشد؟"""
    return gap(spy_name_en, target_name_en) <= INTEL_BLOCK_GAP


def espionage_chance(spy_name_en: str | None, target_name_en: str | None) -> float:
    """
    شانس پایه‌ی موفقیت عملیات جاسوسی (درصد، پیش از بونوس فرمانده/ماهواره).

    نمونه‌ها: آمریکا→یمن ≈ ۶۹٪ | اسرائیل→سوریه ≈ ۶۵٪ | ایران→اسرائیل ≈ ۲۶٪
    """
    raw = ESPIONAGE_BASE_SUCCESS_PCT + gap(spy_name_en, target_name_en) * INTEL_ESPIONAGE_GAP_FACTOR
    return _clamp(raw, INTEL_ESPIONAGE_CHANCE_MIN, INTEL_ESPIONAGE_CHANCE_MAX)


def quality_range(
    spy_name_en: str | None, target_name_en: str | None
) -> tuple[float, float]:
    """
    بازه‌ی کیفیت اطلاعاتِ به‌دست‌آمده در صورت موفقیت.

    نفوذ به کشور قوی‌تر حتی در موفقیت هم اطلاعات ناقص‌تری می‌دهد (هدف
    ضدجاسوسی بهتری دارد و لایه‌های حفاظتی بیشتری در کار است).
    """
    shift = gap(spy_name_en, target_name_en) * INTEL_QUALITY_GAP_FACTOR
    low = _clamp(ESPIONAGE_QUALITY_MIN + shift, 5.0, 95.0)
    high = _clamp(ESPIONAGE_QUALITY_MAX + shift, low + 5.0, 100.0)
    return low, high


def block_reason(
    spy_name_en: str | None,
    target_name_en: str | None,
    *,
    spy_fa: str = "کشور شما",
    target_fa: str = "کشور هدف",
) -> str:
    """پیام فارسی توضیح اینکه چرا این عملیات ممکن نیست."""
    return (
        f"⛔️ سرویس اطلاعاتی شما توان نفوذ به <b>{target_fa}</b> را ندارد.\n\n"
        f"🕵️ رده‌ی اطلاعاتی {spy_fa}: {tier_text(spy_name_en)}\n"
        f"🎯 رده‌ی اطلاعاتی هدف: {tier_text(target_name_en)}\n\n"
        "<i>اختلاف توان اطلاعاتی بیش از حد است؛ عوامل شما پیش از رسیدن به هدف "
        "شناسایی می‌شوند. با پرتاب ماهواره‌ی جاسوسی و داشتن فرمانده‌ی اطلاعات "
        "می‌توانید توان عملیاتی خود را تقویت کنید.</i>"
    )


def can_spy_on(
    spy_name_en: str | None,
    target_name_en: str | None,
    *,
    spy_fa: str = "کشور شما",
    target_fa: str = "کشور هدف",
) -> tuple[bool, str]:
    """
    آیا این کشور می‌تواند روی هدف عملیات اطلاعاتی/ترور اجرا کند؟

    خروجی: (مجاز؟، دلیل فارسی در صورت رد)
    """
    if is_blocked(spy_name_en, target_name_en):
        return False, block_reason(
            spy_name_en, target_name_en, spy_fa=spy_fa, target_fa=target_fa
        )
    return True, ""


def assassination_tier_factor(
    spy_name_en: str | None, target_name_en: str | None
) -> float:
    """
    ضریب رده‌ای ترور فرمانده (۰.۵۵ تا ۱.۳۵).

    روی شانسِ حاصل از کیفیت اطلاعات ضرب می‌شود: کشور نخبه علیه ضعیف تا ۳۵٪
    تقویت می‌شود و کشور ضعیف علیه نخبه تا ۴۵٪ تضعیف.
    """
    factor = 1.0 + gap(spy_name_en, target_name_en) / INTEL_ASSASSINATION_GAP_DIVISOR
    return _clamp(
        factor, INTEL_ASSASSINATION_FACTOR_MIN, INTEL_ASSASSINATION_FACTOR_MAX
    )


def president_gap_bonus(spy_name_en: str | None, target_name_en: str | None) -> float:
    """
    افزایش/کاهش شانس ترور رئیس‌جمهور بابت اختلاف قدرت اطلاعاتی (درصد).

    شانس پایه ۸٪ است؛ آمریکا علیه یمن حدود +۴.۶ و یمن علیه آمریکا −۴.۶
    (که در عمل با مسدودسازی هم مواجه می‌شود).
    """
    return gap(spy_name_en, target_name_en) * INTEL_PRESIDENT_GAP_FACTOR
