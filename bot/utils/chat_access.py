"""ابزارهای کمکی تشخیص و کنترل دسترسی چت‌ها و گروه‌ها (v2.12.0).

مدیریت چت‌های داخلی پروژه و ارزیابی دسترسی کاربران در گروه‌ها و سوپرگروه‌ها.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram.types import User as TgUser

from ..config import get_settings

logger = logging.getLogger(__name__)

# شناسه ربات ادمین ناشناس تلگرام (Telegram GroupAnonymousBot)
TELEGRAM_ANONYMOUS_BOT_ID = 1087968824


def get_internal_chat_ids() -> set[int]:
    """
    استخراج شناسه‌ی تمامی چت‌های داخلی پروژه (گروه‌ها و کانال‌های مدیریتی، لاگ، خبری و...).
    مقادیر به صورت پویا از کانفیگ خوانده می‌شوند تا هر شناسه جدید خودکار اضافه شود.
    """
    settings = get_settings()
    chat_ids: set[int] = set()

    # صفات شناخته‌شده در Settings
    known_attrs = (
        "log_group_id",
        "sanction_bill_group_id",
        "role_econ_group_id",
        "role_attack_group_id",
        "role_sabotage_group_id",
        "role_security_group_id",
        "payment_group_id",
        "phone_group_id",
        "admin_log_channel_id",
        "tweet_channel_id",
        "news_military_channel_id",
        "news_diplomacy_channel_id",
        "news_economy_channel_id",
        "wto_channel_id",
        "force_join_chat_id",
    )

    for attr in known_attrs:
        val = getattr(settings, attr, None)
        if isinstance(val, int):
            chat_ids.add(val)
        elif isinstance(val, str) and val.lstrip("-").isdigit():
            chat_ids.add(int(val))

    # همچنین هر متغیر دیگری در Settings که به _group_id یا _channel_id ختم شود
    for attr, val in settings.__dict__.items():
        if (attr.endswith("_group_id") or attr.endswith("_channel_id")) and val is not None:
            if isinstance(val, int):
                chat_ids.add(val)
            elif isinstance(val, str) and val.lstrip("-").isdigit():
                chat_ids.add(int(val))

    return chat_ids


def is_internal_chat(chat_id: int | str | None) -> bool:
    """آیا این چت یک چت داخلی رسمی پروژه است؟"""
    if chat_id is None:
        return False
    try:
        cid_int = int(chat_id)
        return cid_int in get_internal_chat_ids()
    except (ValueError, TypeError):
        return False


def evaluate_group_access(
    chat: Any,
    from_user: TgUser | None,
    sender_chat: Any | None = None,
) -> bool:
    """
    ارزیابی دسترسی تعامل با ربات در یک چت:
    - چت‌های خصوصی (private) و کانال‌ها: مجاز (True).
    - گروه‌ها و سوپرگروه‌ها:
      * اگر sender_chat وجود داشته باشد (کانال یا ادمین ناشناس): مسدود (False).
      * اگر from_user وجود نداشته باشد یا ادمین ناشناس تلگرام باشد: مسدود (False).
      * اگر مالک بازی باشد: مجاز در تمام گروه‌ها (True).
      * اگر چت داخلی پروژه باشد: ادمین‌ها مجاز (True)، سایرین مسدود (False).
      * اگر گروه متفرقه باشد: فقط مالک مجاز است؛ بنابراین سایرین مسدود (False).
    """
    if chat is None:
        return False

    chat_type = getattr(chat, "type", "")
    if chat_type not in ("group", "supergroup"):
        return True

    # ارسال به عنوان کانال یا ادمین ناشناس
    if sender_chat is not None:
        return False

    if from_user is None:
        return False

    if from_user.id == TELEGRAM_ANONYMOUS_BOT_ID:
        return False

    settings = get_settings()

    # مالک در همه‌ی گروه‌ها دسترسی کامل دارد
    if settings.is_owner(from_user.id):
        return True

    # در چت‌های داخلی پروژه، ادمین‌ها مجاز هستند
    chat_id = getattr(chat, "id", None)
    if is_internal_chat(chat_id):
        return settings.is_admin(from_user.id)

    # در گروه‌های عادی/متفرقه، غیرمالک اجازه تعامل ندارد
    return False
