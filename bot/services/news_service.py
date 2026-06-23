"""
سرویس اخبار: ارسال خبر به کانال مناسب (نظامی/دیپلماسی/اقتصاد/WTO).
لحن رسمی و خبری؛ فقط خلاصه‌ی کلی (اطلاعات حساس فقط داخل ربات).
"""

from __future__ import annotations

import logging

from aiogram import Bot

from ..config import get_settings
from ..enums import NewsCategory

logger = logging.getLogger(__name__)
settings = get_settings()

# نگاشت دسته‌ی خبر به آی‌دی کانال مربوط
_CATEGORY_CHANNEL = {
    NewsCategory.MILITARY: settings.news_military_channel_id,
    NewsCategory.DIPLOMACY: settings.news_diplomacy_channel_id,
    NewsCategory.ECONOMY: settings.news_economy_channel_id,
    NewsCategory.WTO: settings.wto_channel_id,
}

# ایموجی سرتیتر هر دسته
_CATEGORY_HEADER = {
    NewsCategory.MILITARY: "📡 <b>اخبار نظامی</b>",
    NewsCategory.DIPLOMACY: "🕊 <b>اخبار دیپلماسی</b>",
    NewsCategory.ECONOMY: "📈 <b>اخبار اقتصادی</b>",
    NewsCategory.WTO: "🚢 <b>سازمان انتقالات جهانی (WTO)</b>",
}


async def publish_news(
    bot: Bot, category: NewsCategory, text: str
) -> None:
    """ارسال یک خبر به کانال دسته‌ی موردنظر. در صورت نبود کانال، فقط لاگ می‌شود."""
    channel_id = _CATEGORY_CHANNEL.get(category)
    header = _CATEGORY_HEADER.get(category, "📰 خبر")
    message = f"{header}\n\n{text}"

    if channel_id is None:
        logger.info("News channel not configured for %s. News: %s", category, text)
        return

    try:
        await bot.send_message(channel_id, message)
    except Exception as exc:  # noqa: BLE001 — خطای ارسال نباید جریان بازی را قطع کند
        logger.warning("Failed to publish news to %s: %s", channel_id, exc)


async def send_log(bot: Bot, text: str, reply_markup=None) -> None:
    """ارسال یک پیام به گروه لاگ مدیران (مثلاً لاگ تماس یا درخواست خرابکاری)."""
    if settings.log_group_id is None:
        logger.info("Log group not configured. Log: %s", text)
        return
    try:
        await bot.send_message(settings.log_group_id, text, reply_markup=reply_markup)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to send log: %s", exc)
