"""
تولید عکس خبری با Google Gemini (v1.10.6).

هر خبر مهم نظامی یک عکس اختصاصی می‌گیرد که همان لحظه ساخته می‌شود — پس
عکس‌ها هیچ‌وقت تکراری نیستند (برخلاف بانک عکس ثابت).

زنجیره‌ی پشتیبان (هیچ‌وقت نمی‌شکند):
    Gemini → بانک عکس محلی (services/media) → فقط متن

نکته‌ی مهم: اگر `GEMINI_API_KEY` در `.env` نباشد، این ماژول بی‌سروصدا
غیرفعال می‌شود و بازی دقیقاً مثل قبل با عکس‌های محلی کار می‌کند.
"""

from __future__ import annotations

import base64
import binascii
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx

from ...config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# پوشه‌ی ذخیره‌ی عکس‌های تولیدشده
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
GENERATED_DIR = _PROJECT_ROOT / "media_cache" / "generated"

# شمارنده‌ی مصرف روزانه (در حافظه؛ با ریست ربات صفر می‌شود)
_usage_date: str = ""
_usage_count: int = 0


def is_enabled() -> bool:
    """آیا تولید عکس با Gemini فعال است؟ (کلید تنظیم شده باشد)"""
    return bool(settings.gemini_api_key.strip())


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def remaining_quota() -> int:
    """سهمیه‌ی باقی‌مانده‌ی تولید عکس امروز."""
    global _usage_date, _usage_count
    today = _today_key()
    if _usage_date != today:
        _usage_date, _usage_count = today, 0
    return max(0, settings.gemini_image_daily_limit - _usage_count)


def _consume_quota() -> None:
    """ثبت مصرف یک عکس از سهمیه‌ی روزانه."""
    global _usage_date, _usage_count
    today = _today_key()
    if _usage_date != today:
        _usage_date, _usage_count = today, 0
    _usage_count += 1


def _extract_image_bytes(payload: dict) -> bytes | None:
    """
    داده‌ی عکس را از پاسخ Gemini بیرون می‌کشد.
    ساختار پاسخ: candidates[].content.parts[].inlineData.data (base64)
    """
    for candidate in payload.get("candidates", []) or []:
        parts = (candidate.get("content") or {}).get("parts", []) or []
        for part in parts:
            # هر دو نام‌گذاری camelCase و snake_case پشتیبانی می‌شود
            inline = part.get("inlineData") or part.get("inline_data")
            if not inline:
                continue
            data = inline.get("data")
            if not data:
                continue
            try:
                return base64.b64decode(data)
            except (binascii.Error, ValueError) as exc:
                logger.warning("Gemini returned undecodable image data: %s", exc)
    return None


async def generate_image(prompt: str, *, slug: str = "news") -> Path | None:
    """
    یک عکس خبری می‌سازد و مسیر فایل را برمی‌گرداند.

    خروجی None یعنی «عکس ساخته نشد» — که خطا محسوب نمی‌شود؛ فراخوان باید
    به بانک عکس محلی برگردد.

    این تابع هیچ‌وقت استثنا پرتاب نمی‌کند.
    """
    if not is_enabled():
        return None

    if remaining_quota() <= 0:
        logger.info("Gemini daily image quota exhausted; falling back to local media.")
        return None

    url = (
        f"{settings.gemini_base_url.rstrip('/')}"
        f"/models/{settings.gemini_image_model}:generateContent"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }

    try:
        async with httpx.AsyncClient(timeout=settings.gemini_timeout_seconds) as client:
            response = await client.post(
                url,
                json=body,
                headers={
                    "x-goog-api-key": settings.gemini_api_key,
                    "Content-Type": "application/json",
                },
            )

        if response.status_code != 200:
            logger.warning(
                "Gemini image request failed (%s): %s",
                response.status_code,
                response.text[:300],
            )
            return None

        image_bytes = _extract_image_bytes(response.json())
        if not image_bytes:
            logger.warning("Gemini response contained no image data.")
            return None

        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        path = GENERATED_DIR / f"{slug}-{stamp}.png"
        path.write_bytes(image_bytes)
        _consume_quota()
        logger.info("Gemini image generated: %s (quota left: %d)", path.name, remaining_quota())
        return path

    except Exception as exc:  # noqa: BLE001 — تولید عکس هرگز نباید بازی را بشکند
        logger.warning("Gemini image generation failed: %s", exc)
        return None


def cleanup_old_images(keep_hours: int = 48) -> int:
    """
    عکس‌های تولیدشده‌ی قدیمی را پاک می‌کند (پس از ارسال به تلگرام،
    file_id کش می‌شود و فایل محلی دیگر لازم نیست).

    خروجی: تعداد فایل‌های حذف‌شده.
    """
    if not GENERATED_DIR.exists():
        return 0

    cutoff = datetime.now(timezone.utc).timestamp() - keep_hours * 3600
    removed = 0
    for file in GENERATED_DIR.glob("*.png"):
        try:
            if file.stat().st_mtime < cutoff:
                file.unlink()
                removed += 1
        except OSError as exc:
            logger.debug("Could not remove old generated image %s: %s", file, exc)
    return removed
