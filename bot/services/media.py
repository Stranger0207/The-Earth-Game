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
    # عکس‌های برنامه‌ی هسته‌ای (v1.10.4) — کشف برنامه، آزمایش هسته‌ای
    "nuclear": r"D:\PictureDB\Nuclear",
    # اخبار کانال‌ها (عمومی)
    "news_military": r"D:\PictureDB\News\military",
    "news_diplomacy": r"D:\PictureDB\News\diplomacy",
    "news_economy": r"D:\PictureDB\News\economy",
    # عکس‌های منوهای اصلی و زیرمنوها (سیستم تصویری جامع UI)
    "ui_main": r"D:\PictureDB\UI\main",
    "ui_economy": r"D:\PictureDB\UI\economy",
    "ui_diplomacy": r"D:\PictureDB\UI\diplomacy",
    "ui_military": r"D:\PictureDB\UI\military",
    "ui_advisor": r"D:\PictureDB\UI\advisor",
    "ui_status": r"D:\PictureDB\UI\status",
    "ui_bank": r"D:\PictureDB\UI\bank",
    # زیرمنوهای افزوده شده (پوشش ۸۰٪+ منوها)
    "ui_governance": r"D:\PictureDB\UI\governance",
    "ui_un": r"D:\PictureDB\UI\un",
    "ui_industry": r"D:\PictureDB\UI\industry",
    "ui_factories": r"D:\PictureDB\UI\factories",
    "ui_bases": r"D:\PictureDB\UI\bases",
    "ui_satellite": r"D:\PictureDB\UI\satellite",
    "ui_nuclear": r"D:\PictureDB\UI\nuclear",
    "ui_deployment": r"D:\PictureDB\UI\deployment",
    "ui_commanders": r"D:\PictureDB\UI\commanders",
    "ui_facilities": r"D:\PictureDB\UI\facilities",
    "ui_investment": r"D:\PictureDB\UI\investment",
    "ui_straits": r"D:\PictureDB\UI\straits",
    "ui_auction": r"D:\PictureDB\UI\auction",
    "ui_letters": r"D:\PictureDB\UI\letters",
    "ui_alliances": r"D:\PictureDB\UI\alliances",
    "ui_sanctions": r"D:\PictureDB\UI\sanctions",
    "ui_contracts": r"D:\PictureDB\UI\contracts",
    "ui_twitter": r"D:\PictureDB\UI\twitter",
    "ui_security_roles": r"D:\PictureDB\UI\security_roles",
    "ui_military_roles": r"D:\PictureDB\UI\military_roles",
}

# دسته‌های UI (منوهای اصلی و فرعی) — برای پیش‌کش‌کردن در scripts/cache_media.py
UI_CATEGORIES: tuple[str, ...] = (
    "ui_main",
    "ui_economy",
    "ui_diplomacy",
    "ui_military",
    "ui_advisor",
    "ui_status",
    "ui_bank",
    "ui_governance",
    "ui_un",
    "ui_industry",
    "ui_factories",
    "ui_bases",
    "ui_satellite",
    "ui_nuclear",
    "ui_deployment",
    "ui_commanders",
    "ui_facilities",
    "ui_investment",
    "ui_straits",
    "ui_auction",
    "ui_letters",
    "ui_alliances",
    "ui_sanctions",
    "ui_contracts",
    "ui_twitter",
    "ui_security_roles",
    "ui_military_roles",
)

# نگاشت فالبک فقط برای اخبار کانال‌ها (نه منوهای کاربری تا تصاویر منوها با یکدیگر تداخل نکنند)
CATEGORY_FALLBACKS: dict[str, str] = {
    # اخبار کانال‌ها
    "news_military": "military",
    "news_diplomacy": "diplomacy_travel",
    "news_economy": "ui_economy",
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


def _resolve_random_photo(category: str, allow_fallback: bool = True) -> tuple[object | None, Path | None]:
    """یک عکس تصادفی برای یک دسته انتخاب می‌کند (بدون ارسال).

    خروجی: (photo, upload_path)
    - photo: یک file_id کش‌شده (str) یا FSInputFile برای آپلود، یا None اگر عکسی نبود.
    - upload_path: اگر از فایل محلی آپلود می‌شود، مسیر فایل (برای کش‌کردن file_id پس از ارسال).

    اولویت‌ها (v1.10.5): ابتدا فایل‌های محلیِ هنوز کش‌نشده (تا به‌مرور همه کش شوند)،
    سپس file_idهای کش‌شده‌ی تصادفی (روی VPS بدون فولدر)، در نهایت هر فایل محلی.
    در صورت نبود عکس، به دسته‌ی مادر fallback می‌کند.
    """
    cache = _load_cache()
    cached_ids = cache.get(category, [])
    local = _local_images(category)
    cached_names = _cached_filenames(category)

    uncached = [p for p in local if p.name not in cached_names]
    if uncached:
        path = uncached[0]
        return FSInputFile(str(path)), path
    if cached_ids:
        return random.choice(cached_ids), None
    if local:
        path = random.choice(local)
        return FSInputFile(str(path)), path

    # در صورت نبود عکس، بررسی فالبک به دسته‌ی مادر
    if allow_fallback and category in CATEGORY_FALLBACKS:
        parent_cat = CATEGORY_FALLBACKS[category]
        return _resolve_random_photo(parent_cat, allow_fallback=False)

    return None, None


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
    photo, upload_path = _resolve_random_photo(category)

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
