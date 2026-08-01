"""
آرکه‌تایپ‌های خبری (v1.10.6) — سبک‌های متفاوت نوشتن یک خبر.

هدف: خبرها هیچ‌وقت با یک فرمت تکراری منتشر نشوند. هر خبر با یکی از این
سبک‌ها نوشته می‌شود و سبک‌های اخیر تکرار نمی‌شوند.

الگوها از نمونه‌های واقعی کانال‌های خبری نظامی تلگرام استخراج شده‌اند:
تیتر کوتاه با 🔴/‼️، متن یک‌دو خطی، نام‌بردن دقیق از تجهیزات واقعی.
"""

from __future__ import annotations

import random

from ...enums import NewsArchetype

# ---------- شرح هر آرکه‌تایپ برای تزریق به پرامپت ----------
ARCHETYPE_GUIDE: dict[NewsArchetype, str] = {
    NewsArchetype.FLASH: (
        "فلش فوری: حداکثر ۲ خط. با 🔴 یا ‼️ شروع کن. فقط واقعه‌ی اصلی، "
        "بدون تحلیل و بدون مقدمه. لحن: تلگرافی و پرشتاب."
    ),
    NewsArchetype.EYEWITNESS: (
        "روایت شاهد عینی: ۲ تا ۳ خط از زبان منابع محلی یا اهالی منطقه. "
        "از عبارات «شاهدان عینی»، «منابع محلی»، «اهالی منطقه» استفاده کن. "
        "صداها، دود، لرزش را توصیف کن — نه اعداد نظامی."
    ),
    NewsArchetype.OFFICIAL: (
        "بیانیه‌ی رسمی نظامی: لحن خشک و اداری. از «ستاد فرماندهی»، "
        "«روابط عمومی نیروهای مسلح»، «سخنگوی ارتش» نقل کن. "
        "با فعل‌های رسمی مثل «اعلام کرد»، «تأیید نمود» بنویس."
    ),
    NewsArchetype.ANALYST: (
        "تحلیل کارشناس نظامی: ۲ تا ۳ خط تحلیلی درباره‌ی معنای راهبردی عملیات. "
        "به توازن قوا، پیام عملیات و پیامدهای احتمالی اشاره کن. "
        "لحن: آرام و کارشناسی، بدون هیجان خبری."
    ),
    NewsArchetype.DEFENSE_REPORT: (
        "گزارش عملکرد پدافند: تمرکز روی سامانه‌های دفاعی مدافع. "
        "نام سامانه‌ها را ببر، از رهگیری و انهدام اهداف بگو. "
        "زاویه‌ی دید: از سمت مدافع."
    ),
    NewsArchetype.DAMAGE_ASSESSMENT: (
        "ارزیابی میدانی خسارت: گزارش آنچه از بین رفته. "
        "به زیرساخت، تجهیزات و وضعیت منطقه اشاره کن. "
        "از «گزارش‌های اولیه»، «ارزیابی‌های میدانی» استفاده کن."
    ),
    NewsArchetype.WIRE: (
        "خبر خبرگزاری بین‌المللی: لحن بی‌طرف و سوم‌شخص. "
        "هر دو طرف را با نام رسمی ذکر کن. مثل رویتر/آسوشیتدپرس بنویس. "
        "بدون ایموجی هیجانی، حداکثر یک ایموجی در ابتدا."
    ),
    NewsArchetype.TICKER: (
        "تیتر تک‌خطی فوری: فقط **یک خط** کوتاه و کوبنده، مثل تیتر زیرنویس تلویزیون. "
        "با 🔴 شروع کن و با علامت تعجب تمام کن. حداکثر ۱۵ کلمه."
    ),
}

# ---------- نگاشت فاز نبرد به آرکه‌تایپ‌های مناسب ----------
# هر فاز نبرد با سبک‌های خاصی بهتر روایت می‌شود.
PHASE_ARCHETYPE_POOL: dict[str, list[NewsArchetype]] = {
    "opening": [NewsArchetype.FLASH, NewsArchetype.TICKER, NewsArchetype.EYEWITNESS],
    "defense": [
        NewsArchetype.DEFENSE_REPORT,
        NewsArchetype.FLASH,
        NewsArchetype.OFFICIAL,
    ],
    "damage": [
        NewsArchetype.DAMAGE_ASSESSMENT,
        NewsArchetype.EYEWITNESS,
        NewsArchetype.WIRE,
    ],
    "second_wave": [NewsArchetype.FLASH, NewsArchetype.TICKER, NewsArchetype.OFFICIAL],
    "reaction": [
        NewsArchetype.WIRE,
        NewsArchetype.OFFICIAL,
        NewsArchetype.ANALYST,
    ],
    "summary": [NewsArchetype.ANALYST, NewsArchetype.WIRE, NewsArchetype.OFFICIAL],
}


def pick_archetype(
    phase_kind: str,
    used: list[str],
    rng: random.Random | None = None,
) -> NewsArchetype:
    """
    یک آرکه‌تایپ برای این فاز انتخاب می‌کند و تا حد امکان از تکرار
    سبک‌های استفاده‌شده در همین نبرد پرهیز می‌کند.
    """
    generator = rng or random
    pool = PHASE_ARCHETYPE_POOL.get(phase_kind) or list(NewsArchetype)

    fresh = [a for a in pool if a.value not in used]
    if fresh:
        return generator.choice(fresh)

    # همه‌ی سبک‌های این فاز استفاده شده‌اند → از کل مجموعه انتخاب کن
    all_fresh = [a for a in NewsArchetype if a.value not in used]
    if all_fresh:
        return generator.choice(all_fresh)

    return generator.choice(list(NewsArchetype))


def guide_for(archetype: NewsArchetype) -> str:
    """راهنمای نوشتن یک آرکه‌تایپ (برای تزریق به پرامپت)."""
    return ARCHETYPE_GUIDE.get(archetype, ARCHETYPE_GUIDE[NewsArchetype.FLASH])
