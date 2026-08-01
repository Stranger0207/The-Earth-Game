"""
انتشار اخبار نظامی (v1.10.6) — فیلتر کانال + زنجیره‌ی عکس.

دو مسئولیت:

۱. **فیلتر کانال:** طبق خواسته‌ی آپدیت، هر خبری به کانال نظامی نمی‌رود.
   فقط عملیات کشورهای مهم (VIP) با شدت بالا در کانال منتشر می‌شود؛
   بقیه فقط به پیوی طرفین و گروه لاگ می‌روند.

۲. **زنجیره‌ی عکس:** Gemini عکس اختصاصی می‌سازد → اگر نشد، بانک عکس محلی →
   اگر آن هم نبود، فقط متن. عکس یک‌بار ساخته و با file_id بین چت‌ها
   بازاستفاده می‌شود (نه چند بار تولید).
"""

from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from ...config import get_settings
from ...constants import (
    NEWS_CHANNEL_MIN_INTENSITY,
    NEWS_CHANNEL_NONVIP_MIN_INTENSITY,
)
from ..ai import gemini_image
from ..media import send_photo_news
from . import imagery

logger = logging.getLogger(__name__)
settings = get_settings()


def should_publish_to_channel(
    intensity: int, *, attacker_is_vip: bool, defender_is_vip: bool
) -> bool:
    """
    آیا این عملیات شایسته‌ی انتشار در کانال اخبار نظامی است؟

    قاعده (تصمیم آپدیت v1.10.6): «فقط اخبار خیلی مهم کشورهای مهم».
    - اگر یکی از طرفین VIP باشد: شدت ≥ ۵
    - اگر هیچ‌کدام VIP نباشند: شدت ≥ ۹ (عملیات استثنائاً بزرگ)
    """
    if attacker_is_vip or defender_is_vip:
        return intensity >= NEWS_CHANNEL_MIN_INTENSITY
    return intensity >= NEWS_CHANNEL_NONVIP_MIN_INTENSITY


async def _send_photo(
    bot: Bot, chat_id: int, caption: str, photo: str | FSInputFile
) -> tuple[bool, str | None]:
    """
    ارسال یک عکس با کپشن.
    خروجی: (ارسال موفق بود؟، file_id برای بازاستفاده)
    """
    try:
        sent = await bot.send_photo(chat_id, photo=photo, caption=caption)
    except Exception as exc:  # noqa: BLE001 — خطای ارسال نباید جریان بازی را بشکند
        logger.warning("Failed to send news photo to %s: %s", chat_id, exc)
        return False, None

    file_id = sent.photo[-1].file_id if sent.photo else None
    return True, file_id


async def deliver_news(
    bot: Bot,
    *,
    text: str,
    facts: dict,
    phase_kind: str,
    chat_ids: list[int],
) -> None:
    """
    یک خبر را با عکس به چند چت می‌فرستد.

    عکس فقط **یک‌بار** تولید می‌شود؛ برای چت‌های بعدی از file_id تلگرام
    استفاده می‌شود تا نه هزینه‌ی اضافی بدهیم نه ترافیک.

    این تابع هیچ‌وقت استثنا پرتاب نمی‌کند.
    """
    targets = [cid for cid in dict.fromkeys(chat_ids) if cid]
    if not targets:
        return

    media_category = imagery.media_category_for(facts)

    # ---------- تلاش برای ساخت عکس اختصاصی با Gemini ----------
    generated: Path | None = None
    if gemini_image.is_enabled():
        try:
            generated = await gemini_image.generate_image(
                imagery.build_image_prompt(facts, phase_kind),
                slug=imagery.image_slug(facts, phase_kind),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gemini image step failed, using local bank: %s", exc)
            generated = None

    cached_file_id: str | None = None

    for chat_id in targets:
        # ۱) اگر file_id داریم (عکس قبلاً آپلود شده) — ارزان‌ترین راه
        if cached_file_id:
            ok, _ = await _send_photo(bot, chat_id, text, cached_file_id)
            if ok:
                continue

        # ۲) عکس تولیدشده‌ی Gemini (اولین ارسال، آپلود فایل)
        elif generated is not None and generated.exists():
            ok, file_id = await _send_photo(bot, chat_id, text, FSInputFile(str(generated)))
            if ok:
                cached_file_id = file_id
                continue

        # ۳) پشتیبان: بانک عکس محلی (خودش در نبود عکس به متن برمی‌گردد)
        await send_photo_news(bot, chat_id, media_category, text)


async def deliver_operation_news(
    bot: Bot,
    *,
    text: str,
    facts: dict,
    phase_kind: str,
    intensity: int,
    attacker_is_vip: bool,
    defender_is_vip: bool,
    owner_chat_ids: list[int],
) -> bool:
    """
    انتشار خبر یک فاز عملیات با اعمال فیلتر کانال.

    - کانال نظامی: فقط اگر شرط VIP + شدت برقرار باشد
    - گروه لاگ: همیشه (ممیزی کامل)
    - پیوی طرفین: همیشه

    خروجی: آیا خبر در کانال نظامی منتشر شد؟
    """
    to_channel = should_publish_to_channel(
        intensity, attacker_is_vip=attacker_is_vip, defender_is_vip=defender_is_vip
    )

    chat_ids: list[int] = []
    if to_channel and settings.news_military_channel_id:
        chat_ids.append(settings.news_military_channel_id)
    if settings.log_group_id:
        chat_ids.append(settings.log_group_id)
    chat_ids.extend(owner_chat_ids)

    await deliver_news(bot, text=text, facts=facts, phase_kind=phase_kind, chat_ids=chat_ids)
    return to_channel
