"""توابع دسترسی داده برای کاربران."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...enums import UserRole
from ..models import User


async def get_user(session: AsyncSession, telegram_id: int) -> User | None:
    """دریافت کاربر بر اساس آی‌دی تلگرام."""
    return await session.get(User, telegram_id)


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None,
    first_name: str | None,
) -> User:
    """اگر کاربر وجود نداشت آن را می‌سازد، در غیر این صورت اطلاعاتش را به‌روز می‌کند."""
    user = await session.get(User, telegram_id)
    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            role=UserRole.PLAYER,
        )
        session.add(user)
        await session.flush()
    else:
        # به‌روزرسانی نام کاربری/نام در صورت تغییر
        user.username = username
        user.first_name = first_name
    return user


async def set_president_name(
    session: AsyncSession, telegram_id: int, name: str
) -> None:
    """تنظیم نام رئیس‌جمهور برای کاربر."""
    user = await session.get(User, telegram_id)
    if user is not None:
        user.president_name = name


async def set_role(session: AsyncSession, telegram_id: int, role: UserRole) -> None:
    """تغییر نقش کاربر."""
    user = await session.get(User, telegram_id)
    if user is not None:
        user.role = role


async def set_banned(session: AsyncSession, telegram_id: int, banned: bool) -> None:
    """مسدود/آزاد کردن کاربر."""
    user = await session.get(User, telegram_id)
    if user is not None:
        user.is_banned = banned


async def set_suspended(session: AsyncSession, telegram_id: int, suspended: bool) -> None:
    """تعلیق/رفع تعلیق کاربر (v1.10.5) — متمایز از بن کامل."""
    user = await session.get(User, telegram_id)
    if user is not None:
        user.is_suspended = suspended


async def all_users(session: AsyncSession) -> list[User]:
    """فهرست همه‌ی کاربران."""
    result = await session.execute(select(User))
    return list(result.scalars().all())
