"""سرویس هوشمند فیلتر فحش و کلمات رکیک (Profanity Filter Service).

شامل:
- الگوریتم پیشرفته نرمال‌سازی متن (یکسان‌سازی کاراکترهای عربی/فارسی، حذف اعراب، فواصل مجازی، کشیدگی)
- تشخیص ترفندهای نگارشی دور زدن (تکرار حروف مثل «فحشششش»، فاصله‌گذاری مثل «ف.ح.ش» یا «ف ح ش»)
- مصونیت کامل واژگان مشروع سیاسی و نظامی بازی (حمله، ترور، موشک، کشتار، تجاوز، کشتی، کشور، ارتش، مشکل و...)
- کش مقیم در حافظه (In-Memory Cache) با سرعت جستجوی میکروثانیه‌ای O(1)
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models.bot_state import BotState
from ..database.models.profanity import ProfanityWord
from ..database.repositories import profanity as profanity_repo

logger = logging.getLogger(__name__)

# کش درون‌حافظه‌ای
_CACHED_WORDS: set[str] = set()
_CACHED_PHRASES: list[str] = []
_FILTER_ENABLED_CACHE: bool = True
_INITIAL_SEEDED: bool = False

# مسیر فایل پیش‌فرض کلمات اولیه
_DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "profanity_words.json"

# الگوهای تمیزکاری اعراب و نویسه‌های مخفی
_HARAKAT_RE = re.compile(r"[\u064B-\u065F\u0670\u0617-\u061A]")
_ZERO_WIDTH_RE = re.compile(r"[\u200B-\u200F\u202A-\u202E\uFEFF\u0640]")
_MULTIPLE_SPACES_RE = re.compile(r"\s+")
_REPEATED_CHARS_RE = re.compile(r"(.)\1+")
_TOKEN_RE = re.compile(r"[^\W_]+")


def normalize_text(text: str) -> str:
    """نرمال‌سازی کامل متن: تبدیل کاراکترهای عربی، حذف اعراب، نیم‌فاصله و کشیدگی."""
    if not text:
        return ""

    t = text.lower()

    # یکسان‌سازی حروف عربی و فارسی
    char_map = {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ة": "ه",
        "ؤ": "و",
        "إ": "ا",
        "أ": "ا",
        "آ": "ا",
        "ء": "",
        "ئ": "ی",
    }
    for orig, rep in char_map.items():
        t = t.replace(orig, rep)

    # حذف اعراب و نشانه‌های حرکتی
    t = _HARAKAT_RE.sub("", t)

    # حذف کشیدگی (تطویل) و نویسه‌های بدون عرض / جهت‌دار
    t = _ZERO_WIDTH_RE.sub("", t)

    # تبدیل جداکننده‌ها به فاصله برای یکپارچگی
    t = t.replace("_", " ").replace("-", " ")

    # یکدست‌سازی فواصل
    t = _MULTIPLE_SPACES_RE.sub(" ", t).strip()
    return t


def collapse_repeated_letters(word: str) -> str:
    """کاهش تکرار متوالی حروف (مثلاً 'فحشششش' -> 'فحش')."""
    return _REPEATED_CHARS_RE.sub(r"\1", word)


def _rebuild_cache(words: list[str]) -> None:
    """بازسازی کش سریع حافظه از لیست کلمات."""
    global _CACHED_WORDS, _CACHED_PHRASES
    new_words: set[str] = set()
    new_phrases: list[str] = []

    for raw in words:
        norm = normalize_text(raw)
        if not norm:
            continue
        if " " in norm:
            new_phrases.append(norm)
        else:
            new_words.add(norm)

    # مرتب‌سازی عبارات چندکلمه‌ای از طولانی‌تر به کوتاه‌تر
    new_phrases.sort(key=len, reverse=True)

    _CACHED_WORDS = new_words
    _CACHED_PHRASES = new_phrases


async def load_cache(session: AsyncSession) -> None:
    """بارگذاری تمام کلمات ممنوعه از دیتابیس در کش حافظه."""
    words = await profanity_repo.get_all_words(session)
    word_texts = [w.word for w in words]
    _rebuild_cache(word_texts)

    # کش وضعیت فیلتر
    res = await session.execute(select(BotState).where(BotState.id == 1))
    bstate = res.scalars().first()
    global _FILTER_ENABLED_CACHE
    if bstate is not None:
        _FILTER_ENABLED_CACHE = getattr(bstate, "profanity_filter_enabled", True)
    else:
        _FILTER_ENABLED_CACHE = True


async def ensure_seeded(session: AsyncSession) -> int:
    """بارگذاری کلمات اولیه از JSON در دیتابیس در صورت خالی بودن جدول."""
    global _INITIAL_SEEDED
    if _INITIAL_SEEDED and _CACHED_WORDS:
        return 0

    count = await profanity_repo.count_words(session)
    added = 0
    if count == 0 and _DATA_FILE.exists():
        try:
            with open(_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                added = await profanity_repo.add_words_bulk(session, data, added_by=0)
                await session.commit()
                logger.info("Seeded %d initial profanity words into database.", added)
        except Exception as exc:
            logger.warning("Could not seed initial profanity words: %s", exc)

    await load_cache(session)
    _INITIAL_SEEDED = True
    return added


def check_profanity(text: str) -> tuple[bool, str | None]:
    """
    بررسی وجود کلمات یا عبارات رکیک در متن.
    
    خروجی:
        (True, matched_word) در صورت وجود فحش
        (False, None) در صورت پاک بودن متن
    """
    if not text or not _CACHED_WORDS and not _CACHED_PHRASES:
        return False, None

    norm = normalize_text(text)
    if not norm:
        return False, None

    # ۱. بررسی عبارات چندکلمه‌ای با مرز کلمه
    for phrase in _CACHED_PHRASES:
        # جستجو بر پایه مرز کلمه در متن
        pattern = r"(?<![^\W_])" + re.escape(phrase) + r"(?![^\W_])"
        if re.search(pattern, norm):
            return True, phrase

    # ۲. توکنایز کردن کلمات بر پایه فواصل و علائم نگارشی
    tokens = _TOKEN_RE.findall(norm)
    if not tokens:
        return False, None

    for token in tokens:
        # بررسی دقیق توکن
        if token in _CACHED_WORDS:
            return True, token

        # بررسی با کاهش تکرار حروف متوالی (مثل فحشششش)
        collapsed = collapse_repeated_letters(token)
        if collapsed != token and collapsed in _CACHED_WORDS:
            return True, token

    # ۳. تشخیص کلماتی که با علائم نگارشی یا فاصله تک‌حرفی تقطیع شده‌اند (مثل ف.ح.ش یا ف_ح_ش یا ف ح ش)
    # اگر ۲ یا چند توکن متوالی ۱ حرفی داشته باشیم، ترکیب آن‌ها را بررسی می‌کنیم
    if len(tokens) >= 2:
        current_seq: list[str] = []
        for t in tokens:
            if len(t) == 1:
                current_seq.append(t)
            else:
                if len(current_seq) >= 2:
                    joined = "".join(current_seq)
                    if joined in _CACHED_WORDS or collapse_repeated_letters(joined) in _CACHED_WORDS:
                        return True, joined
                current_seq = []
        if len(current_seq) >= 2:
            joined = "".join(current_seq)
            if joined in _CACHED_WORDS or collapse_repeated_letters(joined) in _CACHED_WORDS:
                return True, joined

    return False, None


def is_filter_enabled() -> bool:
    """وضعیت فعلی کش روشن/خاموش بودن فیلتر."""
    return _FILTER_ENABLED_CACHE


def set_filter_enabled_cache(enabled: bool) -> None:
    """به‌روزرسانی کش وضعیت روشن/خاموش بودن فیلتر."""
    global _FILTER_ENABLED_CACHE
    _FILTER_ENABLED_CACHE = enabled


async def toggle_filter(session: AsyncSession) -> bool:
    """تغییر وضعیت فعال/غیرفعال بودن فیلتر در دیتابیس و کش."""
    res = await session.execute(select(BotState).where(BotState.id == 1))
    bstate = res.scalars().first()
    if bstate is None:
        bstate = BotState(id=1, profanity_filter_enabled=False)
        session.add(bstate)
        new_val = False
    else:
        new_val = not getattr(bstate, "profanity_filter_enabled", True)
        bstate.profanity_filter_enabled = new_val

    await session.commit()
    set_filter_enabled_cache(new_val)
    return new_val


async def set_filter_enabled(session: AsyncSession, enabled: bool) -> None:
    """تنظیم صریح وضعیت فیلتر در دیتابیس و کش."""
    res = await session.execute(select(BotState).where(BotState.id == 1))
    bstate = res.scalars().first()
    if bstate is None:
        bstate = BotState(id=1, profanity_filter_enabled=enabled)
        session.add(bstate)
    else:
        bstate.profanity_filter_enabled = enabled
    await session.commit()
    set_filter_enabled_cache(enabled)


async def add_word(session: AsyncSession, word: str, admin_id: int = 0) -> bool:
    """افزودن یک کلمه جدید به دیتابیس و به‌روزرسانی آنی کش رم."""
    norm = normalize_text(word)
    if not norm:
        return False
    pw = await profanity_repo.add_word(session, norm, added_by=admin_id)
    if pw is not None:
        await session.commit()
        if " " in norm:
            if norm not in _CACHED_PHRASES:
                _CACHED_PHRASES.append(norm)
                _CACHED_PHRASES.sort(key=len, reverse=True)
        else:
            _CACHED_WORDS.add(norm)
        return True
    return False


async def add_words_bulk(session: AsyncSession, words: list[str], admin_id: int = 0) -> int:
    """افزودن دسته‌ای از کلمات به دیتابیس و به‌روزرسانی آنی کش رم."""
    normalized_list = [normalize_text(w) for w in words if normalize_text(w)]
    added_count = await profanity_repo.add_words_bulk(session, normalized_list, added_by=admin_id)
    if added_count > 0:
        await session.commit()
        await load_cache(session)
    return added_count


async def remove_word(session: AsyncSession, word: str) -> bool:
    """حذف یک کلمه از دیتابیس و کش رم."""
    norm = normalize_text(word)
    if not norm:
        return False
    ok = await profanity_repo.remove_word(session, norm)
    if ok:
        await session.commit()
        _CACHED_WORDS.discard(norm)
        if norm in _CACHED_PHRASES:
            _CACHED_PHRASES.remove(norm)
        return True
    return False


async def get_all_words(session: AsyncSession) -> list[str]:
    """دریافت لیست تمام کلمات ذخیره شده."""
    items = await profanity_repo.get_all_words(session)
    return [item.word for item in items]
