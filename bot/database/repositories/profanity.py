"""ریپازیتوری دسترسی به داده‌های فیلتر فحش و کلمات رکیک (profanity_words)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.profanity import ProfanityWord


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def get_all_words(session: AsyncSession) -> list[ProfanityWord]:
    """دریافت تمام کلمات ممنوعه ذخیره‌شده."""
    stmt = select(ProfanityWord).order_by(ProfanityWord.word.asc())
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def count_words(session: AsyncSession) -> int:
    """تعداد کل کلمات ممنوعه موجود در جدول."""
    stmt = select(func.count(ProfanityWord.id))
    res = await session.execute(stmt)
    return res.scalar_one_or_none() or 0


async def get_words_paginated(
    session: AsyncSession, offset: int = 0, limit: int = 20
) -> tuple[list[ProfanityWord], int]:
    """دریافت لیست صفحه‌بندی‌شده کلمات همراه با تعداد کل."""
    total = await count_words(session)
    stmt = select(ProfanityWord).order_by(ProfanityWord.word.asc()).offset(offset).limit(limit)
    res = await session.execute(stmt)
    return list(res.scalars().all()), total


async def add_word(
    session: AsyncSession, word: str, added_by: int = 0
) -> ProfanityWord | None:
    """افزودن یک کلمه ممنوعه جدید (در صورت عدم تکرار)."""
    cleaned = word.strip()
    if not cleaned:
        return None
    stmt = select(ProfanityWord).where(ProfanityWord.word == cleaned)
    existing = (await session.execute(stmt)).scalars().first()
    if existing is not None:
        return None
    pw = ProfanityWord(word=cleaned, added_by=added_by, created_at=_utcnow())
    session.add(pw)
    await session.flush()
    return pw


async def add_words_bulk(
    session: AsyncSession, words: list[str], added_by: int = 0
) -> int:
    """افزودن دسته‌ای از کلمات جدید و بازگرداندن تعداد افزوده شده."""
    existing_all = set((await session.execute(select(ProfanityWord.word))).scalars().all())
    to_add: list[ProfanityWord] = []
    now = _utcnow()
    seen: set[str] = set()
    for w in words:
        cleaned = w.strip()
        if not cleaned or cleaned in existing_all or cleaned in seen:
            continue
        seen.add(cleaned)
        to_add.append(ProfanityWord(word=cleaned, added_by=added_by, created_at=now))
    if to_add:
        session.add_all(to_add)
        await session.flush()
    return len(to_add)


async def remove_word(session: AsyncSession, word: str) -> bool:
    """حذف یک کلمه از بلک‌لیست."""
    cleaned = word.strip()
    if not cleaned:
        return False
    stmt = delete(ProfanityWord).where(ProfanityWord.word == cleaned)
    res = await session.execute(stmt)
    await session.flush()
    return (res.rowcount or 0) > 0
