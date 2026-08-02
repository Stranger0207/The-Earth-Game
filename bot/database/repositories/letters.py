"""توابع دسترسی داده برای نامه‌ها (v1.9)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Letter


async def add_letter(
    session: AsyncSession,
    sender_country: int,
    recipient_country: int,
    body: str,
    parent_id: int | None = None,
) -> Letter:
    letter = Letter(
        sender_country=sender_country,
        recipient_country=recipient_country,
        body=body,
        parent_id=parent_id,
    )
    session.add(letter)
    await session.flush()
    return letter


async def get_letter(session: AsyncSession, letter_id: int) -> Letter | None:
    return await session.get(Letter, letter_id)


async def list_inbox(session: AsyncSession, country_id: int) -> list[Letter]:
    """
    نامه‌های دریافتیِ یک کشور (جدیدترین اول).

    (v1.11.1) پاسخ‌ها (`parent_id != None`) هم شامل می‌شوند تا بازیکن بتواند
    از صندوق پستی به یک پاسخ هم پاسخ بدهد و زنجیره‌ی گفتگو قطع نشود.
    """
    result = await session.execute(
        select(Letter)
        .where(Letter.recipient_country == country_id)
        .order_by(Letter.id.desc())
    )
    return list(result.scalars().all())
