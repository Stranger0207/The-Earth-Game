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
    commander_intel,
    commanders,
    cooldowns,
    countries,
    diplomacy,
    drills,
    facilities,
    governance,
    investments,
    letters,
    military,
    news_fingerprints,
    nuclear,
    operations,
    patrols,
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
    "commander_intel",
    "commanders",
    "cooldowns",
    "countries",
    "diplomacy",
    "drills",
    "facilities",
    "governance",
    "investments",
    "letters",
    "military",
    "news_fingerprints",
    "nuclear",
    "operations",
    "patrols",
    "reserves",
    "tariff",
    "trade",
    "users",
]
