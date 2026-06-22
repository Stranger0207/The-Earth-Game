"""
زیرساخت دیتابیس: ساخت موتور ناهمگام (async engine)، کارخانه‌ی session و کلاس پایه‌ی مدل‌ها.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from ..config import get_settings

settings = get_settings()

# موتور ناهمگام متصل به PostgreSQL (درایور asyncpg)
engine = create_async_engine(
    settings.database_url,
    echo=False,        # برای دیباگ کوئری‌ها می‌توان True کرد
    pool_pre_ping=True,
)

# کارخانه‌ی ساخت session؛ expire_on_commit=False تا اشیا بعد از commit قابل‌استفاده بمانند
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """کلاس پایه‌ی همه‌ی مدل‌های ORM."""


async def get_session() -> AsyncIterator[AsyncSession]:
    """یک session تازه می‌سازد و در پایان آن را می‌بندد (برای استفاده با async with/depends)."""
    async with async_session_factory() as session:
        yield session


async def init_db() -> None:
    """
    ساخت همه‌ی جدول‌ها اگر وجود نداشته باشند.
    (برای ساخت اولیه؛ در آینده می‌توان از Alembic برای مهاجرت استفاده کرد.)
    """
    # وارد کردن همه‌ی مدل‌ها تا در متادیتای Base ثبت شوند
    from . import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
