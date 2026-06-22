"""
لایه‌ی دسترسی داده (Repository).
هر ماژول مجموعه‌ای از توابع CRUD برای یک دامنه فراهم می‌کند تا سرویس‌ها مستقیماً
با کوئری‌های SQLAlchemy درگیر نشوند.
"""

from . import (
    claims,
    cooldowns,
    countries,
    diplomacy,
    facilities,
    military,
    reserves,
    trade,
    users,
)

__all__ = [
    "claims",
    "cooldowns",
    "countries",
    "diplomacy",
    "facilities",
    "military",
    "reserves",
    "trade",
    "users",
]
