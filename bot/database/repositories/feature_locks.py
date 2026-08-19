"""دسترسی داده برای قفل آپشن‌ها (v2.1)."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import FeatureLock


async def is_locked(
    session: AsyncSession, feature_key: str, country_id: int | None = None
) -> bool:
    """
    آیا این آپشن برای این کشور قفل است؟

    قفل سراسری (`country_id IS NULL`) روی همه‌ی کشورها اثر دارد؛ پس هر دو حالت
    در یک کوئری بررسی می‌شوند.
    """
    conditions = [FeatureLock.country_id.is_(None)]
    if country_id is not None:
        conditions.append(FeatureLock.country_id == country_id)

    from sqlalchemy import or_

    result = await session.execute(
        select(FeatureLock.id)
        .where(FeatureLock.feature_key == feature_key, or_(*conditions))
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def list_locks(session: AsyncSession) -> list[FeatureLock]:
    """همه‌ی قفل‌های فعال (برای پنل مالک)."""
    result = await session.execute(
        select(FeatureLock).order_by(FeatureLock.feature_key, FeatureLock.country_id)
    )
    return list(result.scalars().all())


async def list_locks_for_feature(
    session: AsyncSession, feature_key: str
) -> list[FeatureLock]:
    """قفل‌های یک آپشن مشخص (سراسری + به‌تفکیک کشور)."""
    result = await session.execute(
        select(FeatureLock)
        .where(FeatureLock.feature_key == feature_key)
        .order_by(FeatureLock.country_id)
    )
    return list(result.scalars().all())


async def is_locked_globally(session: AsyncSession, feature_key: str) -> bool:
    """آیا این آپشن قفل سراسری دارد؟"""
    result = await session.execute(
        select(FeatureLock.id)
        .where(FeatureLock.feature_key == feature_key, FeatureLock.country_id.is_(None))
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def lock(
    session: AsyncSession,
    feature_key: str,
    country_ids: list[int] | None = None,
    note: str | None = None,
) -> int:
    """
    قفل‌کردن یک آپشن.

    `country_ids=None` → قفل سراسری (و قفل‌های تک‌کشوری همان آپشن پاک می‌شوند
    چون دیگر معنایی ندارند).
    خروجی: تعداد قفل تازه‌ی ثبت‌شده (قفل تکراری دوباره ثبت نمی‌شود).
    """
    if country_ids is None:
        if await is_locked_globally(session, feature_key):
            return 0
        # قفل سراسری، قفل‌های موردی را در خود دارد
        await session.execute(
            delete(FeatureLock).where(
                FeatureLock.feature_key == feature_key,
                FeatureLock.country_id.is_not(None),
            )
        )
        session.add(FeatureLock(feature_key=feature_key, country_id=None, note=note))
        await session.flush()
        return 1

    existing = {
        row.country_id
        for row in await list_locks_for_feature(session, feature_key)
        if row.country_id is not None
    }
    added = 0
    for cid in country_ids:
        if cid in existing:
            continue
        session.add(FeatureLock(feature_key=feature_key, country_id=cid, note=note))
        added += 1
    if added:
        await session.flush()
    return added


async def unlock(
    session: AsyncSession, feature_key: str, country_ids: list[int] | None = None
) -> int:
    """
    رفع قفل یک آپشن.

    `country_ids=None` → همه‌ی قفل‌های آن آپشن (سراسری و موردی) برداشته می‌شود.
    خروجی: تعداد ردیف حذف‌شده.
    """
    stmt = delete(FeatureLock).where(FeatureLock.feature_key == feature_key)
    if country_ids is not None:
        stmt = stmt.where(FeatureLock.country_id.in_(country_ids))
    result = await session.execute(stmt)
    await session.flush()
    return int(result.rowcount or 0)


async def unlock_all(session: AsyncSession) -> int:
    """برداشتن همه‌ی قفل‌ها (بازکردن کل بازی)."""
    result = await session.execute(delete(FeatureLock))
    await session.flush()
    return int(result.rowcount or 0)


async def locked_keys_for_country(
    session: AsyncSession, country_id: int | None
) -> set[str]:
    """کلید همه‌ی آپشن‌هایی که برای این کشور قفل‌اند (سراسری + موردی)."""
    from sqlalchemy import or_

    conditions = [FeatureLock.country_id.is_(None)]
    if country_id is not None:
        conditions.append(FeatureLock.country_id == country_id)

    result = await session.execute(
        select(FeatureLock.feature_key).where(or_(*conditions))
    )
    return set(result.scalars().all())
