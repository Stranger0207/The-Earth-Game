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
    "embargo": r"D:\PictureDB\Embargo",
    "military": r"D:\PictureDB\Military",
}

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _load_cache() -> dict[str, list[str]]:
    """خواندن file_idهای کش‌شده از File.md.

    سازگار با هر دو فرمت (v1.10.5):
    - `category | file_id`  (قدیمی)
    - `category | filename | file_id`  (جدید — برای ردیابی تنوع عکس‌ها)
    خروجی: نگاشت دسته → فهرست file_id.
    """
    cache: dict[str, list[str]] = {}
    if not MEDIA_FILE.exists():
        return cache
    for line in MEDIA_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        parts = [p.strip() for p in line[2:].split("|")]
        if len(parts) == 2:
            category, file_id = parts
        elif len(parts) == 3:
            category, _filename, file_id = parts
        else:
            continue
        cache.setdefault(category, []).append(file_id)
    return cache


def _cached_filenames(category: str) -> set[str]:
    """نام فایل‌هایی که برای یک دسته در File.md کش شده‌اند (فقط خطوط سه‌بخشی)."""
    names: set[str] = set()
    if not MEDIA_FILE.exists():
        return names
    for line in MEDIA_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        parts = [p.strip() for p in line[2:].split("|")]
        if len(parts) == 3 and parts[0] == category:
            names.add(parts[1])
    return names


def _append_cache(category: str, file_id: str, filename: str = "") -> None:
    """افزودن یک file_id جدید به File.md (در صورت دادن filename، فرمت سه‌بخشی)."""
    if not MEDIA_FILE.exists():
        MEDIA_FILE.write_text(
            "# File.md — کش عکس‌های اخبار (file_id تلگرام)\n\n"
            "هر خط: `- دسته | نام‌فایل | file_id` (یا قدیمی: `- دسته | file_id`). این فایل\n"
            "خودکار به‌روزرسانی می‌شود؛ پس از پرشدن، ربات بدون نیاز به فولدر D:\\\\PictureDB عکس می‌فرستد.\n\n",
            encoding="utf-8",
        )
    with MEDIA_FILE.open("a", encoding="utf-8") as f:
        if filename:
            f.write(f"- {category} | {filename} | {file_id}\n")
        else:
            f.write(f"- {category} | {file_id}\n")


def _find_local_file(category: str, stem: str) -> Path | None:
    """یافتن یک فایل عکس مشخص (با نام پایه مثل "1") در فولدر یک دسته."""
    folder = MEDIA_DIRS.get(category)
    if not folder or not os.path.isdir(folder):
        return None
    for name in os.listdir(folder):
        p = Path(name)
        if p.stem == stem and p.suffix.lower() in _IMAGE_EXTS:
            return Path(folder) / name
    return None


async def send_specific_photo(
    bot: Bot,
    chat_id: int,
    cache_key: str,
    category: str,
    stem: str,
    caption: str,
    reply_markup=None,
) -> bool:
    """
    یک عکس «مشخص» (نه تصادفی) را می‌فرستد — مثلاً عکس مخصوص یک نوع تحریم.
    file_id تحت کلید cache_key در File.md کش می‌شود تا دفعات بعد بدون فایل محلی ارسال شود.
    """
    cache = _load_cache()
    cached = cache.get(cache_key, [])
    photo = None
    upload = False
    if cached:
        photo = cached[0]
    else:
        local = _find_local_file(category, stem)
        if local is not None:
            photo = FSInputFile(str(local))
            upload = True

    if photo is None:
        try:
            await bot.send_message(chat_id, caption, reply_markup=reply_markup)
        except Exception as exc:  # noqa: BLE001
            logger.warning("send_specific_photo text fallback failed: %s", exc)
        return False

    try:
        sent = await bot.send_photo(
            chat_id, photo=photo, caption=caption, reply_markup=reply_markup
        )
        if upload and sent.photo:
            _append_cache(cache_key, sent.photo[-1].file_id)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to send specific photo (%s): %s", cache_key, exc)
        try:
            await bot.send_message(chat_id, caption, reply_markup=reply_markup)
        except Exception:  # noqa: BLE001
            pass
        return False


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
    cached_names = _cached_filenames(category)

    # v1.10.5: اگر فولدر محلی در دسترس است، فایل‌هایی که هنوز با «نام» کش نشده‌اند را
    # به‌صورت قطعی آپلود می‌کنیم تا کل عکس‌ها به‌مرور کش شوند؛ روی VPS (بدون فولدر)
    # از file_idهای کش‌شده به‌صورت تصادفی استفاده می‌شود (تنوع کامل).
    uncached = [p for p in local if p.name not in cached_names]
    photo = None
    upload_path: Path | None = None
    if uncached:
        upload_path = uncached[0]
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
        # اگر از فایل محلی آپلود کردیم، file_id حاصل را همراه نام فایل ذخیره کن
        if upload_path is not None and sent.photo:
            _append_cache(category, sent.photo[-1].file_id, upload_path.name)
        return True
    except Exception as exc:  # noqa: BLE001 — خطای ارسال نباید جریان بازی را قطع کند
        logger.warning("Failed to send photo news (%s): %s", category, exc)
        try:
            await bot.send_message(chat_id, caption, reply_markup=reply_markup)
        except Exception:  # noqa: BLE001
            pass
        return False
