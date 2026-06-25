"""
سرویس مدیا: انتخاب عکس تصادفی برای اخبار و کش‌کردن file_id تلگرام.

ایده: اولین بار که یک عکس از فولدر محلی (D:\\PictureDB\\...) ارسال می‌شود،
تلگرام یک file_id برمی‌گرداند که برای همیشه معتبر است. این file_id در فایل
File.md ذخیره می‌شود تا دفعات بعد بدون نیاز به روشن‌بودن سیستم محلی، عکس از
روی همان file_id ارسال شود.
"""

from __future__ import annotations

import logging
import os
import random
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

logger = logging.getLogger(__name__)

# ریشه‌ی پروژه (سه پوشه بالاتر از این فایل: bot/services/media.py)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
# فایل ذخیره‌ی file_idها (کش دائمی عکس‌ها)
MEDIA_FILE = _PROJECT_ROOT / "File.md"

# نگاشت دسته‌ی عکس به فولدر محلی منبع
MEDIA_DIRS: dict[str, str] = {
    "wto": r"D:\PictureDB\WTO",
    "trump": r"D:\PictureDB\Trump",
    "diplomacy_travel": r"D:\PictureDB\Diplomaci",
    "meeting": r"D:\PictureDB\Didar",
}

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _load_cache() -> dict[str, list[str]]:
    """خواندن file_idهای کش‌شده از File.md (هر خط: `category | file_id`)."""
    cache: dict[str, list[str]] = {}
    if not MEDIA_FILE.exists():
        return cache
    for line in MEDIA_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        parts = [p.strip() for p in line[2:].split("|")]
        if len(parts) != 2:
            continue
        category, file_id = parts
        cache.setdefault(category, []).append(file_id)
    return cache


def _append_cache(category: str, file_id: str) -> None:
    """افزودن یک file_id جدید به File.md."""
    if not MEDIA_FILE.exists():
        MEDIA_FILE.write_text(
            "# File.md — کش عکس‌های اخبار (file_id تلگرام)\n\n"
            "هر خط: `- دسته | file_id`. این فایل خودکار به‌روزرسانی می‌شود؛\n"
            "پس از پرشدن، ربات بدون نیاز به فولدر D:\\\\PictureDB عکس می‌فرستد.\n\n",
            encoding="utf-8",
        )
    with MEDIA_FILE.open("a", encoding="utf-8") as f:
        f.write(f"- {category} | {file_id}\n")


def _local_images(category: str) -> list[Path]:
    """فهرست عکس‌های محلی یک دسته (در صورت در دسترس بودن فولدر)."""
    folder = MEDIA_DIRS.get(category)
    if not folder or not os.path.isdir(folder):
        return []
    return [
        Path(folder) / name
        for name in os.listdir(folder)
        if Path(name).suffix.lower() in _IMAGE_EXTS
    ]


async def send_photo_news(
    bot: Bot,
    chat_id: int,
    category: str,
    caption: str,
    reply_markup=None,
) -> bool:
    """
    یک عکس تصادفی از دسته‌ی موردنظر به همراه کپشن به chat_id می‌فرستد.
    اولویت با file_idهای کش‌شده (بدون نیاز به سیستم محلی) است؛ در غیر این صورت
    از فولدر محلی آپلود و file_id حاصل در File.md ذخیره می‌شود.
    در صورت نبود عکس، فقط متن ارسال می‌شود. خروجی: آیا عکس فرستاده شد؟
    """
    cache = _load_cache()
    cached_ids = cache.get(category, [])
    local = _local_images(category)

    # اگر هنوز همه‌ی عکس‌های محلی کش نشده‌اند، یکی از کش‌نشده‌ها را آپلود می‌کنیم
    # تا کش به‌مرور کامل شود؛ در غیر این صورت از file_id کش‌شده استفاده می‌شود.
    photo = None
    upload_path: Path | None = None
    if local and len(cached_ids) < len(local):
        upload_path = random.choice(local)
        photo = FSInputFile(str(upload_path))
    elif cached_ids:
        photo = random.choice(cached_ids)
    elif local:
        upload_path = random.choice(local)
        photo = FSInputFile(str(upload_path))

    if photo is None:
        # هیچ عکسی در دسترس نیست → فقط متن
        try:
            await bot.send_message(chat_id, caption, reply_markup=reply_markup)
        except Exception as exc:  # noqa: BLE001
            logger.warning("send_photo_news text fallback failed: %s", exc)
        return False

    try:
        sent = await bot.send_photo(
            chat_id, photo=photo, caption=caption, reply_markup=reply_markup
        )
        # اگر از فایل محلی آپلود کردیم، file_id حاصل را برای دفعات بعد ذخیره کن
        if upload_path is not None and sent.photo:
            _append_cache(category, sent.photo[-1].file_id)
        return True
    except Exception as exc:  # noqa: BLE001 — خطای ارسال نباید جریان بازی را قطع کند
        logger.warning("Failed to send photo news (%s): %s", category, exc)
        try:
            await bot.send_message(chat_id, caption, reply_markup=reply_markup)
        except Exception:  # noqa: BLE001
            pass
        return False
