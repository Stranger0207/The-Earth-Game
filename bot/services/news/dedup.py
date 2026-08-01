"""
تشخیص تکرار خبر (v1.10.6).

هر خبر منتشرشده یک «اثرانگشت» می‌گذارد: هش متن + مجموعه‌ی n-gramها.
خبر جدید پیش از انتشار با اخبار اخیر مقایسه می‌شود و اگر بیش از حد شبیه
بود، با آرکه‌تایپ دیگری بازتولید می‌شود.

توابع این ماژول خالص (pure) هستند تا مستقل از دیتابیس تست شوند.
"""

from __future__ import annotations

import hashlib
import re

# سقف شباهت مجاز؛ بالاتر از این یعنی خبر تکراری است
SIMILARITY_THRESHOLD = 0.55

# طول n-gram کاراکتری برای ساخت اثرانگشت
_SHINGLE_SIZE = 5
# حداکثر تعداد shingle ذخیره‌شده در هر اثرانگشت (کنترل حجم دیتابیس)
_MAX_SHINGLES = 220

# کاراکترهای بی‌اثر در معنا که پیش از مقایسه حذف می‌شوند
_NOISE_RE = re.compile(r"[^\w؀-ۿ]+")
# ایموجی‌ها و علائم تزئینی نباید در سنجش شباهت دخالت کنند
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0000FE00-\U0000FE0F‍]+"
)


def normalize(text: str) -> str:
    """نرمال‌سازی متن فارسی برای مقایسه: حذف ایموجی، علائم و فاصله‌های اضافی."""
    cleaned = _EMOJI_RE.sub(" ", text)
    cleaned = _NOISE_RE.sub(" ", cleaned)
    # یکسان‌سازی حروف عربی/فارسی رایج
    cleaned = cleaned.replace("ي", "ی").replace("ك", "ک").replace("ئ", "ی")
    return " ".join(cleaned.split())


def text_hash(text: str) -> str:
    """هش کوتاه متن نرمال‌شده (تشخیص تکرار عیناً یکسان)."""
    normalized = normalize(text)
    digest = hashlib.sha256(normalized.encode("utf-8"), usedforsecurity=False)
    return digest.hexdigest()[:32]


def build_shingles(text: str) -> set[str]:
    """مجموعه‌ی n-gramهای کاراکتری متن (اثرانگشت فازی)."""
    normalized = normalize(text)
    if len(normalized) <= _SHINGLE_SIZE:
        return {normalized} if normalized else set()
    grams = {
        normalized[i : i + _SHINGLE_SIZE]
        for i in range(len(normalized) - _SHINGLE_SIZE + 1)
    }
    if len(grams) <= _MAX_SHINGLES:
        return grams
    return set(sorted(grams)[:_MAX_SHINGLES])


def encode_shingles(shingles: set[str]) -> str:
    """تبدیل مجموعه‌ی shingle به رشته برای ذخیره در دیتابیس."""
    return "|".join(sorted(shingles))


def decode_shingles(encoded: str) -> set[str]:
    """بازخوانی مجموعه‌ی shingle از رشته‌ی ذخیره‌شده."""
    return {s for s in encoded.split("|") if s} if encoded else set()


def similarity(a: set[str], b: set[str]) -> float:
    """شباهت ژاکارد دو مجموعه‌ی shingle (۰ تا ۱)."""
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    if intersection == 0:
        return 0.0
    return intersection / len(a | b)


def max_similarity(candidate: str, previous_encoded: list[str]) -> float:
    """بیشترین شباهت یک خبر جدید با مجموعه‌ای از اخبار قبلی."""
    candidate_shingles = build_shingles(candidate)
    if not candidate_shingles:
        return 0.0
    highest = 0.0
    for encoded in previous_encoded:
        score = similarity(candidate_shingles, decode_shingles(encoded))
        if score > highest:
            highest = score
            if highest >= 1.0:
                break
    return highest


def is_repetitive(
    candidate: str,
    previous_encoded: list[str],
    threshold: float = SIMILARITY_THRESHOLD,
) -> bool:
    """آیا این خبر بیش از حد شبیه اخبار اخیر است؟"""
    return max_similarity(candidate, previous_encoded) >= threshold


# ---------- استخراج عبارات شاخص ----------
# عبارات کلیشه‌ای که اگر در خبر بیایند، برای پرهیز در خبر بعدی ثبت می‌شوند
_CLICHE_PATTERNS = [
    "خبر فوری",
    "گزارش‌های میدانی",
    "شاهدان عینی",
    "منابع محلی",
    "سامانه‌های پدافند",
    "خسارات سنگین",
    "جزئیات بیشتر",
    "آماده‌باش کامل",
    "حملات دقیق",
    "مواضع دشمن",
    "بزودی اعلام",
    "در حال بررسی",
]


def extract_key_phrases(text: str, limit: int = 4) -> list[str]:
    """
    عبارات شاخص یک خبر — برای گفتن «این‌ها را دوباره ننویس» به خبرنویس بعدی.
    ترکیبی از کلیشه‌های شناخته‌شده و طولانی‌ترین عبارت‌های متن.
    """
    normalized = normalize(text)
    found = [c for c in _CLICHE_PATTERNS if normalize(c) in normalized]

    if len(found) < limit:
        # طولانی‌ترین جمله‌های خبر هم به‌عنوان امضای سبک ثبت می‌شوند
        sentences = [s.strip() for s in re.split(r"[.!?\n]", text) if len(s.strip()) > 25]
        sentences.sort(key=len, reverse=True)
        for sentence in sentences:
            snippet = " ".join(sentence.split()[:6])
            if snippet and snippet not in found:
                found.append(snippet)
            if len(found) >= limit:
                break

    return found[:limit]


def encode_phrases(phrases: list[str]) -> str:
    """ذخیره‌سازی عبارات شاخص در یک ستون متنی."""
    return "|".join(p.replace("|", " ").strip() for p in phrases if p.strip())
