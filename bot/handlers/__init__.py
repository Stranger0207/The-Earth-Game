"""ثبت همه‌ی روترهای ربات روی دیسپچر."""

from aiogram import Dispatcher

from . import (
    admin,
    advisor,
    claim,
    diplomacy,
    economy,
    godmode,
    menu,
    military,
    start,
)


def register_all_routers(dp: Dispatcher) -> None:
    """
    ترتیب ثبت مهم است: روترهای اختصاصی‌تر (start/claim/admin) زودتر،
    سپس منو و بخش‌های بازی.
    """
    dp.include_router(start.router)
    dp.include_router(claim.router)
    dp.include_router(admin.router)
    dp.include_router(godmode.router)
    dp.include_router(menu.router)
    dp.include_router(economy.router)
    dp.include_router(diplomacy.router)
    dp.include_router(military.router)
    dp.include_router(advisor.router)
