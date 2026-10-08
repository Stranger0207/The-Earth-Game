"""
لایه‌ی دسترسی داده (Repository).
هر ماژول مجموعه‌ای از توابع CRUD برای یک دامنه فراهم می‌کند تا سرویس‌ها مستقیماً
با کوئری‌های SQLAlchemy درگیر نشوند.
"""

from . import (
    alliances,
    auctions,
    bank_loans,
    bot_state,
    claims,
    commanders,
    cooldowns,
    countries,
    diplomacy,
    facilities,
    governance,
    investments,
    letters,
    military,
    nuclear,
    reserves,
    tariff,
    trade,
    users,
)

__all__ = [
    "alliances",
    "auctions",
    "bank_loans",
    "bot_state",
    "claims",
    "commanders",
    "cooldowns",
    "countries",
    "diplomacy",
    "facilities",
    "governance",
    "investments",
    "letters",
    "military",
    "nuclear",
    "reserves",
    "tariff",
    "trade",
    "users",
]
