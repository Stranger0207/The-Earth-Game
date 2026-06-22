"""
سنجش‌گرهای هوش مصنوعی: ترکیب context + پرامپت + کلاینت برای داوری رویدادهای بازی.
هر تابع داده‌ی کشور را از DB می‌گیرد، به مدل می‌دهد و نتیجه‌ی ساختاریافته برمی‌گرداند.
"""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from . import prompts
from .client import ask_ai, ask_ai_json
from .context import build_country_context


async def interpret_command(
    session: AsyncSession, country_id: int, command_text: str
) -> dict:
    """تفسیر دستور آزاد بازیکن و سنجش منطقی‌بودن آن."""
    context = await build_country_context(session, country_id)
    user_prompt = (
        f"context کشور:\n{json.dumps(context, ensure_ascii=False)}\n\n"
        f"دستور بازیکن:\n{command_text}"
    )
    return await ask_ai_json(prompts.command_interpreter_prompt(), user_prompt)


async def evaluate_attack(
    session: AsyncSession,
    attacker_id: int,
    defender_id: int,
    attack_type_fa: str,
    payload_text: str,
) -> dict:
    """سنجش یک حمله: سوخت لازم، تلفات دو طرف، نتیجه و زمان اعلام."""
    attacker_ctx = await build_country_context(session, attacker_id)
    defender_ctx = await build_country_context(session, defender_id)
    user_prompt = (
        f"نوع حمله: {attack_type_fa}\n\n"
        f"کشور مهاجم:\n{json.dumps(attacker_ctx, ensure_ascii=False)}\n\n"
        f"کشور مدافع:\n{json.dumps(defender_ctx, ensure_ascii=False)}\n\n"
        f"شرح حمله و تجهیزات انتخابی مهاجم:\n{payload_text}"
    )
    return await ask_ai_json(prompts.attack_evaluator_prompt(), user_prompt)


async def estimate_travel_time(
    origin_name: str, destination_name: str
) -> dict:
    """تخمین زمان سفر برای دیدار حضوری."""
    user_prompt = (
        f"کشور مبدأ: {origin_name}\nکشور مقصد: {destination_name}"
    )
    return await ask_ai_json(prompts.travel_time_prompt(), user_prompt)


async def estimate_shipping_time(
    seller_name: str, buyer_name: str, resource_fa: str, amount: float
) -> dict:
    """تخمین زمان رسیدن محموله‌ی WTO."""
    user_prompt = (
        f"کشور فروشنده: {seller_name}\n"
        f"کشور خریدار: {buyer_name}\n"
        f"محموله: {amount} واحد {resource_fa}"
    )
    return await ask_ai_json(prompts.shipping_time_prompt(), user_prompt)


async def get_advice(
    session: AsyncSession, country_id: int, domain_fa: str, question: str
) -> str:
    """دریافت مشاوره از مشاور AI در یک دامنه."""
    context = await build_country_context(session, country_id)
    user_prompt = (
        f"وضعیت کشور:\n{json.dumps(context, ensure_ascii=False)}\n\n"
        f"پرسش رئیس‌جمهور:\n{question}"
    )
    return await ask_ai(prompts.advisor_prompt(domain_fa), user_prompt)


async def write_news(
    category_fa: str, facts: str, president_name: str | None = None
) -> str:
    """تولید متن خبر رسمی بر اساس واقعیت‌های رویداد."""
    user_prompt = f"واقعیت‌های رویداد:\n{facts}"
    if president_name:
        user_prompt += f"\n\nنام رئیس‌جمهور مرتبط: {president_name}"
    return await ask_ai(prompts.news_writer_prompt(category_fa), user_prompt, temperature=0.8)
