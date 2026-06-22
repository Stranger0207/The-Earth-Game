"""
نقطه‌ی ورود ربات: راه‌اندازی دیتابیس، میدلورها، روترها و زمان‌بند، سپس شروع polling.

اجرا:
    python -m bot
"""

from __future__ import annotations

import asyncio
import logging
import sys

# اطمینان از خروجی UTF-8 در کنسول ویندوز (برای لاگ‌های فارسی)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from .database.base import init_db
from .handlers import register_all_routers
from .loader import bot, dp
from .middlewares import setup_middlewares
from .scheduler import setup_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("earth_game")


async def main() -> None:
    """راه‌اندازی کامل ربات."""
    logger.info("Initializing database...")
    await init_db()

    logger.info("Registering middlewares and routers...")
    setup_middlewares(dp)
    register_all_routers(dp)

    logger.info("Starting scheduler...")
    setup_scheduler(bot)

    logger.info("Bot is starting (polling)...")
    # حذف آپدیت‌های معوق هنگام شروع
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
