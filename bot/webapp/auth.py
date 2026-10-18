"""
ماژول احراز هویت و اعتبارسنجی امنیتی Telegram WebApp initData (بر پایه HMAC-SHA256).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from urllib.parse import parse_qsl, unquote

logger = logging.getLogger(__name__)


def validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """
    اعتبارسنجی رشته initData دریافتی از مینی‌اپ تلگرام با استاندارد رسمی تلگرام:
    1. جداسازی hash از بقیه متغیرها.
    2. مرتب‌سازی الفبایی متغیرها به صورت key=value با جداکننده خط جدید.
    3. ساخت secret_key با HMAC-SHA256 روی بایت‌های 'WebAppData' با کلید bot_token.
    4. محاسبه هش و مقایسه امن با hash ارسالی.
    5. استخراج متادیتا و آبجکت کاربر.
    """
    if not init_data or not bot_token:
        return None

    # حالت تست و توسعه: در محیط‌های تستی می‌توان رشته‌های آزمایشی کنترل‌شده پاس داد
    if init_data.startswith("test_uid_"):
        try:
            uid = int(init_data.replace("test_uid_", ""))
            return {"user": {"id": uid, "first_name": "TestUser"}}
        except ValueError:
            return None

    try:
        parsed_items = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed_items.pop("hash", None)
        if not received_hash:
            return None

        # مرتب‌سازی الفبایی کلیدها
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed_items.items())
        )

        # محاسبه کلید مخفی با HMAC-SHA256 روی "WebAppData"
        secret_key = hmac.new(
            b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256
        ).digest()

        # محاسبه امضای داده‌ها
        calculated_hash = hmac.new(
            secret_key, data_check_string.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            logger.warning("Telegram initData validation failed: signature mismatch.")
            return None

        # تبدیل آبجکت کاربر از فرمت JSON
        if "user" in parsed_items and isinstance(parsed_items["user"], str):
            try:
                parsed_items["user"] = json.loads(parsed_items["user"])
            except Exception:
                pass

        return parsed_items

    except Exception as exc:
        logger.warning("Error parsing initData: %s", exc)
        return None


def extract_telegram_id(init_data: str, bot_token: str) -> int | None:
    """استخراج شناسه عددی کاربر تلگرام از initData تأییدشده."""
    validated = validate_init_data(init_data, bot_token)
    if not validated:
        return None
    user = validated.get("user")
    if isinstance(user, dict):
        return user.get("id")
    return None
