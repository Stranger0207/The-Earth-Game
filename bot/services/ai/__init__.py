"""هسته‌ی هوش مصنوعی: اتصال به Groq، ساخت context و سنجش‌ها."""

from .client import ask_ai, ask_ai_json
from .context import build_country_context

__all__ = ["ask_ai", "ask_ai_json", "build_country_context"]
