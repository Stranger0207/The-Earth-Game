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

    # --- Google Gemini (تولید عکس اخبار — v1.10.6) ---
    # کلید را از https://aistudio.google.com/apikey بگیرید و در .env بگذارید.
    # اگر خالی بماند، ربات خودکار از بانک عکس محلی استفاده می‌کند و هیچ خطایی نمی‌دهد.
    gemini_api_key: str = ""
    gemini_image_model: str = "gemini-3.1-flash-image"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    # سقف تولید عکس در هر ۲۴ ساعت (کنترل هزینه)
    gemini_image_daily_limit: int = 50
    # مهلت هر درخواست تولید عکس (ثانیه)
    gemini_timeout_seconds: int = 60

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
    tweet_channel_id: int = -1004317808331

    # --- گروه‌های ۷گانه مدیریتی و بررسی (آپدیت شماره ۱۰) ---
    sanction_bill_group_id: int = -1004474739499  # گروه ۱: تحریم و لایحه
    role_econ_group_id: int = -1004359181892      # گروه ۳: بررسی رول اقتصادی
    role_attack_group_id: int = -1004424329237    # گروه ۴: بررسی رول حمله
    role_sabotage_group_id: int = -1004317304087  # گروه ۵: بررسی رول خرابکاری
    role_security_group_id: int = -1004317826815  # گروه ۶: بررسی رول امنیتی
    payment_group_id: int = -1004337037351        # گروه ۷: پرداختی‌ها (فیش‌های واریزی)

    # --- مینی‌اپ رادار زنده جهان (Live Strategic Radar) ---
    webapp_port: int = 8080
    webapp_base_url: str = ""                     # آدرس عمومی مینی‌اپ (مثلاً https://...ngrok-free.app)

    # --- جوین اجباری و لینک فولدر بازی ---
    force_join_enabled: bool = False
    force_join_chat_id: str | None = None
    force_join_invite_link: str | None = None
    game_folder_link: str | None = None

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
        """آیا این کاربر مالک بازی است؟ (مالک‌های استاتیک در env یا مالکان ثبت‌شده پویا)"""
        return user_id in self.owner_ids or user_id in _dynamic_owner_ids

    def is_admin(self, user_id: int) -> bool:
        """آیا این کاربر مدیر است؟ (مالک‌ها هم مدیر محسوب می‌شوند)"""
        return (
            user_id in self.admin_ids
            or user_id in self.owner_ids
            or user_id in _dynamic_admin_ids
            or user_id in _dynamic_owner_ids
        )

    def is_static_owner(self, user_id: int) -> bool:
        """آیا این کاربر مالک اولیه/ثابت در env است؟ (غیرقابل خلع)"""
        return user_id in self.owner_ids


# --- مدیریت پویای اعضای تیم در حافظه (همگام با جدول users) ---
_dynamic_admin_ids: set[int] = set()
_dynamic_owner_ids: set[int] = set()


def add_dynamic_admin(uid: int) -> None:
    """افزودن آیدی مدیر پویا به حافظه."""
    _dynamic_admin_ids.add(uid)


def remove_dynamic_admin(uid: int) -> None:
    """حذف آیدی مدیر پویا از حافظه."""
    _dynamic_admin_ids.discard(uid)


def add_dynamic_owner(uid: int) -> None:
    """افزودن آیدی مالک پویا به حافظه."""
    _dynamic_owner_ids.add(uid)


def remove_dynamic_owner(uid: int) -> None:
    """حذف آیدی مالک پویا از حافظه."""
    _dynamic_owner_ids.discard(uid)


def set_dynamic_team(
    admin_ids: set[int] | list[int], owner_ids: set[int] | list[int]
) -> None:
    """بازنشانی کامل کش اعضای پویا (هنگام بالا آمدن ربات از دیتابیس)."""
    global _dynamic_admin_ids, _dynamic_owner_ids
    _dynamic_admin_ids = set(admin_ids)
    _dynamic_owner_ids = set(owner_ids)


def get_dynamic_admins() -> set[int]:
    """دریافت مجموعه‌ی مدیران پویا."""
    return set(_dynamic_admin_ids)


def get_dynamic_owners() -> set[int]:
    """دریافت مجموعه‌ی مالکان پویا."""
    return set(_dynamic_owner_ids)


@lru_cache
def get_settings() -> Settings:
    """نمونه‌ی کش‌شده‌ی تنظیمات؛ فقط یک‌بار از env خوانده می‌شود."""
    return Settings()  # type: ignore[call-arg]

