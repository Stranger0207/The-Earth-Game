"""
خبرنویس نظامی (v1.10.6) — تولید خبر متنوع و ضدتکرار.

جریان کار:
۱. آرکه‌تایپ (سبک) تازه‌ای برای این فاز انتخاب می‌شود.
۲. واقعیت‌های خام همان فاز از نتیجه‌ی موتور نبرد استخراج می‌شود.
۳. عبارات خبرهای اخیر خوانده و به پرامپت تزریق می‌شود («این‌ها را تکرار نکن»).
۴. AI خبر را می‌نویسد؛ اگر شبیه اخبار اخیر بود، با سبک دیگری بازتولید می‌شود.
۵. اثرانگشت خبر برای مقایسه‌های آینده ذخیره می‌شود.

اگر AI در دسترس نباشد، قالب‌های پشتیبان (`facts.fallback_news`) استفاده می‌شوند
تا جریان بازی هرگز قطع نشود.
"""

from __future__ import annotations

import logging
import random

from sqlalchemy.ext.asyncio import AsyncSession

from ...database.repositories import news_fingerprints as fp_repo
from ..ai import prompts
from ..ai.client import ask_ai
from . import archetypes, dedup, facts as facts_mod

logger = logging.getLogger(__name__)

# حداکثر تلاش برای تولید خبر غیرتکراری
_MAX_ATTEMPTS = 3

# برچسب فارسی هر نوع فاز (برای پرامپت)
_PHASE_LABELS: dict[str, str] = {
    "opening": "آغاز عملیات — خبر فوری نخست",
    "defense": "واکنش پدافندی مدافع",
    "damage": "گزارش خسارات",
    "second_wave": "موج دوم حمله",
    "reaction": "واکنش‌های بین‌المللی",
    "summary": "جمع‌بندی نهایی عملیات",
}

# نشانه‌ی خطای کلاینت AI (client.ask_ai در خطا این پیام را برمی‌گرداند)
_AI_ERROR_MARK = "⚠️ خطا در ارتباط"


def _is_ai_failure(text: str) -> bool:
    """آیا پاسخ AI معتبر نیست؟"""
    stripped = (text or "").strip()
    return not stripped or _AI_ERROR_MARK in stripped or len(stripped) < 20


def _trim(text: str, max_lines: int = 5, max_chars: int = 900) -> str:
    """کوتاه‌سازی خبر: حذف خطوط خالی اضافی و رعایت سقف طول کپشن تلگرام."""
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    trimmed = "\n".join(lines[:max_lines])
    if len(trimmed) > max_chars:
        trimmed = trimmed[: max_chars - 1].rstrip() + "…"
    return trimmed


async def write_phase_news(
    session: AsyncSession,
    battle_facts: dict,
    phase_kind: str,
    *,
    used_archetypes: list[str] | None = None,
    category: str = "military",
    seed: int | None = None,
) -> tuple[str, str]:
    """
    یک خبر برای یک فاز عملیات می‌نویسد.

    خروجی: (متن خبر، آرکه‌تایپ استفاده‌شده)

    این تابع هیچ‌وقت استثنا پرتاب نمی‌کند؛ در بدترین حالت خبر پشتیبان می‌دهد.
    """
    rng = random.Random(seed)
    used = list(used_archetypes or [])
    phase_label = _PHASE_LABELS.get(phase_kind, "گزارش عملیات")
    facts_text = facts_mod.facts_to_text(battle_facts, phase_kind)

    # عبارات و سبک‌های اخیر برای پرهیز از تکرار
    try:
        avoid_phrases = await fp_repo.recent_key_phrases(session, category, limit=6)
        recent_encoded = [
            fp.shingles for fp in await fp_repo.list_recent(session, category, limit=60)
        ]
    except Exception as exc:  # noqa: BLE001 — خطای DB نباید خبر را متوقف کند
        logger.warning("Failed to load news history: %s", exc)
        avoid_phrases, recent_encoded = [], []

    best_text = ""
    best_similarity = 1.0
    # سبک پیش‌فرض هم چرخشی انتخاب می‌شود تا اگر AI در دسترس نبود،
    # فازهای مختلف یک عملیات سبک یکسان ثبت نکنند.
    best_archetype = archetypes.pick_archetype(phase_kind, used, rng)

    for attempt in range(_MAX_ATTEMPTS):
        archetype = archetypes.pick_archetype(phase_kind, used, rng)
        guide = archetypes.guide_for(archetype)

        try:
            raw = await ask_ai(
                prompts.military_news_prompt(phase_label, guide, avoid_phrases),
                f"واقعیت‌های تأییدشده‌ی این مرحله:\n{facts_text}",
                temperature=0.95,
                max_tokens=400,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Military news AI call failed: %s", exc)
            raw = ""

        if _is_ai_failure(raw):
            # AI در دسترس نیست → مستقیم به قالب پشتیبان
            break

        candidate = _trim(raw)
        similarity = dedup.max_similarity(candidate, recent_encoded)

        # بهترین گزینه‌ی دیده‌شده را نگه دار
        if similarity < best_similarity:
            best_text, best_similarity, best_archetype = candidate, similarity, archetype

        if similarity < dedup.SIMILARITY_THRESHOLD:
            break  # به‌قدر کافی متفاوت است

        # تکراری بود → سبک این تلاش را بسوزان و دوباره امتحان کن
        used.append(archetype.value)
        logger.info(
            "Regenerating news (attempt %d): similarity %.2f too high",
            attempt + 1,
            similarity,
        )

    # اگر AI هیچ متن قابل‌قبولی نداد، خبر پشتیبان (سبک از قبل چرخشی انتخاب شده)
    if not best_text:
        best_text = facts_mod.fallback_news(battle_facts, phase_kind, rng)

    # ثبت اثرانگشت برای مقایسه‌های آینده
    try:
        await fp_repo.add_fingerprint(
            session,
            category=category,
            archetype=best_archetype.value,
            text_hash=dedup.text_hash(best_text),
            shingles=dedup.encode_shingles(dedup.build_shingles(best_text)),
            key_phrases=dedup.encode_phrases(dedup.extract_key_phrases(best_text)),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to store news fingerprint: %s", exc)

    return best_text, best_archetype.value
