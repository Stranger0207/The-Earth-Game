"""
اسکریپت پیش‌کش‌کردن عکس‌های اخبار (v1.9).

این اسکریپت را **یک‌بار روی همان سیستمی که فولدرهای D:\\PictureDB موجودند**
(ویندوز خودت) اجرا کن. همه‌ی عکس‌ها را به تلگرام آپلود می‌کند، file_id هرکدام را
می‌گیرد و در File.md ذخیره می‌کند. سپس File.md را commit و روی VPS pull کن تا
ربات بدون نیاز به فولدرهای محلی، عکس‌ها را (به‌خصوص عکس‌های تحریم) ضمیمه کند.

اجرا:
    PYTHONUTF8=1 python -m scripts.cache_media
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from aiogram.types import FSInputFile

from bot.config import get_settings
from bot.enums import SANCTION_FA, SanctionType
from bot.loader import bot
from bot.services import media

# نگاشت نوع تحریم به شماره‌ی عکس در فولدر Embargo (هماهنگ با handlers/diplomacy.py)
SANCTION_IMAGE_STEM: dict[SanctionType, str] = {
    SanctionType.OIL_TRADE: "1",
    SanctionType.GAS_TRADE: "2",
    SanctionType.STEEL_TRADE: "3",
    SanctionType.MINERAL_TRADE: "4",
    SanctionType.FINANCIAL: "5",
    SanctionType.ARMS: "6",
    SanctionType.TRANSPORT: "7",
    SanctionType.DIPLOMATIC: "8",
}


async def _upload(chat_id: int, path: Path, cache_key: str, filename: str = "") -> bool:
    """یک عکس را آپلود و file_id آن را زیر cache_key در File.md ذخیره می‌کند.

    اگر filename داده شود، به‌صورت سه‌بخشی ذخیره می‌شود تا تنوع عکس‌ها قابل‌ردیابی باشد.
    """
    try:
        sent = await bot.send_photo(chat_id, photo=FSInputFile(str(path)), caption=cache_key)
        if sent.photo:
            media._append_cache(cache_key, sent.photo[-1].file_id, filename)
            print(f"  ✅ {cache_key} ← {path.name}")
            return True
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️ خطا در {cache_key} ({path.name}): {exc}")
    return False


async def main() -> None:
    settings = get_settings()
    # مقصد آپلود: گروه لاگ یا اولین مالک
    chat_id = settings.log_group_id or (settings.owner_ids[0] if settings.owner_ids else None)
    if chat_id is None:
        print("❌ نه گروه لاگ تنظیم شده و نه OWNER_IDS. یکی را در .env بگذار.")
        return

    cache = media._load_cache()

    # --- عکس‌های تحریم (مخصوص هر نوع) ---
    print("📤 آپلود عکس‌های تحریم (embargo)...")
    embargo_dir = media.MEDIA_DIRS.get("embargo")
    for stype, stem in SANCTION_IMAGE_STEM.items():
        key = f"embargo:{stype.value}"
        if cache.get(key):
            print(f"  ⏭ {key} از قبل کش شده — رد شد")
            continue
        path = media._find_local_file("embargo", stem)
        if path is None:
            print(f"  ⚠️ عکس {stem} برای {SANCTION_FA[stype]} در {embargo_dir} پیدا نشد")
            continue
        await _upload(chat_id, path, key)

    # --- دسته‌های تصادفی (هر عکسِ هنوز کش‌نشده «بر اساس نام فایل» آپلود می‌شود) ---
    # v1.10.5: به‌جای برش ناپایدارِ local[already:]، با نام فایل تشخیص می‌دهیم چه عکسی
    # هنوز کش نشده تا همه‌ی عکس‌ها (به‌ویژه WTO/Trump) قطعی و کامل کش شوند.
    for category in ("wto", "trump", "diplomacy_travel", "meeting"):
        local = media._local_images(category)
        cached_names = media._cached_filenames(category)
        pending = [p for p in local if p.name not in cached_names]
        if not pending:
            print(f"⏭ دسته‌ی {category}: همه‌ی {len(local)} عکس از قبل کش شده‌اند")
            continue
        print(f"📤 دسته‌ی {category}: آپلود {len(pending)} عکس کش‌نشده...")
        for path in pending:
            await _upload(chat_id, path, category, path.name)

    await bot.session.close()
    print("\n✅ تمام شد. حالا File.md را commit و روی VPS pull کن.")


if __name__ == "__main__":
    if hasattr(os, "name"):
        pass
    asyncio.run(main())
