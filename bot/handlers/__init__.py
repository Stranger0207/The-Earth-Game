"""ثبت همه‌ی روترهای ربات روی دیسپچر."""

from aiogram import Dispatcher

from . import (
    admin,
    admin_roles,
    advisor,
    alliance,
    auction,
    bank,
    claim,
    command_center,
    deployment,
    diplomacy,
    economic_projects,
    economy,
    god_locks,
    godmode,
    governance,
    interception,
    investment,
    joint,
    mail,
    maintenance,
    menu,
    military,
    military_base,
    military_roles,
    nuclear,
    satellite,
    security_roles,
    start,
    twitter,
)


def register_all_routers(dp: Dispatcher) -> None:
    """
    ترتیب ثبت مهم است: روترهای اختصاصی‌تر (start/claim/admin) زودتر،
    سپس منو و بخش‌های بازی.
    """
    dp.include_router(start.router)
    dp.include_router(claim.router)
    dp.include_router(admin.router)
    dp.include_router(admin_roles.router)
    dp.include_router(maintenance.router)
    dp.include_router(godmode.router)
    dp.include_router(god_locks.router)
    dp.include_router(menu.router)
    dp.include_router(economy.router)
    dp.include_router(economic_projects.router)
    dp.include_router(auction.router)
    dp.include_router(bank.router)
    dp.include_router(investment.router)
    dp.include_router(joint.router)
    dp.include_router(governance.router)
    dp.include_router(diplomacy.router)
    dp.include_router(mail.router)
    dp.include_router(alliance.router)
    dp.include_router(twitter.router)
    dp.include_router(command_center.router)
    dp.include_router(interception.router)
    dp.include_router(military.router)
    dp.include_router(military_roles.router)
    dp.include_router(security_roles.router)
    dp.include_router(military_base.router)
    dp.include_router(satellite.router)
    dp.include_router(nuclear.router)
    dp.include_router(deployment.router)
    dp.include_router(advisor.router)

