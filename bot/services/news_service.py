"""
سرویس اخبار: ارسال خبر به کانال مناسب (نظامی/دیپلماسی/اقتصاد/WTO).
لحن رسمی و خبری؛ فقط خلاصه‌ی کلی (اطلاعات حساس فقط داخل ربات).
"""

from __future__ import annotations

import logging

from aiogram import Bot

from ..config import get_settings
from ..enums import AdminGroupType, NewsCategory
from aiogram.types import Message

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


def get_admin_group_id(group_type: AdminGroupType) -> int | None:
    """دریافت آی‌دی گروه تلگرام بر اساس نوع گروه مدیریتی (آپدیت شماره ۱۰)."""
    st = get_settings()
    mapping = {
        AdminGroupType.SANCTION_BILL: st.sanction_bill_group_id,
        AdminGroupType.MAIN_LOG: st.log_group_id,
        AdminGroupType.ROLE_ECON: st.role_econ_group_id,
        AdminGroupType.ROLE_ATTACK: st.role_attack_group_id,
        AdminGroupType.ROLE_SABOTAGE: st.role_sabotage_group_id,
        AdminGroupType.ROLE_SECURITY: st.role_security_group_id,
        AdminGroupType.PAYMENT: st.payment_group_id,
    }
    gid = mapping.get(group_type)
    if gid is None:
        return st.log_group_id
    return gid


async def publish_news(
    bot: Bot, category: NewsCategory, text: str
) -> Message | None:
    """ارسال یک خبر به کانال دسته‌ی موردنظر. در صورت نبود کانال، فقط لاگ می‌شود."""
    channel_id = _CATEGORY_CHANNEL.get(category)
    header = _CATEGORY_HEADER.get(category, "📰 خبر")
    message = f"{header}\n\n{text}"

    if channel_id is None:
        logger.info("News channel not configured for %s. News: %s", category, text)
        return None

    try:
        return await bot.send_message(channel_id, message)
    except Exception as exc:  # noqa: BLE001 — خطای ارسال نباید جریان بازی را قطع کند
        logger.warning("Failed to publish news to %s: %s", channel_id, exc)
        return None


async def send_to_admin_group(
    bot: Bot, group_type: AdminGroupType, text: str, reply_markup=None, **kwargs
) -> Message | None:
    """ارسال پیام متنی به یکی از گروه‌های ۷گانه مدیریتی."""
    gid = get_admin_group_id(group_type)
    if gid is None:
        logger.info("Admin group %s not configured. Text: %s", group_type, text)
        return None
    try:
        return await bot.send_message(gid, text, reply_markup=reply_markup, **kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to send message to admin group %s (%s): %s", group_type, gid, exc)
        return None


async def send_photo_to_admin_group(
    bot: Bot, group_type: AdminGroupType, photo, caption: str = "", reply_markup=None, **kwargs
) -> Message | None:
    """ارسال تصویر به همراه کپشن به یکی از گروه‌های ۷گانه مدیریتی."""
    gid = get_admin_group_id(group_type)
    if gid is None:
        logger.info("Admin group %s not configured. Photo caption: %s", group_type, caption)
        return None
    try:
        return await bot.send_photo(
            gid,
            photo=photo,
            caption=caption,
            reply_markup=reply_markup,
            **kwargs,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to send photo to admin group %s (%s): %s", group_type, gid, exc)
        return None


async def send_log(bot: Bot, text: str, reply_markup=None, **kwargs) -> Message | None:
    """ارسال یک پیام به گروه لاگ مدیران (گروه ۲: لاگ اصلی)."""
    return await send_to_admin_group(bot, AdminGroupType.MAIN_LOG, text, reply_markup=reply_markup, **kwargs)


async def send_log_photo(
    bot: Bot, photo, caption: str = "", reply_markup=None, **kwargs
) -> Message | None:
    """ارسال یک تصویر به همراه کپشن به گروه لاگ مدیران (گروه ۲: لاگ اصلی)."""
    return await send_photo_to_admin_group(
        bot, AdminGroupType.MAIN_LOG, photo=photo, caption=caption, reply_markup=reply_markup, **kwargs
    )


async def send_log_document(
    bot: Bot, document, caption: str = "", reply_markup=None, **kwargs
) -> Message | None:
    """ارسال یک فایل سند به همراه کپشن به گروه لاگ مدیران."""
    gid = get_admin_group_id(AdminGroupType.MAIN_LOG)
    if gid is None:
        logger.info("Log group not configured. Document log: %s", caption)
        return None
    try:
        return await bot.send_document(
            gid,
            document=document,
            caption=caption,
            reply_markup=reply_markup,
            **kwargs,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to send log document: %s", exc)
        return None



