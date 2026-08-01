"""
پکیج موتور اخبار نظامی (v1.10.6).

مشکلی که حل می‌کند: نسخه‌ی قبلی یک پرامپت ثابت با ۴ فاز ثابت داشت و
خبرها به‌مرور تکراری می‌شدند.

راهکار سه‌لایه:
- `archetypes`: ۸ سبک متفاوت نوشتن خبر که چرخشی انتخاب می‌شوند
- `dedup`: اثرانگشت n-gram و سنجش شباهت با اخبار اخیر
- `facts`: تبدیل اعداد موتور نبرد به واقعیت‌های خوانا + قالب‌های پشتیبان
- `imagery`: ساخت پرامپت تصویری برای تولید عکس اختصاصی هر خبر
- `publisher`: فیلتر کانال (VIP + شدت) و زنجیره‌ی عکس Gemini → محلی → متن
- `military_news`: ترکیب همه‌ی این‌ها و تولید خبر نهایی
"""

from .archetypes import guide_for, pick_archetype
from .dedup import SIMILARITY_THRESHOLD, build_shingles, is_repetitive, max_similarity, text_hash
from .facts import facts_to_text, fallback_news, phase_plan
from .imagery import build_image_prompt, media_category_for
from .military_news import write_phase_news
from .publisher import deliver_news, deliver_operation_news, should_publish_to_channel

__all__ = [
    "SIMILARITY_THRESHOLD",
    "build_image_prompt",
    "build_shingles",
    "deliver_news",
    "deliver_operation_news",
    "facts_to_text",
    "fallback_news",
    "guide_for",
    "is_repetitive",
    "max_similarity",
    "media_category_for",
    "phase_plan",
    "pick_archetype",
    "should_publish_to_channel",
    "text_hash",
    "write_phase_news",
]
