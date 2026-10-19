"""
سرویس تحلیل هوشمند و نگارش گزارش دیپلماتیک سخنرانی‌های مجمع عمومی سازمان ملل با AI.
"""

from __future__ import annotations

import logging
from aiogram import Bot

from ..config import get_settings
from ..enums import NewsCategory
from .ai.client import ask_ai
from .ai.prompts import general_assembly_speech_prompt
from .media import send_photo_news
from .news_service import publish_news

logger = logging.getLogger(__name__)
settings = get_settings()


async def analyze_and_publish_speech(
    bot: Bot,
    country_fa: str,
    president_name: str,
    speech_transcript: str,
    is_vip: bool = False,
) -> bool:
    """
    آنالیز متن و پیام‌های سخنرانی ایرادشده در مجمع عمومی توسط AI و انتشار در کانال دیپلماسی.
    فیلتر هوشمند ضداسپم: حداقل ۵۰ کاراکتر یا کشورهای VIP.
    سقف توکن بالا (max_tokens=2000) برای جلوگیری از بریده‌شدن گزارش.
    """
    clean_text = (speech_transcript or "").strip()
    if not clean_text:
        return False

    # فیلتر ارزشمندی خبری
    if len(clean_text) < 50 and not is_vip:
        logger.info("Speech by %s too short for news broadcast (%d chars).", country_fa, len(clean_text))
        return False

    system_prompt = general_assembly_speech_prompt(country_fa, president_name)
    user_prompt = f"متن کامل نطق و توضیحات رهبر کشور {country_fa} در صحن مجمع عمومی:\n\n{clean_text}"

    # فراخوانی هوش مصنوعی با سقف توکن ۲۰۰۰ جهت تضمین کامل بودن گزارش
    analysis_text = await ask_ai(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.6,
        max_tokens=2000,
    )

    if not analysis_text or "⚠️ خطا" in analysis_text:
        # در صورت قطعی موقت Groq، خبر کوتاه با سربرگ استاندارد ارسال می‌شود تا جریان متوقف نشود
        analysis_text = (
            f"🏛 <b>نطق رسمی در هفتاد و نهمین مجمع عمومی سازمان ملل متحد (نیویورک):</b>\n\n"
            f"جناب آقای {president_name}، رهبر محترم کشور {country_fa} در صحن علنی مجمع عمومی سازمان ملل به ایراد سخنرانی "
            f"پیرامون مواضع بین‌المللی و راهبردهای کشور خود پرداختند.\n\n"
            f"📜 <b>خلاصه مواضع:</b>\n{clean_text[:600]}..."
        )

    # ارسال خبر عکس‌دار به کانال دیپلماسی
    caption = f"🇺🇳 <b>گزارش اختصاصی از صحن علنی مجمع عمومی سازمان ملل متحد — نیویورک</b>\n\n{analysis_text}"
    sent = await send_photo_news(
        bot=bot,
        category=NewsCategory.DIPLOMACY,
        caption=caption,
        category_photo="meeting",
    )
    if not sent:
        await publish_news(bot, NewsCategory.DIPLOMACY, caption)

    return True
