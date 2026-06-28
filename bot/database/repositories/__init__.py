"""
لایه‌ی دسترسی داده (Repository).
هر ماژول مجموعه‌ای از توابع CRUD برای یک دامنه فراهم می‌کند تا سرویس‌ها مستقیماً
با کوئری‌های SQLAlchemy درگیر نشوند.
"""

from . import (
    alliances,
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
