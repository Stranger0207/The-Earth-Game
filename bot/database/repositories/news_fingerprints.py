"""لایه‌ی دسترسی داده برای اثرانگشت‌های خبری (v1.10.6) — موتور ضدتکرار."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.news_fingerprint import NewsFingerprint


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def add_fingerprint(
    session: AsyncSession,
    *,
    category: str,
    archetype: str,
    text_hash: str,
    shingles: str,
    key_phrases: str = "",
) -> NewsFingerprint:
    """ثبت اثرانگشت یک خبر منتشرشده."""
    fingerprint = NewsFingerprint(
        category=category,
        archetype=archetype,
        text_hash=text_hash,
        shingles=shingles,
        key_phrases=key_phrases,
    )
    session.add(fingerprint)
    await session.flush()
    return fingerprint


async def list_recent(
    session: AsyncSession, category: str, *, limit: int = 200
) -> Sequence[NewsFingerprint]:
    """آخرین اثرانگشت‌های یک دسته (برای سنجش شباهت خبر جدید)."""
    stmt = (
        select(NewsFingerprint)
        .where(NewsFingerprint.category == category)
        .order_by(NewsFingerprint.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def exists_exact(session: AsyncSession, text_hash: str) -> bool:
    """آیا خبری با همین هش دقیق قبلاً منتشر شده است؟"""
    stmt = select(NewsFingerprint.id).where(NewsFingerprint.text_hash == text_hash).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def recent_key_phrases(
    session: AsyncSession, category: str, *, limit: int = 8
) -> list[str]:
    """
    عبارات شاخص چند خبر آخر — برای تزریق «این عبارات را تکرار نکن» به پرامپت.
    """
    stmt = (
        select(NewsFingerprint.key_phrases)
        .where(NewsFingerprint.category == category)
        .order_by(NewsFingerprint.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    phrases: list[str] = []
    for raw in result.scalars().all():
        if not raw:
            continue
        phrases.extend(p.strip() for p in raw.split("|") if p.strip())
    # حذف تکراری‌ها با حفظ ترتیب
    seen: set[str] = set()
    unique: list[str] = []
    for phrase in phrases:
        if phrase not in seen:
            seen.add(phrase)
            unique.append(phrase)
    return unique


async def recent_archetypes(
    session: AsyncSession, category: str, *, limit: int = 5
) -> list[str]:
    """آرکه‌تایپ‌های چند خبر آخر (تا سبک خبر پشت‌سرهم تکرار نشود)."""
    stmt = (
        select(NewsFingerprint.archetype)
        .where(NewsFingerprint.category == category)
        .order_by(NewsFingerprint.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [a for a in result.scalars().all() if a]


async def purge_older_than(session: AsyncSession, days: int = 14) -> int:
    """پاک‌سازی اثرانگشت‌های قدیمی تا جدول بی‌دلیل بزرگ نشود."""
    cutoff = _utcnow() - timedelta(days=days)
    result = await session.execute(
        delete(NewsFingerprint).where(NewsFingerprint.created_at < cutoff)
    )
    return result.rowcount or 0
