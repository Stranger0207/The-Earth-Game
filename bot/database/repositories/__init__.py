"""
لایه‌ی دسترسی داده (Repository).
هر ماژول مجموعه‌ای از توابع CRUD برای یک دامنه فراهم می‌کند تا سرویس‌ها مستقیماً
با کوئری‌های SQLAlchemy درگیر نشوند.
"""

from . import (
    alliances,
    bot_state,
    claims,
    cooldowns,
    countries,
    diplomacy,
    facilities,
    investments,
    letters,
    military,
    reserves,
    tariff,
    trade,
    users,
)

__all__ = [
    "alliances",
    "bot_state",
    "claims",
    "cooldowns",
    "countries",
    "diplomacy",
    "facilities",
    "investments",
    "letters",
    "military",
    "reserves",
    "tariff",
    "trade",
    "users",
]
