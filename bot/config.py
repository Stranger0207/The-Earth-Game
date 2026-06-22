"""
خواندن تنظیمات از فایل .env با استفاده از pydantic-settings.
همه‌ی متغیرهای ربات اینجا تعریف می‌شوند تا در کل پروژه از یک منبع واحد خوانده شوند.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_id_list(value: str | list[int] | None) -> list[int]:
    """رشته‌ی "1,2,3" یا لیست را به لیستی از آی‌دی‌های عددی تبدیل می‌کند."""
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [int(v) for v in value]
    return [int(part.strip()) for part in str(value).split(",") if part.strip()]


class Settings(BaseSettings):
    """تنظیمات کلی ربات؛ مقادیر از فایل .env خوانده می‌شوند."""

    # --- تلگرام ---
    bot_token: str

    # --- دیتابیس ---
    database_url: str

    # --- Groq / AI ---
    groq_api_key: str
    groq_base_url: str = "https://api.groq.com/openai/v1"
    ai_model: str = "openai/gpt-oss-120b"
    ai_max_tokens: int = 1500

    # --- نقش‌ها ---
    owner_ids: list[int] = []
    admin_ids: list[int] = []

    # --- کانال‌ها و گروه‌ها ---
    news_military_channel_id: int | None = None
    news_diplomacy_channel_id: int | None = None
    news_economy_channel_id: int | None = None
    wto_channel_id: int | None = None
    phone_group_id: int | None = None
    log_group_id: int | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # تبدیل رشته‌ی جداشده با کاما به لیست آی‌دی‌ها
    @field_validator("owner_ids", "admin_ids", mode="before")
    @classmethod
    def _validate_id_lists(cls, value):  # noqa: D401
        return _parse_id_list(value)

    def is_owner(self, user_id: int) -> bool:
        """آیا این کاربر مالک بازی است؟"""
        return user_id in self.owner_ids

    def is_admin(self, user_id: int) -> bool:
        """آیا این کاربر مدیر است؟ (مالک‌ها هم مدیر محسوب می‌شوند)"""
        return user_id in self.admin_ids or user_id in self.owner_ids


@lru_cache
def get_settings() -> Settings:
    """نمونه‌ی کش‌شده‌ی تنظیمات؛ فقط یک‌بار از env خوانده می‌شود."""
    return Settings()  # type: ignore[call-arg]
