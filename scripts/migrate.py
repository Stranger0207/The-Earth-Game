"""
مهاجرت سبک دیتابیس برای آپدیت v1.5.
ستون‌های جدید را به جدول‌های موجود اضافه می‌کند (بدون آسیب به داده‌ها) و جدول‌های جدید را می‌سازد.

روی PostgreSQL از «ADD COLUMN IF NOT EXISTS» استفاده می‌شود (idempotent — اجرای چندباره بی‌خطر است).

اجرا:
    python -m scripts.migrate
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import text  # noqa: E402

from bot.database.base import engine, init_db  # noqa: E402

# ستون‌های جدیدی که باید به جدول‌های موجود اضافه شوند (جدول، تعریف ستون)
_NEW_COLUMNS = [
    ("countries", "international_duties", "DOUBLE PRECISION NOT NULL DEFAULT 0"),
    ("sanctions", "sanction_type", "VARCHAR(24) NOT NULL DEFAULT ''"),
    ("group_meetings", "start_at", "TIMESTAMPTZ"),
    ("group_meeting_participants", "travel_eta", "TIMESTAMPTZ"),
]


async def main() -> None:
    # ابتدا جدول‌های جدید (speeches، tariff_rates) ساخته می‌شوند
    print("⏳ ساخت جدول‌های جدید...")
    await init_db()

    print("⏳ افزودن ستون‌های جدید به جدول‌های موجود...")
    async with engine.begin() as conn:
        for table, column, definition in _NEW_COLUMNS:
            stmt = text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}"
            )
            await conn.execute(stmt)
            print(f"  ✅ {table}.{column}")
    print("🎉 مهاجرت v1.5 کامل شد.")


if __name__ == "__main__":
    asyncio.run(main())
