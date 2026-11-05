"""ریپازیتوری دسترسی به داده‌های صف برون‌خط همگام‌سازی ربات مقام (rank_sync_outbox)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.rank_sync import RankSyncOutbox


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def add_to_outbox(
    session: AsyncSession,
    event_id: str,
    payload: dict[str, Any] | list[dict[str, Any]],
    last_error: str | None = None,
    event_type: str = "season_ended",
) -> RankSyncOutbox:
    """ثبت یا به‌روزرسانی رویداد در صف ارسال برون‌خط."""
    payload_str = json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload

    # بررسی وجود رکورد با همین event_id جهت جلوگیری از تکرار
    stmt = select(RankSyncOutbox).where(RankSyncOutbox.event_id == event_id)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        existing.payload_json = payload_str
        existing.last_error = last_error
        existing.updated_at = _utcnow()
        return existing

    outbox = RankSyncOutbox(
        event_id=event_id,
        event_type=event_type,
        payload_json=payload_str,
        attempts=0,
        last_error=last_error,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    session.add(outbox)
    await session.flush()
    return outbox


async def get_pending_outbox(
    session: AsyncSession, limit: int = 10
) -> list[RankSyncOutbox]:
    """دریافت لیست رکوردهای معلق در صف جهت تلاش مجدد."""
    stmt = (
        select(RankSyncOutbox)
        .order_by(RankSyncOutbox.created_at.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def delete_outbox_entry(session: AsyncSession, outbox_id: int) -> None:
    """حذف رکورد ارسال‌شده از صف."""
    await session.execute(delete(RankSyncOutbox).where(RankSyncOutbox.id == outbox_id))


async def update_outbox_failure(
    session: AsyncSession, outbox_id: int, error_msg: str
) -> None:
    """ثبت شکست در تلاش ارسال و افزایش شمارنده‌ی تلاش‌ها."""
    outbox = await session.get(RankSyncOutbox, outbox_id)
    if outbox is not None:
        outbox.attempts += 1
        outbox.last_error = error_msg[:1000]
        outbox.updated_at = _utcnow()
