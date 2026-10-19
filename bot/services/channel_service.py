"""
سرویس بررسی عضویت اجباری در کانال (Forced Channel Subscription).
"""

from __future__ import annotations

import logging
from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..utils.ui import STYLE_MAIN, STYLE_OK

logger = logging.getLogger(__name__)

FORCE_JOIN_TEXT = (
    "📢 <b>عضویت اجباری در کانال بازی</b>\n\n"
    "برای استفاده از ربات و ورود به بازی، ابتدا باید در کانال رسمی ما عضو شوید. "
    "پس از عضویت، روی دکمه <b>«✅ عضو شدم»</b> کلیک کنید:"
)


def force_join_kb(invite_link: str | None) -> InlineKeyboardMarkup:
    """کیبورد دو دکمه‌ای ورود به کانال و تأیید عضویت."""
    url = invite_link or "https://t.me"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📥 ورود به کانال",
                    url=url,
                    style=STYLE_MAIN,
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ عضو شدم",
                    callback_data="check_force_join",
                    style=STYLE_OK,
                )
            ],
        ]
    )


async def check_user_channel_subscription(
    bot: Bot, chat_id: str | int, user_id: int
) -> bool:
    """
    بررسی اینکه آیا کاربر در کانال مورد نظر عضو است یا خیر.
    وضعیت‌های مجاز: member, administrator, creator, restricted.
    """
    try:
        target_chat_id: int | str = (
            int(chat_id) if str(chat_id).lstrip("-").isdigit() else str(chat_id)
        )
        member = await bot.get_chat_member(chat_id=target_chat_id, user_id=user_id)
        status = getattr(member, "status", None)
        status_val = status.value if hasattr(status, "value") else str(status)
        return status_val.lower() in ("member", "administrator", "creator", "restricted")
    except Exception as exc:
        logger.warning(
            "Error checking channel subscription for user %s in chat %s: %s",
            user_id,
            chat_id,
            exc,
        )
        return False
