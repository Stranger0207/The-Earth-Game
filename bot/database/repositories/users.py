from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


async def get_user_by_username_or_id(
    session: AsyncSession, identifier: str | int
) -> tuple[User | None, int | None, str | None]:
    """
    یافتن کاربر هدف بر اساس آیدی عددی یا @username.
    خروجی: (db_user, telegram_id, error_message)
    """
    if isinstance(identifier, int):
        user = await get_user(session, identifier)
        return user, identifier, None

    clean = str(identifier).strip()
    if not clean:
        return None, None, "شناسه‌ای وارد نشده است."

    # اگر آیدی عددی است
    if clean.isdigit() or (clean.startswith("-") and clean[1:].isdigit()):
        uid = int(clean)
        user = await get_user(session, uid)
        return user, uid, None

    # اگر نام کاربری است (@username یا username)
    uname = clean.lstrip("@")
    user = await get_user_by_username(session, uname)
    if user is not None:
        return user, user.telegram_id, None

    return None, None, (
        f"❌ کاربری با نام کاربری @{uname} در دیتابیس ربات یافت نشد.\n"
        "💡 کاربر باید حداقل یک‌بار ربات را استارت کرده باشد تا نام کاربری‌اش ثبت شود. "
        "می‌توانید از آیدی عددی تلگرام کاربر استفاده کنید."
    )


async def set_user_admin(
    session: AsyncSession, telegram_id: int, is_admin: bool
) -> User | None:
    """تنظیم دسترسی ادمین پویا برای کاربر."""
    user = await session.get(User, telegram_id)
    if user is not None:
        user.is_admin = is_admin
    return user


async def set_user_owner(
    session: AsyncSession, telegram_id: int, is_owner: bool
) -> User | None:
    """تنظیم دسترسی مالک پویا برای کاربر (مالک بودن متضمن ادمین بودن نیز هست)."""
    user = await session.get(User, telegram_id)
    if user is not None:
        user.is_owner = is_owner
        if is_owner:
            user.is_admin = True
    return user


async def set_timed_suspension(
    session: AsyncSession,
    telegram_id: int,
    duration_hours: int,
    reason: str | None = None,
) -> tuple[User | None, datetime]:
    """تعلیق زمان‌دار کاربر برای مدت مشخص (ساعت)."""
    user = await session.get(User, telegram_id)
    until = datetime.now(timezone.utc) + timedelta(hours=duration_hours)
    if user is not None:
        user.is_suspended = True
        user.suspended_until = until
        user.suspension_reason = reason
    return user, until


async def lift_suspension(session: AsyncSession, telegram_id: int) -> User | None:
    """رفع تعلیق کاربر و پاکسازی اطلاعات زمان‌دار."""
    user = await session.get(User, telegram_id)
    if user is not None:
        user.is_suspended = False
        user.suspended_until = None
        user.suspension_reason = None
    return user


async def list_team_members(
    session: AsyncSession,
) -> tuple[list[User], list[User]]:
    """فهرست تمام ادمین‌ها و مالکان ثبت‌شده در دیتابیس: (admins, owners)."""
    stmt_admins = select(User).where(User.is_admin.is_(True)).order_by(User.telegram_id)
    stmt_owners = select(User).where(User.is_owner.is_(True)).order_by(User.telegram_id)
    res_admins = await session.execute(stmt_admins)
    res_owners = await session.execute(stmt_owners)
    return list(res_admins.scalars().all()), list(res_owners.scalars().all())


async def list_suspended_users(session: AsyncSession) -> list[User]:
    """فهرست تمام کاربران در وضعیت تعلیق."""
    stmt = (
        select(User)
        .where(User.is_suspended.is_(True))
        .order_by(User.suspended_until.asc().nulls_last())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_expired_suspended_users(
    session: AsyncSession, now: datetime
) -> list[User]:
    """کاربرانی که تعلیق زمان‌دارشان سررسید شده است."""
    stmt = (
        select(User)
        .where(User.is_suspended.is_(True))
        .where(User.suspended_until.is_not(None))
        .where(User.suspended_until <= now)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_all_user_telegram_ids(session: AsyncSession) -> list[int]:
    """فهرست آیدی تلگرام تمام کاربرانی که تاکنون ربات را استارت کرده‌اند."""
    stmt = select(User.telegram_id).order_by(User.telegram_id.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


