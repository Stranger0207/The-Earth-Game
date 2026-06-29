"""دسترسی داده برای وضعیت سراسری ربات (v1.10.5)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import BotState

_SINGLETON_ID = 1


async def get_state(session: AsyncSession) -> BotState:
    """وضعیت ربات را برمی‌گرداند؛ در صورت نبود، سطر پیش‌فرض را می‌سازد."""
    state = await session.get(BotState, _SINGLETON_ID)
    if state is None:
        state = BotState(id=_SINGLETON_ID, maintenance=False, auto_off_enabled=False)
        session.add(state)
        await session.flush()
    return state


async def update_state(session: AsyncSession, **fields) -> BotState:
    """به‌روزرسانی فیلدهای وضعیت ربات."""
    state = await get_state(session)
    for key, value in fields.items():
        setattr(state, key, value)
    await session.flush()
    return state
