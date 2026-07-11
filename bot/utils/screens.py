"""
هلپرهای ناوبری تصویری (سیستم تصویری منوهای اصلی).

چالش: تلگرام اجازه نمی‌دهد پیام عکس‌دار را با edit_text به متن ساده تبدیل کنی
(و برعکس). بنابراین در مرز عکس↔متن باید پیام قبلی حذف و پیام تازه ارسال شود.

دو هلپر:
- show_menu: یک «منوی اصلی» را به‌صورت عکس + کپشن + دکمه رندر می‌کند (با fallback به متن).
- safe_edit: جایگزین امنِ call.message.edit_text برای زیرصفحه‌ها؛ روی پیام متنی
  دقیقاً مثل edit_text عمل می‌کند، روی پیام عکس‌دار حذف+ارسال متن می‌کند.
"""

from __future__ import annotations

import logging

from aiogram.types import CallbackQuery, Message

from ..services import media

logger = logging.getLogger(__name__)

# سقف طول کپشن تلگرام؛ صفحات بلندتر بی‌عکس (متن) رندر می‌شوند
CAPTION_LIMIT = 1024


async def safe_edit(call: CallbackQuery, text: str, reply_markup=None, **kwargs) -> None:
    """
    جایگزین امنِ call.message.edit_text.

    اگر پیام فعلی عکس‌دار باشد (کاربر از یک منوی تصویری آمده)، پیام حذف و متن تازه
    ارسال می‌شود؛ در غیر این صورت مثل edit_text معمولی ویرایش می‌شود. چون روی پیام
    متنی رفتارش معادل edit_text است، جایگزینی‌اش هیچ ریسک رفتاری ندارد.
    """
    msg = call.message
    if msg is None:
        return
    try:
        if msg.photo:
            # پیام عکس‌دار → نمی‌توان به متن ویرایش کرد؛ حذف و ارسال تازه
            try:
                await msg.delete()
            except Exception:  # noqa: BLE001 — حذف ممکن است شکست بخورد؛ مهم نیست
                pass
            await msg.answer(text, reply_markup=reply_markup, **kwargs)
        else:
            await msg.edit_text(text, reply_markup=reply_markup, **kwargs)
    except Exception as exc:  # noqa: BLE001 — خطای تلگرام نباید جریان بازی را قطع کند
        logger.warning("safe_edit failed: %s", exc)
        try:
            await msg.answer(text, reply_markup=reply_markup, **kwargs)
        except Exception:  # noqa: BLE001
            pass


async def show_menu(event, text: str, reply_markup=None, *, image_key: str) -> None:
    """
    یک منوی اصلی را با عکس تصادفیِ مخصوص همان صفحه رندر می‌کند.

    event: می‌تواند CallbackQuery (ناوبری داخل بازی) یا Message (ارسال تازه مثل /start) باشد.
    image_key: کلید صفحه (main/economy/...) که به دسته‌ی media با پیشوند ui_ نگاشت می‌شود.

    رفتار:
    - اگر عکس موجود بود و متن ≤ ۱۰۲۴ کاراکتر: عکس + کپشن + دکمه (هیبرید).
    - در غیر این صورت (عکس نبود یا متن بلند): متن ساده (برای کال‌بک با safe_edit، برای Message با answer).
    همه‌چیز در try/except؛ خطا نباید جریان را قطع کند.
    """
    is_call = isinstance(event, CallbackQuery)
    msg: Message | None = event.message if is_call else event

    photo = None
    upload_path = None
    if len(text) <= CAPTION_LIMIT:
        try:
            photo, upload_path = media._resolve_random_photo(f"ui_{image_key}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("show_menu resolve photo failed (%s): %s", image_key, exc)

    # مسیر بدون‌عکس: متن ساده
    if photo is None or msg is None:
        if is_call:
            await safe_edit(event, text, reply_markup=reply_markup)
        elif msg is not None:
            try:
                await msg.answer(text, reply_markup=reply_markup)
            except Exception as exc:  # noqa: BLE001
                logger.warning("show_menu text fallback failed: %s", exc)
        return

    # مسیر عکس‌دار: ارسال عکس تازه + حذف پیام قبلی (در ناوبری کال‌بک)
    try:
        sent = await msg.answer_photo(photo, caption=text, reply_markup=reply_markup)
        if upload_path is not None and sent.photo:
            media._append_cache(f"ui_{image_key}", sent.photo[-1].file_id, upload_path.name)
        if is_call:
            try:
                await msg.delete()
            except Exception:  # noqa: BLE001 — حذف پیام قبلی بحرانی نیست
                pass
    except Exception as exc:  # noqa: BLE001 — اگر ارسال عکس شکست خورد، به متن برگرد
        logger.warning("show_menu send photo failed (%s): %s", image_key, exc)
        if is_call:
            await safe_edit(event, text, reply_markup=reply_markup)
        else:
            try:
                await msg.answer(text, reply_markup=reply_markup)
            except Exception:  # noqa: BLE001
                pass
