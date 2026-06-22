"""
کلاینت هوش مصنوعی: اتصال به Groq از طریق کتابخانه‌ی openai.
مدل gpt-oss-120b روی endpoint سازگار با openai گرو اجرا می‌شود.
"""

from __future__ import annotations

import json
import logging

from openai import AsyncOpenAI

from ...config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# کلاینت ناهمگام؛ base_url به سمت Groq تنظیم می‌شود تا روی همان رابط openai سوار شود
_client = AsyncOpenAI(
    api_key=settings.groq_api_key,
    base_url=settings.groq_base_url,
)


async def ask_ai(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> str:
    """
    ارسال یک پیام به مدل و دریافت پاسخ متنی.
    در صورت خطا، پیام خطای کوتاه فارسی برمی‌گرداند تا ربات از کار نیفتد.
    """
    try:
        response = await _client.chat.completions.create(
            model=settings.ai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens or settings.ai_max_tokens,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as exc:  # noqa: BLE001 — هر خطایی نباید ربات را متوقف کند
        logger.exception("AI request failed: %s", exc)
        return "⚠️ خطا در ارتباط با هوش مصنوعی. لطفاً بعداً دوباره تلاش کنید."


async def ask_ai_json(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.4,
    max_tokens: int | None = None,
) -> dict:
    """
    مثل ask_ai ولی خروجی را به‌صورت JSON می‌گیرد و parse می‌کند.
    برای سنجش‌های ساختاریافته (تلفات حمله، زمان سفر و ...) استفاده می‌شود.
    در صورت خطای parse، دیکشنری خالی برمی‌گرداند.
    """
    try:
        response = await _client.chat.completions.create(
            model=settings.ai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens or settings.ai_max_tokens,
            response_format={"type": "json_object"},
        )
        content = (response.choices[0].message.content or "{}").strip()
        return json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning("AI JSON parse failed: %s", exc)
        return {}
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI JSON request failed: %s", exc)
        return {}
