"""توابع دسترسی داده برای کاربران."""

from __future__ import annotations

from sqlalchemy import func, select, update
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


async def get_user_by_username(
    session: AsyncSession, username: str
) -> User | None:
    """یافتن کاربر بر اساس نام کاربری (حساس نبودن به حروف کوچک/بزرگ و بدون @)."""
    clean_username = username.lstrip("@").strip().lower()
    if not clean_username:
        return None
    stmt = select(User).where(func.lower(User.username) == clean_username)
    result = await session.execute(stmt)
    return result.scalars().first()


async def list_banned_users(session: AsyncSession) -> list[User]:
    """فهرست تمام کاربران مسدودشده."""
    stmt = select(User).where(User.is_banned.is_(True)).order_by(User.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def unsuspend_countryless_users(session: AsyncSession) -> int:
    """
    رفع تعلیق تمام کاربرانی که معلق هستند اما در حال حاضر مالکیتی بر هیچ کشوری ندارند.
    تعداد کاربران آزادشده را بازمی‌گرداند.
    """
    from ..models import Country

    subq = select(Country.owner_user_id).where(Country.owner_user_id.is_not(None))
    stmt = (
        update(User)
        .where(User.is_suspended.is_(True))
        .where(User.telegram_id.not_in(subq))
        .values(is_suspended=False)
    )
    result = await session.execute(stmt)
    return result.rowcount or 0

