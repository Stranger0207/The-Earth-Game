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


# ستون‌هایی که در آپدیت‌ها به جدول‌های موجود اضافه شده‌اند.
# (جدول، نام ستون، تعریف SQL). هنگام راه‌اندازی، ستون‌های ناموجود خودکار اضافه می‌شوند.
_COLUMN_MIGRATIONS = [
    # v1.5
    ("countries", "international_duties", "DOUBLE PRECISION NOT NULL DEFAULT 0"),
    ("sanctions", "sanction_type", "VARCHAR(24) NOT NULL DEFAULT ''"),
    ("group_meetings", "start_at", "TIMESTAMP WITH TIME ZONE"),
    ("group_meeting_participants", "travel_eta", "TIMESTAMP WITH TIME ZONE"),
    # v1.6
    ("meetings", "start_announced", "BOOLEAN NOT NULL DEFAULT FALSE"),
]


def _apply_column_migrations(sync_conn) -> None:
    """
    ستون‌های جدید را به جدول‌های موجود اضافه می‌کند (مستقل از نوع دیتابیس).
    ابتدا بررسی می‌شود ستون وجود ندارد، سپس اضافه می‌شود؛ پس اجرای چندباره بی‌خطر است.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    existing_tables = set(inspector.get_table_names())
    for table, column, ddl in _COLUMN_MIGRATIONS:
        if table not in existing_tables:
            continue  # جدول هنوز ساخته نشده (در create_all ساخته خواهد شد)
        columns = {c["name"] for c in inspector.get_columns(table)}
        if column not in columns:
            sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


async def init_db() -> None:
    """
    ساخت همه‌ی جدول‌ها اگر وجود نداشته باشند و افزودن ستون‌های جدید آپدیت‌ها به‌صورت خودکار.
    این کار باعث می‌شود راه‌اندازی ربات روی دیتابیس قدیمی بدون نیاز به مهاجرت دستی کار کند.
    """
    # وارد کردن همه‌ی مدل‌ها تا در متادیتای Base ثبت شوند
    from . import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # مهاجرت سبک: افزودن ستون‌های جدید به جدول‌های از قبل موجود
        await conn.run_sync(_apply_column_migrations)
