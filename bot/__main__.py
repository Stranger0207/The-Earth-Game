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

    # اطمینان از وجود تمام کشورهای پایه و نهادهای جدید (مانند UN) در دیتابیس
    try:
        from scripts.seed import seed_countries
        await seed_countries()
    except Exception as exc:
        logger.warning("Could not auto-seed countries: %s", exc)

    # بارگذاری مدیران و مالکان پویا از دیتابیس در کش حافظه
    from .config import set_dynamic_team
    from .database.base import async_session_factory
    from .database.repositories import users as users_repo

    async with async_session_factory() as session:
        db_admins, db_owners = await users_repo.list_team_members(session)
        set_dynamic_team(
            admin_ids=[u.telegram_id for u in db_admins],
            owner_ids=[u.telegram_id for u in db_owners],
        )
        logger.info(
            "Loaded %d dynamic admin(s) and %d dynamic owner(s).",
            len(db_admins),
            len(db_owners),
        )

    logger.info("Registering middlewares and routers...")
    setup_middlewares(dp)
    register_all_routers(dp)

    logger.info("Starting scheduler...")
    setup_scheduler(bot)

    from .config import get_settings
    from .webapp import start_webapp

    settings = get_settings()
    webapp_runner = None
    try:
        logger.info("Starting Live Radar WebApp on port %d...", settings.webapp_port)
        webapp_runner = await start_webapp(bot, settings.webapp_port)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not start Live Radar WebApp: %s", exc)

    logger.info("Bot is starting (polling)...")
    # حذف آپدیت‌های معوق هنگام شروع
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        if webapp_runner:
            logger.info("Stopping Live Radar WebApp...")
            await webapp_runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
