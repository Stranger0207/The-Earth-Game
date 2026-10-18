"""
وب‌سرور سبک aiohttp برای مینی‌اپ رادار زنده استراتژیک جهان (Live Strategic Radar).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from aiohttp import web
from aiogram import Bot

from ..config import get_settings
from ..database.base import async_session_factory
from .auth import extract_telegram_id
from .state import get_radar_state

logger = logging.getLogger(__name__)
settings = get_settings()

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _cors_headers() -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-Telegram-Init-Data, Authorization",
    }


async def handle_options(request: web.Request) -> web.Response:
    """پاسخ به پیش‌پروازهای CORS برای کلاینت‌های مختلف."""
    return web.Response(headers=_cors_headers())


async def handle_index(request: web.Request) -> web.Response:
    """ارائه صفحه اصلی مینی‌اپ نقشه زنده."""
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return web.Response(
            text="<h1>Live Radar UI not found</h1>",
            content_type="text/html",
            status=404,
        )
    return web.FileResponse(index_file)


async def handle_radar_state(request: web.Request) -> web.Response:
    """
    اندپوینت دریافت وضعیت زنده نقشه استراتژیک جهان:
    /api/radar-state
    """
    bot: Bot = request.app["bot"]
    bot_token = settings.bot_token

    # استخراج initData از هدر یا کوئری‌استرینگ
    init_data = (
        request.headers.get("X-Telegram-Init-Data")
        or request.query.get("initData")
        or request.query.get("init_data")
        or ""
    )

    viewer_user_id = extract_telegram_id(init_data, bot_token)

    # حالت توسعه و تست: پشتیبانی از تست‌های خودکار با هدر یا کوئری آزمایشی
    if not viewer_user_id:
        test_uid = request.headers.get("X-Test-User-Id") or request.query.get("test_user_id")
        if test_uid:
            try:
                viewer_user_id = int(test_uid)
            except ValueError:
                pass

    try:
        async with async_session_factory() as session:
            state = await get_radar_state(session, viewer_user_id=viewer_user_id)

        # دریافت نام کاربری ربات برای دیپ‌لینک‌های درون مینی‌اپ
        bot_username = request.app.get("bot_username")
        if not bot_username:
            try:
                me = await bot.get_me()
                bot_username = me.username
                request.app["bot_username"] = bot_username
            except Exception:
                bot_username = ""

        state["bot_username"] = bot_username

        headers = _cors_headers()
        headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return web.json_response(state, headers=headers)

    except Exception as exc:
        logger.exception("Error generating radar state: %s", exc)
        return web.json_response(
            {"error": "Failed to generate radar state", "details": str(exc)},
            status=500,
            headers=_cors_headers(),
        )


def create_webapp(bot: Bot) -> web.Application:
    """ساخت و پیکربندی اپلیکیشن وب‌سرور aiohttp."""
    app = web.Application()
    app["bot"] = bot
    app["bot_username"] = ""

    # مسیرها
    app.router.add_get("/", handle_index)
    app.router.add_options("/api/radar-state", handle_options)
    app.router.add_get("/api/radar-state", handle_radar_state)

    # ارائه فایل‌های استاتیک در صورت نیاز
    if STATIC_DIR.exists():
        app.router.add_static("/static/", path=STATIC_DIR, name="static")

    return app


async def start_webapp(bot: Bot, port: int = 8080) -> web.AppRunner:
    """
    راه‌اندازی سرور وب سبک به صورت غیرمسدودکننده (non-blocking).
    خروجی AppRunner جهت آزادسازی و بستن در پایان کار برمی‌گردد.
    """
    app = create_webapp(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info("🛰 Live Radar WebApp started on http://0.0.0.0:%d", port)
    return runner
